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
WP-SSL-Bootstrap: 高可用建站引擎
适应平台: EL7-10 兼容发行版 (RHEL·CentOS·AlmaLinux·Rocky·Alibaba Cloud Linux 等) / Ubuntu / Debian
=============================================================================

【核心功能】
1. 智能环境探针：动态识别包管理器、Nginx 用户、PHP-FPM 服务与 socket、数据库服务。
2. 数据库安全初始化：auth_socket/unix_socket 插件自适应，Root 凭据不暴露于进程列表。
3. 多源容灾下载：官方中文源与全球主源 fallback，SHA256 严格校验，下载前磁盘预检。
4. 严格文件权限与 SELinux 处理：最小权限原则 + SELinux 布尔值自动配置。
5. 零停机 SSL 签发与多级 CA 容灾：Let's Encrypt 为主，ZeroSSL备用，
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

__version__ = "3.2.0"

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
from typing import Optional  # [V3.2.42] FIX-6: Python 3.6+ always ships typing; remove dead fallback
# import concurrent.futures  # [V3.2.36-P2] 移至使用点延迟导入
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


def _write_lang_file(chosen: str, env_at_choice: str = "") -> None:
    """Atomically write language config with 0600 permissions.

    File format: "chosen:env_at_choice"  (e.g. "zh:en")
    env_at_choice defaults to the current system language when not supplied.

    Falls back to direct (non-atomic) write if rename fails,
    ensuring the language preference is never silently lost.
    """
    _env = env_at_choice if env_at_choice in ("zh", "en") else _env_lang()
    content = f"{chosen}:{_env}"
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
        # [V3.2.12] P2-12: 合并两个等效的 except 分支
        try:
            tmp.unlink()
        except Exception:
            pass
    # Fallback: direct write (non-atomic but functional)
    try:
        fd = os.open(str(_LANG_CONFIG_FILE),
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, _bytes)
            os.fsync(fd)  # [V3.2.2] L-1
        finally:
            os.close(fd)
    except OSError as _fb_e:
        # [V3.2.5] A-14: 记录 fallback 写入失败, 便于排查
        logging.debug("_write_lang_file fallback write failed: %s", _fb_e)


def _sd_escape(path):
    # type: (str) -> str
    """转义路径使其可安全用于 systemd unit ExecStart= 的双引号参数。

    提升至模块级以便 setup_systemd() 与 setup_wp_cron_timer() 共用。
    [V3.2.43] FIX-7: 原为 setup_wp_cron_timer() 内嵌函数，导致
    setup_systemd() 无法访问，ExecStart 路径缺少 % / $ 转义。

    转义规则 (systemd ExecStart= 双引号上下文):
      \\  ->  \\\\   (反斜杠自身)
      "  ->  \\"   (闭合引号)
      %  ->  %%   (systemd specifier, 如 %n %i)
      $  ->  $$   (systemd 环境变量展开, v219+)
    """
    return (path
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('%', '%%')
            .replace('$', '$$'))


def _env_lang() -> str:
    """Return language from environment variables only (ignores config file)."""
    raw = (
        os.environ.get("WP_LANG", "")
        or os.environ.get("LANG", "")
        or os.environ.get("LC_ALL", "")
        or os.environ.get("LANGUAGE", "")
    ).lower()
    return "zh" if raw.startswith("zh") else "en"


def _read_lang_config():  # -> tuple[str, str | None] | None
    """Parse the language config file.

    Returns:
        (chosen, env_at_choice)  — both are 'zh' or 'en'
        (chosen, None)           — old single-token format; env unknown
        None                     — file absent or unreadable
    """
    try:
        if _LANG_CONFIG_FILE.exists():
            val = _LANG_CONFIG_FILE.read_text(encoding="utf-8").strip().lower()
            if ":" in val:
                parts = val.split(":", 1)
                if parts[0] in ("zh", "en") and parts[1] in ("zh", "en"):
                    return (parts[0], parts[1])
            elif val in ("zh", "en"):
                return (val, None)
    except OSError:
        pass
    return None


def _saved_lang():  # -> str | None
    """Compatibility shim: return saved chosen language or None."""
    cfg = _read_lang_config()
    return cfg[0] if cfg is not None else None



# [V3.2.12] P2-9: 添加线程锁保护缓存变量，防止未来多线程调用时数据竞争
import threading as _threading
_CHINA_CLOUD_CACHE = None  # type: Optional[str]  # [V3.2.3] M-9: Python 3.6 compat
_CHINA_CLOUD_LOCK = _threading.Lock()


def _set_china_cloud_cache(value):
    # type: (str) -> str
    """[V3.2.13] P1-1: Thread-safe cache write for _is_china_cloud().
    [V3.2.22] P1-2: 双重检查锁 — 锁内二次校验，防止并发冗余 HTTP 探测。
    """
    global _CHINA_CLOUD_CACHE
    with _CHINA_CLOUD_LOCK:
        # [V3.2.22] P1-2: 双重检查：另一线程可能已在我们持锁前完成写入
        if _CHINA_CLOUD_CACHE is not None:
            return _CHINA_CLOUD_CACHE
        _CHINA_CLOUD_CACHE = value
    return value

def _is_china_cloud() -> str:
    """检测是否运行在国内云服务器上。返回云厂商名称或空字符串。

    [V3.1.4] F3: 结果缓存至模块级变量, 避免重复 HTTP 请求。
    [V3.3.0] 新增: 天翼云/京东云/火山引擎/UCloud/百度云/金山云检测。

    检测策略（每层均短路返回）:
      1. /etc/os-release 关键词匹配 — 速度最快, 覆盖定制发行版
      2. 各厂商专用 release 文件    — /etc/ctyun-release 等
      3. DMI sysfs 硬件信息         — product_name / sys_vendor
      4. 厂商专有元数据端点          — HTTP 超时 1s, 失败静默
      5. 通用 IMDS 端点              — 169.254.169.254 + 厂商特征响应
    """
    with _CHINA_CLOUD_LOCK:
        if _CHINA_CLOUD_CACHE is not None:
            return _CHINA_CLOUD_CACHE

    # ── 层 1: /etc/os-release ──────────────────────────────────────────────
    try:
        osr = Path("/etc/os-release").read_text(encoding="utf-8").lower()
        if any(k in osr for k in ("alibaba", "alinux", "anolis", "aliyun")):
            return _set_china_cloud_cache("Alibaba Cloud")
        if any(k in osr for k in ("tencentos", "tlinux", "tencent")):
            return _set_china_cloud_cache("Tencent Cloud")
        if any(k in osr for k in ("huaweicloud", "euler", "huawei")):
            return _set_china_cloud_cache("Huawei Cloud")
        if any(k in osr for k in ("ctyun", "chinatelecom", "ct-cloud")):
            return _set_china_cloud_cache("CTYun")
        if any(k in osr for k in ("jdcloud", "jd cloud", "jdos")):
            return _set_china_cloud_cache("JD Cloud")
        if any(k in osr for k in ("volcengine", "velinux", "bytedance")):
            return _set_china_cloud_cache("Volcano Engine")
        if "ucloud" in osr:
            return _set_china_cloud_cache("UCloud")
        if any(k in osr for k in ("bce", "baiduyun", "baidu cloud")):
            return _set_china_cloud_cache("Baidu Cloud")
        if any(k in osr for k in ("ksyun", "kingsoft")):
            return _set_china_cloud_cache("Kingsoft Cloud")
    except OSError:
        pass

    # ── 层 2: 厂商专用 release 文件 ───────────────────────────────────────
    _release_files = [
        ("/etc/ctyun-release",       "CTYun"),
        ("/etc/ct-release",          "CTYun"),
        ("/etc/jdcloud-release",     "JD Cloud"),
        ("/etc/ve-release",          "Volcano Engine"),
        ("/etc/volcengine-release",  "Volcano Engine"),
        ("/etc/ucloud-release",      "UCloud"),
        ("/etc/bce-release",         "Baidu Cloud"),
        ("/etc/baidu-release",       "Baidu Cloud"),
        ("/etc/ksyun-release",       "Kingsoft Cloud"),
    ]
    for _rf, _vendor in _release_files:
        if Path(_rf).exists():
            return _set_china_cloud_cache(_vendor)

    # ── 层 3: DMI sysfs 硬件信息 ──────────────────────────────────────────
    for dmi_path in ("/sys/class/dmi/id/product_name",
                     "/sys/class/dmi/id/sys_vendor",
                     "/sys/class/dmi/id/board_vendor"):
        try:
            dmi = Path(dmi_path).read_text(encoding="utf-8").lower().strip()
            if "alibaba" in dmi or "aliyun" in dmi:
                return _set_china_cloud_cache("Alibaba Cloud")
            if "tencent" in dmi:
                return _set_china_cloud_cache("Tencent Cloud")
            if "huawei" in dmi:
                return _set_china_cloud_cache("Huawei Cloud")
            if "ctyun" in dmi or "chinatelecom" in dmi:
                return _set_china_cloud_cache("CTYun")
            if "jdcloud" in dmi or "jd cloud" in dmi:
                return _set_china_cloud_cache("JD Cloud")
            if "volcengine" in dmi or "bytedance" in dmi:
                return _set_china_cloud_cache("Volcano Engine")
            if "ucloud" in dmi:
                return _set_china_cloud_cache("UCloud")
            if "baiduyun" in dmi or "baidu cloud" in dmi or "baidu-cloud" in dmi:  # [PATCH-L1] 收紧匹配
                return _set_china_cloud_cache("Baidu Cloud")
            if "ksyun" in dmi or "kingsoft" in dmi:
                return _set_china_cloud_cache("Kingsoft Cloud")
        except OSError:
            pass

    # ── 层 4: 厂商专有元数据端点 ───────────────────────────────────────────
    import urllib.request as _ureq
    _meta_probes = [
        # 阿里云 ECS 专有地址 (link-local, 仅限 ECS 实例内部)
        ("http://100.100.100.200/latest/meta-data/region-id",
         {"Metadata": "true"}, "Alibaba Cloud"),
        # 腾讯云 CVM 专有地址
        ("http://169.254.0.23/meta-data/instance-id",
         {"Metadata": "true"}, "Tencent Cloud"),
        # 京东云专有地址
        ("http://100.80.80.80/latest/meta-data/instance-id",
         {"Metadata": "true"}, "JD Cloud"),
        # 火山引擎专有地址
        ("http://100.96.0.96/latest/meta-data/",
         {}, "Volcano Engine"),
    ]
    for _url, _headers, _vendor in _meta_probes:
        try:
            _req = _ureq.Request(_url, headers=_headers)
            with _ureq.urlopen(_req, timeout=1) as _resp:
                if _resp.read():
                    return _set_china_cloud_cache(_vendor)
        except Exception:
            pass

    # ── 层 5: 通用 IMDS 端点 (169.254.169.254) ────────────────────────────
    # [V3.2.11] P0-3: 改用具体端点而非扫描整个 user-data；
    # 仅匹配不可能在 AWS/GCP instance-id 中出现的厂商特有前缀，
    # 防止 EC2 用户自定义 user-data 触发误判。
    _imds_probes = [
        # [V3.2.12] P0-2: 华为云 OpenStack meta_data.json 返回 JSON，
        # 其 availability_zone 字段值以 "cn-" 开头 (如 "cn-north-4a")，
        # 而 AWS/GCP 的 IMDS 不使用该端点格式，不会误判。
        ("http://169.254.169.254/openstack/latest/meta_data.json",
         {"Metadata": "true"}, "cn-", "Huawei Cloud"),
        # UCloud 实例 ID 以 "uhost-" 开头
        ("http://169.254.169.254/latest/meta-data/instance-id",
         {"Metadata": "true"}, "uhost-", "UCloud"),
        # 百度云实例 ID 以 "i-" 开头但 region 固定含 "bj/bd/gz/su"
        ("http://169.254.169.254/latest/meta-data/local-hostname",
         {"Metadata": "true"}, "bce-", "Baidu Cloud"),
    ]
    for _imds_url, _imds_hdr, _imds_prefix, _imds_vendor in _imds_probes:
        try:
            _req = _ureq.Request(_imds_url, headers=_imds_hdr)
            with _ureq.urlopen(_req, timeout=1) as _resp:
                _body = _resp.read(512).decode("utf-8", errors="replace")
                # [V3.2.13] P0-1: Huawei Cloud meta_data.json returns JSON;
                # parse availability_zone instead of raw prefix matching.
                if _imds_vendor == "Huawei Cloud":
                    try:
                        _meta = json.loads(_body)
                        _az = str(_meta.get("availability_zone", "")).lower()
                        if _az.startswith(_imds_prefix):
                            return _set_china_cloud_cache(_imds_vendor)
                    except (ValueError, KeyError, TypeError):
                        pass
                    continue
                _body_lower = _body.lower()
                if _body_lower.startswith(_imds_prefix) or ("\n" + _imds_prefix) in _body_lower:
                    return _set_china_cloud_cache(_imds_vendor)
        except Exception:
            pass

    return _set_china_cloud_cache("")


def _prompt_china_cloud_lang() -> None:
    """国内云首次运行时提示选择中文。"""
    global _LANG
    if _read_lang_config() is not None:
        return
    if os.environ.get("WP_LANG", "").strip():
        return
    if not sys.stdin.isatty():
        return
    # [V3.2.3] L-4: self-update 无需云检测 HTTP 请求
    if len(sys.argv) > 1 and sys.argv[1] == "self-update":
        return
    cloud = _is_china_cloud()
    if not cloud:
        return
    print(t("prompt_china_cloud_detected", cloud=cloud))
    try:
        choice = input("选择 / Choose [1/2, Enter=中文]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if choice in ("", "1"):
        _LANG = "zh"
    elif choice == "2":
        _LANG = "en"
    else:
        _LANG = "zh"
    _write_lang_file(_LANG, _env_lang())
    print(f"语言已设置 / Language set → {_LANG.upper()}")


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
    """仅当系统语言相对上次选择时发生了真实切换时才询问用户。

    旧格式兼容 (env_at_choice 为 None): 静默迁移, 本次不弹提示。
    """
    global _LANG

    cfg = _read_lang_config()
    if cfg is None:
        return

    chosen, env_at_choice = cfg

    if _LANG != chosen:
        return

    if os.environ.get("WP_LANG_NOCHECK", "").strip() == "1":
        return

    if not sys.stdin.isatty():
        return

    current_env = _env_lang()

    # 旧格式迁移
    if env_at_choice is None:
        _write_lang_file(chosen, current_env)
        return

    # 系统语言未变 — 不打扰
    if current_env == env_at_choice:
        return

    # 系统语言变了 → 询问
    print(
        f"\n[语言变更提示] 系统语言已从 {env_at_choice.upper()} 切换至 "
        f"{current_env.upper()}，当前保存语言: {chosen.upper()}"
    )
    print(
        f"    [Language change] System language changed: "
        f"{env_at_choice.upper()} → {current_env.upper()}, "
        f"saved preference: {chosen.upper()}"
    )
    print(f"  [1] 保留 {chosen.upper()} / Keep {chosen.upper()} (Enter)")
    print(f"  [2] 跟随系统 → {current_env.upper()} / Follow system → {current_env.upper()}")
    print( "  [3] 手动输入 / Enter manually (zh/en)")
    print()

    try:
        choice = input("选择 / Choose [1/2/3 or zh/en, Enter=keep]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice in ("", "1"):
        _write_lang_file(chosen, current_env)
        return

    if choice == "2":
        new_chosen = current_env
    elif choice in ("zh", "en"):
        new_chosen = choice
    else:
        try:
            code = input("语言代码 / Language code (zh/en): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if code not in ("zh", "en"):
            print(f"无效代码 / Invalid: \'{code or '(empty)'}\', keeping {chosen.upper()}")
            _write_lang_file(chosen, current_env)
            return
        new_chosen = code

    _LANG = new_chosen
    _write_lang_file(new_chosen, current_env)
    print(f"语言已切换 / Language switched → {new_chosen.upper()}")


_LANG = _detect_lang()  # type: str  # noqa: M-9 compat ok  # thread-safety: main-thread only

_MESSAGES: dict = {
    # ── SiteConfig validation (print) ──────────────────────────────────────
    "err_domain_fmt": {
        "zh": "严重错误：域名格式不合法 ({domain})",
        "en": "Fatal: Invalid domain format ({domain})",
    },
    "err_domain_len": {
        "zh": "严重错误：域名长度超出 DNS 规范上限 253 字符 (当前 {n})",
        "en": "Fatal: Domain exceeds DNS 253-char limit (current: {n})",
    },
    "err_email_fmt": {
        "zh": "严重错误：邮箱格式不合法 ({email})",
        "en": "Fatal: Invalid email format ({email})",
    },
    "err_dbhost_fmt": {
        "zh": "严重错误：数据库主机地址格式不合法 ({host})",
        "en": "Fatal: Invalid database host format ({host})",
    },
    "warn_timeout_env": {
        "zh": "环境变量 WP_DB_WAIT_TIMEOUT 不是合法整数 (\'{val}\')，已忽略。",
        "en": "WP_DB_WAIT_TIMEOUT is not a valid integer (\'{val}\'), ignored.",
    },
    "err_timeout_val": {
        "zh": "严重错误：--db-wait-timeout 必须为正整数 (当前值: {val})",
        "en": "Fatal: --db-wait-timeout must be a positive integer (got: {val})",
    },
    # ── Root privilege ──────────────────────────────────────────────────────
    "err_root_required": {
        "zh": "错误：此脚本必须以 root 权限运行。",
        "en": "Error: This script must be run as root.",
    },
    # ── Deploy success (print) ──────────────────────────────────────────────
    "deploy_success": {
        "zh": "部署成功！",
        "en": "Deployment successful!",
    },
    "deploy_url": {
        "zh": "网站地址: https://{domain}",
        "en": "Site URL: https://{domain}",
    },
    "deploy_cred": {
        "zh": "凭据文件 (权限 600): {path}",
        "en": "Credentials file (mode 600): {path}",
    },
    # ── Backup (print) ──────────────────────────────────────────────────────
    "backup_done": {
        "zh": "备份完成: {path}",
        "en": "Backup complete: {path}",
    },
    "backup_size": {
        "zh": "   总大小: {mb:.1f}MB",
        "en": "   Total size: {mb:.1f}MB",
    },
    # [V3.0.9] B7 / S5 新增消息
    "ok_extra_backup": {
        "zh": "附加配置已备份: {path}",
        "en": "Extra config backed up: {path}",
    },
    "warn_extra_backup_fail": {
        "zh": "附加配置备份失败 ({name}): {e}",
        "en": "Failed to back up extra config ({name}): {e}",
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
    # [V3.2.0] P1/P2: WordPress 未安装时跳过插件操作
    "warn_plugin_wp_not_installed": {
        "zh": "WordPress 尚未完成安装, 跳过插件操作。请先访问 https://{domain}/ 完成安装向导, 或使用 --wp-auto-install 自动安装。",
        "en": "WordPress is not yet installed; skipping plugin operations. Visit https://{domain}/ to complete the setup wizard, or use --wp-auto-install.",
    },
    "err_certbot_lock": {
        "zh": "无法获取 Certbot 并发锁: {e}",
        "en": "Failed to acquire Certbot concurrency lock: {e}",
    },
    # [V3.0.16] P2: wp-cron systemd timer
    "info_wp_cron_timer_created": {
        "zh": "WordPress Cron 定时器已创建 (每 15 分钟)。",
        "en": "WordPress Cron timer created (every 15 minutes).",
    },
    "info_wp_cron_timer_no_wpcli": {
        "zh": "提示：WP-CLI 不可用, 使用 php wp-cron.php 作为 cron fallback。",
        "en": "Tip: WP-CLI unavailable; using php wp-cron.php as cron fallback.",
    },
    "dry_run_wp_cron": {
        "zh": "[DRY-RUN] 跳过 WordPress Cron 定时器配置。",
        "en": "[DRY-RUN] Skipping WordPress Cron timer configuration.",
    },
    # [V3.0.16] P3: PHP-FPM 动态调参
    "info_fpm_tuning": {
        "zh": "PHP-FPM 动态调参: 总内存 {total}MB → pm.max_children={children}, pm={mode}",
        "en": "PHP-FPM tuning: total RAM {total}MB → pm.max_children={children}, pm={mode}",
    },
    "warn_fpm_tuning_fail": {
        "zh": "PHP-FPM 调参失败 ({path}): {e}",
        "en": "PHP-FPM tuning failed ({path}): {e}",
    },
    # [V3.0.16] P4: Swap 自动创建
    "info_swap_exists": {
        "zh": "Swap 已存在 ({mb}MB), 跳过创建。",
        "en": "Swap already exists ({mb}MB); skipping creation.",
    },
    "info_swap_creating": {
        "zh": "系统内存 {ram}MB ≤ 2GB 且无 Swap, 创建 {size}MB swapfile...",
        "en": "System RAM {ram}MB ≤ 2GB with no swap; creating {size}MB swapfile...",
    },
    "info_swap_created": {
        "zh": "Swap 文件已创建并激活: {path} ({size}MB)",
        "en": "Swap file created and activated: {path} ({size}MB)",
    },
    "warn_swap_fail": {
        "zh": "Swap 创建失败 (不影响部署): {e}",
        "en": "Swap creation failed (non-blocking): {e}",
    },
    "info_swap_skip_enough_ram": {
        "zh": "系统内存 {ram}MB > 2GB, 跳过 Swap 创建。",
        "en": "System RAM {ram}MB > 2GB; skipping swap creation.",
    },
    "dry_run_swap": {
        "zh": "[DRY-RUN] 跳过 Swap 检测与创建。",
        "en": "[DRY-RUN] Skipping swap detection and creation.",
    },
    # [V3.0.16] P5: 内核网络调优
    "info_kernel_tuning": {
        "zh": "Linux 内核网络参数已调优 (BBR/TCP/fd-max)。",
        "en": "Linux kernel network parameters tuned (BBR/TCP/fd-max).",
    },
    "info_kernel_bbr_unavail": {
        "zh": "内核不支持 BBR 拥塞控制, 跳过 BBR 配置。",
        "en": "Kernel does not support BBR congestion control; skipping BBR config.",
    },
    "warn_kernel_tuning_fail": {
        "zh": "内核调优写入失败 (不影响部署): {e}",
        "en": "Kernel tuning write failed (non-blocking): {e}",
    },
    "dry_run_kernel_tuning": {
        "zh": "[DRY-RUN] 跳过内核网络参数调优。",
        "en": "[DRY-RUN] Skipping kernel network parameter tuning.",
    },
    # [V3.0.16] P6: MariaDB 基础调优
    "info_mariadb_tuning": {
        "zh": "MariaDB 调优配置已写入: {path} (buffer_pool={pool}MB, max_conn={conn})",
        "en": "MariaDB tuning config written: {path} (buffer_pool={pool}MB, max_conn={conn})",
    },
    "warn_mariadb_tuning_fail": {
        "zh": "MariaDB 调优配置写入失败 (不影响部署): {e}",
        "en": "MariaDB tuning config write failed (non-blocking): {e}",
    },
    "info_mariadb_tuning_skip_ext": {
        "zh": "外置数据库, 跳过本地 MariaDB 调优。",
        "en": "External database; skipping local MariaDB tuning.",
    },
    "dry_run_mariadb_tuning": {
        "zh": "[DRY-RUN] 跳过 MariaDB 调优。",
        "en": "[DRY-RUN] Skipping MariaDB tuning.",
    },
    # [V3.0.16] P11: MySQL 周度优化
    "info_db_optimize_timer": {
        "zh": "MariaDB 周度优化定时器已创建 (每周日 03:00)。",
        "en": "MariaDB weekly optimize timer created (Sunday 03:00).",
    },
    "info_db_optimize_skip_ext": {
        "zh": "外置数据库, 跳过本地 mysqlcheck 定时器。",
        "en": "External database; skipping local mysqlcheck timer.",
    },
    "dry_run_db_optimize": {
        "zh": "[DRY-RUN] 跳过 MySQL 优化定时器配置。",
        "en": "[DRY-RUN] Skipping MySQL optimize timer configuration.",
    },
    # [V3.0.16] P12: Cloudflare Real IP
    "info_cloudflare_real_ip": {
        "zh": "Cloudflare Real IP 已配置: {path}",
        "en": "Cloudflare Real IP configured: {path}",
    },
    "info_cloudflare_ip_fetched": {
        "zh": "已获取 {n4} 个 IPv4 + {n6} 个 IPv6 Cloudflare 网段。",
        "en": "Fetched {n4} IPv4 + {n6} IPv6 Cloudflare ranges.",
    },
    "warn_cloudflare_fetch_fail": {
        "zh": "Cloudflare IP 列表获取失败, 使用内置默认值: {e}",
        "en": "Failed to fetch Cloudflare IP list; using built-in defaults: {e}",
    },
    "warn_cloudflare_write_fail": {
        "zh": "Cloudflare Real IP 配置写入失败: {e}",
        "en": "Failed to write Cloudflare Real IP config: {e}",
    },
    "dry_run_cloudflare": {
        "zh": "[DRY-RUN] 跳过 Cloudflare Real IP 配置。",
        "en": "[DRY-RUN] Skipping Cloudflare Real IP configuration.",
    },
    "help_cloudflare": {
        "zh": "启用 Cloudflare Real IP 还原 (自动获取 CF IP 段, 全局生效)",
        "en": "Enable Cloudflare Real IP restoration (auto-fetch CF ranges, global)",
    },
    # [V3.0.16] P7: WP-CLI 自动安装
    "info_wp_auto_install": {
        "zh": "WordPress 安装已自动完成 (管理员: {user})。",
        "en": "WordPress auto-install complete (admin: {user}).",
    },
    "info_wp_auto_install_skip": {
        "zh": "WordPress 已安装, 跳过自动安装。",
        "en": "WordPress already installed; skipping auto-install.",
    },
    "warn_wp_auto_install_fail": {
        "zh": "WordPress 自动安装失败, 请手动访问 {domain}/wp-admin/install.php 完成。",
        "en": "WordPress auto-install failed; visit {domain}/wp-admin/install.php to complete manually.",
    },
    "help_wp_auto_install": {
        "zh": "自动完成 WordPress 安装 (需 WP-CLI; 生成随机管理员密码写入凭据文件)",
        "en": "Auto-complete WordPress installation (requires WP-CLI; random admin password saved to credentials file)",
    },
    # [V3.0.16] P8: nginx -t 门控
    "warn_nginx_reload_test_fail": {
        "zh": "nginx -t 失败, 跳过 reload 以避免宕机。请手动检查配置。",
        "en": "nginx -t failed; skipping reload to prevent downtime. Check config manually.",
    },
    # [V3.0.16] P9: Nginx open_file_cache
    "info_open_file_cache": {
        "zh": "Nginx open_file_cache 已启用 (静态文件元数据缓存)。",
        "en": "Nginx open_file_cache enabled (static file metadata caching).",
    },
    "help_optimize": {
        "zh": "启用 Nginx 高级性能优化 (open_file_cache 等)",
        "en": "Enable Nginx advanced performance optimizations (open_file_cache, etc.)",
    },
    # [V3.0.16] P10: self-update
    "subcmd_self_update": {
        "zh": "从远程下载最新版脚本并原子替换",
        "en": "Download latest script version and atomically replace",
    },
    "help_update_url": {
        "zh": "自定义更新源 URL (默认: 环境变量 WP_UPDATE_URL 或内置地址)",
        "en": "Custom update source URL (default: WP_UPDATE_URL env or built-in)",
    },
    "info_self_update_checking": {
        "zh": "正在检查更新...",
        "en": "Checking for updates...",
    },
    "info_self_update_downloading": {
        "zh": "正在下载最新版本...",
        "en": "Downloading latest version...",
    },
    "info_self_update_same": {
        "zh": "当前已是最新版本 (V{ver})。",
        "en": "Already up to date (V{ver}).",
    },
    "info_self_update_done": {
        "zh": "更新成功: V{old} → V{new}",
        "en": "Updated successfully: V{old} → V{new}",
    },
    "err_self_update_download": {
        "zh": "下载更新失败: {e}",
        "en": "Failed to download update: {e}",
    },
    "err_self_update_hash": {
        "zh": "SHA256 校验失败, 更新已中止。",
        "en": "SHA256 verification failed; update aborted.",
    },
    "err_self_update_no_version": {
        "zh": "下载的文件中未找到版本号, 更新已中止。",
        "en": "No version found in downloaded file; update aborted.",
    },
    "warn_self_update_no_hash": {
        "zh": "未找到校验文件, 跳过 SHA256 校验。",
        "en": "Hash file not found; skipping SHA256 verification.",
    },
    # [V3.1.1] Issue 8: mandatory SHA256 verification
    "err_self_update_hash_unavailable": {
        "zh": "无法获取 SHA256 校验文件, 为安全起见更新已中止: {e}",
        "en": "Cannot fetch SHA256 hash file; update aborted for safety: {e}",
    },
    # [V3.1.1] Issue 1: certbot deploy hook
    "info_certbot_deploy_hook": {
        "zh": "Certbot 持久化 deploy hook 已安装: {path}",
        "en": "Certbot persistent deploy hook installed: {path}",
    },
    # [V3.1.0 S2] 版本降级保护
    "warn_self_update_downgrade": {
        "zh": "远端版本 {remote} 低于当前版本 {current}，已拒绝覆盖。"
              "如需强制降级请手动替换脚本文件。",
        "en": "Remote version {remote} is older than current {current}; "
              "refusing to downgrade. Replace the script file manually if needed.",
    },
    "warn_aw_bak_cleanup_fail": {
        "zh": "无法清理 .aw_bak 文件 {path}: {e}（原子写入已成功，请手动检查）",
        "en": "Could not clean up .aw_bak {path}: {e} (atomic write succeeded; please inspect manually)",
    },
    # [V3.2.9] M-3: _detect_existing_sites 幽灵站点日志国际化
    "warn_ghost_site": {
        "zh": "跳过幽灵站点 (webroot 不存在): {domain}  "
              "\uff08Nginx 配置残留，建议手动检查 /etc/nginx/conf.d/\uff09",
        "en": "Skipping ghost site (no webroot): {domain}  "
              "(Nginx config remains; check /etc/nginx/conf.d/ manually)",
    },
    # ── show_status (print) ─────────────────────────────────────────────────
    # [V3.2.8] L-1: Brotli 与 Cloudflare Real IP 状态国际化
    "status_brotli_on": {
        "zh": "Brotli: 已启用 ({path})",  # [V3.2.9] M-1
        "en": "Brotli: enabled ({path})",
    },
    "status_brotli_off": {
        "zh": "Brotli: 未配置",
        "en": "Brotli: not configured",
    },
    "status_cf_realip_on": {
        "zh": "Cloudflare Real IP: 已启用 ({path})",
        "en": "Cloudflare Real IP: enabled ({path})",
    },
    "status_cf_realip_off": {
        "zh": "Cloudflare Real IP: 未配置",
        "en": "Cloudflare Real IP: not configured",
    },
    "status_header": {
        "zh": "\n===== [{domain}] 站点状态 =====\n",
        "en": "\n===== [{domain}] Site Status =====\n",
    },
    "status_ssl": {
        "zh": "SSL 证书: {info}",
        "en": "SSL Certificate: {info}",
    },
    "status_ssl_expiry_warn": {
        "zh": "   证书将在 30 天内到期！",
        "en": "   Certificate expires within 30 days!",
    },
    "status_ssl_unreadable": {
        "zh": "SSL 证书: 无法读取",
        "en": "SSL Certificate: Unable to read",
    },
    "status_ssl_missing": {
        "zh": "SSL 证书: 未找到",
        "en": "SSL Certificate: Not found",
    },
    "status_external_db": {
        "zh": "数据库: 外置 ({host})，跳过本地服务检查",
        "en": "Database: External ({host}), skipping local service check",
    },
    "status_svc_unknown": {
        "zh": "{label} ({name}): 未知",
        "en": "{label} ({name}): unknown",
    },
    "status_timer": {
        "zh": "{icon} 续期定时器 ({name}): {status}",
        "en": "{icon} Renewal timer ({name}): {status}",
    },
    "status_timer_unknown": {
        "zh": "续期定时器 ({name}): 未知",
        "en": "Renewal timer ({name}): unknown",
    },
    # [V3.2.10] M-2: 通用定时器状态条目（wp-cron / db-optimize）
    "status_timer_generic": {
        "zh": "{icon} {label} ({name}): {status}",
        "en": "{icon} {label} ({name}): {status}",
    },
    "status_timer_generic_unknown": {
        "zh": "{label} ({name}): 未知",
        "en": "{label} ({name}): unknown",
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
    "ok_systemd": {
        "zh": "Systemd SSL 定时续期已启用: {timer}",
        "en": "Systemd SSL auto-renewal timer enabled: {timer}",
    },
    "err_systemd_write": {
        "zh": "Systemd 定时续期配置文件写入失败，SSL 证书将不会自动续期。",
        "en": "Failed to write Systemd renewal unit files; SSL certificate will not auto-renew.",
    },
    "phase_f2b": {
        "zh": "开始配置 Fail2Ban WordPress 防护...",
        "en": "Configuring Fail2Ban WordPress protection...",
    },
    # ── logging.error ───────────────────────────────────────────────────────
    "err_no_pkg_mgr": {
        "zh": "无法识别包管理器，系统不支持自动化装配。",
        "en": "Cannot detect package manager; automated setup is not supported on this OS.",
    },
    "err_disk_low": {
        "zh": "磁盘空间不足 ({label})：{path} 所在分区仅剩 {free}MB，需要 {need}MB。",
        "en": "Insufficient disk space ({label}): {path} has only {free}MB free, need {need}MB.",
    },
    "err_lock_global": {
        "zh": "全局进程冲突：另一个部署任务正在运行，请等待其完成。",
        "en": "Global lock conflict: another deploy task is running, please wait.",
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
        "zh": "MariaDB 直连失败。请查阅 /root/.wp_credentials_*.txt。",
        "en": "Direct MariaDB connection failed. Check /root/.wp_credentials_*.txt.",
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
        "zh": "  # 必须在 find 之后单独执行，恢复安全权限：",
        "en": "  # Must run after find to restore secure permissions:",
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
        "zh": "所有下载方式均失败（tar.gz 源 + WP-CLI）。",
        "en": "All download methods failed (tar.gz sources + WP-CLI).",
    },
    "err_wp_extract": {
        "zh": "WordPress 解压失败 (错误分类: {code})。{stderr_part}\n   建议: 检查磁盘空间与 tar 版本。",
        "en": "WordPress extraction failed (category: {code}).{stderr_part}\n   Suggestion: check disk space and tar version.",
    },
    "err_wp_integrity": {
        "zh": "WordPress 解压后完整性校验失败，核心文件缺失。",
        "en": "WordPress integrity check failed after extraction; core files missing.",
    },
    "err_download_exception": {
        "zh": "下载过程异常: {e}",
        "en": "Download exception: {e}",
    },
    "err_skip_deps_missing": {
        "zh": "--skip-deps 模式下缺少关键依赖: {deps}\n   请先手动安装后重试，或去掉 --skip-deps 让脚本自动安装。",
        "en": "--skip-deps mode: missing critical dependencies: {deps}\n   Install them manually first, or remove --skip-deps.",
    },
    "err_nginx_start": {
        "zh": "Nginx 启动失败，后续阶段均依赖 Nginx，部署终止。",
        "en": "Nginx failed to start; all subsequent stages require Nginx. Deployment aborted.",
    },
    "err_db_name_chars": {
        "zh": "数据库名称包含非法字符: {name}",
        "en": "Database name contains illegal characters: {name}",
    },
    "err_db_user_chars": {
        "zh": "数据库用户名包含非法字符: {user}",
        "en": "Database username contains illegal characters: {user}",
    },
    "err_db_pass_chars": {
        "zh": "数据库密码包含非法字符。",
        "en": "Database password contains illegal characters.",
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
        "zh": "HTTP challenge 预检：无法写入测试文件: {e}",
        "en": "HTTP challenge preflight: cannot write test file: {e}",
    },
    "err_http_challenge_conn_fail": {
        "zh": "HTTP challenge 预检失败：无法通过 HTTP 访问验证路径。\n   可能原因：Nginx 未正确启动、防火墙拦截 80 端口、域名未解析到本机。\n   提示：若 Nginx listen 未绑定 0.0.0.0，127.0.0.1 预检可能误通，请确认 listen 指令。",
        "en": "HTTP challenge preflight failed: cannot reach the ACME challenge path via HTTP.\n   Possible causes: Nginx not running, port 80 blocked by firewall, domain not pointing to this server.\n   Hint: if Nginx listens on a specific IP (not 0.0.0.0), loopback preflight may succeed falsely — verify listen directive.",
    },
    "err_cert_fatal": {
        "zh": "{ca} 签发遇到非 CA 侧致命错误，换 CA 也无法解决，终止尝试。\n   错误摘要: {err}",
        "en": "{ca} encountered a non-CA fatal error; switching CA will not help. Aborted.\n   Error summary: {err}",
    },
    "err_cert_permission": {
        "zh": "{ca} 签发遇到权限错误，终止尝试。\n   错误摘要: {err}",
        "en": "{ca} encountered a permission error. Aborted.\n   Error summary: {err}",
    },
    "err_cert_all_failed": {
        "zh": "证书申请全部失败。",
        "en": "All certificate issuance attempts failed.",
    },
    "err_cert_renew": {
        "zh": "{domain} 证书续期失败。",
        "en": "Certificate renewal failed for {domain}.",
    },
    "err_backup_dir": {
        "zh": "创建备份目录失败: {e}",
        "en": "Failed to create backup directory: {e}",
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
        "zh": "--db-root-pass 包含不安全字符（不允许单引号、反引号、反斜杠等）。",
        "en": "--db-root-pass contains unsafe characters (single quotes, backticks, backslashes not allowed).",
    },
    "warn_db_root_unsafe_skip": {
        "zh": "--db-root-pass 包含不安全字符，跳过此密码（不允许单引号、反引号、反斜杠等）。",
        "en": "--db-root-pass contains unsafe characters; password skipped (single quotes, backticks, backslashes not allowed).",
    },
    "err_external_db_no_pass": {
        "zh": "使用外置数据库 ({host}) 时，必须通过 --db-root-pass 或 WP_DB_ROOT_PASS 提供数据库密码。",
        "en": "When using an external database ({host}), you must provide the password via --db-root-pass or WP_DB_ROOT_PASS.",
    },
    "err_external_db_connect": {
        "zh": "无法连接外置数据库 ({host})。\n   请检查主机地址、端口与防火墙规则，并确认 root 密码正确。",
        "en": "Cannot connect to external database ({host}).\n   Check the host/port, firewall rules, and verify the root password.",
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
        "zh": "本次备份无任何文件通过完整性校验，跳过旧备份清理以防数据全损。",
        "en": "No backup files passed integrity check; skipping cleanup to prevent total data loss.",
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
        "zh": "{ca} 签发失败 (可重试)，{next_msg}",
        "en": "{ca} issuance failed (retryable); {next_msg}",
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
    # ── logging.info — milestones ─────────────────────────────────────────
    "ok_wpcli_wp": {
        "zh": "WP-CLI 下载 WordPress 成功。",
        "en": "WordPress downloaded via WP-CLI.",
    },
    "ok_wpcli_checksums": {
        "zh": "WP-CLI verify-checksums 校验通过。",
        "en": "WP-CLI verify-checksums passed.",
    },
    "ok_nginx_helper_activated": {
        "zh": "nginx-helper 插件已激活（FastCGI 缓存刷新就绪）。",
        "en": "nginx-helper plugin activated (FastCGI cache purge ready).",
    },
    "ok_nginx_helper_installed": {
        "zh": "nginx-helper 插件安装并激活成功（FastCGI 缓存刷新就绪）。",
        "en": "nginx-helper installed and activated (FastCGI cache purge ready).",
    },
    "ok_sha256": {
        "zh": "[{name}] SHA256 校验通过。",
        "en": "[{name}] SHA256 checksum verified.",
    },
    "ok_http_challenge": {
        "zh": "HTTP challenge 预检通过：Nginx 正确响应 ACME 验证路径。",
        "en": "HTTP challenge preflight passed: Nginx correctly serves ACME challenge path.",
    },
    "ok_cert_issued": {
        "zh": "证书由 {ca} 签发成功。",
        "en": "Certificate issued by {ca}.",
    },
    "ok_wpcli_installed": {
        "zh": "WP-CLI 确认：WordPress 已安装并可连接数据库。",
        "en": "WP-CLI confirmed: WordPress is installed and database is reachable.",
    },
    "ok_cert_renew": {
        "zh": "续期检查完毕。",
        "en": "Renewal check complete.",
    },
    "ok_f2b_active": {
        "zh": "Fail2Ban WordPress 防护已激活。",
        "en": "Fail2Ban WordPress protection activated.",
    },
    "ok_db_backup": {
        "zh": "数据库已备份: {path}",
        "en": "Database backed up: {path}",
    },
    "ok_webroot_backup": {
        "zh": "站点文件已备份: {path}",
        "en": "Webroot backed up: {path}",
    },
    "ok_nginx_backup": {
        "zh": "Nginx 配置已备份: {path}",
        "en": "Nginx config backed up: {path}",
    },
    "ok_db_restore": {
        "zh": "数据库恢复成功。",
        "en": "Database restored successfully.",
    },
    "ok_uninstall": {
        "zh": "卸载结束。业务数据与证书已保留。",
        "en": "Uninstall complete. Site data and certificates have been preserved.",
    },
    "ok_wpcli_install_src": {
        "zh": "WP-CLI 安装成功 (来源: {src}): {ver}",
        "en": "WP-CLI installed (source: {src}): {ver}",
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
        "zh": "启用 Redis 对象缓存 (可与 --cache fastcgi 叠加)",
        "en": "Enable Redis object cache (can combine with --cache fastcgi)",
    },
    "help_skip_deps": {
        "zh": "跳过系统包安装 (假定依赖已就绪，仅配置应用层)",
        "en": "Skip system package installation (assume deps are present, configure app layer only)",
    },
    "help_allow_xmlrpc": {
        "zh": "放开 xmlrpc.php 访问 (支持 Jetpack/移动 App)。默认 deny all；启用后改为速率限制 (1r/s burst=10) + PHP-FPM 透传",
        "en": "Allow xmlrpc.php access (Jetpack/mobile app support). Default: deny all; when set: rate-limited (1r/s burst=10) + PHP-FPM pass-through",
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
        "zh": "放开 xmlrpc.php 访问 (需与 deploy 时一致，或用于切换策略)",
        "en": "Allow xmlrpc.php access (match deploy setting, or use to change policy)",
    },
    "help_lang": {
        "zh": "界面语言 (zh|en)。首次指定后自动持久化，后续无需重复传入",
        "en": "Interface language (zh|en). Persisted on first use; no need to repeat",
    },
    # ── logging.error (remaining) ────────────────────────────────────────────
    "err_wp_src_fatal": {
        "zh": "[{name}] 致命错误，跳过后续源。",
        "en": "[{name}] Fatal error; skipping remaining sources.",
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
        "zh": "[{name}] 散列不匹配，切换备用节点...",
        "en": "[{name}] Hash mismatch; switching to fallback source...",
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
    # [V3.0.16] F6: warn_nginx_test_fail_restore 已被 P8 的
    # warn_nginx_reload_test_fail 替代, 保留键以兼容旧日志搜索
    "warn_nginx_test_fail_restore": {
        "zh": "Nginx 配置测试失败，跳过 reload。请手动检查 nginx -t 输出。",
        "en": "Nginx config test failed; skipping reload. Check 'nginx -t' output manually.",
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
        "zh": "  已清理旧备份: {name}",
        "en": "  Cleaned up old backup: {name}",
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
        "zh": "高可用建站引擎",
        "en": "High-availability WordPress deployment engine",
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
        "zh": "从备份恢复站点 (数据库+文件+Nginx)",
        "en": "Restore site from backup (database + files + Nginx)",
    },
    "subcmd_update": {
        "zh": "热更新配置模板 (Nginx/PHP/Fail2Ban/logrotate)",
        "en": "Hot-update config templates (Nginx/PHP/Fail2Ban/logrotate)",
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
        "zh": "提示：FastCGI Cache 已启用，但 WP-CLI 不可用，无法自动安装 nginx-helper 插件。建议手动安装该插件以实现发布文章时自动清除缓存。",
        "en": "Tip: FastCGI Cache is enabled but WP-CLI is unavailable. Install the nginx-helper plugin manually to enable cache purging on post publish.",
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
        "zh": "WP-CLI verify-checksums 未通过，部分核心文件可能被修改。基础完整性已通过，继续部署。",
        "en": "WP-CLI verify-checksums failed; some core files may be modified. Basic integrity passed; continuing deployment.",
    },
    "warn_wp_hash_bad": {
        "zh": "[{name}] hash 文件内容异常，切换备用节点...",
        "en": "[{name}] Hash file content invalid; switching to fallback source...",
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
        "zh": "站点健康检查通过 (HTTP {code}，第 {attempt} 次)。",
        "en": "Site health check passed (HTTP {code}, attempt {attempt}).",
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
        "zh": "站点健康检查未通过（{retries} 次重试后）。\n   站点可能需要更长时间启动，或需要完成 WordPress 初始化向导。\n   请手动访问 https://{domain}/ 确认。",
        "en": "Site health check failed after {retries} retries.\n   The site may need more time to start, or may require the WordPress setup wizard.\n   Please visit https://{domain}/ manually.",
    },
    "info_wp_not_installed": {
        "zh": "WP-CLI 报告 WordPress 尚未完成安装。请访问网站完成 WordPress 初始化向导，或重新运行脚本时加上 --wp-auto-install 参数。",
        "en": "WP-CLI reports WordPress is not yet installed. Visit the site to complete the WordPress setup wizard, or re-run with --wp-auto-install to automate this step.",
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
        "zh": "DNS 预检失败：{domain} 无法解析。\n   请确认域名 A/AAAA 记录已正确指向本服务器 IP。",
        "en": "DNS preflight failed: {domain} cannot be resolved.\n   Verify that A/AAAA records point to this server's IP.",
    },
    "info_cert_skip_www": {
        "zh": "www.{domain} DNS 未解析，证书申请仅包含主域名。",
        "en": "www.{domain} DNS not resolved; certificate request will cover main domain only.",
    },
    "info_renew_domains_from_cert": {
        "zh": "从已有证书读取域名列表: {domains}",
        "en": "Domain list read from existing certificate: {domains}",
    },
    "info_renew_cert_not_found_www": {
        "zh": "未找到已有证书，续期将包含 www 子域。",
        "en": "No existing certificate found; renewal will include www subdomain.",
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

    # ── 证书失败诊断 ───────────────────────────────────────────────────────
    "diag_reading_log": {
        "zh": "正在分析 certbot 日志以诊断失败原因...",
        "en": "Analyzing certbot log to diagnose failure...",
    },
    "diag_log_not_found": {
        "zh": "未找到 certbot 日志文件 ({path})，无法做深度诊断。",
        "en": "Certbot log file not found ({path}); cannot perform deep diagnosis.",
    },
    "diag_summary": {
        "zh": "诊断摘要:\n{detail}",
        "en": "Diagnosis summary:\n{detail}",
    },
    "diag_challenge_fail": {
        "zh": "   ACME Challenge 验证失败 — CA 无法访问本服务器 80 端口。\n"
              "      排查: curl -I http://{domain}/.well-known/acme-challenge/test",
        "en": "   ACME Challenge failed — CA cannot reach port 80.\n"
              "      Debug: curl -I http://{domain}/.well-known/acme-challenge/test",
    },
    "diag_dns_issue": {
        "zh": "   DNS 解析问题 — CA 的 DNS 查询结果与本机不一致。\n"
              "      排查: dig +short {domain} @8.8.8.8",
        "en": "   DNS resolution issue — CA got different results.\n"
              "      Debug: dig +short {domain} @8.8.8.8",
    },
    "diag_rate_limit": {
        "zh": "   触发 CA 速率限制。建议等待 1 小时后重试或用 --staging。",
        "en": "   CA rate limit hit. Wait 1 hour or use --staging.",
    },
    "diag_timeout": {
        "zh": "   CA 连接超时 — 网络不通或延迟过高。",
        "en": "   CA connection timeout — network down or high latency.",
    },
    "diag_port_blocked": {
        "zh": "   端口 80 不可达 — 防火墙或安全组未放行。",
        "en": "   Port 80 unreachable — firewall or security group blocking.",
    },
    "diag_hint_log": {
        "zh": "   完整日志: {path}",
        "en": "   Full log: {path}",
    },
    # ── DNS 自动修复 ───────────────────────────────────────────────────────
    "info_dns_fix_attempt": {
        "zh": "检测到 DNS/验证问题, 尝试切换公共 DNS 后重试...",
        "en": "DNS/validation issue detected; switching to public DNS and retrying...",
    },
    "info_dns_fix_applied": {
        "zh": "   已临时添加公共 DNS: {servers}",
        "en": "   Temporarily added public DNS: {servers}",
    },
    "info_dns_fix_success": {
        "zh": "DNS 修复后证书签发成功。",
        "en": "Certificate issued after DNS fix.",
    },
    "info_dns_fix_rollback": {
        "zh": "   DNS 修复未解决问题, 已恢复原始配置。",
        "en": "   DNS fix did not help; reverted to original configuration.",
    },
    # ── 国内云检测 ─────────────────────────────────────────────────────────
    "prompt_china_cloud_detected": {
        "zh": "\n检测到国内云服务器 ({cloud})，建议使用中文界面。\n"
              "  [1] 使用中文 / Use Chinese (Enter)\n"
              "  [2] Use English\n",
        "en": "\nDetected China-based cloud server ({cloud}).\n"
              "  [1] 使用中文 / Use Chinese (Enter)\n"
              "  [2] Use English\n",
    },
    # ── WordPress 版本化下载 ───────────────────────────────────────────────
    "info_wp_version_fetching": {
        "zh": "正在从 WordPress API 获取最新版本号...",
        "en": "Fetching latest WordPress version from API...",
    },
    "info_wp_version_fetched": {
        "zh": "WordPress 最新版本: {ver}",
        "en": "WordPress latest version: {ver}",
    },
    "warn_wp_version_fetch_fail": {
        "zh": "无法获取版本号，回退至 latest 别名（不做哈希校验）。",
        "en": "Version fetch failed; falling back to latest (no checksum).",
    },
    "ok_sha1": {
        "zh": "[{name}] SHA1 校验通过。",
        "en": "[{name}] SHA1 checksum verified.",
    },
    "info_wp_hash_retry": {
        "zh": "   hash 不匹配, 重新下载校验文件...",
        "en": "   Hash mismatch; retrying checksum download...",
    },
    # ── PHP Redis PECL ─────────────────────────────────────────────────────
    "info_php_redis_pecl_start": {
        "zh": "dnf/yum 源中无预编译 PHP Redis 包，通过 PECL 源码编译安装...",
        "en": "No pre-built PHP Redis in dnf/yum; building via PECL...",
    },
    "ok_php_redis_pecl": {
        "zh": "PHP Redis 扩展已通过 PECL 编译安装。",
        "en": "PHP Redis extension installed via PECL.",
    },
    "warn_php_redis_pecl_fail": {
        "zh": "PECL 编译 PHP Redis 失败: {e}\n"
              "    手动安装: dnf install php-devel php-pear gcc make && pecl install redis",
        "en": "PECL build of PHP Redis failed: {e}\n"
              "    Manual: dnf install php-devel php-pear gcc make && pecl install redis",
    },
    "info_restore_config_hint": {
        "zh": "提示：恢复操作已从备份还原 Nginx 配置。"
              "若需将配置模板更新至最新版本（如脚本升级后），请执行:\n"
              "   python3 {script} update --domain {domain}"
              " [--cache fastcgi] [--redis] [--allow-xmlrpc]\n"
              "   此命令同时会重建 wp-cron / db-optimize / SSL 续期定时器。",
        "en": "Tip: Nginx config has been restored from backup. "
              "To update config templates to the latest version "
              "(e.g. after script upgrade), run:\n"
              "   python3 {script} update --domain {domain}"
              " [--cache fastcgi] [--redis] [--allow-xmlrpc]\n"
              "   This also rebuilds wp-cron / db-optimize / SSL renewal timers.",
    },
    # ── [V3.2.0] 诊断与自动修复消息 ────────────────────────────────────────
    "diag_header": {
        "zh": "[{stage}] 失败诊断开始...",
        "en": "[{stage}] Failure diagnosis started...",
    },
    "diag_check": {
        "zh": "  检查: {item}",
        "en": "  Checking: {item}",
    },
    "diag_found": {
        "zh": "  问题发现: {desc}",
        "en": "  Issue found: {desc}",
    },
    "diag_repair_try": {
        "zh": "  尝试修复: {desc}",
        "en": "  Attempting repair: {desc}",
    },
    "diag_repair_ok": {
        "zh": "  修复成功: {desc}",
        "en": "  Repair succeeded: {desc}",
    },
    "diag_repair_fail": {
        "zh": "  修复失败: {desc}",
        "en": "  Repair failed: {desc}",
    },
    "diag_rollback": {
        "zh": "  ↩  修复失败，正在还原环境...",
        "en": "  ↩  Repair failed; rolling back environment...",
    },
    "diag_rollback_ok": {
        "zh": "  环境已还原。",
        "en": "  Environment restored.",
    },
    "diag_rollback_fail": {
        "zh": "  环境还原失败: {e}（请手动检查）",
        "en": "  Environment rollback failed: {e} (manual inspection required)",
    },
    "diag_no_fix": {
        "zh": "  未发现可自动修复的问题，请根据以上诊断信息手动处理。",
        "en": "  No auto-fixable issues found. Please resolve based on diagnostics above.",
    },
    "diag_pkg_cache_dirty": {
        "zh": "包管理器缓存损坏或过期",
        "en": "Package manager cache is dirty or stale",
    },
    "diag_pkg_clean_retry": {
        "zh": "清理包缓存并重试安装",
        "en": "Cleaning package cache and retrying installation",
    },
    "diag_pkg_epel_missing": {
        "zh": "EPEL 源未启用（RHEL/CentOS 缺少 EPEL 可导致多个包不可用）",
        "en": "EPEL repository not enabled (missing EPEL on RHEL/CentOS causes many packages to be unavailable)",
    },
    "diag_pkg_epel_install": {
        "zh": "安装 EPEL 源并重试",
        "en": "Installing EPEL repository and retrying",
    },
    "diag_pkg_remi_try": {
        "zh": "尝试从 Remi 源安装缺失的 PHP 包",
        "en": "Attempting to install missing PHP packages from Remi repository",
    },
    "diag_pkg_broken_deps": {
        "zh": "检测到依赖冲突，尝试修复",
        "en": "Broken dependencies detected; attempting repair",
    },
    "diag_nginx_port80_occupied": {
        "zh": "80 端口已被占用（可能是 Apache/另一个 Nginx 实例）",
        "en": "Port 80 is in use (possibly Apache or another Nginx instance)",
    },
    "diag_nginx_config_error": {
        "zh": "Nginx 配置文件存在语法错误",
        "en": "Nginx configuration file has syntax errors",
    },
    "diag_nginx_kill_port80": {
        "zh": "停止占用 80 端口的进程并重启 Nginx",
        "en": "Stopping processes occupying port 80 and restarting Nginx",
    },
    "diag_nginx_reset_conf": {
        "zh": "重命名冲突的 Nginx 配置文件并重启",
        "en": "Renaming conflicting Nginx config files and restarting",
    },
    "diag_phpfpm_socket_perm": {
        "zh": "PHP-FPM socket 权限不正确",
        "en": "PHP-FPM socket has incorrect permissions",
    },
    "diag_phpfpm_socket_fix": {
        "zh": "修正 PHP-FPM socket 监听权限",
        "en": "Fixing PHP-FPM socket listen permissions",
    },
    "diag_phpfpm_conf_error": {
        "zh": "PHP-FPM 配置文件存在错误",
        "en": "PHP-FPM configuration file has errors",
    },
    "diag_phpfpm_conf_reset": {
        "zh": "重置 PHP-FPM pool 配置为默认值",
        "en": "Resetting PHP-FPM pool config to defaults",
    },
    "diag_mariadb_disk_full": {
        "zh": "数据目录磁盘空间不足",
        "en": "Insufficient disk space in data directory",
    },
    "diag_mariadb_corrupt": {
        "zh": "检测到 MariaDB 数据目录损坏迹象",
        "en": "Signs of MariaDB data directory corruption detected",
    },
    "diag_mariadb_recover": {
        "zh": "尝试 innodb_force_recovery 安全模式启动并修复",
        "en": "Attempting innodb_force_recovery safe-mode start and repair",
    },
    "diag_mariadb_socket_missing": {
        "zh": "MariaDB unix socket 文件不存在，服务可能未完全启动",
        "en": "MariaDB unix socket missing; service may not have started fully",
    },
    "diag_mariadb_socket_wait": {
        "zh": "延长等待 MariaDB 就绪时间并重试",
        "en": "Extending MariaDB readiness wait and retrying",
    },
    "diag_ssl_dns_not_resolved": {
        "zh": "域名 DNS 未解析到本机 IP（certbot HTTP 验证会失败）",
        "en": "Domain DNS does not resolve to this server's IP (certbot HTTP validation will fail)",
    },
    "diag_ssl_port80_blocked": {
        "zh": "80 端口被防火墙封锁（CA 无法回调验证）",
        "en": "Port 80 is blocked by firewall (CA cannot reach the validation callback)",
    },
    "diag_ssl_firewall_open": {
        "zh": "尝试开放防火墙 80/443 端口",
        "en": "Attempting to open firewall ports 80/443",
    },
    "diag_ssl_certbot_stale_lock": {
        "zh": "certbot 遗留锁文件阻止执行",
        "en": "Stale certbot lock file blocking execution",
    },
    "diag_ssl_certbot_lock_remove": {
        "zh": "清理 certbot 遗留锁文件",
        "en": "Removing stale certbot lock file",
    },
    "diag_ssl_webroot_fix": {
        "zh": "修复 ACME webroot 目录权限",
        "en": "Fixing ACME webroot directory permissions",
    },
    "info_brotli_compile_start": {
        "zh": "Brotli: 开始源码编译 (Nginx {ver})...",
        "en": "Brotli: starting source compilation (Nginx {ver})...",
    },
    "warn_brotli_compile_fail": {
        "zh": "Brotli 编译失败: {e}",
        "en": "Brotli compile failed: {e}",
    },
    "warn_brotli_configure_fail": {
        "zh": "Brotli 编译: configure 失败",
        "en": "Brotli compile: configure failed",
    },
    "warn_brotli_make_fail": {
        "zh": "Brotli 编译: make modules 失败",
        "en": "Brotli compile: make modules failed",
    },
    "warn_brotli_no_so": {
        "zh": "Brotli 编译: 未生成 .so 文件",
        "en": "Brotli compile: no .so files produced",
    },
    "warn_brotli_nginx_test_fail": {
        "zh": "Brotli 编译: nginx -t 失败, 回滚 .so 与 load_module 配置",
        "en": "Brotli compile: nginx -t failed; rolling back .so and load_module",
    },
    "ok_brotli_compiled": {
        "zh": "Brotli 动态模块编译安装成功: {modules}",
        "en": "Brotli dynamic modules compiled: {modules}",
    },
    "info_brotli_no_prebuilt": {
        "zh": "Brotli: 当前系统源无预编译模块, 将尝试源码编译。",
        "en": "Brotli: no pre-built module; will try source compilation.",
    },
    "warn_brotli_nginx_ver": {
        "zh": "Brotli 编译: 无法获取 Nginx 版本号",
        "en": "Brotli compile: cannot determine Nginx version",
    },
    "warn_brotli_src_dl_fail": {
        "zh": "Brotli 编译: Nginx 源码下载失败",
        "en": "Brotli compile: Nginx source download failed",
    },
    "warn_brotli_clone_fail": {
        "zh": "Brotli 编译: ngx_brotli 克隆失败",
        "en": "Brotli compile: ngx_brotli clone failed",
    },
    "warn_brotli_git_unavail": {
        "zh": "Brotli 编译: 安装依赖后 git 仍不可用",
        "en": "Brotli compile: git not available after dep install",
    },
    "diag_build_deps_install": {
        "zh": "安装本地编译依赖 (gcc/make/git...)",
        "en": "Installing native build dependencies (gcc/make/git...)",
    },
    "diag_build_deps_fail": {
        "zh": "编译依赖安装失败，源码编译无法进行",
        "en": "Build dependency installation failed; source compilation cannot proceed",
    },
    "ok_build_deps_ready": {
        "zh": "编译依赖就绪。",
        "en": "Build dependencies ready.",
    },
    "diag_selinux_fix": {
        "zh": "配置 SELinux httpd 布尔值并重试",
        "en": "Configuring SELinux httpd booleans and retrying",
    },
    # ── [V3.2.0] 交互式向导消息 ────────────────────────────────────
    "interactive_banner": {
        "zh": "WP-SSL-Bootstrap 交互式向导",
        "en": "WP-SSL-Bootstrap Interactive Wizard",
    },
    "interactive_detecting": {
        "zh": "正在探测当前环境...",
        "en": "Detecting current environment...",
    },
    "interactive_env_header": {
        "zh": "环境探测结果:",
        "en": "Environment Detection:",
    },
    "interactive_env_os": {
        "zh": "操作系统",
        "en": "OS",
    },
    "interactive_env_ram": {
        "zh": "内存",
        "en": "RAM",
    },
    "interactive_env_disk": {
        "zh": "磁盘可用",
        "en": "Disk Free",
    },
    "interactive_env_pkg": {
        "zh": "包管理器",
        "en": "Pkg Manager",
    },
    "interactive_env_php": {
        "zh": "PHP 版本",
        "en": "PHP Version",
    },
    "interactive_env_db": {
        "zh": "数据库",
        "en": "Database",
    },
    "interactive_env_nginx": {
        "zh": "Nginx",
        "en": "Nginx",
    },
    "interactive_env_nginx_not_installed": {
        "zh": "未安装",
        "en": "Not installed",
    },
    "interactive_env_nginx_installed": {
        "zh": "已安装",
        "en": "Installed",
    },
    "interactive_env_cloud": {
        "zh": "云平台",
        "en": "Cloud",
    },
    "interactive_rec_header": {
        "zh": "推荐配置 (根据当前环境自动生成):",
        "en": "Recommended Config (auto-generated for your environment):",
    },
    "interactive_rec_fastcgi": {
        "zh": "FastCGI 页面缓存      — Nginx 全页缓存, 大幅提升加载速度",
        "en": "FastCGI Page Cache     — Full-page caching, dramatically faster loading",
    },
    "interactive_rec_redis": {
        "zh": "Redis 对象缓存        — 缓存数据库查询, 减少 MySQL 压力",
        "en": "Redis Object Cache     — Cache DB queries, reduce MySQL load",
    },
    "interactive_rec_optimize": {
        "zh": "Nginx 性能优化        — open_file_cache 等高级调优",
        "en": "Nginx Performance      — open_file_cache and advanced tuning",
    },
    "interactive_rec_autoinstall": {
        "zh": "WordPress 自动安装    — 跳过安装向导, 部署后直接可用",
        "en": "WP Auto-Install        — Skip setup wizard, ready immediately",
    },
    "interactive_rec_persist_pwd": {
        "zh": "保存数据库 Root 密码  — 备份/恢复等运维操作需要",
        "en": "Persist DB Root Pass   — Required for backup/restore operations",
    },
    "interactive_rec_cloudflare": {
        "zh": "Cloudflare Real IP    — 还原 CF 代理后的真实访客 IP",
        "en": "Cloudflare Real IP     — Restore real visitor IP behind CF proxy",
    },
    "interactive_input_header": {
        "zh": "请输入必要信息:",
        "en": "Required Information:",
    },
    "interactive_input_domain": {
        "zh": "域名 (如 example.com)",
        "en": "Domain (e.g. example.com)",
    },
    "interactive_input_email": {
        "zh": "邮箱 (SSL 证书注册用)",
        "en": "Email (for SSL certificate)",
    },
    "interactive_invalid_domain": {
        "zh": "域名格式不合法, 请重新输入",
        "en": "Invalid domain format, please try again",
    },
    "interactive_invalid_email": {
        "zh": "邮箱格式不合法, 请重新输入",
        "en": "Invalid email format, please try again",
    },
    "interactive_confirm_header": {
        "zh": "\n确认部署方式:",
        "en": "\nConfirm Deployment:",
    },
    "interactive_confirm_go": {
        "zh": "按推荐配置直接执行",
        "en": "Execute with recommended settings",
    },
    "interactive_confirm_custom": {
        "zh": "自定义配置项 (开关某些功能)",
        "en": "Customize settings (toggle features)",
    },
    "interactive_confirm_cancel": {
        "zh": "取消",
        "en": "Cancel",
    },
    "interactive_confirm_prompt": {
        "zh": "选择 [1/2/3, Enter=1]",
        "en": "Choose [1/2/3, Enter=1]",
    },
    "interactive_toggle_hint": {
        "zh": "输入编号切换开关状态, 输入 0 或直接回车完成:",
        "en": "Enter number to toggle, 0 or Enter to finish:",
    },
    "interactive_toggle_done": {
        "zh": "完成, 开始执行",
        "en": "Done, start execution",
    },
    "interactive_toggle_prompt": {
        "zh": "切换编号 [0=完成]",
        "en": "Toggle # [0=done]",
    },
    "interactive_final_cmd": {
        "zh": "等效命令 (下次可直接使用):",
        "en": "Equivalent command (use directly next time):",
    },
    "interactive_starting": {
        "zh": "\n开始执行, 请稍候...\n",
        "en": "\nStarting, please wait...\n",
    },
    # ── [PATCH] SSL 可选模式消息 ──────────────────────────────────────
    "help_skip_ssl": {
        "zh": "跳过 SSL 证书签发, 仅部署 HTTP 站点 (后续可通过 enable-ssl 补签)",
        "en": "Skip SSL certificate issuance; deploy HTTP-only site (use enable-ssl later)",
    },
    "info_skip_ssl_deploy": {
        "zh": "--skip-ssl 模式: 跳过 SSL 证书签发, 部署 HTTP-only 站点。",
        "en": "--skip-ssl mode: skipping SSL; deploying HTTP-only site.",
    },
    "info_skip_ssl_hint": {
        "zh": "后续启用 SSL:\n"
              "   python3 {script} enable-ssl --domain {domain} --email YOUR_EMAIL",
        "en": "To enable SSL later:\n"
              "   python3 {script} enable-ssl --domain {domain} --email YOUR_EMAIL",
    },
    "deploy_url_http": {
        "zh": "网站地址: http://{domain}  (未启用 HTTPS)",
        "en": "Site URL: http://{domain}  (HTTPS not enabled)",
    },
    "subcmd_enable_ssl": {
        "zh": "为已部署的 HTTP 站点签发 SSL 证书并切换至 HTTPS",
        "en": "Issue SSL certificate for an existing HTTP site and switch to HTTPS",
    },
    "info_enable_ssl_start": {
        "zh": "===== 为 {domain} 启用 SSL =====",
        "en": "===== Enabling SSL for {domain} =====",
    },
    "info_enable_ssl_done": {
        "zh": "SSL 已成功启用, 站点已切换至 HTTPS。",
        "en": "SSL enabled; site switched to HTTPS.",
    },
    "err_enable_ssl_cert": {
        "zh": "SSL 证书签发失败, 站点保持 HTTP 模式。",
        "en": "SSL certificate issuance failed; site remains HTTP.",
    },
    "err_enable_ssl_no_webroot": {
        "zh": "站点目录不存在 ({path}), 请先执行 deploy。",
        "en": "Webroot does not exist ({path}); run deploy first.",
    },
    "interactive_rec_skip_ssl": {
        "zh": "跳过 SSL 证书        — 仅部署 HTTP 站点 (可后续补签)",
        "en": "Skip SSL Certificate   — HTTP-only deploy (enable later)",
    },
    # ── [V3.2.52] ZeroSSL EAB 相关字符串 ─────────────────────────────────
    "help_zerossl_eab_kid": {
        "zh": "ZeroSSL EAB Key ID (从 app.zerossl.com/developer 获取; 可选备用 CA, 支持 WP_ZEROSSL_EAB_KID 环境变量)",
        "en": "ZeroSSL EAB Key ID (from app.zerossl.com/developer; optional backup CA, also via WP_ZEROSSL_EAB_KID env)",
    },
    "help_zerossl_eab_hmac": {
        "zh": "ZeroSSL EAB HMAC Key (与 --zerossl-eab-kid 配套, 两者同时提供才启用 ZeroSSL; 支持 WP_ZEROSSL_EAB_HMAC_KEY 环境变量)",
        "en": "ZeroSSL EAB HMAC Key (pair with --zerossl-eab-kid; both required to enable ZeroSSL; also via WP_ZEROSSL_EAB_HMAC_KEY env)",
    },
    # ── [V3.2.56/57/58] ZeroSSL EAB 自动获取 ──────────────────────────────
    "info_zerossl_eab_auto_fetch": {
        "zh": "Let's Encrypt 失败，正在通过 email 自动获取 ZeroSSL EAB 凭据...",
        "en": "Let's Encrypt failed. Auto-fetching ZeroSSL EAB credentials via email...",
    },
    "ok_zerossl_eab_auto_fetch": {
        "zh": "  ZeroSSL EAB 凭据自动获取成功 (kid: {kid}...)，正在签发证书...",
        "en": "  ZeroSSL EAB credentials fetched automatically (kid: {kid}...), issuing cert...",
    },
    "warn_zerossl_eab_auto_fetch_fail": {
        "zh": "  自动获取 ZeroSSL EAB 失败 ({err})，请手动输入凭据。",
        "en": "  Auto-fetch ZeroSSL EAB failed ({err}). Please enter credentials manually.",
    },
    "prompt_zerossl_le_failed_manual": {
        "zh": "\nLet's Encrypt 签发失败，且无法自动获取 ZeroSSL EAB。\n如已在 https://app.zerossl.com/developer 注册，可手动输入凭据继续：\n   (留空直接回车 = 放弃，退出证书签发)",
        "en": "\nLet's Encrypt failed and ZeroSSL EAB auto-fetch unavailable.\nIf you have credentials from https://app.zerossl.com/developer, enter them now:\n   (Press Enter to skip = abort certificate issuance)",
    },
    "interactive_zerossl_prompt_kid": {
        "zh": "EAB Key ID (留空跳过)",
        "en": "EAB Key ID (leave blank to skip)",
    },
    "interactive_zerossl_prompt_hmac": {
        "zh": "EAB HMAC Key",
        "en": "EAB HMAC Key",
    },
    "warn_zerossl_eab_mismatch": {
        "zh": "ZeroSSL EAB: --zerossl-eab-kid 与 --zerossl-eab-hmac-key 必须同时提供，其中一项为空，ZeroSSL 将被忽略。",
        "en": "ZeroSSL EAB: --zerossl-eab-kid and --zerossl-eab-hmac-key must both be provided; one is empty, ZeroSSL will be ignored.",
    },
    "info_zerossl_added": {
        "zh": "ZeroSSL 已加入 CA 容灾列表 (kid: {kid}...)",
        "en": "ZeroSSL added to CA fallback list (kid: {kid}...)",
    },
    "prompt_zerossl_retry": {
        "zh": "已获取 ZeroSSL EAB 凭据，正在使用 ZeroSSL 重新尝试签发证书...",
        "en": "ZeroSSL EAB credentials acquired; retrying certificate issuance with ZeroSSL...",
    },
    "interactive_op_enable_ssl": {
        "zh": "为 HTTP 站点启用 SSL",
        "en": "Enable SSL for HTTP site",
    },
    "phase_http_prod": {
        "zh": "===== 阶段四(HTTP): 挂载 HTTP 生产配置 =====",
        "en": "===== Stage 4 (HTTP): Apply HTTP Production Config =====",
    },
    "info_http_prod_applied": {
        "zh": "HTTP 生产配置已应用 (未启用 SSL)。",
        "en": "HTTP production config applied (SSL not enabled).",
    },
    "warn_update_no_cert": {
        "zh": "当前站点未启用 SSL, 生成 HTTP-only 配置。如需启用 SSL 请执行 enable-ssl 子命令。",
        "en": "Site has no SSL certificate; generating HTTP-only config. Use enable-ssl to add HTTPS.",
    },

    "interactive_cancelled": {
        "zh": "已取消。",
        "en": "Cancelled.",
    },
    # ── [V3.2.0] 操作菜单 & 站点选择 ──────────────────────────────
    "interactive_op_header": {
        "zh": "请选择操作:",
        "en": "Choose operation:",
    },
    "interactive_op_deploy": {
        "zh": "部署新站点",
        "en": "Deploy new site",
    },
    "interactive_op_update": {
        "zh": "更新站点配置",
        "en": "Update site configuration",
    },
    "interactive_op_backup": {
        "zh": "备份站点",
        "en": "Backup site",
    },
    "interactive_op_restore": {
        "zh": "\u21a9  恢复站点",
        "en": "\u21a9  Restore site",
    },
    "interactive_op_uninstall": {
        "zh": "卸载站点守护组件",
        "en": "Uninstall site components",
    },
    "interactive_op_self_update": {
        "zh": "更新脚本版本",
        "en": "Update script version",
    },
    "interactive_op_prompt": {
        "zh": "选择 [Enter=1]",
        "en": "Choose [Enter=1]",
    },
    "interactive_sites_header": {
        "zh": "检测到已部署站点:",
        "en": "Deployed sites detected:",
    },
    "interactive_sites_none": {
        "zh": "未检测到已部署站点, 请先执行部署。",
        "en": "No deployed sites found. Please deploy first.",
    },
    "interactive_site_auto": {
        "zh": "自动选择站点",
        "en": "Auto-selected site",
    },
    "interactive_site_select": {
        "zh": "选择站点",
        "en": "Select site",
    },
    "interactive_site_prompt": {
        "zh": "站点编号",
        "en": "Site number",
    },
    "interactive_update_header": {
        "zh": "更新 {domain} 配置:",
        "en": "Update {domain} configuration:",
    },
    "interactive_update_xmlrpc": {
        "zh": "放开 xmlrpc.php 访问   — 支持 Jetpack/移动 App",
        "en": "Allow xmlrpc.php        — Jetpack/mobile app support",
    },
    "interactive_uninstall_warn": {
        "zh": "确认卸载 {domain} 的守护组件? (站点数据与证书将保留)",
        "en": "Uninstall daemon components for {domain}? (data & certs preserved)",
    },
    "interactive_uninstall_prompt": {
        "zh": "输入 yes 确认",
        "en": "Type yes to confirm",
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
    # [V3.2.25] BUG-B: msg.format(**kwargs) 若模板占位符与 kwargs 不匹配
    # 会抛出 KeyError，导致日志/UI 调用链意外崩溃。改为安全回退：
    # 格式化失败时返回原始模板字符串，保证调用方永不因翻译函数崩溃。
    if kwargs:
        try:
            return msg.format(**kwargs)
        except (KeyError, IndexError):
            return msg  # graceful: 占位符不匹配时返回原始模板
    return msg


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
        # [V3.2.64] BUG-A: 用户输入 www.example.com 时自动剥离 www. 前缀，
        # 后续 _build_domain_args / _nginx_server_names 会自动添加 www 变体，
        # 确保 SSL 证书与 Nginx 同时覆盖 裸域名 + www 域名。
        if self.domain.startswith("www.") and self.domain.count(".") >= 2:
            _original = self.domain
            self.domain = self.domain[4:]  # strip "www."
            # [V3.2.66] BUG-D-1: 根据 _should_add_www() 输出准确的日志消息
            if _should_add_www(self.domain):
                logging.info("[V3.2.66] 域名自动归一化: %s → %s (www 将作为别名自动添加)", _original, self.domain)
            else:
                logging.info("[V3.2.66] 域名自动归一化: %s → %s (子域名, 不添加 www 变体)", _original, self.domain)
        if not re.match(r'^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$', self.domain):
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

        # [PATCH-M1] 三步无歧义编码，彻底消除域名碰撞
        # foo.bar.com→foo_dbar_dcom  foo--bar.com→foo_h_hbar_dcom
        sanitized_id = (
            self.domain
            .replace('_', '_u')   # 先转义 _ 自身，防止后续步骤引入新歧义
            .replace('.', '_d')   # 点   → _d
            .replace('-', '_h')   # 横线 → _h
        )

        # [V3.2.5] A-10: 超长域名截断后追加短哈希, 避免碰撞
        _raw_db_name = "wp_" + sanitized_id
        if len(_raw_db_name) > 64:
            _db_hash = hashlib.md5(sanitized_id.encode()).hexdigest()[:7]
            self.db_name = _raw_db_name[:56] + "_" + _db_hash
        else:
            self.db_name = _raw_db_name
        _raw_db_user = "u_" + sanitized_id
        if len(_raw_db_user) > 32:
            # [PATCH-H1] 超长时追加 5 位哈希防碰撞，与 db_name 处理方式一致
            _u_hash = hashlib.md5(sanitized_id.encode()).hexdigest()[:5]
            self.db_user = _raw_db_user[:26] + "_" + _u_hash
        else:
            self.db_user = _raw_db_user

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
        self.wp_auto_install = getattr(args, 'wp_auto_install', False)  # [V3.0.16] P7
        self.optimize = getattr(args, 'optimize', False)  # [V3.0.16] P9
        self.cloudflare = getattr(args, 'cloudflare', False)  # [V3.0.16] P12

        # [PATCH] SSL 可选: --skip-ssl 跳过证书签发, 仅部署 HTTP 站点
        self.skip_ssl = getattr(args, 'skip_ssl', False)

        # [V3.2.52] ZeroSSL EAB 凭据 (可选备用 CA)
        # 优先级: CLI 参数 > 环境变量 WP_ZEROSSL_EAB_KID / WP_ZEROSSL_EAB_HMAC_KEY
        self.zerossl_eab_kid = (
            getattr(args, 'zerossl_eab_kid', None) or
            os.environ.get('WP_ZEROSSL_EAB_KID', '')
        ).strip()
        self.zerossl_eab_hmac_key = (
            getattr(args, 'zerossl_eab_hmac_key', None) or
            os.environ.get('WP_ZEROSSL_EAB_HMAC_KEY', '')
        ).strip()
        # 两者必须同时提供才有效；单独提供一个给出警告
        if bool(self.zerossl_eab_kid) != bool(self.zerossl_eab_hmac_key):
            logging.warning(t("warn_zerossl_eab_mismatch"))
            self.zerossl_eab_kid = ""
            self.zerossl_eab_hmac_key = ""

        # [V3.2.21-AUDIT] P2-5: --no-db-ssl 禁用外置数据库 SSL 连接
        # None = 自动 (外置 DB 默认启用); False = 显式禁用
        self.db_ssl = False if getattr(args, 'no_db_ssl', False) else None


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

        # [V3.0.19] D1: certbot 二进制与证书路径在初始化时探测一次，
        # 全局缓存到 self.certbot_bin / self.cert_chain / self.cert_key。
        # 所有下游调用方（apply_cert / renew_cert / setup_nginx 等）直接使用，
        # 消除运行期重复探测，兼容 snap / certbot-auto 非标安装。
        # 首次 deploy 时证书尚未签发：_probe_cert_paths 回退到标准路径，
        # 不影响 apply_cert 等后续流程（调用方各自做 .exists() 检查）。
        self.certbot_bin = self._detect_certbot_bin()
        # [V3.1.1] P4: Cache nginx/systemctl absolute paths
        # Used by _install_certbot_deploy_hook() to generate
        # shell hooks with runtime-detected paths instead of
        # hardcoded /usr/sbin/nginx or /bin/systemctl.
        self.nginx_bin = shutil.which("nginx") or "/usr/sbin/nginx"
        self.systemctl_bin = shutil.which("systemctl") or "/bin/systemctl"
        # [V3.1.1] P7: Cache mysqlcheck absolute path
        # setup_db_optimize_timer() writes this into ExecStart of the
        # systemd service unit instead of relying on bare 'mysqlcheck',
        # which may not be on the narrow default PATH of systemd units.
        # Fallback mirrors common distro locations (/usr/bin is safest).
        self.mysqlcheck_bin = (
            shutil.which("mysqlcheck") or "/usr/bin/mysqlcheck"
        )
        self.cert_chain, self.cert_key = self._probe_cert_paths(
            self.domain, self.certbot_bin
        )

    @property
    def is_external_db(self) -> bool:
        """判断是否使用外置数据库（非本机）。

        [V3.2.3] L-5: 扩展本地别名覆盖, 包含 localhost.localdomain 等。
        [V3.2.13] P1-3: 兼容 host:port 和 [IPv6]:port 格式。
        """
        _h = self.db_host
        # Strip port suffix: [::1]:3306 → ::1, 127.0.0.1:3306 → 127.0.0.1
        if _h.startswith("["):
            _end = _h.find("]")
            if _end > 0:
                _h = _h[1:_end]
        else:
            _parts = _h.rsplit(":", 1)
            if len(_parts) == 2 and _parts[1].isdigit() and ":" not in _parts[0]:
                _h = _parts[0]
        _local_hosts = (
            'localhost', '127.0.0.1', '::1',
            'localhost.localdomain', 'localhost4', 'localhost6',
            'ip6-localhost', 'ip6-loopback',
        )
        return _h not in _local_hosts

    @staticmethod
    def _detect_certbot_bin() -> str:
        """D1: 探测 certbot 可执行文件的实际路径。

        安装方式优先级:
          1. PATH 中的 certbot          — apt/yum 标准包管理器安装
          2. /snap/bin/certbot          — Ubuntu Snap 安装
             (Snap 经常不在 root 的 PATH 中，必须显式探测)
          3. /usr/local/bin/certbot-auto — 旧版 certbot-auto 独立安装
          4. 'certbot'                   — 兜底；不在 PATH 时 run_cmd
             返回 FATAL CmdResult，错误信息清晰可查。
        """
        # 优先级 1: PATH 中的 certbot（apt/yum 标准安装，最常见）
        found = shutil.which("certbot")
        if found:
            return found
        # 优先级 2: Snap 安装路径（Ubuntu 22.04+ 推荐方式，通常不在 root PATH）
        snap_bin = Path("/snap/bin/certbot")
        if snap_bin.is_file():
            return str(snap_bin)
        # 优先级 3: certbot-auto 传统独立安装
        certbot_auto = Path("/usr/local/bin/certbot-auto")
        if certbot_auto.is_file():
            return str(certbot_auto)
        # 优先级 4: 兜底（依赖运行时 PATH，不在 PATH 则 run_cmd 会 FATAL）
        return "certbot"

    @staticmethod
    def _probe_cert_paths(domain: str, certbot_bin: str) -> tuple:
        """D1: 在 SiteConfig 初始化时探测证书文件的实际路径。

        返回 (cert_chain: Path, cert_key: Path)。

        探测策略:
          1. 标准路径 /etc/letsencrypt/live/{domain}/fullchain.pem 已存在
             → 直接返回（最快路径，覆盖续期 / 状态查询等高频场景）。
          2. `certbot_bin certificates --domain {domain}` 解析
             'Certificate Path:' 行，兼容 certbot-auto / snap 自定义目录。
          3. 以上均未命中（首次 deploy，证书尚未签发）
             → 返回标准路径（调用方负责 .exists() 检查）。

        此方法不阻塞: certbot 探测超时 5 s，任何异常静默处理。
        """
        std_dir   = Path(f"/etc/letsencrypt/live/{domain}")
        std_chain = std_dir / "fullchain.pem"
        std_key   = std_dir / "privkey.pem"

        # 优先级 1: 标准路径存在（续期 / status 等最常见场景，无额外开销）
        if std_chain.exists():
            return (std_chain, std_key)

        # 优先级 2: certbot certificates 探测（snap / certbot-auto 非标路径）
        try:
            r = subprocess.run(
                [certbot_bin, "certificates", "--domain", domain],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("Certificate Path:"):
                        cert_path = Path(line.split(":", 1)[1].strip())
                        if cert_path.exists():
                            return (cert_path, cert_path.parent / "privkey.pem")
        except Exception:
            pass

        # 优先级 3: 回退到标准路径（首次 deploy / 探测失败）
        return (std_chain, std_key)

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


# [V3.2.65] BUG-C: 判定域名是否应添加 www 变体
# 仅裸域名需要 www; 子域名 (mail / api / blog ...) 不需要。
_MULTI_PART_TLDS = frozenset({
    "co.uk", "org.uk", "me.uk", "ac.uk", "net.uk",
    "com.au", "net.au", "org.au", "edu.au",
    "co.jp", "or.jp", "ne.jp", "ac.jp",
    "com.cn", "net.cn", "org.cn",
    "com.br", "org.br", "net.br",
    "co.kr", "or.kr",
    "co.nz", "net.nz", "org.nz",
    "co.in", "net.in", "org.in",
    "com.mx", "org.mx",
    "com.tw", "org.tw", "net.tw",
    "co.za", "org.za", "net.za",
    "com.sg", "org.sg", "net.sg",
    "com.hk", "org.hk", "net.hk",
    "co.il", "org.il", "net.il",
    "com.my", "org.my", "net.my",
    "co.th", "or.th",
    "com.tr", "org.tr", "net.tr",
    "co.id",
})


def _should_add_www(domain: str) -> bool:
    """判断是否应为域名添加 www 变体。

    [V3.2.65] BUG-C: 仅裸域名 (apex domain) 需要 www 变体:
      example.com      → True  (裸域名, 1 个点)
      example.co.uk    → True  (裸域名, 已知二级 ccTLD)
      mail.example.com → False (子域名)
      api.example.com  → False (子域名)
    """
    if domain.startswith("www."):
        return False
    parts = domain.split(".")
    if len(parts) <= 2:
        return True   # example.com — 裸域名
    # 检查是否为已知多段 TLD: example.co.uk (3 段但属于裸域名)
    tld_candidate = ".".join(parts[-2:])
    if tld_candidate in _MULTI_PART_TLDS and len(parts) == 3:
        return True   # example.co.uk — 裸域名
    return False      # mail.example.com 等 — 子域名


def _nginx_server_names(domain: str) -> str:
    """N1: 返回 Nginx server_name 值。

    [V3.2.65] BUG-C-1: 子域名不再添加 www 变体。
    www.example.com  → "www.example.com example.com"
    example.com      → "example.com www.example.com"
    mail.example.com → "mail.example.com"
    """
    if domain.startswith("www."):
        bare = domain[4:]
        return f"{domain} {bare}"
    if _should_add_www(domain):
        return f"{domain} www.{domain}"
    return domain


def generate_http_only_config(domain: str, webroot: Path,
                               sock_path: str = "") -> str:
    """生成 HTTP-only 临时配置 (ACME challenge + 基础 PHP 处理)。

    [V3.2.15] P2-4: 添加 PHP location 块, 使得部署中断 (SIGTERM) 后
    站点仍能处理 WordPress PHP 请求, 而非返回空白页。
    sock_path 为空时省略 PHP location (向后兼容旧调用方)。
    """
    _php_loc = ""
    if sock_path:
        _php_loc = (
            f"    index index.php index.html index.htm;\n"  # [V3.2.18] P2
            f"    location / {{ try_files $uri $uri/ /index.php?$args; }}\n"
            f"    location ~ \\.php$ {{\n"
            f"        try_files $uri =404;\n"
            f"        fastcgi_pass unix:{sock_path};\n"
            f"        fastcgi_index index.php;\n"
            f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
            f"        include fastcgi.conf;\n"
            f"    }}\n"
        )
    else:
        # [V3.2.17] P2-3: 补齐 try_files, 防止 WordPress 伪静态链接 404
        _php_loc = f"    location / {{ try_files $uri $uri/ /index.php?$args; index index.php index.html index.htm; }}\n"
    return (
        f"server {{\n"
        f"    listen 80;\n"
        f"    listen [::]:80;\n"
        f"    server_name {_nginx_server_names(domain)};\n"
        f"    root {webroot};\n"
        f"    server_tokens off;\n"
        f"    location ^~ /.well-known/acme-challenge/ {{ allow all; default_type \"text/plain\"; }}\n"
        + _php_loc
        + f"}}\n"
    )


# ---------------------------------------------------------------------------
# Nginx 配置生成 — 模板片段函数 (V3.0.0 重构)
# ---------------------------------------------------------------------------
# 将原先 150 行的巨型 f-string 拆分为独立片段函数。
# 每个片段可独立测试、独立修改，新增 Nginx 指令只需编辑对应片段。
# generate_https_config() 负责组装，保持对外接口不变。
# ---------------------------------------------------------------------------

def _nginx_safe_name(domain: str) -> str:
    """域名 → Nginx 安全标识符 (缓存路径/rate limit zone 名称)。

    [V3.2.5] A-2: 可逆映射 '.' → '__', '-' → '_', 避免
    foo-bar.com 与 foo_bar.com 生成相同标识符导致资源碰撞。
    """
    return domain.replace('.', '__').replace('-', '_')


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
    # [V3.1.1] Issue 3: admin-ajax.php rate limiting zone
    parts.append(
        f"limit_req_zone $binary_remote_addr zone=wpadmin_{safe}:10m rate=10r/s;"
    )
    # [V3.0.3] 放开 XML-RPC 时增加独立 zone，在 PHP 被唤醒前截断暴力攻击。
    # [V3.2.11] P-16: 即使 deny-all 模式（allow_xmlrpc=False）也可考虑总是
    # 生成此 zone（仅占 10m 共享内存），从而简化参数传递。当前保留条件生成
    # 以避免不必要的 nginx.conf 指令膨胀，同时保持向后兼容。
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
        f"    server_name {_nginx_server_names(domain)};\n"
        f"    server_tokens off;\n"  # [V3.0.10] N5: 与 generate_http_only_config B6 对齐
        f"    location ^~ /.well-known/acme-challenge/ {{ root {webroot}; allow all; }}\n"
        f"    location / {{ return 301 https://$host$request_uri; }}\n"
        f"}}\n"
    )


# [V3.0.9] B5: 探测 Nginx 版本，选择兼容的 http2 指令语法
# [V3.0.11] B4: 模块级缓存，避免 deploy/update 多次 fork nginx -v
# [V3.2.12] P2-9: 添加线程锁保护
_NGINX_HTTP2_DIRECTIVE_CACHE = None  # type: Optional[bool]  # [V3.2.3] M-9: Python 3.6 compat
_NGINX_HTTP2_LOCK = _threading.Lock()


def _set_nginx_http2_cache(value):
    # type: (bool) -> bool
    """[V3.2.13] P1-2: Thread-safe cache write for _detect_nginx_http2_directive().
    [V3.2.22] P1-2: 双重检查锁 — 锁内二次校验，防止并发时重复 fork nginx -v。
    """
    global _NGINX_HTTP2_DIRECTIVE_CACHE
    with _NGINX_HTTP2_LOCK:
        # [V3.2.22] P1-2: 双重检查：另一线程可能已在我们持锁前完成写入
        if _NGINX_HTTP2_DIRECTIVE_CACHE is not None:
            return _NGINX_HTTP2_DIRECTIVE_CACHE
        _NGINX_HTTP2_DIRECTIVE_CACHE = value
    return value

def _detect_nginx_http2_directive() -> bool:
    """Return True when Nginx >= 1.25.1 supports the standalone 'http2 on;' directive.

    Nginx < 1.25.1 requires the http2 token inline on the listen line.
    Returns False on detection failure (conservative default: inline syntax
    is compatible with all Nginx versions including CentOS 7 default 1.20.x).

    [V3.0.11] B4: Result is cached at module level to avoid repeated fork.
    """
    with _NGINX_HTTP2_LOCK:
        if _NGINX_HTTP2_DIRECTIVE_CACHE is not None:
            return _NGINX_HTTP2_DIRECTIVE_CACHE
    try:
        r = subprocess.run(
            ["nginx", "-v"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', timeout=5, check=False,
        )
        m = re.search(r'nginx/(\d+)\.(\d+)\.(\d+)', r.stdout + r.stderr)
        if m:
            ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return _set_nginx_http2_cache(ver >= (1, 25, 1))
    except Exception:
        pass
    # [V3.2.10] L-1: 检测失败时默认 False（旧语法内联）而非 True，
    # 防止在 Nginx < 1.25.1（如 CentOS 7 默认 1.20.x）上静默除去 HTTP/2。
    # 旧语法将 http2 配置内联到 listen 行，在所有版本均安全。
    return _set_nginx_http2_cache(False)  # 保守小默认：内联语法兼容所有版本


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
        + f"    server_name {_nginx_server_names(domain)};\n"
        f"    root {webroot};\n"
        + _http2
        + f"    server_tokens off;\n"
        f"\n"
        f"    access_log /var/log/nginx/{domain}.access.log combined;\n"
        f"    error_log  /var/log/nginx/{domain}.error.log;\n"
        f"\n"
        f"    index index.php index.html index.htm;\n"
        f"    client_max_body_size 100M;\n"
        f"\n"
        f"    # [V3.1.1] Issue 9: Block non-standard HTTP methods\n"
        f"    if ($request_method !~ ^(GET|POST|HEAD|OPTIONS)$) {{ return 444; }}\n"
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
        # [V3.2.10] M-4: 对代理请求也启用 gzip，
        # 防止站点在自建反代理或负载均衡器后方时响应体未压缩。
        f"    gzip_proxied any;\n"
    )


# [PATCH-L3] 公共安全头定义：同时被 _nginx_font_security_headers 和
# _nginx_base_security_headers 引用，新增/修改安全头只需改此一处。
_COMMON_SECURITY_HEADER_PAIRS = [
    ("X-Content-Type-Options",         "nosniff"),
    ("Referrer-Policy",                 "strict-origin-when-cross-origin"),
    ("Permissions-Policy",
     "camera=(), microphone=(), geolocation=(), payment=(), "
     "interest-cohort=(), usb=(), display-capture=()"),
    ("X-Permitted-Cross-Domain-Policies", "none"),
]


def _nginx_font_security_headers() -> str:
    """[V3.2.3] H-3: 字体 location 安全头 — 单一事实来源。

    字体 location 使用 add_header (CORS)，会覆盖 server 级 add_header，
    因此必须重新声明所有关键安全头。此函数与 _nginx_base_security_headers()
    共享同一份安全头清单，新增/修改安全头只需改此一处。
    """
    # [PATCH-L3] 使用公共常量，与 _nginx_base_security_headers 保持同步
    _lines = [
        '        add_header Strict-Transport-Security'
        ' "max-age=63072000; includeSubDomains; preload" always;\n',
    ]
    for _hdr, _val in _COMMON_SECURITY_HEADER_PAIRS:
        _lines.append(f'        add_header {_hdr} "{_val}" always;\n')
    return "".join(_lines)


def _nginx_static_cache() -> str:
    """P1: 静态资源浏览器长缓存 (WordOps/SpinupWP 标配)。

    图片 365 天; JS/CSS 30 天; 字体 365 天 + CORS。
    关闭 access_log 减少 I/O。

    [V3.0.16] F4: 图片/JS/CSS 仅用 expires 指令设置缓存 (不用 add_header),
    避免 Nginx location 块 add_header 覆盖 server 块安全响应头 (HSTS 等)。
    字体需要 CORS add_header, 必须重新声明关键安全头。
    """
    # [V3.2.3] H-3: 字体安全头调用共享函数，消除与 _nginx_base_security_headers 的重复
    _font_security = _nginx_font_security_headers()
    return (
        f"\n"
        f"    # [V3.0.16] Static resource browser caching\n"
        f"    # Images: expires only (no add_header → inherits server security headers)\n"
        f"    location ~* \\.(?:jpg|jpeg|png|gif|ico|webp|avif|svg|svgz)$ {{\n"
        f"        expires 365d;\n"
        f"        access_log off;\n"
        f"        log_not_found off;\n"
        f"    }}\n"
        f"    # JS/CSS: expires only\n"
        f"    location ~* \\.(?:css|js)$ {{\n"
        f"        expires 30d;\n"
        f"        access_log off;\n"
        f"        log_not_found off;\n"
        f"    }}\n"
        f"    # Fonts: needs CORS add_header → must re-declare critical security headers\n"
        f"    location ~* \\.(?:woff|woff2|ttf|otf|eot)$ {{\n"
        f"        expires 365d;\n"
        f"        add_header Access-Control-Allow-Origin \"*\";\n"
        + _font_security
        + f"        access_log off;\n"
        f"        log_not_found off;\n"
        f"    }}\n"
    )


def _nginx_open_file_cache() -> str:
    """P9: Nginx open_file_cache — 减少 stat() 系统调用。

    借鉴 SpinupWP / 高级 Nginx 调优指南。
    缓存文件描述符、大小、修改时间等元数据, 对大量静态资源的站点有显著提升。
    inactive=60s: 60 秒内无访问则从缓存移除。
    valid=30s: 每 30 秒重新 stat() 验证文件是否变更。
    """
    return (
        f"\n"
        f"    # [V3.0.16] open_file_cache (--optimize)\n"
        f"    open_file_cache max=10000 inactive=60s;\n"
        f"    open_file_cache_valid 30s;\n"
        f"    open_file_cache_min_uses 2;\n"
        f"    open_file_cache_errors on;\n"
    )


def _nginx_base_security_headers():
    """[V3.2.2] N-1: 公共安全响应头 (HTTP/HTTPS 共用)。

    所有非 HSTS 的安全头集中维护于此。新增安全头只需改此一处。
    注意: _nginx_static_cache() 字体 location 因 add_header 覆盖需独立声明,
    修改本函数时须同步检查字体 location 安全头。
    """
    # [PATCH-L3] 使用公共常量，与 _nginx_font_security_headers 保持同步
    _lines = []
    for _hdr, _val in _COMMON_SECURITY_HEADER_PAIRS:
        _lines.append(f'    add_header {_hdr} "{_val}" always;\n')
    # [V3.2.3] L-6: CSP 保留（字体 location 无需 CSP，故不入公共常量）
    # [V3.2.8] L-2: 以下 CSP 为安全默认值。如使用 Google Fonts、外部 CDN、
    # WooCommerce 支付网关等依赖外部资源的插件，需在此追加对应域名白名单，
    # 例如在 script-src 后加 https://cdn.example.com，否则外部资源会被拦截。
    _lines.append(
        "    add_header Content-Security-Policy \"default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'self';\" always;\n"
    )
    return "".join(_lines)


def _nginx_security_headers(cache_mode="none", safe_name=""):
    """安全响应头: HSTS + 公共头 + 可选 FastCGI 缓存头。"""
    cache_header = ""
    if cache_mode == "fastcgi":
        cache_header = f"    add_header X-FastCGI-Cache $upstream_cache_status;\n"
    return (
        f"\n"
        f"    add_header Strict-Transport-Security"
        f" \"max-age=63072000; includeSubDomains; preload\" always;\n"
        + _nginx_base_security_headers()
        + f"{cache_header}"
    )


def _resolve_cert_paths(domain: str, certbot_bin: str = "") -> tuple:
    """P2/P4: 返回 (fullchain_path_str, privkey_path_str)。

    [V3.1.0 P2] 修复：不再硬编码 ["certbot", ...]。
    未传入 certbot_bin 时自动探测（shutil.which → /snap/bin → certbot-auto → "certbot"），
    与 SiteConfig._detect_certbot_bin() 保持相同优先级。

    [V3.1.0 P4] 重构：探测逻辑全部委托给 SiteConfig._probe_cert_paths()，
    消除与 _probe_cert_paths() 的代码重复。
    接口不变（返回 (str, str)），向后兼容。
    privkey.pem 由 fullchain.pem 所在目录衍生（同目录兄弟文件）。
    """
    if not certbot_bin:
        # [V3.2.2] N-2: 模块顶层已 import shutil
        certbot_bin = (
            shutil.which("certbot")
            or ("/snap/bin/certbot" if Path("/snap/bin/certbot").is_file() else None)
            or ("/usr/local/bin/certbot-auto"
                if Path("/usr/local/bin/certbot-auto").is_file() else None)
            or "certbot"
        )
    # 委托给 SiteConfig._probe_cert_paths() — 单一事实来源
    chain, key = SiteConfig._probe_cert_paths(domain, certbot_bin)
    return (str(chain), str(key))

def _nginx_ssl_params(domain: str,
                      cert_chain: str = "",
                      cert_key: str = "") -> str:
    """SSL 证书 / 协议 / 密码套件 / OCSP Stapling。

    cert_chain / cert_key 必须由调用方通过 _resolve_cert_paths() 填充后传入。
    [V3.1.0 S1] 移除永不可达的硬编码兜底路径（唯一调用点 generate_https_config()
    已保证非空传入）；改为 ValueError，防止未来调用方漏传参数时静默写错 Nginx 配置。
    """
    if not cert_chain or not cert_key:
        raise ValueError(
            f"_nginx_ssl_params({domain!r}): "
            "cert_chain and cert_key must be supplied by caller "
            "(use _resolve_cert_paths()); "
            "hardcoded letsencrypt fallback removed in V3.1.0 S1."
        )
    return (
        f"\n"
        f"    ssl_certificate {cert_chain};\n"
        f"    ssl_certificate_key {cert_key};\n"
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
        # [V3.1.1] P9: OCSP Stapling 已禁用 (LE 2025-08-06 关停服务)。
        # 保留 ssl_stapling on 会产生 nginx [warn] 日志并可能阻塞 reload。
        # 证书吊销验证已转由客户端查询 CRL 负责，此处无需服务端 stapling。
        # 参考: https://letsencrypt.org/2024/12/05/ending-ocsp/
        # f"    ssl_stapling on;\n"
        # f"    ssl_stapling_verify on;\n"
        # f"    resolver 1.1.1.1 8.8.8.8 valid=300s;\n"
        # f"    resolver_timeout 5s;\n"
    )


def _nginx_fastcgi_cache_block(safe_name: str) -> str:
    """FastCGI Cache: 跳过条件 (仅 fastcgi 模式启用)。"""
    return (
        f"\n"
        f"    set $skip_cache 0;\n"
        f"    if ($request_method = POST) {{ set $skip_cache 1; }}\n"
        f"    if ($query_string != \"\") {{ set $skip_cache 1; }}\n"
        # [V3.0.18] C1: $request_uri（含 query string）→ $uri（纯路径），
        # 防止 /?ref=/xmlrpc.php 参数注入穿透 FastCGI 缓存。
        # 各子模式添加 ^ 起始锚点；xmlrpc 额外加 $ 尾锚，与 location ~* 语义一致。
        f"    if ($uri ~* \"^/wp-admin/|^/wp-json/|^/xmlrpc\\.php$|^/wp-.*\\.php$\") "
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
            f"        fastcgi_cache_lock on;\n"
            f"        fastcgi_cache_lock_timeout 5s;\n"
            # [V3.2.0] F2: PHP-FPM 崩溃/重启时返回旧缓存而非 502/504
            # WordOps/SpinupWP/EasyEngine 标配; 不含 http_502 以免掩盖持久故障
            f"        fastcgi_cache_use_stale error timeout updating"
            f" http_500 http_503;\n"
            f"        fastcgi_cache_background_update on;\n"
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
            # [V3.0.17] L1: = (精确匹配) → ~* (大小写不敏感正则)
            # 防止 /XMLRPC.PHP 等大小写变体绕过限速规则，与缓存绕过 ~* 保持语义一致
            f"    location ~* ^/xmlrpc\\.php$ {{\n"
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
            # [V3.0.17] L1: = (精确匹配) → ~* (大小写不敏感正则)
            f"    location ~* ^/xmlrpc\\.php$ {{ deny all; access_log off; log_not_found off; }}\n"
        )
    return (
        f"\n"
        f"    location ~ /\\. {{ deny all; }}\n"
        f"    location ~* wp-config\\.php {{ deny all; return 404; }}\n"
        f"    location ~* /wp-content/uploads/.*\\.php$ {{ deny all; return 404; }}\n"
        f"    # [V3.1.1] Issue 3: admin-ajax.php rate limiting\n"
        f"    location = /wp-admin/admin-ajax.php {{\n"
        f"        limit_req zone=wpadmin_{safe_name} burst=20 nodelay;\n"
        f"        limit_req_status 429;\n"
        f"        try_files $uri =404;\n"
        f"        fastcgi_pass unix:{sock_path};\n"
        f"        fastcgi_index index.php;\n"
        f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        f"        include fastcgi.conf;\n"
        f"    }}\n"
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
        # [V3.2.9] L-2: wp-trackback.php 是已知 DDoS 放大和垃圾评论载体
        f"    location = /wp-trackback.php {{ deny all; access_log off; log_not_found off; }}\n"
        f"    # [V3.1.1] Issue 10: Block direct PHP execution in wp-includes\n"
        f"    # Exception: ms-files.php needed by Multisite media serving\n"
        f"    location = /wp-includes/ms-files.php {{\n"
        f"        try_files $uri =404;\n"
        f"        fastcgi_pass unix:{sock_path};\n"
        f"        fastcgi_index index.php;\n"
        f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        f"        include fastcgi.conf;\n"
        f"    }}\n"
        f"    location ~* /wp-includes/.*\\.php$ {{ deny all; }}\n"
        f"    location ^~ /.well-known/acme-challenge/ {{ allow all; }}\n"
        f"}}\n"
    )



def generate_http_production_config(domain, webroot, sock_path,
                                    cache_mode="none",
                                    allow_xmlrpc=False,
                                    optimize=False):
    """生成不含 SSL 的完整生产 Nginx 配置 (--skip-ssl 模式)。

    与 generate_https_config 功能对等, 但:
      - 仅监听 80 端口 (无 443/SSL/HSTS)
      - 保留 FastCGI 缓存 / 安全 location / Gzip 等所有生产特性
      - 保留 ACME challenge 通道, 方便后续 enable-ssl
    """
    safe = _nginx_safe_name(domain)

    # ── preamble (server{} 块外) ──
    parts = [_nginx_preamble(domain, cache_mode, allow_xmlrpc=allow_xmlrpc)]

    # ── server{} 块 ──
    _sn = _nginx_server_names(domain)
    srv = (
        f"server {{\n"
        f"    listen 80;\n"
        f"    listen [::]:80;\n"
        f"    server_name {_sn};\n"
        f"    root {webroot};\n"
        f"    server_tokens off;\n"
        f"\n"
        f"    access_log /var/log/nginx/{domain}.access.log combined;\n"
        f"    error_log  /var/log/nginx/{domain}.error.log;\n"
        f"\n"
        f"    index index.php index.html index.htm;\n"
        f"    client_max_body_size 100M;\n"
        f"\n"
        f"    # Block non-standard HTTP methods\n"
        f"    if ($request_method !~ ^(GET|POST|HEAD|OPTIONS)$) {{ return 444; }}\n"
    )
    parts.append(srv)

    # Gzip
    parts.append(_nginx_gzip())

    # 静态资源缓存
    parts.append(_nginx_static_cache())

    # open_file_cache (--optimize)
    if optimize:
        parts.append(_nginx_open_file_cache())

    # [V3.2.2] N-1: 复用公共安全头函数 (无 HSTS)
    _sec = "\n" + _nginx_base_security_headers()
    if cache_mode == "fastcgi":
        _sec += "    add_header X-FastCGI-Cache $upstream_cache_status;\n"
    parts.append(_sec)

    # FastCGI 缓存跳过逻辑
    if cache_mode == "fastcgi":
        parts.append(_nginx_fastcgi_cache_block(safe))

    # PHP location
    parts.append(
        _nginx_php_location(sock_path, cache_mode=cache_mode, safe_name=safe)
    )

    # WordPress 安全 location (复用 _nginx_wp_security, 去掉末尾 } 再追加 ACME)
    _wp_sec = _nginx_wp_security(safe, sock_path, allow_xmlrpc=allow_xmlrpc)
    # _nginx_wp_security 末尾已含 ^~ /.well-known/acme-challenge/ 和 }\n
    parts.append(_wp_sec)

    return "".join(parts)



def generate_https_config(domain: str, webroot: Path, sock_path: str,
                          cache_mode: str = "none",
                          allow_xmlrpc: bool = False,
                          optimize: bool = False,
                          cert_chain: str = "",
                          cert_key: str = "") -> str:
    """组装完整的 Nginx HTTPS 配置。

    V3.0.0 重构: 从 10 个独立片段函数组装，每个片段可独立测试和修改。
    V3.0.3: 新增 allow_xmlrpc 参数，控制 xmlrpc.php 是 deny 还是速率限制透传。
    V3.0.19: 新增 cert_chain / cert_key 参数；调用方传入 cfg.cert_chain / cfg.cert_key
             时直接使用，省去函数内 _resolve_cert_paths() 运行时探测。
             空值时降级到 _resolve_cert_paths() 保持向后兼容。
    """
    safe = _nginx_safe_name(domain)
    # [V3.0.9] B5: 探测一次 Nginx 版本，传入 _nginx_ssl_core
    _http2_directive = _detect_nginx_http2_directive()
    # [V3.0.19] D1d: 调用方传入已探测路径时直接使用；未传入则运行时探测（向后兼容）
    if not cert_chain or not cert_key:
        _fc, _fk = _resolve_cert_paths(domain)
        cert_chain = cert_chain or _fc
        cert_key   = cert_key   or _fk

    parts = [
        _nginx_preamble(domain, cache_mode, allow_xmlrpc=allow_xmlrpc),
        _nginx_http_redirect(domain, webroot),
        "\n",
        _nginx_ssl_core(domain, webroot, http2_directive=_http2_directive),
        _nginx_gzip(),
        _nginx_static_cache(),  # [V3.0.16] P1
        _nginx_open_file_cache() if optimize else "",  # [V3.0.16] P9
        _nginx_security_headers(cache_mode=cache_mode, safe_name=safe),
        _nginx_ssl_params(domain, cert_chain=cert_chain, cert_key=cert_key),
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
        # [V3.2.11] P2-10: 这是 invariant check（永不触发的防御断言），
        # 而非业务逻辑。base64url 输出保证不含 ' 或 \，
        # 若触发则说明 secrets/base64 模块行为异常，需立即中止。
        if chr(39) in salt_val or chr(92) in salt_val:
            raise ValueError(
                "base64url output contains unexpected characters "
                "(single-quote or backslash in base64url output)"
            )

        # [V3.2.27] BUG-7: 添加 re.DOTALL，使 '.' 可匹配跨行 salt 值（畸形配置）；
        # 分组已为非贪婪 .*?，此处同步标注以明确意图。
        pattern = r"define\(\s*'" + re.escape(key) + r"'\s*,\s*'(.*?)'\s*\);"
        content = re.sub(pattern, f"define('{key}', '{salt_val}');", content,
                         flags=re.DOTALL)
    return content


def inject_wp_hardening(content, skip_ssl=False):
    # type: (str, bool) -> str
    """向 wp-config.php 注入安全加固常量。

    [V3.2.12] P2-7: 新增 skip_ssl 参数，直接控制 FORCE_SSL_ADMIN 注入值，
    避免调用方先注入 true 再立即覆盖为 false 的冗余操作。

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
        ("FORCE_SSL_ADMIN", "false" if skip_ssl else "true"),
        ("WP_AUTO_UPDATE_CORE", "'minor'"),
        ("WP_POST_REVISIONS", "10"),
        ("EMPTY_TRASH_DAYS", "7"),
        ("DISABLE_WP_CRON", "true"),  # [V3.0.16] P2: 服务端 cron 替代
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
        r"^(?:/\*.*(?:stop editing|停止编辑).*\*/|//.*(?:stop editing|停止编辑))",
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


def _set_force_ssl_admin(content, enabled=True):
    """[V3.2.3] M-8: 使用正则匹配 FORCE_SSL_ADMIN, 容忍格式差异。

    兼容: define('FORCE_SSL_ADMIN', true); / define( "FORCE_SSL_ADMIN" , true );
    以及各种注释后缀。
    """
    if enabled:
        _new_val = "define('FORCE_SSL_ADMIN', true);"
    else:
        _new_val = "define('FORCE_SSL_ADMIN', false); // HTTP-only deploy"
    _pattern = re.compile(
        r"define\s*\(\s*['\"]FORCE_SSL_ADMIN['\"]\s*,\s*(?:true|false)\s*\)\s*;[^\n]*",
        re.IGNORECASE,
    )
    if _pattern.search(content):
        content = _pattern.sub(_new_val, content)
    elif "'FORCE_SSL_ADMIN'" not in content and '"FORCE_SSL_ADMIN"' not in content:
        # [V3.2.5] A-3: 常量缺失时注入到 "stop editing" 标记之前
        _inject = "\n" + _new_val + "\n"
        _marker = re.search(r"^(?:/\*.*(?:stop editing|停止编辑).*\*/|//.*(?:stop editing|停止编辑))",
                            content, re.M | re.I)
        if _marker:
            content = content[:_marker.start()] + _inject + content[_marker.start():]
        else:
            _req_pos = content.rfind("require_once")
            if _req_pos != -1:  # [V3.2.71] BUG-1: rfind 返回 0 时也应注入
                content = content[:_req_pos] + _inject + content[_req_pos:]
    return content


def patch_wplang(content: str) -> str:
    """B6: 确保 wp-config.php 中 WPLANG 与 _LANG 一致。

    解决跨语言兜底下载问题：用户选英文但中文源先成功时，
    wp-config-sample.php 中 WPLANG='zh_CN'；反之亦然。
    此函数在生成 wp-config.php 时强制校正。

    [V3.0.17] B2: 官方全球英文核心包的 wp-config-sample.php 不含
    WPLANG define 行；正则匹配失败时改为主动注入，不再静默跳过。
    """
    target_locale = "zh_CN" if _LANG == "zh" else ""
    # 匹配已有 define('WPLANG', '...')
    pattern = r"(define\(\s*'WPLANG'\s*,\s*')(?:[^'\\]|\\.)*('\s*\);)"
    if re.search(pattern, content):
        # 已有 WPLANG 行：直接替换值
        content = re.sub(pattern, lambda m: m.group(1) + target_locale + m.group(2), content)
    else:
        # [V3.0.17] B2: 英文核心包的 wp-config-sample.php 无 WPLANG define 行，
        # 正则匹配不到时主动注入，注入点选在 DB_COLLATE define 之后。
        inject_line = "\ndefine( 'WPLANG', '" + target_locale + "' );"
        anchor = re.search(
            r"define\s*\(\s*'DB_COLLATE'\s*,[^)]*\)\s*;",
            content,
        )
        if anchor:
            pos = anchor.end()
            content = content[:pos] + inject_line + content[pos:]
        else:
            # 终极兜底：追加到文件末尾
            content = content + inject_line + "\n"
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
    """安全替换 php-fpm pool 配置中的 user/group/listen.owner/listen.group。

    [V3.2.14] P0-1: 补齐 listen.owner / listen.group / listen.mode 修补,
    解决 RHEL/CentOS 上 Nginx 用户 (nginx) 与 FPM pool 默认 listen.owner
    (nobody/apache) 不一致导致 socket 权限错误 → 502 Bad Gateway 的问题。

    Args:
        content: Pool 配置文件内容。
        user:    目标 user 指令值。
        group:   目标 group 指令值；省略时与 user 相同（常规 nginx:nginx 场景）。
    """
    _group = group or user
    # [V3.0.9] S6: 独立处理 user/group，支持两者设为不同值
    # [V3.2.14] P0-1: 同步修补 listen.owner/listen.group/listen.mode
    for key, _val in (
        ('user', user),
        ('group', _group),
        ('listen.owner', user),
        ('listen.group', _group),
    ):
        # 优先匹配已激活行
        pattern = re.compile(
            r'^(\s*' + re.escape(key) + r'\s*=\s*)(\S+)$',
            re.MULTILINE,
        )
        if pattern.search(content):
            content = pattern.sub(lambda m, v=_val: m.group(1) + v, content)
        else:
            # 匹配被 ; 注释的行 → 取消注释并替换值
            commented = re.compile(
                r'^\s*;\s*(' + re.escape(key) + r'\s*=\s*)(\S+)$',
                re.MULTILINE,
            )
            if commented.search(content):
                content = commented.sub(
                    lambda m, v=_val: m.group(1) + v, content, count=1,
                )
    # listen.mode: 确保 socket 权限为 0660 (owner+group 可读写)
    _mode_pat = re.compile(
        r'^(\s*listen\.mode\s*=\s*)(\S+)$', re.MULTILINE,
    )
    if _mode_pat.search(content):
        content = _mode_pat.sub(lambda m: m.group(1) + "0660", content)
    else:
        _mode_commented = re.compile(
            r'^\s*;\s*(listen\.mode\s*=\s*)(\S+)$', re.MULTILINE,
        )
        if _mode_commented.search(content):
            content = _mode_commented.sub(
                lambda m: m.group(1) + "0660", content, count=1,
            )
        else:
            # [V3.2.17] P1-1: listen.mode 完全缺失时追加,
            # 防止 RHEL 最小安装 socket 权限受 umask 影响导致 502
            # [V3.2.34] P-4: 宽松检测已有 listen.mode 行 (含注释后缀等变体),
            # 仅在确实不存在时追加, 避免重复运行产生重复行。
            _has_listen_mode = bool(re.search(
                r'^\s*listen\.mode\s*=', content, re.MULTILINE,
            ))
            if not _has_listen_mode:
                content = content.rstrip("\n") + "\nlisten.mode = 0660\n"
    return content


# ---------------------------------------------------------------------------
# certbot 错误分类（借鉴 sooth_monitor 的 _docker_call 错误分类体系）
# ---------------------------------------------------------------------------
def _fetch_zerossl_eab(email: str) -> tuple:
    """[V3.2.58] 模块级：POST ZeroSSL API 用 email 换 EAB 凭据。

    返回 (kid, hmac)  — 成功
         ("", err_msg) — 失败（连接超时、API 错误等）

    此函数只做网络请求，不含任何用户交互或日志输出。
    供向导函数和 WPDeployManager._acquire_zerossl_eab 共用。
    """
    if not email:
        return ("", "no email provided")
    try:
        import urllib.request as _ur
        import urllib.parse as _up
        _payload = _up.urlencode({"email": email}).encode()
        _req = _ur.Request(
            "https://api.zerossl.com/acme/eab-credentials-email",
            data=_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": "wp-ssl-bootstrap/" + __version__},
        )
        with _ur.urlopen(_req, timeout=15) as _resp:
            _raw = _resp.read(64 * 1024).decode("utf-8")
        _js = json.loads(_raw)
        # [V3.2.62] BUG-β: API 可能返回非 object（null / array / scalar）；
        # 直接 .get() 会触发 AttributeError，被外层 except 捕获但消息误导。
        if not isinstance(_js, dict):
            return ("", f"unexpected response: {_raw[:120]!r}")
        _kid  = str(_js.get("eab_kid",  "")).strip()
        _hmac = str(_js.get("eab_hmac_key", "")).strip()
        if _kid and _hmac:
            return (_kid, _hmac)
        # [V3.2.61] BUG-I: error 字段可能是 dict/string/null，需 isinstance 区分；
        # or{} 模式在 string 值时仍会调用 str.get() → AttributeError
        _err_val = _js.get("error")
        if isinstance(_err_val, dict):
            _err_msg = str(_err_val.get("type", "empty response"))
        elif _err_val is not None:
            _err_msg = str(_err_val)   # API 直接返回字符串错误
        else:
            _err_msg = "empty response"
        return ("", _err_msg)
    except Exception as _e:
        return ("", str(_e))


def classify_certbot_error(stderr: str) -> int:
    """对 certbot 的 stderr 输出做错误分类。

    返回值:
        CmdResult.FATAL      — 非 CA 侧致命错误（端口占用/DNS/webroot），换 CA 也无用
        CmdResult.RETRYABLE  — CA 侧错误（限流/服务端故障），值得尝试下一个 CA
        CmdResult.PERMISSION — 权限问题
    """
    err = stderr.lower()
    # 端口占用 / 绑定失败 — 换 CA 也解决不了
    # [V3.2.63] BUG-1: "port 80" 子串会误匹配 "port 8080"；改用全词匹配，
    # 与 v3.2.60 BUG-B 对 "404" 的处理方式保持一致。
    if (any(k in err for k in (
        "could not bind", "address already in use",
        "problem binding to port",
        "connection refused on port 80",  # [V3.2.71] BUG-2: 本地端口不可达，换 CA 无效
    )) or re.search(r'\bport 80\b', err)):
        return CmdResult.FATAL
    # DNS 未解析 — 域名配置问题，换 CA 无意义
    if any(k in err for k in (
        "dns problem", "nxdomain", "no valid a record",
        "dns resolution", "could not resolve",
    )):
        return CmdResult.FATAL
    # webroot 不可达 / 验证文件无法访问
    # [V3.0.15] B3: 注释澄清——此分支的 "unauthorized" 指 ACME challenge 验证失败
    # （CA 返回 HTTP 403 "unauthorized"），属于 CA 侧交互问题，换 CA 可能成功；
    # 与下方本地文件系统 "permission denied" / "access denied" 是完全不同的错误类型。
    # "challenge failed" 同理：可能是 CA 端网络波动导致验证超时。
    # 仅 "webroot path does not exist" 确定为本地致命错误。
    # [V3.2.60] BUG-B: "404" → re 全词匹配，避免误匹配 "4048" / "port 40480" 等
    if any(k in err for k in (
        "webroot path does not exist", "challenge failed",
        "unauthorized", "the server could not connect",
    )) or re.search(r'\b404\b', err):
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
    # [V3.2.0] 国内云兼容: 扩展镜像列表, 按国内可用性排序
    # [V3.2.14] P2-1: 线程安全缓存保护 (与 _CHINA_CLOUD_CACHE 模式一致)
    _wp_ver_cache_lock = _threading.Lock()
    WPCLI_MIRRORS = [
        {
            "name": "GHFast (国内加速)",
            "phar": "https://ghfast.top/https://github.com/wp-cli/builds/raw/gh-pages/phar/wp-cli.phar",
            "hash": "https://ghfast.top/https://github.com/wp-cli/builds/raw/gh-pages/phar/wp-cli.phar.sha512",
        },
        {
            "name": "KKGitHub (国内镜像)",
            "phar": "https://raw.kkgithub.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
            "hash": "https://raw.kkgithub.com/wp-cli/builds/gh-pages/phar/wp-cli.phar.sha512",
        },
        {
            "name": "jsDelivr CDN",
            "phar": "https://cdn.jsdelivr.net/gh/wp-cli/builds@gh-pages/phar/wp-cli.phar",
            "hash": "https://cdn.jsdelivr.net/gh/wp-cli/builds@gh-pages/phar/wp-cli.phar.sha512",
        },
        {
            "name": "GitHub (官方)",
            "phar": "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
            "hash": "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar.sha512",
        },
    ]
    WPCLI_INSTALL_PATH  = Path("/usr/local/bin/wp")
    _wp_latest_version_cache = ""  # [PATCH-L6] 类级缓存，避免重复 HTTP 请求
    _wp_zh_version_cache = ""      # [FIX-1] 独立缓存 zh_CN 版本号 (cn.wordpress.org 可能落后全球主站)

    # 部署预检 / 健康检查配置
    DNS_CHECK_TIMEOUT     = 10   # dig 超时秒数
    CHALLENGE_TEST_DELAY  = 2    # 写入测试文件后等待秒数
    HEALTH_CHECK_RETRIES  = 5    # 站点健康检查最大重试次数
    HEALTH_CHECK_INTERVAL = 5    # 每次重试间隔秒数
    HEALTH_CHECK_TIMEOUT  = 10   # curl 超时秒数

    # CA 容灾列表 (staging 模式下仅使用 Let's Encrypt Staging)
    # 默认仅包含 Let's Encrypt (无需预注册，中国大陆可达)。
    # ZeroSSL 需要 EAB 预注册，通过 --zerossl-eab-kid/--zerossl-eab-hmac-key 动态注入，
    # 不作为静态条目以避免无凭据时签发失败。
    # [V3.2.51] BuyPass Go 已移除：api.buypass.com 在中国大陆 DNS 无法解析。
    CA_PROVIDERS = [
        {"name": "Let's Encrypt",  "server": None},
        # BuyPass Go 已移除 — 在中国大陆 DNS 无法解析 api.buypass.com
        # 如需在境外服务器启用，可手动追加:
        # {"name": "BuyPass Go", "server": "https://api.buypass.com/acme/directory"},
    ]

    # [V3.2.44] REF-1: 运行时锁文件路径常量 — 原散落于各方法体内的硬编码字符串。
    # 统一管理便于测试替换和路径变更，消除三处重复字符串字面量。
    _GLOBAL_LOCK_FILE    = "/run/wp-bootstrap.lock"  # acquire_lock 全局互斥锁
    _CERTBOT_LOCK_FILE   = "/run/certbot.lock"        # _run_certbot_with_lock 串行锁
    _NGINX_CONF_LOCK_FILE = "/run/nginx_config.lock"  # apply_nginx_config_safe 互斥锁

    # [V3.2.44] REF-2: MySQL 临时凭据目录 — 与 _GLOBAL_LOCK_FILE 同父目录，统一管理。
    _MYSQL_TMP_DIR = "/run/wp-bootstrap"

    # [V3.2.44] REF-3: Certbot 锁等待超时 (秒) — 原为 _run_certbot_with_lock 局部变量，
    # 在函数内被引用两次 (超时判断 + 错误消息)，提升为常量避免魔法数字重复。
    CERTBOT_LOCK_TIMEOUT = 300  # 与 setup_systemd TimeoutStartSec=300 量级一致

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
        self._wpcli_install_attempted = False  # [V3.2.5] A-13
        self._redis_svc_name = ""  # [V3.2.12] P2-11: Redis 服务名缓存
        self._rollback_stack = []  # 部署事务栈：后进先出回滚
        self._wp_admin_info = {}   # [V3.2.18] P1: _wp_auto_install admin cred storage

        self.pkg_mgr = self._detect_pkg_manager()
        # [V3.2.59] BUG-6: _is_dnf5 提升为实例属性，由 _detect_is_dnf5() 初始化
        self._is_dnf5: bool = self._detect_is_dnf5()
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

    def _detect_is_dnf5(self) -> bool:
        """[V3.2.59] BUG-6: 检测当前系统是否使用 dnf5，结果缓存为实例属性。

        与 install_packages() 内原有四级检测逻辑完全相同，提升至方法级
        以便 _install_php_redis_pecl / _brotli_install_deps 等跨方法复用。
        仅在 pkg_mgr == "dnf" 时才有意义；apt/yum 系统直接返回 False。
        """
        if self.pkg_mgr != "dnf":
            return False
        if shutil.which("dnf5"):
            return True
        try:
            _dv = subprocess.run(
                ["dnf", "--version"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace", timeout=10, check=False,
            )
            _out = (_dv.stdout + _dv.stderr).lower()
            if "dnf5" in _out:
                return True
            if _dv.returncode == 0 and _dv.stdout.strip():
                _first = _dv.stdout.strip().splitlines()[0]
                _m = re.match(r"(\d+)\.", _first.strip())
                if _m and int(_m.group(1)) >= 5:
                    return True
        except Exception:
            pass
        try:
            _osr = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
            _vm = re.search(r'VERSION_ID\s*=\s*"?(\d+)', _osr)
            if _vm and int(_vm.group(1)) >= 10:
                logging.debug("[V3.2.59] EL%s → dnf5 mode", _vm.group(1))
                return True
        except Exception:
            pass
        return False

    def _detect_nginx_user(self) -> str:
        conf_path = Path("/etc/nginx/nginx.conf")
        if conf_path.exists():
            try:
                with open(conf_path, 'r', encoding='utf-8') as f:
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
                stdout=subprocess.PIPE, encoding='utf-8', errors='replace', check=False, timeout=10,
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
                stdout=subprocess.PIPE, encoding='utf-8', errors='replace', check=False, timeout=10,
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
        # 最终 fallback：不分发行版地尝试 php 二进制探测版本
        # [V3.2.11] P1-6: 将动态探测提升为通用路径，不再仅限 apt 系；
        # 仅在 php 二进制不存在时才使用硬编码版本号（防止 php8.3→8.4+ 过时）。
        try:  # [PATCH-L4] 动态探测，避免硬编码版本号过时
            _pv_r = subprocess.run(
                ["php", "-r",
                 "echo PHP_MAJOR_VERSION.\".\".PHP_MINOR_VERSION;"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if _pv_r.returncode == 0:
                # [V3.2.11] P1-5/P1-6: 使用顶层 re，无需局部 import
                _ver = _pv_r.stdout.strip()
                if re.match(r'^\d+\.\d+$', _ver):
                    # apt/deb: php8.x-fpm；dnf/yum: php-fpm（无版本后缀）
                    if self.pkg_mgr in ("dnf", "yum"):
                        return "php-fpm"
                    return "php{}-fpm".format(_ver)
        except Exception:
            pass
        return "php-fpm" if self.pkg_mgr in ("dnf", "yum") else "php8.3-fpm"

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
                encoding='utf-8', errors='replace', check=False, timeout=10,
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
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', check=False,
                    timeout=10,  # [V3.1.0 M2]
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
                    with open(ver_conf, 'r', encoding='utf-8') as f:
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
                with open(conf, 'r', encoding='utf-8') as f:
                    for line in f:
                        m = re.match(r'^\s*listen\s*=\s*(/.+\.sock)\s*', line)
                        if m:
                            return m.group(1)
            except Exception:
                pass
        return "/run/php/php-fpm.sock" if self.pkg_mgr == "apt" else "/run/php-fpm/www.sock"

    # -----------------------------------------------------------------------
    # [V3.0.16] P3: PHP-FPM 按内存动态调参
    # -----------------------------------------------------------------------
    @staticmethod
    def _get_fs_type(path: Path) -> str:
        """B3: 返回 path 所在文件系统类型（小写），失败返回空字符串。

        用于 btrfs swap 检测：btrfs 要求 swap 文件必须设为 non-COW (nocow)
        属性，而 chattr +C 只能对空文件操作，必须在 dd 写入前执行。
        """
        target = path if path.exists() else path.parent
        # 优先使用 GNU coreutils stat -f
        try:
            r = subprocess.run(
                ["stat", "-f", "--format=%T", str(target)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().lower()
        except Exception:
            pass
        # fallback: 解析 /proc/mounts，找最长前缀匹配挂载点
        try:
            real = os.path.realpath(str(target))
            entries: list = []
            with open("/proc/mounts", encoding="utf-8") as _f:
                for line in _f:
                    parts = line.split()
                    if len(parts) >= 3:
                        entries.append((parts[1], parts[2]))
            entries.sort(key=lambda x: len(x[0]), reverse=True)
            for mnt, fstype in entries:
                mnt_norm = mnt.rstrip("/")
                if real == mnt_norm or real.startswith(mnt_norm + "/"):
                    return fstype.lower()
        except Exception:
            pass
        return ""

    @staticmethod
    def _get_total_ram_mb() -> int:
        """获取系统物理内存总量 (MB)。"""
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            page_count = os.sysconf("SC_PHYS_PAGES")
            return (page_size * page_count) // (1024 * 1024)
        except (ValueError, OSError):
            pass
        # fallback: /proc/meminfo
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except Exception:
            pass
        return 0

    def _patch_fpm_pool_tuning(self) -> None:
        """根据系统总内存动态计算 PHP-FPM pool 参数。

        公式 (借鉴 WordOps / DigitalOcean 最佳实践):
          可用给 FPM 的内存 = 总内存 * 0.6  (留 40% 给 OS/DB/Nginx)
          每个 PHP 子进程 ≈ 40-60MB (WordPress 典型值)
          pm.max_children = 可用内存 / 50

        内存分级策略:
          ≤ 1GB   → pm=ondemand,  max_children=5
          ≤ 2GB   → pm=ondemand,  max_children=10
          ≤ 4GB   → pm=dynamic,   max_children=20
          > 4GB   → pm=dynamic,   max_children=按公式
        """
        total_mb = self._get_total_ram_mb()
        if total_mb <= 0:
            return

        if total_mb <= 1024:
            pm_mode, max_ch = "ondemand", 5
        elif total_mb <= 2048:
            pm_mode, max_ch = "ondemand", 10
        elif total_mb <= 4096:
            pm_mode, max_ch = "dynamic", 20
        else:
            pm_mode = "dynamic"
            max_ch = max(20, int(total_mb * 0.6 / 50))

        logging.info(t("info_fpm_tuning",
                       total=total_mb, children=max_ch, mode=pm_mode))

        # 计算 dynamic 模式下的辅助参数
        start_servers = max(2, max_ch // 4)
        min_spare = max(1, max_ch // 4)
        max_spare = max(2, max_ch // 2)

        for conf_path in self._get_php_conf_paths():
            try:
                content = Path(conf_path).read_text(encoding="utf-8")
                # pm = dynamic|static|ondemand
                # [V3.0.16] F2: 用 patch_php_ini_line 统一处理 (支持注释行/缺失行)
                content = patch_php_ini_line(content, "pm", pm_mode)
                content = patch_php_ini_line(content, "pm.max_children", str(max_ch))
                if pm_mode == "dynamic":
                    # [V3.0.16] F2: 用 patch_php_ini_line 处理注释行/缺失行
                    content = patch_php_ini_line(content, "pm.start_servers", str(start_servers))
                    content = patch_php_ini_line(content, "pm.min_spare_servers", str(min_spare))
                    content = patch_php_ini_line(content, "pm.max_spare_servers", str(max_spare))
                if pm_mode == "ondemand":
                    # 确保 process_idle_timeout 存在
                    if "pm.process_idle_timeout" not in content:
                        content += "\npm.process_idle_timeout = 10s\n"
                # [V3.2.0] F3: 防止 WordPress 插件内存泄漏导致 worker 无限膨胀
                # WordOps/DigitalOcean/SlickStack 标准值: 500
                content = patch_php_ini_line(content, "pm.max_requests", "500")
                if not self._safe_write_file(conf_path, content, mode=0o644):
                    logging.warning(t("warn_fpm_tuning_fail",
                                      path=conf_path, e="atomic write failed"))
            except Exception as e:
                logging.warning(t("warn_fpm_tuning_fail", path=conf_path, e=e))

    # -----------------------------------------------------------------------
    # [V3.0.16] P6: MariaDB 基础调优
    # -----------------------------------------------------------------------
    def _tune_mariadb(self) -> None:
        """按系统内存分级写入 MariaDB 调优配置。

        借鉴 WordOps / DigitalOcean MySQLTuner 指南:
          ≤ 1GB  → buffer_pool=128M, max_conn=50,  关闭 performance_schema
          ≤ 2GB  → buffer_pool=256M, max_conn=100, 关闭 performance_schema
          ≤ 4GB  → buffer_pool=512M, max_conn=200
          > 4GB  → buffer_pool=总内存*50%, max_conn=300

        写入 /etc/mysql/conf.d/ 或 /etc/my.cnf.d/ (按发行版),
        重启数据库服务生效。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_mariadb_tuning"))
            return

        if self.cfg.is_external_db:
            logging.info(t("info_mariadb_tuning_skip_ext"))
            return

        total_mb = self._get_total_ram_mb()
        if total_mb <= 0:
            return

        if total_mb <= 1024:
            pool, conn, perf_schema = 128, 50, True
        elif total_mb <= 2048:
            pool, conn, perf_schema = 256, 100, True
        elif total_mb <= 4096:
            pool, conn, perf_schema = 512, 200, False
        else:
            pool = int(total_mb * 0.5)
            conn, perf_schema = 300, False

        lines = [
            "# [V3.0.16] WP-SSL-Bootstrap MariaDB tuning",
            "[mysqld]",
            f"innodb_buffer_pool_size = {pool}M",
            # [V3.0.16] F5: 移除 innodb_log_file_size (MariaDB < 10.6 变更后启动失败)
            "innodb_flush_log_at_trx_commit = 2",
            "innodb_flush_method = O_DIRECT",
            f"max_connections = {conn}",
            "skip_name_resolve = ON",
            "tmp_table_size = 64M",
            "max_heap_table_size = 64M",
            "table_open_cache = 2000",
            "thread_cache_size = 16",
        ]
        if perf_schema:
            lines.append("performance_schema = OFF")

        # 确定配置目录
        for conf_dir in ("/etc/mysql/conf.d", "/etc/my.cnf.d"):
            if Path(conf_dir).is_dir():
                conf_path = Path(conf_dir) / "wp-bootstrap-tuning.cnf"
                try:
                    # [V3.2.0] F8: 原子写入, 防止断电截断导致 MariaDB 启动失败
                    _cnf_content = "\n".join(lines) + "\n"
                    if not self._safe_write_file(conf_path, _cnf_content,
                                                 mode=0o644):
                        raise OSError("_safe_write_file failed: "
                                      + str(conf_path))
                    logging.info(t("info_mariadb_tuning",
                                   path=conf_path, pool=pool, conn=conn))
                    # 重启数据库使配置生效
                    _restart_ok = self.run_cmd(
                        ["systemctl", "restart", self.db_svc], quiet=True,
                    )
                    # [V3.2.0] F5: 重启失败时回滚调优配置, 恢复数据库服务
                    if not _restart_ok:
                        logging.warning(
                            "MariaDB restart failed after tuning; "
                            "removing %s and retrying restart...",
                            conf_path,
                        )
                        try:
                            conf_path.unlink()
                        except OSError:
                            pass
                        # [V3.2.3] M-2: 检查回滚后重启是否成功
                        _rollback_restart = self.run_cmd(
                            ["systemctl", "restart", self.db_svc],
                            quiet=True,
                        )
                        if not _rollback_restart:
                            logging.error(
                                "MariaDB restart still failed after removing "
                                "tuning config %s. Data directory may be "
                                "corrupted. Check: journalctl -u %s",
                                conf_path, self.db_svc,
                            )
                    # [V3.2.14] P1-3: 检查返回值并明确告警,
                    # 防止后续 SQL 操作静默失败
                    if not self._wait_db_ready():
                        logging.error(
                            "MariaDB not ready after tuning restart; "
                            "subsequent SQL operations may fail. "
                            "Manual check: systemctl status %s",
                            self.db_svc,
                        )
                except Exception as e:
                    logging.warning(t("warn_mariadb_tuning_fail", e=e))
                return

        # 两个目录都不存在 — 尝试写 /etc/my.cnf 的 include 机制
        logging.warning(t("warn_mariadb_tuning_fail",
                          e="No conf.d directory found"))

    # -----------------------------------------------------------------------
    # [V3.0.16] P5: Linux 内核网络参数调优
    # -----------------------------------------------------------------------
    def _tune_kernel_network(self) -> None:
        """写入 sysctl drop-in, 启用 BBR 拥塞控制并优化 TCP 参数。

        借鉴 WordOps WO-kernel + DigitalOcean 最佳实践。
        BBR 需内核 4.9+, 不支持时静默跳过。
        失败不阻断部署。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_kernel_tuning"))
            return

        # 检测 BBR 可用性
        bbr_available = False
        try:
            r = subprocess.run(
                ["modprobe", "tcp_bbr"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10, check=False,
            )
            if r.returncode == 0:
                # 验证模块已加载
                avail = Path("/proc/sys/net/ipv4/tcp_available_congestion_control")
                if avail.exists() and "bbr" in avail.read_text(encoding="utf-8"):
                    bbr_available = True
        except Exception:
            pass

        lines = [
            "# [V3.0.16] WP-SSL-Bootstrap kernel network tuning",
            "",
            "# TCP optimizations",
            "net.core.somaxconn = 65535",
            "net.core.netdev_max_backlog = 16384",
            "net.ipv4.tcp_max_syn_backlog = 8192",
            "net.ipv4.tcp_slow_start_after_idle = 0",
            "net.ipv4.tcp_tw_reuse = 1",
            "",
            "# File descriptors",
            "fs.file-max = 500000",
            "",
            "# TCP keepalive (faster dead connection detection)",
            "net.ipv4.tcp_keepalive_time = 600",
            "net.ipv4.tcp_keepalive_intvl = 30",
            "net.ipv4.tcp_keepalive_probes = 5",
        ]

        if bbr_available:
            lines.extend([
                "",
                "# BBR congestion control (kernel 4.9+)",
                "net.core.default_qdisc = fq",
                "net.ipv4.tcp_congestion_control = bbr",
            ])
        else:
            logging.info(t("info_kernel_bbr_unavail"))

        conf_file = Path("/etc/sysctl.d/99-wp-bootstrap-network.conf")
        try:
            # [V3.2.0] F8: 原子写入, 防止断电截断 sysctl drop-in
            _sysctl_content = "\n".join(lines) + "\n"
            if not self._safe_write_file(conf_file, _sysctl_content,
                                         mode=0o644):
                raise OSError("_safe_write_file failed: "
                              + str(conf_file))
            self.run_cmd(["sysctl", "--system"], quiet=True)
            logging.info(t("info_kernel_tuning"))
        except Exception as e:
            logging.warning(t("warn_kernel_tuning_fail", e=e))

    # -----------------------------------------------------------------------
    # [V3.0.16] P4: Swap 自动创建 (小内存 VPS 防 OOM)
    # -----------------------------------------------------------------------
    def _swap_detect_existing(self):
        # type: () -> int
        """检测已有 swap 空间 (MB)。

        返回值:
          > 0  — 已有 swap 的 MB 数
            0  — 命令成功但无 swap
           -1  — 检测失败 (两种方式均未成功)

        [V3.2.29] BUG-D: CentOS 7 的 util-linux < 2.26 不支持
        swapon --show, 回退到解析 /proc/swaps (内核接口, 全版本可用)。
        """
        # 方式 1: swapon --show
        _method1_ok = False
        try:
            r = subprocess.run(
                ["swapon", "--show=SIZE", "--bytes", "--noheadings"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                swap_bytes = sum(
                    int(line.strip()) for line in r.stdout.splitlines()
                    if line.strip().isdigit()
                )
                if swap_bytes > 0:
                    return swap_bytes // (1024 * 1024)
                # [V3.2.43] FIX-9: output present but no parseable byte values
                # (e.g. CentOS 7 util-linux < 2.28 returns '2G' even with
                # --bytes when kernel/util-linux mismatch). Fall through to
                # /proc/swaps rather than falsely reporting 0 swap.
            elif r.returncode == 0:
                _method1_ok = True  # 命令成功但无 swap
        except Exception:
            pass

        # 方式 2: /proc/swaps (CentOS 7 / util-linux < 2.26)
        if not _method1_ok:
            try:
                _ps = Path("/proc/swaps").read_text(encoding="utf-8")
                _ps_lines = _ps.strip().splitlines()[1:]  # 跳过表头
                if _ps_lines:
                    _swap_kb = sum(
                        int(parts[2]) for parts in
                        (_line.split() for _line in _ps_lines)  # [V3.2.36-P4]
                        if len(parts) >= 3 and parts[2].isdigit()
                    )
                    return _swap_kb // 1024
                return 0
            except (OSError, IndexError, ValueError):
                pass
            return -1

        return 0

    def _swap_create_file(self, swap_size_mb):
        # type: (int) -> None
        """创建并激活 swap 文件, 持久化到 /etc/fstab。

        失败时清理残留并抛出 RuntimeError。
        """
        swap_file = Path("/swapfile")

        if swap_file.exists():
            # 可能是之前创建的未激活 swap
            try:
                r = subprocess.run(
                    ["swapon", str(swap_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=10, check=False,
                )
                if r.returncode == 0:
                    logging.info(t("info_swap_created",
                                   path=swap_file, size=swap_size_mb))
                    return
            except Exception:
                pass
            # swapon 失败 — 删掉重建
            swap_file.unlink()

        # 创建 swap 文件
        # [V3.0.17] B3: btrfs 强制要求 swap 文件具有 nocow（non-COW）属性。
        # chattr +C 只能对空文件（尚未写入数据的文件）生效，必须在 dd 之前执行。
        _fs_type = self._get_fs_type(swap_file.parent)
        if _fs_type == "btrfs":
            # 先建空文件 → chattr +C 禁用 COW → 再 dd 写零
            # [V3.2.17] P2-2: Path.touch() 默认 exist_ok=True,
            # 不会抛 FileExistsError, 移除死代码
            swap_file.touch(mode=0o600)
            _chattr_result = self.run_cmd(
                ["chattr", "+C", str(swap_file)], quiet=True
            )
            if not _chattr_result:
                # chattr +C 失败：btrfs swap 文件缺少 nocow 属性，
                # swapon 可能随后报错 "swapfile has holes"，提前告警。
                logging.warning(
                    "P6: chattr +C %s failed "
                    "(btrfs nocow attribute not set); "
                    "swapon may fail — check kernel/btrfs version.",
                    swap_file,
                )
        dd_result = self.run_cmd(
            ["dd", "if=/dev/zero", "of=%s" % swap_file,
             "bs=1M", "count=%d" % swap_size_mb, "status=none"],
            timeout=120, quiet=True,
        )
        if not dd_result:
            raise RuntimeError("dd failed to create swapfile")

        os.chmod(str(swap_file), 0o600)

        mkswap_result = self.run_cmd(
            ["mkswap", str(swap_file)], timeout=30, quiet=True,
        )
        if not mkswap_result:
            raise RuntimeError("mkswap failed")

        swapon_result = self.run_cmd(
            ["swapon", str(swap_file)], timeout=10, quiet=True,
        )
        if not swapon_result:
            raise RuntimeError("swapon failed")

        # [V3.2.2] M-2: 原子追加, 防断电写入不完整行
        # [V3.2.28] BUG-II: 将 fstab 读写纳入独立 try/except。
        # 原代码中 fstab.read_text() 若抛 OSError 将被外层
        # except Exception 捕获，进而 swapoff + unlink 已激活的 swap，
        # 并误报 "swap creation failed"。现在 fstab 操作失败仅记录
        # 警告（swap 已激活，只是重启后不自动挂载），不影响当次运行。
        fstab = Path("/etc/fstab")
        try:
            fstab_content = fstab.read_text(encoding="utf-8")
            # [V3.2.21-AUDIT] P1-2: 行首精确匹配，排除注释行和子路径
            if not re.search(r'^\s*/swapfile\s', fstab_content, re.MULTILINE):
                _new_fstab = fstab_content.rstrip("\n") + "\n/swapfile none swap sw 0 0\n"
                self._safe_write_file(fstab, _new_fstab, mode=0o644)
        except OSError as _fstab_e:
            logging.warning(
                "swap: /etc/fstab update failed (%s); "
                "swapfile is active but will not persist after reboot.",
                _fstab_e,
            )

        # 调优 swappiness (小内存服务器适合保守值)
        self.run_cmd(
            ["sysctl", "-w", "vm.swappiness=10"], quiet=True,
        )
        # [V3.2.2] M-1: 原子写入, 防断电截断 sysctl drop-in
        sysctl_conf = Path("/etc/sysctl.d/99-wp-bootstrap-swap.conf")
        try:
            self._safe_write_file(
                sysctl_conf,
                "# [V3.0.16] WP-SSL-Bootstrap swap tuning\n"
                "vm.swappiness = 10\n",
                mode=0o644,
            )
        except OSError:
            pass

        logging.info(t("info_swap_created",
                       path=swap_file, size=swap_size_mb))

    def _ensure_swap(self) -> None:
        """检测系统 swap, ≤ 2GB RAM 且无 swap 时自动创建 swapfile。

        策略 (借鉴 SlickStack / Webinoly):
          RAM ≤ 1GB  → swap = 1GB
          RAM ≤ 2GB  → swap = 2GB
          RAM > 2GB  → 跳过 (通常不需要)

        创建流程: fallocate → chmod 600 → mkswap → swapon → /etc/fstab 持久化。
        失败不阻断部署 (仅警告)。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_swap"))
            return

        # [V3.2.0] R1: 容器环境无权创建 swap, 提前跳过
        _in_container = (
            Path("/.dockerenv").exists()
            or Path("/run/.containerenv").exists()
            or os.environ.get("container", "") != ""
        )
        if not _in_container:
            try:
                with open("/proc/1/cgroup", encoding="utf-8") as _cg:
                    _cg_text = _cg.read()
                    if any(k in _cg_text for k in (
                        "/docker/", "/lxc/", "/kubepods",
                    )):
                        _in_container = True
            except OSError:
                pass
        if _in_container:
            logging.info(
                "Container environment detected; skipping swap creation."
            )
            return

        total_mb = self._get_total_ram_mb()
        if total_mb <= 0:
            return

        if total_mb > 2048:
            logging.info(t("info_swap_skip_enough_ram", ram=total_mb))
            return

        # [V3.2.35] 拆分: 检测已有 swap
        _existing_mb = self._swap_detect_existing()
        if _existing_mb > 0:
            logging.info(t("info_swap_exists", mb=_existing_mb))
            return

        swap_size_mb = 1024 if total_mb <= 1024 else 2048
        swap_file = Path("/swapfile")

        logging.info(t("info_swap_creating", ram=total_mb, size=swap_size_mb))

        try:
            # [V3.2.35] 拆分: 创建 swap 文件
            self._swap_create_file(swap_size_mb)
        except Exception as e:
            logging.warning(t("warn_swap_fail", e=e))
            # 清理可能的残留
            if swap_file.exists():
                try:
                    self.run_cmd(["swapoff", str(swap_file)], quiet=True)
                    swap_file.unlink()
                except Exception:
                    pass



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
        # [V3.2.36-P3] 兼容 Python 3.6 早期补丁版本
        try:
            sig_name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            sig_name = "SIG%d" % signum
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
            self.global_lock_fd = open(self._GLOBAL_LOCK_FILE, 'w', encoding='utf-8')  # [V3.2.44] REF-1
            fcntl.flock(self.global_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.error(t("err_lock_global"))
            sys.exit(1)

        try:
            self.lock_fd = open(self.cfg.lock_file, 'w', encoding='utf-8')
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()
        except BlockingIOError:
            # 锁被占用——检查持有者进程是否仍在运行 (SIGKILL 残留检测)
            stale = False
            try:
                with open(self.cfg.lock_file, 'r', encoding='utf-8') as f:
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
                    self.lock_fd = open(self.cfg.lock_file, 'w', encoding='utf-8')
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.lock_fd.write(str(os.getpid()))
                    self.lock_fd.flush()
                    return
                except BlockingIOError:
                    pass  # 仍然失败，走下面的错误退出
            logging.error(t("err_lock_domain", domain=self.cfg.domain))
            # [V3.0.15] B4: per-domain 锁获取失败时显式释放已持有的全局锁，
            # 避免 sys.exit() 依赖内核隐式释放，保持资源清理的显式性。
            # [V3.2.23] self-1: stale 重试路径下 open() 可能已成功但 flock() 失败，
            # self.lock_fd 持有未加锁的悬挂句柄；在退出前显式关闭以保持与
            # global_lock_fd 一致的资源清理风格。
            try:
                if self.lock_fd:
                    self.lock_fd.close()
                    self.lock_fd = None
            except OSError:
                pass
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
                sensitive: bool = False, stream: bool = False) -> CmdResult:
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
            # [PATCH-STREAM] stream 模式: stdout 直接到终端显示实时进度,
            # stderr 仍捕获以保留错误分类能力 (dnf/apt 进度条走 stdout)。
            if stream:
                r = subprocess.run(
                    cmd_list,
                    stdout=None,             # 继承终端 → 用户看到实时进度
                    stderr=subprocess.PIPE,  # 仍捕获 → 错误分类不丢失
                    encoding='utf-8', errors='replace',
                    timeout=timeout, check=False,
                )
                if r.returncode == 0:
                    return CmdResult.success()
                stderr_text = (r.stderr or "").strip()
                error_code = CmdResult.classify_stderr(stderr_text)
                if not quiet:
                    logging.error(t("err_cmd_failed", cmd=cmd_list[0], code=error_code, stderr=stderr_text))
                return CmdResult(ok=False, code=error_code, stderr=stderr_text)
            r = subprocess.run(
                cmd_list,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace',  # [V3.2.43] FIX-8: drop redundant universal_newlines (encoding= implies text mode in Py3.6+)
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
        _tmp_dir = Path(self._MYSQL_TMP_DIR)  # [V3.2.44] REF-2
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
            # [V3.2.11] P2-14: 安全假设说明 —
            #   密码白名单含 '!' 字符，MySQL .cnf 在某些版本将 !include 解释为
            #   include 指令。但 MySQL 官方文档明确：双引号包裹的 password 值内
            #   '!' 不会被解释为指令（仅行首未引用的 !include 才生效）。
            #   转义方案：\ → \\ ，" → \"；单引号和 ! 无需额外转义。
            _esc_pw = password.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))
            cnf_lines = f'[client]\npassword="{_esc_pw}"\n'
            # [V3.2.21-AUDIT] P2-5: 可控的外置数据库 SSL
            # db_ssl=None (auto): 外置 DB 默认启用 SSL
            # db_ssl=False (--no-db-ssl): 内网直连等场景禁用 SSL
            if self.cfg.is_external_db and self.cfg.db_ssl is not False:
                cnf_lines += "ssl\n"
            os.write(fd, cnf_lines.encode('utf-8'))
            # [V3.2.70] BUG-4: 补充 os.fsync(fd)，确保密码文件内容落盘后再关闭。
            # _safe_write_file() 和 atomic_write() 均有 fsync；此处遗漏在高负载
            # 系统（aggressive write-back cache）上可能导致 mysql 读到空文件。
            os.fsync(fd)
        except Exception:
            # [V3.2.27] BUG-2/BUG-8: 控制字符校验或 os.write 抛异常时，
            # 在关闭 fd 后立即删除含密码的临时文件，防止敏感信息泄露。
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        else:
            os.close(fd)
        # [V3.2.27] BUG-2/BUG-8: os.chmod 纳入 try 保护范围；
        # chmod 失败时同样删除临时文件并向上抛异常。
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def _mysql_escape_value(value: str) -> str:
        """转义 SQL 单引号字符串字面量中的危险字符。

        [PATCH-H2] 增加防御性白名单校验，防止未经校验的直接调用导致 SQL 注入。
        auto-generated passwords use [a-zA-Z0-9];
        user-supplied values must pass [a-zA-Z0-9!@#$%^&*()_+=.-]+ whitelist.

        [V3.2.34] P-9: 设计说明 — 白名单不含 \\ 和 ' , 因此下方的
        replace() 在正常输入下永远不会触发 (effective no-op)。这是刻意的
        纵深防御: 若未来白名单意外扩大或上层校验被绕过, 此处仍能正确转义,
        防止 SQL 注入。不要因为 "当前不触发" 就移除这些 replace()。
        """
        # [V3.2.10] L-2: 移除幽灵 import re as _re，模块顶层已有 import re
        # [V3.2.9] M-2: \ 不在白名单内，与上层调用方检验保持一致，补齐防御纵深。
        # [V3.2.24] sync-whitelist: 移除 \\^ (\\^ 原意转义^，但 \\ 意外将反斜杠纳入白名单)
        #   和 \\- (raw 字符串中无效转义序列，触发 SyntaxWarning)；与上游 5 处校验对齐。
        if not re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', value):  # [V3.2.24] sync-whitelist: rm accidental \\ (backslash) + fix \- SyntaxWarning
            raise ValueError(
                "_mysql_escape_value: input contains characters "
                "outside the safe whitelist"
            )
        for ch in value:
            if ord(ch) < 32:
                raise ValueError(t("err_escape_control_char"))
        return value.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))

    @staticmethod
    def _safe_write_file(path, content: str, mode: int = 0o600) -> bool:
        """原子写入文件，从创建瞬间即为 mode 权限。

        解决 write_text() + chmod() 之间的窗口期问题：
        在窗口期内文件以默认 umask 权限存在，可能被同机用户读取。

        [V3.2.11] P1-7: 与 atomic_write() 的职责分工：
          - _safe_write_file : 轻量接口，无备份/回滚，用于 Nginx/systemd 等配置文件
          - atomic_write     : 带 .aw_bak 备份 + 原权限保留，用于用户数据文件
        两者均通过 os.open(O_CREAT|O_WRONLY|O_TRUNC, mode) 保证权限从零秒生效。
        建议：若需要备份语义，优先使用 atomic_write()。

        流程：open(O_CREAT|O_WRONLY, mode) → write → fsync → rename
        """
        target = Path(path)  # [V3.0.2] B3: 模块顶层已导入
        tmp_path = target.with_name(target.name + '.sf_tmp')
        # [V3.2.20] P0: 捕获原文件属主, replace 后恢复,
        # 防止 wp-config.php 属主被重置为 root:root 导致 PHP-FPM 500
        _orig_uid = -1
        _orig_gid = -1
        if target.exists():
            try:
                _orig_st = target.stat()
                _orig_uid = _orig_st.st_uid
                _orig_gid = _orig_st.st_gid
            except OSError:
                pass
        try:
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
            try:
                os.write(fd, content.encode('utf-8'))
                os.fsync(fd)
            finally:
                os.close(fd)
            # [V3.2.21-AUDIT] P2-4: 先 chown tmp 再 replace，
            # 彻底消除 os.replace→os.chown 之间的属主竞态窗口。
            # [V3.2.34] P-7: 仅当原文件属主与当前进程不同时才 chown,
            # 避免 root→root 的冗余 syscall, 并兼容 grsec 内核限制。
            if _orig_uid >= 0 and _orig_gid >= 0:
                _cur_uid, _cur_gid = os.getuid(), os.getgid()
                if _orig_uid != _cur_uid or _orig_gid != _cur_gid:
                    try:
                        os.chown(str(tmp_path), _orig_uid, _orig_gid)
                    except OSError as _chown_e:
                        logging.debug(
                            "_safe_write_file: chown(%s, %d, %d) failed: %s",
                            tmp_path, _orig_uid, _orig_gid, _chown_e,
                        )
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
                encoding='utf-8', errors='replace',  # [V3.2.44] FIX-10: drop redundant universal_newlines (encoding= implies text mode, mirrors FIX-8)
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
    def atomic_write(self, target_path: Path, content: str, mode=None) -> bool:  # [PATCH-L2]
        """原子写入文件。

        Args:
            target_path: 目标文件路径。
            content:     写入内容（UTF-8 字符串）。
            mode:        文件权限（八进制整数，如 0o600）。
                         **仅对新建文件生效**；若目标文件已存在，
                         写入后权限保持原文件不变（设计意图：保护凭据文件权限）。
                         若调用方需要修改已有文件权限，请在本函数返回后
                         手动调用 os.chmod()。  [V3.2.8] L-4
        Returns:
            True  写入成功；False 写入失败（已尝试从 .aw_bak 回滚）。
        """
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
            # [V3.2.9] L-1: os.open 显式指定 0o600 创建临时文件，
            # 消除 Path.write_text() 依赖 umask 造成的权限微窗口期。
            _aw_tmp_fd = os.open(
                str(tmp_path),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            try:
                os.write(_aw_tmp_fd, content.encode('utf-8'))
                # [V3.2.27] BUG-1: 在关闭 fd 之前直接 fsync，与 _safe_write_file
                # 的既有实现保持一致，消除关闭后重新以 O_RDONLY 打开的非标准用法
                # 及其引入的时间窗口。fsync 失败降级处理，保持旧版行为。
                try:
                    os.fsync(_aw_tmp_fd)
                except OSError:
                    pass  # 降级: fsync 失败不阻断, 保持旧版行为
            finally:
                os.close(_aw_tmp_fd)
            # [V3.2.5] A-5: 新建文件时显式设置权限, 不依赖 umask
            if not target_path.exists() and mode is not None:  # [PATCH-L2] 允许 mode=0
                try:
                    os.chmod(str(tmp_path), mode)
                except OSError:
                    pass
            # V2.7.2: 保留原文件权限（如 0600 凭据文件）
            if target_path.exists():
                try:
                    _orig_st = target_path.stat()
                    # [V3.2.42] FIX-5: chown 必须在 chmod 之前执行。
                    # 在非 root 进程中，chown 会清除 setuid/setgid 位；
                    # 若先 chmod 再 chown，setuid/setgid 将被静默清除。
                    # 本脚本虽以 root 运行（chown 不清位），但遵循正确顺序
                    # 以保证语义健壮，防止未来被非 root 上下文复用时出错。
                    os.chown(str(tmp_path), _orig_st.st_uid, _orig_st.st_gid)
                    os.chmod(str(tmp_path), stat.S_IMODE(_orig_st.st_mode))
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
    # [V3.0.16] P8: nginx reload 统一门控
    # -----------------------------------------------------------------------
    def _safe_reload_nginx(self) -> bool:
        """nginx -t 通过后才执行 reload, 防止配置错误导致服务宕机。

        所有非 apply_nginx_config_safe 路径的 reload 统一调用此方法。
        """
        if self.cfg.dry_run:
            return True
        if self.run_cmd(["nginx", "-t"], quiet=True):
            return bool(self.run_cmd(["systemctl", "reload", "nginx"], quiet=True))
        logging.warning(t("warn_nginx_reload_test_fail"))
        return False

    # -----------------------------------------------------------------------
    # [V3.1.1] Issue 1: Certbot persistent deploy hook
    # -----------------------------------------------------------------------
    def _install_certbot_deploy_hook(self) -> None:
        """Install a persistent deploy hook for certbot renewal.

        Writes /etc/letsencrypt/renewal-hooks/deploy/01-reload-nginx.sh
        with absolute paths for nginx and systemctl.  This ensures Nginx
        reload works regardless of snap confinement, PATH limitations,
        or whether renewal is triggered by the script timer or certbot's
        own timer.
        """
        if self.cfg.dry_run:
            return
        hook_dir = Path("/etc/letsencrypt/renewal-hooks/deploy")
        try:
            hook_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        hook_file = hook_dir / "01-reload-nginx.sh"
        # [V3.1.1] P1: runtime-detected paths
        _nginx = self.cfg.nginx_bin
        _systemctl = self.cfg.systemctl_bin
        content = (
            "#!/bin/sh\n"
            "# [V3.1.1] Auto-generated by WP-SSL-Bootstrap\n"
            f"{_nginx} -t 2>/dev/null && "
            f"{_systemctl} reload nginx\n"
        )
        if self._safe_write_file(hook_file, content, mode=0o755):
            logging.info(t("info_certbot_deploy_hook", path=hook_file))

    # -----------------------------------------------------------------------
    # Nginx 配置安全应用
    # -----------------------------------------------------------------------
    def apply_nginx_config_safe(self, config_str: str) -> bool:
        if self.cfg.dry_run: return True
        bak_path = self.cfg.nginx_conf.with_suffix('.bak')
        tmp_path = self.cfg.nginx_conf.with_suffix('.pending')
        lock_path = Path(self._NGINX_CONF_LOCK_FILE)  # [V3.2.44] REF-1
        try:
            with open(lock_path, 'w', encoding='utf-8') as f_lock:
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
                    # [V3.2.26] BUG-C: 原 write_text() 依赖 umask 权限且缺少 fsync。
                    # 改用 os.open 指定精确权限，写入后 fsync 确保落盘，
                    # 再 os.replace 原子替换，消除权限窗口期与断电数据丢失风险。
                    # [V3.2.27] BUG-6: 改为 0o644，与 /etc/nginx/conf.d/ 标准惯例
                    # 及同文件其余 _safe_write_file(nginx_conf, mode=0o644) 保持一致。
                    # nginx 主进程以 root 身份读取配置，0o644 足以满足权限要求。
                    _enc = config_str.encode('utf-8')
                    _pending_fd = os.open(
                        str(tmp_path),
                        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                        0o644,
                    )
                    try:
                        os.write(_pending_fd, _enc)
                        os.fsync(_pending_fd)
                    finally:
                        os.close(_pending_fd)
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
                # [V3.2.37] P-3: 成功路径清理 .bak 残留, 防止长期运行积累垃圾文件
                try:
                    if bak_path.exists():
                        bak_path.unlink()
                except OSError:
                    pass
                return True
        finally:
            # [V3.0.4] 用 debug 替代 pass：只读挂载点等极端故障下保留可追溯日志
            try:
                tmp_path.unlink()
            except OSError as _e:
                logging.debug(t("debug_nginx_pending_cleanup"), _e)  # [V3.2.23] P1-3: lazy-arg fmt
            # [V3.2.26] BUG-D: 确保锁文件在函数退出时被删除，防止异常路径残留
            # 导致下次运行时 fcntl.flock 虽可正常获取锁，但遗留文件使运维人员困惑
            try:
                lock_path.unlink()
            except OSError:
                pass  # 文件已被其他进程删除或从未创建，可忽略

    # -----------------------------------------------------------------------
    # 软件包安装
    # -----------------------------------------------------------------------
    def install_packages(self) -> bool:
        pkgs = ["nginx", "certbot", "wget", "curl", "tar"]
        if self.pkg_mgr in ("dnf", "yum"):
            _epel_check = subprocess.run(
                [self.pkg_mgr, "repolist", "enabled"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace',  # [V3.2.45] BUG-C: consistent with FIX-8 series
                timeout=30, check=False,
            )
            if "epel" not in _epel_check.stdout.lower():
                self.run_cmd([self.pkg_mgr, "install", "-y", "epel-release"], quiet=True)
            # [FIX-C1] php-json 在 PHP 8.0+ 已合并入 php-common，
            # EL9/EL10 默认 PHP 8.x，安装不存在的 php-json 导致 dnf 整条失败。
            # 改为运行时检测: PHP < 8.0 才追加 php-json。
            pkgs.extend([
                "php", "php-fpm", "php-mysqlnd", "php-gd",
                "php-mbstring", "php-xml",
                # [V2.9.4] S3: WordPress 官方推荐扩展
                # php-curl: 远程 HTTP 请求（插件更新、REST API）
                # php-zip:  插件/主题/WordPress 核心更新包解压
                # php-intl: 多语言 locale 处理（WPML 等插件依赖）
                # php-opcache: 字节码缓存，显著提升 PHP 执行速度
                "php-curl", "php-zip", "php-intl", "php-opcache",
            ])
            # [FIX-C10] php-json: PHP 8.0+ 已内置, EL10 默认 PHP 8.x 无此包。
            # Fresh install 时 php 二进制不存在, 检测失败不应默认追加,
            # 否则在 dnf5 (无 --skip-unavailable) 下导致整条安装失败。
            # 改为: 仅当 PHP < 8 确认存在时才追加; 其他情况(含检测失败)跳过。
            _need_php_json = False  # 默认不需要 (EL10/PHP8+ 安全默认)
            try:
                _pv = subprocess.run(
                    ["php", "-r", "echo PHP_MAJOR_VERSION;"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                if _pv.returncode == 0 and _pv.stdout.strip().isdigit():
                    if int(_pv.stdout.strip()) < 8:
                        _need_php_json = True
            except Exception:
                pass  # php 不存在 → 即将安装的版本大概率 >= 8, 不追加
            if _need_php_json:
                pkgs.append("php-json")
            # 外置数据库：只需客户端工具（mariadb），无需安装服务端（mariadb-server）
            pkgs.append("mariadb" if self.cfg.is_external_db else "mariadb-server")
            # [FIX-EL10] Redis 从主包列表分离, 单独安装
            # if self.cfg.redis_cache: pkgs.append("redis")  # 已移至下方独立安装
            # quiet=False: 包安装失败时需要日志排查
            # [V3.2.0] 失败后自动诊断并尝试修复
            # [FIX-C9] dnf5 (EL10+) 不支持 --skip-unavailable,
            # 检测 dnf 版本避免无意义报错噪音。
            # dnf4 (EL8/9): 支持 --skip-unavailable
            # dnf5 (EL10+): 不支持, 直接用标准 install
            # yum (EL7):    走 else 分支标准安装
            _install_ok = False
            # [V3.2.59] BUG-6: 使用 __init__ 时已初始化的实例属性，消除重复检测
            _is_dnf5 = self._is_dnf5
            if self.pkg_mgr == "dnf" and not _is_dnf5:
                _install_ok = bool(self.run_cmd(
                    ["dnf", "install", "-y", "--skip-unavailable"] + pkgs,
                    quiet=False, stream=True, timeout=600,
                ))
            if not _install_ok:
                _install_ok = bool(self.run_cmd(
                    [self.pkg_mgr, "install", "-y"] + pkgs,
                    quiet=False, stream=True, timeout=600,
                ))
            if not _install_ok:
                if not self._diagnose_pkg_failure(pkgs):
                    return False
            # [FIX-EL10] Redis 独立安装 — 失败不阻断部署
            # EL10 (Rocky/Alma 10) EPEL 可能无 redis, RHEL 10+ 推 valkey 替代
            if self.cfg.redis_cache:
                _redis_installed = False
                # 候选包名: redis (EL7-9 EPEL), valkey (EL10+), redis7 (Remi)
                for _rpkg in ("redis", "valkey", "redis7", "redis6"):
                    if self.run_cmd(
                        [self.pkg_mgr, "install", "-y", _rpkg],
                        quiet=True, timeout=120,
                    ):
                        _redis_installed = True
                        logging.info("[FIX-EL10] Redis service installed: %s", _rpkg)
                        break
                if not _redis_installed:
                    # 尝试 Remi 源
                    logging.warning(
                        "[FIX-EL10] Redis not in default repos; trying Remi..."
                    )
                    _el_ver = "10"
                    try:
                        _osr = Path("/etc/os-release").read_text(encoding="utf-8")
                        _vm = re.search(r'VERSION_ID="?(\d+)', _osr)
                        if _vm:
                            _el_ver = _vm.group(1)
                    except OSError:
                        pass
                    self.run_cmd(
                        [self.pkg_mgr, "install", "-y",
                         "https://rpms.remirepo.net/enterprise/remi-release-%s.rpm" % _el_ver],
                        quiet=True, timeout=120,
                    )
                    for _rpkg in ("redis", "redis7", "valkey"):
                        if self.run_cmd(
                            [self.pkg_mgr, "install", "-y", _rpkg],
                            quiet=True, timeout=120,
                        ):
                            _redis_installed = True
                            logging.info("[FIX-EL10] Redis via Remi: %s", _rpkg)
                            break
                if not _redis_installed:
                    logging.warning(
                        "Redis 安装失败，部署将继续（不含 Redis 缓存）。"
                        "\n    手动安装后执行: python3 %s update --domain %s --redis",
                        self.cfg.script_path, self.cfg.domain,
                    )
                    self.cfg.redis_cache = False

            # [V3.2.0] PHP Redis: 先尝试预编译包, PECL 作最终兜底
            # [V3.2.0] 委托 _compile_php_redis_extension() 共享编译基础设施
            # [FIX-EL10] 仅当 Redis 服务安装成功时才装 PHP 扩展
            if self.cfg.redis_cache:
                _redis_prebuilt = False
                for _rpkg in ("php-pecl-redis6", "php-pecl-redis5",
                              "php-pecl-redis", "php-redis"):
                    if self.run_cmd(
                        [self.pkg_mgr, "install", "-y", _rpkg],
                        quiet=True, timeout=60,
                    ):
                        logging.info(t("ok_php_redis_pecl"))
                        _redis_prebuilt = True
                        break
                if not _redis_prebuilt:
                    self._compile_php_redis_extension()
            return True
        elif self.pkg_mgr == "apt":
            self.run_cmd(["apt", "update"], quiet=True)
            # [FIX-C8] php-json 在 PHP 8.0+ 已合并, Ubuntu 22.04+ 无需
            _apt_php_pkgs = [
                "php-fpm", "php-mysql", "php-gd",
                "php-mbstring", "php-xml",
                # [V2.9.4] S3: WordPress 官方推荐扩展（与 dnf/yum 列表一致）
                "php-curl", "php-zip", "php-intl", "php-opcache",
            ]
            pkgs.extend(_apt_php_pkgs)
            # [FIX-C10] php-json: 仅 PHP < 8 需要; 检测失败时不追加
            # (apt 下安装不存在的包会报错但不致命, 仍改为保守跳过)
            try:
                _pv_apt = subprocess.run(
                    ["php", "-r", "echo PHP_MAJOR_VERSION;"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                if _pv_apt.returncode == 0 and _pv_apt.stdout.strip().isdigit():
                    if int(_pv_apt.stdout.strip()) < 8:
                        pkgs.append("php-json")
            except Exception:
                pass  # [FIX-C10] php 不存在 → 新安装大概率 >= 8, 跳过
            # 外置数据库：只需客户端工具（mariadb-client），无需安装服务端（mariadb-server）
            pkgs.append("mariadb-client" if self.cfg.is_external_db else "mariadb-server")
            if self.cfg.redis_cache:  # [V2.9.8]
                pkgs.extend(["redis-server", "php-redis"])
            # [V3.2.0] 失败后自动诊断并尝试修复
            if not self.run_cmd(["apt", "install", "-y"] + pkgs, quiet=False, stream=True):  # [PATCH-STREAM]
                return self._diagnose_pkg_failure(pkgs)
            return True
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
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5,  # [V3.1.0 M3]
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
                        encoding='utf-8', errors='replace',  # [V3.2.45] BUG-A: mirrors FIX-8/FIX-10/FIX-11; non-UTF-8 locale safe
                        timeout=5, check=False,
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
                    encoding='utf-8', errors='replace',  # [V3.2.44] FIX-11: drop redundant universal_newlines (mirrors FIX-8/FIX-10)
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
                _file_pwd = self.global_root_pwd_file.read_text(encoding="utf-8").strip()
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
                encoding='utf-8', errors='replace',  # [V3.2.45] BUG-B: MariaDB error messages may contain non-ASCII bytes
                check=False, timeout=15,
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
            # [V3.2.36-P1] 添加 re.DOTALL: 防止 DB_PASSWORD 值跨行时匹配失败
            m = re.search(
                r"define\(\s*'DB_PASSWORD'\s*,\s*'((?:[^'\\]|\\.)*)'\s*\);", content,
                re.DOTALL,
            )
            if m and m.group(1):
                # 反转义 PHP 字符串：\\' → ' , \\\\ → \\
                recovered_pwd = m.group(1).replace(
                    chr(92) + chr(92), chr(92)         # \\\\ → \\ (must be first)
                ).replace(
                    chr(92) + chr(39), chr(39)         # \' → '  (must be second)
                )
                # 与 SiteConfig.validate_sql_password 保持一致的安全校验：
                # 只接受纯字母数字，拒绝任何可能引起 .cnf 或 SQL 转义问题的字符
                # [V3.2.5] A-7: 扩展白名单至与 --db-root-pass 一致,
                # 接受运维人员手动设置的含特殊字符的强密码
                if re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', recovered_pwd):
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
            # [V3.2.27] BUG-4: 对相对路径候选项（如 "wp"），若 shutil.which 返回
            # None，则跳过；不使用原始字符串回退，避免 os.path.isfile("wp") 意外
            # 匹配 CWD 下同名文件导致行为不可预期。
            _resolved = shutil.which(candidate)
            if _resolved is None:
                if not os.path.isabs(candidate):
                    continue  # 相对路径且 which 找不到，跳过
                path = candidate  # 绝对路径直接使用
            else:
                path = _resolved
            if os.path.isfile(path) and os.access(path, os.X_OK):
                try:
                    # [V3.2.0] W3: 脚本以 root 运行, 必须带 --allow-root
                    r = subprocess.run(
                        [path, "--allow-root", "--version"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding='utf-8', errors='replace', timeout=10, check=False,
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

        # [V3.2.0] F1: 非国内环境反转镜像列表, GitHub 官方优先
        # 避免非国内服务器连接中国代理镜像逐个超时 (每个 8s)
        _mirrors = list(self.WPCLI_MIRRORS)
        if not _is_china_cloud():
            _mirrors = list(reversed(_mirrors))

        fd_phar, phar_tmp = tempfile.mkstemp(prefix="wp_cli_", suffix=".phar")
        os.fchmod(fd_phar, stat.S_IRUSR | stat.S_IWUSR)  # 0600 防止共享主机竞态读取
        os.close(fd_phar)
        fd_hash, hash_tmp = tempfile.mkstemp(prefix="wp_cli_hash_", suffix=".sha512")
        os.fchmod(fd_hash, stat.S_IRUSR | stat.S_IWUSR)
        os.close(fd_hash)

        def _dl_cmd(dest: str, url: str) -> list:
            if shutil.which("curl"):
                return ["curl", "-sSL", "--connect-timeout", "8", "-o", dest, url]
            return ["wget", "-q", "-O", dest, "--connect-timeout=8", "--read-timeout=60", url]

        try:
            for mirror in _mirrors:
                mirror_name = mirror["name"]
                logging.info(t("info_wpcli_mirror_try", mirror=mirror_name))

                # 下载 phar
                if not self.run_cmd(_dl_cmd(phar_tmp, mirror["phar"]), timeout=60, quiet=True):
                    logging.warning(t("warn_wpcli_phar_fail", mirror=mirror_name))
                    continue

                # 下载 hash（与 phar 来自同一镜像，保证一致性）
                if not self.run_cmd(_dl_cmd(hash_tmp, mirror["hash"]), timeout=30, quiet=True):
                    logging.warning(t("warn_wpcli_hash_fail", mirror=mirror_name))
                    continue

                # SHA-512 校验
                try:
                    expected_hash = Path(hash_tmp).read_text(encoding="utf-8").strip().split()[0]
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
                    # [V3.2.0] W2: 脚本以 root 运行, 必须带 --allow-root
                    r = subprocess.run(
                        [install_path, "--allow-root", "--version"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding='utf-8', errors='replace', timeout=10, check=False,
                    )
                    if r.returncode == 0 and "WP-CLI" in r.stdout:
                        self._wpcli_bin = install_path
                        logging.info(t("ok_wpcli_install_src", src=mirror_name, ver=r.stdout.strip()))
                        return install_path
                    # [V3.2.0] W1: 记录验证失败的诊断信息
                    logging.warning(
                        "  [%s] wp --version failed: rc=%d, "
                        "stdout=%s, stderr=%s",
                        mirror_name, r.returncode,
                        r.stdout.strip()[:100] or "(empty)",
                        r.stderr.strip()[:200] or "(empty)",
                    )
                except Exception as _wv_e:
                    # [V3.2.0] W1: 记录验证异常信息
                    logging.warning(
                        "  [%s] wp --version exception: %s",
                        mirror_name, _wv_e,
                    )
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
        返回路径或空字符串（调用方需处理不可用情况）。
        [V3.2.5] A-13: 缓存安装失败结果, 避免同一次部署中重复探测。
        """
        path = self._detect_wpcli()
        if path:
            return path
        if self._wpcli_install_attempted:
            return ""
        self._wpcli_install_attempted = True
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
        # [V3.2.0] P1: WordPress 未安装时跳过, 避免 "site not installed" 错误
        if not self._wpcli_check_installed():
            logging.warning(t("warn_plugin_wp_not_installed",
                              domain=self.cfg.domain))
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
            # [V3.2.16] P0-1: 使用 _nginx_safe_name 而非 systemd_prefix,
            # 与 generate_https_config / generate_http_production_config
            # 中 fastcgi_cache_path 的 keys_zone 名称保持一致。
            safe_name = _nginx_safe_name(self.cfg.domain)
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


    @staticmethod
    def _fetch_wp_latest_version() -> str:
        """从 WordPress 官方全球 API 获取最新版本号。
        返回版本字符串 (如 '6.9.4')，失败返回空字符串。

        [V3.2.14] P2-1: 使用类级锁保护缓存读写。
        [V3.2.41] FIX-1: 仅查询全球主站 API，不再混查 cn API。
        zh_CN 版本号由 _fetch_wp_zh_version() 独立维护，两者可能不同步
        (例如全球 6.9.4 而中文站仅 6.9.3)。
        """
        # 无锁快速路径（GIL 保护读）
        if WPDeployManager._wp_latest_version_cache:
            return WPDeployManager._wp_latest_version_cache
        import urllib.request
        # [V3.2.39] P4: 锁内仅做缓存读写, 网络 I/O 移至锁外
        with WPDeployManager._wp_ver_cache_lock:
            if WPDeployManager._wp_latest_version_cache:
                return WPDeployManager._wp_latest_version_cache
        # ── 锁外执行网络 I/O ──
        _fetched_ver = ""
        try:
            import urllib.request as _ur
            req = _ur.Request(
                "https://api.wordpress.org/core/version-check/1.7/",
                headers={"User-Agent": "wp-ssl-bootstrap"},
            )
            with _ur.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read(512 * 1024).decode("utf-8"))
                offers = data.get("offers", [])
                if offers:
                    ver = offers[0].get("version", "").strip()
                    if ver and re.match(r'^\d+\.\d+(\.\d+)?$', ver):
                        _fetched_ver = ver
        except Exception:
            pass
        if _fetched_ver:
            with WPDeployManager._wp_ver_cache_lock:
                if not WPDeployManager._wp_latest_version_cache:
                    WPDeployManager._wp_latest_version_cache = _fetched_ver
            return _fetched_ver
        return WPDeployManager._wp_latest_version_cache or ""

    def _fetch_wp_zh_version(self) -> str:
        """[FIX-1] 从 cn.wordpress.org API 独立获取 zh_CN 最新版本号。

        cn.wordpress.org 的发布节奏落后于全球主站：全球已发 6.9.4 时，
        中文站可能仍停留在 6.9.3。若用全球版本号拼接 zh_CN 下载 URL，
        会导致 SHA1 校验失败并意外回退到英文包。

        本方法单独缓存 zh_CN 版本，供 _build_wp_download_sources() 使用，
        确保 zh_CN URL 始终对应中文站实际存在的版本。
        失败时回退至全球版本号（_fetch_wp_latest_version()）。
        """
        # 无锁快速路径（GIL 保护读）
        if WPDeployManager._wp_zh_version_cache:
            return WPDeployManager._wp_zh_version_cache
        # [V3.2.42] FIX-4: 锁内二次校验，与 _fetch_wp_latest_version 保持对称，
        # 防止多线程并发时重复触发对 cn.wordpress.org 的 HTTP 请求。
        with WPDeployManager._wp_ver_cache_lock:
            if WPDeployManager._wp_zh_version_cache:
                return WPDeployManager._wp_zh_version_cache
        # ── 锁外执行网络 I/O ──
        import urllib.request as _ur
        _fetched_ver = ""
        try:
            req = _ur.Request(
                "https://cn.wordpress.org/core/version-check/1.7/",
                headers={"User-Agent": "wp-ssl-bootstrap"},
            )
            with _ur.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read(512 * 1024).decode("utf-8"))
                offers = data.get("offers", [])
                if offers:
                    ver = offers[0].get("version", "").strip()
                    if ver and re.match(r'^\d+\.\d+(\.\d+)?$', ver):
                        _fetched_ver = ver
        except Exception:
            pass
        if _fetched_ver:
            with WPDeployManager._wp_ver_cache_lock:
                if not WPDeployManager._wp_zh_version_cache:
                    WPDeployManager._wp_zh_version_cache = _fetched_ver
            return _fetched_ver
        # cn API 失败时回退至全球版本（可能导致 hash 不匹配并自动切换到英文包）
        return self._fetch_wp_latest_version()

    @staticmethod
    def _decrement_wp_version(ver):
        # type: (str) -> list
        """[FIX-ZH1] 生成前 N 个 patch 版本用于降级重试。

        '6.9.4' → ['6.9.3', '6.9.2']
        '6.9.0' → []  (不降到负数)
        '6.9'   → []  (无 patch 段不降级)
        """
        parts = ver.split('.')
        if len(parts) == 3 and parts[2].isdigit():
            patch = int(parts[2])
            results = []
            for i in range(1, 3):  # 最多降 2 个 patch 版本
                if patch - i >= 0:
                    results.append(
                        '%s.%s.%s' % (parts[0], parts[1], patch - i)
                    )
            return results
        return []

    @staticmethod
    def _head_check_url(url, timeout=8):
        # type: (str, int) -> bool
        """[FIX-ZH2] HEAD 请求检测远程文件是否存在 (HTTP 200)。

        用于在下载前验证版本化 URL 的实际可用性,
        避免下载一个不存在的文件浪费时间和带宽。
        """
        import urllib.request as _ur
        try:
            _req = _ur.Request(url, method='HEAD',
                               headers={"User-Agent": "wp-ssl-bootstrap"})
            with _ur.urlopen(_req, timeout=timeout) as _resp:
                return _resp.status == 200
        except Exception:
            return False

    @staticmethod
    def _is_valid_gzip(filepath, min_size_bytes=5 * 1024 * 1024):
        # type: (str, int) -> bool
        """[PATCH-GZ1] Validate file is gzip format with reasonable size.

        WordPress tar.gz is always > 20MB; anything < 5MB is suspicious.
        Catches HTML error pages returned with HTTP 200.
        """
        try:
            st = os.stat(filepath)
            if st.st_size < min_size_bytes:
                logging.warning(
                    "[PATCH-GZ1] File too small: %d bytes (min %d)",
                    st.st_size, min_size_bytes,
                )
                return False
            with open(filepath, 'rb') as f:
                magic = f.read(2)
                if magic != b'\x1f\x8b':
                    f.seek(0)
                    head = f.read(200)
                    logging.warning(
                        "[PATCH-GZ1] Not gzip (magic: %s). Preview: %s",
                        magic.hex() if magic else "(empty)",
                        head.decode('utf-8', errors='replace')[:150],
                    )
                    return False
            return True
        except OSError as e:
            logging.warning("[PATCH-GZ1] Validate failed: %s", e)
            return False

    def _build_wp_download_sources(self, wp_ver):
        # type: (str) -> list
        """根据 WordPress 版本号构建下载源列表（含 zh_CN 降级重试）。

        wp_ver 非空时使用版本化 URL + SHA1 校验;
        为空时回退到 latest 别名 (无哈希校验)。

        [FIX-ZH1] 中文环境下载顺序 (四级容灾):
          1. zh_CN 版本化 (cn API 版本, HEAD 预检)
          2. zh_CN 降级重试 (patch -1, -2, HEAD 预检)
          3. zh_CN latest 别名 (无 hash 但保证指向最新已发布版本)
          4. 英文全球源 (最终兜底)

        解决: cn API 返回 6.9.4 但实际 zh_CN 包仅发布到 6.9.3 时,
        自动降级到 6.9.3 下载, 避免意外使用英文版。
        """
        if not wp_ver:
            # API 失败: 回退至 latest 别名, 无哈希校验
            _src_zh = {
                "name": t("src_cn_node"),
                "wp":   "https://cn.wordpress.org/latest-zh_CN.tar.gz",
                "hash": "",
            }
            _src_en = {
                "name": t("src_global_node"),
                "wp":   "https://wordpress.org/latest.tar.gz",
                "hash": "",
            }
            if _LANG == "zh":
                return [_src_zh, _src_en]
            return [_src_en, _src_zh]

        sources = []

        if _LANG == "zh":
            _zh_ver = self._fetch_wp_zh_version()

            # [FIX-ZH2] HEAD 预检: 确认版本化 URL 实际存在后才加入源列表,
            # 避免下载一个 404 文件浪费时间。
            _zh_url_tpl = "https://cn.wordpress.org/wordpress-%s-zh_CN.tar.gz"
            _zh_hash_tpl = "https://cn.wordpress.org/wordpress-%s-zh_CN.tar.gz.sha1"

            # 候选版本: 当前版本 + 降级版本
            _candidate_versions = [_zh_ver] + self._decrement_wp_version(_zh_ver)

            _added_any_versioned = False
            for _cv in _candidate_versions:
                _cv_url = _zh_url_tpl % _cv
                # HEAD 探测: 文件存在才加入
                if self._head_check_url(_cv_url):
                    _suffix = ""
                    if _cv != _zh_ver:
                        _suffix = " (降级 fallback)"
                        logging.info(
                            "[FIX-ZH1] zh_CN v%s HEAD OK, 加入下载源%s",
                            _cv, _suffix,
                        )
                    sources.append({
                        "name": t("src_cn_node") + " (v%s%s)" % (_cv, _suffix),
                        "wp":   _cv_url,
                        "hash": _zh_hash_tpl % _cv,
                    })
                    _added_any_versioned = True
                    break  # HEAD 通过的第一个版本即为最佳候选
                else:
                    logging.info(
                        "[FIX-ZH1] zh_CN v%s HEAD 404, 尝试降级...", _cv,
                    )

            # 若所有版本化 HEAD 都失败, 追加无 HEAD 的候选让下载器尝试
            if not _added_any_versioned:
                # 仍加入主版本 (可能是网络问题导致 HEAD 失败但 GET 成功)
                sources.append({
                    "name": t("src_cn_node") + " (v%s)" % _zh_ver,
                    "wp":   _zh_url_tpl % _zh_ver,
                    "hash": _zh_hash_tpl % _zh_ver,
                })

            # [V3.2.50] zh_CN latest 优先于英文源 (保证中文包)
            sources.append({
                "name": t("src_cn_node") + " (latest)",
                "wp":   "https://cn.wordpress.org/latest-zh_CN.tar.gz",
                "hash": "",
            })

            # 英文全球源最终兜底 (有哈希但非中文包)
            sources.append({
                "name": t("src_global_node"),
                "wp":   "https://wordpress.org/wordpress-%s.tar.gz" % wp_ver,
                "hash": "https://wordpress.org/wordpress-%s.tar.gz.sha1" % wp_ver,
            })

        else:
            # 英文环境: 全球源优先, zh_CN 作为网络兜底
            sources.append({
                "name": t("src_global_node"),
                "wp":   "https://wordpress.org/wordpress-%s.tar.gz" % wp_ver,
                "hash": "https://wordpress.org/wordpress-%s.tar.gz.sha1" % wp_ver,
            })
            _zh_ver = self._fetch_wp_zh_version()
            sources.append({
                "name": t("src_cn_node"),
                "wp":   "https://cn.wordpress.org/wordpress-%s-zh_CN.tar.gz" % _zh_ver,
                "hash": "https://cn.wordpress.org/wordpress-%s-zh_CN.tar.gz.sha1" % _zh_ver,
            })

        return sources

    def _download_wp_with_hash(self, sources, dest, hash_dest):
        # type: (list, str, str) -> tuple
        """从源列表逐个下载 WordPress 压缩包并校验 SHA1。

        返回 (download_success, wpcli_downloaded, hash_verified) 三元组。
        所有 tar.gz 源均失败时回退到 WP-CLI 直接下载。
        """
        download_success = False
        wpcli_downloaded = False  # WP-CLI 直接下载到 webroot，无需 tar 解压
        _hash_verified = False  # [PATCH-M4] 追踪是否经过 SHA1 校验

        for src in sources:
            logging.info(t("info_wp_src_try", name=src['name']))
            if shutil.which("curl"):
                cmd_wp = ["curl", "-sSL", "--connect-timeout", "10", "-o", dest, src['wp']]
            elif shutil.which("wget"):
                cmd_wp = ["wget", "-q", "-O", dest, "--connect-timeout=10", "--read-timeout=90", src['wp']]
            else:
                logging.error(t("err_no_curl_wget"))
                return (False, False, False)

            wp_result = self.run_cmd(cmd_wp, timeout=120, quiet=True)

            # 无 hash URL: 跳过哈希校验但验证 gzip 格式 [PATCH-GZ1]
            if wp_result and not src.get("hash"):
                if self._is_valid_gzip(dest):
                    download_success = True
                    # _hash_verified 保持 False，提取后将强制 WP-CLI 校验
                    break
                else:
                    logging.warning(
                        "[PATCH-GZ1] [%s] Not valid gzip; trying next.",
                        src['name'],
                    )
                    continue

            if src.get("hash"):
                cmd_hash = (["curl", "-sSL", "--connect-timeout", "10", "-o", hash_dest, src['hash']]
                            if shutil.which("curl") else
                            ["wget", "-q", "-O", hash_dest, "--connect-timeout=10", src['hash']])
                hash_result = self.run_cmd(cmd_hash, timeout=60, quiet=True)
            else:
                hash_result = None

            if wp_result and hash_result:
                try:
                    hash_text = Path(hash_dest).read_text(encoding="utf-8").strip()
                    expected_hash = hash_text.split()[0]
                except (IndexError, OSError):
                    logging.warning(t("warn_wp_hash_bad", name=src['name']))
                    continue
                # [V3.2.3] M-10: WordPress 官方仅提供 SHA1 校验 (版本化 URL)。
                # SHA1 已不推荐用于密码学场景, 但在 HTTPS 传输下用于下载
                # 完整性验证仍可接受 (防比特翻转, 非防主动篡改)。
                # 若未来 WordPress 提供 SHA256, 应优先使用。
                sha1_obj = hashlib.sha1()
                with open(dest, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha1_obj.update(chunk)
                actual_hash = sha1_obj.hexdigest()

                if expected_hash.lower() == actual_hash:
                    logging.info(t("ok_sha1", name=src['name']))
                    _hash_verified = True  # [PATCH-M4]
                    download_success = True
                    break
                else:
                    # [V3.2.0] N1: CDN 缓存不一致时重试一次哈希文件
                    logging.info(t("info_wp_hash_retry"))
                    time.sleep(2)
                    _retry_hash = self.run_cmd(cmd_hash, timeout=60, quiet=True)
                    if _retry_hash:
                        try:
                            _rh_text = Path(hash_dest).read_text(encoding="utf-8").strip()
                            _rh_expected = _rh_text.split()[0].lower()
                        except (IndexError, OSError):
                            _rh_expected = ""
                        if _rh_expected == actual_hash:
                            logging.info(t("ok_sha1", name=src['name']))
                            _hash_verified = True  # [PATCH-M4]
                            download_success = True
                            break
                    logging.warning(t("warn_wp_src_hash_mismatch", name=src['name']))
            else:
                # 利用 CmdResult 错误分类判断是否值得重试
                if wp_result.code == CmdResult.FATAL:
                    logging.error(t("err_wp_src_fatal", name=src['name']))
                    break

        if not download_success:
            # WP-CLI 保底：所有 tar.gz 源均失败时才安装并尝试
            self._ensure_wpcli()
            if self._wpcli_bin:
                logging.warning(t("warn_all_tgz_failed"))
                if self._wpcli_download_wordpress():
                    download_success = True
                    wpcli_downloaded = True

        return (download_success, wpcli_downloaded, _hash_verified)

    def download_and_verify_wordpress(self) -> bool:
        # 磁盘空间预检（借鉴 sooth_monitor 的磁盘空间检查模式）
        if not self.check_disk_space(
            self.cfg.webroot_path,
            SiteConfig.MIN_DISK_FREE_MB_DOWNLOAD,
            t("label_wp_download"),
        ):
            return False

        # 先从 API 获取最新版本号, 构造版本化 URL + SHA1 校验
        # WordPress 官网仅对具体版本提供 sha1/md5, latest 别名无哈希
        logging.info(t("info_wp_version_fetching"))
        _wp_ver = self._fetch_wp_latest_version()
        if _wp_ver:
            logging.info(t("info_wp_version_fetched", ver=_wp_ver))
            # [FIX-1] 中文环境下预取 zh_CN 版本号并提示，与全球版本可能不同
            if _LANG == "zh":
                _zh_ver = self._fetch_wp_zh_version()
                if _zh_ver and _zh_ver != _wp_ver:
                    logging.info(
                        "zh_CN API 版本: %s, 全球版本: %s "
                        "— 将通过 HEAD 探测确认实际可用版本后下载",
                        _zh_ver, _wp_ver,
                    )
        else:
            logging.warning(t("warn_wp_version_fetch_fail"))

        # [V3.2.35] 拆分: 构建下载源
        sources = self._build_wp_download_sources(_wp_ver)

        fd_wp, dest = tempfile.mkstemp(prefix="wp_", suffix=".tar.gz")
        os.close(fd_wp)
        fd_hash, hash_dest = tempfile.mkstemp(prefix="wp_hash_", suffix=".sha1")
        os.close(fd_hash)

        try:
            # [V3.2.35] 拆分: 下载 + 哈希校验
            download_success, wpcli_downloaded, _hash_verified = \
                self._download_wp_with_hash(sources, dest, hash_dest)

            if not download_success:
                logging.error(t("err_wp_download_all_failed"))
                return False

            # WP-CLI 直接下载到 webroot，跳过 tar 解压
            if not wpcli_downloaded:
                # [PATCH-GZ1] 解压前验证 gzip 格式
                if not self._is_valid_gzip(dest):
                    logging.error(
                        "[PATCH-GZ1] Archive failed gzip validation."
                    )
                    return False

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
            # [PATCH-M4] 无哈希回退场景强制安装 WP-CLI 并校验
            if not _hash_verified and not self._wpcli_bin:
                self._ensure_wpcli()
            if self._wpcli_bin:
                if not self._wpcli_verify_checksums():
                    if not _hash_verified:
                        logging.warning(
                            "[PATCH-M4] latest download: verify-checksums failed; "
                            "manual inspection recommended"
                        )
                    else:
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

    # -----------------------------------------------------------------------
    # [V3.2.32] setup_lemp_and_wp() 拆分: 子方法
    # -----------------------------------------------------------------------
    # [V3.2.33] P-4: removed dead code _configure_php_settings (V3.2.32 refactor remnant, never called)

    # [V3.2.33] P-4: removed dead code _start_core_services (V3.2.32 refactor remnant, never called)

    # [V3.2.33] P-4: removed dead code _setup_wp_database_and_user (V3.2.32 refactor remnant, never called)

    # [V3.2.33] P-4: removed dead code _generate_wp_config (V3.2.32 refactor remnant, never called)


    # -----------------------------------------------------------------------
    # [V3.2.32] download_and_verify_wordpress() 拆分: 子方法
    # -----------------------------------------------------------------------
    # [V3.2.33] P-4: removed dead code _build_wp_download_sources (V3.2.32 refactor remnant, never called)

    # [V3.2.33] P-4: removed dead code _try_download_wp_from_sources (V3.2.32 refactor remnant, never called)

    # -----------------------------------------------------------------------
    # [V3.2.35] setup_lemp_and_wp() 拆分: 子方法
    # -----------------------------------------------------------------------

    def _lemp_configure_php(self):
        # type: () -> None
        """配置 PHP ini 参数和 FPM pool 用户/组。"""
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

        # [V3.0.16] P3: 按内存动态调整 PHP-FPM pool 参数 (在服务启动前)
        self._patch_fpm_pool_tuning()

    def _lemp_start_services(self):
        # type: () -> bool
        """逐个启用核心服务 (DB, PHP-FPM, Nginx), 启动失败时尝试诊断修复。

        Nginx 是后续所有阶段的硬依赖，启动失败必须终止。
        返回 True 表示服务全部就绪。
        """
        # [FIX-C11] EL10 上 certbot/mod_http2 等会将 httpd 作为弱依赖拉入,
        # httpd 可能自动启动并占用 80 端口导致 nginx 启动失败。
        # 在启动 nginx 之前主动停止并禁用 httpd (仅限当前运行中的场景)。
        if not self.cfg.dry_run:
            try:
                _httpd_active = subprocess.run(
                    ["systemctl", "is-active", "httpd"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5,
                    check=False,
                )
                if _httpd_active.returncode == 0:
                    logging.info(
                        "[FIX-C11] httpd is running (installed as weak dep); "
                        "stopping to free port 80 for nginx..."
                    )
                    self.run_cmd(
                        ["systemctl", "stop", "httpd"], quiet=True,
                    )
                    self.run_cmd(
                        ["systemctl", "disable", "httpd"], quiet=True,
                    )
            except Exception:
                pass

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
                    # [V3.2.0] 诊断 Nginx 启动失败
                    if not self._diagnose_nginx_failure():
                        logging.error(t("err_nginx_start"))
                        return False
                elif svc == self.php_fpm_svc:
                    # [V3.2.70] BUG-2: PHP-FPM 是 Nginx 的硬依赖，启动失败必须终止。
                    # 原实现仅 warning 后继续，会导致 Nginx 启动成功但所有 PHP 请求 502。
                    if not self._diagnose_phpfpm_failure(svc):
                        logging.error(t("warn_svc_enable_fail", svc=svc, code=result.code))
                        self._exit_code = 1
                        return False
                elif svc == self.db_svc:
                    # [V3.2.70] BUG-2: MariaDB 是 WordPress 的硬依赖，启动失败必须终止。
                    if not self._diagnose_mariadb_failure():
                        logging.error(t("warn_svc_enable_fail", svc=svc, code=result.code))
                        self._exit_code = 1
                        return False
                else:
                    logging.warning(t("warn_svc_enable_fail", svc=svc, code=result.code))
        self.setup_firewall()
        return True

    def _lemp_setup_database(self):
        # type: () -> tuple
        """初始化 MariaDB, 创建数据库和用户, 注册回滚。

        返回 (ok, recovered_pass, need_rewrite_wp_config) 三元组。
        ok=False 表示致命错误, 调用方应终止部署。
        """
        logging.info(t("info_db_allocate"))
        # [V2.9.4] B9 修复：_wait_db_ready 返回 False 表示超时未就绪，
        # 记录上下文日志但不中断（init_mariadb_root 的失败信息已足够具体）。
        if not self._wait_db_ready():
            logging.warning(t("warn_db_timeout_continue"))
        if not self.init_mariadb_root():
            return (False, "", False)

        self._tune_mariadb()  # [V3.0.16] P6: MariaDB 按内存调优

        # [V3.0.16] F7: DB restart 后重新等待就绪, 避免后续 SQL 失败
        if not self.cfg.is_external_db and not self.cfg.dry_run:
            self._wait_db_ready()

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
                        ["mysql", "--defaults-extra-file=%s" % _tmp_def,
                         "-u", self.cfg.db_user] + _host_args +
                        [self.cfg.db_name, "-e", "SELECT 1;"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding='utf-8', errors='replace', timeout=10, check=False,
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
            return (False, "", False)
        if not SiteConfig.validate_sql_identifier(self.cfg.db_user):
            logging.error(t("err_db_user_chars", user=self.cfg.db_user))
            return (False, "", False)
        # [PATCH-M2] 已恢复密码通过了独立白名单校验且数据库连通，
        # 无需再经 validate_sql_password（其白名单比 recover 更严格）
        if not (recovered_pass and self.cfg.db_pass == recovered_pass):
            if not SiteConfig.validate_sql_password(self.cfg.db_pass):
                logging.error(t("err_db_pass_chars"))
                return (False, "", False)

        # 外置数据库：授权来源使用 '%'（允许远程连接），本地使用 'localhost'
        db_grant_host = '%' if self.cfg.is_external_db else 'localhost'
        # [V3.0.8] S1: 防御性校验 — 仅允许安全值, 无需 SQL 转义
        if db_grant_host not in ('%', 'localhost'):
            raise ValueError("Unexpected db_grant_host: %s" % db_grant_host)
        # V2.7.1: 幂等重跑时，若已从 wp-config.php 恢复密码，跳过 ALTER USER，
        # 避免新生成的随机密码覆盖数据库中的旧密码导致 WordPress 连不上数据库。
        if recovered_pass:
            db_sql = (
                "CREATE DATABASE IF NOT EXISTS `%s`"
                " CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
                "CREATE USER IF NOT EXISTS '%s'@'%s'"
                " IDENTIFIED BY '%s';\n"
                "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX ON `%s`.*"  # [V2.9.7] 最小权限
                " TO '%s'@'%s';\n"
                "FLUSH PRIVILEGES;\n"
                % (self.cfg.db_name,
                   self.cfg.db_user, db_grant_host,
                   self._mysql_escape_value(self.cfg.db_pass),
                   self.cfg.db_name,
                   self.cfg.db_user, db_grant_host))
        else:
            db_sql = (
                "CREATE DATABASE IF NOT EXISTS `%s`"
                " CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
                "CREATE USER IF NOT EXISTS '%s'@'%s'"
                " IDENTIFIED BY '%s';\n"
                "ALTER USER '%s'@'%s'"
                " IDENTIFIED BY '%s';\n"
                "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX ON `%s`.*"  # [V2.9.7] 最小权限
                " TO '%s'@'%s';\n"
                "FLUSH PRIVILEGES;\n"
                % (self.cfg.db_name,
                   self.cfg.db_user, db_grant_host,
                   self._mysql_escape_value(self.cfg.db_pass),
                   self.cfg.db_user, db_grant_host,
                   self._mysql_escape_value(self.cfg.db_pass),
                   self.cfg.db_name,
                   self.cfg.db_user, db_grant_host))
        if not self.run_sql(db_sql, use_pwd=True):
            return (False, "", False)

        # 本次新建的数据库：注册回滚清理（仅首次部署，幂等重跑不回滚）
        if not recovered_pass:
            db_name = self.cfg.db_name
            db_user = self.cfg.db_user
            drop_sql = (
                "DROP DATABASE IF EXISTS `%s`;\n"
                "DROP USER IF EXISTS '%s'@'%s';\n"
                "FLUSH PRIVILEGES;\n"
                % (db_name, db_user, db_grant_host)
            )
            self._register_rollback(
                t("rollback_db_user", db=db_name, user=db_user),
                lambda sql=drop_sql: self.run_sql(sql, use_pwd=True),
            )

        return (True, recovered_pass, _need_rewrite_wp_config)

    def _lemp_write_wp_config(self, recovered_pass, need_rewrite):
        # type: (str, bool) -> bool
        """写入或更新 wp-config.php, 设置目录权限。

        recovered_pass: 从已有 wp-config.php 恢复的密码 (空串表示新生成)
        need_rewrite:   是否需要重写已有 wp-config.php 中的 DB_PASSWORD
        返回 True 表示成功。
        """
        wp_config = self.cfg.webroot_path / "wp-config.php"
        wp_sample = self.cfg.webroot_path / "wp-config-sample.php"

        # V2.7.5: 恢复密码验证失败时, 更新已有 wp-config.php 中的 DB_PASSWORD
        if need_rewrite and wp_config.exists() and not self.cfg.dry_run:
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
                # [V3.2.12] P2-7: 直接传入 skip_ssl，避免冗余的二次覆盖
                content = inject_wp_hardening(content, skip_ssl=self.cfg.skip_ssl)
                content = patch_wplang(content)  # [V3.0.15] B6: 校正 WPLANG
                # [V2.9.6] 原子写入, 从创建瞬间即为 0440
                if not self._safe_write_file(wp_config, content, mode=0o440):
                    raise OSError("_safe_write_file failed to create wp-config.php")
                # 本次新写的 wp-config.php：注册回滚清理
                self._register_rollback(
                    "Remove %s" % wp_config,
                    lambda p=wp_config: (p.unlink() if p.exists() else None),
                )
            except Exception as e:
                logging.error(t("err_wpconfig_generate", e=e))
                return False

        self.run_cmd(
            ["chown", "-R", "%s:%s" % (self.nginx_user, self.nginx_user),
             str(self.cfg.webroot_path)],
            quiet=True,
        )
        self.run_cmd(
            ["find", str(self.cfg.webroot_path), "-type", "d",
             "-exec", "chmod", "755", "{}", "+"],
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

    def setup_lemp_and_wp(self) -> bool:
        logging.info(t("phase1"))
        self._ensure_swap()  # [V3.0.16] P4: 小内存防 OOM
        self._tune_kernel_network()  # [V3.0.16] P5: TCP/BBR 调优
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

        # [V3.2.35] 拆分: PHP 配置
        self._lemp_configure_php()

        # [V3.2.35] 拆分: 启动服务
        if not self._lemp_start_services():
            return False
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

        # WP-CLI: tar.gz 下载完成后再装, 用于校验和插件安装
        self._ensure_wpcli()

        self.handle_selinux()
        if self.check_shutdown():
            return False

        # [V3.2.35] 拆分: 数据库初始化
        _db_ok, _recovered_pass, _need_rewrite = self._lemp_setup_database()
        if not _db_ok:
            return False

        # [V3.2.35] 拆分: wp-config + 权限
        if not self._lemp_write_wp_config(_recovered_pass, _need_rewrite):
            return False

        return True



    # -----------------------------------------------------------------------
    # 阶段二：Nginx HTTP 验证通道
    # -----------------------------------------------------------------------
    def setup_nginx_for_challenge(self) -> bool:
        logging.info(t("phase2"))
        # [V3.2.15] P2-4: 传入 sock_path, 使 ACME 配置也能处理 PHP
        config = generate_http_only_config(
            self.cfg.domain, self.cfg.webroot_path,
            sock_path=self.get_php_sock_path(),
        )
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
        # [V3.2.65] BUG-C-2: www 前缀 / 子域名均跳过 www 变体检测
        _has_www_variant = _should_add_www(self.cfg.domain)
        _dns_check_list = [self.cfg.domain]
        if _has_www_variant:
            _dns_check_list.append(f"www.{self.cfg.domain}")

        for domain in _dns_check_list:
            resolved = False

            # 优先用 dig
            if shutil.which("dig"):
                for rtype in ("A", "AAAA"):
                    try:
                        r = subprocess.run(
                            ["dig", "+short", "+time=5", "+tries=2", rtype, domain],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding='utf-8', errors='replace', timeout=self.DNS_CHECK_TIMEOUT,
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
                        encoding='utf-8', errors='replace', timeout=self.DNS_CHECK_TIMEOUT,
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
        # [V3.2.0] N1: 域名已含 www 时无需检测 www 变体, 视为通过
        www_ok = results.get(f"www.{self.cfg.domain}", False) if _has_www_variant else True
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
        except OSError as e:
            logging.error(t("err_http_challenge_write", e=e))
            return False

        # [V3.2.28] BUG-I: 检查 _safe_write_file 的返回值。
        # 该函数在内部捕获 OSError 并返回 False，不向外传播异常。
        # 原代码忽略返回值，写入失败时仍会执行 curl 验证并误报为
        # "HTTP challenge 连通性失败"而非"测试文件写入失败"。
        # 将 mkdir 和 _safe_write_file 分离到独立 try 块：
        #   mkdir 失败时 test_file 尚未创建，直接 return False；
        #   _safe_write_file 失败时 test_file 不存在，同样直接 return False，
        #   并在进入第二个 try 块前清理（finally 中 unlink 已有 try-except 保护）。
        if not self._safe_write_file(test_file, token, mode=0o644):
            logging.error(t("err_http_challenge_write",
                            e="_safe_write_file returned False"))
            return False

        # 确保 Nginx 用户可读（chown 失败不致命，curl 会以实际权限验证）
        self.run_cmd(
            ["chown", "-R", f"{self.nginx_user}:{self.nginx_user}",
             str(self.cfg.webroot_path / ".well-known")],
            quiet=True,
        )

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
                        encoding='utf-8', errors='replace', timeout=15, check=False,
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
                        encoding='utf-8', errors='replace', timeout=15, check=False,
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


    # -----------------------------------------------------------------------
    # 证书签发失败自动诊断
    # -----------------------------------------------------------------------
    def _diagnose_cert_failure(self) -> dict:
        """读取 letsencrypt.log 分析证书签发失败的根因。"""
        result = {
            "dns_issue": False, "challenge_fail": False,
            "rate_limit": False, "timeout": False,
            "port_blocked": False, "detail": "",
        }
        log_path = Path("/var/log/letsencrypt/letsencrypt.log")
        logging.info(t("diag_reading_log"))
        if not log_path.exists():
            logging.warning(t("diag_log_not_found", path=log_path))
            return result
        try:
            fsize = log_path.stat().st_size
            rsize = min(fsize, 50 * 1024)
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                if fsize > rsize:
                    f.seek(fsize - rsize)
                tail = f.read()
        except OSError:
            return result

        low = tail.lower()
        domain = self.cfg.domain
        lines = []

        if any(k in low for k in ("dns problem", "nxdomain", "no valid a record", "servfail")):
            result["dns_issue"] = True
            lines.append(t("diag_dns_issue", domain=domain))
        if any(k in low for k in ("challenge failed", "unauthorized", "invalid response from")):  # [V3.2.71] BUG-3: "connection refused on port 80" 归入 port_blocked 分支
            result["challenge_fail"] = True
            lines.append(t("diag_challenge_fail", domain=domain))
        if any(k in low for k in ("rate limit", "too many", "rate-limited")):
            result["rate_limit"] = True
            lines.append(t("diag_rate_limit"))
        if any(k in low for k in ("timeout", "timed out", "network is unreachable")):
            result["timeout"] = True
            lines.append(t("diag_timeout"))
        # [V3.2.63] BUG-2: 同 BUG-1，"port 80" 改为全词匹配
        if (any(k in low for k in ("could not bind", "address already in use",
                                    "problem binding to port"))
                or re.search(r'\bport 80\b', low)):
            result["port_blocked"] = True
            lines.append(t("diag_port_blocked"))

        if not lines:
            lines.append("   No known error pattern; inspect log manually.")

        detail = "\n".join(lines) + "\n" + t("diag_hint_log", path=log_path)
        result["detail"] = detail
        logging.info(t("diag_summary", detail=detail))
        return result

    # -----------------------------------------------------------------------
    # DNS 自动修复
    # -----------------------------------------------------------------------
    def _try_fix_dns(self) -> bool:
        """尝试向 /etc/resolv.conf 注入公共 DNS。返回 True 表示已修改。"""
        if self.cfg.dry_run:
            return False
        resolv = Path("/etc/resolv.conf")
        try:
            original = resolv.read_text(encoding="utf-8")
        except OSError:
            return False
        bak = resolv.with_suffix(".conf.wp_ssl_bak")
        try:
            shutil.copy2(str(resolv), str(bak))
        except OSError:
            return False
        cloud = _is_china_cloud()
        dns_servers = (
            ["223.5.5.5", "114.114.114.114", "8.8.8.8"] if cloud
            else ["1.1.1.1", "8.8.8.8"]
        )
        new_lines = [
            f"nameserver {s}" for s in dns_servers
            if f"nameserver {s}" not in original
        ]
        if not new_lines:
            return False
        # [V3.2.27] BUG-3: 改为写入临时文件后 os.replace 原子替换，
        # 消除读取原文件与写入之间的 TOCTOU 竞态窗口（NFS/并发场景可见）。
        _resolv_tmp = resolv.with_name("resolv.conf.wp_ssl_tmp")
        try:
            new_content = (
                original
                + "\n# WP-SSL-Bootstrap DNS fix\n"
                + "\n".join(new_lines)
                + "\n"
            )
            _tmp_fd = os.open(
                str(_resolv_tmp),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o644,
            )
            try:
                os.write(_tmp_fd, new_content.encode("utf-8"))
                os.fsync(_tmp_fd)
            finally:
                os.close(_tmp_fd)
            os.replace(str(_resolv_tmp), str(resolv))
            logging.info(t("info_dns_fix_applied", servers=", ".join(dns_servers)))
            self._dns_resolv_backup = str(bak)
            return True
        except OSError:
            try:
                _resolv_tmp.unlink()
            except OSError:
                pass
            return False

    def _rollback_dns_fix(self) -> None:
        """回滚 DNS 修改。"""
        bak_path = getattr(self, "_dns_resolv_backup", "")
        if bak_path and Path(bak_path).exists():
            try:
                shutil.copy2(bak_path, "/etc/resolv.conf")
                logging.info(t("info_dns_fix_rollback"))
            except OSError:
                pass

    def _run_certbot_with_lock(self, cmd: list, sensitive: bool = False) -> CmdResult:
        lock_file = Path(self._CERTBOT_LOCK_FILE)  # [V3.2.44] REF-1c
        # [V3.2.26] BUG-E: 原 fcntl.flock(LOCK_EX) 无超时，若持锁进程挂起，
        # 后续调用将永久阻塞。改为 LOCK_NB 非阻塞轮询 + 300 s 超时上限，
        # 超时后返回 FATAL 而非无限等待。同时在 finally 中清理 lock 文件，
        # 防止进程异常退出时遗留 /run/certbot.lock。
        # [V3.2.28] BUG-IV: 修复 TOCTOU 竞态。
        # 原实现：进程 A 持锁 → finally 中 unlink → close（释放锁）
        #         进程 B 等待时已 open 同一 inode，A 释放后 B 获得旧 inode 上的锁
        #         进程 C 同时 open 新 inode 并立即获得锁 → 两个 certbot 并发运行
        # 修复：获得 flock 后通过 fstat/stat 比对 inode，不一致则说明
        #       文件已被删除并重建，放弃当前 fd 重新竞争，直至持有当前 inode 的锁。
        _deadline = time.time() + self.CERTBOT_LOCK_TIMEOUT  # [V3.2.44] REF-3
        f_lock = None
        try:
            while True:
                try:
                    f_lock = open(str(lock_file), 'w', encoding='utf-8')
                except OSError as e:
                    return CmdResult(ok=False, code=CmdResult.FATAL,
                                     stderr=t("err_certbot_lock", e=e))
                try:
                    fcntl.flock(f_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    # [V3.2.38] FIX-1: IOError → OSError, 与 fcntl 文档一致
                    # 锁被占用
                    try:
                        f_lock.close()
                    except OSError:
                        pass
                    f_lock = None
                    if time.time() >= _deadline:
                        return CmdResult(
                            ok=False, code=CmdResult.FATAL,
                            stderr=t(
                                "err_certbot_lock",
                                e="lock timeout after %ds" % self.CERTBOT_LOCK_TIMEOUT,  # [V3.2.44] REF-3
                            ),
                        )
                    time.sleep(2)
                    continue
                # 已获得 flock — 验证 fd 与磁盘上路径指向同一 inode，
                # 排除 "锁在已删除 inode 上" 的竞态场景。
                try:
                    _fd_ino = os.fstat(f_lock.fileno()).st_ino
                    _path_ino = os.stat(str(lock_file)).st_ino
                    if _fd_ino == _path_ino:
                        break  # inode 一致，锁有效
                    # inode 不一致：文件已被删除并重建，放弃此 fd 重试
                except OSError:
                    pass  # stat 失败（文件已删除）→ 同样重试
                try:
                    f_lock.close()
                except OSError:
                    pass
                f_lock = None
                if time.time() >= _deadline:
                    return CmdResult(
                        ok=False, code=CmdResult.FATAL,
                        stderr=t(
                            "err_certbot_lock",
                            e="lock timeout after %ds" % self.CERTBOT_LOCK_TIMEOUT,  # [V3.2.44] REF-3
                        ),
                    )
                # 短暂等待让持锁进程完成 unlink+release 动作
                time.sleep(0.1)

            # 持有有效锁，执行 certbot
            try:
                return self.run_cmd(cmd, sensitive=sensitive)
            finally:
                # 持锁期间负责清理 lock 文件，与 apply_nginx_config_safe 保持一致
                try:
                    lock_file.unlink()
                except OSError:
                    pass
                try:
                    f_lock.close()
                except OSError:
                    pass
        except Exception as e:  # [V3.2.31] P-5: OSError→Exception 防止锁泄漏
            return CmdResult(ok=False, code=CmdResult.FATAL,
                             stderr=t("err_certbot_lock", e=e))

    # [V3.2.59] BUG-4: _fetch_zerossl_eab_by_email 已删除（重构残留死方法）
    # 调用方请直接使用模块级 _fetch_zerossl_eab(email) 或 self._acquire_zerossl_eab()

    # -----------------------------------------------------------------------
    # [V3.2.57] 模块化证书命令构建与 CA 尝试
    # -----------------------------------------------------------------------

    def _build_domain_args(self, include_www: bool = True) -> list:
        """构建 certbot -d 参数列表，统一处理 www 前缀逻辑。

        避免 www.www 双前缀问题，apply_cert 和 _default_cert_domain_args
        原先各自判断，现统一到此处。

        [V3.2.65] BUG-C-3: 子域名 (mail/api/blog...) 不再添加 www 变体。
        """
        if self.cfg.domain.startswith("www."):
            # 防御性: 域名未归一化时, 同时包含 www 和裸域名
            bare = self.cfg.domain[4:]
            args = ["-d", self.cfg.domain, "-d", bare]
            return args
        args = ["-d", self.cfg.domain]
        if include_www and _should_add_www(self.cfg.domain):
            args.extend(["-d", f"www.{self.cfg.domain}"])
        elif include_www:
            # 子域名, 不添加 www 变体
            logging.info("[V3.2.65] 子域名 %s: 跳过 www 变体", self.cfg.domain)
        else:
            logging.info(t("info_cert_skip_www", domain=self.cfg.domain))
        return args

    def _build_certbot_cmd(self, domain_args: list, *,
                           email: str = "",
                           quiet: bool = False,
                           staging: bool = False) -> list:
        """构建 certbot 基础命令（不含 CA 专属参数）。

        apply_cert 与 renew_cert 共用同一命令骨架，消除重复构造逻辑：
          certbot certonly --webroot -w <root> <domain_args>
                 --cert-name <domain> --agree-tos --non-interactive
                 [-m <email> | --register-unsafely-without-email]
                 [--quiet] [--staging]

        CA 专属参数（--server / --eab-kid / --eab-hmac-key）由
        _try_issue_with_ca() 追加，不在此处处理。

        email 为空时追加 --register-unsafely-without-email（renew 无账户兜底）。
        """
        cmd = [
            self.cfg.certbot_bin, "certonly", "--webroot",
            "-w", str(self.cfg.webroot_path),
        ] + domain_args + [
            "--cert-name", self.cfg.domain,
            "--agree-tos", "--non-interactive",
        ]
        if email:
            cmd.extend(["-m", email])
        else:
            cmd.append("--register-unsafely-without-email")
        if quiet:
            cmd.append("--quiet")
        if staging:
            cmd.append("--staging")
        return cmd

    def _try_issue_with_ca(self, cmd_base: list, ca: dict) -> tuple:
        """用单个 CA 尝试签发，返回 (success, err_type, stderr)。

        success:  True = 签发成功
        err_type: CmdResult.FATAL / PERMISSION / RETRYABLE（仅 success=False 时有效）
        stderr:   原始错误输出（用于上层日志）

        调用方根据 err_type 决定是否熔断（FATAL/PERMISSION）或继续下一个 CA。
        """
        cmd = list(cmd_base)
        if ca.get("server"):
            cmd.extend(["--server", ca["server"]])
        # [V3.2.52] ZeroSSL EAB: certbot >= 1.7 支持 --eab-kid / --eab-hmac-key
        if ca.get("eab_kid") and ca.get("eab_hmac_key"):
            cmd.extend(["--eab-kid", ca["eab_kid"],
                         "--eab-hmac-key", ca["eab_hmac_key"]])
        # sensitive=True: --eab-hmac-key 为密钥，不得写入日志
        result = self._run_certbot_with_lock(
            cmd, sensitive=bool(ca.get("eab_hmac_key"))
        )
        if result:
            return (True, None, "")
        return (False, classify_certbot_error(result.stderr), result.stderr)

    def _acquire_zerossl_eab(self) -> tuple:
        """[V3.2.58] 运行时三级 EAB 获取（LE 失败后触发），委托模块级实现。

        与向导场景的区别：此处通过 logging 输出（非 print），
        适合非交互式环境；TTY 时降级到 print+input 手动输入。
        """
        # ── L1: auto-fetch ────────────────────────────────────────────────
        logging.info(t("info_zerossl_eab_auto_fetch"))
        _fetched = _fetch_zerossl_eab(self.cfg.email)
        if _fetched[0]:
            logging.info(t("ok_zerossl_eab_auto_fetch", kid=_fetched[0][:8]))
            return _fetched

        _fetch_err = _fetched[1] if len(_fetched) > 1 else "unknown"
        logging.warning(t("warn_zerossl_eab_auto_fetch_fail", err=_fetch_err))

        # ── L2: TTY 手动输入 ──────────────────────────────────────────────
        if sys.stdin.isatty():
            print(t("prompt_zerossl_le_failed_manual"))
            print()
            try:
                _kid = input(
                    "  " + t("interactive_zerossl_prompt_kid") + ": "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                _kid = ""
            if _kid:
                try:
                    _hmac = input(
                        "  " + t("interactive_zerossl_prompt_hmac") + ": "
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    _hmac = ""
                if _hmac:
                    return (_kid, _hmac)

        # ── L3: 放弃 ─────────────────────────────────────────────────────
        return ("", "")

    def apply_cert(self, include_www: bool = True, _dns_retry: bool = False,
                   _eab_prompted: bool = False) -> bool:
        """多级 CA 容灾签发，借鉴 sooth_monitor 熔断器模式。

        [V3.2.57] 重构：命令构建、单 CA 尝试、EAB 获取均委托给独立方法：
          _build_domain_args()   → -d 参数列表
          _build_certbot_cmd()   → certbot 基础命令（与 renew_cert 共用）
          _try_issue_with_ca()   → 单 CA 签发 + 错误分类
          _acquire_zerossl_eab() → 三级 EAB 获取（auto-fetch → TTY → 放弃）
        """
        # [V3.2.63] BUG-4: apply_cert 可递归（EAB 重试 / DNS 修复重试）；
        # phase3 横幅仅在首次进入时输出，避免日志中出现重复阶段标题。
        if not _eab_prompted and not _dns_retry:
            logging.info(t("phase3"))

        _cert_domains = self._build_domain_args(include_www)
        cmd_base = self._build_certbot_cmd(
            _cert_domains,
            email=self.cfg.email,
            staging=self.cfg.staging,
        )

        providers = [self.CA_PROVIDERS[0]] if self.cfg.staging else list(self.CA_PROVIDERS)
        if not self.cfg.staging and self.cfg.zerossl_eab_kid and self.cfg.zerossl_eab_hmac_key:
            providers.append({
                "name": "ZeroSSL",
                "server": "https://acme.zerossl.com/v2/DV90",
                "eab_kid": self.cfg.zerossl_eab_kid,
                "eab_hmac_key": self.cfg.zerossl_eab_hmac_key,
            })
            logging.info(t("info_zerossl_added", kid=self.cfg.zerossl_eab_kid[:8]))

        _last_cert_error = CmdResult.RETRYABLE

        for i, ca in enumerate(providers, 1):
            logging.info(t("info_cert_try", idx=i, total=len(providers), ca=ca["name"]))
            success, err_type, stderr = self._try_issue_with_ca(cmd_base, ca)
            if success:
                logging.info(t("ok_cert_issued", ca=ca["name"]))
                return True
            _last_cert_error = err_type
            if err_type == CmdResult.FATAL:
                logging.error(t("err_cert_fatal", ca=ca["name"], err=stderr[:200]))
                break
            elif err_type == CmdResult.PERMISSION:
                logging.error(t("err_cert_permission", ca=ca["name"], err=stderr[:200]))
                break
            logging.warning(t("warn_cert_retryable",
                ca=ca["name"],
                next_msg=t("warn_cert_next_ca") if i < len(providers)
                         else t("warn_cert_no_more_ca")))

        # ZeroSSL EAB 降级（RETRYABLE + 无预配置 EAB + 首次）
        if (
            _last_cert_error == CmdResult.RETRYABLE
            and not self.cfg.zerossl_eab_kid
            and not _eab_prompted
            and not self.cfg.staging
        ):
            _kid, _hmac = self._acquire_zerossl_eab()
            if _kid and _hmac:
                self.cfg.zerossl_eab_kid = _kid
                self.cfg.zerossl_eab_hmac_key = _hmac
                logging.info(t("prompt_zerossl_retry"))  # [V3.2.59] BUG-3: print→logging.info
                return self.apply_cert(
                    include_www=include_www,
                    _dns_retry=_dns_retry,
                    _eab_prompted=True,
                )

        # [V3.2.63] BUG-3: err_cert_all_failed 原先在 DNS 修复前输出；
        # 若修复成功则与最终成功结果自相矛盾。改为仅在确认无路可走时输出。
        diag = self._diagnose_cert_failure()
        if not _dns_retry and (
            diag.get("dns_issue") or diag.get("challenge_fail")
            or diag.get("timeout")
        ):
            logging.info(t("info_dns_fix_attempt"))
            if self._try_fix_dns():
                if self.apply_cert(include_www=include_www, _dns_retry=True,
                                   _eab_prompted=_eab_prompted):
                    logging.info(t("info_dns_fix_success"))
                    return True
                else:
                    self._rollback_dns_fix()
        logging.error(t("err_cert_all_failed"))
        return False

    # -----------------------------------------------------------------------
    # 阶段四：HTTPS 生产配置
    # -----------------------------------------------------------------------
    def setup_nginx_for_production(self) -> bool:
        logging.info(t("phase4"))
        sock_path = self.get_php_sock_path()
        # [FIX-1] 根据证书是否实际存在选择配置生成器
        _has_cert = self.cfg.cert_chain.exists()
        if _has_cert:
            config = generate_https_config(
                self.cfg.domain, self.cfg.webroot_path, sock_path,
                cache_mode=self.cfg.cache_mode,
                allow_xmlrpc=self.cfg.allow_xmlrpc,
                optimize=self.cfg.optimize,
                cert_chain=str(self.cfg.cert_chain),
                cert_key=str(self.cfg.cert_key),
            )
        else:
            config = generate_http_production_config(
                self.cfg.domain, self.cfg.webroot_path, sock_path,
                cache_mode=self.cfg.cache_mode,
                allow_xmlrpc=self.cfg.allow_xmlrpc,
                optimize=self.cfg.optimize,
            )
        if self.cfg.optimize:
            logging.info(t("info_open_file_cache"))
        if self.cfg.cache_mode == "fastcgi" and not self.cfg.dry_run:
            # [V3.2.15] P0-3: 使用 _nginx_safe_name 而非 systemd_prefix,
            # 与 generate_https_config / generate_http_production_config
            # 中 fastcgi_cache_path 的 keys_zone 名称保持一致。
            safe_name = _nginx_safe_name(self.cfg.domain)
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

        # [V3.2.1] N-2: 根据证书状态选择 scheme, 防御 HTTP-only 调用场景
        _scheme = "https" if self.cfg.cert_chain.exists() else "http"
        url = f"{_scheme}://{self.cfg.domain}/"
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
                    encoding='utf-8', errors='replace', timeout=self.HEALTH_CHECK_TIMEOUT + 5, check=False,
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
    # [V3.0.16] P7: WP-CLI 自动完成 WordPress 安装
    # -----------------------------------------------------------------------
    def _wp_auto_install(self) -> None:
        """使用 WP-CLI 自动完成 WordPress 安装向导。

        仅在满足以下所有条件时执行:
          1. --wp-auto-install 参数已指定
          2. WP-CLI 可用
          3. WordPress 尚未完成安装 (wp core is-installed 返回非零)

        管理员密码使用 secrets 模块生成, 写入凭据文件。
        """
        if not self.cfg.wp_auto_install:
            return
        if self.cfg.dry_run:
            return
        if not self._wpcli_bin:
            return

        # 检查是否已安装
        if self._wpcli_check_installed():
            logging.info(t("info_wp_auto_install_skip"))
            return

        # [V3.2.0] F7: 纯字母数字, 避免凭据文件被 shell 工具误解析
        safe_chars = string.ascii_letters + string.digits
        admin_pass = ''.join(secrets.choice(safe_chars) for _ in range(32))
        admin_user = "admin"
        admin_email = self.cfg.email or f"admin@{self.cfg.domain}"
        site_title = self.cfg.domain.split('.')[0].capitalize()

        result = self._run_wpcli(
            "core", "install",
            # [FIX-4] 根据证书状态选择 URL scheme
            "--url={scheme}://{domain}".format(
                scheme="https" if self.cfg.cert_chain.exists() else "http",
                domain=self.cfg.domain,
            ),
            f"--title={site_title}",
            f"--admin_user={admin_user}",
            f"--admin_password={admin_pass}",
            f"--admin_email={admin_email}",
            "--skip-email",
            timeout=120, quiet=True,
        )
        if result:
            logging.info(t("info_wp_auto_install", user=admin_user))
            # [V3.2.18] P1: store admin creds; summary functions write to disk
            self._wp_admin_info = {
                "user": admin_user,
                "pass": admin_pass,
                "email": admin_email,
            }
            # [V3.2.18] P1: update path — cred file already exists, append directly
            cred_file = Path(
                f"/root/.wp_credentials_{self.cfg.systemd_prefix}.txt"
            )
            if cred_file.exists():
                try:
                    # [V3.2.23] P1-4: enforce 0600 before append — existing file may
                    # have been created with wrong permissions (e.g. umask mismatch).
                    # Use os.open(O_APPEND) so the mode is applied on creation;
                    # also explicitly chmod to tighten pre-existing files.
                    _cred_line = (
                        f"\n===== WordPress Admin =====\n"
                        f"Admin User : {admin_user}\n"
                        f"Admin Pass : {admin_pass}\n"
                        f"Admin Email: {admin_email}\n"
                    )
                    try:
                        os.chmod(str(cred_file), 0o600)
                    except OSError:
                        pass
                    _afd = os.open(
                        str(cred_file),
                        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                        0o600,
                    )
                    try:
                        os.write(_afd, _cred_line.encode("utf-8"))
                        os.fsync(_afd)  # [V3.2.71] BUG-4: 补全 fsync，确保密码落盘
                    finally:
                        os.close(_afd)
                except OSError:
                    pass
        else:
            logging.warning(t("warn_wp_auto_install_fail",
                              domain=self.cfg.domain))

    # -----------------------------------------------------------------------
    # 证书域名提取 (V3.0.13 N1)
    # -----------------------------------------------------------------------
    def _default_cert_domain_args(self) -> list:
        """N6: 返回默认 certbot -d 参数，委托 _build_domain_args() 统一处理。"""
        return self._build_domain_args(include_www=True)

    def _get_cert_domains(self) -> list:
        """N1: 从已有证书的 SAN 中提取域名列表。

        读取 self.cfg.cert_chain（由 SiteConfig 初始化时通过 _probe_cert_paths()
        探测所得的实际路径，兼容标准路径与 snap/certbot-auto 非标安装）的
        Subject Alternative Names，返回 ["-d", "domain", "-d", "www.domain", ...]
        格式的参数列表。

        [V3.1.0] P5: 更新 docstring，与实际使用 self.cfg.cert_chain 的代码一致，
        删除原先硬编码路径的误导性描述。
        证书不存在或解析失败时返回默认列表（含 www）。
        """
        cert_file = self.cfg.cert_chain  # [V3.0.19] D1: 使用初始化时探测的路径
        if not cert_file.exists():
            logging.info(t("info_renew_cert_not_found_www"))
            return self._default_cert_domain_args()

        try:
            r = subprocess.run(
                ["openssl", "x509", "-noout", "-text", "-in", str(cert_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=10, check=False,
            )
            if r.returncode != 0:
                return self._default_cert_domain_args()

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
                return self._default_cert_domain_args()

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
            return self._default_cert_domain_args()

    # -----------------------------------------------------------------------
    # 证书续期
    # -----------------------------------------------------------------------
    def renew_cert(self, force: bool = False):
        logging.info(t("info_renew_check", domain=self.cfg.domain))

        # [V3.1.1] P3: 确保持久化 deploy hook 存在.
        # 覆盖从旧版本升级后直接 renew 而未执行 update/deploy 的场景.
        # 有了持久 hook 后, 下方的内联 --deploy-hook 已移除 (P2).
        self._install_certbot_deploy_hook()

        # 证书到期预检：输出剩余天数，方便运维观测
        cert_file = self.cfg.cert_chain  # [V3.0.19] D1: 使用初始化时探测的路径
        if cert_file.exists() and not self.cfg.dry_run:
            try:
                r = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout",
                     "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', timeout=10, check=False,
                )
                if r.returncode == 0 and r.stdout.strip():
                    logging.info(t("info_cert_expiry", expiry=r.stdout.strip()))
                # 检查是否 30 天内到期
                r2 = subprocess.run(
                    ["openssl", "x509", "-checkend", str(30 * 86400),
                     "-noout", "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', timeout=10, check=False,
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
        # [V3.2.57] 使用 _build_certbot_cmd() 与 apply_cert 共享命令骨架
        _renew_domains = self._get_cert_domains()
        cmd = self._build_certbot_cmd(
            _renew_domains,
            email=self.cfg.email,   # 优先用账户 email；空则自动追加 --register-unsafely-without-email
            quiet=True,
            # [V3.1.1] P2: 内联 --deploy-hook 已移除.
            # Nginx reload 由持久化 renewal-hook 统一负责:
            # /etc/letsencrypt/renewal-hooks/deploy/01-reload-nginx.sh
        )
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
        return bool(success)  # [V3.2.71] BUG-6: 显式 bool，与函数契约一致

    # -----------------------------------------------------------------------
    # Redis 对象缓存 (V2.9.8)
    # -----------------------------------------------------------------------
    # [V3.0.9] C1: Redis 服务名统一检测点，消除三处重复逻辑
    # ===================================================================
    # [V3.2.0] 共享本地编译基础设施
    # ===================================================================

    def _ensure_build_deps(self, extra_pkgs: list = None) -> bool:
        """安装本地源码编译所需的公共依赖。

        公共依赖: gcc / make / git
        调用方可通过 extra_pkgs 追加额外包（如 php-devel/php-pear for PECL,
        pcre-devel/zlib-devel for Nginx 模块编译）。

        返回 True 表示依赖安装成功（或已就绪），False 表示失败。
        失败时记录 diag_build_deps_fail 提示；不抛异常，不阻断部署。
        """
        logging.info(t("diag_build_deps_install"))
        base_pkgs_rpm = ["gcc", "make", "git"]
        base_pkgs_deb = ["gcc", "make", "git"]

        all_pkgs_rpm = base_pkgs_rpm + (extra_pkgs or [])
        all_pkgs_deb = base_pkgs_deb + (extra_pkgs or [])

        if self.pkg_mgr in ("dnf", "yum"):
            ok = bool(self.run_cmd(
                [self.pkg_mgr, "install", "-y"] + all_pkgs_rpm,
                quiet=True, timeout=180,
            ))
        elif self.pkg_mgr == "apt":
            ok = bool(self.run_cmd(
                ["apt", "install", "-y"] + all_pkgs_deb,
                quiet=True, timeout=180,
            ))
        else:
            ok = False

        if ok:
            logging.info(t("ok_build_deps_ready"))
        else:
            logging.warning(t("diag_build_deps_fail"))
        return ok

    def _compile_php_redis_extension(self) -> bool:
        """从 PECL 源码编译安装 PHP Redis 扩展。

        使用 _ensure_build_deps() 共享编译依赖安装逻辑（与 Brotli 编译合并）。
        编译目录在函数内临时创建，结束后自动清理。
        失败静默返回 False，不阻断部署。
        """
        # [V3.2.29] BUG-G: dry_run 模式下跳过 PECL 编译
        if self.cfg.dry_run:
            logging.info("[DRY-RUN] Skipping PHP Redis PECL compilation.")
            return False
        logging.info(t("info_php_redis_pecl_start"))

        # 公共依赖 + PECL 专用依赖
        # [FIX-C6] EL10 上 php-pear 可能需要 EPEL 或叫 php-pear-*
        if self.pkg_mgr in ("dnf", "yum"):
            _pecl_extra = ["php-devel"]
            # php-pear: 先尝试标准包名，失败后 pecl 可能已随 php-devel 安装
            # [V3.2.59] BUG-5: dnf5 不支持 `info --available`；
            # 与 _brotli_install_deps 保持一致，改用 `install -y --dry-run`
            # [V3.2.60] BUG-A: --dry-run 是 dnf4/5 专属选项，yum (EL7) 不支持；
            # 与 _brotli_install_deps 保持一致：dnf → --dry-run，yum → info
            for _pear_name in ("php-pear", "php-pear-noarch"):
                _pear_chk = subprocess.run(
                    [self.pkg_mgr, "install", "-y", "--dry-run", _pear_name]
                    if self.pkg_mgr == "dnf" else
                    [self.pkg_mgr, "info", _pear_name],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', timeout=15, check=False,
                )
                if _pear_chk.returncode == 0:
                    _pecl_extra.append(_pear_name)
                    break
            else:
                _pecl_extra.append("php-pear")  # 尝试装，失败不致命
        else:
            _pecl_extra = ["php-dev", "php-pear"]
        if not self._ensure_build_deps(
            extra_pkgs=_pecl_extra
        ):
            return False

        _pecl = shutil.which("pecl")
        if not _pecl:
            logging.warning(t("warn_php_redis_pecl_fail", e="pecl not found after dep install"))
            return False

        try:
            # [PATCH-M3] 用 Python 直接构造 20 个换行作为 stdin，
            # 完全绕过 shell，兼容 Debian/Ubuntu (dash) 和 RHEL (bash)
            _pecl_r = subprocess.run(
                [_pecl, "install", "redis"],
                input="\n" * 20,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=300, check=False,
            )
            if _pecl_r.returncode != 0:
                raise RuntimeError(_pecl_r.stderr[:400])

            # 写入 ini 配置（RHEL 路径；apt 系 php-dev 通常自动加载）
            # [V3.2.15] P2-5: 原子写入, 与其他配置文件风格一致
            # [V3.2.17] P2-4: 扩展 ini 路径覆盖 Debian/Ubuntu
            # mods-available 机制, 否则 php -m 看不到 redis 扩展
            _ini_candidates = [
                Path("/etc/php.d/50-redis.ini"),               # RHEL/CentOS
                Path("/etc/php/conf.d/50-redis.ini"),          # 通用
            ]
            # Debian/Ubuntu: 写入版本化 mods-available 并创建 symlink
            for _ma in sorted(glob.glob("/etc/php/*/mods-available"), reverse=True):
                _ini_candidates.insert(0, Path(_ma) / "redis.ini")
                break
            # [V3.2.22] P2-2: 写入 ini 后执行 php -m 验证扩展已加载；
            # 某些混合环境（如 RHEL→Ubuntu 迁移）同时存在多套 ini 目录，
            # 仅写第一个匹配目录可能不是 PHP-FPM 实际读取的路径。
            _redis_loaded = False
            for _ini in _ini_candidates:
                if not _ini.parent.is_dir():
                    continue
                WPDeployManager._safe_write_file(
                    _ini, "extension=redis.so\n", mode=0o644,
                )
                # Debian/Ubuntu mods-available 需 phpenmod 激活
                if "/mods-available/" in str(_ini):
                    _phpenmod = shutil.which("phpenmod")
                    if _phpenmod:
                        subprocess.run(
                            [_phpenmod, "redis"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=15, check=False,
                        )
                # 验证 PHP CLI 是否已加载 redis 扩展
                try:
                    _php_bin = shutil.which("php") or "php"
                    _chk = subprocess.run(
                        [_php_bin, "-m"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding='utf-8', errors='replace', timeout=10, check=False,
                    )
                    if "redis" in _chk.stdout.lower():
                        _redis_loaded = True
                        break
                    else:
                        logging.debug(
                            "redis ext not visible via php -m after writing %s; "
                            "trying next candidate", _ini
                        )
                except Exception as _vm_e:
                    logging.debug("php -m check failed: %s", _vm_e)
                    # 无法验证时保守跳过，让后续候选路径继续尝试
                    break
            if not _redis_loaded:
                logging.warning(
                    "redis extension written to ini but not detected by php -m; "
                    "manual verification recommended"
                )

            logging.info(t("ok_php_redis_pecl"))
            return True

        except Exception as _e:
            logging.warning(t("warn_php_redis_pecl_fail", e=_e))
            return False

    # ===================================================================
    # [V3.2.0] 阶段失败诊断与自动修复
    # ===================================================================

    def _try_repair(self, stage: str, repairs: list) -> bool:
        """通用修复执行器。

        Args:
            stage:   阶段名称（用于日志展示）
            repairs: list of (描述: str, 修复函数: callable, 还原函数: callable | None)
                     修复函数返回 True 表示修复成功；还原函数在修复失败时调用。

        返回 True 表示至少有一项修复成功并经过验证；False 表示所有修复均失败。
        """
        logging.info(t("diag_header", stage=stage))
        for desc, fix_fn, rollback_fn in repairs:
            logging.info(t("diag_repair_try", desc=desc))
            try:
                ok = fix_fn()
            except Exception as _fe:
                ok = False
                logging.debug("  repair exception: %s", _fe)
            if ok:
                logging.info(t("diag_repair_ok", desc=desc))
                return True
            # 修复失败 → 尝试还原
            logging.warning(t("diag_repair_fail", desc=desc))
            if rollback_fn:
                logging.warning(t("diag_rollback"))
                try:
                    rollback_fn()
                    logging.info(t("diag_rollback_ok"))
                except Exception as _re:
                    logging.error(t("diag_rollback_fail", e=_re))
        logging.info(t("diag_no_fix"))
        return False

    def _diagnose_pkg_failure(self, failed_pkgs: list) -> bool:
        """诊断并修复包安装失败问题。

        常见原因及修复策略:
          1. 缓存过期         → 清理缓存并重试
          2. EPEL 未启用      → 安装 EPEL 并重试（仅 RHEL 系）
          3. 依赖冲突         → yum/apt --fix-broken 尝试修复

        返回 True 表示修复后安装成功。
        """
        def _clean_and_retry():
            if self.pkg_mgr in ("dnf", "yum"):
                self.run_cmd([self.pkg_mgr, "clean", "all"], quiet=True)
                self.run_cmd([self.pkg_mgr, "makecache"], quiet=True, timeout=60)
            elif self.pkg_mgr == "apt":
                self.run_cmd(["apt", "clean"], quiet=True)
                self.run_cmd(["apt", "update"], quiet=True, timeout=120)
            return bool(self.run_cmd(
                [self.pkg_mgr if self.pkg_mgr != "apt" else "apt",
                 "install", "-y"] + failed_pkgs,
                quiet=False, timeout=300, stream=True,  # [PATCH-STREAM-2]
            ))

        def _install_epel_retry():
            if self.pkg_mgr not in ("dnf", "yum"):
                return False
            _epel_ok = bool(self.run_cmd(
                [self.pkg_mgr, "install", "-y", "epel-release"],
                quiet=True, timeout=120,
            ))
            if not _epel_ok:
                return False
            return bool(self.run_cmd(
                [self.pkg_mgr, "install", "-y"] + failed_pkgs,
                quiet=False, timeout=300, stream=True,  # [PATCH-STREAM-2]
            ))

        def _fix_broken():
            if self.pkg_mgr == "apt":
                self.run_cmd(["apt", "--fix-broken", "install", "-y"], quiet=True)
                return bool(self.run_cmd(
                    ["apt", "install", "-y"] + failed_pkgs,
                    quiet=False, timeout=300, stream=True,  # [PATCH-STREAM-2]
                ))
            elif self.pkg_mgr in ("dnf", "yum"):
                self.run_cmd([self.pkg_mgr, "distro-sync", "-y"], quiet=True, timeout=180)
                return bool(self.run_cmd(
                    [self.pkg_mgr, "install", "-y"] + failed_pkgs,
                    quiet=False, timeout=300,
                ))
            return False

        repairs = [
            (t("diag_pkg_clean_retry"), _clean_and_retry, None),
            (t("diag_pkg_epel_install"), _install_epel_retry, None),
            (t("diag_pkg_broken_deps"), _fix_broken, None),
        ]
        return self._try_repair("install_packages", repairs)

    def _nginx_reset_conflicting_conf(self):
        # type: () -> bool
        """从 conf.d 中检测并重命名导致 nginx -t 失败的配置文件。

        优先从 stderr 精确匹配问题文件; 未命中时回退逐文件检测 (上限 10 次)。
        返回 nginx restart 是否成功。
        """
        # [V3.2.5] A-15: 先运行一次 nginx -t, 从 stderr 提取问题文件名,
        # 避免逐文件 fork nginx -t (大量 .conf 时极慢)
        _conf_d = Path("/etc/nginx/conf.d")
        _ts = time.strftime("%Y%m%d%H%M%S")
        _current_conf = self.cfg.nginx_conf.name if self.cfg.nginx_conf else ""
        _t_init = subprocess.run(
            ["nginx", "-t"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', check=False, timeout=10,
        )
        if _t_init.returncode == 0:
            return bool(self.run_cmd(
                ["systemctl", "restart", "nginx"], quiet=True, timeout=30,
            ))
        _err_text = (_t_init.stderr + _t_init.stdout).lower()
        _renamed_any = False
        # 精确匹配: 从 stderr 中查找被引用的 conf.d 文件
        for _f in sorted(_conf_d.glob("*.conf")):
            if _f.name == _current_conf:
                continue
            if str(_f).lower() in _err_text or _f.name.lower() in _err_text:
                _bak = _f.with_suffix(".conf.bak." + _ts)
                _f.rename(_bak)
                logging.info("  重命名冲突配置: %s → %s", _f.name, _bak.name)
                _renamed_any = True
        if not _renamed_any:
            # stderr 未指向具体文件, 回退到逐文件检测 (罕见路径)
            # [V3.2.8] M-3: 追踪所有被重命名的文件；找到真正的问题文件后
            # 恢复之前被误禁的正常配置。
            _max_attempts = 10  # [PATCH-M7] 避免大量 .conf 时 fork 过多
            _attempt_count = 0
            _sequentially_renamed = []   # [(orig_path, bak_path), ...]
            for _f in sorted(_conf_d.glob("*.conf")):
                if _f.name == _current_conf:
                    continue
                if _attempt_count >= _max_attempts:  # [PATCH-M7]
                    # [V3.2.10] M-3: 达到上限时未找到问题文件，
                    # 必须全量恢复已被误移除的正常配置。
                    for _orig, _b in _sequentially_renamed:
                        try:
                            _b.rename(_orig)
                            logging.info(
                                "  达上限全量恢复: %s → %s",
                                _b.name, _orig.name,
                            )
                        except OSError as _re2:
                            logging.warning(
                                "  恢复配置失败: %s (%s)", _b.name, _re2
                            )
                    logging.warning(
                        "  逐文件检测已达上限 (%d 次), 停止; 如仍有冲突请手动检查",
                        _max_attempts,
                    )
                    break
                _attempt_count += 1
                _bak = _f.with_suffix(".conf.bak." + _ts)
                _f.rename(_bak)
                logging.info("  重命名冲突配置: %s → %s", _f.name, _bak.name)
                _sequentially_renamed.append((_f, _bak))
                _t2 = subprocess.run(
                    ["nginx", "-t"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', check=False, timeout=10,
                )
                if _t2.returncode == 0:
                    # 最后一个是真正的问题文件，其余的应当恢复
                    for _orig, _b in _sequentially_renamed[:-1]:
                        try:
                            _b.rename(_orig)
                            logging.info(
                                "  恢复误禁配置: %s → %s", _b.name, _orig.name
                            )
                        except OSError as _re:
                            logging.warning(
                                "  恢复配置失败: %s (%s)", _b.name, _re
                            )
                    break
            else:
                # [V3.2.17] P1-3: for 正常结束 (未 break) — 所有文件
                # 都被重命名但 nginx -t 仍失败, 全量恢复防止配置丢失
                for _orig, _b in _sequentially_renamed:
                    try:
                        _b.rename(_orig)
                        logging.info(
                            "  全量恢复: %s → %s", _b.name, _orig.name
                        )
                    except OSError as _re3:
                        logging.warning(
                            "  恢复配置失败: %s (%s)", _b.name, _re3
                        )
                # [V3.2.34] P-5: 逐个移除失败时尝试成对检测 —
                # 两个单独合法的配置可能因 server_name 冲突等原因
                # 组合后导致 nginx -t 失败。
                if len(_sequentially_renamed) >= 2:
                    logging.info(
                        "  尝试成对冲突检测 (%d 个文件)...",
                        len(_sequentially_renamed),
                    )
                    _pair_fixed = False
                    # 仅对少量文件尝试 (O(n²) 但 n 通常 < 5)
                    _sr_files = [_o for _o, _b in _sequentially_renamed]
                    if len(_sr_files) <= 8:
                        for _pi in range(len(_sr_files)):
                            for _pj in range(_pi + 1, len(_sr_files)):
                                _fa, _fb_f = _sr_files[_pi], _sr_files[_pj]
                                _ba = _fa.with_suffix(".conf.bak." + _ts)
                                _bb = _fb_f.with_suffix(".conf.bak." + _ts)
                                try:
                                    if _fa.exists():
                                        _fa.rename(_ba)
                                    if _fb_f.exists():
                                        _fb_f.rename(_bb)
                                    _pt = subprocess.run(
                                        ["nginx", "-t"],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        timeout=10, check=False,
                                    )
                                    if _pt.returncode == 0:
                                        logging.info(
                                            "  成对冲突: %s + %s",
                                            _fa.name, _fb_f.name,
                                        )
                                        _pair_fixed = True
                                        break
                                    # 恢复这对, 试下一对
                                    if _ba.exists():
                                        _ba.rename(_fa)
                                    if _bb.exists():
                                        _bb.rename(_fb_f)
                                except OSError:
                                    # 恢复尽力而为
                                    for _x, _y in [(_ba, _fa), (_bb, _fb_f)]:
                                        if _x.exists() and not _y.exists():
                                            try:
                                                _x.rename(_y)
                                            except OSError:
                                                pass
                            if _pair_fixed:
                                break
        return bool(self.run_cmd(
            ["systemctl", "restart", "nginx"], quiet=True, timeout=30,
        ))

    def _diagnose_nginx_failure(self) -> bool:
        """诊断并修复 Nginx 启动失败。

        常见原因:
          1. 80/443 端口被占用  → lsof/ss 探测 + 停止占用进程
          2. 配置语法错误       → nginx -t 输出 + 重命名冲突配置
          3. SELinux 阻断       → 补充 setsebool 配置

        返回 True 表示 Nginx 成功启动。
        """
        # 记录 nginx -t 输出便于诊断
        _t = subprocess.run(
            ["nginx", "-t"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', check=False, timeout=10,
        )
        if _t.returncode != 0:
            logging.warning(t("diag_found", desc=t("diag_nginx_config_error")))
            logging.warning("  nginx -t: %s", (_t.stderr or _t.stdout)[:500])

        def _kill_port80_and_restart():
            # 探测占用 80 端口的进程
            _ss = subprocess.run(
                ["ss", "-tlnp", "sport", "=", ":80"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', check=False, timeout=5,
            )
            if "nginx" not in _ss.stdout.lower():
                # 有非 nginx 进程占用 80 端口 → 停止 Apache 等
                for _svc in ("apache2", "httpd", "lighttpd"):
                    self.run_cmd(["systemctl", "stop", _svc], quiet=True)
            return bool(self.run_cmd(
                ["systemctl", "restart", "nginx"], quiet=True, timeout=30,
            ))

        def _selinux_fix_and_restart():
            self.run_cmd(["setsebool", "-P", "httpd_can_network_connect", "1"], quiet=True)
            self.run_cmd(["setsebool", "-P", "httpd_unified", "1"], quiet=True)
            return bool(self.run_cmd(
                ["systemctl", "restart", "nginx"], quiet=True, timeout=30,
            ))

        repairs = [
            (t("diag_nginx_kill_port80"), _kill_port80_and_restart, None),
            (t("diag_nginx_reset_conf"), self._nginx_reset_conflicting_conf, None),
            (t("diag_selinux_fix"), _selinux_fix_and_restart, None),
        ]
        return self._try_repair("nginx_start", repairs)



    def _diagnose_phpfpm_failure(self, svc: str) -> bool:
        """诊断并修复 PHP-FPM 启动失败。

        常见原因:
          1. Pool 配置中 user/group 不存在
          2. listen.owner/listen.group 权限错误
          3. 之前的调参写入了语法错误
        """
        def _fix_pool_user():
            # [V3.2.29] BUG-A: 使用 self.nginx_user 替代硬编码 www-data,
            # RHEL/CentOS 上 Nginx 用户为 nginx 而非 www-data。
            _target_user = self.nginx_user
            _fixed = False
            for _cpath in self._get_php_conf_paths():
                try:
                    _content = Path(_cpath).read_text(encoding="utf-8")
                    _new = re.sub(r'^(user\s*=\s*)\S+$', r'\g<1>' + _target_user, _content, flags=re.M)
                    _new = re.sub(r'^(group\s*=\s*)\S+$', r'\g<1>' + _target_user, _new, flags=re.M)
                    _new = re.sub(r'^(listen\.owner\s*=\s*)\S+$', r'\g<1>' + _target_user, _new, flags=re.M)
                    _new = re.sub(r'^(listen\.group\s*=\s*)\S+$', r'\g<1>' + _target_user, _new, flags=re.M)
                    if _new != _content:
                        # [V3.2.25] BUG-A: 原 write_text() 为非原子写入，中断时
                        # PHP-FPM 池配置文件将被截断，导致服务无法启动。
                        # 改用 _safe_write_file() 保证原子替换 (O_CREAT+rename)。
                        if self._safe_write_file(_cpath, _new, mode=0o644):
                            _fixed = True
                except Exception:
                    pass
            return _fixed and bool(self.run_cmd(
                ["systemctl", "restart", svc], quiet=True, timeout=30,
            ))

        def _fix_pool_nginx_user():
            _fixed = False
            for _cpath in self._get_php_conf_paths():
                try:
                    _content = Path(_cpath).read_text(encoding="utf-8")
                    _new = patch_php_fpm_pool_user(_content, self.nginx_user)
                    if _new != _content:
                        # [V3.2.25] BUG-A: 同 _fix_pool_user 修复，原子写入。
                        if self._safe_write_file(_cpath, _new, mode=0o644):
                            _fixed = True
                except Exception:
                    pass
            return _fixed and bool(self.run_cmd(
                ["systemctl", "restart", svc], quiet=True, timeout=30,
            ))

        repairs = [
            (t("diag_phpfpm_socket_fix"), _fix_pool_nginx_user, None),
            (t("diag_phpfpm_conf_reset"), _fix_pool_user, None),
        ]
        return self._try_repair(f"phpfpm({svc})", repairs)

    def _diagnose_mariadb_failure(self) -> bool:
        """诊断并修复 MariaDB 启动/连接失败。

        常见原因:
          1. Socket 文件路径与配置不一致
          2. innodb_buffer_pool_size 超过可用内存（调优配置有误）
          3. 磁盘空间不足
          4. 数据目录权限错误
        """
        def _remove_tuning_restart():
            """回滚调优配置，以默认配置重新启动。"""
            _removed = False
            for _conf_dir in ("/etc/mysql/conf.d", "/etc/my.cnf.d"):
                _f = Path(_conf_dir) / "wp-bootstrap-tuning.cnf"
                if _f.exists():
                    _bak = _f.with_suffix(".cnf.bak")
                    try:
                        _f.rename(_bak)
                        _removed = True
                        logging.info("  已备份调优配置: %s → %s", _f.name, _bak.name)
                    except OSError:
                        pass
            if _removed:
                return bool(self.run_cmd(
                    ["systemctl", "restart", self.db_svc], quiet=True, timeout=60,
                ))
            return False

        def _fix_datadir_perms():
            """修复数据目录权限（常见于 Docker/LXC 环境）。"""
            for _data_dir in ("/var/lib/mysql", "/var/lib/mariadb"):
                if Path(_data_dir).exists():
                    self.run_cmd(
                        ["chown", "-R", "mysql:mysql", _data_dir], quiet=True,
                    )
            return bool(self.run_cmd(
                ["systemctl", "restart", self.db_svc], quiet=True, timeout=60,
            ))

        def _extend_wait_retry():
            """延长等待时间，等待慢速存储上的 InnoDB 初始化完成。"""
            time.sleep(15)
            self.run_cmd(
                ["systemctl", "start", self.db_svc], quiet=True, timeout=90,
            )
            return self._wait_db_ready(max_wait=60)

        def _rollback_tuning():
            for _conf_dir in ("/etc/mysql/conf.d", "/etc/my.cnf.d"):
                _f = Path(_conf_dir) / "wp-bootstrap-tuning.cnf"
                _bak = _f.with_suffix(".cnf.bak")
                if _bak.exists() and not _f.exists():
                    try:
                        _bak.rename(_f)
                    except OSError:
                        pass

        repairs = [
            (t("diag_mariadb_socket_wait"), _extend_wait_retry, None),
            (t("diag_mariadb_recover"), _remove_tuning_restart, _rollback_tuning),
            (t("diag_mariadb_corrupt"), _fix_datadir_perms, None),
        ]
        return self._try_repair("mariadb_init", repairs)

    def _diagnose_ssl_failure(self, domain: str) -> bool:
        """诊断并修复 SSL 证书签发前置条件失败。

        常见原因:
          1. 防火墙未开放 80/443 端口
          2. certbot 遗留锁文件
          3. webroot 路径不存在或无写权限
          4. DNS 未生效（提示用户，无法自动修复）

        返回 True 表示前置条件已修复，可以重新尝试签发；
        返回 False 表示需要人工干预。
        """
        def _open_firewall():
            _ok = False
            if shutil.which("firewall-cmd"):
                self.run_cmd(
                    ["firewall-cmd", "--permanent",
                     "--add-service=http", "--add-service=https"],
                    quiet=True,
                )
                _ok = bool(self.run_cmd(
                    ["firewall-cmd", "--reload"], quiet=True,
                ))
            if shutil.which("ufw"):
                self.run_cmd(["ufw", "allow", "80/tcp"], quiet=True)
                self.run_cmd(["ufw", "allow", "443/tcp"], quiet=True)
                _ok = bool(self.run_cmd(["ufw", "reload"], quiet=True))
            if shutil.which("iptables"):
                self.run_cmd(
                    ["iptables", "-I", "INPUT", "-p", "tcp",
                     "--dport", "80", "-j", "ACCEPT"], quiet=True,
                )
                self.run_cmd(
                    ["iptables", "-I", "INPUT", "-p", "tcp",
                     "--dport", "443", "-j", "ACCEPT"], quiet=True,
                )
                _ok = True
            return _ok

        def _remove_certbot_lock():
            _lock_dirs = [
                "/var/lib/letsencrypt/.certbot.lock",
                "/tmp/.certbot.lock",
                # [V3.2.5] A-12: Snap 安装的 certbot 锁文件路径
                "/snap/certbot/common/.certbot.lock",
            ]
            _removed = False
            for _lk in _lock_dirs:
                if Path(_lk).exists():
                    try:
                        Path(_lk).unlink()
                        _removed = True
                    except OSError:
                        pass
            return _removed

        def _fix_webroot():
            try:
                _wr = self.cfg.webroot_path
                _wr.mkdir(parents=True, exist_ok=True)
                _acme = _wr / ".well-known" / "acme-challenge"
                _acme.mkdir(parents=True, exist_ok=True)
                os.chmod(str(_wr), 0o755)
                return True
            except OSError:
                return False

        repairs = [
            (t("diag_ssl_firewall_open"), _open_firewall, None),
            (t("diag_ssl_certbot_lock_remove"), _remove_certbot_lock, None),
            (t("diag_ssl_webroot_fix"), _fix_webroot, None),
        ]
        return self._try_repair(f"ssl_preflight({domain})", repairs)

    # ===================================================================
    # [END V3.3.0]
    # ===================================================================

    def _detect_redis_service_name(self) -> str:
        """Detect the Redis systemd service name (redis vs redis-server).

        Returns 'redis-server' on Debian/Ubuntu when that unit exists,
        'redis' otherwise (RHEL/CentOS/Alibaba Cloud Linux).
        [V3.2.12] P2-11: 结果缓存到 self._redis_svc_name。
        """
        if self._redis_svc_name:
            return self._redis_svc_name
        if self.pkg_mgr == "apt":
            try:
                _r = subprocess.run(
                    ["systemctl", "list-unit-files", "redis-server.service"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                if _r.returncode == 0 and "redis-server" in _r.stdout:
                    self._redis_svc_name = "redis-server"
                    return self._redis_svc_name
            except Exception:
                pass
        # [FIX-EL10] 检测 valkey (RHEL 10+ Redis 替代品)
        try:
            _r = subprocess.run(
                ["systemctl", "list-unit-files", "valkey.service"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if _r.returncode == 0 and "valkey" in _r.stdout:
                self._redis_svc_name = "valkey"
                return self._redis_svc_name
        except Exception:
            pass
        self._redis_svc_name = "redis"
        return self._redis_svc_name

    def _redis_ensure_running(self, _redis_svc):
        # type: (str) -> bool
        """确保 Redis 服务运行中; 未安装时自动安装包 + PHP 扩展。

        返回 True 表示 Redis 已就绪, False 表示启动失败应跳过缓存设置。
        """
        if self.run_cmd(["systemctl", "is-active", _redis_svc], quiet=True):
            return True

        # [V3.2.20] P6: update --redis 路径下 Redis 可能未安装,
        # 先检测并安装 Redis 包 + PHP 扩展, 防止后续操作静默失败
        _has_redis_bin = bool(
            shutil.which("redis-server") or shutil.which("redis-cli")
            or shutil.which("valkey-server") or shutil.which("valkey-cli")  # [FIX-EL10]
        )
        if not _has_redis_bin:
            logging.info("[V3.2.20] P6: Redis not installed, auto-installing...")
            if self.pkg_mgr in ("dnf", "yum"):
                # [FIX-C3] 多包名候选: EL10 可能无 redis, 用 valkey 替代
                _r_installed = False
                for _r_pkg in ("redis", "valkey", "redis7"):
                    if self.run_cmd(
                        [self.pkg_mgr, "install", "-y", _r_pkg],
                        quiet=True, timeout=120,
                    ):
                        _r_installed = True
                        logging.info("[FIX-C3] Installed: %s", _r_pkg)
                        break
                if not _r_installed:
                    logging.warning(
                        "[FIX-C3] Redis/Valkey auto-install failed; "
                        "skipping Redis cache setup."
                    )
                    return False
            elif self.pkg_mgr == "apt":
                self.run_cmd(
                    ["apt", "install", "-y", "redis-server"],
                    quiet=True, timeout=120,
                )
            # 同步安装 PHP Redis 扩展 (update 路径未走 install_packages)
            _php_redis_ok = False
            try:
                _pr_r = subprocess.run(
                    ["php", "-m"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                if _pr_r.returncode == 0:
                    _php_redis_ok = "redis" in [
                        x.strip().lower()
                        for x in _pr_r.stdout.splitlines()
                    ]
            except Exception:
                pass
            if not _php_redis_ok:
                if self.pkg_mgr in ("dnf", "yum"):
                    _pr_done = False
                    for _rpkg in (
                        "php-pecl-redis6", "php-pecl-redis5",
                        "php-pecl-redis", "php-redis",
                    ):
                        if self.run_cmd(
                            [self.pkg_mgr, "install", "-y", _rpkg],
                            quiet=True, timeout=60,
                        ):
                            _pr_done = True
                            break
                    if not _pr_done:
                        self._compile_php_redis_extension()
                elif self.pkg_mgr == "apt":
                    self.run_cmd(
                        ["apt", "install", "-y", "php-redis"],
                        quiet=True, timeout=60,
                    )
                # [V3.2.30] BUG-J: 安装扩展后立即重启 FPM 使其加载,
                # 否则后续 wp redis enable 因扩展未加载而失败
                self.run_cmd(
                    ["systemctl", "restart", self.php_fpm_svc],
                    quiet=True,
                )
                # 等待 FPM 就绪 (socket 重建需要时间)
                time.sleep(2)
            # 重新检测服务名 (安装后可能变更)
            self._redis_svc_name = ""
            _redis_svc = self._detect_redis_service_name()

        _redis_start = self.run_cmd(["systemctl", "enable", "--now", _redis_svc], quiet=True)
        # [V3.2.3] M-4: Redis 启动失败时提前返回
        if not _redis_start:
            logging.warning(
                "Redis service failed to start; skipping Redis cache setup. "
                "Check: systemctl status %s", _redis_svc,
            )
            return False
        # [V3.2.14] P1-1: systemctl 返回后 Redis 可能仍未就绪,
        # 等待最多 10s 直到 redis-cli ping 成功
        _redis_cli = shutil.which("redis-cli") or shutil.which("valkey-cli")  # [FIX-EL10]
        if _redis_cli:
            for _rw in range(10):
                try:
                    _rp = subprocess.run(
                        [_redis_cli, "ping"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        encoding='utf-8', errors='replace', timeout=3, check=False,
                    )
                    if _rp.returncode == 0 and "PONG" in _rp.stdout:
                        break
                except Exception:
                    pass
                time.sleep(1)

        return True

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

        # [V3.2.35] 拆分: 确保 Redis 运行
        if not self._redis_ensure_running(_redis_svc):
            return

        if not self._wpcli_bin:
            logging.info(t("info_redis_manual"))
            return
        # [V3.2.0] P2: WordPress 未安装时跳过, 避免 "site not installed" 错误
        if not self._wpcli_check_installed():
            logging.warning(t("warn_plugin_wp_not_installed",
                              domain=self.cfg.domain))
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
    # [V3.0.16] P12: Cloudflare Real IP 还原
    # -----------------------------------------------------------------------
    # 内置的 Cloudflare IP 段 (2024-12 版本, 作为获取失败时的回退)
    _CF_IPV4_DEFAULTS = [
        "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22",
        "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
        "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22",
        "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
        "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    ]
    _CF_IPV6_DEFAULTS = [
        "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32",
        "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29",
        "2c0f:f248::/32",
    ]

    def _setup_cloudflare_real_ip(self) -> None:
        """配置 Nginx Cloudflare Real IP 还原。

        从 Cloudflare 官方 API 获取最新 IP 段, 写入
        /etc/nginx/conf.d/cloudflare-real-ip.conf (全局生效)。
        获取失败时使用内置默认值。

        借鉴 WordOps / SlickStack 的 Cloudflare 集成。
        """
        if not self.cfg.cloudflare:
            return
        if self.cfg.dry_run:
            logging.info(t("dry_run_cloudflare"))
            return

        import urllib.request
        import urllib.error

        ipv4_ranges = list(self._CF_IPV4_DEFAULTS)
        ipv6_ranges = list(self._CF_IPV6_DEFAULTS)

        # [V3.2.0] 尝试从 Cloudflare 获取最新 IP 段 (带 User-Agent + JSON 备路径)
        _cf_ua = {"User-Agent": "wp-ssl-bootstrap/" + __version__}
        _cf_v4_fetched = False
        _cf_v6_fetched = False
        # [V3.2.0] F4: 分离 IPv4/IPv6 try 块, 避免一方失败拖累另一方
        # 路径 1a: IPv4 文本端点
        try:
            _req4 = urllib.request.Request(
                "https://www.cloudflare.com/ips-v4", headers=_cf_ua)
            with urllib.request.urlopen(_req4, timeout=15) as resp:
                _lines = resp.read(256 * 1024).decode("utf-8").strip().splitlines()
                if len(_lines) >= 5:
                    ipv4_ranges = [_l.strip() for _l in _lines if _l.strip()]
                    _cf_v4_fetched = True
        except Exception:
            pass
        # 路径 1b: IPv6 文本端点
        try:
            _req6 = urllib.request.Request(
                "https://www.cloudflare.com/ips-v6", headers=_cf_ua)
            with urllib.request.urlopen(_req6, timeout=15) as resp:
                _lines = resp.read(256 * 1024).decode("utf-8").strip().splitlines()
                if len(_lines) >= 3:
                    ipv6_ranges = [_l.strip() for _l in _lines if _l.strip()]
                    _cf_v6_fetched = True
        except Exception:
            pass
        _cf_fetched = _cf_v4_fetched and _cf_v6_fetched
        # 路径 2: JSON API 兜底 (仅补全未获取的协议)
        if not _cf_fetched:
            try:
                _req_j = urllib.request.Request(
                    "https://api.cloudflare.com/client/v4/ips",
                    headers=_cf_ua)
                with urllib.request.urlopen(_req_j, timeout=15) as resp:
                    _cf_j = json.loads(resp.read(256 * 1024).decode("utf-8"))
                    _res = _cf_j.get("result", {})
                    _v4 = _res.get("ipv4_cidrs", [])
                    _v6 = _res.get("ipv6_cidrs", [])
                    # [V3.2.0] F4: 仅补全文本端点未获取的协议
                    if not _cf_v4_fetched and len(_v4) >= 5:
                        ipv4_ranges = _v4
                        _cf_v4_fetched = True
                    if not _cf_v6_fetched and len(_v6) >= 3:
                        ipv6_ranges = _v6
                        _cf_v6_fetched = True
                    _cf_fetched = _cf_v4_fetched or _cf_v6_fetched
            except Exception:
                pass
        if _cf_fetched:
            logging.info(t("info_cloudflare_ip_fetched",
                           n4=len(ipv4_ranges), n6=len(ipv6_ranges)))
        else:
            logging.warning(t("warn_cloudflare_fetch_fail",
                              e="all CF endpoints failed; using built-in defaults"))

        # [V3.2.5] A-9: 使用 ipaddress 模块做严格 CIDR 验证,
        # 替代正则, 彻底拒绝无效地址 (如 ZZZZ::/999)
        import ipaddress as _ipaddr
        _valid_v4 = []
        for _r in ipv4_ranges:
            try:
                _ipaddr.ip_network(_r if "/" in _r else _r + "/32",
                                   strict=False)
                _valid_v4.append(_r)
            except ValueError:
                pass
        _valid_v6 = []
        for _r in ipv6_ranges:
            try:
                _ipaddr.ip_network(_r if "/" in _r else _r + "/128",
                                   strict=False)
                _valid_v6.append(_r)
            except ValueError:
                pass
        ipv4_ranges = _valid_v4
        ipv6_ranges = _valid_v6
        if not ipv4_ranges:
            logging.warning(t("warn_cloudflare_write_fail",
                              e="no valid IPv4 CIDRs after validation"))
            return

        # 生成 Nginx 配置
        lines = [
            "# [V3.2.0] Auto-generated by WP-SSL-Bootstrap",
            "# Cloudflare Real IP restoration",
            "# Update: python3 wp_ssl_bootstrap.py update"
            " --domain DOMAIN --cloudflare",
            "",
        ]
        for cidr in ipv4_ranges:
            lines.append(f"set_real_ip_from {cidr};")
        for cidr in ipv6_ranges:
            lines.append(f"set_real_ip_from {cidr};")
        lines.extend([
            "",
            "real_ip_header CF-Connecting-IP;",
            "real_ip_recursive on;",
        ])

        conf_path = Path("/etc/nginx/conf.d/cloudflare-real-ip.conf")
        try:
            # [V3.2.1] N-3: 原子写入, 与 MariaDB/sysctl 调优配置保持一致
            if not self._safe_write_file(
                conf_path, "\n".join(lines) + "\n", mode=0o644,
            ):
                raise OSError("_safe_write_file failed: " + str(conf_path))
            # 验证配置有效
            if self.run_cmd(["nginx", "-t"], quiet=True):
                logging.info(t("info_cloudflare_real_ip", path=conf_path))
                # [V3.1.0] P3: 统一使用门控函数 _safe_reload_nginx()
                # (V3.0.16 P8 建立)，避免绕过 nginx -t 二次校验直接 reload。
                # 注：_safe_reload_nginx() 内部已含 dry_run 保护与 nginx -t，
                # 此处外层的 nginx -t 用于决定是否回滚，两者职责不同，共存合理。
                self._safe_reload_nginx()  # [V3.1.0] P3
            else:
                # 配置无效 — 回滚
                try:
                    conf_path.unlink()
                except OSError:
                    pass
                logging.warning(t("warn_cloudflare_write_fail",
                                  e="nginx -t failed after write"))
        except OSError as e:
            logging.warning(t("warn_cloudflare_write_fail", e=e))

    # -----------------------------------------------------------------------
    # Brotli 压缩 (V2.9.8 自动检测)
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # [V3.2.32] _compile_brotli_module() 拆分: 子方法
    # -----------------------------------------------------------------------
    def _brotli_get_nginx_version(self):
        # type: () -> str
        """获取当前 Nginx 版本号, 失败返回空字符串。"""
        try:
            _r = subprocess.run(
                ["nginx", "-v"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=10, check=False)
            _m = re.search(r'nginx/(\d+\.\d+\.\d+)', _r.stdout + _r.stderr)
            if _m:
                return _m.group(1)
        except Exception:
            pass
        return ""

    def _brotli_install_deps(self):
        # type: () -> bool
        """安装 Brotli 编译依赖, 返回是否成功。"""
        if self.pkg_mgr in ("dnf", "yum"):
            # [FIX-C2] EL10 弃用 PCRE1, 仅有 pcre2-devel;
            # EL7-9 两者都有, pcre2-devel 更现代。优先 pcre2, 回退 pcre1。
            # [FIX-B1][V3.2.60 BUG-C 注释修正] `--dry-run` 对 dnf4 和 dnf5 均有效；
            # yum (EL7) 不支持 --dry-run，故三元式保持 dnf → dry-run / yum → info。
            # self._is_dnf5 无需参与此判断（不必区分 dnf4 与 dnf5，两者行为一致）。
            _pcre_pkg = "pcre2-devel"
            _pcre_test = subprocess.run(
                [self.pkg_mgr, "install", "-y", "--dry-run", "pcre2-devel"]
                if self.pkg_mgr == "dnf" else
                [self.pkg_mgr, "info", "pcre2-devel"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=15, check=False,
            )
            # dnf5 dry-run 返回非零 = 包不存在; dnf4 info 同理
            if _pcre_test.returncode != 0:
                _pcre_pkg = "pcre-devel"
            _extra = [_pcre_pkg, "zlib-devel", "openssl-devel"]
        elif self.pkg_mgr == "apt":
            _extra = ["libpcre3-dev", "zlib1g-dev", "libssl-dev",
                       "libbrotli-dev"]
        else:
            return False
        if not self._ensure_build_deps(extra_pkgs=_extra):
            return False
        if self.pkg_mgr in ("dnf", "yum"):
            # [FIX-C7] brotli-devel 可能在不同仓库, 候选包名尝试
            for _bd_pkg in ("brotli-devel", "libbrotli-devel"):
                if self.run_cmd(
                    [self.pkg_mgr, "install", "-y", _bd_pkg],
                    quiet=True, timeout=60,
                ):
                    break
        if not shutil.which("git"):
            logging.warning(t("warn_brotli_git_unavail"))
            return False
        return True

    def _brotli_download_and_clone(self, build_dir, nver):
        # type: (Path, str) -> bool
        """下载 Nginx 源码 + 克隆 ngx_brotli, 返回是否成功。"""
        _tar = build_dir / ("nginx-%s.tar.gz" % nver)
        _url = "https://nginx.org/download/nginx-%s.tar.gz" % nver
        _dl = (
            ["curl", "-sSL", "--connect-timeout", "15",
             "-o", str(_tar), _url]
            if shutil.which("curl") else
            ["wget", "-q", "--connect-timeout=15",
             "-O", str(_tar), _url])
        if not self.run_cmd(_dl, timeout=120, quiet=True):
            logging.warning(t("warn_brotli_src_dl_fail"))
            return False
        if not self.run_cmd(
            ["tar", "-xzf", str(_tar), "-C", str(build_dir)],
            timeout=60, quiet=True,
        ):
            return False
        _ngx_br = build_dir / "ngx_brotli"
        _git_shallow_sub_flag = []
        try:
            _gv_r = subprocess.run(
                ["git", "--version"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', errors='replace', timeout=5, check=False)
            _gv_m = re.search(r"(\d+)\.(\d+)", _gv_r.stdout or "")
            if _gv_m and (int(_gv_m.group(1)), int(_gv_m.group(2))) >= (2, 9):
                _git_shallow_sub_flag = ["--shallow-submodules"]
        except Exception:
            pass
        _git_urls = ["https://github.com/google/ngx_brotli.git"]
        if _is_china_cloud():
            _git_urls.insert(0,
                "https://ghfast.top/https://github.com/"
                "google/ngx_brotli.git")
        for _gu in _git_urls:
            if _ngx_br.exists():
                shutil.rmtree(str(_ngx_br), ignore_errors=True)
            if self.run_cmd(
                ["git", "clone", "--depth=1",
                 "--recurse-submodules"] + _git_shallow_sub_flag + [
                 _gu, str(_ngx_br)],
                timeout=120, quiet=True,
            ):
                return True
        logging.warning(t("warn_brotli_clone_fail"))
        return False

    def _brotli_configure_and_make(self, build_dir, nver):
        # type: (Path, str) -> list
        """配置并编译 Brotli 模块, 返回 .so 文件列表或空列表。"""
        _src = build_dir / ("nginx-%s" % nver)
        _ngx_br = build_dir / "ngx_brotli"
        _cr = subprocess.run(
            ["./configure", "--with-compat",
             "--add-dynamic-module=%s" % _ngx_br],
            cwd=str(_src),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', timeout=120, check=False)
        if _cr.returncode != 0:
            _persistent_log = Path("/tmp/nginx_brotli_configure.log")
            try:
                _persistent_log.write_text(
                    _cr.stderr, encoding='utf-8', errors='replace')
                logging.warning(
                    t("warn_brotli_configure_fail") + ": %s  [log: %s]",
                    _cr.stderr.strip()[:300], _persistent_log)
            except OSError:
                logging.warning(
                    t("warn_brotli_configure_fail") + ": %s",
                    _cr.stderr.strip()[:300])
            return []
        _nproc = os.cpu_count() or 1
        _mr = subprocess.run(
            ["make", "-j%d" % _nproc, "modules"],
            cwd=str(_src),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', timeout=300, check=False)
        if _mr.returncode != 0:
            logging.warning(
                t("warn_brotli_make_fail") + ": %s",
                _mr.stderr.strip()[:300])
            return []
        _mod_dir = Path("/usr/lib64/nginx/modules")
        if not _mod_dir.is_dir():
            _mod_dir = Path("/usr/lib/nginx/modules")
        _mod_dir.mkdir(parents=True, exist_ok=True)
        _objs = _src / "objs"
        _sos = []
        for _so_name in ("ngx_http_brotli_filter_module.so",
                         "ngx_http_brotli_static_module.so"):
            _s = _objs / _so_name
            _d = _mod_dir / _so_name
            if _s.exists():
                shutil.copy2(str(_s), str(_d))
                os.chmod(str(_d), 0o755)
                _sos.append(str(_d))
        if not _sos:
            logging.warning(t("warn_brotli_no_so"))
        return _sos

    def _brotli_install_load_module(self, _sos):
        # type: (list) -> bool
        """写入 load_module 配置并验证, 返回是否成功。

        失败时自动回滚 .so 和 load_module 配置。
        """
        _lm_conf = None
        for _cd in ("/usr/share/nginx/modules",
                     "/etc/nginx/modules-enabled"):
            if Path(_cd).is_dir():
                _lm_conf = Path(_cd) / "50-mod-brotli.conf"
                break
        _injected_nginx_main = False
        _nginx_main_conf = Path("/etc/nginx/nginx.conf")
        if _lm_conf is None:
            _me_dir = Path("/etc/nginx/modules-enabled")
            try:
                _me_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _lm_conf = _me_dir / "50-mod-brotli.conf"
            try:
                _nm_text = _nginx_main_conf.read_text(encoding="utf-8")
                _inc_pat = r"include\s+/etc/nginx/modules-enabled/\*\.conf"
                if not re.search(_inc_pat, _nm_text):
                    _inject = "include /etc/nginx/modules-enabled/*.conf;\n"
                    _inject_done = False
                    for _kw in ("events", "http"):
                        _pat = r"^[ \t]*" + re.escape(_kw) + r"[ \t]*\{"
                        for _km in re.finditer(_pat, _nm_text, re.M):
                            _ln_s = _nm_text.rfind("\n", 0, _km.start()) + 1
                            _pre = _nm_text[_ln_s:_km.start()].strip()
                            if _pre.startswith("#"):
                                continue
                            _nm_backup = _nm_text
                            _patched = (_nm_text[:_ln_s] + _inject
                                        + _nm_text[_ln_s:])
                            if self._safe_write_file(
                                _nginx_main_conf, _patched, mode=0o644
                            ):
                                if self.run_cmd(["nginx", "-t"], quiet=True):
                                    _inject_done = True
                                    _injected_nginx_main = True
                                else:
                                    self._safe_write_file(
                                        _nginx_main_conf, _nm_backup,
                                        mode=0o644)
                                    _lm_direct = "".join(
                                        "load_module %s;\n" % p
                                        for p in _sos)
                                    self._safe_write_file(
                                        _nginx_main_conf,
                                        _lm_direct + _nm_backup,
                                        mode=0o644)
                                    _lm_conf = None
                                    _inject_done = True
                            break
                        if _inject_done:
                            break
                    if not _inject_done:
                        _lm_direct = "".join(
                            "load_module %s;\n" % p for p in _sos)
                        self._safe_write_file(
                            _nginx_main_conf,
                            _lm_direct + _nm_text, mode=0o644)
                        _lm_conf = None
            except OSError:
                pass
        if _lm_conf is not None:
            _lm_lines = ["# [V3.2.32] Auto-compiled by WP-SSL-Bootstrap"]
            for _p in _sos:
                _lm_lines.append("load_module %s;" % _p)
            if not self._safe_write_file(
                _lm_conf, "\n".join(_lm_lines) + "\n", mode=0o644
            ):
                logging.warning("Failed to write brotli load_module config")
                for _so_p in _sos:
                    try:
                        Path(_so_p).unlink()
                    except OSError:
                        pass
                return False
        if not self.run_cmd(["nginx", "-t"], quiet=True):
            logging.warning(t("warn_brotli_nginx_test_fail"))
            if _lm_conf is not None:
                try:
                    _lm_conf.unlink()
                except OSError:
                    pass
            else:
                try:
                    _current = _nginx_main_conf.read_text(encoding="utf-8")
                    _cleaned = _current
                    for _so_p in _sos:
                        _cleaned = _cleaned.replace(
                            "load_module %s;\n" % _so_p, "")
                    _cleaned = _cleaned.replace(
                        "include /etc/nginx/modules-enabled/*.conf;\n", "")
                    if _cleaned != _current:
                        self._safe_write_file(
                            _nginx_main_conf, _cleaned, mode=0o644)
                except Exception:
                    pass
            for _p in _sos:
                try:
                    Path(_p).unlink()
                except OSError:
                    pass
            return False
        logging.info(t("ok_brotli_compiled",
            modules=", ".join(Path(p).name for p in _sos)))
        try:
            _pl = Path("/tmp/nginx_brotli_configure.log")
            if _pl.exists():
                _pl.unlink()
        except OSError:
            pass
        return True
    def _compile_brotli_module(self):
        # type: () -> bool
        """从源码编译 ngx_brotli 动态模块。

        [V3.2.32] 重构: 拆分为 4 个子方法。
        """
        _nver = self._brotli_get_nginx_version()
        if not _nver:
            logging.warning(t("warn_brotli_nginx_ver"))
            return False
        logging.info(t("info_brotli_compile_start", ver=_nver))
        if not self._brotli_install_deps():
            return False
        _bd = Path(tempfile.mkdtemp(prefix="nginx_brotli_"))
        try:
            if not self._brotli_download_and_clone(_bd, _nver):
                return False
            _sos = self._brotli_configure_and_make(_bd, _nver)
            if not _sos:
                return False
            return self._brotli_install_load_module(_sos)
        except Exception as e:
            logging.warning(t("warn_brotli_compile_fail", e=e))
            return False
        finally:
            shutil.rmtree(str(_bd), ignore_errors=True)

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
            # [V3.2.0] B1: 尝试多个候选包名 (不同源命名不一致)
            _brotli_installed = False
            for _bpkg in ("nginx-mod-http-brotli",
                          "nginx-module-brotli",
                          "nginx-mod-brotli"):
                if self.run_cmd(
                    [self.pkg_mgr, "install", "-y", _bpkg],
                    quiet=True, timeout=60,
                ):
                    _brotli_installed = True
                    break
            if not _brotli_installed:
                logging.info(t("info_brotli_no_prebuilt"))

        # 检测模块是否可用
        brotli_available = False
        try:
            r = subprocess.run(
                ["nginx", "-V"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace', timeout=10, check=False,
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
            # [V3.2.0] B6: 包安装失败时尝试源码编译
            if self._compile_brotli_module():
                brotli_available = True
            else:
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

        # [V3.2.3] M-1: 原子写入, 与其他配置文件保持一致
        try:
            if not self._safe_write_file(conf_file, conf_content, mode=0o644):
                return
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
        """为站点独立的 Nginx 日志配置 logrotate。

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
            f"        NGINX_PID=\"\"\n"
            f"        for _pidfile in /run/nginx.pid /var/run/nginx.pid; do\n"
            f"            [ -f \"$_pidfile\" ] && NGINX_PID=\"$_pidfile\" && break\n"
            f"        done\n"
            f"        [ -n \"$NGINX_PID\" ] && kill -USR1 $(cat \"$NGINX_PID\") 2>/dev/null || true\n"
            f"    endscript\n"
            f"}}\n"
        )

        try:
            # [V3.2.1] N-3: 原子写入, 与其他配置文件保持一致
            if not self._safe_write_file(conf_file, conf_content, mode=0o644):
                raise OSError("atomic write failed: " + str(conf_file))
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

        # [V3.2.22] P2-3: 检测站点 Nginx 配置中的日志格式。
        # fail2ban filter regex 依赖 Nginx combined 格式（IP 在行首）；
        # 若用户自定义了 JSON 等非标准格式，regex 将完全失效。
        # 检测策略：从站点 conf 文件中提取 access_log 指令，
        #   - 无 format 参数  → 使用默认 combined，安全继续
        #   - format 为 combined / main / combined_ssl / main_ext → 兼容
        #   - 其他自定义格式 → 跳过 fail2ban 并告警用户手动配置
        _COMPAT_LOG_FORMATS = frozenset([
            "combined", "main", "combined_ssl", "main_ext", "",
        ])
        _nginx_conf_path = Path("/etc/nginx/conf.d") / f"{self.cfg.domain}.conf"
        _log_format_ok = True  # 默认允许
        try:
            _nc_text = _nginx_conf_path.read_text(encoding="utf-8")
            # 匹配 access_log /path/to/file [format]; 捕获可选的 format 名
            _alf_match = re.search(
                r'access_log\s+\S+\s*([a-zA-Z0-9_-]*)\s*;',
                _nc_text,
            )
            if _alf_match:
                _fmt_name = _alf_match.group(1).strip().lower()
                if _fmt_name not in _COMPAT_LOG_FORMATS:
                    logging.warning(
                        "[fail2ban] Nginx access_log uses non-standard format '%s'; "
                        "fail2ban combined-format regex will not match. "
                        "Skipping fail2ban setup for %s. "
                        "Please configure fail2ban manually for your log format.",
                        _fmt_name, self.cfg.domain,
                    )
                    _log_format_ok = False
        except OSError:
            pass  # 配置文件不存在时跳过检测，保守继续
        if not _log_format_ok:
            return

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
                "            ^<HOST> .*\"POST /xmlrpc\\.php.* HTTP/\\d\\.\\d\" 429 \\S+\n"  # [PATCH-H1] 移除行尾 $

            )
        else:
            xmlrpc_filter_comment = (
                "# xmlrpc.php: 已被 Nginx deny (403)，任何访问均为异常探测。\n"
            )
            xmlrpc_filter_rule = (
                "            ^<HOST> .*\"(GET|POST) /xmlrpc\\.php.* HTTP/\\d\\.\\d\" 403 \\S+\n"  # [PATCH-H1] 移除行尾 $

            )
        filter_content = (
            "# Auto-generated by WP-SSL-Bootstrap\n"
            "[Definition]\n"
            "# wp-login.php: 登录失败返回 200，成功返回 302，仅匹配 200 减少误封。\n"
            + xmlrpc_filter_comment
            + "failregex = ^<HOST> .*\"POST /wp-login\\.php.* HTTP/\\d\\.\\d\" 200 \\S+\n"  # [PATCH-H1] 移除行尾 $: combined 日志状态码后还有更多字段

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
            f"bantime  = 86400\n"
            f"bantime.increment = true\n"
            f"bantime.rndtime = 1800\n"
        )

        try:
            # [V3.2.1] N-3: 原子写入, 防止截断的配置文件导致 fail2ban 启动失败
            if not self._safe_write_file(filter_file, filter_content, mode=0o644):
                raise OSError("atomic write failed: " + str(filter_file))
            if not self._safe_write_file(jail_file, jail_content, mode=0o644):
                raise OSError("atomic write failed: " + str(jail_file))
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
    # -----------------------------------------------------------------------
    # [V3.0.16] P11: MySQL 周度优化 (mysqlcheck --optimize)
    # -----------------------------------------------------------------------
    def setup_db_optimize_timer(self) -> None:
        """创建 systemd timer 每周运行 mysqlcheck --optimize。

        借鉴 WordOps 周度 mysqlcheck: 回收碎片空间, 更新索引统计。
        --single-transaction 保证 InnoDB 表不锁表。
        仅本地数据库生效; 外置数据库跳过。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_db_optimize"))
            return
        if self.cfg.is_external_db:
            logging.info(t("info_db_optimize_skip_ext"))
            return

        prefix = self.cfg.systemd_prefix

        # 构建 mysqlcheck 命令 (使用全局密码文件)
        # [V3.1.1] P7: 使用运行时探测的绝对路径写入 ExecStart,
        # 避免依赖 systemd 单元的窄 PATH (通常仅 /usr/bin:/bin)。
        _mysqlcheck = self.cfg.mysqlcheck_bin
        _pwd_file = str(self.global_root_pwd_file)
        if self.global_root_pwd_file.exists():
            exec_cmd = (
                # [V3.2.10] L-6: 对 --defaults-extra-file 路径加引号，
                # 与 setup_wp_cron_timer 的 "--path={webroot}" 保护一致。
                # [V3.2.45] BUG-D: 对 mysqlcheck 路径和 pwd_file 路径均应用
                # _sd_escape()，与 setup_wp_cron_timer/setup_systemd 保持一致；
                # 路径含 % $ \\ " 时 systemd unit ExecStart= 不再损坏。
                '"{}" "--defaults-extra-file={}"'.format(
                    _sd_escape(_mysqlcheck),
                    _sd_escape(_pwd_file),
                )
                + " -u root --optimize --single-transaction"
                  " --all-databases"
            )
        else:
            # 无密码文件时使用 socket 认证 (MariaDB 默认)
            # [V3.2.9] L-6: 对 mysqlcheck 路径加引号，与 setup_wp_cron_timer 风格统一
            # [V3.2.45] BUG-D: 同样应用 _sd_escape()
            exec_cmd = (
                '"{}" -u root --optimize'.format(_sd_escape(_mysqlcheck))
                + " --single-transaction --all-databases"
            )

        svc_file = Path(
            f"/etc/systemd/system/{prefix}-db-optimize.service"
        )
        timer_file = Path(
            f"/etc/systemd/system/{prefix}-db-optimize.timer"
        )

        svc_content = (
            f"[Unit]\n"
            f"Description={self.cfg.domain} MariaDB Weekly Optimize\n"
            f"After={self.db_svc}.service\n"
            f"\n"
            f"[Service]\n"
            f"Type=oneshot\n"
            f"User=root\n"
            # [V3.2.9] L-6: 直接 exec，避免 /bin/sh -c 引号嵌套；
            # 与 setup_wp_cron_timer 的 [PATCH-M5] 修复保持风格一致。
            # [V3.2.11] P2-9: ExecStart 中双引号语法需 systemd >= v219
            # (CentOS 7 默认 v219)。v219+ 不展开 $VAR，行为与 shell 不同。
            # [V3.2.12] P1-5: ExecStart 双引号路径语法需 systemd >= v219
            # (CentOS 7 默认恰好 v219，更早的系统可能无法解析)
            f"ExecStart={exec_cmd}\n"
            f"TimeoutStartSec=600\n"
            f"StandardOutput=journal\n"
            f"StandardError=journal\n"
        )

        timer_content = (
            f"[Unit]\n"
            f"Description=Run {self.cfg.domain} MariaDB Optimize Weekly\n"
            f"\n"
            f"[Timer]\n"
            f"OnCalendar=Sun *-*-* 03:00:00\n"
            f"RandomizedDelaySec=1800\n"
            f"Persistent=true\n"
            f"Unit={prefix}-db-optimize.service\n"
            f"\n"
            f"[Install]\n"
            f"WantedBy=timers.target\n"
        )

        if self.atomic_write(svc_file, svc_content, mode=0o644) and \
           self.atomic_write(timer_file, timer_content, mode=0o644):
            self.run_cmd(["systemctl", "daemon-reload"], quiet=True)
            self.run_cmd(
                ["systemctl", "enable", "--now",
                 f"{prefix}-db-optimize.timer"],
                quiet=True,
            )
            logging.info(t("info_db_optimize_timer"))

    # -----------------------------------------------------------------------
    # [V3.0.16] P2: WordPress Cron 系统定时器 (替代 wp-cron.php 页面触发)
    # -----------------------------------------------------------------------
    def setup_wp_cron_timer(self):
        """创建 systemd timer 每 15 分钟触发 wp cron event run。

        WordPress 默认的 wp-cron.php 在每次页面请求时触发, 高并发时成为
        性能瓶颈。注入 DISABLE_WP_CRON=true 后改由此 timer 驱动。

        WP-CLI 可用时使用 `wp cron event run --due-now` (精确只执行到期任务);
        不可用时 fallback 到 `php wp-cron.php`。
        """
        if self.cfg.dry_run:
            logging.info(t("dry_run_wp_cron"))
            return

        webroot = str(self.cfg.webroot_path)
        prefix = self.cfg.systemd_prefix

        # [V3.2.28] BUG-III: 对嵌入 systemd unit 文件双引号上下文的路径做转义。
        # systemd 的 ExecStart= 使用类 shell 引号规则：双引号内 \ 和 " 需转义。
        # 虽然 domain 白名单排除了 " 和 \，php_bin 来自 PATH 扫描，在被篡改
        # 的 PATH 环境下也可能包含特殊字符，统一转义以确保健壮性。
        # [V3.2.43] FIX-7: _sd_escape 提升为模块级函数，setup_systemd() 共用。
        # 此处直接使用模块级 _sd_escape()，无需重复定义。

        if self._wpcli_bin:
            # [V3.2.3] M-7: 使用 -- 分隔路径
            # [V3.2.8] L-6: 对 wpcli_bin 和 --path 加引号，防 webroot 含空格时
            # systemd 解析 ExecStart= 失败（systemd 以空格分割参数）
            exec_cmd = (
                '"{}" cron event run --due-now'
                ' "--path={}" --allow-root --quiet'.format(
                    _sd_escape(self._wpcli_bin),
                    _sd_escape(webroot),
                )
            )
        else:
            # fallback: 直接调用 php wp-cron.php
            # [V3.2.8] L-6: 同样对路径加引号
            php_bin = shutil.which("php") or "php"
            exec_cmd = '"{}" "{}"'.format(
                _sd_escape(php_bin),
                _sd_escape(webroot + "/wp-cron.php"),
            )
            logging.info(t("info_wp_cron_timer_no_wpcli", webroot=webroot))  # [V3.2.44] FIX-12: drop dead guard — already in else branch (self._wpcli_bin is falsy)

        svc_file = Path(f"/etc/systemd/system/{prefix}-wp-cron.service")
        timer_file = Path(f"/etc/systemd/system/{prefix}-wp-cron.timer")

        svc_content = (
            f"[Unit]\n"
            f"Description={self.cfg.domain} WordPress Cron\n"
            f"After=network-online.target {self.db_svc}.service\n"
            f"\n"
            f"[Service]\n"
            f"Type=oneshot\n"
            f"User={self.nginx_user}\n"
            # [PATCH-M5] 直接使用 ExecStart=，避免 /bin/sh -c 引号嵌套问题
            # systemd 直接 exec，路径来自 shutil.which，不含 shell 特殊字符
            f"ExecStart={exec_cmd}\n"
            f"TimeoutStartSec=120\n"
            f"StandardOutput=journal\n"
            f"StandardError=journal\n"
        )

        timer_content = (
            f"[Unit]\n"
            f"Description=Run {self.cfg.domain} WordPress Cron every 15min\n"
            f"\n"
            f"[Timer]\n"
            f"OnCalendar=*:0/15\n"
            f"RandomizedDelaySec=60\n"
            f"Persistent=true\n"
            f"Unit={prefix}-wp-cron.service\n"
            f"\n"
            f"[Install]\n"
            f"WantedBy=timers.target\n"
        )

        if self.atomic_write(svc_file, svc_content, mode=0o644) and \
           self.atomic_write(timer_file, timer_content, mode=0o644):
            self.run_cmd(["systemctl", "daemon-reload"], quiet=True)
            _timer_ok = self.run_cmd(
                ["systemctl", "enable", "--now", f"{prefix}-wp-cron.timer"],
                quiet=True,
            )
            if _timer_ok:
                logging.info(t("info_wp_cron_timer_created"))
            else:
                # [V3.2.5] A-6: timer 创建失败时回滚 DISABLE_WP_CRON,
                # 恢复 WordPress 内置 cron 机制, 防止定时任务完全停止
                logging.warning(
                    "wp-cron timer failed; rolling back DISABLE_WP_CRON "
                    "to restore WordPress built-in cron."
                )
                _wpc = self.cfg.webroot_path / "wp-config.php"
                if _wpc.exists() and not self.cfg.dry_run:
                    try:
                        _wpc_content = _wpc.read_text(encoding="utf-8")
                        _wpc_new = re.sub(
                            r"define\s*\(\s*['\"]DISABLE_WP_CRON['\"]\s*,\s*true\s*\)\s*;[^\n]*",
                            "define('DISABLE_WP_CRON', false); // timer failed, reverted",
                            _wpc_content,
                            flags=re.IGNORECASE,  # [V3.2.19] A2: 兼容 True/TRUE
                        )
                        if _wpc_new != _wpc_content:
                            self._safe_write_file(_wpc, _wpc_new, mode=0o440)
                    except Exception as _rb_e:
                        logging.warning(
                            "DISABLE_WP_CRON rollback failed: %s", _rb_e,
                        )

    def _ensure_wp_cron_constant(self) -> None:
        """确保已有 wp-config.php 包含 DISABLE_WP_CRON 且值为 true。

        update_config() 创建 systemd wp-cron timer, 但老站点的
        wp-config.php 可能缺少此常量 (inject_wp_hardening 仅新站点
        deploy 时执行), 导致页面触发 cron 与 timer 双重执行。

        [V3.2.19] A3: 检查常量值而非仅存在性；timer 回滚可能将值
        改为 false，此时需纠正为 true，否则 cron 双重执行。
        [V3.2.30] BUG-H: 先检查 timer unit 文件存在且 active，
        防止 setup_wp_cron_timer 失败回滚后此函数覆盖为 true
        导致 WordPress 定时任务永久瘫痪。
        """
        if self.cfg.dry_run:
            return
        wp_config = self.cfg.webroot_path / "wp-config.php"
        if not wp_config.exists():
            return
        # [V3.2.30] BUG-H: 仅当 timer 实际可用时才强制 true
        _timer_name = "%s-wp-cron.timer" % self.cfg.systemd_prefix
        _timer_unit = Path("/etc/systemd/system/%s" % _timer_name)
        _timer_active = False
        if _timer_unit.exists():
            try:
                _ta_r = subprocess.run(
                    ["systemctl", "is-active", _timer_name],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                _timer_active = (_ta_r.returncode == 0)
            except Exception:
                pass
        if not _timer_active:
            # Timer 不存在或未激活 -- 不能禁用内置 cron
            # 如果当前值为 true 需回退为 false
            try:
                content = wp_config.read_text(encoding="utf-8")
                _cron_true_pat = re.compile(
                    r"define\s*\(\s*['\"]DISABLE_WP_CRON['\"]\s*,\s*true\s*\)\s*;[^\n]*",
                    re.IGNORECASE,
                )
                if _cron_true_pat.search(content):
                    content = _cron_true_pat.sub(
                        "define('DISABLE_WP_CRON', false); // [V3.2.30] timer inactive, reverted",
                        content,
                    )
                    self._safe_write_file(wp_config, content, mode=0o440)
                    logging.warning(
                        "[BUG-H] wp-cron timer inactive; reverted DISABLE_WP_CRON to false"
                    )
            except Exception as _bh_e:
                logging.debug("BUG-H revert check failed: %s", _bh_e)
            return
        try:
            content = wp_config.read_text(encoding="utf-8")
            # [V3.2.19] A3: 检查值是否已为 true（大小写不敏感）
            _cron_true_pat = re.search(
                r"define\s*\(\s*['\"]DISABLE_WP_CRON['\"]\s*,\s*true\s*\)",
                content, re.IGNORECASE,
            )
            if _cron_true_pat:
                return  # 已正确设为 true
            # 存在但值为 false -> 替换为 true
            _cron_false_pat = re.compile(
                r"define\s*\(\s*['\"]DISABLE_WP_CRON['\"]\s*,\s*false\s*\)\s*;[^\n]*",
                re.IGNORECASE,
            )
            if _cron_false_pat.search(content):
                content = _cron_false_pat.sub(
                    "define('DISABLE_WP_CRON', true); // [V3.2.19] systemd cron",
                    content,
                )
                self._safe_write_file(wp_config, content, mode=0o440)
                return
            # [V3.2.34] P-8: 注入前再次验证 timer 仍 active,
            # 缩小 TOCTOU 窗口 (无法完全消除, 但降低并发 uninstall 风险)。
            try:
                _recheck = subprocess.run(
                    ["systemctl", "is-active", _timer_name],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=3, check=False,
                )
                if _recheck.returncode != 0:
                    logging.warning(
                        "[P-8] Timer %s became inactive during "
                        "wp-config.php update; aborting injection.",
                        _timer_name,
                    )
                    return
            except Exception:
                pass  # 校验失败不阻断, 保守继续注入
            # [V3.2.37] P-6: 注入前通用 define 存在性检查, 防止非标准格式
            # (如变量赋值、常量包裹等) 导致重复追加。
            _any_cron_define = re.search(
                r"define\s*\(\s*['\"]DISABLE_WP_CRON['\"]",
                content, re.IGNORECASE,
            )
            if _any_cron_define:
                logging.debug(
                    "[P-6] DISABLE_WP_CRON define exists (non-standard format), "
                    "skipping injection to avoid duplication."
                )
                return
            # 完全不存在 -> 注入
            inject = "\ndefine('DISABLE_WP_CRON', true); // [V3.1.2] systemd cron\n"
            marker = re.search(
                r"^(?:/\*.*(?:stop editing|停止编辑).*\*/|//.*(?:stop editing|停止编辑))",
                content, re.MULTILINE | re.IGNORECASE,
            )
            if marker:
                pos = marker.start()
                content = content[:pos] + inject + content[pos:]
            else:
                req_pos = content.rfind("require_once")
                if req_pos != -1:  # [V3.2.71] BUG-1: rfind 返回 0 时也应注入
                    content = content[:req_pos] + inject + content[req_pos:]
                else:
                    content += inject
            self._safe_write_file(wp_config, content, mode=0o440)
        except Exception as e:
            logging.warning("DISABLE_WP_CRON injection failed: %s", e)

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
            f"ExecStart=\"{_sd_escape(str(sys.executable))}\" \"{_sd_escape(str(self.cfg.script_path))}\""  # [V3.2.42] FIX-3: quote  # [V3.2.43] FIX-7: _sd_escape
            f" renew --domain {_sd_escape(self.cfg.domain)} --quiet\n"  # [V3.2.71] BUG-5: 与 ExecStart 其他参数保持一致
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

        if self.atomic_write(self.cfg.service_file, service_content, mode=0o644) and \
           self.atomic_write(self.cfg.timer_file, timer_content, mode=0o644):
            self.run_cmd(["systemctl", "daemon-reload"], quiet=True)
            self.run_cmd(
                ["systemctl", "enable", "--now", f"{self.cfg.systemd_prefix}-ssl.timer"],
                quiet=True,
            )
            logging.info(t("ok_systemd", timer=f"{self.cfg.systemd_prefix}-ssl.timer"))
        else:
            logging.error(t("err_systemd_write"))

    # -----------------------------------------------------------------------
    # 部署完成摘要
    # -----------------------------------------------------------------------
    def _append_wp_admin_credentials(self, cred_content):
        """[V3.2.21-AUDIT] P1-3: 共享 WP 管理员凭据处理。

        单一事实来源: _print_http_summary() 与 print_final_summary()
        共用此方法，消除 80%% 重复代码，防止修一处漏另一处导致
        管理员密码段丢失。
        """
        cred_file = Path(
            f"/root/.wp_credentials_{self.cfg.systemd_prefix}.txt"
        )
        if self._wp_admin_info:
            cred_content += (
                f"\n===== WordPress Admin =====\n"
                f"Admin User : {self._wp_admin_info['user']}\n"
                f"Admin Pass : {self._wp_admin_info['pass']}\n"
                f"Admin Email: {self._wp_admin_info['email']}\n"
            )
        elif not self.cfg.dry_run and cred_file.exists():
            try:
                _existing_cred = cred_file.read_text(encoding="utf-8")
                _admin_start = _existing_cred.find(
                    "===== WordPress Admin ====="
                )
                if _admin_start >= 0:
                    _admin_block = _existing_cred[_admin_start:]
                    _next_eq = _admin_block.find(
                        "\n=====",
                        len("===== WordPress Admin =====")
                    )
                    if _next_eq > 0:
                        _admin_block = _admin_block[:_next_eq]
                    cred_content += (
                        "\n" + _admin_block.rstrip("\n") + "\n"
                    )
            except OSError:
                pass
        return cred_content

    def _print_http_summary(self):
        """--skip-ssl 模式的部署完成摘要。"""
        cred_file = Path(
            f"/root/.wp_credentials_{self.cfg.systemd_prefix}.txt"
        )
        db_host_arg = f" -h {self.cfg.db_host}" if self.cfg.is_external_db else ""
        # [V3.2.2] P-1: 统一 f-string
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
            f"{t('cred_site_status')}\n"
            f"  {sys.executable} {self.cfg.script_path} status --domain {self.cfg.domain}\n\n"
            f"{t('cred_backup')}\n"
            f"  {sys.executable} {self.cfg.script_path} backup --domain {self.cfg.domain}\n\n"
            f"===== Enable SSL =====\n"
            f"  python3 {self.cfg.script_path} enable-ssl --domain {self.cfg.domain} --email YOUR_EMAIL\n"
        )
        # [V3.2.21-AUDIT] P1-3: 委托共享方法处理 WP 管理员凭据
        cred_content = self._append_wp_admin_credentials(cred_content)
        if not self.cfg.dry_run:
            self._safe_write_file(cred_file, cred_content)

        print("\n" + "=" * 50)
        print(t("deploy_success"))
        print("=" * 50)
        print(t("deploy_url_http", domain=self.cfg.domain))
        # [V3.2.66] BUG-D-4: 裸域名时追加显示 www 访问地址
        if _should_add_www(self.cfg.domain):
            print(f"              http://www.{self.cfg.domain}")
        print(t("deploy_cred", path=cred_file))
        print(t("info_skip_ssl_hint",
                 script=self.cfg.script_path,
                 domain=self.cfg.domain))
        print("=" * 50)


    def print_final_summary(self):
        cred_file = Path(f"/root/.wp_credentials_{self.cfg.systemd_prefix}.txt")
        db_host_arg = f" -h {self.cfg.db_host}" if self.cfg.is_external_db else ""
        # [V3.2.65] BUG-C-4: 仅裸域名添加 www 变体, 子域名不添加
        _cred_cert_d = f"-d {self.cfg.domain}"
        if _should_add_www(self.cfg.domain):
            _cred_cert_d += f" -d www.{self.cfg.domain}"
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
            f"    {_cred_cert_d} \\\n"
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
        # [V3.2.21-AUDIT] P1-3: 委托共享方法处理 WP 管理员凭据
        cred_content = self._append_wp_admin_credentials(cred_content)
        # [V2.9.5] 原子写入，从创建瞬间即为 0600
        if not self.cfg.dry_run:
            self._safe_write_file(cred_file, cred_content)

        print("\n" + "=" * 50)
        print(t("deploy_success"))
        print("=" * 50)
        print(t("deploy_url", domain=self.cfg.domain))
        # [V3.2.66] BUG-D-3: 裸域名时追加显示 www 访问地址
        if _should_add_www(self.cfg.domain):
            print(f"              https://www.{self.cfg.domain}")
        print(t("deploy_cred", path=cred_file))
        print("=" * 50)

    # -----------------------------------------------------------------------
    # 备份
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # [V3.2.32] backup() 拆分: 子方法
    # -----------------------------------------------------------------------
    def _backup_load_root_password(self):
        # type: () -> None
        """加载 MariaDB root 密码用于数据库备份。

        优先级: CLI --db-root-pass > 全局密码文件。
        """
        if not self.db_root_pass and self.cfg.db_root_pass_input:
            _cli_pwd = self.cfg.db_root_pass_input
            if re.fullmatch(r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _cli_pwd):
                self.db_root_pass = _cli_pwd
                logging.info(t("info_backup_use_cli_pwd"))
            else:
                logging.warning(t("warn_db_root_unsafe_skip"))
        if not self.db_root_pass and self.global_root_pwd_file.exists():
            try:
                _raw_pwd = self.global_root_pwd_file.read_text(
                    encoding="utf-8").strip()
                if _raw_pwd and re.fullmatch(
                    r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _raw_pwd
                ):
                    self.db_root_pass = _raw_pwd
                elif _raw_pwd:
                    logging.warning(t("warn_backup_pwd_bad_chars"))
            except OSError:
                pass

    def _backup_database(self, db_dump):
        # type: (Path) -> bool
        """执行数据库 dump 到 gzip 压缩文件, 返回是否成功。"""
        if not self.db_root_pass:
            logging.warning(t("warn_db_pwd_unavail_backup"))
            self._exit_code = 1
            return False
        defaults_file = self._write_mysql_defaults_file(self.db_root_pass)
        try:
            dump_cmd = [
                "mysqldump",
                "--defaults-extra-file=%s" % defaults_file,
                "-u", "root",
                "--single-transaction", "--quick",
            ]
            if self.cfg.is_external_db:
                dump_cmd.extend(["-h", self.cfg.db_host, "--compress"])
            dump_cmd.append(self.cfg.db_name)
            dump_timeout = 600 if self.cfg.is_external_db else 300
            return self._backup_run_dump_pipeline(
                dump_cmd, db_dump, dump_timeout)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass

    def _backup_run_dump_pipeline(self, dump_cmd, db_dump, timeout):
        # type: (list, Path, int) -> bool
        """mysqldump | gzip 管道执行, 返回是否成功。"""
        dump_ok = False
        p_dump = None
        p_gzip = None
        gzip_fd = None
        try:
            p_dump = subprocess.Popen(
                dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _dump_raw_fd = os.open(
                str(db_dump),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                gzip_fd = os.fdopen(_dump_raw_fd, 'wb')
            except Exception:
                os.close(_dump_raw_fd)
                raise
            p_gzip = subprocess.Popen(
                ["gzip"], stdin=p_dump.stdout,
                stdout=gzip_fd, stderr=subprocess.PIPE)
            # [V3.2.39] P3: 子进程已通过 dup2 继承 fd, 父进程拷贝无用途;
            # 及时关闭以释放资源并防止 finally 中潜在的双重关闭。
            gzip_fd.close()
            gzip_fd = None
            p_dump.stdout.close()
            import concurrent.futures  # [V3.2.36-P2] 延迟导入
            _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                _stderr_fut = _ex.submit(p_dump.stderr.read)
                try:
                    # [V3.2.40] BUG-C (false positive, defensive fix):
                    # gzip_err is assigned by communicate() below. If
                    # TimeoutExpired is raised, the inner handler re-raises
                    # immediately so gzip_err is never referenced in that path
                    # (outer except TimeoutExpired doesn't use it). The
                    # initialisation here is purely defensive against future
                    # refactors that might restructure the exception flow.
                    gzip_err = b""
                    _, gzip_err = p_gzip.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # [V3.2.38] FIX-4: kill 前尝试收集 stderr 用于超时诊断
                    _timeout_diag = []
                    try:
                        _partial = _stderr_fut.result(timeout=3)
                        if _partial:
                            _timeout_diag.append(
                                _partial.decode("utf-8", errors="replace")[:200])
                    except Exception:
                        pass
                    if p_gzip is not None and p_gzip.stderr:
                        try:
                            _gz_partial = p_gzip.stderr.read(512)
                            if _gz_partial:
                                _timeout_diag.append(
                                    _gz_partial.decode("utf-8", errors="replace"))
                        except Exception:
                            pass
                    for _p in (p_dump, p_gzip):
                        if _p is not None and _p.poll() is None:
                            try:
                                _p.kill()
                            except OSError:
                                pass
                    if p_dump and p_dump.stderr:
                        try:
                            p_dump.stderr.close()
                        except Exception:
                            pass
                    if _timeout_diag:
                        logging.debug(
                            "[FIX-4] backup timeout stderr: %s",
                            " | ".join(_timeout_diag)[:400])
                    raise
                try:
                    dump_err = _stderr_fut.result(
                        timeout=max(30, timeout // 4))
                except Exception:
                    dump_err = b""
                    if p_dump and p_dump.stderr:
                        try:
                            p_dump.stderr.close()
                        except Exception:
                            pass
            finally:
                # [V3.2.39] P2: Python 3.6 shutdown(wait=True) 无超时参数,
                # 若 p_dump.stderr.read 线程卡住则主进程永久阻塞。
                # Future 结果已通过带超时的 .result() 获取,
                # 此处 wait=False 即可; 底层守护线程随进程退出回收。
                _ex.shutdown(wait=False)
            p_dump.wait(timeout=30)
            if (p_dump.returncode == 0
                    and p_gzip.returncode == 0
                    and db_dump.exists()
                    and db_dump.stat().st_size > 0):
                logging.info(t("ok_db_backup", path=db_dump))
                dump_ok = True
            else:
                err_msg = (dump_err or gzip_err or b"").decode(
                    "utf-8", errors="replace")
                logging.warning(t("warn_db_backup_fail",
                                  err=err_msg[:200]))
        except subprocess.TimeoutExpired:
            logging.warning(t("warn_db_backup_timeout", t=timeout))
        except Exception as e:
            logging.warning(t("warn_db_backup_exception", e=e))
        finally:
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
                        if p.poll() is None:
                            p.kill()
                            p.wait(timeout=5)
                    except Exception:
                        pass
            # [V3.2.37] P-4: gzip_fd 在 finally 中关闭, 即使 TimeoutExpired
            # raise 跳出内层 try, finally 仍保证执行。此注释防止未来重构误删。
            if gzip_fd is not None:
                try:
                    gzip_fd.close()
                except Exception:
                    pass
        if not dump_ok:
            logging.warning(t("warn_db_dump_incomplete"))
            self._exit_code = 1
            if db_dump.exists():
                try:
                    db_dump.unlink()
                except OSError:
                    pass
        return dump_ok

    def _backup_webroot_files(self, backup_dir):
        # type: (Path) -> None
        """压缩 webroot 目录到备份。"""
        webroot_tar = backup_dir / "webroot.tar.gz"
        if self.cfg.webroot_path.exists():
            result = self.run_cmd(
                ["tar", "-czf", str(webroot_tar),
                 "-C", str(self.cfg.webroot_path.parent),
                 self.cfg.webroot_path.name],
                timeout=600, quiet=True)
            if result:
                logging.info(t("ok_webroot_backup", path=webroot_tar))
            else:
                logging.warning(t("warn_webroot_backup_fail"))
                self._exit_code = 1
        else:
            logging.warning(t("warn_webroot_missing",
                              path=self.cfg.webroot_path))
            self._exit_code = 1

    def _backup_nginx_and_extras(self, backup_dir):
        # type: (Path) -> None
        """备份 Nginx 配置 + Fail2Ban/logrotate 附加配置。"""
        if self.cfg.nginx_conf.exists():
            nginx_bak = backup_dir / self.cfg.nginx_conf.name
            try:
                shutil.copy2(self.cfg.nginx_conf, nginx_bak)
                logging.info(t("ok_nginx_backup", path=nginx_bak))
            except OSError as e:
                logging.warning(t("warn_nginx_bak_copy_fail", e=e))
        _safe_name = self.cfg.systemd_prefix
        _extras_dir = backup_dir / "extras"
        _extra_srcs = [
            (Path("/etc/fail2ban/filter.d/wordpress-%s.conf" % _safe_name),
             "fail2ban-filter-wordpress-%s.conf" % _safe_name),
            (Path("/etc/fail2ban/jail.d/wordpress-%s.conf" % _safe_name),
             "fail2ban-jail-wordpress-%s.conf" % _safe_name),
            (Path("/etc/logrotate.d/nginx-wp-%s" % _safe_name),
             "logrotate-nginx-wp-%s" % _safe_name),
        ]
        _has_extras = any(_src.exists() for _src, _ in _extra_srcs)
        if _has_extras:
            try:
                _extras_dir.mkdir(exist_ok=True)
                _extras_dir.chmod(0o700)
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

    def _backup_verify_and_cleanup(self, backup_dir, keep_count):
        # type: (Path, int) -> None
        """校验备份完整性并清理旧备份。"""
        db_dump = backup_dir / ("%s.sql.gz" % self.cfg.db_name)
        webroot_tar = backup_dir / "webroot.tar.gz"
        gz_files = [f for f in (db_dump, webroot_tar)
                    if f.exists() and f.stat().st_size > 0]
        backup_verified = bool(gz_files)
        for gz_file in gz_files:
            try:
                r = subprocess.run(
                    ["gzip", "-t", str(gz_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', timeout=120, check=False)
                if r.returncode != 0:
                    logging.warning(t("warn_backup_gz_fail",
                        name=gz_file.name,
                        detail=(r.stderr.strip()[:100]
                                if r.stderr else "gzip -t non-zero")))
                    backup_verified = False
            except Exception as e:
                logging.warning(t("warn_backup_integrity_err",
                                  name=gz_file.name, e=e))
                backup_verified = False
        if not backup_verified:
            logging.warning(t("warn_backup_integrity"))
        if keep_count > 0 and backup_verified:
            domain_bak_root = backup_dir.parent
            try:
                all_backups = sorted(
                    [d for d in domain_bak_root.iterdir() if d.is_dir()],
                    key=lambda d: d.name)
                if len(all_backups) > keep_count:
                    to_remove = all_backups[:-keep_count]
                    for old_dir in to_remove:
                        try:
                            shutil.rmtree(old_dir)
                            logging.info(t("info_cleanup_old_bak",
                                           name=old_dir.name))
                        except OSError as e:
                            logging.warning(t("warn_cleanup_old_bak_fail",
                                              name=old_dir.name, e=e))
                    logging.info(t("info_backup_cleanup_summary",
                        keep=keep_count, removed=len(to_remove)))
            except OSError as e:
                logging.warning(t("warn_list_bak_fail", e=e))
    def backup(self, keep_count=5):
        # type: (int) -> None
        """一键备份：数据库 dump + webroot 压缩包 + Nginx 配置。

        [V3.2.32] 重构: 拆分为 6 个子方法, 各自职责单一。
        """
        logging.info(t("info_backup_start", domain=self.cfg.domain))
        if self.cfg.dry_run:
            logging.info(t("dry_run_backup"))
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = self.cfg.backup_base_dir / self.cfg.domain / timestamp
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_dir.chmod(0o700)
        except OSError as e:
            logging.error(t("err_backup_dir", e=e))
            return
        # 1. 加载密码
        self._backup_load_root_password()
        # 2. 数据库 dump
        db_dump = backup_dir / ("%s.sql.gz" % self.cfg.db_name)
        _db_ok = self._backup_database(db_dump)
        # 3. Webroot 压缩
        self._backup_webroot_files(backup_dir)
        # 4. Nginx + 附加配置
        self._backup_nginx_and_extras(backup_dir)
        # 5. 摘要输出
        # [V3.2.34] P-1: 反映 DB dump 实际结果，避免全失败时仍显示成功横幅
        total_size = sum(
            f.stat().st_size for f in backup_dir.rglob("*") if f.is_file())
        total_mb = total_size / (1024 * 1024)
        _has_any_file = any(
            f.is_file() and f.stat().st_size > 0
            for f in backup_dir.rglob("*")
        )
        print("\n" + "=" * 50)
        if _has_any_file:
            print(t("backup_done", path=backup_dir))
        else:
            print("" + t("warn_backup_integrity"))
        print(t("backup_size", mb=total_mb))
        if not _db_ok:
            print("   Database dump failed or was skipped.")
        print("=" * 50 + "\n")
        # 6. 完整性校验 + 旧备份清理
        self._backup_verify_and_cleanup(backup_dir, keep_count)

    # -----------------------------------------------------------------------
    # 状态查询
    # -----------------------------------------------------------------------
    def show_status(self):
        """输出站点运行状态摘要：证书到期、服务状态、定时器、磁盘空间。"""
        domain = self.cfg.domain
        print(t("status_header", domain=domain))

        # 证书信息
        cert_file = self.cfg.cert_chain  # [V3.0.19] D1: 使用初始化时探测的路径
        if cert_file.exists():
            try:
                r = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout",
                     "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', timeout=10, check=False,
                )
                if r.returncode == 0:
                    print(t("status_ssl", info=r.stdout.strip()))
                # 30 天预警
                r2 = subprocess.run(
                    ["openssl", "x509", "-checkend", str(30 * 86400),
                     "-noout", "-in", str(cert_file)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace', timeout=10, check=False,
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
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                status = r.stdout.strip()
                icon = "" if status == "active" else ""
                print(f"{icon} {svc_label} ({svc_name}): {status}")
            except Exception:
                print(t("status_svc_unknown", label=svc_label, name=svc_name))

        # 定时器状态（续期 / wp-cron / db-optimize）
        # [V3.2.10] M-2: 展示本脚本创建的全部定时器
        _timers_to_show = [
            (f"{self.cfg.systemd_prefix}-ssl.timer",         "SSL 续期",   True),
            (f"{self.cfg.systemd_prefix}-wp-cron.timer",    "WP Cron",    False),
            (f"{self.cfg.systemd_prefix}-db-optimize.timer","DB Optimize",False),
        ]
        for _tn, _tlabel, _use_ssl_key in _timers_to_show:
            # 仅展示实际存在的 timer unit
            _unit_file = Path(f"/etc/systemd/system/{_tn}")
            if not _unit_file.exists() and not _use_ssl_key:
                continue
            try:
                _r = subprocess.run(
                    ["systemctl", "is-active", _tn],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    encoding='utf-8', errors='replace', timeout=5, check=False,
                )
                _st = _r.stdout.strip()
                _ic = "" if _st == "active" else ""
                if _use_ssl_key:
                    print(t("status_timer", icon=_ic, name=_tn, status=_st))
                else:
                    print(t("status_timer_generic",
                            icon=_ic, label=_tlabel, name=_tn, status=_st))
            except Exception:
                if _use_ssl_key:
                    print(t("status_timer_unknown", name=_tn))
                else:
                    print(t("status_timer_generic_unknown",
                            label=_tlabel, name=_tn))

        # [PATCH-L7] Brotli 模块状态
        # [V3.2.8] L-1: 使用 t() 国际化
        _brotli_conf = Path("/etc/nginx/conf.d/brotli-wp-bootstrap.conf")
        if _brotli_conf.exists():
            print(t("status_brotli_on", path=_brotli_conf))  # [V3.2.9] M-1
        else:
            print(t("status_brotli_off"))

        # [PATCH-L7] Cloudflare Real IP 状态
        # [V3.2.8] L-1: 使用 t() 国际化
        _cf_conf = Path("/etc/nginx/conf.d/cloudflare-real-ip.conf")
        if _cf_conf.exists():
            print(t("status_cf_realip_on", path=_cf_conf))
        else:
            print(t("status_cf_realip_off"))

        # 磁盘空间
        free_mb = self.get_disk_free_mb(self.cfg.webroot_path)
        icon = "" if free_mb >= 500 else ("" if free_mb >= 200 else "")
        print(t("status_disk", icon=icon, mb=free_mb, path=self.cfg.webroot_path))

        print()

    # -----------------------------------------------------------------------
    # 从备份恢复 (V2.9.8)
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # [V3.2.32] restore() 拆分: 子方法
    # -----------------------------------------------------------------------
    def _restore_locate_backup(self, backup_path):
        # type: (str) -> Path
        """定位备份目录, 返回 Path 或 None。"""
        if backup_path:
            bak_dir = Path(backup_path)
        else:
            domain_bak_root = self.cfg.backup_base_dir / self.cfg.domain
            if not domain_bak_root.exists():
                logging.error(t("err_backup_not_found",
                                path=domain_bak_root))
                return None
            candidates = sorted(
                [d for d in domain_bak_root.iterdir() if d.is_dir()],
                key=lambda d: d.name, reverse=True)
            if not candidates:
                logging.error(t("err_backup_no_items"))
                return None
            bak_dir = candidates[0]
            logging.info(t("info_restore_auto_bak", path=bak_dir))
        if not bak_dir.is_dir():
            logging.error(t("err_backup_not_dir", path=bak_dir))
            return None
        return bak_dir

    def _restore_database(self, bak_dir):
        # type: (Path) -> None
        """从备份恢复数据库。"""
        db_dumps = list(bak_dir.glob("*.sql.gz"))
        if not db_dumps:
            logging.info(t("info_no_db_dump"))
            return
        db_file = db_dumps[0]
        logging.info(t("info_restore_db", name=db_file.name))
        # [V3.2.38] FIX-3: 复用 _backup_load_root_password() 避免逻辑分歧,
        # 原 V3.2.37 P-1 内联代码缺少 warn_backup_pwd_bad_chars 分支。
        self._backup_load_root_password()
        if not self.db_root_pass:
            logging.warning(t("warn_db_pwd_unavail_restore"))
            self._exit_code = 1
            return
        defaults_file = self._write_mysql_defaults_file(self.db_root_pass)
        p_gunzip = None
        p_mysql = None
        # [V3.2.40] BUG-B: initialise before try so the TimeoutExpired handler
        # can join the thread regardless of which communicate()/wait() timed out.
        _gz_drain_t = None
        try:
            host_args = (["-h", self.cfg.db_host]
                         if self.cfg.is_external_db else [])
            mysql_cmd = [
                "mysql",
                "--defaults-extra-file=%s" % defaults_file,
                "-u", "root",
            ] + host_args + [self.cfg.db_name]
            # [V3.2.38] FIX-5: 捕获 gunzip stderr, 便于诊断损坏备份
            # [V3.2.39] P1: 使用后台线程排空 gunzip stderr,
            # 防止 stderr >64KB 时管道缓冲区满导致 gunzip 阻塞写 stdout,
            # 进而使整条 gunzip|mysql 管道死锁。
            p_gunzip = subprocess.Popen(
                ["gunzip", "-c", str(db_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p_mysql = subprocess.Popen(
                mysql_cmd, stdin=p_gunzip.stdout,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p_gunzip.stdout.close()
            # 启动守护线程排空 gunzip stderr, 线程结果通过容器列表传回
            _gz_err_container = [b""]
            def _drain_gunzip_stderr(_pipe, _container):
                try:
                    _container[0] = _pipe.read() or b""
                except Exception:
                    pass
            # [V3.2.42] P3: 移除冗余局部 import，统一使用模块级 _threading
            _gz_drain_t = _threading.Thread(
                target=_drain_gunzip_stderr,
                args=(p_gunzip.stderr, _gz_err_container))
            _gz_drain_t.daemon = True
            _gz_drain_t.start()
            _, mysql_err = p_mysql.communicate(timeout=600)
            p_gunzip.wait(timeout=30)
            _gz_drain_t.join(timeout=10)
            _gunzip_err = _gz_err_container[0]
            if p_mysql.returncode == 0 and p_gunzip.returncode == 0:
                logging.info(t("ok_db_restore"))
            elif p_mysql.returncode == 0 and p_gunzip.returncode != 0:
                # mysql 成功但 gunzip 报错 (罕见: 截断文件部分可读)
                logging.warning(
                    "[FIX-5] DB restore succeeded but gunzip exited %d: %s",
                    p_gunzip.returncode,
                    _gunzip_err.decode("utf-8", errors="replace")[:200])
            else:
                _combined = mysql_err or _gunzip_err or b""
                logging.warning(t("warn_restore_db_fail",
                    err=_combined.decode("utf-8", errors="replace")[:200]))
                self._exit_code = 1
        except subprocess.TimeoutExpired:
            logging.warning(t("warn_db_restore_timeout"))
            self._exit_code = 1
            # [V3.2.40] BUG-B fix: join the drain thread so its stderr pipe
            # reference is released promptly. The finally block closes
            # p_gunzip.stderr first, which unblocks the read(); the join()
            # here then confirms the thread has exited. Under repeated timeout
            # conditions this prevents thread/fd accumulation.
            # NOTE: the finally block runs *after* this except body, so
            # p_gunzip.stderr is still open here; we rely on the thread's own
            # except-pass to handle the close that comes in finally.
            if _gz_drain_t is not None:
                try:
                    _gz_drain_t.join(timeout=5)
                except Exception:
                    pass
        except Exception as e:
            logging.warning(t("warn_db_restore_exception", e=e))
            self._exit_code = 1
        finally:
            # [V3.2.40] BUG-A fix: guard with `not _pipe.closed` so
            # p_gunzip.stdout (explicitly closed above for pipe hand-off) is
            # not double-closed here. Python io objects are idempotent on
            # double-close, but the guard makes the intent unambiguous.
            for _p in (p_gunzip, p_mysql):
                if _p is not None:
                    for _pipe in (
                        getattr(_p, 'stdout', None),
                        getattr(_p, 'stderr', None),
                    ):
                        if _pipe is not None and not _pipe.closed:
                            try:
                                _pipe.close()
                            except Exception:
                                pass
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

    def _restore_webroot_files(self, bak_dir):
        # type: (Path) -> None
        """从备份恢复站点文件。"""
        webroot_tar = bak_dir / "webroot.tar.gz"
        if not webroot_tar.exists():
            logging.info(t("info_no_webroot_tar"))
            return
        logging.info(t("info_restore_webroot"))
        self.cfg.webroot_path.mkdir(parents=True, exist_ok=True)
        result = self.run_cmd(
            ["tar", "-xzf", str(webroot_tar),
             "-C", str(self.cfg.webroot_path.parent)],
            timeout=600, quiet=True)
        if result:
            logging.info(t("info_webroot_restore_ok"))
        else:
            logging.warning(t("warn_webroot_restore_fail"))
            self._exit_code = 1

    def _restore_nginx_and_extras(self, bak_dir):
        # type: (Path) -> dict
        """恢复 Nginx + 附加配置, 返回恢复前的 Nginx 配置快照 (用于回滚)。"""
        _nginx_pre = {}
        nginx_baks = list(bak_dir.glob("*.conf"))
        if nginx_baks:
            logging.info(t("info_restore_nginx"))
            for conf in nginx_baks:
                target = Path("/etc/nginx/conf.d/%s" % conf.name)
                if target.exists():
                    try:
                        _nginx_pre[str(target)] = target.read_text(
                            encoding="utf-8")
                    except OSError:
                        pass
            for conf in nginx_baks:
                target = Path("/etc/nginx/conf.d/%s" % conf.name)
                try:
                    shutil.copy2(str(conf), str(target))
                    logging.info(t("info_nginx_conf_restored",
                                   name=conf.name))
                except OSError as e:
                    logging.warning(t("warn_nginx_conf_restore_fail",
                                      name=conf.name, e=e))
        # 附加配置
        _extras_dir = bak_dir / "extras"
        _f2b_restored = False
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
                            if _prefix.startswith("fail2ban-"):
                                _f2b_restored = True
                        except OSError as _e:
                            logging.warning(
                                t("warn_extra_conf_restore_fail",
                                  name=_ef.name, e=_e))
                        break
        if _f2b_restored and shutil.which("fail2ban-client"):
            self.run_cmd(["systemctl", "restart", "fail2ban"], quiet=True)
        return _nginx_pre

    def _restore_post_fixup(self, _nginx_pre):
        # type: (dict) -> None
        """恢复后权限修复、服务重载、定时器重建。"""
        if self.cfg.webroot_path.exists():
            self.run_cmd(
                ["chown", "-R",
                 "%s:%s" % (self.nginx_user, self.nginx_user),
                 str(self.cfg.webroot_path)], quiet=True)
            self.run_cmd(
                ["find", str(self.cfg.webroot_path), "-type", "d",
                 "-exec", "chmod", "755", "{}", "+"], quiet=True)
            self.run_cmd(
                ["find", str(self.cfg.webroot_path), "-type", "f",
                 "-not", "-name", "wp-config.php",
                 "-exec", "chmod", "644", "{}", "+"], quiet=True)
            wp_config = self.cfg.webroot_path / "wp-config.php"
            if wp_config.exists():
                self.run_cmd(["chmod", "0440", str(wp_config)], quiet=True)
        if not self._safe_reload_nginx():
            if _nginx_pre:
                logging.warning(
                    "nginx -t failed after restore; "
                    "rolling back Nginx configs...")
                _rollback_ok = True
                for _tp, _old in _nginx_pre.items():
                    if not self._safe_write_file(
                        Path(_tp), _old, mode=0o644
                    ):
                        logging.error(
                            "Failed to rollback Nginx config: %s", _tp)
                        _rollback_ok = False
                if _rollback_ok:
                    self._safe_reload_nginx()
                else:
                    logging.error(
                        "Skipping Nginx reload: rollback writes failed")
            self._exit_code = 1
        # [V3.2.33] P-6: check PHP-FPM restart result
        if not self.run_cmd(
            ["systemctl", "restart", self.php_fpm_svc], quiet=True):
            logging.warning(
                "PHP-FPM restart failed after restore; "
                "check: systemctl status %s", self.php_fpm_svc,
            )
        if not self.cfg.email:
            _renewal_conf = Path(
                "/etc/letsencrypt/renewal/%s.conf" % self.cfg.domain)
            if _renewal_conf.exists():
                try:
                    _rc_text = _renewal_conf.read_text(encoding="utf-8")
                    _em_m = re.search(
                        r"^\s*email\s*=\s*(.+)$", _rc_text, re.MULTILINE)
                    if _em_m:
                        _em = _em_m.group(1).strip()
                        if _em and "@" in _em:
                            self.cfg.email = _em
                except OSError:
                    pass
        # [V3.2.33] P-1: HTTP-only 站点无需 SSL 续期定时器
        if self.cfg.cert_chain.exists():
            self.setup_systemd()
            self._install_certbot_deploy_hook()  # [V3.2.72] Bug-2: 恢复 certbot deploy hook
        # [V3.2.72] Bug-1: 恢复后重新探测 WP-CLI, 确保 wp-cron timer 不降级
        self._ensure_wpcli()
        self.setup_wp_cron_timer()
        self._ensure_wp_cron_constant()  # [V3.2.33] P-2
        self.setup_db_optimize_timer()
        self._setup_redis_cache()  # [V3.2.72] Bug-5: --redis 标志生效

    def restore(self, backup_path=""):
        # type: (str) -> None
        """从备份目录恢复站点。

        [V3.2.32] 重构: 拆分为 5 个子方法。
        """
        logging.info(t("info_restore_start", domain=self.cfg.domain))
        if self.cfg.dry_run:
            logging.info(t("dry_run_restore"))
            return
        bak_dir = self._restore_locate_backup(backup_path)
        if bak_dir is None:
            return
        self._restore_database(bak_dir)
        self._restore_webroot_files(bak_dir)
        _nginx_pre = self._restore_nginx_and_extras(bak_dir)
        self._restore_post_fixup(_nginx_pre)
        logging.info(t("info_restore_done",
                        domain=self.cfg.domain, src=bak_dir.name))
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

        # 1. Nginx 配置 (感知 SSL 状态)
        sock_path = self.get_php_sock_path()
        # [FIX-2] 有证书 → HTTPS 配置; 无证书 → HTTP-only 配置
        _has_cert = self.cfg.cert_chain.exists()
        if _has_cert:
            config = generate_https_config(
                self.cfg.domain, self.cfg.webroot_path, sock_path,
                cache_mode=self.cfg.cache_mode,
                allow_xmlrpc=self.cfg.allow_xmlrpc,
                optimize=self.cfg.optimize,
                cert_chain=str(self.cfg.cert_chain),
                cert_key=str(self.cfg.cert_key),
            )
        else:
            logging.info(t("warn_update_no_cert"))
            config = generate_http_production_config(
                self.cfg.domain, self.cfg.webroot_path, sock_path,
                cache_mode=self.cfg.cache_mode,
                allow_xmlrpc=self.cfg.allow_xmlrpc,
                optimize=self.cfg.optimize,
            )
        if self.apply_nginx_config_safe(config):
            logging.info(t("info_nginx_updated"))
        else:
            logging.warning(t("warn_nginx_update_fail"))

        # [V3.2.29] BUG-E: update --cache fastcgi 时同步创建缓存目录,
        # 否则 Nginx reload 后 fastcgi_cache_path 指向不存在的目录会报错。
        if self.cfg.cache_mode == "fastcgi" and not self.cfg.dry_run:
            _safe = _nginx_safe_name(self.cfg.domain)
            _cache_dir = Path("/var/cache/nginx/" + _safe)
            try:
                _cache_dir.mkdir(parents=True, exist_ok=True)
                self.run_cmd(
                    ["chown", "-R",
                     self.nginx_user + ":" + self.nginx_user,
                     str(_cache_dir)], quiet=True)
                logging.info(t("info_fastcgi_cache_created", path=_cache_dir))
            except OSError as _cd_e:
                logging.warning(t("warn_fastcgi_cache_dir_fail", e=_cd_e))

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
                # [V3.2.0] F1: 原子写入, 与 deploy 路径保持一致
                if not self._safe_write_file(ini_path, content, mode=0o644):
                    logging.warning(t("warn_php_ini_fail",
                                      path=ini_path, e="atomic write failed"))
            except Exception as e:
                logging.warning(t("warn_php_ini_fail", path=ini_path, e=e))
        # [V3.2.15] P1-5: update 路径同步 deploy 中的 pool user 修补,
        # 确保旧站点升级后 listen.owner/listen.group/listen.mode 被修正
        for _fpm_conf in self._get_php_conf_paths():
            try:
                _fpm_content = Path(_fpm_conf).read_text(encoding="utf-8")
                _fpm_new = patch_php_fpm_pool_user(_fpm_content, self.nginx_user)
                if _fpm_new != _fpm_content:
                    if not self._safe_write_file(_fpm_conf, _fpm_new, mode=0o644):
                        logging.warning(t("warn_php_ini_fail",
                                          path=_fpm_conf, e="atomic write failed"))
            except Exception as _fpm_e:
                logging.warning(t("warn_php_ini_fail", path=_fpm_conf, e=_fpm_e))
        self._patch_fpm_pool_tuning()  # [V3.0.16] P3
        logging.info(t("info_php_updated"))

        # 3. WP-CLI (须在所有依赖它的步骤之前)
        # [V3.2.0] O1: 从原位置提前, 确保 wp-cron timer 等能使用 WP-CLI
        self._ensure_wpcli()

        # 4. Fail2Ban + logrotate + Brotli + nginx-helper
        self.setup_fail2ban()
        self.setup_logrotate()
        self.setup_wp_cron_timer()  # [V3.0.16] P2
        self._ensure_wp_cron_constant()  # [V3.2.0] F4
        self.setup_db_optimize_timer()  # [V3.0.16] P11
        if _has_cert:                                # [V3.2.69] BUG-2: HTTP-only 无需 certbot hook
            self._install_certbot_deploy_hook()      # [V3.1.1] Issue 1
        self._setup_brotli()
        self._setup_cloudflare_real_ip()  # [V3.0.16] P12
        # [V3.2.0] P3: deploy 时 WP-CLI 不可用导致自动安装跳过, update 补执行
        self._wp_auto_install()
        self._install_nginx_helper()
        self._setup_redis_cache()  # [V3.0.11] B2: 允许 update --redis 补装

        # [V3.0.9] B8: 同步 Systemd 续期单元（修正脚本路径变更后旧路径残留）
        if _has_cert:                                # [V3.2.69] BUG-1: HTTP-only 无需续期 timer
            self.setup_systemd()

        # 重载服务
        self.run_cmd(["systemctl", "restart", self.php_fpm_svc], quiet=True)
        self._safe_reload_nginx()  # [V3.0.16] P8: 门控 reload
        logging.info(t("info_update_done", domain=self.cfg.domain))

    # -----------------------------------------------------------------------
    # 卸载
    # -----------------------------------------------------------------------
    def _upgrade_http_to_https(self):
        """[V3.2.1] L-1: deploy --skip-ssl 后 enable-ssl 时恢复 HTTPS 设置。

        1. 将 wp-config.php 中 FORCE_SSL_ADMIN 从 false 改回 true
        2. 通过 WP-CLI 更新 siteurl/home 为 https://
        """
        if self.cfg.dry_run:
            return
        # 1. 恢复 FORCE_SSL_ADMIN
        wp_config = self.cfg.webroot_path / "wp-config.php"
        if wp_config.exists():
            try:
                _content = wp_config.read_text(encoding="utf-8")
                _new_content = _set_force_ssl_admin(_content, enabled=True)
                if _new_content != _content:
                    self._safe_write_file(wp_config, _new_content, mode=0o440)
            except Exception as _e:
                logging.warning(
                    "Failed to restore FORCE_SSL_ADMIN: %s", _e,
                )
        # 2. 更新 WordPress siteurl/home (WP-CLI 可用时)
        if self._wpcli_bin and self._wpcli_check_installed():
            _https_url = "https://%s" % self.cfg.domain
            self._run_wpcli(
                "option", "update", "siteurl", _https_url,
                timeout=15, quiet=True,
            )
            self._run_wpcli(
                "option", "update", "home", _https_url,
                timeout=15, quiet=True,
            )

    def _restore_http_production_config(self):
        """[V3.2.3] H-1: 恢复 HTTP 生产配置，防止站点停留在 ACME-only 模式。

        enable_ssl() 中 setup_nginx_for_challenge() 会将 Nginx 配置替换为
        极简 ACME 验证配置（无 PHP 处理能力）。DNS 或 HTTP challenge 失败时
        必须恢复完整的 HTTP 生产配置，否则站点完全不可访问。

        [V3.2.31] P-4: 优先恢复 enable_ssl 前保存的原始配置快照,
        避免因 CLI 参数差异（如缺少 --cache fastcgi）导致重生成的
        配置丢失 FastCGI 缓存等原有功能。
        """
        # [V3.2.31] P-4: 优先恢复原始快照
        _saved = getattr(self, '_pre_ssl_nginx_config', None)
        if _saved:
            try:
                if self.apply_nginx_config_safe(_saved):
                    logging.info(
                        "Nginx config restored from pre-SSL snapshot."
                    )
                    return
            except Exception:
                pass  # 快照恢复失败，降级到重生成
        try:
            _sock = self.get_php_sock_path()
            _http_conf = generate_http_production_config(
                self.cfg.domain, self.cfg.webroot_path, _sock,
                cache_mode=self.cfg.cache_mode,
                allow_xmlrpc=self.cfg.allow_xmlrpc,
                optimize=self.cfg.optimize,
            )
            if not self.apply_nginx_config_safe(_http_conf):  # [PATCH-M6]
                logging.error(
                    "CRITICAL: Failed to restore HTTP production config. "
                    "Site may be unreachable. "
                    "Manual fix: nginx -t && systemctl reload nginx"
                )
            else:
                logging.info("HTTP production config restored after SSL failure.")
        except Exception as _e:
            logging.warning(
                "Failed to restore HTTP config after SSL failure: %s. "
                "Manual intervention may be required: nginx -t && systemctl reload nginx",
                _e,
            )

    def _retry_with_ssl_diagnosis(self, action, *args, **kwargs):
        """[V3.2.2] D-1: SSL 操作失败后诊断+重试的通用辅助。"""
        if action(*args, **kwargs):
            return True
        if self._diagnose_ssl_failure(self.cfg.domain):
            return action(*args, **kwargs)
        return False

    def _ssl_recover_credentials(self):
        # type: () -> None
        """SSL 签发完成后恢复真实 DB 凭据, 防止覆写为错误密码。

        优先从 wp-config.php 恢复; 失败时回退到凭据文件的多格式解析。
        """
        # [V3.2.21-AUDIT] P0: 恢复真实凭据
        # [V3.2.30] BUG-I: 恢复失败时从现有凭据文件中提取 db_pass
        _recovered = self._recover_existing_db_pass()
        if _recovered:
            self.cfg.db_pass = _recovered
        else:
            # [V3.2.34] P-2: 多格式凭据文件解析, 防止标签变更导致密码丢失
            _cred_file = Path(
                "/root/.wp_credentials_%s.txt" % self.cfg.systemd_prefix
            )
            _cred_recovered = False
            if _cred_file.exists():
                try:
                    _cred_text = _cred_file.read_text(encoding="utf-8")
                    # 尝试多种可能的标签格式 (中英文 / 旧版 / 手动编辑)
                    _db_pass_patterns = [
                        r"^DB Pass\s*:\s*(.+)$",
                        r"^DB.?Password\s*:\s*(.+)$",
                        r"^数据库密码\s*[:：]\s*(.+)$",
                        r"^DB_PASSWORD\s*[:=]\s*(.+)$",
                    ]
                    for _pat in _db_pass_patterns:
                        _db_pass_m = re.search(_pat, _cred_text, re.MULTILINE | re.IGNORECASE)
                        if _db_pass_m:
                            _cred_pass = _db_pass_m.group(1).strip()
                            if (_cred_pass
                                    and _cred_pass != "[UNKNOWN]"
                                    and not _cred_pass.startswith("[UNKNOWN")):
                                self.cfg.db_pass = _cred_pass
                                logging.info(
                                    "[P-2] DB password recovered from existing "
                                    "credentials file (pattern: %s).",
                                    _pat[:30],
                                )
                                _cred_recovered = True
                                break
                except OSError:
                    pass
            if not _cred_recovered:
                self.cfg.db_pass = "[UNKNOWN - check wp-config.php]"
                logging.warning(
                    "[BUG-I] Could not recover DB password from wp-config.php; "
                    "credentials file will contain placeholder. "
                    "Real password is in wp-config.php DB_PASSWORD define."
                )
        if self.global_root_pwd_file.exists():
            try:
                _pwd = self.global_root_pwd_file.read_text(
                    encoding="utf-8"
                ).strip()
                if _pwd and re.fullmatch(
                    r'[a-zA-Z0-9!@#$%^&*()_+=.-]+', _pwd
                ):
                    self.db_root_pass = _pwd
            except OSError:
                pass
        # [V3.2.38] FIX-2: enable-ssl --persist-root-pwd 生效
        # 若 persist_root_pwd 标志为真且已恢复有效 root 密码, 持久化到磁盘,
        # 防止后续 backup/restore 流程因密码文件缺失而失败。
        if (getattr(self.cfg, 'persist_root_pwd', False)
                and self.db_root_pass
                and not self.cfg.dry_run):
            if not self.global_root_pwd_file.exists():
                self._safe_write_file(
                    self.global_root_pwd_file, self.db_root_pass)
                logging.info(
                    "[FIX-2] Root password persisted to %s via "
                    "--persist-root-pwd.", self.global_root_pwd_file)

    def enable_ssl(self, force_renew=False):
        """为已部署的 HTTP-only 站点补签 SSL 并切换至 HTTPS。

        流程: 验证 webroot → 配置 ACME 通道 → DNS 预检 →
              HTTP challenge → 签发证书 → 切换 HTTPS 配置 →
              安装 systemd 续期定时器。
        """
        logging.info(t("info_enable_ssl_start", domain=self.cfg.domain))

        if not self.cfg.webroot_path.exists():
            logging.error(t("err_enable_ssl_no_webroot",
                            path=self.cfg.webroot_path))
            self._exit_code = 1
            return False

        # [V3.2.31] P-4: 保存当前 Nginx 配置快照, SSL 失败时原样恢复
        self._pre_ssl_nginx_config = None
        if self.cfg.nginx_conf.exists():
            try:
                self._pre_ssl_nginx_config = self.cfg.nginx_conf.read_text(
                    encoding="utf-8"
                )
            except OSError:
                pass

        # 阶段 2: ACME 验证通道
        if not self.setup_nginx_for_challenge():
            logging.error(t("err_deploy_nginx_acme"))
            self._exit_code = 1
            return False

        # DNS 预检
        _dns_main, _dns_www = self.verify_dns()
        if not _dns_main:
            logging.error(t("err_deploy_dns"))
            # [V3.2.3] H-1: 恢复 HTTP 生产配置
            self._restore_http_production_config()
            self._exit_code = 1
            return False

        # [V3.2.2] D-1: 统一诊断+重试
        if not self._retry_with_ssl_diagnosis(self.verify_http_challenge):
            logging.error(t("err_deploy_http_challenge"))
            self._restore_http_production_config()
            self._exit_code = 1
            return False

        # 阶段 3: 签发证书
        if not self._retry_with_ssl_diagnosis(
            self.apply_cert, include_www=_dns_www
        ):
            logging.error(t("err_enable_ssl_cert"))
            self._restore_http_production_config()
            self._exit_code = 1
            return False

        # 刷新证书路径缓存 (签发后才存在)
        self.cfg.cert_chain, self.cfg.cert_key = (
            SiteConfig._probe_cert_paths(
                self.cfg.domain, self.cfg.certbot_bin
            )
        )

        # 阶段 4: 切换 HTTPS 生产配置
        if not self.setup_nginx_for_production():
            logging.error(t("err_deploy_https"))
            self._restore_http_production_config()
            self._exit_code = 1
            return False

        # [V3.2.1] L-1: 恢复 FORCE_SSL_ADMIN 并更新 WordPress URL
        self._ensure_wpcli()  # [V3.2.19] A1: enable-ssl 需探测 WP-CLI
        self._upgrade_http_to_https()

        # [V3.2.29] BUG-C: 重启 PHP-FPM 清除 OPcache 中的旧 wp-config.php
        self.run_cmd(["systemctl", "restart", self.php_fpm_svc], quiet=True)

        # 后续增强 — 与 _run_deploy_branch() HTTPS 路径对齐
        # [V3.2.69] BUG-E: Brotli/CF 配置写入后再做健康检查，验证终态 Nginx 配置
        self._setup_brotli()
        self._setup_cloudflare_real_ip()    # [V3.2.33] P-5
        # [V3.2.73] Bug-6: 先完成自动安装, 再做健康检查 (与 deploy 路径对齐)
        self._wp_auto_install()
        self.verify_site_health()           # [V3.2.69] BUG-E: 移至 brotli/CF 之后、systemd 之前
        self.verify_wp_installation()       # [V3.2.69] BUG-E: 与 HTTPS path 对齐（纯信息检查）

        # 阶段 5: Systemd 续期
        self.setup_systemd()
        self._install_certbot_deploy_hook()
        self.setup_wp_cron_timer()          # [V3.2.33] P-3
        self._ensure_wp_cron_constant()     # [V3.2.33] P-3
        self.setup_db_optimize_timer()      # [V3.2.33] P-3

        # [V3.2.69] BUG-A: enable-ssl 升级后 Fail2Ban 防暴力破解保护缺失（与所有其他路径对齐）
        self.setup_fail2ban()
        # [V3.2.69] BUG-B: enable-ssl 升级后 Nginx 日志轮转未配置（与所有其他路径对齐）
        self.setup_logrotate()
        # [V3.2.69] BUG-C: --cache fastcgi 时 nginx-helper 缓存清理插件未安装
        self._install_nginx_helper()
        # [V3.2.69] BUG-D: --redis 标志在 enable-ssl 下完全无效（调用缺失）
        self._setup_redis_cache()

        logging.info(t("info_enable_ssl_done"))

        # [V3.2.35] 拆分: 恢复凭据
        self._ssl_recover_credentials()

        # [V3.2.9] M-5: 重写凭据文件，将 URL 从 http:// 更新为 https://
        self.print_final_summary()
        return True




    def uninstall(self):
        logging.info(t("info_uninstall_start", domain=self.cfg.domain))
        self.run_cmd(
            ["systemctl", "stop",
             f"{self.cfg.systemd_prefix}-ssl.timer",
             f"{self.cfg.systemd_prefix}-ssl.service",
             f"{self.cfg.systemd_prefix}-wp-cron.timer",
             f"{self.cfg.systemd_prefix}-wp-cron.service",
             f"{self.cfg.systemd_prefix}-db-optimize.timer",
             f"{self.cfg.systemd_prefix}-db-optimize.service"],
            quiet=True,
        )
        self.run_cmd(
            ["systemctl", "disable",
             f"{self.cfg.systemd_prefix}-ssl.timer",
             f"{self.cfg.systemd_prefix}-ssl.service",
             f"{self.cfg.systemd_prefix}-wp-cron.timer",
             f"{self.cfg.systemd_prefix}-wp-cron.service",
             f"{self.cfg.systemd_prefix}-db-optimize.timer",
             f"{self.cfg.systemd_prefix}-db-optimize.service"],
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

        # [V3.0.16] F9: cloudflare-real-ip.conf 是全局配置, 多域名共享,
        # 卸载单个域名时不删除 (配置无害, 避免影响其他域名)。
        # 如需手动移除: rm /etc/nginx/conf.d/cloudflare-real-ip.conf && nginx -t && systemctl reload nginx

        # [V2.9.9] 清理 logrotate 配置 (V2.9.7 setup_logrotate 创建)
        _logrotate_conf = Path(f"/etc/logrotate.d/nginx-wp-{safe_name}")
        if _logrotate_conf.exists():
            try:
                _logrotate_conf.unlink()
                logging.info(t("info_deleted", path=_logrotate_conf))
            except OSError:
                pass

        # [V3.0.16] P2: 清理 wp-cron timer 文件
        # [V3.0.16] P11: 同时清理 db-optimize timer 文件
        _wpc_svc = Path(f"/etc/systemd/system/{self.cfg.systemd_prefix}-wp-cron.service")
        _wpc_tmr = Path(f"/etc/systemd/system/{self.cfg.systemd_prefix}-wp-cron.timer")
        _dbo_svc = Path(f"/etc/systemd/system/{self.cfg.systemd_prefix}-db-optimize.service")
        _dbo_tmr = Path(f"/etc/systemd/system/{self.cfg.systemd_prefix}-db-optimize.timer")
        for _wpc_f in (_wpc_svc, _wpc_tmr, _dbo_svc, _dbo_tmr):
            if _wpc_f.exists():
                try:
                    _wpc_f.unlink()
                    logging.info(t("info_deleted", path=_wpc_f))
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
        self._safe_reload_nginx()  # [V3.0.16] P8: 门控 reload
        logging.info(t("ok_uninstall"))
        # [V3.2.72] Bug-3: 移除多余的 cleanup_and_exit(0),
        # 由 main() 的 finally 块统一处理, 与其他子命令保持一致。

    # -----------------------------------------------------------------------
    # 部署分支 (从 run() 提取, V3.0.12 N1)
    # -----------------------------------------------------------------------
    def _run_deploy_branch(self) -> bool:
        """N1: 从 run() 提取的完整部署流程, early-return 风格。

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

        # [PATCH] SSL 可选: --skip-ssl 时跳过阶段 2-5, 直接生成 HTTP 生产配置
        if self.cfg.skip_ssl:
            logging.info(t("info_skip_ssl_deploy"))
            logging.info(t("phase_http_prod"))
            _sock = self.get_php_sock_path()
            _http_conf = generate_http_production_config(
                self.cfg.domain, self.cfg.webroot_path, _sock,
                cache_mode=self.cfg.cache_mode,
                allow_xmlrpc=self.cfg.allow_xmlrpc,
                optimize=self.cfg.optimize,
            )
            if not self.apply_nginx_config_safe(_http_conf):
                logging.error(t("err_deploy_https"))
                self._exit_code = 1
                return False
            logging.info(t("info_http_prod_applied"))
            if self.cfg.cache_mode == "fastcgi" and not self.cfg.dry_run:
                # [V3.2.15] P0-3: 与 Nginx 配置中 fastcgi_cache_path 对齐
                _sn = _nginx_safe_name(self.cfg.domain)
                _cd = Path("/var/cache/nginx/" + _sn)
                try:
                    _cd.mkdir(parents=True, exist_ok=True)
                    self.run_cmd(
                        ["chown", "-R",
                         self.nginx_user + ":" + self.nginx_user,
                         str(_cd)], quiet=True)
                except OSError:
                    pass
            # 后续增强步骤 (不含 SSL 相关)
            self._setup_brotli()
            self._setup_cloudflare_real_ip()
            self._ensure_wpcli()
            # [FIX-2] 先完成自动安装，再做深度健康检查
            self._wp_auto_install()
            # [V3.2.5] A-8: skip_ssl 路径补充健康检查 (与 HTTPS 路径对齐)
            self.verify_site_health()
            self.verify_wp_installation()
            self.setup_fail2ban()
            self.setup_logrotate()
            self.setup_wp_cron_timer()
            self._ensure_wp_cron_constant()  # [V3.2.36] P-3
            self.setup_db_optimize_timer()
            self._install_nginx_helper()
            self._setup_redis_cache()
            # 打印摘要 (HTTP 版本)
            self._print_http_summary()
            return True


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
            # [V3.2.0] B1 修复: 触发 SSL 前置条件诊断 (防火墙/webroot/锁文件)
            if self._diagnose_ssl_failure(self.cfg.domain):
                # 前置条件已修复, 重试一次 HTTP challenge 预检
                if not self.verify_http_challenge():
                    logging.error(t("err_deploy_http_challenge"))
                    self._exit_code = 1
                    return False
            else:
                logging.error(t("err_deploy_http_challenge"))
                self._exit_code = 1
                return False

        if self.check_shutdown():
            self._exit_code = 130
            return False

        # [V3.0.12] N1: 根据 www DNS 结果动态裁剪 certbot -d 列表
        if not self.apply_cert(include_www=_dns_www):
            # [V3.2.0] B1 修复: 尝试修复 SSL 前置条件后重试一次
            if self._diagnose_ssl_failure(self.cfg.domain):
                if not self.apply_cert(include_www=_dns_www):
                    logging.error(t("err_deploy_cert"))
                    self._exit_code = 1
                    return False
            else:
                logging.error(t("err_deploy_cert"))
                self._exit_code = 1
                return False

        if self.check_shutdown():
            self._exit_code = 130
            return False

        # [V3.2.17] P1-2: 签发成功后刷新证书路径缓存,
        # 与 enable_ssl 保持一致, 兼容 snap certbot 非标路径
        self.cfg.cert_chain, self.cfg.cert_key = (
            SiteConfig._probe_cert_paths(
                self.cfg.domain, self.cfg.certbot_bin
            )
        )

        if not self.setup_nginx_for_production():
            logging.error(t("err_deploy_https"))
            self._exit_code = 1
            return False

        # 部署成功 — 执行后续增强步骤
        self._setup_brotli()
        self._setup_cloudflare_real_ip()  # [V3.0.16] P12
        self._wp_auto_install()        # [V3.2.69] BUG-3: 先完成自动安装
        self.verify_site_health()      # [V3.2.69] BUG-3: 再做健康检查 (与 HTTP 路径对齐)
        self.verify_wp_installation()  # [FIX-2] 检查时 WP 已安装，输出准确
        self.setup_systemd()
        self.setup_fail2ban()
        self.setup_logrotate()
        self.setup_wp_cron_timer()  # [V3.0.16] P2
        self._ensure_wp_cron_constant()  # [V3.2.36] P-3
        self.setup_db_optimize_timer()  # [V3.0.16] P11
        self._install_certbot_deploy_hook()  # [V3.1.1] Issue 1
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
# ---------------------------------------------------------------------------
# [V3.0.16] P10: 自更新常量
# ---------------------------------------------------------------------------
# 用户可通过环境变量 WP_UPDATE_URL / WP_UPDATE_HASH_URL 覆盖
SELF_UPDATE_URL_DEFAULT = (
    "https://raw.githubusercontent.com/wenghang-hub/wp-ssl-bootstrap"
    "/main/wp_ssl_bootstrap.py"
)
SELF_UPDATE_HASH_URL_DEFAULT = (
    "https://raw.githubusercontent.com/wenghang-hub/wp-ssl-bootstrap"
    "/main/wp_ssl_bootstrap.py.sha256"
)


def _do_self_update(update_url: str = "") -> None:
    """从远程下载最新版脚本并原子替换自身。

    流程: 下载 → SHA256 校验 → 版本号提取 → 备份 → 原子替换。
    """
    import urllib.request
    import urllib.error

    script_path = Path(os.path.abspath(__file__))
    url = (update_url
           or os.environ.get("WP_UPDATE_URL", "").strip()
           or SELF_UPDATE_URL_DEFAULT)
    hash_url = os.environ.get("WP_UPDATE_HASH_URL", "").strip()
    if not hash_url:
        if url == SELF_UPDATE_URL_DEFAULT:
            hash_url = SELF_UPDATE_HASH_URL_DEFAULT
        else:
            hash_url = url + ".sha256"

    logging.info(t("info_self_update_downloading"))

    # 下载脚本
    fd_new, tmp_path = tempfile.mkstemp(
        prefix="wp_ssl_update_", suffix=".py",
    )
    os.fchmod(fd_new, 0o600)
    os.close(fd_new)

    try:
        try:
            # [V3.0.16] F10: urlretrieve 无超时, 改用 urlopen + 手动写入
            _MAX_SCRIPT_SIZE = 10 * 1024 * 1024  # [V3.2.0] F6: 10MB 硬上限
            with urllib.request.urlopen(url, timeout=60) as resp:
                with open(tmp_path, "wb") as f_out:
                    _dl_total = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        _dl_total += len(chunk)
                        if _dl_total > _MAX_SCRIPT_SIZE:
                            raise ValueError(
                                f"Download size exceeds "
                                f"{_MAX_SCRIPT_SIZE} byte limit"
                            )
                        f_out.write(chunk)
        except Exception as e:
            logging.error(t("err_self_update_download", e=e))
            return

        # SHA256 校验 (可选)
        try:
            with urllib.request.urlopen(hash_url, timeout=30) as resp:
                # [V3.2.0] F2: 限制读取 4KB, 防止劫持响应耗尽内存
                expected_hash = resp.read(4096).decode("utf-8").strip().split()[0]
            sha256 = hashlib.sha256()
            with open(tmp_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256.update(chunk)
            if sha256.hexdigest() != expected_hash:
                logging.error(t("err_self_update_hash"))
                return
        except Exception as e:
            # [V3.2.70] BUG-5: 原 except 仅捕获网络/IO 异常；
            # 若 hash 文件为空或非 UTF-8，resp.read().decode().split()[0]
            # 会抛出 IndexError / UnicodeDecodeError，绕过日志直接冒泡，
            # finally 虽仍会清理 tmp_path，但不会输出可读错误信息。
            # 扩展为 except Exception 确保所有失败均有明确日志并 return。
            # [V3.1.1] Issue 8: SHA256 verification is now mandatory
            logging.error(t("err_self_update_hash_unavailable", e=e))
            return

        # 提取新版本号
        new_content = Path(tmp_path).read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', new_content)
        if not m:
            logging.error(t("err_self_update_no_version"))
            return
        new_ver = m.group(1)

        # [V3.1.0 S2] 语义版本比较：相同跳过、旧版拒绝、新版继续
        def _ver_tuple(v: str):
            try:
                return tuple(int(x) for x in v.split("."))
            except ValueError:
                return (0,)

        if new_ver == __version__:
            logging.info(t("info_self_update_same", ver=__version__))
            return

        if _ver_tuple(new_ver) < _ver_tuple(__version__):
            logging.warning(t("warn_self_update_downgrade",
                               remote=new_ver, current=__version__))
            return

        # [V3.2.0] F5: 语法校验 — 防止损坏脚本通过 SHA256 后覆盖本地
        try:
            compile(new_content, "<self-update>", "exec")
        except SyntaxError as _syn_e:
            logging.error(
                "Self-update aborted: downloaded script has syntax error: %s",
                _syn_e,
            )
            return

        # 备份当前文件 (仅保留最新一份)
        bak = script_path.with_suffix(f".{__version__}.bak")
        # [V3.2.0] F6: 清理旧版本备份
        for _old_bak in script_path.parent.glob(script_path.stem + ".*.bak"):
            if _old_bak != bak:
                try:
                    _old_bak.unlink()
                except OSError:
                    pass
        shutil.copy2(script_path, bak)

        # 原子替换
        os.chmod(tmp_path, os.stat(str(script_path)).st_mode)
        # [PATCH-L2] fsync 确保下载内容落盘，防止断电截断覆盖脚本
        try:
            _upd_fd = os.open(tmp_path, os.O_RDONLY)
            try:
                os.fsync(_upd_fd)
            finally:
                os.close(_upd_fd)
        except OSError:
            pass  # fsync 失败降级，不阻断更新
        os.replace(tmp_path, str(script_path))
        tmp_path = None  # 已消费, 不再清理

        print(f"\n{'=' * 50}")
        print(t("info_self_update_done", old=__version__, new=new_ver))
        print(f"{'=' * 50}")
        # [V3.0.16] F11: 直接输出备份路径, 不依赖翻译键
        print(f"  Backup: {bak}")
        print()

    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# [V3.2.0] 交互式向导 (deploy / update / backup / restore / uninstall)
# ---------------------------------------------------------------------------

def _detect_existing_sites():
    """扫描已部署的站点, 返回域名列表。

    [V3.2.3] L-2: 增加 WordPress 标志文件检测, 排除非 WP 站点。
    """
    sites = []
    conf_dir = Path("/etc/nginx/conf.d")
    _exclude = {
        "default.conf", "cloudflare-real-ip.conf",
        "brotli-wp-bootstrap.conf",
    }
    # WordPress 标志文件: 至少存在其一才认定为 WP 站点
    _wp_markers = ("wp-config.php", "wp-login.php", "wp-includes/version.php")
    if conf_dir.is_dir():
        for f in sorted(conf_dir.glob("*.conf")):
            if f.name in _exclude or f.name.startswith("00-"):
                continue
            domain = f.stem
            if not re.match(r'^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$', domain):
                continue
            # 尝试从 Nginx 配置中提取 root 路径
            _webroot = None
            try:
                _nc = f.read_text(encoding="utf-8")
                # [V3.2.21-AUDIT] P2-6: 增强 root 探测——优先匹配
                # 包含 domain server_name 的 server{} 块内的 root，
                # 避免跨 server 块误取 HTTP redirect 的 root。
                _nc_clean = re.sub(r'(?m)^\s*#[^\n]*', '', _nc)
                # 策略 1: 在包含 server_name <domain> 的 server 块内查找
                _block_root = None
                for _blk in re.split(r'(?=server\s*\{)', _nc_clean):
                    # [V3.2.22] P2-1: 用正则单词边界代替子串匹配，
                    # 防止 "a.com" 误匹配 "ba.com" 或注释中的域名片段。
                    if re.search(
                        r'\bserver_name\b[^;]*\b' + re.escape(domain) + r'\b',
                        _blk,
                    ):
                        _rm = re.search(
                            r'(?:^|\n)[ \t]+root[ \t]+([^\s;]+)\s*;',
                            _blk,
                        )
                        if _rm:
                            _block_root = _rm.group(1)
                            break
                if _block_root:
                    # [V3.2.31] P-3: 剥离 Nginx 配置中 root 路径的引号
                    _webroot = Path(_block_root.strip('"').strip("'"))
                else:
                    # 策略 2 回退: 所有 root 取缩进最浅的
                    _all_roots = re.findall(
                        r'(?:^|\n)([ \t]{1,})root[ \t]+([^\s;]+)\s*;',
                        _nc_clean,
                    )
                    if _all_roots:
                        _all_roots.sort(
                            key=lambda x: len(x[0].expandtabs())
                        )
                        # [V3.2.31] P-3: 剥离引号
                        _webroot = Path(_all_roots[0][1].strip('"').strip("'"))
            except OSError:
                pass
            if _webroot is None:
                # 回退: 按惯例猜测路径
                for _base in ("/var/www/html", "/usr/share/nginx/html"):
                    _guess = Path(_base) / domain
                    if _guess.is_dir():
                        _webroot = _guess
                        break
            # 检测 WordPress 标志文件
            if _webroot and _webroot.is_dir():
                if any((_webroot / _m).exists() for _m in _wp_markers):
                    sites.append(domain)
            else:
                # [PATCH-L3] webroot 不存在 → 幽灵站点，不纳入操作列表
                # 避免 backup/update 等操作在无文件时失败
                # [V3.2.8] L-3: 升级为 info，默认日志级别下用户可见残留配置提示
                # [V3.2.9] M-3: 使用 t() 国际化，--lang en 下输出英文
                logging.info(t("warn_ghost_site", domain=domain))
    return sites


def _detect_site_config(domain):
    """探测已部署站点的当前配置。"""
    config = {
        "cache": "none", "redis": False, "optimize": False,
        "cloudflare": False, "allow_xmlrpc": False,
    }
    conf_path = Path(f"/etc/nginx/conf.d/{domain}.conf")
    if conf_path.exists():
        try:
            _c = conf_path.read_text(encoding="utf-8")
            if "fastcgi_cache_path" in _c:
                config["cache"] = "fastcgi"
            if "open_file_cache" in _c:
                config["optimize"] = True
            _xp = _c.find("xmlrpc")
            if _xp >= 0:
                _snip = _c[_xp:_xp + 200]
                if "deny all" not in _snip and "limit_req" in _snip:
                    config["allow_xmlrpc"] = True
        except OSError:
            pass
    if Path("/etc/nginx/conf.d/cloudflare-real-ip.conf").exists():
        config["cloudflare"] = True
    for _rs in ("redis", "redis-server", "valkey"):  # [FIX-C4] EL10 valkey
        try:
            _r = subprocess.run(
                ["systemctl", "is-active", _rs],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if _r.returncode == 0:
                config["redis"] = True
                break
        except Exception:
            pass
    return config


def _interactive_mode() -> list:
    """交互式向导: 支持 deploy / update / backup / restore / uninstall / self-update。

    当用户直接运行脚本而未指定子命令时自动进入 (仅 TTY 终端)。

    返回:
        非空 list — CLI 参数 (如 ["deploy", "--domain", "x.com", ...])
        空 list   — 用户取消
    """
    print()
    print("=" * 58)
    print(t("interactive_banner"))
    print("=" * 58)
    print()

    # ── 检测已部署站点 ─────────────────────────────────────────
    _sites = _detect_existing_sites()
    if _sites:
        print(t("interactive_sites_header"))
        for _s in _sites:
            _cert = Path(f"/etc/letsencrypt/live/{_s}/fullchain.pem")
            _icon = "" if _cert.exists() else ""
            print(f"  {_icon} {_s}")
        print()

    # ── 操作菜单 ───────────────────────────────────────────────
    print(t("interactive_op_header"))
    _ops = [
        ("deploy",      t("interactive_op_deploy")),
        ("update",      t("interactive_op_update")),
        ("backup",      t("interactive_op_backup")),
        ("restore",     t("interactive_op_restore")),
        ("uninstall",   t("interactive_op_uninstall")),
        ("enable-ssl",  t("interactive_op_enable_ssl")),
        ("self-update", t("interactive_op_self_update")),
        ("cancel",      t("interactive_confirm_cancel")),
    ]
    for _i, (_, _label) in enumerate(_ops, 1):
        _df = " (Enter)" if _i == 1 else ""
        print(f"  [{_i}] {_label}{_df}")
    print()

    # [V3.2.2] I-2: 动态范围提示
    _op_prompt = t("interactive_op_prompt").replace("[", "[1-%d, " % len(_ops))
    try:
        _ch = input(f"  {_op_prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n  {t('interactive_cancelled')}")
        return []

    _idx = 0
    if _ch == "" or _ch == "1":
        _idx = 0
    elif _ch.isdigit() and 1 <= int(_ch) <= len(_ops):
        _idx = int(_ch) - 1
    else:
        print(f"  {t('interactive_cancelled')}")
        return []

    _op = _ops[_idx][0]
    if _op == "cancel":
        print(f"  {t('interactive_cancelled')}")
        return []
    if _op == "self-update":
        return ["self-update"]
    if _op == "deploy":
        return _interactive_deploy_flow()

    # ── 需要选择已有站点的操作 ─────────────────────────────────
    if not _sites:
        print(f"\n  {t('interactive_sites_none')}")
        return []

    _domain = ""
    if len(_sites) == 1:
        _domain = _sites[0]
        print(f"\n  {t('interactive_site_auto')}: {_domain}")
    else:
        print(f"\n  {t('interactive_site_select')}:")
        for _i, _s in enumerate(_sites, 1):
            print(f"    [{_i}] {_s}")
        print()
        try:
            _sch = input(f"  {t('interactive_site_prompt')} [Enter=1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {t('interactive_cancelled')}")
            return []
        if _sch == "" or _sch == "1":
            _domain = _sites[0]
        elif _sch.isdigit() and 1 <= int(_sch) <= len(_sites):
            _domain = _sites[int(_sch) - 1]
        else:
            print(f"  {t('interactive_cancelled')}")
            return []

    if _op == "update":
        return _interactive_update_flow(_domain)
    if _op == "backup":
        print(t("interactive_starting"))
        return ["backup", "--domain", _domain]
    if _op == "restore":
        print(t("interactive_starting"))
        return ["restore", "--domain", _domain]
    if _op == "enable-ssl":
        # [V3.2.1] L-2+L-4: 移除死代码 (if not _sites 在上方已处理)
        _ssl_domain = _domain
        print()
        # [V3.2.70] BUG-7: 证书已存在时发出警告，防止用户意外触发 Let's Encrypt
        # 重复签发（同域名每周限 5 次），且会短暂替换 Nginx 配置导致服务中断。
        _existing_cert = Path(f"/etc/letsencrypt/live/{_ssl_domain}/fullchain.pem")
        if _existing_cert.exists():
            print(f"  ⚠  {_ssl_domain} 已有有效证书 ({_existing_cert})")
            print(f"  重新签发会短暂中断服务并消耗 Let's Encrypt 签发配额。")
            try:
                _confirm_reissue = input("  确认继续? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {t('interactive_cancelled')}")
                return []
            if _confirm_reissue not in ("y", "yes"):
                print(f"  {t('interactive_cancelled')}")
                return []
        _ssl_email = ""
        while not _ssl_email:
            try:
                _raw = input("  " + t("interactive_input_email") + ": ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  " + t("interactive_cancelled"))
                return []
            if _raw and re.match(r'^[^@]+@[^@]+\.[^@]+$', _raw):
                _ssl_email = _raw.lower()
            elif _raw:
                print("  " + t("interactive_invalid_email"))
        # [V3.2.1] L-2: 自动探测当前站点配置, 避免缓存等设置丢失
        _cfg = _detect_site_config(_ssl_domain)
        _cli = ["enable-ssl", "--domain", _ssl_domain, "--email", _ssl_email]
        if _cfg["cache"] == "fastcgi":
            _cli.extend(["--cache", "fastcgi"])
        if _cfg["redis"]:
            _cli.append("--redis")
        if _cfg["optimize"]:
            _cli.append("--optimize")
        if _cfg["cloudflare"]:
            _cli.append("--cloudflare")
        if _cfg["allow_xmlrpc"]:
            _cli.append("--allow-xmlrpc")
        # [V3.2.37] P-7: 自动探测全局密码文件, 若存在则传递 --persist-root-pwd,
        # 确保 enable-ssl 后续操作 (wp-cron timer, db-optimize timer 等)
        # 能正确访问 DB 密码文件。
        _global_pwd = Path("/root/.mariadb_root.pwd")
        if _global_pwd.exists():
            _cli.append("--persist-root-pwd")
        print(t("interactive_starting"))
        return _cli


    if _op == "uninstall":
        print()
        print(f"  {t('interactive_uninstall_warn', domain=_domain)}")
        try:
            _confirm = input(f"  {t('interactive_uninstall_prompt')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {t('interactive_cancelled')}")
            return []
        if _confirm.lower() != "yes":
            print(f"  {t('interactive_cancelled')}")
            return []
        print(t("interactive_starting"))
        return ["uninstall", "--domain", _domain]

    # [V3.2.34] P-6: 显式兜底 — 未知 _op 值不会隐式返回 None
    logging.debug("_interactive_mode: unhandled operation '%s'", _op)
    return []


def _interactive_deploy_flow() -> list:
    """交互式部署向导: 环境探测 → 推荐配置 → 用户确认 → 生成 CLI 参数。"""

    print()
    print(t("interactive_detecting"))
    print()

    # ── 1. 环境探测 ───────────────────────────────────────────
    _os_name = "Linux"
    try:
        _osr = Path("/etc/os-release").read_text(encoding="utf-8")
        _m = re.search(r'^PRETTY_NAME="?([^"\n]+)', _osr, re.M)
        if _m:
            _os_name = _m.group(1).strip()
    except OSError:
        pass

    _ram_mb = 0
    try:
        _ram_mb = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) // (1024 * 1024)
    except (ValueError, OSError):
        try:
            with open("/proc/meminfo", encoding="utf-8") as _f:
                for _line in _f:
                    if _line.startswith("MemTotal:"):
                        _ram_mb = int(_line.split()[1]) // 1024
                        break
        except Exception:
            pass

    _disk_gb = 0.0
    try:
        _disk_gb = shutil.disk_usage("/").free / (1024 ** 3)
    except OSError:
        pass

    _pkg = "unknown"
    for _pm in ("dnf", "yum", "apt"):
        if shutil.which(_pm):
            _pkg = _pm
            break

    _php = "auto"
    try:
        _r = subprocess.run(
            ["php", "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', timeout=5, check=False,
        )
        _m = re.search(r"PHP\s+(\d+\.\d+)", _r.stdout)
        if _m:
            _php = _m.group(1)
    except Exception:
        pass

    _db = "unknown"
    for _svc in ("mariadb", "mysql", "mysqld"):
        try:
            _r = subprocess.run(
                ["systemctl", "list-unit-files", f"{_svc}.service"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', errors='replace', timeout=5, check=False,
            )
            if _r.returncode == 0 and f"{_svc}.service" in _r.stdout:
                _db = _svc
                break
        except Exception:
            pass

    _nginx_bin = shutil.which("nginx")
    _nginx_ver = t("interactive_env_nginx_not_installed")
    if _nginx_bin:
        try:
            _nv_r = subprocess.run(
                [_nginx_bin, "-v"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=5, check=False,
            )
            _nv_m = re.search(r"nginx/(\S+)", _nv_r.stdout)
            _nginx_ver = _nv_m.group(1) if _nv_m else t("interactive_env_nginx_installed")
        except Exception:
            _nginx_ver = t("interactive_env_nginx_installed")
    _cloud = _is_china_cloud()

    # ── 2. 展示探测结果 ──────────────────────────────────────
    print(t("interactive_env_header"))
    _env_items = [
        (t("interactive_env_os"),    _os_name),
        (t("interactive_env_ram"),   f"{_ram_mb} MB"),
        (t("interactive_env_disk"),  f"{_disk_gb:.1f} GB"),
        (t("interactive_env_pkg"),   _pkg),
        (t("interactive_env_php"),   _php if _php != "auto" else ("auto" if _LANG == "en" else "\u81ea\u52a8\u63a2\u6d4b")),
        (t("interactive_env_db"),    _db),
        (t("interactive_env_nginx"), _nginx_ver),
    ]
    if _cloud:
        _env_items.append((t("interactive_env_cloud"), _cloud))
    for _label, _val in _env_items:
        print(f"  {_label:14s}: {_val}")
    print()

    # ── 3. 生成推荐配置 ──────────────────────────────────────
    _recs = [
        ("fastcgi",       ["--cache", "fastcgi"], True,             "interactive_rec_fastcgi"),
        ("redis",         ["--redis"],            _ram_mb >= 1024,  "interactive_rec_redis"),
        ("optimize",      ["--optimize"],         True,             "interactive_rec_optimize"),
        ("autoinstall",   ["--wp-auto-install"],  True,             "interactive_rec_autoinstall"),
        ("persist_pwd",   ["--persist-root-pwd"], True,             "interactive_rec_persist_pwd"),
        ("cloudflare",    ["--cloudflare"],       False,            "interactive_rec_cloudflare"),
        ("skip_ssl",      ["--skip-ssl"],         False,            "interactive_rec_skip_ssl"),
    ]

    def _print_recs(recs):
        print(t("interactive_rec_header"))
        for _i, (_k, _f, _on, _dk) in enumerate(recs, 1):
            _icon = "" if _on else ""
            print(f"  [{_i}] {_icon} {t(_dk)}")
        print()

    _print_recs(_recs)

    # ── 4. 必要信息输入 ──────────────────────────────────────
    print(t("interactive_input_header"))

    _domain = ""
    while not _domain:
        try:
            _raw = input(f"  {t('interactive_input_domain')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {t('interactive_cancelled')}")
            return []
        if _raw and re.match(r'^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$', _raw.lower()):
            _domain = _raw.lower()
            # [V3.2.64] BUG-A: 交互模式同样剥离 www. 前缀
            if _domain.startswith("www.") and _domain.count(".") >= 2:
                _domain = _domain[4:]
                # [V3.2.66] BUG-D-2: 根据 _should_add_www() 输出准确提示
                if _should_add_www(_domain):
                    print(f"  [auto] www. 前缀已剥离, 使用裸域名: {_domain} (www 将自动添加)")
                else:
                    print(f"  [auto] www. 前缀已剥离, 使用域名: {_domain} (子域名, 不添加 www 变体)")
        elif _raw:
            print(f"  {t('interactive_invalid_domain')}")

    # ── 4b. 邮箱输入将在 toggle 确认之后，仅当 skip_ssl=off 时才询问 ────────
    # [V3.2.70] BUG-1: 原实现在用户尚未能切换 skip_ssl 之前就强制要求邮箱，
    # 导致选择 --skip-ssl 的用户仍需填写实际不会使用的邮箱地址。
    # 修复：邮箱提示推迟到 toggle 完成后，仅在 skip_ssl 未开启时要求输入。
    _email = ""  # 将在 toggle 之后按需填写

    # ── 5. 确认 & toggle ──────────────────────────────────────────────────
    print(t("interactive_confirm_header"))
    print(f"  [1] {t('interactive_confirm_go')} (Enter)")
    print(f"  [2] {t('interactive_confirm_custom')}")
    print(f"  [3] {t('interactive_confirm_cancel')}")
    print()

    try:
        _choice = input(f"  {t('interactive_confirm_prompt')}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n  {t('interactive_cancelled')}")
        return []

    if _choice == "3":
        print(f"  {t('interactive_cancelled')}")
        return []

    if _choice == "2":
        print()
        print(t("interactive_toggle_hint"))
        while True:
            print()
            for _i, (_k, _f, _on, _dk) in enumerate(_recs, 1):
                _icon = "" if _on else ""
                print(f"  [{_i}] {_icon} {t(_dk)}")
            print(f"  [0] {t('interactive_toggle_done')}")
            print()
            try:
                _tog = input(f"  {t('interactive_toggle_prompt')}: ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {t('interactive_cancelled')}")
                return []
            if _tog in ("0", ""):
                break
            try:
                _tidx = int(_tog) - 1
                if 0 <= _tidx < len(_recs):
                    _k, _f, _on, _dk = _recs[_tidx]
                    _recs[_tidx] = (_k, _f, not _on, _dk)
            except ValueError:
                pass

    # 在 toggle 循环之后计算 skip_ssl 的实际状态
    _skip_ssl_default = any(_k == "skip_ssl" and _on for _k, _f, _on, _dk in _recs)

    # [V3.2.70] BUG-1: 仅当 skip_ssl=off 时才要求邮箱（SSL 签发所需）
    if not _skip_ssl_default:
        while not _email:
            try:
                _raw = input("  " + t('interactive_input_email') + ": ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  " + t('interactive_cancelled'))
                return []
            if _raw and re.match(r'^[^@]+@[^@]+\.[^@]+$', _raw):
                _email = _raw.lower()
            elif _raw:
                print("  " + t('interactive_invalid_email'))

    # ── 6. 构建 CLI 参数 ─────────────────────────────────────
    # [V3.2.9] M-4: skip_ssl 模式下 email 可为空；
    # 不传入空 --email "" 避免等效命令提示中带此项令用户困惑
    _cli = ["deploy", "--domain", _domain]
    if _email:
        _cli.extend(["--email", _email])
    for _k, _f, _on, _dk in _recs:
        if _on:
            _cli.extend(_f)

    print()
    print(t("interactive_final_cmd"))
    _script = os.path.basename(sys.argv[0]) if sys.argv else "wp_ssl_bootstrap.py"
    print(f"  python3 {_script} {' '.join(_cli)}")
    print(t("interactive_starting"))

    return _cli


def _interactive_update_flow(domain) -> list:
    """交互式更新向导: 探测当前配置 → 切换 → 生成 CLI 参数。"""

    _cfg = _detect_site_config(domain)
    print()
    print(t("interactive_update_header", domain=domain))

    _recs = [
        ("cache",      ["--cache", "fastcgi"], _cfg["cache"] == "fastcgi", "interactive_rec_fastcgi"),
        ("redis",      ["--redis"],            _cfg["redis"],              "interactive_rec_redis"),
        ("optimize",   ["--optimize"],         _cfg["optimize"],           "interactive_rec_optimize"),
        ("autoinstall", ["--wp-auto-install"],  False,                     "interactive_rec_autoinstall"),
        ("cloudflare", ["--cloudflare"],       _cfg["cloudflare"],         "interactive_rec_cloudflare"),
        ("xmlrpc",     ["--allow-xmlrpc"],     _cfg["allow_xmlrpc"],       "interactive_update_xmlrpc"),
    ]

    print(t("interactive_toggle_hint"))
    while True:
        print()
        for _i, (_k, _f, _on, _dk) in enumerate(_recs, 1):
            _icon = "" if _on else ""
            print(f"  [{_i}] {_icon} {t(_dk)}")
        print(f"  [0] {t('interactive_toggle_done')}")
        print()
        try:
            _tog = input(f"  {t('interactive_toggle_prompt')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {t('interactive_cancelled')}")
            return []
        if _tog in ("0", ""):
            break
        try:
            _tidx = int(_tog) - 1
            if 0 <= _tidx < len(_recs):
                _k, _f, _on, _dk = _recs[_tidx]
                _recs[_tidx] = (_k, _f, not _on, _dk)
        except ValueError:
            pass

    _cli = ["update", "--domain", domain]
    for _k, _f, _on, _dk in _recs:
        if _on:
            _cli.extend(_f)

    print()
    print(t("interactive_final_cmd"))
    _script = os.path.basename(sys.argv[0]) if sys.argv else "wp_ssl_bootstrap.py"
    print(f"  python3 {_script} {' '.join(_cli)}")
    print(t("interactive_starting"))

    return _cli


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
    # [V3.2.21-AUDIT] P2-5: 外置数据库 SSL 降级选项
    sub_parser.add_argument(
        "--no-db-ssl", action="store_true", default=False,
        help="Disable SSL for external DB (for LAN/VPC direct connect)",
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
        _write_lang_file(_LANG, _env_lang())

    if os.geteuid() != 0:
        print(t("err_root_required"))
        sys.exit(1)

    # ── 语言变更检测：仅在未通过 --lang 显式指定时触发 ─────────────────────
    _prompt_lang_change()
    _prompt_china_cloud_lang()

    parser = argparse.ArgumentParser(
        description=t("parser_description") + " (V%s)" % __version__,
        usage="%(prog)s [--lang zh|en] <command> [options]",
    )
    parser.add_argument(
        "--version", action="version", version="WP-SSL-Bootstrap V%s" % __version__,
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
        "--optimize", action="store_true",
        help=t("help_optimize"),
    )
    p_deploy.add_argument(
        "--cloudflare", action="store_true",
        help=t("help_cloudflare"),
    )

    p_deploy.add_argument(
        "--skip-ssl", action="store_true",
        help=t("help_skip_ssl"),
    )

    p_deploy.add_argument(
        "--wp-auto-install", action="store_true",
        help=t("help_wp_auto_install"),
    )
    p_deploy.add_argument(
        "--persist-root-pwd", action="store_true",
        help=t("help_persist_root_pwd"),
    )
    p_deploy.add_argument(
        "--db-wait-timeout", type=int, default=None, metavar="SECONDS",
        help=t("help_db_wait_timeout"),
    )
    # [V3.2.52] ZeroSSL 备用 CA — 两个参数必须同时提供
    p_deploy.add_argument(
        "--zerossl-eab-kid",
        default=os.environ.get("WP_ZEROSSL_EAB_KID"),
        metavar="KID",
        help=t("help_zerossl_eab_kid"),
    )
    p_deploy.add_argument(
        "--zerossl-eab-hmac-key",
        default=os.environ.get("WP_ZEROSSL_EAB_HMAC_KEY"),
        metavar="HMAC_KEY",
        help=t("help_zerossl_eab_hmac"),
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
        "--optimize", action="store_true",
        help=t("help_optimize"),
    )
    p_update.add_argument(
        "--cloudflare", action="store_true",
        help=t("help_cloudflare"),
    )
    p_update.add_argument(
        "--wp-auto-install", action="store_true",
        help=t("help_wp_auto_install"),
    )
    p_update.add_argument(
        "--php-version", default=None, metavar="X.Y",
        help=t("help_php_version"),
    )

    # --- self-update 子命令 ---
    p_selfupdate = subparsers.add_parser(
        "self-update", help=t("subcmd_self_update"),
    )
    p_selfupdate.add_argument(
        "--url", dest="update_url", default="", metavar="URL",
        help=t("help_update_url"),
    )

    # --- enable-ssl 子命令 ---
    p_enable_ssl = subparsers.add_parser(
        "enable-ssl", help=t("subcmd_enable_ssl"),
    )
    _add_common_args(p_enable_ssl)
    p_enable_ssl.add_argument(
        "--email",
        default=os.environ.get("WP_EMAIL"),
        help=t("help_email"),
    )
    p_enable_ssl.add_argument(
        "--cache", choices=["none", "fastcgi"], default="none",
        help=t("help_cache_update"),
    )
    p_enable_ssl.add_argument(
        "--redis", action="store_true",
        help=t("help_redis_update"),
    )
    p_enable_ssl.add_argument(
        "--allow-xmlrpc", action="store_true",
        help=t("help_allow_xmlrpc_update"),
    )
    p_enable_ssl.add_argument(
        "--optimize", action="store_true",
        help=t("help_optimize"),
    )
    p_enable_ssl.add_argument(
        "--cloudflare", action="store_true",
        help=t("help_cloudflare"),
    )
    # [V3.2.72] Bug-4: enable-ssl 支持 --wp-auto-install, 与 deploy/update 对齐
    p_enable_ssl.add_argument(
        "--wp-auto-install", action="store_true",
        help=t("help_wp_auto_install"),
    )
    p_enable_ssl.add_argument(
        "--force", action="store_true",
        help=t("help_force_renew"),
    )
    # [V3.2.37] P-7: enable-ssl 支持 --persist-root-pwd,
    # 防止 enable-ssl 后续流程中 DB 密码文件丢失。
    p_enable_ssl.add_argument(
        "--persist-root-pwd", action="store_true",
        help=t("help_persist_root_pwd"),
    )
    # [V3.2.52] ZeroSSL 备用 CA — 两个参数必须同时提供
    p_enable_ssl.add_argument(
        "--zerossl-eab-kid",
        default=os.environ.get("WP_ZEROSSL_EAB_KID"),
        metavar="KID",
        help=t("help_zerossl_eab_kid"),
    )
    p_enable_ssl.add_argument(
        "--zerossl-eab-hmac-key",
        default=os.environ.get("WP_ZEROSSL_EAB_HMAC_KEY"),
        metavar="HMAC_KEY",
        help=t("help_zerossl_eab_hmac"),
    )


    # --- uninstall 子命令 ---
    p_uninstall = subparsers.add_parser(
        "uninstall", help=t("subcmd_uninstall"),
    )
    _add_common_args(p_uninstall)

    args = parser.parse_args()

    # [V3.2.0] 未指定子命令: TTY 终端进入交互式向导, 非 TTY 打印帮助
    if not args.command:
        if sys.stdin.isatty():
            _interactive_args = _interactive_mode()
            if not _interactive_args:
                sys.exit(0)
            args = parser.parse_args(_interactive_args)
        else:
            parser.print_help()
            sys.exit(1)

    # [V3.0.16] P10: self-update 不需要 --domain
    # [V3.2.3] L-4: self-update 提前退出, 跳过后续 SiteConfig 初始化
    # 及其触发的 _is_china_cloud() HTTP 元数据探测请求
    if args.command == "self-update":
        logging.info(t("info_self_update_checking"))
        _do_self_update(update_url=getattr(args, "update_url", ""))
        sys.exit(0)

    if not args.domain:
        parser.error(t("err_no_domain"))

    # email 仅 deploy 时强制要求
    # [V3.2.3] M-6: --skip-ssl 时 email 非必填 (仅 SSL 签发需要)
    if args.command == "enable-ssl" or (
        args.command == "deploy" and not getattr(args, 'skip_ssl', False)
    ):
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
    elif args.command == "enable-ssl":
        # [FIX-5] email 已在上方统一校验, 无需重复
        manager.setup_signals()
        manager.acquire_lock()
        _sub_exit = 0
        try:
            if not manager.enable_ssl(
                force_renew=getattr(args, 'force', False)
            ):
                _sub_exit = 1
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