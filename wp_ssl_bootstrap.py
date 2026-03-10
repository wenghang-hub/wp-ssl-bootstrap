#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: MIT
#
# Copyright (c) 2024-2025 WP-SSL-Bootstrap Contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
=============================================================================
WP-SSL-Bootstrap: 高可用建站引擎 (V3.0.15)
适应平台: Alibaba Cloud Linux 3 / CentOS 7-9 / RHEL / Ubuntu / Debian
=============================================================================

【核心功能】
1. 智能环境探针：动态识别包管理器、Nginx 用户、PHP-FPM 服务与 socket、数据库服务。
2. 数据库安全初始化：auth_socket/unix_socket 插件自适应，Root 凭据不暴露于进程列表。
3. 多源容灾下载：官方中文源与全球主源 fallback，SHA256 严格校验，下载前磁盘预检。
4. 严格文件权限与 SELinux 处理：最小权限原则 + SELinux 布尔值自动配置。
5. 零停机 SSL 签发与多级 CA 容灾：Let's Encrypt → BuyPass Go，
   certbot 错误分类（致命/可重试），非 CA 侧错误立即熔断跳出。
6. 三级部署预检：DNS 解析验证 → HTTP challenge 路径可达性 → 站点健康检查。
7. WP-CLI 可选增强：自动安装 WP-CLI，提供下载兜底 / verify-checksums 深度校验 /
   is-installed 安装状态检测。WP-CLI 不可用时所有功能均有完整回退路径。
8. Systemd 定时续期：TimeoutStartSec 防卡死，--cert-name 精准续期。

【安全机制】
1. 密码学安全：secrets 模块生成凭据与 Salts。
2. 零命令行泄露：数据库密码通过 --defaults-extra-file 临时文件传递。
3. 零 SQL 注入：严格字符白名单校验。
4. 原子写入：所有配置文件写入均带备份与回滚能力。
5. 非零退出码：所有失败路径正确返回非零退出码。

【借鉴自 sooth_monitor.py 的工程模式】
· CmdResult 错误分类体系：命令执行结果区分 SUCCESS/RETRYABLE/TIMEOUT/PERMISSION/FATAL，
  替代简单 bool，通过 __bool__ 保持向后兼容，调用方按需获取详细错误类型。
· 磁盘空间预检：下载和解压前检查目标分区可用空间，避免磁盘写满导致半残状态。
· certbot 错误熔断：对 certbot 输出做错误分类，非 CA 侧致命错误（端口占用/DNS 未解析/
  webroot 不可达）立即跳出 CA 循环，避免无意义重试。
· 信号清理防递归：cleanup_and_exit 末尾恢复信号为 SIG_DFL，防止清理过程中再次
  收到信号导致递归调用。

【兼容性】
--domain / --email 支持命令行参数与环境变量 (WP_DOMAIN / WP_EMAIL) 双入口。

"""

__version__ = "3.0.15"

import os
import sys
import fcntl
import signal
import subprocess
import argparse
import logging
import tempfile
import shutil
import string
import re
import base64
import secrets
import hashlib
import pwd
import glob
import stat
import time
import traceback
import concurrent.futures
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# 多语言支持 (V3.0.5)
# ---------------------------------------------------------------------------
# 优先级(高→低): --lang CLI 参数 > 持久配置文件 > WP_LANG 环境变量
#              > LANG > LC_ALL > LANGUAGE > 默认英文
# CLI 示例  : sudo python3 wp_ssl_bootstrap.py --lang en deploy ...
#   首次指定后，语言偏好自动写入 /root/.wp_ssl_lang，后续无需重复指定。
# 环境变量  : WP_LANG=en  强制英文；WP_LANG=zh  强制中文
# ---------------------------------------------------------------------------
_LANG_CONFIG_FILE = Path("/root/.wp_ssl_lang")


def _write_lang_file(content: str) -> None:
    """Atomically write language config with 0600 permissions.

    Falls back to direct (non-atomic) write if rename fails,
    ensuring the language preference is never silently lost.
    """
    _bytes = content.encode("utf-8")
    tmp = _LANG_CONFIG_FILE.with_name(_LANG_CONFIG_FILE.name + ".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, _bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(_LANG_CONFIG_FILE))
        return  # atomic write succeeded
    except OSError:
        pass
    finally:
        # Always clean up tmp (no-op if os.replace already consumed it)
        # [V3.0.9] S1: missing_ok=True 需要 Python 3.8+; 改写以兼容 3.6
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
    # Fallback: direct write (non-atomic but functional)
    try:
        fd = os.open(str(_LANG_CONFIG_FILE),
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, _bytes)
        finally:
            os.close(fd)
    except OSError:
        pass


def _env_lang() -> str:
    """Return language from environment variables only (ignores config file)."""
    raw = (
        os.environ.get("WP_LANG", "")
        or os.environ.get("LANG", "")
        or os.environ.get("LC_ALL", "")
        or os.environ.get("LANGUAGE", "")
    ).lower()
    return "zh" if raw.startswith("zh") else "en"


def _saved_lang():  # -> str | None
    """Return the language saved in the config file, or None if absent/invalid."""
    try:
        if _LANG_CONFIG_FILE.exists():
            val = _LANG_CONFIG_FILE.read_text().strip().lower()
            if val in ("zh", "en"):
                return val
    except OSError:
        pass
    return None


def _detect_lang() -> str:
    """Detect display language.

    Priority (highest first):
      1. /root/.wp_ssl_lang  (written by --lang on first use)
      2. WP_LANG / LANG / LC_ALL / LANGUAGE env vars
      3. Default: 'en'
    """
    saved = _saved_lang()
    return saved if saved is not None else _env_lang()


def _prompt_lang_change() -> None:
    """Prompt the user when the environment language differs from the saved preference.

    Called once per run after the root check.  Silent when:
      - No config file exists yet (nothing to compare).
      - Saved and env languages already match.
      - WP_LANG_NOCHECK=1 is set (for scripts/cron).
      - stdin is not a tty (piped / non-interactive).
      - --lang was already handled by the pre-scanner (_LANG was updated).

    User choices (bilingual prompt, always readable regardless of _LANG):
      1 / Enter  Keep the saved language (no change).
      2          Switch to the environment language and persist.
      3          Type a language code manually (zh / en).
      zh / en    Accepted directly as shorthand for either option.
    """
    global _LANG

    saved = _saved_lang()
    if saved is None:
        return  # no config file — nothing to compare

    # If --lang was already applied by the pre-scanner, _LANG was updated and
    # persisted; we just need to verify the file now matches _LANG.
    if _LANG == saved and _env_lang() == saved:
        return  # everything in sync

    env = _env_lang()

    # If --lang was supplied, the pre-scanner already updated _LANG.
    # saved() still reflects the OLD file until the write, so re-check.
    if _LANG != saved:
        # --lang already changed _LANG in pre-scan; config will be written there.
        return

    if env == saved:
        return  # no mismatch

    if os.environ.get("WP_LANG_NOCHECK", "").strip() == "1":
        return  # caller opted out

    if not sys.stdin.isatty():
        return  # non-interactive — keep saved silently

    # ── Bilingual prompt (always print both zh + en lines) ───────────────
    zh_notice  = (
        f"\n⚠️  [语言变更提示] 已保存语言: {saved.upper()}，"
        f"当前环境语言: {env.upper()}"
    )
    en_notice  = (
        f"    [Language change] Saved: {saved.upper()}, "
        f"env: {env.upper()}"
    )
    print(zh_notice)
    print(en_notice)
    print(f"  [1] 保留 {saved.upper()} / Keep {saved.upper()} (Enter)")
    print(f"  [2] 切换至 {env.upper()} / Switch to {env.upper()}")
    print( "  [3] 手动输入 / Enter manually (zh/en)")
    print()

    try:
        choice = input(
            "选择 / Choose [1/2/3 or zh/en, Enter=keep]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice in ("", "1"):
        return  # keep saved — already persisted

    if choice == "2":
        chosen = env
    elif choice in ("zh", "en"):
        chosen = choice
    else:
        # Option 3 or unrecognised — ask for explicit code
        try:
            code = input("语言代码 / Language code (zh/en): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if code not in ("zh", "en"):
            _code_display = code or "(empty)"
            print(f"⚠️  无效代码 / Invalid code: '{_code_display}'，"
                  f"保持当前语言 / keeping {saved.upper()}")
            return
        chosen = code

    _LANG = chosen
    _write_lang_file(chosen)
    print(f"✅  语言已切换 / Language switched → {chosen.upper()}")


_LANG: str = _detect_lang()

_MESSAGES: dict = {
    # ── SiteConfig validation (print) ──────────────────────────────────────
    "err_domain_fmt": {
        "zh": "❌ 严重错误：域名格式不合法 ({domain})",
        "en": "❌ Fatal: Invalid domain format ({domain})",
    },
    "err_domain_len": {
        "zh": "❌ 严重错误：域名长度超出 DNS 规范上限 253 字符 (当前 {n})",
        "en": "❌ Fatal: Domain exceeds DNS 253-char limit (current: {n})",
    },
    "err_email_fmt": {
        "zh": "❌ 严重错误：邮箱格式不合法 ({email})",
        "en": "❌ Fatal: Invalid email format ({email})",
    },
    "err_dbhost_fmt": {
        "zh": "❌ 严重错误：数据库主机地址格式不合法 ({host})",
        "en": "❌ Fatal: Invalid database host format ({host})",
    },
    "warn_timeout_env": {
        "zh": "⚠️  环境变量 WP_DB_WAIT_TIMEOUT 不是合法整数 (\'{val}\')，已忽略。",
        "en": "⚠️  WP_DB_WAIT_TIMEOUT is not a valid integer (\'{val}\'), ignored.",
    },
    "err_timeout_val": {
        "zh": "❌ 严重错误：--db-wait-timeout 必须为正整数 (当前值: {val})",
        "en": "❌ Fatal: --db-wait-timeout must be a positive integer (got: {val})",
    },
    # ── Root privilege ──────────────────────────────────────────────────────
    "err_root_required": {
        "zh": "❌ 错误：此脚本必须以 root 权限运行。",
        "en": "❌ Error: This script must be run as root.",
    },
    # ── Deploy success (print) ──────────────────────────────────────────────
    "deploy_success": {
        "zh": "🎉 部署成功！",
        "en": "🎉 Deployment successful!",
    },
    "deploy_url": {
        "zh": "🌍 网站地址: https://{domain}",
        "en": "🌍 Site URL: https://{domain}",
    },
    "deploy_cred": {
        "zh": "📄 凭据文件 (权限 600): {path}",
        "en": "📄 Credentials file (mode 600): {path}",
    },
    # ── Backup (print) ──────────────────────────────────────────────────────
    "backup_done": {
        "zh": "📦 备份完成: {path}",
        "en": "📦 Backup complete: {path}",
    },
    "backup_size": {
        "zh": "   总大小: {mb:.1f}MB",
        "en": "   Total size: {mb:.1f}MB",
    },
    # [V3.0.9] B7 / S5 新增消息
    "ok_extra_backup": {
        "zh": "📄 附加配置已备份: {path}",
        "en": "📄 Extra config backed up: {path}",
    },
    "warn_extra_backup_fail": {
        "zh": "⚠️  附加配置备份失败 ({name}): {e}",
        "en": "⚠️  Failed to back up extra config ({name}): {e}",
    },
    "info_extra_conf_restored": {
        "zh": "  已恢复附加配置: {name}",
        "en": "  Restored extra config: {name}",
    },
    "warn_extra_conf_restore_fail": {
        "zh": "  恢复附加配置失败 ({name}): {e}",
        "en": "  Failed to restore extra config ({name}): {e}",
    },
    "err_escape_control_char": {
        "zh": "安全拦截：凭据字符串包含非法的系统控制字符！",
        "en": "Security block: credential string contains illegal control characters!",
    },
    "err_wpcli_unavailable": {
        "zh": "WP-CLI 不可用",
        "en": "WP-CLI is not available",
    },
    "err_certbot_lock": {
        "zh": "无法获取 Certbot 并发锁: {e}",
        "en": "Failed to acquire Certbot concurrency lock: {e}",
    },
    "warn_aw_bak_cleanup_fail": {
        "zh": "⚠️  无法清理 .aw_bak 文件 {path}: {e}（原子写入已成功，请手动检查）",
        "en": "⚠️  Could not clean up .aw_bak {path}: {e} (atomic write succeeded; please inspect manually)",
    },
    # ── show_status (print) ─────────────────────────────────────────────────
    "status_header": {
        "zh": "\n===== [{domain}] 站点状态 =====\n",
        "en": "\n===== [{domain}] Site Status =====\n",
    },
    "status_ssl": {
        "zh": "🔒 SSL 证书: {info}",
        "en": "🔒 SSL Certificate: {info}",
    },
    "status_ssl_expiry_warn": {
        "zh": "   ⚠️  证书将在 30 天内到期！",
        "en": "   ⚠️  Certificate expires within 30 days!",
    },
    "status_ssl_unreadable": {
        "zh": "🔒 SSL 证书: 无法读取",
        "en": "🔒 SSL Certificate: Unable to read",
    },
    "status_ssl_missing": {
        "zh": "🔒 SSL 证书: 未找到",
        "en": "🔒 SSL Certificate: Not found",
    },
    "status_external_db": {
        "zh": "ℹ️  数据库: 外置 ({host})，跳过本地服务检查",
        "en": "ℹ️  Database: External ({host}), skipping local service check",
    },
    "status_svc_unknown": {
        "zh": "❓ {label} ({name}): 未知",
        "en": "❓ {label} ({name}): unknown",
    },
    "status_timer": {
        "zh": "{icon} 续期定时器 ({name}): {status}",
        "en": "{icon} Renewal timer ({name}): {status}",
    },
    "status_timer_unknown": {
        "zh": "❓ 续期定时器 ({name}): 未知",
        "en": "❓ Renewal timer ({name}): unknown",
    },
    "status_disk": {
        "zh": "{icon} Webroot 磁盘可用: {mb}MB ({path})",
        "en": "{icon} Webroot disk free: {mb}MB ({path})",
    },
    # ── Phase banners ───────────────────────────────────────────────────────
    "phase1": {
        "zh": "===== 阶段一：系统依赖安装与站点部署 =====",
        "en": "===== Stage 1: System Dependencies & WordPress Deployment =====",
    },
    "phase2": {
        "zh": "===== 阶段二：配置 Nginx ACME 验证通道 =====",
        "en": "===== Stage 2: Configure Nginx ACME Challenge Channel =====",
    },
    "phase3": {
        "zh": "===== 阶段三：申请 SSL 证书 =====",
        "en": "===== Stage 3: Obtain SSL Certificate =====",
    },
    "phase4": {
        "zh": "===== 阶段四：挂载 HTTPS 生产配置 =====",
        "en": "===== Stage 4: Apply HTTPS Production Config =====",
    },
    "phase5": {
        "zh": "===== 阶段五：配置 Systemd 定时续期 =====",
        "en": "===== Stage 5: Configure Systemd Auto-Renewal =====",
    },
    "phase_f2b": {
        "zh": "===== 配置 Fail2Ban WordPress 防护 =====",
        "en": "===== Configure Fail2Ban WordPress Protection =====",
    },
    # ── logging.error ───────────────────────────────────────────────────────
    "err_no_pkg_mgr": {
        "zh": "无法识别包管理器，系统不支持自动化装配。",
        "en": "Cannot detect package manager; automated setup is not supported on this OS.",
    },
    "err_disk_low": {
        "zh": "❌ 磁盘空间不足 ({label})：{path} 所在分区仅剩 {free}MB，需要 {need}MB。",
        "en": "❌ Insufficient disk space ({label}): {path} has only {free}MB free, need {need}MB.",
    },
    "err_lock_global": {
        "zh": "❌ 全局进程冲突：另一个部署任务正在运行，请等待其完成。",
        "en": "❌ Global lock conflict: another deploy task is running, please wait.",
    },
    "err_lock_domain": {
        "zh": "进程冲突：针对 {domain} 的部署实例正在运行。",
        "en": "Process conflict: a deploy instance for {domain} is already running.",
    },
    "err_cmd_failed": {
        "zh": "命令失败 [{cmd}] (分类: {code}):\n{stderr}",
        "en": "Command failed [{cmd}] (category: {code}):\n{stderr}",
    },
    "err_cmd_timeout": {
        "zh": "执行超时: {cmd}",
        "en": "Execution timed out: {cmd}",
    },
    "err_cmd_exception": {
        "zh": "系统异常: {e}",
        "en": "System exception: {e}",
    },
    "err_sql_pipe": {
        "zh": "SQL 管道失败:\n{err}",
        "en": "SQL pipe failed:\n{err}",
    },
    "err_sql_timeout": {
        "zh": "SQL 执行超时 ({t}s)，mysql 可能无响应。",
        "en": "SQL execution timed out ({t}s); mysql may be unresponsive.",
    },
    "err_sql_exception": {
        "zh": "SQL 异常: {e}",
        "en": "SQL exception: {e}",
    },
    "err_atomic_write": {
        "zh": "原子写入 {path} 失败: {e}\n{tb}",
        "en": "Atomic write to {path} failed: {e}\n{tb}",
    },
    "err_safe_write": {
        "zh": "_safe_write_file({target}) 失败: {e}",
        "en": "_safe_write_file({target}) failed: {e}",
    },
    "err_mariadb_direct": {
        "zh": "❌ MariaDB 直连失败。请查阅 /root/.wp_credentials_*.txt。",
        "en": "❌ Direct MariaDB connection failed. Check /root/.wp_credentials_*.txt.",
    },
    "err_no_curl_wget": {
        "zh": "缺失 curl/wget。",
        "en": "Missing curl/wget.",
    },
    # [V3.0.15] B5: 下载源名称 / 磁盘检查标签 / 回滚描述 国际化
    "src_cn_node": {
        "zh": "官方中文节点",
        "en": "Official Chinese mirror",
    },
    "src_global_node": {
        "zh": "官方全球主节点",
        "en": "Official global mirror",
    },
    "label_wp_download": {
        "zh": "WordPress 下载",
        "en": "WordPress download",
    },
    "label_args_redacted": {
        "zh": "[参数已隐藏]",
        "en": "[REDACTED]",
    },
    "label_wp_extract": {
        "zh": "WordPress 解压",
        "en": "WordPress extraction",
    },
    "rollback_wp_dir": {
        "zh": "删除 WordPress 站点目录 {path}",
        "en": "Remove WordPress webroot {path}",
    },
    "rollback_db_user": {
        "zh": "删除数据库 {db} 和用户 {user}",
        "en": "Drop database {db} and user {user}",
    },
    "cred_header": {
        "zh": "===== [ {domain} ] 站点凭据 =====",
        "en": "===== [ {domain} ] Site Credentials =====",
    },
    "cred_emergency": {
        "zh": "===== 急救指南 =====",
        "en": "===== Emergency Guide =====",
    },
    "cred_db_connect": {
        "zh": "# 手动连接数据库 (执行后交互式输入密码，避免进程列表泄露)",
        "en": "# Connect to database manually (enter password interactively to avoid process list exposure)",
    },
    "cred_fix_perms": {
        "zh": "# 重置站点文件权限",
        "en": "# Reset site file permissions",
    },
    "cred_fix_perms_warn": {
        "zh": "  # ⚠️  必须在 find 之后单独执行，恢复安全权限：",
        "en": "  # ⚠️  Must run after find to restore secure permissions:",
    },
    "cred_manual_renew": {
        "zh": "# 手动续期 SSL 证书",
        "en": "# Manually renew SSL certificate",
    },
    "cred_nginx_reload": {
        "zh": "# 检查 Nginx 配置并重载",
        "en": "# Test Nginx config and reload",
    },
    "cred_timer_status": {
        "zh": "# 查看续期定时器状态",
        "en": "# Check renewal timer status",
    },
    "cred_uninstall": {
        "zh": "# 完整卸载本站守护组件 (保留数据与证书)",
        "en": "# Uninstall site daemon components (data & certs preserved)",
    },
    "cred_site_status": {
        "zh": "# 查看站点运行状态",
        "en": "# Check site status",
    },
    "cred_backup": {
        "zh": "# 一键备份 (数据库 + 站点文件 + Nginx 配置)",
        "en": "# Full backup (database + site files + Nginx config)",
    },
    "err_wp_download_all_failed": {
        "zh": "❌ 所有下载方式均失败（tar.gz 源 + WP-CLI）。",
        "en": "❌ All download methods failed (tar.gz sources + WP-CLI).",
    },
    "err_wp_extract": {
        "zh": "❌ WordPress 解压失败 (错误分类: {code})。{stderr_part}\n   建议: 检查磁盘空间与 tar 版本。",
        "en": "❌ WordPress extraction failed (category: {code}).{stderr_part}\n   Suggestion: check disk space and tar version.",
    },
    "err_wp_integrity": {
        "zh": "❌ WordPress 解压后完整性校验失败，核心文件缺失。",
        "en": "❌ WordPress integrity check failed after extraction; core files missing.",
    },
    "err_download_exception": {
        "zh": "下载过程异常: {e}",
        "en": "Download exception: {e}",
    },
    "err_skip_deps_missing": {
        "zh": "❌ --skip-deps 模式下缺少关键依赖: {deps}\n   请先手动安装后重试，或去掉 --skip-deps 让脚本自动安装。",
        "en": "❌ --skip-deps mode: missing critical dependencies: {deps}\n   Install them manually first, or remove --skip-deps.",
    },
    "err_nginx_start": {
        "zh": "❌ Nginx 启动失败，后续阶段均依赖 Nginx，部署终止。",
        "en": "❌ Nginx failed to start; all subsequent stages require Nginx. Deployment aborted.",
    },
    "err_db_name_chars": {
        "zh": "❌ 数据库名称包含非法字符: {name}",
        "en": "❌ Database name contains illegal characters: {name}",
    },
    "err_db_user_chars": {
        "zh": "❌ 数据库用户名包含非法字符: {user}",
        "en": "❌ Database username contains illegal characters: {user}",
    },
    "err_db_pass_chars": {
        "zh": "❌ 数据库密码包含非法字符。",
        "en": "❌ Database password contains illegal characters.",
    },
    "err_wpconfig_update": {
        "zh": "更新 wp-config.php 失败: {e}",
        "en": "Failed to update wp-config.php: {e}",
    },
    "err_wpconfig_generate": {
        "zh": "生成 wp-config.php 失败: {e}",
        "en": "Failed to generate wp-config.php: {e}",
    },
    "err_http_challenge_write": {
        "zh": "❌ HTTP challenge 预检：无法写入测试文件: {e}",
        "en": "❌ HTTP challenge preflight: cannot write test file: {e}",
    },
    "err_http_challenge_conn_fail": {
        "zh": "❌ HTTP challenge 预检失败：无法通过 HTTP 访问验证路径。\n   可能原因：Nginx 未正确启动、防火墙拦截 80 端口、域名未解析到本机。\n   提示：若 Nginx listen 未绑定 0.0.0.0，127.0.0.1 预检可能误通，请确认 listen 指令。",
        "en": "❌ HTTP challenge preflight failed: cannot reach the ACME challenge path via HTTP.\n   Possible causes: Nginx not running, port 80 blocked by firewall, domain not pointing to this server.\n   Hint: if Nginx listens on a specific IP (not 0.0.0.0), loopback preflight may succeed falsely — verify listen directive.",
    },
    "err_cert_fatal": {
        "zh": "❌ {ca} 签发遇到非 CA 侧致命错误，换 CA 也无法解决，终止尝试。\n   错误摘要: {err}",
        "en": "❌ {ca} encountered a non-CA fatal error; switching CA will not help. Aborted.\n   Error summary: {err}",
    },
    "err_cert_permission": {
        "zh": "❌ {ca} 签发遇到权限错误，终止尝试。\n   错误摘要: {err}",
        "en": "❌ {ca} encountered a permission error. Aborted.\n   Error summary: {err}",
    },
    "err_cert_all_failed": {
        "zh": "❌ 证书申请全部失败。",
        "en": "❌ All certificate issuance attempts failed.",
    },
    "err_cert_renew": {
        "zh": "❌ {domain} 证书续期失败。",
        "en": "❌ Certificate renewal failed for {domain}.",
    },
    "err_backup_dir": {
        "zh": "❌ 创建备份目录失败: {e}",
        "en": "❌ Failed to create backup directory: {e}",
    },
    "err_backup_not_found": {
        "zh": "备份目录不存在: {path}",
        "en": "Backup directory does not exist: {path}",
    },
    "err_backup_no_items": {
        "zh": "未找到任何备份。",
        "en": "No backups found.",
    },
    "err_backup_not_dir": {
        "zh": "备份路径不是目录: {path}",
        "en": "Backup path is not a directory: {path}",
    },
    "err_deploy_deps": {
        "zh": "部署终止：基础依赖安装失败。",
        "en": "Deployment aborted: base dependency installation failed.",
    },
    "err_deploy_nginx_acme": {
        "zh": "部署终止：Nginx ACME 验证通道配置失败。",
        "en": "Deployment aborted: Nginx ACME challenge channel configuration failed.",
    },
    "err_deploy_dns": {
        "zh": "部署终止：DNS 预检失败，域名未解析到本机。",
        "en": "Deployment aborted: DNS preflight failed; domain does not resolve to this server.",
    },
    "err_deploy_http_challenge": {
        "zh": "部署终止：HTTP challenge 预检失败。\n   请检查 Nginx 是否正常运行，以及 80 端口是否可从公网访问。",
        "en": "Deployment aborted: HTTP challenge preflight failed.\n   Check that Nginx is running and port 80 is publicly accessible.",
    },
    "err_deploy_cert": {
        "zh": "部署终止：证书签发失败。",
        "en": "Deployment aborted: certificate issuance failed.",
    },
    "err_deploy_https": {
        "zh": "部署终止：HTTPS 配置挂载失败。",
        "en": "Deployment aborted: failed to apply HTTPS config.",
    },
    "err_rollback_exception": {
        "zh": "回滚过程发生未预期异常: {e}\n{tb}",
        "en": "Unexpected exception during rollback: {e}\n{tb}",
    },
    "err_nginx_bak_fail": {
        "zh": "Nginx 配置备份失败 ({src} → {dst}): {e}",
        "en": "Nginx config backup failed ({src} → {dst}): {e}",
    },
    "err_db_root_unsafe": {
        "zh": "❌ --db-root-pass 包含不安全字符（不允许单引号、反引号、反斜杠等）。",
        "en": "❌ --db-root-pass contains unsafe characters (single quotes, backticks, backslashes not allowed).",
    },
    "warn_db_root_unsafe_skip": {
        "zh": "❌ --db-root-pass 包含不安全字符，跳过此密码（不允许单引号、反引号、反斜杠等）。",
        "en": "❌ --db-root-pass contains unsafe characters; password skipped (single quotes, backticks, backslashes not allowed).",
    },
    "err_external_db_no_pass": {
        "zh": "❌ 使用外置数据库 ({host}) 时，必须通过 --db-root-pass 或 WP_DB_ROOT_PASS 提供数据库密码。",
        "en": "❌ When using an external database ({host}), you must provide the password via --db-root-pass or WP_DB_ROOT_PASS.",
    },
    "err_external_db_connect": {
        "zh": "❌ 无法连接外置数据库 ({host})。\n   请检查主机地址、端口与防火墙规则，并确认 root 密码正确。",
        "en": "❌ Cannot connect to external database ({host}).\n   Check the host/port, firewall rules, and verify the root password.",
    },
    # ── logging.warning ─────────────────────────────────────────────────────
    "warn_signal": {
        "zh": "接收到信号 {sig}，正在安全退出...",
        "en": "Received signal {sig}, shutting down gracefully...",
    },
    "warn_rollback_start": {
        "zh": "部署失败，开始回滚本次创建的资源...",
        "en": "Deployment failed; rolling back created resources...",
    },
    "warn_rollback_item": {
        "zh": "  回滚 [{desc}] 时出错: {e}",
        "en": "  Error rolling back [{desc}]: {e}",
    },
    "warn_lock_stale": {
        "zh": "检测到残留的 .lock 文件 (进程已不存在)，自动清理并重试。",
        "en": "Stale .lock file detected (process no longer exists); cleaning up and retrying.",
    },
    "warn_db_not_ready": {
        "zh": "数据库服务在 {t}s 内未就绪，继续尝试后续操作。",
        "en": "Database service not ready within {t}s; proceeding anyway.",
    },
    "warn_selinux": {
        "zh": "检测到 SELinux 已启用，正在配置布尔值...",
        "en": "SELinux detected as enforcing; configuring booleans...",
    },
    "warn_backup_integrity": {
        "zh": "⚠️  本次备份无任何文件通过完整性校验，跳过旧备份清理以防数据全损。",
        "en": "⚠️  No backup files passed integrity check; skipping cleanup to prevent total data loss.",
    },
    "warn_wpcli_no_download": {
        "zh": "WP-CLI 安装跳过：缺少 curl/wget。",
        "en": "WP-CLI installation skipped: curl/wget not found.",
    },
    "warn_wpcli_all_failed": {
        "zh": "WP-CLI 所有镜像均下载/校验失败，跳过安装。",
        "en": "WP-CLI: all mirrors failed to download/verify; skipping installation.",
    },
    "warn_cert_retryable": {
        "zh": "⚠️ {ca} 签发失败 (可重试)，{next_msg}",
        "en": "⚠️ {ca} issuance failed (retryable); {next_msg}",
    },
    "warn_cert_next_ca": {
        "zh": "尝试下一个 CA...",
        "en": "trying next CA...",
    },
    "warn_cert_no_more_ca": {
        "zh": "已无更多 CA。",
        "en": "no more CAs available.",
    },
    # ── logging.info — dry-run ───────────────────────────────────────────────
    "dry_run_cmd": {
        "zh": "[DRY-RUN] 模拟执行: {cmd}",
        "en": "[DRY-RUN] Simulating: {cmd}",
    },
    "dry_run_sql": {
        "zh": "[DRY-RUN] 模拟通过 stdin 执行 SQL",
        "en": "[DRY-RUN] Simulating SQL execution via stdin",
    },
    "dry_run_atomic": {
        "zh": "[DRY-RUN] 模拟原子写入 -> {path}",
        "en": "[DRY-RUN] Simulating atomic write -> {path}",
    },
    "dry_run_wpcli": {
        "zh": "[DRY-RUN] 跳过 WP-CLI 安装。",
        "en": "[DRY-RUN] Skipping WP-CLI installation.",
    },
    "dry_run_nginx_helper": {
        "zh": "[DRY-RUN] 跳过 nginx-helper 插件安装。",
        "en": "[DRY-RUN] Skipping nginx-helper plugin installation.",
    },
    "dry_run_dns": {
        "zh": "[DRY-RUN] 跳过 DNS 预检。",
        "en": "[DRY-RUN] Skipping DNS preflight.",
    },
    "dry_run_http": {
        "zh": "[DRY-RUN] 跳过 HTTP challenge 预检。",
        "en": "[DRY-RUN] Skipping HTTP challenge preflight.",
    },
    "dry_run_health": {
        "zh": "[DRY-RUN] 跳过站点健康检查。",
        "en": "[DRY-RUN] Skipping site health check.",
    },
    "dry_run_redis": {
        "zh": "[DRY-RUN] 跳过 Redis 对象缓存配置。",
        "en": "[DRY-RUN] Skipping Redis object cache configuration.",
    },
    "dry_run_brotli": {
        "zh": "[DRY-RUN] 跳过 Brotli 检测。",
        "en": "[DRY-RUN] Skipping Brotli detection.",
    },
    "dry_run_logrotate": {
        "zh": "[DRY-RUN] 跳过 logrotate 配置。",
        "en": "[DRY-RUN] Skipping logrotate configuration.",
    },
    "dry_run_f2b": {
        "zh": "[DRY-RUN] 跳过 Fail2Ban 配置。",
        "en": "[DRY-RUN] Skipping Fail2Ban configuration.",
    },
    "dry_run_backup": {
        "zh": "[DRY-RUN] 跳过实际备份操作。",
        "en": "[DRY-RUN] Skipping actual backup.",
    },
    "dry_run_restore": {
        "zh": "[DRY-RUN] 跳过实际恢复操作。",
        "en": "[DRY-RUN] Skipping actual restore.",
    },
    # ── logging.info — ✅ milestones ─────────────────────────────────────────
    "ok_wpcli_wp": {
        "zh": "✅ WP-CLI 下载 WordPress 成功。",
        "en": "✅ WordPress downloaded via WP-CLI.",
    },
    "ok_wpcli_checksums": {
        "zh": "✅ WP-CLI verify-checksums 校验通过。",
        "en": "✅ WP-CLI verify-checksums passed.",
    },
    "ok_nginx_helper_activated": {
        "zh": "✅ nginx-helper 插件已激活（FastCGI 缓存刷新就绪）。",
        "en": "✅ nginx-helper plugin activated (FastCGI cache purge ready).",
    },
    "ok_nginx_helper_installed": {
        "zh": "✅ nginx-helper 插件安装并激活成功（FastCGI 缓存刷新就绪）。",
        "en": "✅ nginx-helper installed and activated (FastCGI cache purge ready).",
    },
    "ok_sha256": {
        "zh": "✅ [{name}] SHA256 校验通过。",
        "en": "✅ [{name}] SHA256 checksum verified.",
    },
    "ok_http_challenge": {
        "zh": "✅ HTTP challenge 预检通过：Nginx 正确响应 ACME 验证路径。",
        "en": "✅ HTTP challenge preflight passed: Nginx correctly serves ACME challenge path.",
    },
    "ok_cert_issued": {
        "zh": "✅ 证书由 {ca} 签发成功。",
        "en": "✅ Certificate issued by {ca}.",
    },
    "ok_wpcli_installed": {
        "zh": "✅ WP-CLI 确认：WordPress 已安装并可连接数据库。",
        "en": "✅ WP-CLI confirmed: WordPress is installed and database is reachable.",
    },
    "ok_cert_renew": {
        "zh": "✅ 续期检查完毕。",
        "en": "✅ Renewal check complete.",
    },
    "ok_f2b_active": {
        "zh": "✅ Fail2Ban WordPress 防护已激活。",
        "en": "✅ Fail2Ban WordPress protection activated.",
    },
    "ok_db_backup": {
        "zh": "✅ 数据库已备份: {path}",
        "en": "✅ Database backed up: {path}",
    },
    "ok_webroot_backup": {
        "zh": "✅ 站点文件已备份: {path}",
        "en": "✅ Webroot backed up: {path}",
    },
    "ok_nginx_backup": {
        "zh": "✅ Nginx 配置已备份: {path}",
        "en": "✅ Nginx config backed up: {path}",
    },
    "ok_db_restore": {
        "zh": "数据库恢复成功。",
        "en": "Database restored successfully.",
    },
    "ok_uninstall": {
        "zh": "✅ 卸载结束。业务数据与证书已保留。",
        "en": "✅ Uninstall complete. Site data and certificates have been preserved.",
    },
    "ok_wpcli_install_src": {
        "zh": "✅ WP-CLI 安装成功 (来源: {src}): {ver}",
        "en": "✅ WP-CLI installed (source: {src}): {ver}",
    },
    # ── argparse help ────────────────────────────────────────────────────────
    "help_domain": {
        "zh": "网站域名 (如: example.com)。也可通过环境变量 WP_DOMAIN 传入",
        "en": "Site domain (e.g. example.com). Also accepts env var WP_DOMAIN",
    },
    "help_dry_run": {
        "zh": "演练模式：不执行真实写操作",
        "en": "Dry-run mode: no real write operations will be performed",
    },
    "help_staging": {
        "zh": "使用 Let's Encrypt Staging 环境",
        "en": "Use Let's Encrypt Staging environment",
    },
    "help_quiet": {
        "zh": "静默模式：仅输出 WARNING 及以上级别日志",
        "en": "Quiet mode: only WARNING and above log levels",
    },
    "help_db_host": {
        "zh": "数据库主机地址 (默认: localhost)。也可通过环境变量 WP_DB_HOST 传入",
        "en": "Database host (default: localhost). Also accepts env var WP_DB_HOST",
    },
    "help_db_root_pass": {
        "zh": "MariaDB/MySQL root 密码。backup 子命令用于数据库 dump；也可通过环境变量 WP_DB_ROOT_PASS 传入",
        "en": "MariaDB/MySQL root password. Used by backup for DB dump. Also accepts env var WP_DB_ROOT_PASS",
    },
    "help_backup_dir": {
        "zh": "备份根目录 (默认: /root/backups)。支持外挂数据盘场景，如 /data/backups。也可通过环境变量 WP_BACKUP_DIR 传入",
        "en": "Backup root directory (default: /root/backups). Supports external storage, e.g. /data/backups. Also accepts env var WP_BACKUP_DIR",
    },
    "help_email": {
        "zh": "证书申请联系邮箱。也可通过环境变量 WP_EMAIL 传入",
        "en": "Contact email for certificate registration. Also accepts env var WP_EMAIL",
    },
    "help_cache": {
        "zh": "Nginx 缓存模式 (默认: none)。fastcgi = 开启 FastCGI 页面缓存",
        "en": "Nginx cache mode (default: none). fastcgi = enable FastCGI page cache",
    },
    "help_redis": {
        "zh": "[V2.9.8] 启用 Redis 对象缓存 (可与 --cache fastcgi 叠加)",
        "en": "[V2.9.8] Enable Redis object cache (can combine with --cache fastcgi)",
    },
    "help_skip_deps": {
        "zh": "[V3.0.0] 跳过系统包安装 (假定依赖已就绪，仅配置应用层)",
        "en": "[V3.0.0] Skip system package installation (assume deps are present, configure app layer only)",
    },
    "help_allow_xmlrpc": {
        "zh": "[V3.0.3] 放开 xmlrpc.php 访问 (支持 Jetpack/移动 App)。默认 deny all；启用后改为速率限制 (1r/s burst=10) + PHP-FPM 透传",
        "en": "[V3.0.3] Allow xmlrpc.php access (Jetpack/mobile app support). Default: deny all; when set: rate-limited (1r/s burst=10) + PHP-FPM pass-through",
    },
    "help_php_version": {
        "zh": "强制指定 PHP-FPM 版本 (如: 8.2)。默认自动探测最高版本",
        "en": "Force a specific PHP-FPM version (e.g. 8.2). Default: auto-detect highest available",
    },
    "help_persist_root_pwd": {
        "zh": "[警告] 允许将生成的 MariaDB root 密码明文保存到磁盘 (/root/.mariadb_root.pwd)",
        "en": "[Warning] Allow saving the generated MariaDB root password in plaintext to disk (/root/.mariadb_root.pwd)",
    },
    "help_db_wait_timeout": {
        "zh": "等待数据库服务就绪的超时秒数 (默认: 本地 30s，外置/跨地域 60s)。极高延迟或跨地域云环境建议设为 120~300。也可通过环境变量 WP_DB_WAIT_TIMEOUT 传入",
        "en": "Seconds to wait for the database to become ready (default: 30s local, 60s external). For high-latency cross-region setups, use 120~300. Also accepts env var WP_DB_WAIT_TIMEOUT",
    },
    "help_force_renew": {
        "zh": "强制续期：忽略证书到期时间，立即申请新证书",
        "en": "Force renewal: ignore expiry date and immediately request a new certificate",
    },
    "help_redis_status": {
        "zh": "检查并显示 Redis 服务状态",
        "en": "Check and display Redis service status",
    },
    "help_keep": {
        "zh": "保留最近 N 份备份，自动清理旧备份 (默认: 5，0 = 不清理)",
        "en": "Keep the N most recent backups; auto-remove older ones (default: 5, 0 = no cleanup)",
    },
    "help_restore_from": {
        "zh": "备份目录路径。省略则自动选择最新备份",
        "en": "Backup directory path. Omit to auto-select the latest backup",
    },
    "help_cache_update": {
        "zh": "Nginx 缓存模式 (需与 deploy 时一致, 默认: none)",
        "en": "Nginx cache mode (must match deploy setting, default: none)",
    },
    "help_redis_update": {
        "zh": "指示站点已启用 Redis 对象缓存 (需与 deploy 时一致)",
        "en": "Indicate that Redis object cache was enabled at deploy time",
    },
    "help_allow_xmlrpc_update": {
        "zh": "[V3.0.3] 放开 xmlrpc.php 访问 (需与 deploy 时一致，或用于切换策略)",
        "en": "[V3.0.3] Allow xmlrpc.php access (match deploy setting, or use to change policy)",
    },
    "help_lang": {
        "zh": "界面语言 (zh|en)。首次指定后自动持久化，后续无需重复传入",
        "en": "Interface language (zh|en). Persisted on first use; no need to repeat",
    },
    # ── logging.error (remaining) ────────────────────────────────────────────
    "err_wp_src_fatal": {
        "zh": "❌ [{name}] 致命错误，跳过后续源。",
        "en": "❌ [{name}] Fatal error; skipping remaining sources.",
    },
    # ── logging.warning (full coverage) ─────────────────────────────────────
    "warn_read_global_pwd": {
        "zh": "读取全局密码文件失败，跳过此优先级: {e}",
        "en": "Failed to read global password file; skipping this priority: {e}",
    },
    "warn_user_pwd_fail": {
        "zh": "用户提供的 MariaDB root 密码验证失败，继续尝试初始化。",
        "en": "User-provided MariaDB root password verification failed; proceeding with initialization.",
    },
    "warn_mariadb_plugin_timeout": {
        "zh": "检测 MariaDB 认证插件超时，按非 socket 认证处理。",
        "en": "MariaDB auth plugin detection timed out; treating as non-socket authentication.",
    },
    "warn_read_wpconfig_pwd": {
        "zh": "读取 wp-config.php 恢复密码失败: {e}",
        "en": "Failed to read password from wp-config.php: {e}",
    },
    "warn_wpcli_phar_fail": {
        "zh": "  [{mirror}] WP-CLI phar 下载失败，尝试下一镜像。",
        "en": "  [{mirror}] WP-CLI phar download failed; trying next mirror.",
    },
    "warn_wpcli_hash_fail": {
        "zh": "  [{mirror}] WP-CLI hash 文件下载失败，尝试下一镜像。",
        "en": "  [{mirror}] WP-CLI hash file download failed; trying next mirror.",
    },
    "warn_wpcli_hash_bad": {
        "zh": "  [{mirror}] hash 文件内容异常，尝试下一镜像。",
        "en": "  [{mirror}] Hash file content invalid; trying next mirror.",
    },
    "warn_wpcli_install_fail": {
        "zh": "WP-CLI 安装到 {path} 失败: {e}",
        "en": "WP-CLI installation to {path} failed: {e}",
    },
    "warn_wpcli_verify_fail": {
        "zh": "  [{mirror}] 安装后验证失败，尝试下一镜像。",
        "en": "  [{mirror}] Post-install verification failed; trying next mirror.",
    },
    "warn_wpcli_wp_dl_fail": {
        "zh": "WP-CLI 下载 WordPress 失败: {err}",
        "en": "WP-CLI failed to download WordPress: {err}",
    },
    "warn_wp_src_hash_mismatch": {
        "zh": "⚠️ [{name}] 散列不匹配，切换备用节点...",
        "en": "⚠️ [{name}] Hash mismatch; switching to fallback source...",
    },
    "warn_all_tgz_failed": {
        "zh": "所有 tar.gz 源拉取失败，尝试 WP-CLI 兜底下载...",
        "en": "All tar.gz sources failed; attempting WP-CLI fallback download...",
    },
    "warn_php_ini_fail": {
        "zh": "修改 {path} 失败: {e}",
        "en": "Failed to modify {path}: {e}",
    },
    "warn_http_challenge_curl_err": {
        "zh": "HTTP challenge 预检 curl 异常: {e}",
        "en": "HTTP challenge preflight curl exception: {e}",
    },
    "warn_fastcgi_cache_dir_fail": {
        "zh": "FastCGI 缓存目录创建失败: {e}",
        "en": "Failed to create FastCGI cache directory: {e}",
    },
    "warn_no_curl_health": {
        "zh": "curl 不可用，跳过站点健康检查。",
        "en": "curl not available; skipping site health check.",
    },
    "warn_cert_not_found": {
        "zh": "证书文件不存在: {path}，certbot 将尝试签发。",
        "en": "Certificate file not found: {path}; certbot will attempt issuance.",
    },
    "warn_redis_plugin_fail": {
        "zh": "redis-cache 插件安装失败: {err}",
        "en": "redis-cache plugin installation failed: {err}",
    },
    "warn_logrotate_dir_missing": {
        "zh": "logrotate 目录不存在，跳过日志轮转配置。",
        "en": "logrotate directory not found; skipping log rotation configuration.",
    },
    "warn_logrotate_write_fail": {
        "zh": "logrotate 配置写入失败: {e}",
        "en": "Failed to write logrotate configuration: {e}",
    },
    "warn_f2b_install_fail": {
        "zh": "fail2ban 安装失败，跳过防护配置。",
        "en": "fail2ban installation failed; skipping protection configuration.",
    },
    "warn_f2b_write_fail": {
        "zh": "Fail2Ban 配置写入失败: {e}",
        "en": "Failed to write Fail2Ban configuration: {e}",
    },
    "warn_backup_pwd_bad_chars": {
        "zh": "密码文件内容包含异常字符，跳过数据库备份。",
        "en": "Password file contains invalid characters; skipping database backup.",
    },
    "warn_db_backup_fail": {
        "zh": "数据库备份可能失败: {err}",
        "en": "Database backup may have failed: {err}",
    },
    "warn_db_backup_timeout": {
        "zh": "数据库备份超时 ({t}s)。",
        "en": "Database backup timed out ({t}s).",
    },
    "warn_db_backup_exception": {
        "zh": "数据库备份异常: {e}",
        "en": "Database backup exception: {e}",
    },
    "warn_db_dump_incomplete": {
        "zh": "数据库 dump 未成功完成，备份可能不完整。",
        "en": "Database dump did not complete successfully; backup may be incomplete.",
    },
    "warn_db_pwd_unavail_backup": {
        "zh": "数据库 root 密码不可用，跳过数据库备份。",
        "en": "Database root password unavailable; skipping database backup.",
    },
    "warn_webroot_backup_fail": {
        "zh": "站点文件备份失败。",
        "en": "Site files backup failed.",
    },
    "warn_webroot_missing": {
        "zh": "Webroot 不存在: {path}，跳过。",
        "en": "Webroot not found: {path}; skipping.",
    },
    "warn_nginx_bak_copy_fail": {
        "zh": "Nginx 配置备份失败: {e}",
        "en": "Nginx configuration backup failed: {e}",
    },
    "warn_backup_integrity_err": {
        "zh": "备份完整性校验异常 ({name}): {e}",
        "en": "Backup integrity check error ({name}): {e}",
    },
    "warn_cleanup_old_bak_fail": {
        "zh": "清理旧备份失败 ({name}): {e}",
        "en": "Failed to clean up old backup ({name}): {e}",
    },
    "warn_list_bak_fail": {
        "zh": "枚举备份目录失败: {e}",
        "en": "Failed to enumerate backup directory: {e}",
    },
    "warn_db_restore_timeout": {
        "zh": "数据库恢复超时。",
        "en": "Database restore timed out.",
    },
    "warn_db_restore_exception": {
        "zh": "数据库恢复异常: {e}",
        "en": "Database restore exception: {e}",
    },
    "warn_db_pwd_unavail_restore": {
        "zh": "数据库 root 密码不可用, 跳过数据库恢复。",
        "en": "Database root password unavailable; skipping database restore.",
    },
    "warn_webroot_restore_fail": {
        "zh": "站点文件恢复失败。",
        "en": "Site files restore failed.",
    },
    "warn_nginx_conf_restore_fail": {
        "zh": "  恢复 {name} 失败: {e}",
        "en": "  Failed to restore {name}: {e}",
    },
    "warn_nginx_update_fail": {
        "zh": "Nginx 配置更新失败。",
        "en": "Nginx configuration update failed.",
    },
    "warn_nginx_test_fail_restore": {
        "zh": "⚠️  Nginx 配置测试失败，跳过 reload。请手动检查 nginx -t 输出。",
        "en": "⚠️  Nginx config test failed; skipping reload. Check 'nginx -t' output manually.",
    },
    # ── logging.info (full coverage) ─────────────────────────────────────────
    "info_php_version_forced": {
        "zh": "使用用户指定的 PHP 版本: {ver}",
        "en": "Using user-specified PHP version: {ver}",
    },
    "info_php_socket_forced": {
        "zh": "使用用户指定 PHP {ver} 的 socket: {sock}",
        "en": "Using socket for user-specified PHP {ver}: {sock}",
    },
    "info_php_socket_from_conf": {
        "zh": "从 {conf} 读取 socket: {sock}",
        "en": "Read socket from {conf}: {sock}",
    },
    "info_disk_ok": {
        "zh": "磁盘空间检查通过 ({label})：{free}MB 可用。",
        "en": "Disk space check passed ({label}): {free}MB available.",
    },
    "info_rollback_item": {
        "zh": "  回滚: {desc}",
        "en": "  Rolling back: {desc}",
    },
    "info_rollback_done": {
        "zh": "回滚完成。",
        "en": "Rollback complete.",
    },
    "info_exit": {
        "zh": "退出部署脚本 (Exit Code: {code})",
        "en": "Exiting deployment script (Exit Code: {code})",
    },
    "info_run_cmd": {
        "zh": "执行命令: {cmd}",
        "en": "Running command: {cmd}",
    },
    "info_ufw": {
        "zh": "配置 UFW 防火墙...",
        "en": "Configuring UFW firewall...",
    },
    "info_firewalld": {
        "zh": "配置 Firewalld 防火墙...",
        "en": "Configuring Firewalld firewall...",
    },
    "info_db_wait": {
        "zh": "等待数据库服务就绪 (超时: {t}s)...",
        "en": "Waiting for database to become ready (timeout: {t}s)...",
    },
    "info_db_ready": {
        "zh": "数据库服务就绪 (等待 {t}s)。",
        "en": "Database ready (waited {t}s).",
    },
    "info_db_ready_auth": {
        "zh": "数据库服务就绪（需认证，{t}s）。",
        "en": "Database ready with authentication required ({t}s).",
    },
    "info_db_fallback_detect": {
        "zh": "mysqladmin 不可用，直接使用 mysql 检测数据库就绪状态...",
        "en": "mysqladmin not available; using mysql directly to detect readiness...",
    },
    "info_db_ready_fallback": {
        "zh": "数据库服务就绪（回退检测）。",
        "en": "Database ready (fallback detection).",
    },
    "info_db_ready_fallback_auth": {
        "zh": "数据库服务就绪（回退检测，需认证）。",
        "en": "Database ready with authentication required (fallback detection).",
    },
    "info_ext_db_ok": {
        "zh": "外置数据库 ({host}) 连接验证通过。",
        "en": "External database ({host}) connection verified.",
    },
    "info_mariadb_env_ok": {
        "zh": "MariaDB Root 环境验证通过。",
        "en": "MariaDB root environment verified.",
    },
    "info_try_user_pwd": {
        "zh": "尝试使用用户提供的 MariaDB root 密码...",
        "en": "Trying user-provided MariaDB root password...",
    },
    "info_user_pwd_ok": {
        "zh": "用户提供的 MariaDB root 密码验证通过。",
        "en": "User-provided MariaDB root password verified.",
    },
    "info_wpcli_found": {
        "zh": "检测到 WP-CLI: {path} ({ver})",
        "en": "WP-CLI detected: {path} ({ver})",
    },
    "info_wpcli_installing": {
        "zh": "尝试自动安装 WP-CLI...",
        "en": "Attempting automatic WP-CLI installation...",
    },
    "info_wpcli_mirror_try": {
        "zh": "  尝试镜像: {mirror} ...",
        "en": "  Trying mirror: {mirror} ...",
    },
    "info_wpcli_wp_fallback": {
        "zh": "使用 WP-CLI 兜底下载 WordPress...",
        "en": "Using WP-CLI as fallback to download WordPress...",
    },
    "info_wpcli_verify_checksums": {
        "zh": "使用 WP-CLI 执行核心文件校验 (verify-checksums)...",
        "en": "Running WP-CLI verify-checksums for core file integrity...",
    },
    "info_nginx_helper_install": {
        "zh": "为 FastCGI Cache 安装 nginx-helper 插件...",
        "en": "Installing nginx-helper plugin for FastCGI Cache...",
    },
    "info_wp_src_try": {
        "zh": "尝试从 [{name}] 拉取镜像与校验值...",
        "en": "Fetching archive and checksum from [{name}]...",
    },
    "info_skip_deps_verify": {
        "zh": "[--skip-deps] 跳过系统包安装，验证关键依赖...",
        "en": "[--skip-deps] Skipping package installation; verifying critical dependencies...",
    },
    "info_deps_ok": {
        "zh": "关键依赖检查通过: nginx, php, mysql 均可用。",
        "en": "Critical dependency check passed: nginx, php, mysql all available.",
    },
    "info_db_allocate": {
        "zh": "正在分配站点级数据库...",
        "en": "Allocating site database...",
    },
    "info_wpconfig_reuse_pwd": {
        "zh": "检测到已有 wp-config.php，复用现有数据库密码以保持幂等性。",
        "en": "Existing wp-config.php detected; reusing database password for idempotency.",
    },
    "info_wpconfig_pwd_updated": {
        "zh": "已更新 wp-config.php 中的数据库密码。",
        "en": "Database password in wp-config.php updated.",
    },
    "info_dns_ok_rtype": {
        "zh": "DNS 预检通过：{domain} {rtype} → {addrs}",
        "en": "DNS preflight passed: {domain} {rtype} → {addrs}",
    },
    "info_dns_ok_getent": {
        "zh": "DNS 预检通过（getent）：{domain} → {addr}",
        "en": "DNS preflight passed (getent): {domain} → {addr}",
    },
    "info_cert_try": {
        "zh": "[{idx}/{total}] 尝试 {ca} 签发证书...",
        "en": "[{idx}/{total}] Attempting certificate issuance via {ca}...",
    },
    "info_fastcgi_cache_created": {
        "zh": "FastCGI 缓存目录已创建: {path}",
        "en": "FastCGI cache directory created: {path}",
    },
    "info_health_check": {
        "zh": "执行站点健康检查: {url}",
        "en": "Running site health check: {url}",
    },
    "info_wpcli_deep_check": {
        "zh": "使用 WP-CLI 执行深度安装状态检查...",
        "en": "Running WP-CLI deep installation status check...",
    },
    "info_wp_version": {
        "zh": "WordPress 版本: {ver}",
        "en": "WordPress version: {ver}",
    },
    "info_renew_check": {
        "zh": "执行 {domain} 证书续期检查...",
        "en": "Running certificate renewal check for {domain}...",
    },
    "info_cert_expiry": {
        "zh": "当前证书到期时间: {expiry}",
        "en": "Current certificate expiry: {expiry}",
    },
    "info_cert_valid": {
        "zh": "证书有效期充足 (>30天)，certbot 将跳过续期。",
        "en": "Certificate valid for more than 30 days; certbot will skip renewal.",
    },
    "info_cert_expiring_soon": {
        "zh": "证书将在 30 天内到期，certbot 将执行续期。",
        "en": "Certificate expires within 30 days; certbot will perform renewal.",
    },
    "info_redis_installing": {
        "zh": "安装 Redis Object Cache 插件...",
        "en": "Installing Redis Object Cache plugin...",
    },
    "info_redis_enabled": {
        "zh": "Redis 对象缓存已启用。",
        "en": "Redis object cache enabled.",
    },
    "info_brotli_unavail": {
        "zh": "Nginx Brotli 模块不可用, 跳过 (Gzip 仍然生效)。",
        "en": "Nginx Brotli module not available; skipping (Gzip remains active).",
    },
    "info_brotli_enabled": {
        "zh": "Brotli 压缩已启用 (全局生效)。",
        "en": "Brotli compression enabled (globally active).",
    },
    "info_brotli_rollback": {
        "zh": "Brotli 配置验证失败, 已回滚 (Gzip 仍然生效)。",
        "en": "Brotli configuration validation failed; rolled back (Gzip remains active).",
    },
    "info_logrotate_written": {
        "zh": "logrotate 配置已写入: {path}",
        "en": "logrotate configuration written: {path}",
    },
    "info_f2b_installing": {
        "zh": "安装 fail2ban...",
        "en": "Installing fail2ban...",
    },
    "info_f2b_written": {
        "zh": "Fail2Ban 规则已写入: {filter}, {jail}",
        "en": "Fail2Ban rules written: {filter}, {jail}",
    },
    "info_backup_start": {
        "zh": "开始备份 {domain}...",
        "en": "Starting backup for {domain}...",
    },
    "info_backup_use_cli_pwd": {
        "zh": "使用 --db-root-pass 提供的 root 密码执行数据库备份。",
        "en": "Using --db-root-pass password for database backup.",
    },
    "info_cleanup_old_bak": {
        "zh": "🗑️  已清理旧备份: {name}",
        "en": "🗑️  Cleaned up old backup: {name}",
    },
    "info_restore_start": {
        "zh": "开始恢复 {domain}...",
        "en": "Starting restore for {domain}...",
    },
    "info_restore_auto_bak": {
        "zh": "自动选择最新备份: {path}",
        "en": "Auto-selected latest backup: {path}",
    },
    "info_restore_db": {
        "zh": "恢复数据库: {name} ...",
        "en": "Restoring database: {name} ...",
    },
    "info_no_db_dump": {
        "zh": "备份中无数据库 dump, 跳过。",
        "en": "No database dump in backup; skipping.",
    },
    "info_restore_webroot": {
        "zh": "恢复站点文件...",
        "en": "Restoring site files...",
    },
    "info_webroot_restore_ok": {
        "zh": "站点文件恢复成功。",
        "en": "Site files restored successfully.",
    },
    "info_no_webroot_tar": {
        "zh": "备份中无 webroot 压缩包, 跳过。",
        "en": "No webroot archive in backup; skipping.",
    },
    "info_restore_nginx": {
        "zh": "恢复 Nginx 配置...",
        "en": "Restoring Nginx configuration...",
    },
    "info_nginx_conf_restored": {
        "zh": "  {name} 已恢复",
        "en": "  {name} restored",
    },
    "info_restore_done": {
        "zh": "{domain} 恢复完成 (来源: {src})",
        "en": "{domain} restore complete (source: {src})",
    },
    "info_update_start": {
        "zh": "===== 配置热更新: {domain} =====",
        "en": "===== Config hot-update: {domain} =====",
    },
    "info_nginx_updated": {
        "zh": "Nginx HTTPS 配置已更新。",
        "en": "Nginx HTTPS configuration updated.",
    },
    "info_php_updated": {
        "zh": "PHP 配置已更新。",
        "en": "PHP configuration updated.",
    },
    "info_update_done": {
        "zh": "{domain} 配置热更新完成。",
        "en": "{domain} config hot-update complete.",
    },
    "info_uninstall_start": {
        "zh": "开始卸载 {domain} 的守护组件...",
        "en": "Starting uninstall of daemon components for {domain}...",
    },
    "info_deleted": {
        "zh": "已删除: {path}",
        "en": "Deleted: {path}",
    },
    "debug_nginx_pending_cleanup": {
        "zh": "apply_nginx_config_safe: 清理 .pending 文件失败 (可忽略): %s",
        "en": "apply_nginx_config_safe: failed to clean up .pending file (ignorable): %s",
    },
    # ── ArgumentParser description / subcommand help ─────────────────────────
    "parser_description": {
        "zh": "高可用建站引擎 (V3.0.15)",
        "en": "High-availability WordPress deployment engine (V3.0.15)",
    },
    "subcmd_list": {
        "zh": "可用子命令",
        "en": "available subcommands",
    },
    "subcmd_deploy": {
        "zh": "部署 WordPress 站点并签发 SSL 证书",
        "en": "Deploy a WordPress site and obtain an SSL certificate",
    },
    "subcmd_renew": {
        "zh": "续期 SSL 证书",
        "en": "Renew the SSL certificate",
    },
    "subcmd_status": {
        "zh": "查询站点运行状态（证书、服务、磁盘）",
        "en": "Show site status (certificate, services, disk)",
    },
    "subcmd_backup": {
        "zh": "备份数据库、站点文件与 Nginx 配置",
        "en": "Back up the database, site files, and Nginx config",
    },
    "subcmd_restore": {
        "zh": "[V2.9.8] 从备份恢复站点 (数据库+文件+Nginx)",
        "en": "[V2.9.8] Restore site from backup (database + files + Nginx)",
    },
    "subcmd_update": {
        "zh": "[V2.9.8] 热更新配置模板 (Nginx/PHP/Fail2Ban/logrotate)",
        "en": "[V2.9.8] Hot-update config templates (Nginx/PHP/Fail2Ban/logrotate)",
    },
    "subcmd_uninstall": {
        "zh": "卸载指定域名的守护组件 (保留数据与证书)",
        "en": "Uninstall daemon components for the domain (data and certs preserved)",
    },
    # ── parser.error() messages ───────────────────────────────────────────────
    "err_no_domain": {
        "zh": "--domain 未指定，也未设置环境变量 WP_DOMAIN。",
        "en": "--domain not specified and WP_DOMAIN env var is not set.",
    },
    "err_no_email": {
        "zh": "--email 未指定，也未设置环境变量 WP_EMAIL。",
        "en": "--email not specified and WP_EMAIL env var is not set.",
    },
    # ── V3.0.6 新增翻译 (审计修复: 硬编码消息迁移) ──────────────────────────
    "label_database": {
        "zh": "数据库",
        "en": "Database",
    },
    "warn_global_pwd_bad_chars": {
        "zh": "全局密码文件包含非预期字符，跳过此优先级",
        "en": "Global password file contains unexpected characters; skipping this priority.",
    },
    "warn_recover_pwd_bad_chars": {
        "zh": "wp-config.php 中的 DB_PASSWORD 含非字母数字字符（本脚本仅接受 [a-zA-Z0-9]，以防 MySQL .cnf 文件注入），将重新生成密码并同步到数据库。",
        "en": "DB_PASSWORD in wp-config.php contains non-alphanumeric characters (only [a-zA-Z0-9] accepted to prevent MySQL .cnf injection); regenerating and syncing to database.",
    },
    "warn_php_version_fallback": {
        "zh": "指定的 PHP 版本 {ver} 对应的服务 {svc} 未找到，回退到自动探测。",
        "en": "PHP version {ver}: service {svc} not found; falling back to auto-detection.",
    },
    "warn_php_sock_fallback": {
        "zh": "PHP {ver} 的 socket 未找到，回退到通用探测。",
        "en": "Socket for PHP {ver} not found; falling back to generic detection.",
    },
    "info_nginx_helper_no_wpcli": {
        "zh": "💡 提示：FastCGI Cache 已启用，但 WP-CLI 不可用，无法自动安装 nginx-helper 插件。建议手动安装该插件以实现发布文章时自动清除缓存。",
        "en": "💡 Tip: FastCGI Cache is enabled but WP-CLI is unavailable. Install the nginx-helper plugin manually to enable cache purging on post publish.",
    },
    "warn_nginx_helper_activate_fail": {
        "zh": "nginx-helper 插件已安装但激活失败，请在 WordPress 后台手动激活。",
        "en": "nginx-helper plugin is installed but activation failed; please activate it manually in WordPress admin.",
    },
    "warn_nginx_helper_install_fail": {
        "zh": "nginx-helper 插件安装失败。建议在 WordPress 后台手动安装 nginx-helper 插件，以实现发布文章时自动清除 Nginx FastCGI 缓存。",
        "en": "nginx-helper plugin installation failed. Install it manually in WordPress admin for automatic Nginx FastCGI cache purging.",
    },
    "warn_wpcli_sha512_mismatch": {
        "zh": "  [{mirror}] SHA-512 校验不匹配，尝试下一镜像。",
        "en": "  [{mirror}] SHA-512 checksum mismatch; trying next mirror.",
    },
    "warn_wpcli_checksums_failed": {
        "zh": "WP-CLI verify-checksums 校验未通过: {detail}",
        "en": "WP-CLI verify-checksums failed: {detail}",
    },
    "warn_wpcli_checksums_continue": {
        "zh": "⚠️ WP-CLI verify-checksums 未通过，部分核心文件可能被修改。基础完整性已通过，继续部署。",
        "en": "⚠️ WP-CLI verify-checksums failed; some core files may be modified. Basic integrity passed; continuing deployment.",
    },
    "warn_wp_hash_bad": {
        "zh": "⚠️ [{name}] hash 文件内容异常，切换备用节点...",
        "en": "⚠️ [{name}] Hash file content invalid; switching to fallback source...",
    },
    "warn_svc_enable_fail": {
        "zh": "服务 {svc} 启用失败 (错误分类: {code})，继续尝试其余服务。",
        "en": "Service {svc} failed to start (category: {code}); continuing with remaining services.",
    },
    "warn_db_timeout_continue": {
        "zh": "数据库服务超时未就绪，仍尝试继续初始化。若后续 SQL 操作失败，请检查数据库服务状态或增大 --db-wait-timeout。",
        "en": "Database service not ready after timeout; proceeding with initialization. If SQL operations fail, check the database service or increase --db-wait-timeout.",
    },
    "warn_recover_pwd_verify_fail": {
        "zh": "wp-config.php 中的密码无法连接数据库，将使用新密码并同步到数据库和 wp-config.php。",
        "en": "Password in wp-config.php cannot connect to the database; using a new password and syncing to database and wp-config.php.",
    },
    "info_health_ok": {
        "zh": "✅ 站点健康检查通过 (HTTP {code}，第 {attempt} 次)。",
        "en": "✅ Site health check passed (HTTP {code}, attempt {attempt}).",
    },
    "warn_health_conn_fail": {
        "zh": "健康检查第 {attempt}/{total} 次：连接失败 (HTTP 000)，{interval}s 后重试...",
        "en": "Health check attempt {attempt}/{total}: connection failed (HTTP 000), retrying in {interval}s...",
    },
    "warn_health_bad_code": {
        "zh": "健康检查第 {attempt}/{total} 次：HTTP {code}，{interval}s 后重试...",
        "en": "Health check attempt {attempt}/{total}: HTTP {code}, retrying in {interval}s...",
    },
    "warn_health_exception": {
        "zh": "健康检查第 {attempt}/{total} 次异常: {e}",
        "en": "Health check attempt {attempt}/{total} exception: {e}",
    },
    "warn_health_final": {
        "zh": "⚠️ 站点健康检查未通过（{retries} 次重试后）。\n   站点可能需要更长时间启动，或需要完成 WordPress 初始化向导。\n   请手动访问 https://{domain}/ 确认。",
        "en": "⚠️ Site health check failed after {retries} retries.\n   The site may need more time to start, or may require the WordPress setup wizard.\n   Please visit https://{domain}/ manually.",
    },
    "info_wp_not_installed": {
        "zh": "WP-CLI 报告 WordPress 尚未完成安装 — 这是正常的，请访问网站完成 WordPress 初始化向导。",
        "en": "WP-CLI reports WordPress is not yet installed — this is normal. Visit the site to complete the WordPress setup wizard.",
    },
    "info_redis_manual": {
        "zh": "Redis 已安装但 WP-CLI 不可用。请手动安装插件:\n  wp plugin install redis-cache --activate --allow-root\n  wp redis enable --allow-root",
        "en": "Redis installed but WP-CLI unavailable. Install the plugin manually:\n  wp plugin install redis-cache --activate --allow-root\n  wp redis enable --allow-root",
    },
    "warn_redis_dropin_fail": {
        "zh": "Redis drop-in 启用失败, 可能需手动执行: wp redis enable --allow-root",
        "en": "Redis drop-in activation failed; try manually: wp redis enable --allow-root",
    },
    "info_nginx_listen_detected": {
        "zh": "检测到 Nginx listen 绑定 {addr}:80，使用该地址进行 HTTP challenge 预检。",
        "en": "Detected Nginx listen binding on {addr}:80; using this address for HTTP challenge preflight.",
    },
    "warn_http_challenge_curl_detail": {
        "zh": "HTTP challenge 预检：curl 返回码={rc}，内容匹配={match}",
        "en": "HTTP challenge preflight: curl returncode={rc}, content match={match}",
    },
    "warn_dns_fail": {
        "zh": "❌ DNS 预检失败：{domain} 无法解析。\n   请确认域名 A/AAAA 记录已正确指向本服务器 IP。",
        "en": "❌ DNS preflight failed: {domain} cannot be resolved.\n   Verify that A/AAAA records point to this server's IP.",
    },
    "info_cert_skip_www": {
        "zh": "ℹ️  www.{domain} DNS 未解析，证书申请仅包含主域名。",
        "en": "ℹ️  www.{domain} DNS not resolved; certificate request will cover main domain only.",
    },
    "info_renew_domains_from_cert": {
        "zh": "ℹ️  从已有证书读取域名列表: {domains}",
        "en": "ℹ️  Domain list read from existing certificate: {domains}",
    },
    "info_renew_cert_not_found_www": {
        "zh": "ℹ️  未找到已有证书，续期将包含 www 子域。",
        "en": "ℹ️  No existing certificate found; renewal will include www subdomain.",
    },
    "warn_backup_gz_fail": {
        "zh": "备份文件完整性校验失败: {name} ({detail})",
        "en": "Backup file integrity check failed: {name} ({detail})",
    },
    "info_backup_cleanup_summary": {
        "zh": "备份清理完成：保留最近 {keep} 份，删除 {removed} 份旧备份。",
        "en": "Backup cleanup complete: kept {keep} most recent, removed {removed} old backups.",
    },
    "warn_restore_db_fail": {
        "zh": "数据库恢复可能失败: {err}",
        "en": "Database restore may have failed: {err}",
    },
    # ── V3.0.7 新增翻译 ─────────────────────────────────────────────────
    "label_yes": {
        "zh": "是",
        "en": "yes",
    },
    "label_no": {
        "zh": "否",
        "en": "no",
    },
    "info_restore_config_hint": {
        "zh": "💡 提示：恢复操作已从备份还原 Nginx 配置。"
              "若需将配置模板更新至最新版本（如脚本升级后），请执行:\n"
              "   python3 {script} update --domain {domain}"
              " [--cache fastcgi] [--redis] [--allow-xmlrpc]",
        "en": "💡 Tip: Nginx config has been restored from backup. "
              "To update config templates to the latest version "
              "(e.g. after script upgrade), run:\n"
              "   python3 {script} update --domain {domain}"
              " [--cache fastcgi] [--redis] [--allow-xmlrpc]",
    },
}


def t(key: str, **kwargs) -> str:
    """Return the message for the current locale, formatted with kwargs.

    Falls back to the Chinese variant if no English translation exists,
    and falls back to the key string itself if the key is not found at all.
    This ensures the script never crashes due to a missing translation.
    """
    entry = _MESSAGES.get(key)
    if entry is None:
        return key  # graceful: return the key as-is
    msg = entry.get(_LANG)
    if msg is None:
        msg = entry.get("zh")
    if msg is None:
        msg = key
    return msg.format(**kwargs) if kwargs else msg


# [V2.9.0 修复] 禁用 Core dump 防止内存泄露
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except Exception:
    pass

# [V2.9.5] 进程级 dumpable 禁用：即使 /proc/sys/kernel/core_pattern 被配置，
# 也阻止 /proc/self/mem 被其他进程读取（需 CAP_SYS_PTRACE 才能绕过）。
try:
    import ctypes
    _PR_SET_DUMPABLE = 4
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0)
except Exception:
    pass

# ---------------------------------------------------------------------------
# 全局日志初始化
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,  # [V2.9.5] 日志输出到 stderr，避免与 stdout 数据流混杂
)


# ---------------------------------------------------------------------------
# 命令执行结果（借鉴 sooth_monitor 错误分类体系）
# ---------------------------------------------------------------------------
class CmdResult:
    """命令执行结果，携带错误分类信息和命令输出。

    通过 __bool__ 返回 self.ok，保持与原 bool 返回值的向后兼容：
        if self.run_cmd([...]):   # 仍然有效
    需要详细信息时：
        result = self.run_cmd([...])
        if result.code == CmdResult.TIMEOUT: ...
        print(result.stdout)   # 命令标准输出
    """
    # 错误分类常量
    SUCCESS    = 0   # 命令成功
    RETRYABLE  = 1   # 暂时性错误，可重试
    TIMEOUT    = 2   # 执行超时
    PERMISSION = 3   # 权限不足
    FATAL      = 4   # 不可恢复的致命错误

    def __init__(self, ok: bool, code: int = 0, stdout: str = "", stderr: str = ""):
        self.ok = ok
        self.code = code if not ok else self.SUCCESS
        self.stdout = stdout
        self.stderr = stderr

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        labels = {0: "SUCCESS", 1: "RETRYABLE", 2: "TIMEOUT", 3: "PERMISSION", 4: "FATAL"}
        return f"CmdResult(ok={self.ok}, code={labels.get(self.code, self.code)})"

    @staticmethod
    def success(stdout: str = "") -> "CmdResult":
        return CmdResult(ok=True, code=CmdResult.SUCCESS, stdout=stdout)

    @staticmethod
    def classify_stderr(stderr: str) -> int:
        """根据 stderr 内容推断错误类别。"""
        err = stderr.lower()
        # 权限类
        if any(k in err for k in (
            "permission denied", "access denied", "operation not permitted",
            "authentication required", "unauthorized",
        )):
            return CmdResult.PERMISSION
        # 致命类（不可重试）
        if any(k in err for k in (
            "no space left on device", "read-only file system",
            "command not found", "no such file or directory",
            "syntax error", "invalid option",
        )):
            return CmdResult.FATAL
        # 超时类
        if any(k in err for k in ("timeout", "timed out")):
            return CmdResult.TIMEOUT
        # 默认为可重试
        return CmdResult.RETRYABLE


# ---------------------------------------------------------------------------
# 站点配置数据类
# ---------------------------------------------------------------------------
class SiteConfig:
    # 磁盘空间阈值 (MB)
    MIN_DISK_FREE_MB_DOWNLOAD = 500   # WordPress 下载+解压最低要求
    MIN_DISK_FREE_MB_EXTRACT  = 200   # 解压前二次检查

    def __init__(self, args):
        self.domain = args.domain.lower().strip()
        if not re.match(r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$', self.domain):
            print(t("err_domain_fmt", domain=self.domain))
            sys.exit(1)
        # [V2.9.5] DNS 规范最大 253 字符，防止超长域名触发下游缓冲区异常
        if len(self.domain) > 253:
            print(t("err_domain_len", n=len(self.domain)))
            sys.exit(1)

        # email 仅 deploy 子命令必填，renew / uninstall 可省略
        raw_email = getattr(args, 'email', None) or ''
        self.email = raw_email.lower().strip()
        if self.email and not re.match(r'^[^@]+@[^@]+\.[^@]+$', self.email):
            print(t("err_email_fmt", email=self.email))
            sys.exit(1)

        sanitized_id = re.sub(r'[^a-z0-9_]', '_', self.domain)
        sanitized_id = re.sub(r'_{2,}', '_', sanitized_id).strip('_')

        self.db_name = f"wp_{sanitized_id}"[:64]
        self.db_user = f"u_{sanitized_id}"[:32]

        # 严格白名单字符集（纯字母数字），保证不可能注入 SQL 或 .cnf 转义问题
        safe_chars = string.ascii_letters + string.digits
        self.db_pass = ''.join(secrets.choice(safe_chars) for _ in range(32))  # [V2.9.0 修复] 提升至 32 字节

        self.webroot_path = Path(f"{self._detect_webroot_base()}/{self.domain}")
        self.nginx_conf = Path(f"/etc/nginx/conf.d/{self.domain}.conf")

        run_dir = Path("/run")
        if not run_dir.exists():
            run_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = run_dir / f"{sanitized_id}_ssl_manager.lock"

        self.systemd_prefix = sanitized_id
        self.service_file = Path(f"/etc/systemd/system/{self.systemd_prefix}-ssl.service")
        self.timer_file = Path(f"/etc/systemd/system/{self.systemd_prefix}-ssl.timer")
        self.script_path = Path(os.path.abspath(__file__))

        self.dry_run = args.dry_run
        self.staging = args.staging
        self.cache_mode = getattr(args, 'cache', 'none') or 'none'
        self.redis_cache = getattr(args, 'redis', False)  # [V2.9.8] Redis 对象缓存
        self.skip_deps = getattr(args, 'skip_deps', False)  # [V3.0.0] 跳过依赖安装
        self.allow_xmlrpc = getattr(args, 'allow_xmlrpc', False)  # [V3.0.3] 可选放开 XML-RPC
        self.php_version = getattr(args, 'php_version', None) or None

        # [V3.0.4] 备份根目录：CLI --backup-dir > 环境变量 WP_BACKUP_DIR > 默认 /root/backups
        # 允许用户将备份写入外挂数据盘（如 /data/backups），对开源部署场景更友好。
        _cli_backup_dir  = getattr(args, 'backup_dir', None) or ''
        _env_backup_dir  = os.environ.get('WP_BACKUP_DIR', '').strip()
        _backup_base_raw = _cli_backup_dir or _env_backup_dir or '/root/backups'
        self.backup_base_dir = Path(_backup_base_raw)
        self.db_root_pass_input = getattr(args, 'db_root_pass', None) or \
            os.environ.get('WP_DB_ROOT_PASS') or None
        self.db_host = getattr(args, 'db_host', None) or \
            os.environ.get('WP_DB_HOST') or 'localhost'
        self.persist_root_pwd = getattr(args, 'persist_root_pwd', False)
        # V2.7.1: db_host 白名单校验，防止 SQL 注入与命令注入
        if not re.fullmatch(r'[a-zA-Z0-9._:\[\]-]+', self.db_host):
            print(t("err_dbhost_fmt", host=self.db_host))
            sys.exit(1)

        # 数据库等待超时：CLI 参数 > 环境变量 WP_DB_WAIT_TIMEOUT > 默认值（函数内决策）
        _cli_timeout = getattr(args, 'db_wait_timeout', None)
        _env_timeout = os.environ.get('WP_DB_WAIT_TIMEOUT', '')
        if _cli_timeout is not None:
            self.db_wait_timeout = int(_cli_timeout)
        elif _env_timeout:
            # [V2.9.5] 使用 try/except 替代 isdigit()，兼容前导 0 等边界输入
            try:
                self.db_wait_timeout = int(_env_timeout)
            except ValueError:
                print(t("warn_timeout_env", val=_env_timeout))
                self.db_wait_timeout = None
        else:
            self.db_wait_timeout = None  # 由 _wait_db_ready 根据 is_external_db 决定

        # V2.8.0: 校验超时值为正整数，防止 range() 空迭代跳过等待
        if self.db_wait_timeout is not None and self.db_wait_timeout < 1:
            print(t("err_timeout_val", val=self.db_wait_timeout))
            sys.exit(1)

    @property
    def is_external_db(self) -> bool:
        """判断是否使用外置数据库（非本机）。"""
        return self.db_host not in ('localhost', '127.0.0.1', '::1')

    @staticmethod
    def _detect_webroot_base() -> str:
        """根据发行版选择 Nginx 站点根目录基准路径。
        Debian/Ubuntu: /var/www/html  (apt 体系惯例)
        RHEL/CentOS:   /usr/share/nginx/html  (yum/dnf 体系惯例)

        V2.8.0: 优先从 /etc/os-release 识别发行版族系，
        避免安装了 apt 的非 Debian 系统（如 Arch）误判。"""
        # 优先级 1: /etc/os-release（最可靠的发行版标识）
        try:
            _osr = Path('/etc/os-release').read_text(encoding='utf-8').lower()
            # ID_LIKE 包含 debian 的衍生版（Ubuntu/Mint/Deepin）
            if 'id_like' in _osr:
                _like = re.search(r'^id_like\s*=\s*"?([^"\n]+)', _osr, re.MULTILINE)
                if _like and 'debian' in _like.group(1):
                    return "/var/www/html"
                if _like and any(d in _like.group(1) for d in ('rhel', 'fedora', 'centos')):
                    return "/usr/share/nginx/html"
            # 直接匹配 ID
            _id = re.search(r'^id\s*=\s*"?([^"\n]+)', _osr, re.MULTILINE)
            if _id:
                _id_val = _id.group(1).strip()
                if _id_val in ('debian', 'ubuntu', 'linuxmint', 'deepin', 'pop', 'kali'):
                    return "/var/www/html"
        except Exception:
            pass
        # 优先级 2: 包管理器探测（回退）
        if shutil.which("apt"):
            return "/var/www/html"
        return "/usr/share/nginx/html"

    @staticmethod
    def validate_sql_identifier(name: str) -> bool:
        """校验数据库名/用户名：仅允许字母、数字、下划线，防止 SQL 注入。"""
        return bool(re.fullmatch(r'[a-zA-Z0-9_]+', name))

    @staticmethod
    def validate_sql_password(password: str) -> bool:
        """校验自动生成的数据库密码：严格纯字母数字字符集。"""
        return bool(re.fullmatch(r'[a-zA-Z0-9]+', password))

# ---------------------------------------------------------------------------
# Nginx 配置生成（纯函数，方便单元测试）
# ---------------------------------------------------------------------------
def generate_http_only_config(domain: str, webroot: Path) -> str:
    return (
        f"server {{\n"
        f"    listen 80;\n"
        f"    listen [::]:80;\n"
        f"    server_name {domain} www.{domain};\n"
        f"    root {webroot};\n"
        f"    server_tokens off;\n"  # [V3.0.9] B6
        f"    location ^~ /.well-known/acme-challenge/ {{ allow all; default_type \"text/plain\"; }}\n"
        f"    location / {{ index index.php index.html index.htm; }}\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# Nginx 配置生成 — 模板片段函数 (V3.0.0 重构)
# ---------------------------------------------------------------------------
# 将原先 150 行的巨型 f-string 拆分为独立片段函数。
# 每个片段可独立测试、独立修改，新增 Nginx 指令只需编辑对应片段。
# generate_https_config() 负责组装，保持对外接口不变。
# ---------------------------------------------------------------------------

def _nginx_safe_name(domain: str) -> str:
    """域名 → Nginx 安全标识符 (缓存路径/rate limit zone 名称)。"""
    name = re.sub(r'[^a-z0-9_]', '_', domain)
    return re.sub(r'_{2,}', '_', name).strip('_')


def _nginx_preamble(domain: str, cache_mode: str, allow_xmlrpc: bool = False) -> str:
    """server{} 块外的指令: limit_req_zone + 可选 fastcgi_cache_path。"""
    safe = _nginx_safe_name(domain)
    parts = []
    if cache_mode == "fastcgi":
        parts.append(
            f"fastcgi_cache_path /var/cache/nginx/{safe} levels=1:2"
            f" keys_zone={safe}:10m max_size=256m inactive=60m use_temp_path=off;"
        )
    parts.append(
        f"limit_req_zone $binary_remote_addr zone=wplogin_{safe}:10m rate=1r/s;"
    )
    # [V3.0.3] 放开 XML-RPC 时增加独立 zone，在 PHP 被唤醒前截断暴力攻击
    if allow_xmlrpc:
        parts.append(
            f"limit_req_zone $binary_remote_addr zone=xmlrpc_{safe}:10m rate=1r/s;"
        )
    # [V3.0.2] B4: 元素不带末尾 \n, 由 join 统一换行, 消除多余空行
    return "\n".join(parts) + "\n\n"


def _nginx_http_redirect(domain: str, webroot: Path) -> str:
    """HTTP→HTTPS 重定向 server 块 + ACME challenge 通道。"""
    return (
        f"server {{\n"
        f"    listen 80;\n"
        f"    listen [::]:80;\n"
        f"    server_name {domain} www.{domain};\n"
        f"    server_tokens off;\n"  # [V3.0.10] N5: 与 generate_http_only_config B6 对齐
        f"    location ^~ /.well-known/acme-challenge/ {{ root {webroot}; allow all; }}\n"
        f"    location / {{ return 301 https://$host$request_uri; }}\n"
        f"}}\n"
    )


# [V3.0.9] B5: 探测 Nginx 版本，选择兼容的 http2 指令语法
# [V3.0.11] B4: 模块级缓存，避免 deploy/update 多次 fork nginx -v
_NGINX_HTTP2_DIRECTIVE_CACHE = None  # type: bool | None


def _detect_nginx_http2_directive() -> bool:
    """Return True when Nginx >= 1.25.1 supports the standalone 'http2 on;' directive.

    Nginx < 1.25.1 requires the http2 token inline on the listen line.
    Returns True on detection failure (safe default for modern distributions).

    [V3.0.11] B4: Result is cached at module level to avoid repeated fork.
    """
    global _NGINX_HTTP2_DIRECTIVE_CACHE
    if _NGINX_HTTP2_DIRECTIVE_CACHE is not None:
        return _NGINX_HTTP2_DIRECTIVE_CACHE
    try:
        r = subprocess.run(
            ["nginx", "-v"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=5, check=False,
        )
        m = re.search(r'nginx/(\d+)\.(\d+)\.(\d+)', r.stdout + r.stderr)
        if m:
            ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            _NGINX_HTTP2_DIRECTIVE_CACHE = ver >= (1, 25, 1)
            return _NGINX_HTTP2_DIRECTIVE_CACHE
    except Exception:
        pass
    _NGINX_HTTP2_DIRECTIVE_CACHE = True  # 默认新语法；现代发行版 Nginx 均 >= 1.25.1
    return True


def _nginx_ssl_core(domain: str, webroot: Path,
                    http2_directive: bool = True) -> str:
    """HTTPS server 块: listen/server_name/日志/基础指令。

    Args:
        http2_directive: True  → 独立 'http2 on;' 指令 (Nginx >= 1.25.1)
                         False → 内联 'listen 443 ssl http2;' (Nginx < 1.25.1)
    """
    if http2_directive:
        _listen = (
            f"    listen 443 ssl;\n"
            f"    listen [::]:443 ssl;\n"
        )
        _http2 = f"    http2 on;\n"
    else:
        _listen = (
            f"    listen 443 ssl http2;\n"
            f"    listen [::]:443 ssl http2;\n"
        )
        _http2 = ""
    return (
        f"server {{\n"
        + _listen
        + f"    server_name {domain} www.{domain};\n"
        f"    root {webroot};\n"
        + _http2
        + f"    server_tokens off;\n"
        f"\n"
        f"    access_log /var/log/nginx/{domain}.access.log combined;\n"
        f"    error_log  /var/log/nginx/{domain}.error.log;\n"
        f"\n"
        f"    index index.php index.html index.htm;\n"
        f"    client_max_body_size 100M;\n"
    )


def _nginx_gzip() -> str:
    """Gzip 压缩。"""
    return (
        f"\n"
        f"    gzip on;\n"
        f"    gzip_comp_level 5;\n"
        f"    gzip_min_length 1024;\n"
        f"    gzip_types text/plain text/css application/javascript application/json"
        f" application/x-javascript text/xml application/xml application/xml+rss"
        f" font/woff font/woff2 image/svg+xml;\n"
        f"    gzip_vary on;\n"
    )


def _nginx_security_headers(cache_mode: str = "none",
                             safe_name: str = "") -> str:
    """安全响应头: HSTS / X-Frame / CSP-RO / 可选 FastCGI 缓存头。"""
    cache_header = ""
    if cache_mode == "fastcgi":
        cache_header = f"    add_header X-FastCGI-Cache $upstream_cache_status;\n"
    return (
        f"\n"
        f"    add_header Strict-Transport-Security \"max-age=63072000; includeSubDomains; preload\" always;\n"
        f"    add_header X-Frame-Options SAMEORIGIN always;\n"
        f"    add_header X-Content-Type-Options nosniff always;\n"
        f"    add_header Referrer-Policy strict-origin-when-cross-origin always;\n"
        f"    add_header Permissions-Policy \"camera=(), microphone=(), geolocation=(), payment=()\" always;\n"
        f"    add_header Content-Security-Policy-Report-Only \"default-src 'self'; "
        f"script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        f"style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data: https:; "
        f"font-src 'self' data:; "
        f"connect-src 'self' https:; "
        f"frame-ancestors 'self';\" always;\n"
        f"{cache_header}"
    )


def _nginx_ssl_params(domain: str) -> str:
    """SSL 证书 / 协议 / 密码套件 / OCSP Stapling。"""
    return (
        f"\n"
        f"    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n"
        f"    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n"
        f"    ssl_session_timeout 1d;\n"
        f"    ssl_session_cache shared:MozSSL:10m;\n"
        f"    ssl_session_tickets off;\n"
        f"\n"
        f"    ssl_protocols TLSv1.2 TLSv1.3;\n"
        f"    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
        f"ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
        f"ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
        f"DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384:"
        f"DHE-RSA-CHACHA20-POLY1305;\n"
        f"    ssl_prefer_server_ciphers off;\n"
        f"\n"
        f"    ssl_stapling on;\n"
        f"    ssl_stapling_verify on;\n"
        f"    resolver 1.1.1.1 8.8.8.8 valid=300s;\n"
        f"    resolver_timeout 5s;\n"
    )


def _nginx_fastcgi_cache_block(safe_name: str) -> str:
    """FastCGI Cache: 跳过条件 (仅 fastcgi 模式启用)。"""
    return (
        f"\n"
        f"    set $skip_cache 0;\n"
        f"    if ($request_method = POST) {{ set $skip_cache 1; }}\n"
        f"    if ($query_string != \"\") {{ set $skip_cache 1; }}\n"
        f"    if ($request_uri ~* \"/wp-admin/|/wp-json/|/xmlrpc.php|wp-.*.php\") "
        f"{{ set $skip_cache 1; }}\n"
        f"    if ($http_cookie ~* \"comment_author|wordpress_[a-f0-9]+|"
        f"wp-postpass|wordpress_logged_in\") {{ set $skip_cache 1; }}\n"
    )


def _nginx_php_location(sock_path: str, cache_mode: str = "none",
                         safe_name: str = "") -> str:
    """PHP 处理 location 块 + 可选 FastCGI 缓存指令。"""
    cache_directives = ""
    if cache_mode == "fastcgi":
        cache_directives = (
            f"        fastcgi_cache {safe_name};\n"
            f"        fastcgi_cache_valid 200 301 302 60m;\n"
            f"        fastcgi_cache_bypass $skip_cache;\n"
            f"        fastcgi_no_cache $skip_cache;\n"
            f"        fastcgi_cache_key \"$scheme$request_method$host$request_uri\";\n"
        )
    return (
        f"\n"
        f"    location / {{ try_files $uri $uri/ /index.php?$args; }}\n"
        f"\n"
        f"    location ~ \\.php$ {{\n"
        f"        try_files $uri =404;\n"
        f"        fastcgi_pass unix:{sock_path};\n"
        f"        fastcgi_index index.php;\n"
        f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        f"        include fastcgi.conf;\n"
        f"{cache_directives}"
        f"    }}\n"
    )


def _nginx_wp_security(safe_name: str, sock_path: str,
                       allow_xmlrpc: bool = False) -> str:
    """WordPress 安全 location 块: 隐藏文件 / wp-config / uploads / rate limit / cron / xmlrpc。"""
    # [V3.0.3] xmlrpc.php 处理：默认 deny all；--allow-xmlrpc 时改为速率限制后透传 PHP-FPM
    if allow_xmlrpc:
        xmlrpc_block = (
            f"    location = /xmlrpc.php {{\n"
            f"        limit_req zone=xmlrpc_{safe_name} burst=10 nodelay;\n"
            f"        limit_req_status 429;\n"
            f"        try_files $uri =404;\n"
            f"        fastcgi_pass unix:{sock_path};\n"
            f"        fastcgi_index index.php;\n"
            f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
            f"        include fastcgi.conf;\n"
            f"    }}\n"
        )
    else:
        xmlrpc_block = (
            f"    location = /xmlrpc.php {{ deny all; access_log off; log_not_found off; }}\n"
        )
    return (
        f"\n"
        f"    location ~ /\\. {{ deny all; }}\n"
        f"    location ~* wp-config\\.php {{ deny all; return 404; }}\n"
        f"    location ~* /wp-content/uploads/.*\\.php$ {{ deny all; return 404; }}\n"
        f"    location = /wp-login.php {{\n"
        f"        limit_req zone=wplogin_{safe_name} burst=5 nodelay;\n"
        f"        limit_req_status 429;\n"
        f"        try_files $uri =404;\n"
        f"        fastcgi_pass unix:{sock_path};\n"
        f"        fastcgi_index index.php;\n"
        f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        f"        include fastcgi.conf;\n"
        f"    }}\n"
        f"    location = /wp-cron.php {{\n"
        f"        allow 127.0.0.1;\n"
        f"        allow ::1;\n"
        f"        deny all;\n"
        f"        access_log off;\n"
        f"        log_not_found off;\n"
        f"        try_files $uri =404;\n"
        f"        fastcgi_pass unix:{sock_path};\n"
        f"        fastcgi_index index.php;\n"
        f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        f"        include fastcgi.conf;\n"
        f"    }}\n"
        f"{xmlrpc_block}"
        f"    location ^~ /.well-known/acme-challenge/ {{ allow all; }}\n"
        f"}}\n"
    )


def generate_https_config(domain: str, webroot: Path, sock_path: str,
                          cache_mode: str = "none",
                          allow_xmlrpc: bool = False) -> str:
    """组装完整的 Nginx HTTPS 配置。

    V3.0.0 重构: 从 10 个独立片段函数组装，每个片段可独立测试和修改。
    V3.0.3: 新增 allow_xmlrpc 参数，控制 xmlrpc.php 是 deny 还是速率限制透传。
    对外接口 (函数签名 + 返回格式) 保持不变，所有调用点无需修改。
    """
    safe = _nginx_safe_name(domain)
    # [V3.0.9] B5: 探测一次 Nginx 版本，传入 _nginx_ssl_core
    _http2_directive = _detect_nginx_http2_directive()

    parts = [
        _nginx_preamble(domain, cache_mode, allow_xmlrpc=allow_xmlrpc),
        _nginx_http_redirect(domain, webroot),
        "\n",
        _nginx_ssl_core(domain, webroot, http2_directive=_http2_directive),
        _nginx_gzip(),
        _nginx_security_headers(cache_mode=cache_mode, safe_name=safe),
        _nginx_ssl_params(domain),
    ]

    if cache_mode == "fastcgi":
        parts.append(_nginx_fastcgi_cache_block(safe))

    parts.extend([
        _nginx_php_location(sock_path, cache_mode=cache_mode, safe_name=safe),
        _nginx_wp_security(safe, sock_path, allow_xmlrpc=allow_xmlrpc),
    ])

    return "".join(parts)


# ---------------------------------------------------------------------------
# wp-config.php 安全生成（纯函数，替代 sed）
# ---------------------------------------------------------------------------
def patch_wp_config(content: str, db_name: str, db_user: str, db_pass: str,
                     db_host: str = "localhost") -> str:
    """用 Python 正则替换 wp-config-sample.php 中的占位符，避免 sed 误匹配。
    每个占位符与其对应的 define key 精确绑定，不会跨行误替换。

    安全说明 (V2.8.0):
    · DB_HOST 的占位符 'localhost' 看似通用，但正则通过 define_key='DB_HOST'
      精确限定了只匹配 define('DB_HOST', 'localhost') 这一行，
      不会误替换其他 define 中碰巧值为 'localhost' 的行。
    · fallback 分支使用 (?:[^'\\\\]|\\\\.)* 匹配已有值（支持 PHP 转义），这是幂等重跑的预期行为。
    · 所有替换值均经过 PHP 转义（\\ 和 \'），防止 PHP define() 语法破坏。"""
    mapping = [
        ('database_name_here', 'DB_NAME', db_name),
        ('username_here',      'DB_USER', db_user),
        ('password_here',      'DB_PASSWORD', db_pass),
        ('localhost',          'DB_HOST', db_host),
    ]
    for placeholder, define_key, value in mapping:
        # 优先精确匹配占位符（wp-config-sample.php 场景）
        pattern = (
            r"(define\(\s*'"
            + re.escape(define_key)
            + r"'\s*,\s*')"
            + re.escape(placeholder)
            + r"('\s*\);)"
        )
        if re.search(pattern, content):
            # V2.7.2: 转义值中的反斜杠和单引号，防止 PHP define() 语法破坏
            _safe_v = value.replace(chr(92), chr(92)*2).replace(chr(39), chr(92)+chr(39))
            content = re.sub(pattern, lambda m, v=_safe_v: m.group(1) + v + m.group(2), content)
        else:
            # V2.7.1: 回退 — 匹配已被修改过的值（幂等重跑/非 sample 场景）
            # [V2.9.5] 使用 (?:[^'\\]|\\.)* 替代 [^']*，与 _recover_existing_db_pass
            # 保持一致，正确处理含 PHP 转义 (\') 的密码值。
            fallback = (
                r"(define\(\s*'"
                + re.escape(define_key)
                + r"'\s*,\s*')(?:[^'\\]|\\.)*('\s*\);)"
            )
            # V2.7.3: fallback 分支同样需要转义单引号和反斜杠
            _safe_fb = value.replace(chr(92), chr(92)*2).replace(chr(39), chr(92)+chr(39))
            content = re.sub(fallback, lambda m, v=_safe_fb: m.group(1) + v + m.group(2), content)
    return content


def inject_salts(content: str) -> str:
    """为 wp-config.php 注入密码学安全的 Salt 值。"""
    salt_keys = [
        'AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY',
        'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT',
    ]
    for key in salt_keys:
        salt_val = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode('ascii')
        # [V2.9.5] base64url 字符集为 [A-Za-z0-9_-=]，理论不含单引号和反斜杠。
        # [V3.0.8] S3: 改用显式 if/raise, 防止 python3 -O 跳过 assert
        if chr(39) in salt_val or chr(92) in salt_val:
            raise ValueError(
                f"base64url output contains unexpected characters: {salt_val!r}"
            )

        pattern = r"define\(\s*'" + re.escape(key) + r"'\s*,\s*'(.*?)'\s*\);"
        content = re.sub(pattern, f"define('{key}', '{salt_val}');", content)
    return content


def inject_wp_hardening(content: str) -> str:
    """[V2.9.7] 向 wp-config.php 注入安全加固常量。

    借鉴 WordOps / SlickStack / WordPress 官方加固指南：
    · DISALLOW_FILE_EDIT   — 禁用后台 PHP 编辑器，堵住攻击者代码注入路径
    · DISALLOW_UNFILTERED_HTML — 禁止管理员注入任意 HTML
    · FORCE_SSL_ADMIN      — 后台强制 HTTPS
    · WP_AUTO_UPDATE_CORE  — 自动安装安全补丁，不自动大版本升级
    · WP_POST_REVISIONS    — 限制修订版本，防止数据库膨胀
    · EMPTY_TRASH_DAYS     — 回收站 7 天自动清理

    插入位置：在 "stop editing" 注释行之前。
    幂等：已存在的 define 不会重复插入。
    """
    hardening_defines = [
        ("DISALLOW_FILE_EDIT", "true"),
        ("DISALLOW_UNFILTERED_HTML", "true"),
        ("FORCE_SSL_ADMIN", "true"),
        ("WP_AUTO_UPDATE_CORE", "'minor'"),
        ("WP_POST_REVISIONS", "10"),
        ("EMPTY_TRASH_DAYS", "7"),
    ]

    lines_to_inject = []
    for const_name, const_val in hardening_defines:
        # 幂等：跳过已存在的 define
        if f"'{const_name}'" in content or f'"{const_name}"' in content:
            continue
        lines_to_inject.append(f"define('{const_name}', {const_val});")

    if not lines_to_inject:
        return content

    inject_block = (
        "\n/* [WP-SSL-Bootstrap] Security Hardening Constants */\n"
        + "\n".join(lines_to_inject)
        + "\n"
    )

    # 优先插入到 "stop editing" 注释行之前
    marker = re.search(
        r"^/\*.*(?:stop editing|停止编辑).*\*/",
        content, re.MULTILINE | re.IGNORECASE,
    )
    if marker:
        pos = marker.start()
        return content[:pos] + inject_block + "\n" + content[pos:]

    # 回退：插入到 require_once 之前
    req_marker = content.rfind("require_once")
    if req_marker > 0:
        return content[:req_marker] + inject_block + "\n" + content[req_marker:]

    # 最终回退：追加到末尾
    return content + inject_block


def patch_wplang(content: str) -> str:
    """[V3.0.15] B6: 确保 wp-config.php 中 WPLANG 与 _LANG 一致。

    解决跨语言兜底下载问题：用户选英文但中文源先成功时，
    wp-config-sample.php 中 WPLANG='zh_CN'；反之亦然。
    此函数在生成 wp-config.php 时强制校正。
    """
    target_locale = "zh_CN" if _LANG == "zh" else ""
    # 匹配已有 define('WPLANG', '...')
    pattern = r"(define\(\s*'WPLANG'\s*,\s*')(?:[^'\\]|\\.)*('\s*\);)"
    if re.search(pattern, content):
        content = re.sub(pattern, lambda m: m.group(1) + target_locale + m.group(2), content)
    return content


# ---------------------------------------------------------------------------
# PHP 配置修改（纯函数，替代 sed）
# ---------------------------------------------------------------------------
def patch_php_ini_line(content: str, directive: str, value: str) -> str:
    """安全替换 php.ini 中的指令值。

    匹配策略（按优先级）：
    1. 已有的非注释行（直接替换值）；
    2. 被注释掉的行（取消注释并替换值）；
    3. 以上都未匹配 → 在文件末尾追加 directive = value。

    这解决了许多 Linux 发行版默认 php.ini 中指令被 ; 注释的问题，
    避免正则匹配不到导致修改静默失败。
    """
    # 优先级 1：匹配已激活（非注释）的行
    active_pattern = re.compile(
        r'^(\s*' + re.escape(directive) + r'\s*=\s*)(.+)$',
        re.MULTILINE,
    )
    if active_pattern.search(content):
        # [V2.9.5] 使用 lambda 替代 rf-string，避免 value 中的 \1 等被误解释为反向引用
        return active_pattern.sub(lambda m: m.group(1) + value, content)

    # 优先级 2：匹配被注释掉的行（;directive = ...），取消注释并设置新值
    # [V3.0.8] B1: 从 [;\s]+ 收紧为 \s*;\s*, 排除纯空白前缀的非注释行
    commented_pattern = re.compile(
        r'^\s*;\s*(' + re.escape(directive) + r'\s*=\s*)(.+)$',
        re.MULTILINE,
    )
    if commented_pattern.search(content):
        # [V2.9.5] 使用 lambda 替代 rf-string
        return commented_pattern.sub(lambda m: m.group(1) + value, content, count=1)

    # 优先级 3：未找到任何匹配行，追加到文件末尾
    appendix = f"\n{directive} = {value}\n"
    return content + appendix


def patch_php_fpm_pool_user(content: str, user: str, group: str = "") -> str:
    """安全替换 php-fpm pool 配置中的 user/group。

    Args:
        content: Pool 配置文件内容。
        user:    目标 user 指令值。
        group:   目标 group 指令值；省略时与 user 相同（常规 nginx:nginx 场景）。
    """
    # [V3.0.9] S6: 独立处理 user/group，支持两者设为不同值
    _group = group or user
    for key, _val in (('user', user), ('group', _group)):
        pattern = re.compile(
            r'^(\s*' + re.escape(key) + r'\s*=\s*)(\S+)$',
            re.MULTILINE,
        )
        # 使用默认参数捕获循环变量，避免闭包延迟绑定问题
        content = pattern.sub(lambda m, v=_val: m.group(1) + v, content)
    return content


# ---------------------------------------------------------------------------
# certbot 错误分类（借鉴 sooth_monitor 的 _docker_call 错误分类体系）
# ---------------------------------------------------------------------------
def classify_certbot_error(stderr: str) -> int:
    """对 certbot 的 stderr 输出做错误分类。

    返回值:
        CmdResult.FATAL      — 非 CA 侧致命错误（端口占用/DNS/webroot），换 CA 也无用
        CmdResult.RETRYABLE  — CA 侧错误（限流/服务端故障），值得尝试下一个 CA
        CmdResult.PERMISSION — 权限问题
    """
    err = stderr.lower()
    # 端口占用 / 绑定失败 — 换 CA 也解决不了
    if any(k in err for k in (
        "could not bind", "port 80", "address already in use",
        "problem binding to port",
    )):
        return CmdResult.FATAL
    # DNS 未解析 — 域名配置问题，换 CA 无意义
    if any(k in err for k in (
        "dns problem", "nxdomain", "no valid a records",
        "dns resolution", "could not resolve",
    )):
        return CmdResult.FATAL
    # webroot 不可达 / 验证文件无法访问
    # [V3.0.15] B3: 注释澄清——此分支的 "unauthorized" 指 ACME challenge 验证失败
    # （CA 返回 HTTP 403 "unauthorized"），属于 CA 侧交互问题，换 CA 可能成功；
    # 与下方本地文件系统 "permission denied" / "access denied" 是完全不同的错误类型。
    # "challenge failed" 同理：可能是 CA 端网络波动导致验证超时。
    # 仅 "webroot path does not exist" 确定为本地致命错误。
    if any(k in err for k in (
        "webroot path does not exist", "challenge failed",
        "404", "connection refused on port 80",
        "unauthorized", "the server could not connect",
    )):
        if "webroot path does not exist" in err:
            return CmdResult.FATAL
        return CmdResult.RETRYABLE
    # 限流 — 典型的 CA 侧问题，换 CA 有效
    if any(k in err for k in ("rate limit", "too many requests", "rate-limited")):
        return CmdResult.RETRYABLE
    # 权限
    if any(k in err for k in ("permission denied", "access denied")):
        return CmdResult.PERMISSION
    # 默认可重试
    return CmdResult.RETRYABLE


# ---------------------------------------------------------------------------
# 主部署管理器
# ---------------------------------------------------------------------------
class WPDeployManager:
    # WordPress 解压完整性校验清单（WP-CLI 不可用时的回退方案）
    WP_INTEGRITY_FILES = [
        "wp-includes/version.php",
        "wp-login.php",
        "wp-admin/index.php",
        "wp-config-sample.php",
        "index.php",
    ]

    # WP-CLI 下载镜像列表（按优先级依次尝试）
    # 主源：GitHub raw；兜底：jsDelivr CDN（在国内网络受限时可用）
    # 两个来源内容完全一致，SHA-512 校验跨源有效。
    WPCLI_MIRRORS = [
        {
            "name": "GitHub (官方)",
            "phar": "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
            "hash": "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar.sha512",
        },
        {
            "name": "jsDelivr CDN (国内兜底)",
            "phar": "https://cdn.jsdelivr.net/gh/wp-cli/builds@gh-pages/phar/wp-cli.phar",
            "hash": "https://cdn.jsdelivr.net/gh/wp-cli/builds@gh-pages/phar/wp-cli.phar.sha512",
        },
    ]
    WPCLI_INSTALL_PATH  = Path("/usr/local/bin/wp")

    # 部署预检 / 健康检查配置
    DNS_CHECK_TIMEOUT     = 10   # dig 超时秒数
    CHALLENGE_TEST_DELAY  = 2    # 写入测试文件后等待秒数
    HEALTH_CHECK_RETRIES  = 5    # 站点健康检查最大重试次数
    HEALTH_CHECK_INTERVAL = 5    # 每次重试间隔秒数
    HEALTH_CHECK_TIMEOUT  = 10   # curl 超时秒数

    # CA 容灾列表 (staging 模式下仅使用 Let's Encrypt Staging)
    # 注意：ZeroSSL 需要 EAB 预注册，不适合作为免配置 fallback，故不纳入。
    CA_PROVIDERS = [
        {"name": "Let's Encrypt",  "server": None},
        {"name": "BuyPass Go",     "server": "https://api.buypass.com/acme/directory"},
    ]

    def __init__(self, cfg: SiteConfig):
        self.cfg = cfg
        self.lock_fd = None
        self.global_lock_fd = None
        self._cleanup_done = False
        self._exit_code = 0
        self._shutdown_requested = False
        # V2.1: systemd_mode 已被 CLI 子命令 (deploy/renew/uninstall) 显式替代
        self.global_root_pwd_file = Path("/root/.mariadb_root.pwd")
        self.db_root_pass = ""
        self._wpcli_bin: str = ""  # WP-CLI 可执行路径（空 = 不可用）
        self._rollback_stack = []  # 部署事务栈：后进先出回滚

        self.pkg_mgr = self._detect_pkg_manager()
        self.nginx_user = self._detect_nginx_user()
        # --php-version 覆盖自动探测
        if self.cfg.php_version:
            self.php_fpm_svc = self._resolve_php_fpm_service(self.cfg.php_version)
        else:
            self.php_fpm_svc = self._detect_php_fpm_service()
        self.db_svc = self._detect_db_service()

    # -----------------------------------------------------------------------
    # 环境探测
    # -----------------------------------------------------------------------
    def _detect_pkg_manager(self) -> str:
        for pm in ("dnf", "yum", "apt"):
            if shutil.which(pm):
                return pm
        logging.error(t("err_no_pkg_mgr"))
        sys.exit(1)

    def _detect_nginx_user(self) -> str:
        conf_path = Path("/etc/nginx/nginx.conf")
        if conf_path.exists():
            try:
                with open(conf_path, 'r') as f:
                    for line in f:
                        match = re.match(r'^\s*user\s+([a-zA-Z0-9_-]+)\s*;', line)
                        if match:
                            return match.group(1)
            except Exception:
                pass
        try:
            pwd.getpwnam("nginx")
            return "nginx"
        except KeyError:
            pass
        return "www-data" if self.pkg_mgr == "apt" else "nginx"

    def _detect_php_fpm_service(self) -> str:
        # 优先检查已激活的服务（最准确）
        # V2.7.1: 收集所有已激活的 php-fpm 服务，按版本号降序取最高版本
        try:
            r = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=active", "--no-legend"],
                stdout=subprocess.PIPE, universal_newlines=True, check=False, timeout=10,
            )
            active_candidates = []
            for line in r.stdout.splitlines():
                # V2.7.2: 收紧匹配，排除 php-fpm-exporter 等非 FPM 服务
                if re.search(r"php[\d]*(?:\.\d+)*-?fpm\.service", line):
                    active_candidates.append(line.split()[0].replace(".service", ""))
            if active_candidates:
                active_candidates.sort(
                    key=lambda s: self._extract_php_version(s), reverse=True,
                )
                return active_candidates[0]
        except Exception:
            pass
        # 回退：扫描已安装的 unit 文件（即使服务未启动也能识别）
        try:
            r = subprocess.run(
                ["systemctl", "list-unit-files", "--type=service", "--no-legend"],
                stdout=subprocess.PIPE, universal_newlines=True, check=False, timeout=10,
            )
            # 收集所有匹配的 php*fpm 服务，取版本号最高的
            candidates = []
            for line in r.stdout.splitlines():
                # V2.7.2: 收紧匹配，排除 php-fpm-exporter 等非 FPM 服务
                if re.search(r"php[\d]*(?:\.\d+)*-?fpm\.service", line):
                    svc_name = line.split()[0].replace(".service", "")
                    candidates.append(svc_name)
            if candidates:
                # 按版本号降序：php8.3-fpm > php8.2-fpm > php-fpm
                candidates.sort(key=lambda s: self._extract_php_version(s), reverse=True)
                return candidates[0]
        except Exception:
            pass
        # 最终 fallback：按发行版惯例猜测
        return "php-fpm" if self.pkg_mgr in ("dnf", "yum") else "php8.1-fpm"

    @staticmethod
    def _extract_php_version(svc_name: str) -> tuple:
        """从服务名中提取 PHP 版本号用于排序。
        php8.3-fpm → (8, 3)    php-fpm → (0, 0)"""
        m = re.search(r'php(\d+)\.(\d+)', svc_name)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (0, 0)

    def _resolve_php_fpm_service(self, version: str) -> str:
        """根据用户指定的 PHP 版本号解析 FPM 服务名。
        version: "8.2" / "7.4" 等。回退到自动探测。"""
        # Debian/Ubuntu: php8.2-fpm    RHEL/CentOS: php-fpm (通常只有一个版本)
        if self.pkg_mgr == "apt":
            candidate = f"php{version}-fpm"
        else:
            candidate = "php-fpm"

        # 验证服务存在
        try:
            r = subprocess.run(
                ["systemctl", "list-unit-files", f"{candidate}.service"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                universal_newlines=True, check=False, timeout=10,
            )
            if r.returncode == 0 and f"{candidate}.service" in r.stdout:
                logging.info(t("info_php_version_forced", ver=candidate))
                return candidate
        except Exception:
            pass

        logging.warning(t("warn_php_version_fallback", ver=version, svc=candidate))
        return self._detect_php_fpm_service()

    def _detect_db_service(self) -> str:
        for svc in ("mariadb", "mysql", "mysqld"):
            try:
                r = subprocess.run(
                    ["systemctl", "list-unit-files", f"{svc}.service"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, check=False,
                )
                if r.returncode == 0 and f"{svc}.service" in r.stdout:
                    return svc
            except Exception:
                pass
        return "mariadb"

    def _get_php_ini_paths(self) -> list:
        paths = ["/etc/php.ini"]
        paths.extend(glob.glob("/etc/php/*/fpm/php.ini"))
        return [p for p in paths if os.path.exists(p)]

    def _get_php_conf_paths(self) -> list:
        paths = ["/etc/php-fpm.d/www.conf"]
        paths.extend(glob.glob("/etc/php/*/fpm/pool.d/www.conf"))
        return [p for p in paths if os.path.exists(p)]

    def get_php_sock_path(self) -> str:
        # 用户指定 PHP 版本时，优先查找版本化 sock 路径
        if self.cfg.php_version:
            ver = self.cfg.php_version
            version_sock_candidates = [
                f"/run/php/php{ver}-fpm.sock",           # Debian/Ubuntu
                f"/var/run/php/php{ver}-fpm.sock",       # Debian 旧版
                f"/run/php-fpm/php{ver}-fpm.sock",       # 部分 RHEL
            ]
            for sock in version_sock_candidates:
                if Path(sock).exists():
                    logging.info(t("info_php_socket_forced", ver=ver, sock=sock))
                    return sock
            # 版本化 sock 不存在时，尝试从版本化 pool 配置中读取
            ver_conf = f"/etc/php/{ver}/fpm/pool.d/www.conf"
            if os.path.exists(ver_conf):
                try:
                    with open(ver_conf, 'r') as f:
                        for line in f:
                            m = re.match(r'^\s*listen\s*=\s*(/.+\.sock)\s*', line)
                            if m:
                                logging.info(t("info_php_socket_from_conf", conf=ver_conf, sock=m.group(1)))
                                return m.group(1)
                except Exception:
                    pass
            logging.warning(t("warn_php_sock_fallback", ver=ver))
        for conf in self._get_php_conf_paths():
            try:
                with open(conf, 'r') as f:
                    for line in f:
                        m = re.match(r'^\s*listen\s*=\s*(/.+\.sock)\s*', line)
                        if m:
                            return m.group(1)
            except Exception:
                pass
        return "/run/php-fpm/www.sock"

    # -----------------------------------------------------------------------
    # 磁盘空间工具（借鉴 sooth_monitor._get_disk_free_mb）
    # -----------------------------------------------------------------------
    @staticmethod
    def get_disk_free_mb(path: Path) -> int:
        """返回指定路径所在分区的可用空间 (MB)，失败返回 0。"""
        try:
            # path 可能尚不存在，向上查找第一个存在的父目录
            check_path = path
            while not check_path.exists() and check_path.parent != check_path:
                check_path = check_path.parent
            usage = shutil.disk_usage(str(check_path))
            return usage.free // (1024 * 1024)
        except OSError:
            return 0

    def check_disk_space(self, path: Path, required_mb: int, label: str) -> bool:
        """检查磁盘可用空间是否满足最低要求。"""
        free_mb = self.get_disk_free_mb(path)
        if free_mb < required_mb:
            logging.error(t("err_disk_low", label=label, path=path, free=free_mb, need=required_mb))
            return False
        logging.info(t("info_disk_ok", label=label, free=free_mb))
        return True

    # -----------------------------------------------------------------------
    # 信号处理（标志位模式）
    # -----------------------------------------------------------------------
    def setup_signals(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        # V2.8.0 竞态说明：CPython 的 GIL 保证信号处理函数在主线程的两个
        # bytecode 指令之间原子执行。_shutdown_requested 和 _exit_code 的
        # 赋值在 GIL 保护下不会与主线程产生数据竞争。
        # 在非 CPython 实现（如 PyPy、GraalPy）上理论上存在竞态，
        # 但本脚本仅支持 CPython。
        sig_name = signal.Signals(signum).name
        logging.warning(t("warn_signal", sig=sig_name))
        self._shutdown_requested = True
        # V2.7.2: 仅在无更具体错误码时设置信号退出码
        if self._exit_code == 0:
            self._exit_code = 128 + signum

    def check_shutdown(self) -> bool:
        return self._shutdown_requested

    # -----------------------------------------------------------------------
    # 部署事务栈：回滚能力
    # -----------------------------------------------------------------------
    def _register_rollback(self, description: str, action):
        """注册一个回滚动作（后进先出）。action 为无参 callable。"""
        self._rollback_stack.append((description, action))

    def _rollback_deploy(self):
        """部署失败时执行回滚：按注册的逆序依次执行清理动作。
        仅在首次部署失败时调用，幂等重跑时不回滚（已有资源会被复用）。"""
        if not self._rollback_stack:
            return
        logging.warning(t("warn_rollback_start"))
        while self._rollback_stack:
            desc, action = self._rollback_stack.pop()
            try:
                logging.info(t("info_rollback_item", desc=desc))
                action()
            except Exception as e:
                logging.warning(t("warn_rollback_item", desc=desc, e=e))
        logging.info(t("info_rollback_done"))

    # -----------------------------------------------------------------------
    # 进程锁
    # -----------------------------------------------------------------------
    def cleanup_and_exit(self, exit_code: int = 0):
        if self._cleanup_done:
            return
        self._cleanup_done = True
        # [V2.9.1] 释放全局部署锁
        if self.global_lock_fd:
            try:
                fcntl.flock(self.global_lock_fd, fcntl.LOCK_UN)
                self.global_lock_fd.close()
            except OSError:
                pass
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()
                if self.cfg.lock_file.exists():
                    self.cfg.lock_file.unlink()
            except OSError:
                pass
        final_code = exit_code if exit_code != 0 else self._exit_code
        logging.info(t("info_exit", code=final_code))
        # 恢复信号为默认处理，防止清理过程中再次收到信号导致递归
        # （借鉴 sooth_monitor._cleanup_and_exit 的防递归设计）
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        sys.exit(final_code)

    def acquire_lock(self):
        try:
            self.global_lock_fd = open("/run/wp-bootstrap.lock", 'w')
            fcntl.flock(self.global_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.error(t("err_lock_global"))
            sys.exit(1)

        try:
            self.lock_fd = open(self.cfg.lock_file, 'w')
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()
        except BlockingIOError:
            # 锁被占用——检查持有者进程是否仍在运行 (SIGKILL 残留检测)
            stale = False
            try:
                with open(self.cfg.lock_file, 'r') as f:
                    old_pid = int(f.read().strip())
                # 向进程发送信号 0：不杀进程，仅检测是否存在
                os.kill(old_pid, 0)
            except (ValueError, OSError):
                # ValueError: 文件内容不是合法 PID
                # OSError (ESRCH): 进程不存在 → 锁文件为残留物
                stale = True

            if stale:
                logging.warning(t("warn_lock_stale"))
                try:
                    self.lock_fd.close()
                except OSError:
                    pass
                try:
                    self.cfg.lock_file.unlink()
                except OSError:
                    pass
                # 重试一次
                try:
                    self.lock_fd = open(self.cfg.lock_file, 'w')
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.lock_fd.write(str(os.getpid()))
                    self.lock_fd.flush()
                    return
                except BlockingIOError:
                    pass  # 仍然失败，走下面的错误退出
            logging.error(t("err_lock_domain", domain=self.cfg.domain))
            # [V3.0.15] B4: per-domain 锁获取失败时显式释放已持有的全局锁，
            # 避免 sys.exit() 依赖内核隐式释放，保持资源清理的显式性。
            try:
                if self.global_lock_fd:
                    fcntl.flock(self.global_lock_fd, fcntl.LOCK_UN)
                    self.global_lock_fd.close()
                    self.global_lock_fd = None
            except OSError:
                pass
            sys.exit(1)

    # -----------------------------------------------------------------------
    # 命令执行（返回 CmdResult，借鉴 sooth_monitor 错误分类体系）
    # -----------------------------------------------------------------------
    def run_cmd(self, cmd_list: list, timeout: int = 300, quiet: bool = False,
                sensitive: bool = False) -> CmdResult:
        """执行外部命令，返回带错误分类的 CmdResult。

        通过 CmdResult.__bool__() 保持向后兼容：
            if self.run_cmd([...]):  # 等同于 if result.ok
        需要错误分类时：
            result = self.run_cmd([...])
            if result.code == CmdResult.TIMEOUT: ...

        Args:
            sensitive: True 时日志仅输出命令名，隐藏完整参数。
        """
        if self.cfg.dry_run:
            _log_cmd = cmd_list[0] if sensitive else ' '.join(cmd_list)
            logging.info(t("dry_run_cmd", cmd=_log_cmd))
            return CmdResult.success()
        if not quiet:
            # [V2.9.5] sensitive=True 时脱敏，仅记录命令名
            _log_cmd = f"{cmd_list[0]} {t('label_args_redacted')}" if sensitive else ' '.join(cmd_list)
            logging.info(t("info_run_cmd", cmd=_log_cmd))
        try:
            r = subprocess.run(
                cmd_list,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                timeout=timeout, check=False,
            )
            if r.returncode == 0:
                if not quiet and r.stdout.strip():
                    logging.info(r.stdout.strip())
                if not quiet and r.stderr.strip():
                    logging.warning(f"[STDERR_WARN] {cmd_list[0]}: {r.stderr.strip()}")
                return CmdResult.success(stdout=r.stdout.strip())
            # 命令失败 — 分类错误
            stderr_text = r.stderr.strip()
            error_code = CmdResult.classify_stderr(stderr_text)
            if not quiet:
                logging.error(t("err_cmd_failed", cmd=cmd_list[0], code=error_code, stderr=stderr_text))
            return CmdResult(ok=False, code=error_code, stdout=r.stdout.strip(), stderr=stderr_text)
        except subprocess.TimeoutExpired:
            # [V2.9.6] 超时路径同样遵守 sensitive 脱敏
            _t_cmd = f"{cmd_list[0]} {t('label_args_redacted')}" if sensitive else ' '.join(cmd_list)
            logging.error(t("err_cmd_timeout", cmd=_t_cmd))
            return CmdResult(ok=False, code=CmdResult.TIMEOUT, stderr="timeout")
        except Exception as e:
            logging.error(t("err_cmd_exception", e=e))
            return CmdResult(ok=False, code=CmdResult.FATAL, stderr=str(e))

    # -----------------------------------------------------------------------
    # SQL 执行（密码通过 --defaults-extra-file 传递）
    # -----------------------------------------------------------------------
    def _write_mysql_defaults_file(self, password: str) -> str:
        """将数据库密码写入临时 .cnf 文件，返回路径。调用方负责删除。
        注意：当前密码字符集严格限定为 [a-zA-Z0-9]，无需 .cnf 特殊转义。
        外置数据库自动启用 SSL/TLS 传输加密，防止中间人截获。
        """
        # V2.7.1: 使用 tempfile 默认安全目录，兼容容器环境
        _tmp_dir = Path("/run/wp-bootstrap")
        # [V3.0.11] S2: 仅在新建目录时 chmod, 避免已存在时无谓系统调用
        _created = not _tmp_dir.exists()
        _tmp_dir.mkdir(parents=True, exist_ok=True)
        if _created:
            _tmp_dir.chmod(0o700)
        fd, path = tempfile.mkstemp(prefix=".my_tmp_", suffix=".cnf", dir=str(_tmp_dir))
        try:
            # [V3.0.8] S2: 拦截控制字符, 防止换行符截断 .cnf [client] 段
            for _ch in password:
                if ord(_ch) < 32:
                    raise ValueError(
                        "Password contains control characters unsafe for .cnf"
                    )
            # V2.7.2: 密码值加双引号包裹，防止 # ; 等字符截断 .cnf 解析
            _esc_pw = password.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))
            cnf_lines = f'[client]\npassword="{_esc_pw}"\n'
            # 外置数据库：强制 SSL 加密传输
            # 'ssl' 指令兼容 MySQL 5.7+ 和 MariaDB 10.2+
            if self.cfg.is_external_db:
                cnf_lines += "ssl\n"
            os.write(fd, cnf_lines.encode('utf-8'))
        finally:
            os.close(fd)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return path

    @staticmethod
    def _mysql_escape_value(value: str) -> str:
        """转义 SQL 单引号字符串字面量中的危险字符。

        Important: This function only escapes \\ and \'.
        It assumes the input has been pre-validated against a safe charset
        (auto-generated: [a-zA-Z0-9], user-input: [a-zA-Z0-9!@#$%^&*()_+=.-]+).
        Characters like backtick, semicolon, or NUL are rejected by the
        caller\'s whitelist validation, not by this function.
        """
        for ch in value:
            if ord(ch) < 32:
                raise ValueError(t("err_escape_control_char"))
        return value.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))

    @staticmethod
    def _safe_write_file(path, content: str, mode: int = 0o600) -> bool:
        """[V2.9.5] 原子写入文件，从创建瞬间即为 mode 权限。

        解决 write_text() + chmod() 之间的窗口期问题：
        在窗口期内文件以默认 umask 权限存在，可能被同机用户读取。

        流程：open(O_CREAT|O_WRONLY, mode) → write → fsync → rename
        """
        target = Path(path)  # [V3.0.2] B3: 模块顶层已导入
        tmp_path = target.with_name(target.name + '.sf_tmp')
        try:
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
            try:
                os.write(fd, content.encode('utf-8'))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(str(tmp_path), str(target))
            return True
        except OSError as e:
            logging.warning(t("err_safe_write", target=target, e=e))
            try:
                # [V3.0.9] S1: missing_ok=True 需要 Python 3.8+; 改写以兼容 3.6
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
            return False

    def run_sql(self, sql: str, use_pwd: bool = True, timeout: int = 30) -> bool:
        if self.cfg.dry_run:
            logging.info(t("dry_run_sql"))
            return True

        defaults_file = None
        cmd_list = ["mysql", "-u", "root"]

        if use_pwd and self.db_root_pass:
            defaults_file = self._write_mysql_defaults_file(self.db_root_pass)
            cmd_list = ["mysql", f"--defaults-extra-file={defaults_file}", "-u", "root"]

        # 外置数据库：添加 -h 指定主机
        if self.cfg.is_external_db:
            cmd_list.extend(["-h", self.cfg.db_host])

        try:
            r = subprocess.run(
                cmd_list, input=sql,
                text=True, encoding='utf-8', errors='replace',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=timeout,
            )
            if r.returncode != 0:
                logging.error(t("err_sql_pipe", err=r.stderr.strip()))
                return False
            return True
        except subprocess.TimeoutExpired:
            logging.error(t("err_sql_timeout", t=timeout))
            return False
        except Exception as e:
            logging.error(t("err_sql_exception", e=e))
            return False
        finally:
            if defaults_file:
                try:
                    os.unlink(defaults_file)
                except OSError:
                    pass

    # -----------------------------------------------------------------------
    # 原子写入
    # -----------------------------------------------------------------------
    def atomic_write(self, target_path: Path, content: str) -> bool:
        if self.cfg.dry_run:
            logging.info(t("dry_run_atomic", path=target_path))
            return True
        # V2.8.0: 使用 .aw_tmp/.aw_bak 后缀，避免与 apply_nginx_config_safe
        # 的 .pending/.bak 命名空间冲突（两者均操作 /etc/nginx/conf.d/）
        tmp_path = target_path.with_name(target_path.name + '.aw_tmp')
        bak_path = target_path.with_name(target_path.name + '.aw_bak')
        try:
            if target_path.exists():
                shutil.copy2(target_path, bak_path)
            tmp_path.write_text(content, encoding='utf-8')
            # V2.7.2: 保留原文件权限（如 0600 凭据文件）
            if target_path.exists():
                try:
                    _orig_st = target_path.stat()
                    os.chmod(str(tmp_path), stat.S_IMODE(_orig_st.st_mode))
                    os.chown(str(tmp_path), _orig_st.st_uid, _orig_st.st_gid)
                except OSError:
                    pass
            os.replace(tmp_path, target_path)
            # [V3.0.9] S5: 成功后清理 .aw_bak; 删除失败时记录警告（写入已成功）
            try:
                if bak_path.exists():
                    bak_path.unlink()
            except OSError as _aw_e:
                logging.warning(t("warn_aw_bak_cleanup_fail",
                                  path=bak_path, e=_aw_e))
            return True
        except OSError as e:
            logging.error(t("err_atomic_write", path=target_path, e=e, tb=traceback.format_exc()))
            if bak_path.exists():
                try:
                    os.replace(bak_path, target_path)
                except OSError:
                    pass
            return False
        finally:
            # [V3.0.1] S1: 确保异常路径下 .aw_tmp 不残留（可能含凭据）
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    # -----------------------------------------------------------------------
    # Nginx 配置安全应用
    # -----------------------------------------------------------------------
    def apply_nginx_config_safe(self, config_str: str) -> bool:
        if self.cfg.dry_run: return True
        bak_path = self.cfg.nginx_conf.with_suffix('.bak')
        tmp_path = self.cfg.nginx_conf.with_suffix('.pending')
        lock_path = Path("/run/nginx_config.lock")
        try:
            with open(lock_path, 'w') as f_lock:
                fcntl.flock(f_lock, fcntl.LOCK_EX)
                if self.cfg.nginx_conf.exists():
                    try:
                        shutil.copy2(self.cfg.nginx_conf, bak_path)
                    except OSError as e:
                        logging.error(t("err_nginx_bak_fail", src=self.cfg.nginx_conf, dst=bak_path, e=e))
                        return False
                try: self.cfg.nginx_conf.parent.mkdir(parents=True, exist_ok=True)
                except OSError: return False
                try:
                    tmp_path.write_text(config_str, encoding='utf-8')
                    os.replace(str(tmp_path), str(self.cfg.nginx_conf))
                except OSError: return False
                if not self.run_cmd(["nginx", "-t"], quiet=True):
                    if bak_path.exists(): os.replace(str(bak_path), str(self.cfg.nginx_conf))
                    return False
                reload_result = self.run_cmd(["systemctl", "reload", "nginx"], quiet=True)
                if not reload_result:
                    if bak_path.exists(): os.replace(str(bak_path), str(self.cfg.nginx_conf))
                    self.run_cmd(["nginx", "-t"], quiet=True)
                    self.run_cmd(["systemctl", "reload", "nginx"], quiet=True)
                    return False
                return True
        finally:
            # [V3.0.4] 用 debug 替代 pass：只读挂载点等极端故障下保留可追溯日志
            try:
                tmp_path.unlink()
            except OSError as _e:
                logging.debug(t("debug_nginx_pending_cleanup") % _e)

    # -----------------------------------------------------------------------
    # 软件包安装
    # -----------------------------------------------------------------------
    def install_packages(self) -> bool:
        pkgs = ["nginx", "certbot", "wget", "curl", "tar"]
        if self.pkg_mgr in ("dnf", "yum"):
            self.run_cmd([self.pkg_mgr, "install", "-y", "epel-release"], quiet=True)
            pkgs.extend([
                "php", "php-fpm", "php-mysqlnd", "php-gd",
                "php-json", "php-mbstring", "php-xml",
                # [V2.9.4] S3: WordPress 官方推荐扩展
                # php-curl: 远程 HTTP 请求（插件更新、REST API）
                # php-zip:  插件/主题/WordPress 核心更新包解压
                # php-intl: 多语言 locale 处理（WPML 等插件依赖）
                # php-opcache: 字节码缓存，显著提升 PHP 执行速度
                "php-curl", "php-zip", "php-intl", "php-opcache",
            ])
            # 外置数据库：只需客户端工具（mariadb），无需安装服务端（mariadb-server）
            pkgs.append("mariadb" if self.cfg.is_external_db else "mariadb-server")
            if self.cfg.redis_cache:  # [V2.9.8]
                pkgs.extend(["redis", "php-pecl-redis"])
            return bool(self.run_cmd([self.pkg_mgr, "install", "-y"] + pkgs, quiet=True))
        elif self.pkg_mgr == "apt":
            self.run_cmd(["apt", "update"], quiet=True)
            pkgs.extend([
                "php-fpm", "php-mysql", "php-gd",
                "php-json", "php-mbstring", "php-xml",
                # [V2.9.4] S3: WordPress 官方推荐扩展（与 dnf/yum 列表一致）
                "php-curl", "php-zip", "php-intl", "php-opcache",
            ])
            # 外置数据库：只需客户端工具（mariadb-client），无需安装服务端（mariadb-server）
            pkgs.append("mariadb-client" if self.cfg.is_external_db else "mariadb-server")
            if self.cfg.redis_cache:  # [V2.9.8]
                pkgs.extend(["redis-server", "php-redis"])
            return bool(self.run_cmd(["apt", "install", "-y"] + pkgs, quiet=True))
        return False

    # -----------------------------------------------------------------------
    # 防火墙 & SELinux
    # -----------------------------------------------------------------------
    def setup_firewall(self):
        if shutil.which("ufw"):
            logging.info(t("info_ufw"))
            self.run_cmd(["ufw", "allow", "80/tcp"], quiet=True)
            self.run_cmd(["ufw", "allow", "443/tcp"], quiet=True)
            self.run_cmd(["ufw", "reload"], quiet=True)
        elif shutil.which("firewall-cmd"):
            logging.info(t("info_firewalld"))
            self.run_cmd(["systemctl", "enable", "--now", "firewalld"], quiet=True)
            self.run_cmd(
                ["firewall-cmd", "--permanent", "--add-service=http", "--add-service=https"],
                quiet=True,
            )
            self.run_cmd(["firewall-cmd", "--reload"], quiet=True)

    def handle_selinux(self):
        if shutil.which("selinuxenabled"):
            r = subprocess.run(
                ["selinuxenabled"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if r.returncode == 0:
                logging.warning(t("warn_selinux"))
                self.run_cmd(["setsebool", "-P", "httpd_unified", "1"], quiet=True)
                self.run_cmd(["setsebool", "-P", "httpd_can_network_connect", "1"], quiet=True)
                if self.cfg.webroot_path.exists():
                    self.run_cmd(
                        ["restorecon", "-R", str(self.cfg.webroot_path)], quiet=True,
                    )

    # -----------------------------------------------------------------------
    # MariaDB Root 初始化
    # -----------------------------------------------------------------------
    def _wait_db_ready(self, max_wait: int = 30) -> bool:
        """等待数据库服务就绪（可接受连接）。
        MariaDB/MySQL 首次启动时 InnoDB 初始化可能需要数秒。
        使用 mysqladmin ping -u root（不需要密码即可判断 daemon 是否响应）。
        外置数据库模式下，通过 -h 指定远程主机。

        超时优先级（高 → 低）：
          1. --db-wait-timeout CLI 参数 / WP_DB_WAIT_TIMEOUT 环境变量（已在 SiteConfig 合并）
          2. 外置数据库自动上调至 60s（跨地域网络 / 防火墙白名单生效延迟）
          3. 本地数据库默认 30s
        """
        if self.cfg.db_wait_timeout is not None:
            max_wait = self.cfg.db_wait_timeout
        elif self.cfg.is_external_db:
            max_wait = max(max_wait, 60)
        logging.info(t("info_db_wait", t=max_wait))
        host_args = ["-h", self.cfg.db_host] if self.cfg.is_external_db else []
        # [V2.9.4] B6 修复：mysqladmin 不可用（如最小化镜像）时直接跳过轮询循环，
        # 避免每次迭代抛 FileNotFoundError 被静默吞掉，白白阻塞 max_wait 秒才走回退。
        _have_mysqladmin = bool(shutil.which("mysqladmin"))
        if _have_mysqladmin:
            for attempt in range(1, max_wait + 1):
                # mysqladmin ping 的返回值只反映 daemon 可达性，
                # Access denied 说明 daemon 在运行，也算就绪。
                try:
                    r = subprocess.run(
                        ["mysqladmin", "-u", "root"] + host_args + ["ping", "--silent"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=5, check=False,
                    )
                    if r.returncode == 0:
                        logging.info(t("info_db_ready", t=attempt))
                        return True
                    # Access denied = daemon 在运行，认为就绪
                    if "access denied" in r.stderr.lower():
                        logging.info(t("info_db_ready_auth", t=attempt))
                        return True
                except Exception:
                    pass
                time.sleep(1)
        else:
            logging.info(t("info_db_fallback_detect"))
        # [V3.0.8] R2: fallback 循环等待, 而非仅试一次
        _fb_tries = max(max_wait // 2, 5) if not _have_mysqladmin else 5
        for _fb_i in range(_fb_tries):
            try:
                r = subprocess.run(
                    ["mysql", "-u", "root"] + host_args + ["-e", "SELECT 1;"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace',
                    timeout=10, check=False,
                )
                if r.returncode == 0:
                    logging.info(t("info_db_ready_fallback"))
                    return True
                if "access denied" in r.stderr.lower():
                    logging.info(t("info_db_ready_fallback_auth"))
                    return True
            except Exception:
                pass
            time.sleep(1)
        logging.warning(t("warn_db_not_ready", t=max_wait))
        return False

    def init_mariadb_root(self) -> bool:
        # 外置数据库模式：跳过本地 root 初始化，必须由用户提供 root 密码
        if self.cfg.is_external_db:
            # V2.7.1: 校验外部传入的 root 密码
            if self.cfg.db_root_pass_input and not re.fullmatch(
                r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', self.cfg.db_root_pass_input
            ):
                logging.error(t("err_db_root_unsafe"))
                return False
            if not self.cfg.db_root_pass_input:
                logging.error(t("err_external_db_no_pass", host=self.cfg.db_host))
                return False
            self.db_root_pass = self.cfg.db_root_pass_input
            if self.run_sql("SELECT 1;", use_pwd=True):
                logging.info(t("info_ext_db_ok", host=self.cfg.db_host))
                return True
            else:
                logging.error(t("err_external_db_connect", host=self.cfg.db_host))
                return False

        # 优先级 1：全局密码文件（上次部署写入）
        if self.global_root_pwd_file.exists():
            try:
                _file_pwd = self.global_root_pwd_file.read_text().strip()
                # V2.7.3: 校验密码文件字符集，防止被篡改后注入 SQL
                # V2.7.6: 与 --db-root-pass 输入校验保持一致的字符集
                if _file_pwd and re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _file_pwd):
                    self.db_root_pass = _file_pwd
                elif _file_pwd:
                    logging.warning(t("warn_global_pwd_bad_chars"))
                    self.db_root_pass = ""
                else:
                    self.db_root_pass = ""
            except OSError as e:
                logging.warning(t("warn_read_global_pwd", e=e))
                self.db_root_pass = ""
            if self.db_root_pass and self.run_sql("SELECT 1;", use_pwd=True):
                logging.info(t("info_mariadb_env_ok"))
                return True

        # 优先级 2：用户通过 --db-root-pass 或 WP_DB_ROOT_PASS 传入的已有密码
        if self.cfg.db_root_pass_input:
            # V2.7.1: 校验外部传入的 root 密码，防止单引号截断 SQL
            if not re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', self.cfg.db_root_pass_input):
                logging.error(t("err_db_root_unsafe"))
                return False
            logging.info(t("info_try_user_pwd"))
            self.db_root_pass = self.cfg.db_root_pass_input
            if self.run_sql("SELECT 1;", use_pwd=True):
                logging.info(t("info_user_pwd_ok"))
                # [V2.9.5] 原子写入，从创建瞬间即为 0600
                if not self.cfg.dry_run and self.cfg.persist_root_pwd:
                    self._safe_write_file(self.global_root_pwd_file, self.db_root_pass)
                return True
            else:
                logging.warning(t("warn_user_pwd_fail"))

        safe_chars = string.ascii_letters + string.digits
        self.db_root_pass = ''.join(secrets.choice(safe_chars) for _ in range(32))  # [V2.9.0 修复] 提升至 32 字节

        check_plugin_cmd = [
            "mysql", "-u", "root", "-e",
            "SELECT plugin FROM mysql.user WHERE user='root' AND host='localhost';",
        ]
        try:
            plugin_result = subprocess.run(
                check_plugin_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False, timeout=15,
            )
        except subprocess.TimeoutExpired:
            logging.warning(t("warn_mariadb_plugin_timeout"))
            plugin_result = subprocess.CompletedProcess(
                args=check_plugin_cmd, returncode=1, stdout="", stderr="timeout",
            )

        is_socket_auth = False
        if plugin_result.returncode == 0:
            plugin_output = plugin_result.stdout.lower()
            if "auth_socket" in plugin_output or "unix_socket" in plugin_output:
                is_socket_auth = True
            # mysql_native_password / caching_sha2_password 等
            # 均走通用 ALTER USER ... IDENTIFIED BY 路径，无需单独标记

        is_mysql = self.db_svc in ("mysql", "mysqld")

        if is_socket_auth:
            # socket 认证 → 需要显式切换到密码认证
            # MariaDB 和 MySQL 的语法不同
            if is_mysql:
                alter_sql = (
                    f"ALTER USER 'root'@'localhost' "
                    f"IDENTIFIED WITH mysql_native_password BY '{self._mysql_escape_value(self.db_root_pass)}';"
                )
            else:
                alter_sql = (
                    f"ALTER USER 'root'@'localhost' "
                    f"IDENTIFIED VIA mysql_native_password USING PASSWORD('{self._mysql_escape_value(self.db_root_pass)}');"
                )
        else:
            # mysql_native_password / caching_sha2_password / 其他
            # IDENTIFIED BY 会自动使用当前默认插件加密密码
            # 此语法在 MariaDB 和 MySQL 上通用
            alter_sql = (
                f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{self._mysql_escape_value(self.db_root_pass)}';"
            )

        secure_sql = (
            f"{alter_sql}\n"
            "DELETE FROM mysql.user WHERE User='';\n"
            "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');\n"
            "DROP DATABASE IF EXISTS test;\n"
            "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';\n"
            "FLUSH PRIVILEGES;\n"
        )

        # 注意：secure_sql 通过 stdin 传递给 mysql，SQL 文本中包含明文密码。
        # 这是 MySQL CLI 的固有限制（ALTER USER ... IDENTIFIED BY 必须在 SQL 中）。
        # 密码不会出现在进程列表中（stdin 而非命令行参数），但理论上可被
        # kernel core dump 捕获。生产环境建议禁用 core dump：
        #   echo 0 > /proc/sys/kernel/core_uses_pid
        #   ulimit -c 0
        if self.run_sql(secure_sql, use_pwd=False):
            # [V2.9.5] 原子写入，从创建瞬间即为 0600
            if not self.cfg.dry_run and self.cfg.persist_root_pwd:
                self._safe_write_file(self.global_root_pwd_file, self.db_root_pass)
            return True
        else:
            logging.error(t("err_mariadb_direct"))
            return False

    # -----------------------------------------------------------------------
    # WordPress 下载与完整性校验
    # -----------------------------------------------------------------------
    def _check_wp_integrity(self) -> bool:
        for rel_path in self.WP_INTEGRITY_FILES:
            if not (self.cfg.webroot_path / rel_path).exists():
                return False
        return True
    
    # -----------------------------------------------------------------------
    # 幂等性：从已有 wp-config.php 恢复数据库密码
    # -----------------------------------------------------------------------
    def _recover_existing_db_pass(self) -> str:
        """从已有的 wp-config.php 中提取 DB_PASSWORD，避免重跑时生成新密码
        导致与数据库中已有用户的密码不一致。

        恢复优先级：wp-config.php（权威源）。
        返回空字符串表示未找到，调用方应使用新生成的密码。"""
        wp_config = self.cfg.webroot_path / "wp-config.php"
        if not wp_config.exists():
            return ""
        try:
            content = wp_config.read_text(encoding='utf-8')
            # V2.8.0: 支持 PHP 转义后的密码（patch_wp_config 会对 \ 和 ' 做转义）
            # 使用支持转义序列的正则，避免 \' 提前截断匹配
            m = re.search(
                r"define\(\s*'DB_PASSWORD'\s*,\s*'((?:[^'\\]|\\.)*)'\s*\);", content,
            )
            if m and m.group(1):
                # 反转义 PHP 字符串：\\' → ' , \\\\ → \\
                recovered_pwd = m.group(1).replace(
                    chr(92) + chr(39), chr(39)        # \' → '
                ).replace(
                    chr(92) + chr(92), chr(92)         # \\\\ → \\
                )
                # 与 SiteConfig.validate_sql_password 保持一致的安全校验：
                # 只接受纯字母数字，拒绝任何可能引起 .cnf 或 SQL 转义问题的字符
                if re.fullmatch(r'[a-zA-Z0-9]+', recovered_pwd):
                    return recovered_pwd
                logging.warning(t("warn_recover_pwd_bad_chars"))
        except Exception as e:
            logging.warning(t("warn_read_wpconfig_pwd", e=e))
        return ""
    
    # -----------------------------------------------------------------------
    # WP-CLI 支持（可选增强，所有功能在 WP-CLI 不可用时均有回退路径）
    # -----------------------------------------------------------------------
    def _detect_wpcli(self) -> str:
        """检测系统中是否已安装 WP-CLI，返回可执行路径或空字符串。"""
        # 已缓存
        if self._wpcli_bin:
            return self._wpcli_bin
        # 常见安装位置
        for candidate in ("wp", "/usr/local/bin/wp", "/usr/bin/wp"):
            path = shutil.which(candidate) or candidate
            if os.path.isfile(path) and os.access(path, os.X_OK):
                try:
                    r = subprocess.run(
                        [path, "--version"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=10, check=False,
                    )
                    if r.returncode == 0 and "WP-CLI" in r.stdout:
                        self._wpcli_bin = path
                        logging.info(t("info_wpcli_found", path=path, ver=r.stdout.strip()))
                        return path
                except Exception:
                    pass
        return ""

    def _install_wpcli(self) -> str:
        """尝试下载安装 WP-CLI，成功返回路径，失败返回空字符串。

        按 WPCLI_MIRRORS 列表依次尝试：主源（GitHub raw）→ 国内兜底（jsDelivr CDN）。
        每个镜像的 phar 与 hash 文件均来自同一源，保证 SHA-512 校验的一致性。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_wpcli"))
            return ""

        downloader = shutil.which("curl") or shutil.which("wget")
        if not downloader:
            logging.warning(t("warn_wpcli_no_download"))
            return ""

        logging.info(t("info_wpcli_installing"))

        fd_phar, phar_tmp = tempfile.mkstemp(prefix="wp_cli_", suffix=".phar")
        os.fchmod(fd_phar, stat.S_IRUSR | stat.S_IWUSR)  # 0600 防止共享主机竞态读取
        os.close(fd_phar)
        fd_hash, hash_tmp = tempfile.mkstemp(prefix="wp_cli_hash_", suffix=".sha512")
        os.fchmod(fd_hash, stat.S_IRUSR | stat.S_IWUSR)
        os.close(fd_hash)

        def _dl_cmd(dest: str, url: str) -> list:
            if shutil.which("curl"):
                return ["curl", "-sSL", "--connect-timeout", "15", "-o", dest, url]
            return ["wget", "-qO", dest, url]

        try:
            for mirror in self.WPCLI_MIRRORS:
                mirror_name = mirror["name"]
                logging.info(t("info_wpcli_mirror_try", mirror=mirror_name))

                # 下载 phar
                if not self.run_cmd(_dl_cmd(phar_tmp, mirror["phar"]), timeout=120, quiet=True):
                    logging.warning(t("warn_wpcli_phar_fail", mirror=mirror_name))
                    continue

                # 下载 hash（与 phar 来自同一镜像，保证一致性）
                if not self.run_cmd(_dl_cmd(hash_tmp, mirror["hash"]), timeout=30, quiet=True):
                    logging.warning(t("warn_wpcli_hash_fail", mirror=mirror_name))
                    continue

                # SHA-512 校验
                try:
                    expected_hash = Path(hash_tmp).read_text().strip().split()[0]
                except (IndexError, OSError):
                    logging.warning(t("warn_wpcli_hash_bad", mirror=mirror_name))
                    continue

                sha512 = hashlib.sha512()
                with open(phar_tmp, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha512.update(chunk)
                if sha512.hexdigest() != expected_hash:
                    logging.warning(t("warn_wpcli_sha512_mismatch", mirror=mirror_name))
                    continue

                # 安装到 /usr/local/bin/wp
                install_path = str(self.WPCLI_INSTALL_PATH)
                # V2.7.3: 原子安装 — 先写临时文件再 rename，
                # 避免 shutil.move 跨文件系统时中途崩溃留下不完整文件
                _stage = install_path + ".staging"
                try:
                    shutil.copy2(phar_tmp, _stage)
                    os.chmod(_stage, 0o755)
                    os.replace(_stage, install_path)
                except OSError as e:
                    logging.warning(t("warn_wpcli_install_fail", path=install_path, e=e))
                    for _f in (_stage, install_path):
                        try:
                            os.unlink(_f)
                        except OSError:
                            pass
                    return ""

                # 验证
                try:
                    r = subprocess.run(
                        [install_path, "--version"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=10, check=False,
                    )
                    if r.returncode == 0 and "WP-CLI" in r.stdout:
                        self._wpcli_bin = install_path
                        logging.info(t("ok_wpcli_install_src", src=mirror_name, ver=r.stdout.strip()))
                        return install_path
                except Exception:
                    pass
                logging.warning(t("warn_wpcli_verify_fail", mirror=mirror_name))
                # 清理已 move 过去的坏文件，防止遗留无法运行的 /usr/local/bin/wp
                try:
                    os.unlink(install_path)
                except OSError:
                    pass

            logging.warning(t("warn_wpcli_all_failed"))
            return ""
        finally:
            try:
                Path(phar_tmp).unlink()
            except OSError:
                pass
            try:
                Path(hash_tmp).unlink()
            except OSError:
                pass

    def _ensure_wpcli(self) -> str:
        """确保 WP-CLI 可用：先检测已有安装，没有则尝试自动安装。
        返回路径或空字符串（调用方需处理不可用情况）。"""
        path = self._detect_wpcli()
        if path:
            return path
        return self._install_wpcli()

    def _run_wpcli(self, *args: str, timeout: int = 120, quiet: bool = False) -> CmdResult:
        """执行 WP-CLI 命令。自动附加 --path 和 --allow-root。"""
        wp = self._wpcli_bin
        if not wp:
            return CmdResult(ok=False, code=CmdResult.FATAL, stderr=t("err_wpcli_unavailable"))
        cmd = [
            wp, f"--path={self.cfg.webroot_path}", "--allow-root",
        ] + list(args)
        return self.run_cmd(cmd, timeout=timeout, quiet=quiet)

    def _wpcli_download_wordpress(self) -> bool:
        """WP-CLI 兜底下载：根据 _LANG 决定 --locale。"""
        if not self._wpcli_bin:
            return False
        logging.info(t("info_wpcli_wp_fallback"))
        self.cfg.webroot_path.mkdir(parents=True, exist_ok=True)
        # [V3.0.15] B1: 优先下载与 _LANG 匹配的版本，失败后尝试另一语言
        if _LANG == "zh":
            _primary_args = ("core", "download", "--locale=zh_CN", "--force")
            _fallback_args = ("core", "download", "--force")
        else:
            _primary_args = ("core", "download", "--force")
            _fallback_args = ("core", "download", "--locale=zh_CN", "--force")
        result = self._run_wpcli(*_primary_args, timeout=300, quiet=True)
        if not result:
            result = self._run_wpcli(*_fallback_args, timeout=300, quiet=True)
        if result:
            logging.info(t("ok_wpcli_wp"))
        else:
            logging.warning(t("warn_wpcli_wp_dl_fail", err=result.stderr[:200]))
        return bool(result)

    def _wpcli_verify_checksums(self) -> bool:
        """使用 wp core verify-checksums 做深度完整性校验。
        比手写文件列表更全面——校验所有核心文件的 MD5。"""
        if not self._wpcli_bin:
            return False
        logging.info(t("info_wpcli_verify_checksums"))
        result = self._run_wpcli("core", "verify-checksums", timeout=60, quiet=True)
        if result:
            logging.info(t("ok_wpcli_checksums"))
        else:
            logging.warning(t("warn_wpcli_checksums_failed",
                detail=result.stderr[:200] if result.stderr else "(no details)"))
        return bool(result)

    def _wpcli_check_installed(self) -> bool:
        """使用 wp core is-installed 检测 WordPress 是否已完成安装。
        比 curl HTTP 状态码更深层——直接查询数据库中的安装状态。"""
        if not self._wpcli_bin:
            return False
        result = self._run_wpcli("core", "is-installed", timeout=15, quiet=True)
        return bool(result)

    def _install_nginx_helper(self) -> None:
        """为 FastCGI Cache 安装并激活 nginx-helper 插件。

        当 --cache fastcgi 启用时，WordPress 端没有内置机制清理 Nginx 缓存。
        发布/编辑文章后 Nginx 仍会返回旧缓存直到 inactive 过期。
        nginx-helper 插件在文章发布/更新时自动清除对应的 FastCGI 缓存条目，
        实现 WordPress 内容变更 → Nginx 缓存即时刷新的闭环。

        该方法为可选增强：WP-CLI 不可用或安装失败均不阻断部署流程。
        """
        if self.cfg.cache_mode != "fastcgi":
            return
        if not self._wpcli_bin:
            logging.info(t("info_nginx_helper_no_wpcli"))
            return
        if self.cfg.dry_run:
            logging.info(t("dry_run_nginx_helper"))
            return

        # 检查插件是否已安装
        check_result = self._run_wpcli(
            "plugin", "is-installed", "nginx-helper", timeout=15, quiet=True,
        )
        if check_result:
            # 已安装，确保激活
            activate_result = self._run_wpcli(
                "plugin", "activate", "nginx-helper", timeout=30, quiet=True,
            )
            if activate_result:
                logging.info(t("ok_nginx_helper_activated"))
            else:
                logging.warning(t("warn_nginx_helper_activate_fail"))
            return

        # 安装并激活
        logging.info(t("info_nginx_helper_install"))
        install_result = self._run_wpcli(
            "plugin", "install", "nginx-helper", "--activate",
            timeout=120, quiet=True,
        )
        if install_result:
            logging.info(t("ok_nginx_helper_installed"))
            # 配置 nginx-helper 使用 FastCGI 缓存清除模式
            # [V3.0.1] C3: 使用 json.dumps 替代裸字符串拼接, 防止路径注入
            # [V3.0.9] S2: import json 已移至模块顶层
            safe_name = self.cfg.systemd_prefix
            cache_path = f"/var/cache/nginx/{safe_name}"
            _nh_opts = json.dumps({
                "enable_purge": "1",
                "cache_method": "enable_fastcgi",
                "purge_method": "get_request",
                "nginx_cache_path": cache_path,
            })
            self._run_wpcli(
                "option", "update", "rt_wp_nginx_helper_options",
                _nh_opts,
                timeout=15, quiet=True,
            )
        else:
            logging.warning(t("warn_nginx_helper_install_fail"))

    def download_and_verify_wordpress(self) -> bool:
        # 磁盘空间预检（借鉴 sooth_monitor 的磁盘空间检查模式）
        if not self.check_disk_space(
            self.cfg.webroot_path,
            SiteConfig.MIN_DISK_FREE_MB_DOWNLOAD,
            t("label_wp_download"),
        ):
            return False

        # [V3.0.15] B1: 根据 _LANG 决定下载源顺序。
        # _LANG == "zh" → 中文包优先，全球主源兜底
        # _LANG == "en" → 全球主源（英文）优先，中文包兜底
        _src_zh = {
            "name": t("src_cn_node"),
            "wp": "https://cn.wordpress.org/latest-zh_CN.tar.gz",
            "hash": "https://cn.wordpress.org/latest-zh_CN.tar.gz.sha256",
        }
        _src_en = {
            "name": t("src_global_node"),
            "wp": "https://wordpress.org/latest.tar.gz",
            "hash": "https://wordpress.org/latest.tar.gz.sha256",
        }
        sources = [_src_zh, _src_en] if _LANG == "zh" else [_src_en, _src_zh]

        fd_wp, dest = tempfile.mkstemp(prefix="wp_", suffix=".tar.gz")
        os.close(fd_wp)
        fd_hash, hash_dest = tempfile.mkstemp(prefix="wp_hash_", suffix=".sha256")
        os.close(fd_hash)

        try:
            download_success = False
            wpcli_downloaded = False  # WP-CLI 直接下载到 webroot，无需 tar 解压

            for src in sources:
                logging.info(t("info_wp_src_try", name=src['name']))
                if shutil.which("curl"):
                    cmd_wp = ["curl", "-sSL", "-o", dest, src['wp']]
                    cmd_hash = ["curl", "-sSL", "-o", hash_dest, src['hash']]
                elif shutil.which("wget"):
                    cmd_wp = ["wget", "-qO", dest, src['wp']]
                    cmd_hash = ["wget", "-qO", hash_dest, src['hash']]
                else:
                    logging.error(t("err_no_curl_wget"))
                    return False

                wp_result = self.run_cmd(cmd_wp, timeout=300, quiet=True)
                hash_result = self.run_cmd(cmd_hash, timeout=60, quiet=True)

                if wp_result and hash_result:
                    try:
                        hash_text = Path(hash_dest).read_text().strip()
                        expected_hash = hash_text.split()[0]
                    except (IndexError, OSError):
                        logging.warning(t("warn_wp_hash_bad", name=src['name']))
                        continue
                    sha256_obj = hashlib.sha256()
                    with open(dest, 'rb') as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            sha256_obj.update(chunk)
                    actual_hash = sha256_obj.hexdigest()

                    if expected_hash == actual_hash:
                        logging.info(t("ok_sha256", name=src['name']))
                        download_success = True
                        break
                    else:
                        logging.warning(t("warn_wp_src_hash_mismatch", name=src['name']))
                else:
                    # 利用 CmdResult 错误分类判断是否值得重试
                    if wp_result.code == CmdResult.FATAL:
                        logging.error(t("err_wp_src_fatal", name=src['name']))
                        break

            if not download_success:
                # WP-CLI 兜底：所有 tar.gz 源均失败时尝试 wp core download
                if self._wpcli_bin:
                    logging.warning(t("warn_all_tgz_failed"))
                    if self._wpcli_download_wordpress():
                        download_success = True
                        wpcli_downloaded = True

            if not download_success:
                logging.error(t("err_wp_download_all_failed"))
                return False

            # WP-CLI 直接下载到 webroot，跳过 tar 解压
            if not wpcli_downloaded:
                # 解压前二次磁盘检查
                if not self.check_disk_space(
                    self.cfg.webroot_path,
                    SiteConfig.MIN_DISK_FREE_MB_EXTRACT,
                    t("label_wp_extract"),
                ):
                    return False

                tar_result = self.run_cmd(
                    ["tar", "-zxf", dest, "--strip-components=1", "-C", str(self.cfg.webroot_path)],
                    quiet=True,
                )
                if not tar_result:
                    logging.error(t("err_wp_extract", code=tar_result.code,
                        stderr_part=("\n   " + tar_result.stderr[:200]) if tar_result.stderr else ""))
                    return False

            if not self._check_wp_integrity():
                logging.error(t("err_wp_integrity"))
                return False

            # WP-CLI 深度校验（可选增强）：校验所有核心文件的 MD5
            if self._wpcli_bin:
                if not self._wpcli_verify_checksums():
                    logging.warning(t("warn_wpcli_checksums_continue"))

            return True

        except Exception as e:
            logging.error(t("err_download_exception", e=e))
            return False
        finally:
            try:
                Path(dest).unlink()
            except OSError:
                pass
            try:
                Path(hash_dest).unlink()
            except OSError:
                pass

    # -----------------------------------------------------------------------
    # 阶段一：系统依赖安装与 WordPress 部署
    # -----------------------------------------------------------------------
    def setup_lemp_and_wp(self) -> bool:
        logging.info(t("phase1"))
        if self.cfg.skip_deps:
            logging.info(t("info_skip_deps_verify"))
            # [V3.0.0] 依赖可用性探测：缺失时给出明确错误
            _missing = []
            for _bin in ("nginx", "php", "mysql"):
                if not shutil.which(_bin):
                    _missing.append(_bin)
            if _missing:
                logging.error(t("err_skip_deps_missing", deps=", ".join(_missing)))
                return False
            logging.info(t("info_deps_ok"))
        else:
            if not self.install_packages():
                return False
        if self.check_shutdown():
            return False

        # WP-CLI 检测/安装（可选增强，失败不阻断部署）
        self._ensure_wpcli()

        for ini_path in self._get_php_ini_paths():
            try:
                content = Path(ini_path).read_text(encoding='utf-8')
                content = patch_php_ini_line(content, 'upload_max_filesize', '100M')
                content = patch_php_ini_line(content, 'post_max_size', '100M')
                # [V2.9.4] I3: 补充 WordPress 重型插件（WooCommerce/Elementor 等）
                # 所需的 PHP 运行时参数，以及 OPcache 基础配置。
                content = patch_php_ini_line(content, 'memory_limit', '256M')
                content = patch_php_ini_line(content, 'max_execution_time', '300')
                content = patch_php_ini_line(content, 'opcache.enable', '1')
                content = patch_php_ini_line(content, 'opcache.memory_consumption', '256')
                content = patch_php_ini_line(content, 'opcache.interned_strings_buffer', '16')
                content = patch_php_ini_line(content, 'opcache.max_accelerated_files', '10000')
                content = patch_php_ini_line(content, 'opcache.revalidate_freq', '2')
                # [V3.0.15] B2: 原子写入，防止断电时 PHP-FPM 读到截断的配置
                if not self._safe_write_file(ini_path, content, mode=0o644):
                    logging.warning(t("warn_php_ini_fail", path=ini_path, e="atomic write failed"))
            except Exception as e:
                logging.warning(t("warn_php_ini_fail", path=ini_path, e=e))

        for conf_path in self._get_php_conf_paths():
            try:
                content = Path(conf_path).read_text(encoding='utf-8')
                content = patch_php_fpm_pool_user(content, self.nginx_user)
                # [V3.0.15] B2: 原子写入，与 php.ini 保持一致
                if not self._safe_write_file(conf_path, content, mode=0o644):
                    logging.warning(t("warn_php_ini_fail", path=conf_path, e="atomic write failed"))
            except Exception as e:
                logging.warning(t("warn_php_ini_fail", path=conf_path, e=e))

        # 逐个启用服务，避免某个服务名不存在导致整条命令失败
        # Nginx 是后续所有阶段的硬依赖，启动失败必须终止
        # 外置数据库模式下跳过本地 DB 服务启用
        services_to_enable = [self.php_fpm_svc, "nginx"]
        if not self.cfg.is_external_db:
            services_to_enable.insert(0, self.db_svc)
        if self.cfg.redis_cache:  # [V2.9.8]
            # [V3.0.9] C1: 统一委托 _detect_redis_service_name()
            services_to_enable.insert(0, self._detect_redis_service_name())
        for svc in services_to_enable:
            result = self.run_cmd(["systemctl", "enable", "--now", svc], quiet=True)
            if not result:
                if svc == "nginx":
                    logging.error(t("err_nginx_start"))
                    return False
                logging.warning(t("warn_svc_enable_fail", svc=svc, code=result.code))
        self.setup_firewall()
        if self.check_shutdown():
            return False

        wp_existed = self._check_wp_integrity()
        if not wp_existed:
            self.cfg.webroot_path.mkdir(parents=True, exist_ok=True)
            if not self.download_and_verify_wordpress():
                return False
            # 本次新下载的 WordPress 文件：注册回滚清理
            webroot = self.cfg.webroot_path
            self._register_rollback(
                t("rollback_wp_dir", path=webroot),
                lambda p=str(webroot): shutil.rmtree(p, ignore_errors=True),
            )

        self.handle_selinux()
        if self.check_shutdown():
            return False

        logging.info(t("info_db_allocate"))
        # [V2.9.4] B9 修复：_wait_db_ready 返回 False 表示超时未就绪，
        # 记录上下文日志但不中断（init_mariadb_root 的失败信息已足够具体）。
        if not self._wait_db_ready():
            logging.warning(t("warn_db_timeout_continue"))
        if not self.init_mariadb_root():
            return False

        # 幂等性处理：如果上次运行已创建数据库用户并写入了 wp-config.php，
        # 复用该密码，避免生成新密码后与数据库中已有用户不一致。
        _need_rewrite_wp_config = False  # V2.7.5
        recovered_pass = self._recover_existing_db_pass()
        if recovered_pass:
            # V2.7.4: 恢复密码后验证数据库可连，防止手动改密码后不一致
            _verify_ok = False
            if not self.cfg.dry_run:
                _tmp_def = self._write_mysql_defaults_file(recovered_pass)
                _host_args = ["-h", self.cfg.db_host] if self.cfg.is_external_db else []
                try:
                    _r = subprocess.run(
                        ["mysql", f"--defaults-extra-file={_tmp_def}",
                         "-u", self.cfg.db_user] + _host_args +
                        [self.cfg.db_name, "-e", "SELECT 1;"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=10, check=False,
                    )
                    _verify_ok = (_r.returncode == 0)
                except Exception:
                    pass
                finally:
                    try:
                        os.unlink(_tmp_def)
                    except OSError:
                        pass
            else:
                _verify_ok = True
            if _verify_ok:
                logging.info(t("info_wpconfig_reuse_pwd"))
                self.cfg.db_pass = recovered_pass
            else:
                logging.warning(t("warn_recover_pwd_verify_fail"))
                recovered_pass = ""
                # V2.7.5: 标记需要重写已有的 wp-config.php 中的 DB_PASSWORD
                _need_rewrite_wp_config = True

        if not SiteConfig.validate_sql_identifier(self.cfg.db_name):
            logging.error(t("err_db_name_chars", name=self.cfg.db_name))
            return False
        if not SiteConfig.validate_sql_identifier(self.cfg.db_user):
            logging.error(t("err_db_user_chars", user=self.cfg.db_user))
            return False
        if not SiteConfig.validate_sql_password(self.cfg.db_pass):
            logging.error(t("err_db_pass_chars"))
            return False

        # 外置数据库：授权来源使用 '%'（允许远程连接），本地使用 'localhost'
        db_grant_host = '%' if self.cfg.is_external_db else 'localhost'
        # [V3.0.8] S1: 防御性校验 — 仅允许安全值, 无需 SQL 转义
        if db_grant_host not in ('%', 'localhost'):
            raise ValueError(f"Unexpected db_grant_host: {db_grant_host}")
        # V2.7.1: 幂等重跑时，若已从 wp-config.php 恢复密码，跳过 ALTER USER，
        # 避免新生成的随机密码覆盖数据库中的旧密码导致 WordPress 连不上数据库。
        if recovered_pass:
            db_sql = (
                f"CREATE DATABASE IF NOT EXISTS `{self.cfg.db_name}`"
                f" CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
                f"CREATE USER IF NOT EXISTS '{self.cfg.db_user}'@'{db_grant_host}'"
                f" IDENTIFIED BY '{self._mysql_escape_value(self.cfg.db_pass)}';\n"
                f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX ON `{self.cfg.db_name}`.*"  # [V2.9.7] 最小权限
                f" TO '{self.cfg.db_user}'@'{db_grant_host}';\n"
                f"FLUSH PRIVILEGES;\n"
            )
        else:
            db_sql = (
                f"CREATE DATABASE IF NOT EXISTS `{self.cfg.db_name}`"
                f" CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
                f"CREATE USER IF NOT EXISTS '{self.cfg.db_user}'@'{db_grant_host}'"
                f" IDENTIFIED BY '{self._mysql_escape_value(self.cfg.db_pass)}';\n"
                f"ALTER USER '{self.cfg.db_user}'@'{db_grant_host}'"
                f" IDENTIFIED BY '{self._mysql_escape_value(self.cfg.db_pass)}';\n"
                f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX ON `{self.cfg.db_name}`.*"  # [V2.9.7] 最小权限
                f" TO '{self.cfg.db_user}'@'{db_grant_host}';\n"
                f"FLUSH PRIVILEGES;\n"
            )
        if not self.run_sql(db_sql, use_pwd=True):
            return False

        # 本次新建的数据库：注册回滚清理（仅首次部署，幂等重跑不回滚）
        if not recovered_pass:
            db_name = self.cfg.db_name
            db_user = self.cfg.db_user
            drop_sql = (
                f"DROP DATABASE IF EXISTS `{db_name}`;\n"
                f"DROP USER IF EXISTS '{db_user}'@'{db_grant_host}';\n"
                f"FLUSH PRIVILEGES;\n"
            )
            self._register_rollback(
                t("rollback_db_user", db=db_name, user=db_user),
                lambda sql=drop_sql: self.run_sql(sql, use_pwd=True),
            )

        wp_config = self.cfg.webroot_path / "wp-config.php"
        wp_sample = self.cfg.webroot_path / "wp-config-sample.php"

        # V2.7.5: 恢复密码验证失败时, 更新已有 wp-config.php 中的 DB_PASSWORD
        if _need_rewrite_wp_config and wp_config.exists() and not self.cfg.dry_run:
            try:
                _wpc = wp_config.read_text(encoding="utf-8")
                _wpc = patch_wp_config(
                    _wpc, self.cfg.db_name, self.cfg.db_user, self.cfg.db_pass,
                    db_host=self.cfg.db_host,
                )
                # [V2.9.6] 原子写入, 从创建瞬间即为 0440
                if not self._safe_write_file(wp_config, _wpc, mode=0o440):
                    raise OSError("_safe_write_file failed to write wp-config.php")
                logging.info(t("info_wpconfig_pwd_updated"))
            except Exception as e:
                logging.error(t("err_wpconfig_update", e=e))
                return False

        if wp_sample.exists() and not wp_config.exists() and not self.cfg.dry_run:
            try:
                content = wp_sample.read_text(encoding='utf-8')
                content = patch_wp_config(
                    content, self.cfg.db_name, self.cfg.db_user, self.cfg.db_pass,
                    db_host=self.cfg.db_host,
                )
                content = inject_salts(content)
                content = inject_wp_hardening(content)  # [V2.9.7] 安全加固常量
                content = patch_wplang(content)  # [V3.0.15] B6: 校正 WPLANG
                # [V2.9.6] 原子写入, 从创建瞬间即为 0440
                if not self._safe_write_file(wp_config, content, mode=0o440):
                    raise OSError("_safe_write_file failed to create wp-config.php")
                # 本次新写的 wp-config.php：注册回滚清理
                self._register_rollback(
                    f"Remove {wp_config}",
                    lambda p=wp_config: (p.unlink() if p.exists() else None),
                )
            except Exception as e:
                logging.error(t("err_wpconfig_generate", e=e))
                return False

        self.run_cmd(
            ["chown", "-R", f"{self.nginx_user}:{self.nginx_user}", str(self.cfg.webroot_path)],
            quiet=True,
        )
        self.run_cmd(
            ["find", str(self.cfg.webroot_path), "-type", "d", "-exec", "chmod", "755", "{}", "+"],
            quiet=True,
        )
        # [V3.0.1] C4: 排除 wp-config.php, 消除 644→0440 之间的权限窗口期
        self.run_cmd(
            ["find", str(self.cfg.webroot_path), "-type", "f",
             "-not", "-name", "wp-config.php",
             "-exec", "chmod", "644", "{}", "+"],
            quiet=True,
        )
        # 单独确保 wp-config.php 保持 0440 (find 已排除, 此处为防御性补充)
        wp_config = self.cfg.webroot_path / "wp-config.php"
        if wp_config.exists() and not self.cfg.dry_run:
            try:
                self.run_cmd(["chmod", "0440", str(wp_config)], quiet=True)
            except Exception:
                pass

        return True

    # -----------------------------------------------------------------------
    # 阶段二：Nginx HTTP 验证通道
    # -----------------------------------------------------------------------
    def setup_nginx_for_challenge(self) -> bool:
        logging.info(t("phase2"))
        config = generate_http_only_config(self.cfg.domain, self.cfg.webroot_path)
        return self.apply_nginx_config_safe(config)

    # -----------------------------------------------------------------------
    # 阶段三：SSL 证书申请（带错误分类熔断）
    # -----------------------------------------------------------------------
    def verify_dns(self) -> tuple:
        """DNS 预检：验证域名 A/AAAA 记录已解析，避免 certbot 白跑。
        使用 dig（优先）或 getent hosts 回退。

        [V3.0.12] N1: 返回 (main_ok, www_ok) 元组。
        主域名失败时部署终止；www 失败时仅警告，certbot 将不包含 www。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_dns"))
            return (True, True)

        results = {}  # domain -> bool

        for domain in [self.cfg.domain, f"www.{self.cfg.domain}"]:
            resolved = False

            # 优先用 dig
            if shutil.which("dig"):
                for rtype in ("A", "AAAA"):
                    try:
                        r = subprocess.run(
                            ["dig", "+short", "+time=5", "+tries=2", rtype, domain],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=self.DNS_CHECK_TIMEOUT,
                            check=False,
                        )
                        answers = [
                            line.strip() for line in r.stdout.splitlines()
                            if line.strip() and not line.strip().startswith(";")
                        ]
                        if answers:
                            logging.info(t("info_dns_ok_rtype", domain=domain,
                                           rtype=rtype, addrs=', '.join(answers)))
                            resolved = True
                            break
                    except Exception:
                        pass

            # 回退：getent hosts（不依赖 dig/bind-utils）
            if not resolved and shutil.which("getent"):
                try:
                    r = subprocess.run(
                        ["getent", "hosts", domain],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=self.DNS_CHECK_TIMEOUT,
                        check=False,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        addr = r.stdout.strip().split()[0]
                        logging.info(t("info_dns_ok_getent", domain=domain,
                                       addr=addr))
                        resolved = True
                except Exception:
                    pass

            if not resolved:
                # [V3.0.8] B7: www 子域失败降级为警告, 兼容无 www 的子域名场景
                if domain.startswith("www."):
                    logging.warning(t("warn_dns_fail", domain=domain))
                else:
                    logging.error(t("warn_dns_fail", domain=domain))

            results[domain] = resolved

        main_ok = results.get(self.cfg.domain, False)
        www_ok = results.get(f"www.{self.cfg.domain}", False)
        return (main_ok, www_ok)

    def verify_http_challenge(self) -> bool:
        """HTTP challenge 预检：在 certbot 之前验证 Nginx 能正确
        响应 /.well-known/acme-challenge/ 下的请求。
        写入临时文件 → curl 访问 → 比对内容 → 清理。"""
        if self.cfg.dry_run:
            logging.info(t("dry_run_http"))
            return True

        challenge_dir = self.cfg.webroot_path / ".well-known" / "acme-challenge"
        token = secrets.token_hex(16)
        test_file = challenge_dir / "wp_ssl_precheck"

        try:
            challenge_dir.mkdir(parents=True, exist_ok=True)
            test_file.write_text(token, encoding='utf-8')
            # 确保 Nginx 用户可读
            self.run_cmd(
                ["chown", "-R", f"{self.nginx_user}:{self.nginx_user}",
                 str(self.cfg.webroot_path / ".well-known")],
                quiet=True,
            )
        except OSError as e:
            logging.error(t("err_http_challenge_write", e=e))
            return False

        try:
            time.sleep(self.CHALLENGE_TEST_DELAY)

            # V2.8.0: 探测 Nginx listen 绑定地址，回退到 127.0.0.1
            # 解决 Nginx 仅绑定特定 IP 时 127.0.0.1 预检误报失败的问题
            _listen_addr = "127.0.0.1"
            if self.cfg.nginx_conf.exists():
                try:
                    _nc = self.cfg.nginx_conf.read_text(encoding='utf-8')
                    _lm_ipv4 = re.search(r'listen\s+(\d{1,3}(?:\.\d{1,3}){3}):80\b', _nc)
                    _lm_ipv6 = re.search(r'listen\s+\[([0-9a-fA-F:]+)\]:80\b', _nc)
                    if _lm_ipv4 and _lm_ipv4.group(1) not in ("0.0.0.0", "127.0.0.1"):
                        _listen_addr = _lm_ipv4.group(1)
                        logging.info(t("info_nginx_listen_detected", addr=_listen_addr))
                    elif _lm_ipv6 and _lm_ipv6.group(1) != "::":
                        _listen_addr = f"[{_lm_ipv6.group(1)}]"
                        logging.info(t("info_nginx_listen_detected", addr=_listen_addr))
                except Exception:
                    pass
            url = f"http://{_listen_addr}/.well-known/acme-challenge/wp_ssl_precheck"
            ok = False

            if shutil.which("curl"):
                try:
                    r = subprocess.run(
                        ["curl", "-sSf", "--max-time", "10",
                         "-H", "Host: " + self.cfg.domain, url],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=15, check=False,
                    )
                    if r.returncode == 0 and r.stdout.strip() == token:
                        ok = True
                    else:
                        logging.warning(t("warn_http_challenge_curl_detail",
                            rc=r.returncode,
                            match=t("label_yes") if r.stdout.strip() == token else t("label_no")))
                except Exception as e:
                    logging.warning(t("warn_http_challenge_curl_err", e=e))

            # 回退：用 wget（同样使用 127.0.0.1）
            if not ok and shutil.which("wget"):
                try:
                    r = subprocess.run(
                        ["wget", "-qO-", "--timeout=10",
                         "--header=Host: " + self.cfg.domain, url],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=15, check=False,
                    )
                    if r.returncode == 0 and r.stdout.strip() == token:
                        ok = True
                except Exception:
                    pass

            if ok:
                logging.info(t("ok_http_challenge"))
            else:
                logging.error(t("err_http_challenge_conn_fail"))
            return ok
        finally:
            # 无论成功失败，确保测试文件被清理
            try:
                test_file.unlink()
            except OSError:
                pass

    def _run_certbot_with_lock(self, cmd: list) -> CmdResult:
        lock_file = Path("/run/certbot.lock")
        try:
            with open(lock_file, 'w') as f_lock:
                fcntl.flock(f_lock, fcntl.LOCK_EX)
                return self.run_cmd(cmd)
        except OSError as e:
            return CmdResult(ok=False, code=CmdResult.FATAL, stderr=t("err_certbot_lock", e=e))

    def apply_cert(self, include_www: bool = True) -> bool:
        """多级 CA 容灾签发，借鉴 sooth_monitor 熔断器模式：
        对 certbot 输出做错误分类，非 CA 侧致命错误立即跳出循环。

        [V3.0.12] N1: 新增 include_www 参数。www DNS 未解析时传 False，
        certbot 仅申请主域名证书，避免 www 验证失败导致整体签发失败。
        """
        logging.info(t("phase3"))

        # [V3.0.12] N1: 根据 DNS 预检结果动态构建 -d 列表
        _cert_domains = ["-d", self.cfg.domain]
        if include_www:
            _cert_domains.extend(["-d", f"www.{self.cfg.domain}"])
        else:
            logging.info(t("info_cert_skip_www", domain=self.cfg.domain))

        cmd_base = [
            "certbot", "certonly", "--webroot",
            "-w", str(self.cfg.webroot_path),
        ] + _cert_domains + [
            "--cert-name", self.cfg.domain,
            "-m", self.cfg.email, "--agree-tos", "--non-interactive",
        ]

        if self.cfg.staging:
            cmd_base.append("--staging")

        providers = [self.CA_PROVIDERS[0]] if self.cfg.staging else self.CA_PROVIDERS

        for i, ca in enumerate(providers, 1):
            cmd = list(cmd_base)
            if ca["server"]:
                cmd.extend(["--server", ca["server"]])

            logging.info(t("info_cert_try", idx=i, total=len(providers), ca=ca['name']))
            result = self._run_certbot_with_lock(cmd)

            if result:
                logging.info(t("ok_cert_issued", ca=ca['name']))
                return True

            # 错误分类熔断：对 certbot 特定错误做精细判断
            cert_error = classify_certbot_error(result.stderr)

            if cert_error == CmdResult.FATAL:
                logging.error(t("err_cert_fatal", ca=ca['name'], err=result.stderr[:200]))
                break
            elif cert_error == CmdResult.PERMISSION:
                logging.error(t("err_cert_permission", ca=ca['name'], err=result.stderr[:200]))
                break
            else:
                # RETRYABLE — 值得尝试下一个 CA
                logging.warning(t("warn_cert_retryable",
                    ca=ca['name'],
                    next_msg=t("warn_cert_next_ca") if i < len(providers) else t("warn_cert_no_more_ca")))

        logging.error(t("err_cert_all_failed"))
        return False

    # -----------------------------------------------------------------------
    # 阶段四：HTTPS 生产配置
    # -----------------------------------------------------------------------
    def setup_nginx_for_production(self) -> bool:
        logging.info(t("phase4"))
        sock_path = self.get_php_sock_path()
        config = generate_https_config(
            self.cfg.domain, self.cfg.webroot_path, sock_path,
            cache_mode=self.cfg.cache_mode,
            allow_xmlrpc=self.cfg.allow_xmlrpc,
        )
        if self.cfg.cache_mode == "fastcgi" and not self.cfg.dry_run:
            safe_name = self.cfg.systemd_prefix
            cache_dir = Path(f"/var/cache/nginx/{safe_name}")
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                # 确保 Nginx 用户可写
                self.run_cmd(
                    ["chown", "-R", f"{self.nginx_user}:{self.nginx_user}",
                     str(cache_dir)],
                    quiet=True,
                )
                logging.info(t("info_fastcgi_cache_created", path=cache_dir))
            except OSError as e:
                logging.warning(t("warn_fastcgi_cache_dir_fail", e=e))
        return self.apply_nginx_config_safe(config)

    # -----------------------------------------------------------------------
    # 站点健康检查（部署后验证）
    # -----------------------------------------------------------------------
    def verify_site_health(self) -> bool:
        """部署完成后验证站点可访问：curl https://domain，
        带重试机制，允许 Nginx/PHP-FPM 启动延迟。"""
        if self.cfg.dry_run:
            logging.info(t("dry_run_health"))
            return True

        if not shutil.which("curl"):
            logging.warning(t("warn_no_curl_health"))
            return True

        url = f"https://{self.cfg.domain}/"
        logging.info(t("info_health_check", url=url))

        for attempt in range(1, self.HEALTH_CHECK_RETRIES + 1):
            try:
                curl_cmd = [
                    "curl", "-sSo", "/dev/null", "-w", "%{http_code}",
                    "--max-time", str(self.HEALTH_CHECK_TIMEOUT),
                ]
                # staging 模式使用 Let's Encrypt Staging CA，证书不被信任，需跳过验证
                if self.cfg.staging:
                    curl_cmd.append("-k")
                curl_cmd.append(url)

                r = subprocess.run(
                    curl_cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=self.HEALTH_CHECK_TIMEOUT + 5, check=False,
                )
                http_code = r.stdout.strip()

                if http_code in ("200", "301", "302", "303", "307", "308"):
                    logging.info(t("info_health_ok", code=http_code, attempt=attempt))
                    return True

                # WordPress 首次安装会返回 302 → /wp-admin/install.php，这是正常的
                if http_code == "000":
                    logging.warning(t("warn_health_conn_fail",
                        attempt=attempt, total=self.HEALTH_CHECK_RETRIES,
                        interval=self.HEALTH_CHECK_INTERVAL))
                else:
                    logging.warning(t("warn_health_bad_code",
                        attempt=attempt, total=self.HEALTH_CHECK_RETRIES,
                        code=http_code, interval=self.HEALTH_CHECK_INTERVAL))
            except Exception as e:
                logging.warning(t("warn_health_exception",
                    attempt=attempt, total=self.HEALTH_CHECK_RETRIES, e=e))

            if attempt < self.HEALTH_CHECK_RETRIES:
                time.sleep(self.HEALTH_CHECK_INTERVAL)

        logging.warning(t("warn_health_final",
            retries=self.HEALTH_CHECK_RETRIES, domain=self.cfg.domain))
        # 返回 True：健康检查失败不应阻断部署流程，仅作为警告
        return True

    def verify_wp_installation(self) -> None:
        """部署末尾的 WP-CLI 深度健康检查（可选增强）。
        检测 WordPress 数据库连接和安装状态，比 HTTP 状态码更深层。
        结果仅作为信息输出，不阻断部署。"""
        if not self._wpcli_bin:
            return
        logging.info(t("info_wpcli_deep_check"))
        # wp core is-installed: 检查 WordPress 是否已连接数据库并完成安装
        if self._wpcli_check_installed():
            logging.info(t("ok_wpcli_installed"))
        else:
            logging.info(t("info_wp_not_installed"))
        # wp core version: 输出当前 WordPress 版本供确认
        ver_result = self._run_wpcli("core", "version", timeout=15, quiet=True)
        if ver_result and ver_result.stdout:
            logging.info(t("info_wp_version", ver=ver_result.stdout))

    # -----------------------------------------------------------------------
    # 证书域名提取 (V3.0.13 N1)
    # -----------------------------------------------------------------------
    def _get_cert_domains(self) -> list:
        """[V3.0.13] N1: 从已有证书的 SAN 中提取域名列表。

        读取 /etc/letsencrypt/live/{domain}/fullchain.pem 的
        Subject Alternative Names, 返回 ["-d", "domain", "-d", "www.domain", ...]
        格式的参数列表。

        证书不存在或解析失败时返回默认列表（含 www）。
        """
        cert_file = Path(f"/etc/letsencrypt/live/{self.cfg.domain}/fullchain.pem")
        if not cert_file.exists():
            logging.info(t("info_renew_cert_not_found_www"))
            return ["-d", self.cfg.domain, "-d", f"www.{self.cfg.domain}"]

        try:
            r = subprocess.run(
                ["openssl", "x509", "-noout", "-text", "-in", str(cert_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=10, check=False,
            )
            if r.returncode != 0:
                return ["-d", self.cfg.domain, "-d", f"www.{self.cfg.domain}"]

            # 解析 SAN: "DNS:example.com, DNS:www.example.com"
            san_domains = []
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("DNS:") or ", DNS:" in line:
                    # 整行可能是 "DNS:a.com, DNS:b.com"
                    for part in line.split(","):
                        part = part.strip()
                        if part.startswith("DNS:"):
                            dns_name = part[4:].strip()
                            if dns_name:
                                san_domains.append(dns_name)

            if not san_domains:
                return ["-d", self.cfg.domain, "-d", f"www.{self.cfg.domain}"]

            # 确保主域名在列表首位
            if self.cfg.domain not in san_domains:
                san_domains.insert(0, self.cfg.domain)

            logging.info(t("info_renew_domains_from_cert",
                           domains=", ".join(san_domains)))

            result = []
            for d in san_domains:
                result.extend(["-d", d])
            return result

        except Exception:
            return ["-d", self.cfg.domain, "-d", f"www.{self.cfg.domain}"]

    # -----------------------------------------------------------------------
    # 证书续期
    # -----------------------------------------------------------------------
    def renew_cert(self, force: bool = False):
        logging.info(t("info_renew_check", domain=self.cfg.domain))

        # 证书到期预检：输出剩余天数，方便运维观测
        cert_file = Path(f"/etc/letsencrypt/live/{self.cfg.domain}/fullchain.pem")
        if cert_file.exists() and not self.cfg.dry_run:
            try:
                r = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout",
                     "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=10, check=False,
                )
                if r.returncode == 0 and r.stdout.strip():
                    logging.info(t("info_cert_expiry", expiry=r.stdout.strip()))
                # 检查是否 30 天内到期
                r2 = subprocess.run(
                    ["openssl", "x509", "-checkend", str(30 * 86400),
                     "-noout", "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=10, check=False,
                )
                if r2.returncode == 0:
                    logging.info(t("info_cert_valid"))
                else:
                    logging.info(t("info_cert_expiring_soon"))
            except Exception:
                pass
        elif not cert_file.exists():
            logging.warning(t("warn_cert_not_found", path=cert_file))

        # [V3.0.13] N1: 从已有证书 SAN 读取域名, 不再硬编码 www
        _renew_domains = self._get_cert_domains()
        cmd = [
            "certbot", "certonly", "--webroot",
            "-w", str(self.cfg.webroot_path),
        ] + _renew_domains + [
            "--cert-name", self.cfg.domain,
            "--quiet", "--non-interactive",
            "--register-unsafely-without-email",  # V2.7.2: 兜底无账户场景
            "--deploy-hook", "systemctl reload nginx",
        ]
        if force:
            cmd.append("--force-renewal")
        else:
            cmd.append("--keep-until-expiring")
        success = self._run_certbot_with_lock(cmd)
        if success:
            logging.info(t("ok_cert_renew"))
        else:
            logging.error(t("err_cert_renew", domain=self.cfg.domain))
            self._exit_code = 1
        return success

    # -----------------------------------------------------------------------
    # Redis 对象缓存 (V2.9.8)
    # -----------------------------------------------------------------------
    # [V3.0.9] C1: Redis 服务名统一检测点，消除三处重复逻辑
    def _detect_redis_service_name(self) -> str:
        """Detect the Redis systemd service name (redis vs redis-server).

        Returns 'redis-server' on Debian/Ubuntu when that unit exists,
        'redis' otherwise (RHEL/CentOS/Alibaba Cloud Linux).
        """
        if self.pkg_mgr == "apt":
            try:
                _r = subprocess.run(
                    ["systemctl", "list-unit-files", "redis-server.service"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    universal_newlines=True, timeout=5, check=False,
                )
                if _r.returncode == 0 and "redis-server" in _r.stdout:
                    return "redis-server"
            except Exception:
                pass
        return "redis"

    def _setup_redis_cache(self):
        """启用 Redis 对象缓存: 安装 redis-cache 插件并激活。

        Redis 缓存 WordPress 数据库查询结果 (对象缓存层),
        与 FastCGI 全页缓存互补: 前者加速 PHP/MySQL, 后者短路 Nginx。
        WP-CLI 可用时自动完成; 不可用时仅打印手动指引。
        """
        if not self.cfg.redis_cache:
            return
        if self.cfg.dry_run:
            logging.info(t("dry_run_redis"))
            return

        # [V3.0.9] B2/C1: 使用统一的服务名检测辅助方法
        _redis_svc = self._detect_redis_service_name()
        if not self.run_cmd(["systemctl", "is-active", _redis_svc], quiet=True):
            self.run_cmd(["systemctl", "enable", "--now", _redis_svc], quiet=True)

        if not self._wpcli_bin:
            logging.info(t("info_redis_manual"))
            return

        # WP-CLI 安装并激活 redis-cache 插件
        check = self._run_wpcli("plugin", "is-installed", "redis-cache",
                                timeout=15, quiet=True)
        if not check:
            logging.info(t("info_redis_installing"))
            result = self._run_wpcli(
                "plugin", "install", "redis-cache", "--activate",
                timeout=120, quiet=True,
            )
            if not result:
                logging.warning(t("warn_redis_plugin_fail", err=result.stderr[:200]))
                return
        else:
            self._run_wpcli("plugin", "activate", "redis-cache",
                            timeout=15, quiet=True)

        # 启用 Redis 对象缓存 (创建 object-cache.php drop-in)
        enable_result = self._run_wpcli("redis", "enable", timeout=30, quiet=True)
        if enable_result:
            logging.info(t("info_redis_enabled"))
        else:
            logging.warning(t("warn_redis_dropin_fail"))

    # -----------------------------------------------------------------------
    # Brotli 压缩 (V2.9.8 自动检测)
    # -----------------------------------------------------------------------
    def _setup_brotli(self):
        """自动检测 Nginx Brotli 模块, 可用时写入全局压缩配置。

        Brotli 对文本类资源比 Gzip 再压缩 15-25%。
        检测失败时静默跳过, 不影响部署 (Gzip 仍然生效)。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_brotli"))
            return

        # Best-effort 安装 Brotli 模块
        if self.pkg_mgr == "apt":
            self.run_cmd(
                ["apt", "install", "-y",
                 "libnginx-mod-http-brotli-filter",
                 "libnginx-mod-http-brotli-static"],
                quiet=True,
            )
        elif self.pkg_mgr in ("dnf", "yum"):  # [V2.9.9] RHEL/CentOS 分支
            self.run_cmd(
                [self.pkg_mgr, "install", "-y", "nginx-mod-http-brotli"],
                quiet=True,
            )

        # 检测模块是否可用
        brotli_available = False
        try:
            r = subprocess.run(
                ["nginx", "-V"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=10, check=False,
            )
            if "brotli" in (r.stdout + r.stderr).lower():
                brotli_available = True
        except Exception:
            pass
        if not brotli_available:
            for mod_dir in ("/etc/nginx/modules-enabled",
                            "/usr/lib64/nginx/modules"):
                if Path(mod_dir).exists() and list(Path(mod_dir).glob("*brotli*")):
                    brotli_available = True
                    break

        if not brotli_available:
            logging.info(t("info_brotli_unavail"))
            return

        conf_file = Path("/etc/nginx/conf.d/brotli-wp-bootstrap.conf")
        conf_content = (
            "# Auto-generated by WP-SSL-Bootstrap\n"
            "brotli on;\n"
            "brotli_comp_level 4;\n"
            "brotli_min_length 1024;\n"
            "brotli_types text/plain text/css application/javascript application/json\n"
            "             application/xml text/xml application/xml+rss\n"
            "             font/woff font/woff2 image/svg+xml;\n"
        )

        try:
            conf_file.write_text(conf_content, encoding='utf-8')
        except OSError:
            return

        # 验证配置有效 (模块未加载时 nginx -t 会报错)
        if self.run_cmd(["nginx", "-t"], quiet=True):
            logging.info(t("info_brotli_enabled"))
        else:
            try:
                conf_file.unlink()
            except OSError:
                pass
            logging.info(t("info_brotli_rollback"))

    # -----------------------------------------------------------------------
    # Nginx 日志轮转 (防止磁盘写满)
    # -----------------------------------------------------------------------
    def setup_logrotate(self):
        """[V2.9.7] 为站点独立的 Nginx 日志配置 logrotate。

        generate_https_config 为每个域名生成独立的 access_log / error_log，
        但系统默认的 /etc/logrotate.d/nginx 只管 /var/log/nginx/*.log。
        若站点日志路径不在默认通配范围内，日志文件将无限增长直至磁盘写满。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_logrotate"))
            return

        logrotate_dir = Path("/etc/logrotate.d")
        if not logrotate_dir.exists():
            logging.warning(t("warn_logrotate_dir_missing"))
            return

        safe_name = self.cfg.systemd_prefix
        conf_file = logrotate_dir / f"nginx-wp-{safe_name}"
        log_path = f"/var/log/nginx/{self.cfg.domain}.*.log"

        # [V3.0.4] logrotate create 指令的日志组：
        #   Debian/Ubuntu (apt): adm  — 与 /etc/logrotate.d/nginx 官方配置一致
        #   RHEL/CentOS/Alibaba Cloud Linux (dnf/yum): root — adm 组通常不存在
        # 硬编码 adm 会导致 RHEL 系 logrotate 报 "unknown group 'adm'" 并跳过轮转。
        log_group = "adm" if self.pkg_mgr == "apt" else "root"
        conf_content = (
            f"{log_path} {{\n"
            f"    daily\n"
            f"    missingok\n"
            f"    rotate 14\n"
            f"    compress\n"
            f"    delaycompress\n"
            f"    notifempty\n"
            f"    create 0640 {self.nginx_user} {log_group}\n"
            f"    sharedscripts\n"
            f"    postrotate\n"
            f"        [ -f /var/run/nginx.pid ] && kill -USR1 $(cat /var/run/nginx.pid) 2>/dev/null || true\n"
            f"    endscript\n"
            f"}}\n"
        )

        try:
            conf_file.write_text(conf_content, encoding='utf-8')
            logging.info(t("info_logrotate_written", path=conf_file))
        except OSError as e:
            logging.warning(t("warn_logrotate_write_fail", e=e))

    # -----------------------------------------------------------------------
    # Fail2Ban WordPress 暴力破解防护
    # -----------------------------------------------------------------------
    def setup_fail2ban(self):
        """安装并配置 Fail2Ban，自动封禁对 wp-login.php / xmlrpc.php 的暴力请求。"""
        logging.info(t("phase_f2b"))

        if self.cfg.dry_run:
            logging.info(t("dry_run_f2b"))
            return

        # 安装 fail2ban（幂等）
        if not shutil.which("fail2ban-client"):
            logging.info(t("info_f2b_installing"))
            if self.pkg_mgr in ("dnf", "yum"):
                self.run_cmd([self.pkg_mgr, "install", "-y", "fail2ban"], quiet=True)
            elif self.pkg_mgr == "apt":
                self.run_cmd(["apt", "install", "-y", "fail2ban"], quiet=True)
            if not shutil.which("fail2ban-client"):
                logging.warning(t("warn_f2b_install_fail"))
                return

        safe_name = self.cfg.systemd_prefix

        # Nginx access log 路径（与 generate_https_config 中 access_log 指令一致）
        log_path = f"/var/log/nginx/{self.cfg.domain}.access.log"

        # 写入 filter 规则
        filter_dir = Path("/etc/fail2ban/filter.d")
        filter_dir.mkdir(parents=True, exist_ok=True)
        filter_file = filter_dir / f"wordpress-{safe_name}.conf"
        # [V3.0.3] xmlrpc.php 放开后请求成功返回 200（XML Body），失败也返回 200，
        # Nginx access log 无法区分认证是否成功，不能用状态码判断暴力破解。
        # 正确做法：仅匹配 Nginx 速率限制触发的 429——意味着该 IP 在 1r/s 窗口内
        # 持续高频请求，已被 Nginx 截断，此时封禁 IP 语义明确且无误封风险。
        if self.cfg.allow_xmlrpc:
            xmlrpc_filter_comment = (
                "# xmlrpc.php: 已放开 (--allow-xmlrpc)，仅匹配 Nginx 限速触发的 429，\n"
                "# 即持续高频请求被截断的 IP，语义明确无误封风险。\n"
                "# 注：xmlrpc.php 合法请求与认证失败均返回 200，无法通过状态码区分。\n"
            )
            xmlrpc_filter_rule = (
                "            ^<HOST> .*\"POST /xmlrpc\\.php.* HTTP/\\d\\.\\d\" 429$\n"
            )
        else:
            xmlrpc_filter_comment = (
                "# xmlrpc.php: 已被 Nginx deny (403)，任何访问均为异常探测。\n"
            )
            xmlrpc_filter_rule = (
                "            ^<HOST> .*\"(GET|POST) /xmlrpc\\.php.* HTTP/\\d\\.\\d\" 403$\n"
            )
        filter_content = (
            "# Auto-generated by WP-SSL-Bootstrap\n"
            "[Definition]\n"
            "# wp-login.php: 登录失败返回 200，成功返回 302，仅匹配 200 减少误封。\n"
            + xmlrpc_filter_comment
            + "failregex = ^<HOST> .*\"POST /wp-login\\.php.* HTTP/\\d\\.\\d\" 200$\n"
            + xmlrpc_filter_rule
            + "ignoreregex =\n"
        )

        # 写入 jail 规则
        jail_dir = Path("/etc/fail2ban/jail.d")
        jail_dir.mkdir(parents=True, exist_ok=True)
        jail_file = jail_dir / f"wordpress-{safe_name}.conf"
        jail_content = (
            f"# Auto-generated by WP-SSL-Bootstrap\n"
            f"[wordpress-{safe_name}]\n"
            f"enabled  = true\n"
            f"port     = http,https\n"
            f"filter   = wordpress-{safe_name}\n"
            f"logpath  = {log_path}\n"
            f"maxretry = 5\n"
            f"findtime = 600\n"
            f"bantime  = 3600\n"
        )

        try:
            filter_file.write_text(filter_content, encoding='utf-8')
            jail_file.write_text(jail_content, encoding='utf-8')
            logging.info(t("info_f2b_written", filter=filter_file, jail=jail_file))
        except OSError as e:
            logging.warning(t("warn_f2b_write_fail", e=e))
            return

        # 启用并重启 fail2ban
        self.run_cmd(["systemctl", "enable", "--now", "fail2ban"], quiet=True)
        self.run_cmd(["systemctl", "restart", "fail2ban"], quiet=True)
        logging.info(t("ok_f2b_active"))

    # -----------------------------------------------------------------------
    # 阶段五：Systemd 定时续期
    # -----------------------------------------------------------------------
    def setup_systemd(self):
        logging.info(t("phase5"))

        service_content = (
            f"[Unit]\n"
            f"Description={self.cfg.domain} SSL Auto-Renewal\n"
            f"After=network-online.target nginx.service\n"
            f"\n"
            f"[Service]\n"
            f"Type=oneshot\n"
            f"User=root\n"
            f"WorkingDirectory=/root\n"
            f"TimeoutStartSec=300\n"
            f"StandardOutput=journal\n"
            f"StandardError=journal\n"  # [V2.9.3] 确保续期失败时 journalctl 可查完整输出
            f"ExecStart={sys.executable} \"{self.cfg.script_path}\""
            f" renew --domain {self.cfg.domain} --quiet\n"
            f"\n"
            f"[Install]\n"
            f"WantedBy=multi-user.target\n"
        )

        timer_content = (
            f"[Unit]\n"
            f"Description=Run {self.cfg.domain} SSL Renewal Daily\n"
            f"\n"
            f"[Timer]\n"
            f"OnCalendar=daily\n"
            f"RandomizedDelaySec=12h\n"
            f"Persistent=true\n"
            f"Unit={self.cfg.systemd_prefix}-ssl.service\n"
            f"\n"
            f"[Install]\n"
            f"WantedBy=timers.target\n"
        )

        if self.atomic_write(self.cfg.service_file, service_content) and \
           self.atomic_write(self.cfg.timer_file, timer_content):
            self.run_cmd(["systemctl", "daemon-reload"], quiet=True)
            self.run_cmd(
                ["systemctl", "enable", "--now", f"{self.cfg.systemd_prefix}-ssl.timer"],
                quiet=True,
            )

    # -----------------------------------------------------------------------
    # 部署完成摘要
    # -----------------------------------------------------------------------
    def print_final_summary(self):
        cred_file = Path(f"/root/.wp_credentials_{self.cfg.systemd_prefix}.txt")
        db_host_arg = f" -h {self.cfg.db_host}" if self.cfg.is_external_db else ""
        # [V3.0.15] B5: 凭据文件内容国际化
        cred_content = (
            f"{t('cred_header', domain=self.cfg.domain)}\n"
            f"Webroot   : {self.cfg.webroot_path}\n"
            f"DB Host   : {self.cfg.db_host}\n"
            f"DB Name   : {self.cfg.db_name}\n"
            f"DB User   : {self.cfg.db_user}\n"
            f"DB Pass   : {self.cfg.db_pass}\n\n"
            f"===== MariaDB Root =====\n"
            f"Root Password: {self.db_root_pass}\n\n"
            f"{t('cred_emergency')}\n"
            f"{t('cred_db_connect')}\n"
            f"  mysql{db_host_arg} -u {self.cfg.db_user} -p {self.cfg.db_name}\n\n"
            f"{t('cred_fix_perms')}\n"
            f"  chown -R {self.nginx_user}:{self.nginx_user} {self.cfg.webroot_path}\n"
            f"  find {self.cfg.webroot_path} -type d -exec chmod 755 {{}} +\n"
            f"  find {self.cfg.webroot_path} -type f -exec chmod 644 {{}} +\n"
            f"{t('cred_fix_perms_warn')}\n"
            f"  chmod 0440 {self.cfg.webroot_path}/wp-config.php\n\n"
            f"{t('cred_manual_renew')}\n"
            f"  certbot certonly --webroot -w {self.cfg.webroot_path} \\\n"
            f"    -d {self.cfg.domain} -d www.{self.cfg.domain} \\\n"
            f"    --cert-name {self.cfg.domain}\n\n"
            f"{t('cred_nginx_reload')}\n"
            f"  nginx -t && systemctl reload nginx\n\n"
            f"{t('cred_timer_status')}\n"
            f"  systemctl status {self.cfg.systemd_prefix}-ssl.timer\n\n"
            f"{t('cred_uninstall')}\n"
            f"  {sys.executable} {self.cfg.script_path} uninstall \\\n"
            f"    --domain {self.cfg.domain}\n\n"
            f"{t('cred_site_status')}\n"
            f"  {sys.executable} {self.cfg.script_path} status \\\n"
            f"    --domain {self.cfg.domain}\n\n"
            f"{t('cred_backup')}\n"
            f"  {sys.executable} {self.cfg.script_path} backup \\\n"
            f"    --domain {self.cfg.domain}\n"
        )
        # [V2.9.5] 原子写入，从创建瞬间即为 0600
        if not self.cfg.dry_run:
            self._safe_write_file(cred_file, cred_content)

        print("\n" + "=" * 50)
        print(t("deploy_success"))
        print("=" * 50)
        print(t("deploy_url", domain=self.cfg.domain))
        print(t("deploy_cred", path=cred_file))
        print("=" * 50)

    # -----------------------------------------------------------------------
    # 备份
    # -----------------------------------------------------------------------
    def backup(self, keep_count: int = 5):
        """一键备份：数据库 dump + webroot 压缩包 + Nginx 配置。

        Args:
            keep_count: 保留的最大备份份数，超出部分从最旧开始删除。0 = 不清理。
        """
        logging.info(t("info_backup_start", domain=self.cfg.domain))
        if self.cfg.dry_run:
            logging.info(t("dry_run_backup"))
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = self.cfg.backup_base_dir / self.cfg.domain / timestamp
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            # [V2.9.3] 备份目录含数据库 dump，显式 0700 防止 umask 松散导致全局可读
            backup_dir.chmod(0o700)
        except OSError as e:
            logging.error(t("err_backup_dir", e=e))
            return

        # ---- 1. 数据库 dump ----
        # 密码加载优先级（与 init_mariadb_root 一致）：
        #   1. CLI --db-root-pass / 环境变量 WP_DB_ROOT_PASS（V2.9.4 B5 修复）
        #   2. 全局密码文件（--persist-root-pwd 写入）
        # [V2.9.4] 修复 B5：V2.9.3 虽把 --db-root-pass 加入公共参数，但 backup()
        # 从未读取 cfg.db_root_pass_input，导致该参数对 backup 子命令实际无效。
        if not self.db_root_pass and self.cfg.db_root_pass_input:
            _cli_pwd = self.cfg.db_root_pass_input
            if re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _cli_pwd):
                self.db_root_pass = _cli_pwd
                logging.info(t("info_backup_use_cli_pwd"))
            else:
                logging.warning(t("warn_db_root_unsafe_skip"))

        if not self.db_root_pass and self.global_root_pwd_file.exists():
            try:
                _raw_pwd = self.global_root_pwd_file.read_text().strip()
                # V2.7.2: 校验密码文件内容，防止被篡改后注入 .cnf 指令
                if _raw_pwd and re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _raw_pwd):
                    self.db_root_pass = _raw_pwd
                elif _raw_pwd:
                    logging.warning(t("warn_backup_pwd_bad_chars"))
            except OSError:
                pass

        db_dump = backup_dir / f"{self.cfg.db_name}.sql.gz"
        if self.db_root_pass:
            defaults_file = self._write_mysql_defaults_file(self.db_root_pass)
            try:
                # V2.7.1: 使用 subprocess.Popen 管道替代 bash -c 字符串拼接，
                # 消除 db_host 等用户输入的 shell 注入风险。
                dump_cmd = [
                    "mysqldump",
                    f"--defaults-extra-file={defaults_file}",
                    "-u", "root",
                    "--single-transaction", "--quick",
                ]
                if self.cfg.is_external_db:
                    dump_cmd.extend(["-h", self.cfg.db_host, "--compress"])
                dump_cmd.append(self.cfg.db_name)
                dump_timeout = 600 if self.cfg.is_external_db else 300
                dump_ok = False
                p_dump = None
                p_gzip = None
                gzip_fd = None
                try:
                    p_dump = subprocess.Popen(
                        dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    gzip_fd = open(str(db_dump), 'wb')
                    os.fchmod(gzip_fd.fileno(), 0o600)  # [V3.0.8] S5
                    p_gzip = subprocess.Popen(
                        ["gzip"], stdin=p_dump.stdout,
                        stdout=gzip_fd, stderr=subprocess.PIPE,
                    )
                    p_dump.stdout.close()  # 允许 SIGPIPE 传播

                    # [V2.9.4] B8 修复：用独立线程异步读取 mysqldump stderr，
                    # 防止 stderr 缓冲区满时 mysqldump 阻塞而主线程等待 gzip 结束
                    # 的经典管道死锁。
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                        _stderr_fut = _ex.submit(p_dump.stderr.read)
                        try:
                            _, gzip_err = p_gzip.communicate(timeout=dump_timeout)
                        except subprocess.TimeoutExpired:
                            raise
                        dump_err = _stderr_fut.result(timeout=15)

                    p_dump.stderr.close()
                    p_dump.wait(timeout=30)
                    if (p_dump.returncode == 0
                            and p_gzip.returncode == 0
                            and db_dump.exists()
                            and db_dump.stat().st_size > 0):
                        logging.info(t("ok_db_backup", path=db_dump))
                        dump_ok = True
                    else:
                        err_msg = (dump_err or gzip_err or b"").decode("utf-8", errors="replace")
                        logging.warning(t("warn_db_backup_fail", err=err_msg[:200]))
                except subprocess.TimeoutExpired:
                    logging.warning(t("warn_db_backup_timeout", t=dump_timeout))
                except Exception as e:
                    logging.warning(t("warn_db_backup_exception", e=e))
                finally:
                    # [V2.9.4] B7 修复：先 poll() 检查进程是否已退出，
                    # 仅对仍在运行的进程调用 kill()，避免向已结束进程发 SIGKILL。
                    for p in (p_dump, p_gzip):
                        if p is not None:
                            for _pipe in (
                                getattr(p, 'stdout', None),
                                getattr(p, 'stderr', None),
                            ):
                                if _pipe is not None:
                                    try:
                                        _pipe.close()
                                    except Exception:
                                        pass
                            try:
                                if p.poll() is None:   # 进程仍在运行才 kill
                                    p.kill()
                                    p.wait(timeout=5)
                            except Exception:
                                pass
                    if gzip_fd is not None:
                        try:
                            gzip_fd.close()
                        except Exception:
                            pass
                    # V2.7.4: dump_ok 检查放在内层 finally 末尾
                    # 此时子进程已处理完毕、文件描述符已关闭，可安全判断
                    if not dump_ok:
                        logging.warning(t("warn_db_dump_incomplete"))
                        self._exit_code = 1  # [V3.0.9] B3: 反映部分失败到退出码
                        # [V3.0.12] N2: 清理损坏的 dump 文件, 防止恢复时误用
                        if db_dump.exists():
                            try:
                                db_dump.unlink()
                            except OSError:
                                pass
            finally:
                try:
                    os.unlink(defaults_file)
                except OSError:
                    pass
        else:
            logging.warning(t("warn_db_pwd_unavail_backup"))
            self._exit_code = 1  # [V3.0.9] B3: DB 备份已跳过，标记部分失败

        # ---- 2. Webroot 压缩包 ----
        webroot_tar = backup_dir / "webroot.tar.gz"
        if self.cfg.webroot_path.exists():
            result = self.run_cmd(
                ["tar", "-czf", str(webroot_tar),
                 "-C", str(self.cfg.webroot_path.parent),
                 self.cfg.webroot_path.name],
                timeout=600, quiet=True,
            )
            if result:
                logging.info(t("ok_webroot_backup", path=webroot_tar))
            else:
                logging.warning(t("warn_webroot_backup_fail"))
                self._exit_code = 1  # [V3.0.9] B3
        else:
            logging.warning(t("warn_webroot_missing", path=self.cfg.webroot_path))
            self._exit_code = 1  # [V3.0.9] B3

        # ---- 3. Nginx 配置 ----
        if self.cfg.nginx_conf.exists():
            nginx_bak = backup_dir / self.cfg.nginx_conf.name
            try:
                shutil.copy2(self.cfg.nginx_conf, nginx_bak)
                logging.info(t("ok_nginx_backup", path=nginx_bak))
            except OSError as e:
                logging.warning(t("warn_nginx_bak_copy_fail", e=e))

        # ---- 4. Fail2Ban + logrotate 配置 ----
        # [V3.0.9] B7: 将防护/日志配置纳入备份，恢复后无需重跑 update
        _safe_name = self.cfg.systemd_prefix
        _extras_dir = backup_dir / "extras"
        _extra_srcs = [
            (Path(f"/etc/fail2ban/filter.d/wordpress-{_safe_name}.conf"),
             f"fail2ban-filter-wordpress-{_safe_name}.conf"),
            (Path(f"/etc/fail2ban/jail.d/wordpress-{_safe_name}.conf"),
             f"fail2ban-jail-wordpress-{_safe_name}.conf"),
            (Path(f"/etc/logrotate.d/nginx-wp-{_safe_name}"),
             f"logrotate-nginx-wp-{_safe_name}"),
        ]
        # [V3.0.12] N4: mkdir+chmod 提取到循环外, 消除重复系统调用
        _has_extras = any(_src.exists() for _src, _ in _extra_srcs)
        if _has_extras:
            try:
                _extras_dir.mkdir(exist_ok=True)
                _extras_dir.chmod(0o700)  # [V3.0.11] B3: 不依赖 umask
            except OSError as _e:
                logging.warning(t("warn_extra_backup_fail",
                                  name="extras/", e=_e))
                _has_extras = False
        if _has_extras:
            for _src, _bak_name in _extra_srcs:
                if _src.exists():
                    try:
                        shutil.copy2(_src, _extras_dir / _bak_name)
                        logging.info(t("ok_extra_backup",
                                       path=_extras_dir / _bak_name))
                    except OSError as _e:
                        logging.warning(t("warn_extra_backup_fail",
                                          name=_src.name, e=_e))

        # 摘要
        # [V3.0.10] N3: rglob 递归统计 extras/ 子目录文件，确保报告大小准确
        total_size = sum(
            f.stat().st_size for f in backup_dir.rglob("*") if f.is_file()
        )
        total_mb = total_size / (1024 * 1024)
        print(f"\n{'=' * 50}")
        print(t("backup_done", path=backup_dir))
        print(t("backup_size", mb=total_mb))
        print(f"{'=' * 50}\n")

        # ---- 5. 本次备份完整性校验 ----
        # 在清理旧备份前验证新备份完整性，避免损坏的新备份导致健康旧备份被删除
        # 所有实际生成的压缩文件均须通过 gzip -t，任意一个失败即视为备份不可信
        gz_files_to_check = [f for f in (db_dump, webroot_tar)
                             if f.exists() and f.stat().st_size > 0]
        backup_verified = bool(gz_files_to_check)  # 至少有一个文件才有意义
        for gz_file in gz_files_to_check:
            try:
                r = subprocess.run(
                    ["gzip", "-t", str(gz_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=120, check=False,
                )
                if r.returncode != 0:
                    logging.warning(t("warn_backup_gz_fail",
                        name=gz_file.name,
                        detail=r.stderr.strip()[:100] if r.stderr else "gzip -t non-zero exit"))
                    backup_verified = False  # 任一文件损坏即标记失败
            except Exception as e:
                logging.warning(t("warn_backup_integrity_err", name=gz_file.name, e=e))
                backup_verified = False

        if not backup_verified:
            logging.warning(t("warn_backup_integrity"))

        # ---- 6. 旧备份清理（仅在本次备份通过校验后执行）----
        if keep_count > 0 and backup_verified:
            domain_backup_root = backup_dir.parent  # /root/backups/{domain}/
            try:
                all_backups = sorted(
                    [d for d in domain_backup_root.iterdir() if d.is_dir()],
                    key=lambda d: d.name,  # 目录名为 YYYYMMDD_HHMMSS，按名称排序即按时间排序
                )
                if len(all_backups) > keep_count:
                    to_remove = all_backups[:-keep_count]
                    for old_dir in to_remove:
                        try:
                            shutil.rmtree(old_dir)
                            logging.info(t("info_cleanup_old_bak", name=old_dir.name))
                        except OSError as e:
                            logging.warning(t("warn_cleanup_old_bak_fail", name=old_dir.name, e=e))
                    logging.info(t("info_backup_cleanup_summary",
                        keep=keep_count, removed=len(to_remove)))
            except OSError as e:
                logging.warning(t("warn_list_bak_fail", e=e))

    # -----------------------------------------------------------------------
    # 状态查询
    # -----------------------------------------------------------------------
    def show_status(self):
        """输出站点运行状态摘要：证书到期、服务状态、定时器、磁盘空间。"""
        domain = self.cfg.domain
        print(t("status_header", domain=domain))

        # 证书信息
        cert_file = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
        if cert_file.exists():
            try:
                r = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout",
                     "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=10, check=False,
                )
                if r.returncode == 0:
                    print(t("status_ssl", info=r.stdout.strip()))
                # 30 天预警
                r2 = subprocess.run(
                    ["openssl", "x509", "-checkend", str(30 * 86400),
                     "-noout", "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=10, check=False,
                )
                if r2.returncode != 0:
                    print(t("status_ssl_expiry_warn"))
            except Exception:
                print(t("status_ssl_unreadable"))
        else:
            print(t("status_ssl_missing"))

        # 服务状态
        # V2.7.1: 外置数据库模式下跳过本地数据库服务检查
        status_services = [
            ("nginx", "Nginx"),
            (self.php_fpm_svc, "PHP-FPM"),
        ]
        # [V2.9.9] Redis 服务状态 (--redis 启用时)
        # [V3.0.1] B4: Debian/Ubuntu 服务名为 redis-server, RHEL/CentOS 为 redis
        if self.cfg.redis_cache:
            # [V3.0.9] C1: 统一委托 _detect_redis_service_name()
            status_services.append((self._detect_redis_service_name(), "Redis"))
        if self.cfg.is_external_db:
            print(t("status_external_db", host=self.cfg.db_host))
        else:
            status_services.append((self.db_svc, t("label_database")))
        for svc_name, svc_label in status_services:
            try:
                r = subprocess.run(
                    ["systemctl", "is-active", svc_name],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    universal_newlines=True, timeout=5, check=False,
                )
                status = r.stdout.strip()
                icon = "✅" if status == "active" else "❌"
                print(f"{icon} {svc_label} ({svc_name}): {status}")
            except Exception:
                print(t("status_svc_unknown", label=svc_label, name=svc_name))

        # 续期定时器
        timer_name = f"{self.cfg.systemd_prefix}-ssl.timer"
        try:
            r = subprocess.run(
                ["systemctl", "is-active", timer_name],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                universal_newlines=True, timeout=5, check=False,
            )
            status = r.stdout.strip()
            icon = "✅" if status == "active" else "⚠️"
            print(t("status_timer", icon=icon, name=timer_name, status=status))
        except Exception:
            print(t("status_timer_unknown", name=timer_name))

        # 磁盘空间
        free_mb = self.get_disk_free_mb(self.cfg.webroot_path)
        icon = "✅" if free_mb >= 500 else ("⚠️" if free_mb >= 200 else "❌")
        print(t("status_disk", icon=icon, mb=free_mb, path=self.cfg.webroot_path))

        print()

    # -----------------------------------------------------------------------
    # 从备份恢复 (V2.9.8)
    # -----------------------------------------------------------------------
    def restore(self, backup_path: str = ""):
        """从备份目录恢复站点: 数据库 + webroot + Nginx 配置。

        Args:
            backup_path: 备份目录路径。为空时自动选择最新备份。
        """
        logging.info(t("info_restore_start", domain=self.cfg.domain))
        if self.cfg.dry_run:
            logging.info(t("dry_run_restore"))
            return

        # 定位备份目录
        if backup_path:
            bak_dir = Path(backup_path)
        else:
            domain_bak_root = self.cfg.backup_base_dir / self.cfg.domain
            if not domain_bak_root.exists():
                logging.error(t("err_backup_not_found", path=domain_bak_root))
                return
            candidates = sorted(
                [d for d in domain_bak_root.iterdir() if d.is_dir()],
                key=lambda d: d.name, reverse=True,
            )
            if not candidates:
                logging.error(t("err_backup_no_items"))
                return
            bak_dir = candidates[0]
            logging.info(t("info_restore_auto_bak", path=bak_dir))

        if not bak_dir.is_dir():
            logging.error(t("err_backup_not_dir", path=bak_dir))
            return

        # ---- 1. 恢复数据库 ----
        db_dumps = list(bak_dir.glob("*.sql.gz"))
        if db_dumps:
            db_file = db_dumps[0]
            logging.info(t("info_restore_db", name=db_file.name))
            if not self.db_root_pass and self.cfg.db_root_pass_input:
                self.db_root_pass = self.cfg.db_root_pass_input
            if not self.db_root_pass and self.global_root_pwd_file.exists():
                try:
                    _pwd = self.global_root_pwd_file.read_text().strip()
                    if _pwd and re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _pwd):
                        self.db_root_pass = _pwd
                except OSError:
                    pass
            if self.db_root_pass:
                defaults_file = self._write_mysql_defaults_file(self.db_root_pass)
                p_gunzip = None  # [V3.0.2] B3: 预初始化防 finally NameError
                p_mysql = None
                try:
                    host_args = ["-h", self.cfg.db_host] if self.cfg.is_external_db else []
                    mysql_cmd = [
                        "mysql", f"--defaults-extra-file={defaults_file}",
                        "-u", "root",
                    ] + host_args + [self.cfg.db_name]
                    # gunzip | mysql 管道 (与 backup 的 mysqldump | gzip 风格一致)
                    # [V2.9.9] stderr=DEVNULL 防止管道死锁 (与 backup B8 同模式)
                    p_gunzip = subprocess.Popen(
                        ["gunzip", "-c", str(db_file)],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    )
                    p_mysql = subprocess.Popen(
                        mysql_cmd, stdin=p_gunzip.stdout,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    p_gunzip.stdout.close()
                    _, mysql_err = p_mysql.communicate(timeout=600)
                    p_gunzip.wait(timeout=30)
                    if p_mysql.returncode == 0:
                        logging.info(t("ok_db_restore"))
                    else:
                        logging.warning(t("warn_restore_db_fail",
                            err=mysql_err.decode("utf-8", errors="replace")[:200]))
                        self._exit_code = 1  # [V3.0.9] B3
                except subprocess.TimeoutExpired:
                    logging.warning(t("warn_db_restore_timeout"))
                    self._exit_code = 1  # [V3.0.10] N4: 与 B3 模式对齐
                except Exception as e:
                    logging.warning(t("warn_db_restore_exception", e=e))
                    self._exit_code = 1  # [V3.0.10] N4: 与 B3 模式对齐
                finally:
                    # [V2.9.9] 进程清理: poll+kill 防僵尸 (与 backup B7 同模式)
                    for _p in (p_gunzip, p_mysql):
                        if _p is not None:
                            try:
                                if _p.poll() is None:
                                    _p.kill()
                                    _p.wait(timeout=5)
                            except Exception:
                                pass
                    try:
                        os.unlink(defaults_file)
                    except OSError:
                        pass
            else:
                logging.warning(t("warn_db_pwd_unavail_restore"))
                self._exit_code = 1  # [V3.0.9] B3
        else:
            logging.info(t("info_no_db_dump"))

        # ---- 2. 恢复 webroot ----
        webroot_tar = bak_dir / "webroot.tar.gz"
        if webroot_tar.exists():
            logging.info(t("info_restore_webroot"))
            self.cfg.webroot_path.mkdir(parents=True, exist_ok=True)
            result = self.run_cmd(
                ["tar", "-xzf", str(webroot_tar),
                 "-C", str(self.cfg.webroot_path.parent)],
                timeout=600, quiet=True,
            )
            if result:
                logging.info(t("info_webroot_restore_ok"))
            else:
                logging.warning(t("warn_webroot_restore_fail"))
                self._exit_code = 1  # [V3.0.9] B3
        else:
            logging.info(t("info_no_webroot_tar"))

        # ---- 3. 恢复 Nginx 配置 ----
        nginx_baks = list(bak_dir.glob("*.conf"))
        if nginx_baks:
            logging.info(t("info_restore_nginx"))
            for conf in nginx_baks:
                target = Path(f"/etc/nginx/conf.d/{conf.name}")
                try:
                    shutil.copy2(str(conf), str(target))
                    logging.info(t("info_nginx_conf_restored", name=conf.name))
                except OSError as e:
                    logging.warning(t("warn_nginx_conf_restore_fail", name=conf.name, e=e))

        # ---- 4. 恢复 Fail2Ban + logrotate 配置 ----
        # [V3.0.9] B7: 恢复 setup_fail2ban / setup_logrotate 生成的配置
        _extras_dir = bak_dir / "extras"
        _f2b_restored = False  # [V3.0.11] B1: 追踪是否实际恢复了 f2b 规则
        if _extras_dir.is_dir():
            _extra_dest = {
                "fail2ban-filter-": Path("/etc/fail2ban/filter.d"),
                "fail2ban-jail-":   Path("/etc/fail2ban/jail.d"),
                "logrotate-":       Path("/etc/logrotate.d"),
            }
            for _ef in sorted(_extras_dir.iterdir()):
                if not _ef.is_file():
                    continue
                for _prefix, _dest_dir in _extra_dest.items():
                    if _ef.name.startswith(_prefix):
                        _orig_name = _ef.name[len(_prefix):]
                        try:
                            _dest_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(_ef, _dest_dir / _orig_name)
                            logging.info(t("info_extra_conf_restored",
                                           name=_ef.name))
                            # [V3.0.11] B1: 仅 f2b 文件才标记需重启
                            if _prefix.startswith("fail2ban-"):
                                _f2b_restored = True
                        except OSError as _e:
                            logging.warning(
                                t("warn_extra_conf_restore_fail",
                                  name=_ef.name, e=_e))
                        break

        # [V3.0.11] N6+B1: 仅在实际恢复了 fail2ban 规则文件时重启
        if _f2b_restored and shutil.which("fail2ban-client"):
            self.run_cmd(["systemctl", "restart", "fail2ban"], quiet=True)

        # ---- 5. 修复权限 + 重载 ----
        if self.cfg.webroot_path.exists():
            self.run_cmd(
                ["chown", "-R", f"{self.nginx_user}:{self.nginx_user}",
                 str(self.cfg.webroot_path)], quiet=True,
            )
            wp_config = self.cfg.webroot_path / "wp-config.php"
            if wp_config.exists():
                self.run_cmd(["chmod", "0440", str(wp_config)], quiet=True)

        if self.run_cmd(["nginx", "-t"], quiet=True):
            self.run_cmd(["systemctl", "reload", "nginx"], quiet=True)
        else:
            # [V3.0.12] N3: 配置测试失败时记录警告并标记退出码
            logging.warning(t("warn_nginx_test_fail_restore"))
            self._exit_code = 1
        self.run_cmd(["systemctl", "restart", self.php_fpm_svc], quiet=True)
        logging.info(t("info_restore_done", domain=self.cfg.domain, src=bak_dir.name))
        # [V3.0.7] 提示用户恢复后如需更新配置模板应使用 update 子命令
        logging.info(t("info_restore_config_hint",
            script=self.cfg.script_path, domain=self.cfg.domain))

    # -----------------------------------------------------------------------
    # 配置热更新 (V2.9.8)
    # -----------------------------------------------------------------------
    def update_config(self):
        """重新生成并应用所有配置模板, 不触碰数据库和站点文件。

        适用场景: 脚本升级后将新版 Nginx/PHP/Fail2Ban/logrotate 配置
        应用到已有站点, 无需重走完整 deploy 流程。
        """
        logging.info(t("info_update_start", domain=self.cfg.domain))

        # 1. Nginx HTTPS 配置
        sock_path = self.get_php_sock_path()
        config = generate_https_config(
            self.cfg.domain, self.cfg.webroot_path, sock_path,
            cache_mode=self.cfg.cache_mode,
            allow_xmlrpc=self.cfg.allow_xmlrpc,
        )
        if self.apply_nginx_config_safe(config):
            logging.info(t("info_nginx_updated"))
        else:
            logging.warning(t("warn_nginx_update_fail"))

        # 2. PHP ini
        for ini_path in self._get_php_ini_paths():
            try:
                content = Path(ini_path).read_text(encoding='utf-8')
                for directive, value in (
                    ('upload_max_filesize', '100M'),
                    ('post_max_size', '100M'),
                    ('memory_limit', '256M'),
                    ('max_execution_time', '300'),
                    ('opcache.enable', '1'),
                    ('opcache.memory_consumption', '256'),
                    # [V2.9.9] 与 setup_lemp_and_wp 保持完全一致
                    ('opcache.interned_strings_buffer', '16'),
                    ('opcache.max_accelerated_files', '10000'),
                    ('opcache.revalidate_freq', '2'),
                ):
                    content = patch_php_ini_line(content, directive, value)
                Path(ini_path).write_text(content, encoding='utf-8')
            except Exception as e:
                logging.warning(t("warn_php_ini_fail", path=ini_path, e=e))
        logging.info(t("info_php_updated"))

        # 3. Fail2Ban + logrotate + Brotli + nginx-helper
        self.setup_fail2ban()
        self.setup_logrotate()
        self._setup_brotli()
        # [V3.0.9] B4: 改用 _ensure_wpcli()，允许在 update 时补装 WP-CLI
        self._ensure_wpcli()
        self._install_nginx_helper()
        self._setup_redis_cache()  # [V3.0.11] B2: 允许 update --redis 补装

        # [V3.0.9] B8: 同步 Systemd 续期单元（修正脚本路径变更后旧路径残留）
        self.setup_systemd()

        # 重载服务
        self.run_cmd(["systemctl", "restart", self.php_fpm_svc], quiet=True)
        self.run_cmd(["systemctl", "reload", "nginx"], quiet=True)
        logging.info(t("info_update_done", domain=self.cfg.domain))

    # -----------------------------------------------------------------------
    # 卸载
    # -----------------------------------------------------------------------
    def uninstall(self):
        logging.info(t("info_uninstall_start", domain=self.cfg.domain))
        self.run_cmd(
            ["systemctl", "stop",
             f"{self.cfg.systemd_prefix}-ssl.timer",
             f"{self.cfg.systemd_prefix}-ssl.service"],
            quiet=True,
        )
        self.run_cmd(
            ["systemctl", "disable",
             f"{self.cfg.systemd_prefix}-ssl.timer",
             f"{self.cfg.systemd_prefix}-ssl.service"],
            quiet=True,
        )

        # 清理 Fail2Ban 配置
        safe_name = self.cfg.systemd_prefix
        f2b_filter = Path(f"/etc/fail2ban/filter.d/wordpress-{safe_name}.conf")
        f2b_jail = Path(f"/etc/fail2ban/jail.d/wordpress-{safe_name}.conf")
        f2b_deleted = False
        for f2b_file in (f2b_filter, f2b_jail):
            if f2b_file.exists():
                try:
                    f2b_file.unlink()
                    logging.info(t("info_deleted", path=f2b_file))
                    f2b_deleted = True
                except OSError:
                    pass
        # 仅在实际删除了配置文件时重启 fail2ban 使之生效
        if f2b_deleted and shutil.which("fail2ban-client"):
            self.run_cmd(["systemctl", "restart", "fail2ban"], quiet=True)

        # [V2.9.9] 清理 logrotate 配置 (V2.9.7 setup_logrotate 创建)
        _logrotate_conf = Path(f"/etc/logrotate.d/nginx-wp-{safe_name}")
        if _logrotate_conf.exists():
            try:
                _logrotate_conf.unlink()
                logging.info(t("info_deleted", path=_logrotate_conf))
            except OSError:
                pass

        for f in (self.cfg.service_file, self.cfg.timer_file, self.cfg.nginx_conf):
            if f.exists():
                try:
                    f.unlink()
                    logging.info(t("info_deleted", path=f))
                except OSError:
                    pass

        self.run_cmd(["systemctl", "daemon-reload"], quiet=True)
        self.run_cmd(["systemctl", "reload", "nginx"], quiet=True)
        logging.info(t("ok_uninstall"))
        self.cleanup_and_exit(0)

    # -----------------------------------------------------------------------
    # 部署分支 (从 run() 提取, V3.0.12 N1)
    # -----------------------------------------------------------------------
    def _run_deploy_branch(self) -> bool:
        """[V3.0.12] N1: 从 run() 提取的完整部署流程, early-return 风格。

        Returns:
            True = 部署成功, False = 失败 (self._exit_code 已设置)。
        """
        if not self.setup_lemp_and_wp():
            logging.error(t("err_deploy_deps"))
            self._exit_code = 1
            return False

        if self.check_shutdown():
            self._exit_code = 130
            return False

        if not self.setup_nginx_for_challenge():
            logging.error(t("err_deploy_nginx_acme"))
            self._exit_code = 1
            return False

        if self.check_shutdown():
            self._exit_code = 130
            return False

        # [V3.0.12] N1: verify_dns 返回 (main_ok, www_ok)
        _dns_main, _dns_www = self.verify_dns()
        if not _dns_main:
            logging.error(t("err_deploy_dns"))
            self._exit_code = 1
            return False

        if not self.verify_http_challenge():
            logging.error(t("err_deploy_http_challenge"))
            self._exit_code = 1
            return False

        if self.check_shutdown():
            self._exit_code = 130
            return False

        # [V3.0.12] N1: 根据 www DNS 结果动态裁剪 certbot -d 列表
        if not self.apply_cert(include_www=_dns_www):
            logging.error(t("err_deploy_cert"))
            self._exit_code = 1
            return False

        if self.check_shutdown():
            self._exit_code = 130
            return False

        if not self.setup_nginx_for_production():
            logging.error(t("err_deploy_https"))
            self._exit_code = 1
            return False

        # 部署成功 — 执行后续增强步骤
        self._setup_brotli()
        self.verify_site_health()
        self.verify_wp_installation()
        self.setup_systemd()
        self.setup_fail2ban()
        self.setup_logrotate()
        self._install_nginx_helper()
        self._setup_redis_cache()
        self.print_final_summary()
        return True

    # -----------------------------------------------------------------------
    # 主运行入口
    # -----------------------------------------------------------------------
    def run(self, renew_only: bool = False, force_renew: bool = False):
        """主运行入口。

        Args:
            renew_only: True = 仅执行证书续期 (对应 renew 子命令)；
                        False = 完整部署流程 (对应 deploy 子命令)。
            force_renew: True = 强制续期，忽略证书到期时间。
        """
        self.setup_signals()
        self.acquire_lock()

        deploy_ok = False
        try:
            if renew_only:
                self.renew_cert(force=force_renew)
                deploy_ok = (self._exit_code == 0)
            else:
                deploy_ok = self._run_deploy_branch()
        finally:
            exit_code = 0 if deploy_ok else (self._exit_code if self._exit_code != 0 else 1)
            # 首次部署失败时回滚本次创建的资源（renew 模式无需回滚）
            # [V2.9.6] 回滚异常不得阻断清理流程, 否则 cleanup_and_exit 永远不会执行
            if not deploy_ok and not renew_only:
                try:
                    self._rollback_deploy()
                except Exception as _rb_err:
                    logging.error(t("err_rollback_exception", e=_rb_err, tb=traceback.format_exc()))
            self.cleanup_and_exit(exit_code)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def _add_common_args(sub_parser):
    """为子命令添加公共参数。"""
    sub_parser.add_argument(
        "--domain",
        default=os.environ.get("WP_DOMAIN"),
        help=t("help_domain"),
    )
    sub_parser.add_argument(
        "--dry-run", action="store_true", help=t("help_dry_run"),
    )
    sub_parser.add_argument(
        "--staging", action="store_true",
        help=t("help_staging"),
    )
    sub_parser.add_argument(
        "--quiet", action="store_true",
        help=t("help_quiet"),
    )
    # V2.7.1: --db-host 提升为公共参数，backup/renew/status 均需知道数据库位置
    sub_parser.add_argument(
        "--db-host", default=None, metavar="HOST",
        help=t("help_db_host"),
    )
    # [V2.9.3] --db-root-pass 提升为公共参数，backup 子命令需要它来完成数据库 dump；
    # 未启用 --persist-root-pwd 时此为唯一传入途径，不提供将导致数据库备份静默跳过。
    sub_parser.add_argument(
        "--db-root-pass", default=None,
        help=t("help_db_root_pass"),
    )
    # [V3.0.4] --backup-dir 提升为公共参数，backup/restore/deploy 均需要一致的路径；
    # renew/status/update/uninstall 不关心该参数，getattr 默认值保护已在 SiteConfig 处理。
    sub_parser.add_argument(
        "--backup-dir", default=None, metavar="PATH",
        help=t("help_backup_dir"),
    )


def main():
    # ── 语言预扫描：在构建解析器前确定 _LANG ─────────────────────────────────
    # argparse help= 参数在 add_argument() 调用时立即求值，因此必须在构建任何
    # 解析器之前先确定语言，否则 --lang 只能影响逻辑输出，无法影响帮助文本。
    # _pre 解析器不设 choices= 以避免在 root 检查前因非法值提前退出；
    # 合法性校验由主 parser 的 --lang 负责。
    global _LANG
    _pre = argparse.ArgumentParser(add_help=False)
    _pre.add_argument("--lang", default=None)
    _pre_args, _ = _pre.parse_known_args()
    if _pre_args.lang in ("zh", "en"):
        _LANG = _pre_args.lang
        # 持久化：将语言偏好写入配置文件，后续运行无需重复指定 --lang
        _write_lang_file(_LANG)

    if os.geteuid() != 0:
        print(t("err_root_required"))
        sys.exit(1)

    # ── 语言变更检测：仅在未通过 --lang 显式指定时触发 ─────────────────────
    _prompt_lang_change()

    parser = argparse.ArgumentParser(
        description=t("parser_description"),
        usage="%(prog)s [--lang zh|en] <command> [options]",
    )
    parser.add_argument(
        "--version", action="version", version=f"WP-SSL-Bootstrap V{__version__}",
    )
    parser.add_argument(
        "--lang", choices=["zh", "en"], default=None,
        help=t("help_lang"),
    )
    subparsers = parser.add_subparsers(dest="command", help=t("subcmd_list"))

    # --- deploy 子命令 ---
    p_deploy = subparsers.add_parser(
        "deploy", help=t("subcmd_deploy"),
    )
    _add_common_args(p_deploy)
    p_deploy.add_argument(
        "--email",
        default=os.environ.get("WP_EMAIL"),
        help=t("help_email"),
    )
    p_deploy.add_argument(
        "--cache", choices=["none", "fastcgi"], default="none",
        help=t("help_cache"),
    )
    p_deploy.add_argument(
        "--redis", action="store_true",
        help=t("help_redis"),
    )
    p_deploy.add_argument(
        "--skip-deps", action="store_true",
        help=t("help_skip_deps"),
    )
    p_deploy.add_argument(
        "--allow-xmlrpc", action="store_true",
        help=t("help_allow_xmlrpc"),
    )
    p_deploy.add_argument(
        "--php-version", default=None, metavar="X.Y",
        help=t("help_php_version"),
    )
    # V2.7.1: --db-host 已移至 _add_common_args 公共参数
    # [V2.9.3]: --db-root-pass 已移至 _add_common_args 公共参数（backup 子命令同样需要）
    p_deploy.add_argument(
        "--persist-root-pwd", action="store_true",
        help=t("help_persist_root_pwd"),
    )
    p_deploy.add_argument(
        "--db-wait-timeout", type=int, default=None, metavar="SECONDS",
        help=t("help_db_wait_timeout"),
    )

    # --- renew 子命令 ---
    p_renew = subparsers.add_parser("renew", help=t("subcmd_renew"))
    _add_common_args(p_renew)
    p_renew.add_argument(
        "--force", action="store_true",
        help=t("help_force_renew"),
    )

    # --- status 子命令 ---
    p_status = subparsers.add_parser(
        "status", help=t("subcmd_status"),
    )
    _add_common_args(p_status)
    p_status.add_argument(
        "--redis", action="store_true",
        help=t("help_redis_status"),
    )

    # --- backup 子命令 ---
    p_backup = subparsers.add_parser(
        "backup", help=t("subcmd_backup"),
    )
    _add_common_args(p_backup)
    p_backup.add_argument(
        "--keep", type=int, default=5, metavar="N",
        help=t("help_keep"),
    )

    # --- restore 子命令 ---
    p_restore = subparsers.add_parser(
        "restore", help=t("subcmd_restore"),
    )
    _add_common_args(p_restore)
    p_restore.add_argument(
        "--from", dest="restore_from", default="", metavar="PATH",
        help=t("help_restore_from"),
    )
    p_restore.add_argument(
        "--cache", choices=["none", "fastcgi"], default="none",
        help=t("help_cache_update"),
    )
    p_restore.add_argument(
        "--redis", action="store_true",
        help=t("help_redis_update"),
    )
    p_restore.add_argument(
        "--allow-xmlrpc", action="store_true",
        help=t("help_allow_xmlrpc_update"),
    )

    # --- update 子命令 ---
    p_update = subparsers.add_parser(
        "update", help=t("subcmd_update"),
    )
    _add_common_args(p_update)
    p_update.add_argument(
        "--cache", choices=["none", "fastcgi"], default="none",
        help=t("help_cache_update"),
    )
    p_update.add_argument(
        "--redis", action="store_true",
        help=t("help_redis_update"),
    )
    p_update.add_argument(
        "--allow-xmlrpc", action="store_true",
        help=t("help_allow_xmlrpc_update"),
    )
    p_update.add_argument(
        "--php-version", default=None, metavar="X.Y",
        help=t("help_php_version"),
    )

    # --- uninstall 子命令 ---
    p_uninstall = subparsers.add_parser(
        "uninstall", help=t("subcmd_uninstall"),
    )
    _add_common_args(p_uninstall)

    args = parser.parse_args()

    # 未指定子命令时打印帮助并退出
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not args.domain:
        parser.error(t("err_no_domain"))

    # email 仅 deploy 时强制要求
    if args.command == "deploy":
        if not getattr(args, 'email', None):
            parser.error(t("err_no_email"))

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    cfg = SiteConfig(args)
    manager = WPDeployManager(cfg)

    if args.command == "uninstall":
        # [V3.0.9] B1: 与其他写操作子命令统一，补加排他锁
        manager.setup_signals()
        manager.acquire_lock()
        _sub_exit = 0
        try:
            manager.uninstall()
        except Exception as _sub_e:
            logging.error(t("err_cmd_exception", e=_sub_e))
            _sub_exit = 1
        finally:
            manager.cleanup_and_exit(_sub_exit or manager._exit_code)
    elif args.command == "restore":
        # [V3.0.2] B5: 恢复操作需要排他锁
        manager.setup_signals()
        manager.acquire_lock()
        _sub_exit = 0
        try:
            manager.restore(backup_path=getattr(args, 'restore_from', ''))
        except Exception as _sub_e:
            logging.error(t("err_cmd_exception", e=_sub_e))
            _sub_exit = 1
        finally:
            manager.cleanup_and_exit(_sub_exit or manager._exit_code)
    elif args.command == "update":
        # [V3.0.2] B5: 配置热更新需要排他锁
        manager.setup_signals()
        manager.acquire_lock()
        _sub_exit = 0
        try:
            manager.update_config()
        except Exception as _sub_e:
            logging.error(t("err_cmd_exception", e=_sub_e))
            _sub_exit = 1
        finally:
            manager.cleanup_and_exit(_sub_exit or manager._exit_code)
    elif args.command == "status":
        manager.show_status()
    elif args.command == "backup":
        # [V3.0.2] B5: 备份操作需要排他锁
        manager.setup_signals()
        manager.acquire_lock()
        _sub_exit = 0
        try:
            manager.backup(keep_count=getattr(args, 'keep', 5))
        except Exception as _sub_e:
            logging.error(t("err_cmd_exception", e=_sub_e))
            _sub_exit = 1
        finally:
            manager.cleanup_and_exit(_sub_exit or manager._exit_code)
    elif args.command == "renew":
        manager.run(renew_only=True, force_renew=getattr(args, 'force', False))
    else:
        manager.run(renew_only=False)


if __name__ == "__main__":
    main()