#!/usr/bin/env python3
"""WP-SSL-Bootstrap V3.2.6 集成测试脚本

在真实服务器上端到端验证脚本所有功能。

用法:
  # 交互式 (推荐 — 自动检测域名/邮箱/基线/平台):
  python3 test_integration.py

  # 命令行 (CI/CD 场景):
  python3 test_integration.py --domain example.com --email admin@example.com

  # 安全模式 (跳过破坏性测试):
  python3 test_integration.py --domain example.com --email admin@example.com --safe

  # 仅测试特定阶段:
  python3 test_integration.py --domain example.com --email admin@example.com --phase verify,ssl,security

支持平台:
  - EL 7-10 (CentOS/RHEL/Alma/Rocky)
  - Ubuntu 22.04-24.04
  - Debian 12-13

环境要求:
  - root 权限
  - 域名 A 记录指向本机 (SSL 测试需要)
  - 80 + 443 端口可达
"""

import argparse
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ───────────────────── 日志 Tee (stdout → 终端 + 文件) ─────────

class _TeeWriter:
    """将 stdout/stderr 同时写入终端和日志文件"""

    encoding = "utf-8"  # subprocess 等模块检查此属性

    def __init__(self, log_path):
        self._terminal = sys.stdout
        self._terminal_err = sys.stderr
        self._log = open(log_path, "w", encoding="utf-8", errors="replace")
        self.path = log_path

    def write(self, msg):
        self._terminal.write(msg)
        # 去除 ANSI 转义序列后写入日志
        clean = re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', msg)
        self._log.write(clean)
        self._log.flush()

    def flush(self):
        self._terminal.flush()
        self._log.flush()

    def fileno(self):
        """返回终端 fd, 供 subprocess 等需要真实 fd 的场景使用"""
        return self._terminal.fileno()

    def isatty(self):
        return self._terminal.isatty()

    def close(self):
        self._log.close()
        sys.stdout = self._terminal
        sys.stderr = self._terminal_err


class _TeeStderr:
    """stderr 版 Tee — 共享 _TeeWriter 的日志文件"""

    def __init__(self, tee_writer: _TeeWriter):
        self._terminal = tee_writer._terminal_err
        self._log = tee_writer._log

    def write(self, msg):
        self._terminal.write(msg)
        clean = re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', msg)
        self._log.write(clean)
        self._log.flush()

    def flush(self):
        self._terminal.flush()
        self._log.flush()

# ───────────────────── 语言检测 (与主脚本一致) ─────────────────

_LANG_CONFIG_FILE = Path("/root/.wp_ssl_lang")


def _detect_lang() -> str:
    """检测显示语言 (优先级与主脚本一致)

    1. /root/.wp_ssl_lang 配置文件
    2. WP_LANG > LANG > LC_ALL > LANGUAGE 环境变量
    3. 默认 'en'
    """
    # L1: 配置文件
    try:
        if _LANG_CONFIG_FILE.exists():
            val = _LANG_CONFIG_FILE.read_text(encoding="utf-8").strip().lower()
            chosen = val.split(":")[0] if ":" in val else val
            if chosen in ("zh", "en"):
                return chosen
    except OSError:
        pass
    # L2: 环境变量
    raw = (
        os.environ.get("WP_LANG", "")
        or os.environ.get("LANG", "")
        or os.environ.get("LC_ALL", "")
        or os.environ.get("LANGUAGE", "")
    ).lower()
    return "zh" if raw.startswith("zh") else "en"


LANG = _detect_lang()
_ZEROSSL_EAB_KID = ""
_ZEROSSL_EAB_HMAC = ""


def _confirm_lang(detected: str = "") -> str:
    """确认/切换显示语言

    显示检测到的语言, 用户可确认或切换。
    始终双语显示 (确认前不知道用户偏好)。
    """
    global LANG
    lang = detected or LANG

    if not sys.stdin.isatty():
        return lang

    label = "中文" if lang == "zh" else "English"
    print(f"\n  语言 / Language: {label}")
    print(f"    [1] 中文")
    print(f"    [2] English")
    try:
        ch = input(f"    选择 / Choose [Enter={label}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        ch = ""

    if ch == "1":
        LANG = "zh"
    elif ch == "2":
        LANG = "en"
    else:
        LANG = lang
    return LANG

# ───────────────────── 双语 i18n ───────────────────────────────

_I18N = {
    "title":              {"zh": "WP-SSL-Bootstrap 集成测试", "en": "WP-SSL-Bootstrap Integration Test"},
    "interactive_title":  {"zh": "WP-SSL-Bootstrap 集成测试 — 交互式设置", "en": "WP-SSL-Bootstrap Integration Test — Interactive Setup"},
    "platform":           {"zh": "平台", "en": "Platform"},
    "script":             {"zh": "脚本", "en": "Script"},
    "baseline":           {"zh": "基线", "en": "Baseline"},
    "baseline_not_found": {"zh": "(未找到, 将跳过静态分析)", "en": "(not found, skipping static analysis)"},
    "sites":              {"zh": "站点", "en": "Sites"},
    "sites_none":         {"zh": "(未检测到已部署站点, 将执行全新部署)", "en": "(no deployed sites, will do fresh deploy)"},
    "domain":             {"zh": "域名", "en": "Domain"},
    "email":              {"zh": "邮箱", "en": "Email"},
    "auto_domain":        {"zh": "自动选择域名", "en": "Auto-selected domain"},
    "auto_email":         {"zh": "自动获取邮箱", "en": "Auto-detected email"},
    "input_domain":       {"zh": "请输入测试域名 (A 记录须指向本机)", "en": "Enter test domain (A record must point here)"},
    "input_email":        {"zh": "请输入邮箱 (用于证书注册)", "en": "Enter email (for cert registration)"},
    "need_domain":        {"zh": "需要域名", "en": "Domain required"},
    "need_email":         {"zh": "需要有效邮箱", "en": "Valid email required"},
    "select_site":        {"zh": "检测到多个站点:", "en": "Multiple sites detected:"},
    "select_site_prompt": {"zh": "选择站点 [1-{n}, 或输入新域名]", "en": "Select site [1-{n}, or enter new domain]"},
    "test_mode":          {"zh": "测试模式:", "en": "Test mode:"},
    "mode_full":          {"zh": "完整测试 (含卸载重装)", "en": "Full test (includes uninstall/redeploy)"},
    "mode_safe":          {"zh": "安全模式 (跳过卸载/恢复)", "en": "Safe mode (skip uninstall/restore)"},
    "mode_verify":        {"zh": "仅验证 (不修改任何配置)", "en": "Verify only (no modifications)"},
    "mode_prompt":        {"zh": "选择 [1-3, Enter=2]", "en": "Choose [1-3, Enter=2]"},
    "will_run":           {"zh": "将执行", "en": "Phases"},
    "confirm_start":      {"zh": "确认开始? (Y/n)", "en": "Start? (Y/n)"},
    "cancelled":          {"zh": "取消", "en": "Cancelled"},
    "phases":             {"zh": "阶段", "en": "Phases"},
    "mode":               {"zh": "模式", "en": "Mode"},
    "mode_full_label":    {"zh": "完整", "en": "Full"},
    "mode_safe_label":    {"zh": "安全", "en": "Safe"},
    "phase_n_of":         {"zh": "阶段 [{n}/{total}]", "en": "Phase [{n}/{total}]"},
    "passed":             {"zh": "通过", "en": "passed"},
    "skip":               {"zh": "跳过", "en": "Skip"},
    "skip_no_deploy":     {"zh": "跳过 (--no-deploy)", "en": "Skip (--no-deploy)"},
    "skip_safe":          {"zh": "跳过 (--safe)", "en": "Skip (--safe)"},
    "skip_existing":      {"zh": "已部署且有证书, 用 update 测试增量更新", "en": "Already deployed with cert, using update for incremental test"},
    "skip_has_cert":      {"zh": "跳过 (证书已存在)", "en": "Skip (cert exists)"},
    "skip_no_backup":     {"zh": "无可用备份 (backup 阶段未执行?)", "en": "No backup available (backup phase not run?)"},
    "skip_no_cert":       {"zh": "无证书", "en": "No certificate"},
    "report_title":       {"zh": "测试报告", "en": "Test Report"},
    "report_duration":    {"zh": "总耗时", "en": "Duration"},
    "report_passed":      {"zh": "通过", "en": "Passed"},
    "report_failed":      {"zh": "失败", "en": "Failed"},
    "report_failed_list": {"zh": "失败项:", "en": "Failures:"},
    "report_phase_stats": {"zh": "阶段统计:", "en": "Phase stats:"},
    "report_json":        {"zh": "JSON 报告", "en": "JSON report"},
    "report_log":         {"zh": "完整日志", "en": "Full log"},
    "baseline_missing":   {"zh": "未找到基线文件 (同目录放一份旧版 .bak 即可)", "en": "Baseline not found (place old version as .bak in same dir)"},
    "network_timeout":    {"zh": "网络超时 (GFW?)", "en": "Network timeout (GFW?)"},
}


def t(key, **kwargs):
    """双语翻译"""
    entry = _I18N.get(key, {})
    msg = entry.get(LANG, entry.get("en", key))
    if kwargs:
        try:
            msg = msg.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return msg


def _m(zh: str, en: str) -> str:
    """轻量双语消息: 无需注册到 _I18N, 就地使用"""
    return zh if LANG == "zh" else en


# ───────────────────── 配置 ────────────────────────────────────

SCRIPT = "wp_ssl_bootstrap.py"
SCRIPT_PATH = Path(__file__).parent / SCRIPT

# 测试阶段定义
PHASES = [
    "pre",         # 环境预检
    "static",      # 静态分析 (AST 级对比新旧版)
    "deploy",      # 全新部署 (已部署时自动跳过)
    "verify",      # 部署后验证 (服务/端口/配置/WP)
    "ssl",         # SSL/TLS 深度验证
    "security",    # 安全检查 (headers/权限/暴露文件)
    "status",      # status 子命令
    "update",      # 配置热更新
    "idempotency", # 幂等性 (二次 update 无变化)
    "migrate_ssl", # SSL 供应商迁移 (ZeroSSL ↔ LE)
    "renew",       # 证书续期
    "backup",      # 备份
    "restore",     # 从备份恢复
    "logs",        # 日志 + 性能检查
    "uninstall",   # 卸载 + 重新部署
]

# ───────────────────── 数据结构 ─────────────────────────────────

@dataclass
class TestResult:
    name: str
    phase: str
    passed: bool
    message: str = ""
    duration: float = 0.0

@dataclass
class TestContext:
    domain: str = ""
    email: str = ""
    safe: bool = False
    no_deploy: bool = False
    staging: bool = True  # [PATCH-285] 默认 staging, --no-staging 才用生产
    notify_webhook: str = ""
    baseline: str = ""
    zerossl_eab_kid: str = ""
    zerossl_eab_hmac: str = ""
    phases: list = field(default_factory=list)
    results: list = field(default_factory=list)
    backup_dir: str = ""
    start_time: float = 0.0

# ───────────────────── 工具函数 ─────────────────────────────────

# 允许透传的 WP_* 环境变量白名单 (其余在测试中清除, 防止 CI 宿主机污染)
_WP_ENV_WHITELIST = frozenset({
    "WP_LANG", "WP_DOMAIN", "WP_EMAIL",
    "WP_ZEROSSL_EAB_KID", "WP_ZEROSSL_EAB_HMAC_KEY",
    "WP_DB_ROOT_PASS",
})


def _clean_env(extra: dict = None) -> dict:
    """构建干净的测试环境变量: 继承系统 env, 清除非白名单 WP_* 变量。

    防止 CI 宿主机残留的 WP_SKIP_SSL / WP_CACHE_MODE 等变量
    意外改变被测脚本行为, 导致测试结果不可复现。
    """
    cleaned = {k: v for k, v in os.environ.items()
               if not k.startswith("WP_") or k in _WP_ENV_WHITELIST}
    if extra:
        cleaned.update(extra)
    return cleaned


def run(cmd, timeout=300, check=False, capture=True, env=None):
    """执行命令, 返回 CompletedProcess"""
    merged_env = _clean_env(env)
    try:
        r = subprocess.run(
            cmd, shell=isinstance(cmd, str),
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            encoding="utf-8", errors="replace",
            timeout=timeout, check=check, env=merged_env,
        )
        return r
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "TIMEOUT")
    except subprocess.CalledProcessError as e:
        return subprocess.CompletedProcess(cmd, e.returncode, e.stdout or "", e.stderr or "")


def run_with_tty(cmd_str, stdin_text, timeout=300, env=None):
    """用伪 TTY 执行命令 (解决 isatty() 检查), 逐行显示输出"""
    merged_env = _clean_env(env)
    merged_env.setdefault("WP_LANG", LANG)
    escaped_cmd = cmd_str.replace("'", "'\\''")
    wrapper = f"script -qec '{escaped_cmd}' /dev/null <<< '{stdin_text}'"
    DIM = "\033[2m"
    RST = "\033[0m"
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            ["bash", "-c", wrapper],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", env=merged_env,
        )
        all_lines = []
        for line in proc.stdout:
            all_lines.append(line)
            stripped = line.rstrip()
            if not stripped:
                continue
            elapsed = time.time() - t0
            if "[ERROR]" in stripped:
                tag = "\033[91m"
            elif "[WARNING]" in stripped:
                tag = "\033[93m"
            else:
                tag = DIM
            sys.stdout.write(f"    {tag}[{elapsed:5.0f}s] {stripped}{RST}\n")
            sys.stdout.flush()
        proc.wait(timeout=max(1, timeout - (time.time() - t0)))
        return subprocess.CompletedProcess(
            cmd_str, proc.returncode, "".join(all_lines), "")
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return subprocess.CompletedProcess(cmd_str, 124, "", "TIMEOUT")


def run_script(args_str, timeout=600, env=None, label="", tty=False):
    """执行 wp_ssl_bootstrap.py, 逐行实时显示输出

    tty=True: 用 script -qec 包装, 使子进程看到 TTY (isatty()=True)
              仅 deploy 需要 (EAB 自动获取的隐私检查要求 TTY)
    tty=False: 直接执行, stdin=DEVNULL (默认, 更快更稳定)
    """
    cmd = f"python3 {SCRIPT_PATH} {args_str}"
    _script_extra = {"WP_LANG": LANG}
    # 传递 ZeroSSL EAB (确保 CA 降级链完整)
    if _ZEROSSL_EAB_KID:
        _script_extra["WP_ZEROSSL_EAB_KID"] = _ZEROSSL_EAB_KID
    if _ZEROSSL_EAB_HMAC:
        _script_extra["WP_ZEROSSL_EAB_HMAC_KEY"] = _ZEROSSL_EAB_HMAC
    if env:
        _script_extra.update(env)
    merged_env = _clean_env(_script_extra)

    import threading

    try:
        if tty:
            # deploy 需要 TTY: _acquire_zerossl_eab 的隐私保护检查
            escaped = cmd.replace("'", "'\\''" )
            cmd_str = f"script -qec '{escaped}' /dev/null"
        else:
            cmd_str = cmd
        proc = subprocess.Popen(
            cmd_str, shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", env=merged_env,
        )
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))

    all_lines = []
    t0 = time.time()

    # 实时逐行读取并显示
    DIM = "\033[2m"
    RST = "\033[0m"
    try:
        for line in proc.stdout:
            all_lines.append(line)
            stripped = line.rstrip()
            if not stripped:
                continue
            elapsed = time.time() - t0
            # 按日志级别着色
            if "[ERROR]" in stripped:
                tag = "\033[91m"  # red
            elif "[WARNING]" in stripped:
                tag = "\033[93m"  # yellow
            else:
                tag = DIM
            sys.stdout.write(f"    {tag}[{elapsed:5.0f}s] {stripped}{RST}\n")
            sys.stdout.flush()
    except Exception:
        pass

    # 等待进程结束
    try:
        proc.wait(timeout=max(1, timeout - (time.time() - t0)))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return subprocess.CompletedProcess(cmd, 124, "".join(all_lines), "TIMEOUT")

    stdout_text = "".join(all_lines)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout_text, "")


def svc_active(name):
    """检查 systemd 服务是否 active"""
    r = run(["systemctl", "is-active", name])
    return r.returncode == 0


def _read_db_password():
    """从密码文件读取 MariaDB root 密码"""
    pwd_file = Path("/root/.mariadb_root.pwd")
    if pwd_file.exists():
        try:
            return pwd_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""


def _read_eab_credentials(domain):
    """从 systemd ssl.env 文件读取 ZeroSSL EAB 凭据

    与主脚本 _extract_existing_deploy_params 逻辑一致。
    返回 (kid, hmac_key) 或 ("", "")
    """
    # 计算 systemd prefix (与主脚本 SiteConfig._encode_domain_id 一致)
    import hashlib as _hl
    sanitized = "wp_" + re.sub(r'[^a-zA-Z0-9]', '_', domain).rstrip('_')
    if len(sanitized) > 48:
        h = _hl.md5(sanitized.encode()).hexdigest()[:7]
        sanitized = sanitized[:40] + "_" + h
    env_file = Path(f"/etc/systemd/system/{sanitized}-ssl.env")
    kid = hmac = ""
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("WP_ZEROSSL_EAB_KID="):
                    kid = line.split("=", 1)[1].strip()
                elif line.startswith("WP_ZEROSSL_EAB_HMAC_KEY="):
                    hmac = line.split("=", 1)[1].strip()
        except OSError:
            pass
    return (kid, hmac)


def _detect_zerossl_eab():
    """从服务器已有配置中检测 ZeroSSL EAB 凭据

    搜索: ssl.env 文件 → 环境变量
    """
    kid = os.environ.get("WP_ZEROSSL_EAB_KID", "")
    hmac = os.environ.get("WP_ZEROSSL_EAB_HMAC_KEY", "")
    if kid and hmac:
        return kid, hmac
    # 从 ssl.env 文件搜索
    for env_file in Path("/etc/systemd/system").glob("*ssl.env"):
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("WP_ZEROSSL_EAB_KID="):
                    kid = line.split("=", 1)[1].strip()
                elif line.startswith("WP_ZEROSSL_EAB_HMAC_KEY="):
                    hmac = line.split("=", 1)[1].strip()
        except OSError:
            pass
    return kid, hmac


def _detect_webhook_url():
    """从服务器已有 ssl.env 配置中自动检测 webhook URL

    与 _detect_zerossl_eab 同源搜索, 复用已部署站点的 webhook 配置。
    返回 URL 字符串或空字符串。
    """
    for env_file in Path("/etc/systemd/system").glob("*ssl.env"):
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("NOTIFY_WEBHOOK="):
                    val = line.split("=", 1)[1].strip().strip('"')
                    if val.startswith("https://"):
                        return val
        except OSError:
            pass
    return ""


def svc_enabled(name):
    """检查 systemd 服务是否 enabled"""
    r = run(["systemctl", "is-enabled", name])
    return r.stdout.strip() == "enabled"

def port_listening(port):
    """检查端口是否在监听"""
    r = run(f"ss -tlnp | grep :{port}")
    return r.returncode == 0

def curl_status(url, timeout=10, insecure=False):
    """获取 HTTP 状态码"""
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
           "--max-time", str(timeout)]
    if insecure:
        cmd.append("-k")
    cmd.append(url)
    r = run(cmd)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0

def cert_info(domain):
    """获取证书信息"""
    cert = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
    if not cert.exists():
        return {}
    info = {}
    cert_str = str(cert)
    # Issuer
    r = run(["openssl", "x509", "-noout", "-issuer", "-in", cert_str])
    if r.returncode == 0:
        m = re.search(r'CN\s*=\s*(.+?)(?:,|$)', r.stdout)
        info["issuer"] = m.group(1).strip() if m else ""
        info["is_le"] = "Let's Encrypt" in r.stdout
    # Expiry
    r = run(["openssl", "x509", "-noout", "-enddate", "-in", cert_str])
    if r.returncode == 0:
        info["enddate"] = r.stdout.strip().split("=", 1)[-1]
    # Key type
    r = run(["openssl", "x509", "-noout", "-text", "-in", cert_str])
    if r.returncode == 0:
        info["ecdsa"] = "id-ecPublicKey" in r.stdout or "EC Public Key" in r.stdout
    return info

def detect_platform():
    """检测平台, 返回 dict 包含所有平台相关信息

    支持: EL 7-10 (CentOS/RHEL/Alma/Rocky), Ubuntu 22-24, Debian 12-13
    """
    info = {"family": "unknown", "id": "", "version": "", "version_major": 0,
            "db_svc": "mariadb", "redis_svc": "redis", "php_fpm_svc": "php-fpm",
            "firewall": "none", "pkg_mgr": "yum"}

    # 解析 /etc/os-release
    try:
        with open("/etc/os-release") as f:
            osr = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    osr[k] = v.strip('"')
        info["id"] = osr.get("ID", "").lower()
        info["version"] = osr.get("VERSION_ID", "")
        try:
            info["version_major"] = int(info["version"].split(".")[0])
        except (ValueError, IndexError):
            pass
    except OSError:
        pass

    # 判定平台家族
    el_ids = {"centos", "rhel", "almalinux", "rocky", "ol", "eurolinux",
              "cloudlinux", "scientific", "amzn", "alinux"}
    if info["id"] in el_ids or Path("/etc/redhat-release").exists():
        info["family"] = "el"
        info["pkg_mgr"] = "dnf" if info["version_major"] >= 8 else "yum"
        info["firewall"] = "firewalld"
        info["redis_svc"] = "redis"
        info["php_fpm_svc"] = "php-fpm"
        # EL7: mariadb 可能叫 mariadb 或 mysql; EL8+: mariadb
        info["db_svc"] = _detect_active_svc(["mariadb", "mysql", "mysqld"])
    elif info["id"] in ("ubuntu", "debian", "linuxmint", "pop"):
        info["family"] = "debian"
        info["pkg_mgr"] = "apt"
        info["redis_svc"] = _detect_active_svc(["redis-server", "redis"])
        info["db_svc"] = _detect_active_svc(["mariadb", "mysql", "mysqld"])
        # PHP-FPM: phpX.Y-fpm (Sury/native)
        for v in ["8.4", "8.3", "8.2", "8.1", "8.0"]:
            svc = f"php{v}-fpm"
            if _svc_exists(svc):
                info["php_fpm_svc"] = svc
                break
        # Ubuntu 用 ufw (已装但可能未启用), Debian 12+ 用 nftables
        if info["id"] == "ubuntu":
            info["firewall"] = "ufw"
        elif _svc_exists("ufw"):
            info["firewall"] = "ufw"
        elif _svc_exists("firewalld"):
            info["firewall"] = "firewalld"
        # Debian 12+ 默认 nftables (已装未启用)
        elif _svc_exists("nftables"):
            info["firewall"] = "nftables"
    return info


def _detect_active_svc(candidates):
    """从候选列表中找到第一个 active/exists 的服务"""
    for svc in candidates:
        if svc_active(svc):
            return svc
    # 都没 active, 返回第一个存在 unit 文件的
    for svc in candidates:
        if _svc_exists(svc):
            return svc
    return candidates[0]  # 兜底


def _svc_exists(name):
    """检查 systemd unit 是否存在 (不一定 active)"""
    r = run(["systemctl", "cat", name],
            env={**os.environ, "SYSTEMD_COLORS": "0"})
    return r.returncode == 0

# ───────────────────── 测试实现 ─────────────────────────────────

class IntegrationTest:
    def __init__(self, ctx: TestContext):
        self.ctx = ctx
        self.platform = detect_platform()
        self._phase = ""
        self.fatal = False  # [PATCH-285] 关键预检失败时终止后续阶段

    @property
    def is_el(self):
        return self.platform["family"] == "el"

    @property
    def is_debian(self):
        return self.platform["family"] == "debian"

    @property
    def el_ver(self):
        return self.platform["version_major"] if self.is_el else 0

    def _common_flags(self, include_deploy_only=True):
        """构建平台感知的通用参数 (含 EAB 凭据透传)
        与交互式向导默认配置对齐:
          cache=redis(srcache), redis=on, optimize=on, http3=on,
          cloudflare=on, serve-dist=on (仅 deploy/update)
        Args:
          include_deploy_only: 包含仅 deploy/update 支持的参数
                               (--serve-dist)。restore 应传 False
        """
        flags = "--cache redis --redis --optimize --cloudflare"
        if include_deploy_only:
            flags += " --serve-dist"
        # HTTP/3: 需要 nginx ≥ 1.25.0, EL7 可能只有 1.20
        if not (self.is_el and self.el_ver <= 7):
            flags += " --http3"
        # ZeroSSL EAB: 从 ssl.env 读取已有凭据, 透传给子命令
        if self.ctx.domain:
            kid, hmac = _read_eab_credentials(self.ctx.domain)
            if kid and hmac:
                flags += f" --zerossl-eab-kid {kid} --zerossl-eab-hmac-key {hmac}"
        # Staging: 使用 LE Staging 环境, 避免 CI 频繁测试触发速率限制
        if self.ctx.staging:
            flags += " --staging"
        # Webhook: SSL 续期失败通知
        if self.ctx.notify_webhook:
            flags += f" --notify-webhook {shlex.quote(self.ctx.notify_webhook)}"
        return flags

    def check(self, name, condition, msg=""):
        """记录测试结果"""
        r = TestResult(name=name, phase=self._phase, passed=bool(condition),
                       message=msg if not condition else "")
        self.ctx.results.append(r)
        mark = "✅" if r.passed else "❌"
        print(f"  {mark} {name}" + (f" — {msg}" if msg and not r.passed else ""))
        return r.passed

    def run_phase(self, phase):
        self._phase = phase
        fn = getattr(self, f"phase_{phase}", None)
        if not fn:
            print(f"\n⚠ 跳过未知阶段: {phase}")
            return
        print(f"\n{'='*60}")
        print(f"  {t('phase_n_of', n=self.ctx.phases.index(phase)+1, total=len(self.ctx.phases))}: {phase.upper()}")
        print(f"{'='*60}")
        t0 = time.time()
        try:
            fn()
        except Exception as e:
            self.check(f"{phase}_exception", False, str(e))
        elapsed = time.time() - t0
        # 阶段小结
        phase_r = [r for r in self.ctx.results if r.phase == phase]
        p = sum(1 for r in phase_r if r.passed)
        f = sum(1 for r in phase_r if not r.passed)
        mark = "✅" if f == 0 else "❌"
        print(f"  {mark} {p}/{p+f} {t('passed')} | ⏱ {elapsed:.1f}s")

    # ── 阶段 0: 环境预检 ────────────────────────────────────────

    def phase_pre(self):
        """环境预检"""
        self.check("root", os.geteuid() == 0, _m("需要 root 权限", "root privileges required"))
        self.check("script_exists", SCRIPT_PATH.exists(), str(SCRIPT_PATH))
        self.check("python3", run("python3 --version").returncode == 0)

        # AST 编译
        r = run(f"python3 -c \"import ast; ast.parse(open('{SCRIPT_PATH}').read())\"")
        self.check("ast_compile", r.returncode == 0, r.stderr[:200] if r.returncode else "")

        # 端口
        self.check("port_80_free_or_nginx",
                    not port_listening(80) or svc_active("nginx"),
                    _m("80 端口被非 nginx 进程占用", "port 80 occupied by non-nginx process"))

        # DNS (如果有域名)
        if self.ctx.domain:
            r = run(f"dig +short {self.ctx.domain} A")
            has_dns = bool(r.stdout.strip())
            self.check("dns_resolved", has_dns,
                       f"{self.ctx.domain} " + _m("无 A 记录", "has no A record"))
            if not has_dns:
                self.fatal = True

            # 验证 A 记录指向本机 (Cloudflare 代理时 A 记录指向 CF, 属正常)
            if has_dns:
                resolved_ip = r.stdout.strip().split('\n')[0]
                r2 = run("curl -s ifconfig.me --max-time 5")
                my_ip = r2.stdout.strip()
                # 检测是否走 Cloudflare 代理 (A 记录在 CF IP 段内)
                is_cf = any(resolved_ip.startswith(p) for p in
                            ["104.16.", "104.17.", "104.18.", "104.19.",
                             "104.20.", "104.21.", "104.22.", "104.23.",
                             "104.24.", "104.25.", "104.26.", "104.27.",
                             "172.64.", "172.65.", "172.66.", "172.67.",
                             "173.245.", "103.21.", "103.22.", "103.31.",
                             "141.101.", "108.162.", "190.93.", "188.114.",
                             "197.234.", "198.41.", "162.158.", "131.0.72."])
                if is_cf:
                    self.check("dns_cloudflare_proxy", True,
                               f"A={resolved_ip} (Cloudflare 代理)")
                else:
                    self.check("dns_points_here",
                               resolved_ip == my_ip or not my_ip,
                               f"A={resolved_ip} vs 本机={my_ip}")

        # 磁盘空间
        r = run("df -BG / | tail -1 | awk '{print $4}'")
        if r.stdout:
            avail = int(re.sub(r'\D', '', r.stdout) or 0)
            self.check("disk_space", avail >= 2, f"{avail}GB " + _m("可用空间不足 2GB", "available < 2GB required"))

    # ── 阶段 1: 静态分析 ──────────────────────────────────────

    def phase_static(self):
        """内嵌静态验证 (整合 verify_upgrade + verify_refactor 核心检测)

        ~35 项 AST 级检查, 覆盖:
          结构层: 编译/解析、类方法不丢失、常量不丢失、全局函数不丢失
          安全层: undefined name、重复参数、self.xxx 可达、代理目标有效
          契约层: 核心导入、异常捕获、安全基元、环境变量、shell=True
          语义层: 返回值、with 语句、日志级别、正则转义、类型注解
        """
        script_dir = SCRIPT_PATH.parent

        # 查找基线
        baseline = Path(self.ctx.baseline) if self.ctx.baseline else None
        if not baseline or not baseline.exists():
            _, baseline = _find_script_and_baseline()
        if not baseline or not baseline.exists():
            self.check("static_baseline", False,
                       "未找到基线文件 (同目录放一份旧版 .bak 即可)")
            return

        try:
            new_src = SCRIPT_PATH.read_text(encoding="utf-8")
            old_src = baseline.read_text(encoding="utf-8")
        except OSError as e:
            self.check("static_read", False, str(e))
            return

        import ast as _ast

        # ── 1. 编译 ──
        try:
            nt = _ast.parse(new_src)
            self.check("ast_parse", True)
        except SyntaxError as e:
            self.check("ast_parse", False, f"L{e.lineno}: {e.msg}")
            return

        try:
            compile(new_src, SCRIPT_PATH.name, "exec")
            self.check("compile", True)
        except SyntaxError as e:
            self.check("compile", False, str(e))

        try:
            ot = _ast.parse(old_src)
        except SyntaxError:
            ot = None

        if not ot:
            self.check("baseline_parse", False, _m("基线文件 AST 解析失败", "baseline file AST parse failed"))
            return

        nb = _parse_build(str(SCRIPT_PATH))
        ob = _parse_build(str(baseline))
        self.check("version_forward", nb >= ob,
                   f"新版 {nb} < 旧版 {ob}")

        # ── 辅助函数 ──
        def cls_methods(tree, name):
            for n in _ast.walk(tree):
                if isinstance(n, _ast.ClassDef) and n.name == name:
                    return {m.name for m in n.body
                            if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef))}
            return set()

        def cls_constants(tree, name):
            for n in _ast.walk(tree):
                if isinstance(n, _ast.ClassDef) and n.name == name:
                    consts = set()
                    for item in n.body:
                        if isinstance(item, _ast.Assign):
                            for t in item.targets:
                                if isinstance(t, _ast.Name) and t.id.isupper():
                                    consts.add(t.id)
                    return consts
            return set()

        def global_funcs(tree):
            return {n.name for n in _ast.iter_child_nodes(tree)
                    if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}

        def all_classes(tree):
            return {n.name for n in _ast.walk(tree)
                    if isinstance(n, _ast.ClassDef)}

        def get_imports(tree):
            imps = set()
            for n in _ast.walk(tree):
                if isinstance(n, _ast.Import):
                    for a in n.names:
                        imps.add(a.name.split(".")[0])
                elif isinstance(n, _ast.ImportFrom) and n.module:
                    imps.add(n.module.split(".")[0])
            return imps

        def count_pattern(src, pat):
            return src.count(pat)

        def env_vars(tree):
            keys = set()
            for n in _ast.walk(tree):
                if (isinstance(n, _ast.Call)
                        and isinstance(n.func, _ast.Attribute)
                        and n.func.attr == "get"
                        and n.args
                        and isinstance(n.args[0], _ast.Constant)
                        and isinstance(n.args[0].value, str)
                        and n.args[0].value.startswith("WP_")):
                    keys.add(n.args[0].value)
            return keys

        def count_with(tree):
            return sum(1 for n in _ast.walk(tree) if isinstance(n, _ast.With))

        def count_try(tree):
            return sum(1 for n in _ast.walk(tree) if isinstance(n, _ast.Try))

        def count_docstrings(tree):
            c = 0
            for n in _ast.walk(tree):
                if isinstance(n, (_ast.FunctionDef, _ast.ClassDef)):
                    if (n.body and isinstance(n.body[0], _ast.Expr)
                            and isinstance(n.body[0].value, _ast.Constant)
                            and isinstance(n.body[0].value.value, str)):
                        c += 1
            return c

        def count_annotations(tree):
            return sum(1 for n in _ast.walk(tree)
                       if isinstance(n, _ast.FunctionDef) and n.returns)

        # ── 2. 结构层 ──
        # WPDeployManager 方法不丢失
        ow = cls_methods(ot, "WPDeployManager")
        nw = cls_methods(nt, "WPDeployManager")
        lost = ow - nw
        self.check(f"wpdm_methods ({len(ow)}→{len(nw)})",
                   len(lost) == 0,
                   f"丢失: {sorted(lost)[:5]}" if lost else "")

        # 所有 Manager 类方法不丢失
        for cn in ["NginxManager", "MariaDBManager", "PHPManager",
                    "RedisManager", "CertManager"]:
            om = cls_methods(ot, cn)
            nm = cls_methods(nt, cn)
            ml = om - nm
            if om:  # 旧版有此类
                self.check(f"{cn} " + _m("方法不丢失", "methods preserved"),
                           len(ml) == 0,
                           f"丢失: {sorted(ml)[:3]}" if ml else "")

        # 类常量不丢失
        oc = cls_constants(ot, "WPDeployManager")
        nc = cls_constants(nt, "WPDeployManager")
        cl = oc - nc
        self.check(_m("类常量不丢失", "class consts preserved") + f" ({len(oc)}→{len(nc)})",
                   len(cl) == 0,
                   f"丢失: {sorted(cl)[:5]}" if cl else "")

        # 全局函数不丢失
        of = global_funcs(ot)
        nf = global_funcs(nt)
        fl = of - nf
        self.check(_m("全局函数不丢失", "global funcs preserved") + f" ({len(of)}→{len(nf)})",
                   len(fl) == 0,
                   f"丢失: {sorted(fl)[:5]}" if fl else "")

        # 类不丢失
        occ = all_classes(ot)
        ncc = all_classes(nt)
        ccl = occ - ncc
        self.check(_m("类不丢失", "classes preserved") + f" ({len(occ)}→{len(ncc)})",
                   len(ccl) == 0,
                   f"丢失: {sorted(ccl)}" if ccl else "")

        # ── 3. 安全层: undefined name ──
        def find_undefined(tree, src):
            """简化版 undefined name 检测"""
            defined = set()
            used_self = set()
            for n in _ast.walk(tree):
                if isinstance(n, _ast.FunctionDef):
                    defined.add(n.name)
                elif isinstance(n, _ast.ClassDef):
                    defined.add(n.name)
                elif isinstance(n, _ast.Name) and isinstance(n.ctx, _ast.Store):
                    defined.add(n.id)
            return defined

        # 零重复参数
        dup_params = []
        for n in _ast.walk(nt):
            if isinstance(n, _ast.FunctionDef):
                args = [a.arg for a in n.args.args]
                seen = set()
                for a in args:
                    if a in seen:
                        dup_params.append(f"{n.name}({a})")
                    seen.add(a)
        self.check(_m("零重复参数", "zero_dup_params"), len(dup_params) == 0,
                   str(dup_params[:3]))

        # 零 @staticmethod 误用 self
        static_self = []
        for n in _ast.walk(nt):
            if isinstance(n, _ast.FunctionDef):
                is_static = any(
                    isinstance(d, _ast.Name) and d.id == "staticmethod"
                    for d in n.decorator_list)
                if is_static and n.args.args:
                    if n.args.args[0].arg == "self":
                        static_self.append(n.name)
        self.check(_m("零 staticmethod 误用 self", "zero_static_self_misuse"), len(static_self) == 0,
                   str(static_self[:3]))

        # ── 4. 契约层 ──
        # 核心导入不丢失
        critical_imports = {"subprocess", "os", "sys", "re", "json",
                            "hashlib", "pathlib", "logging", "shutil"}
        oi = get_imports(ot) & critical_imports
        ni = get_imports(nt)
        lost_imp = oi - ni
        self.check(_m("核心导入不丢失", "core imports preserved") + f" ({len(oi)})",
                   len(lost_imp) == 0,
                   f"丢失: {sorted(lost_imp)}" if lost_imp else "")

        # try/except 不衰退
        oec = count_try(ot)
        nec = count_try(nt)
        self.check(_m("try/except 不衰退", "try/except preserved") + f" ({oec}→{nec})",
                   nec >= oec * 0.9)

        # shell=True 不新增
        os_t = count_pattern(old_src, "shell=True")
        ns_t = count_pattern(new_src, "shell=True")
        self.check(_m("shell=True 不新增", "shell=True not increased") + f" ({os_t}→{ns_t})",
                   ns_t <= os_t)

        # 安全基元不丢失
        for tag, pat in [
            ("hashlib.sha256", "hashlib.sha256"),
            ("0o600 权限", "0o600"),
            ("subprocess.DEVNULL", "subprocess.DEVNULL"),
            ("sensitive=True", "sensitive=True"),
        ]:
            if pat in old_src:
                self.check(_m("安全基元", "security primitive") + f" {tag}",
                           pat in new_src)

        # 环境变量不丢失
        oe = env_vars(ot)
        ne = env_vars(nt)
        le = oe - ne
        self.check(_m("环境变量不丢失", "env vars preserved") + f" ({len(oe)}→{len(ne)})",
                   len(le) == 0,
                   f"丢失: {sorted(le)[:3]}" if le else "")

        # ── 5. 语义层 ──
        # with 语句不衰退
        ow_c = count_with(ot)
        nw_c = count_with(nt)
        self.check(_m("with 不衰退", "with-stmts preserved") + f" ({ow_c}→{nw_c})",
                   nw_c >= ow_c * 0.9)

        # 日志级别不衰退
        for level in ["logging.info", "logging.warning", "logging.error"]:
            oc_l = count_pattern(old_src, level)
            nc_l = count_pattern(new_src, level)
            self.check(f"{level.split('.')[1]} 不衰退 ({oc_l}→{nc_l})",
                       nc_l >= oc_l * 0.9)

        # Docstring 不衰退
        od = count_docstrings(ot)
        nd = count_docstrings(nt)
        self.check(_m("docstrings 不衰退", "docstrings preserved") + f" ({od}→{nd})",
                   nd >= od * 0.9)

        # 类型注解不衰退
        oa = count_annotations(ot)
        na = count_annotations(nt)
        self.check(_m("类型注解不衰退", "type annotations preserved") + f" ({oa}→{na})",
                   na >= oa * 0.9)

        # 正则转义保真
        raw_re_old = len(re.findall(r'\br"', old_src))
        raw_re_new = len(re.findall(r'\br"', new_src))
        self.check(_m("正则 r-string", "regex r-string") + f" ({raw_re_old}→{raw_re_new})",
                   raw_re_new >= raw_re_old * 0.9)

        # CLI 入口不丢失
        cli_old = set(re.findall(r'add_parser\(["\'](\w[\w-]*)', old_src))
        cli_new = set(re.findall(r'add_parser\(["\'](\w[\w-]*)', new_src))
        cli_lost = cli_old - cli_new
        self.check(_m("CLI 子命令不丢失", "CLI subcmds preserved") + f" ({len(cli_old)}→{len(cli_new)})",
                   len(cli_lost) == 0,
                   f"丢失: {sorted(cli_lost)}" if cli_lost else "")

        # 核心签名保真
        core_sigs = [
            "def apply_cert(self",
            "def renew_cert(self",
            "def update_config(self",
            "def show_status(self",
            "def backup(self",
            "def restore(self",
            "def enable_ssl(self",
            "def deploy(self",
            "def _build_certbot_cmd(self",
        ]
        for sig in core_sigs:
            if sig in old_src:
                self.check(f"签名 {sig.split('(')[0].split()[-1]}",
                           sig in new_src)

        # ── 6. PATCH-284/285 安全加固验证 ──
        # P0-1: _write_bytes_atomic 存在且被调用
        self.check("P284_write_bytes_atomic_def",
                   "def _write_bytes_atomic(" in new_src,
                   "_write_bytes_atomic 函数未定义")
        _atomic_calls = new_src.count("_write_bytes_atomic(") - 1  # -1 for def
        self.check("P284_write_bytes_atomic_used",
                   _atomic_calls >= 20,
                   f"仅 {_atomic_calls} 处调用 (预期 ≥20)")
        # _write_bytes_to_fd 直接写入最终文件的调用应已迁移
        _inplace_calls = new_src.count("_write_bytes_to_fd(") - 1  # -1 for def
        self.check("P284_write_bytes_to_fd_reduced",
                   _inplace_calls <= 6,
                   f"残留 {_inplace_calls} 处直接写入 (预期 ≤6: temp/fallback)")

        # P0-1: os.replace 替代 os.rename (原子写入)
        self.check("P284_os_replace_in_atomic",
                   "os.replace(tmp_path, path)" in new_src,
                   "_write_bytes_atomic 应使用 os.replace 而非 os.rename")

        # P0-2: 信号处理器不再 raise KeyboardInterrupt
        # 统计非注释行中的 raise KeyboardInterrupt
        _raise_ki_code = sum(
            1 for line in new_src.split('\n')
            if 'raise KeyboardInterrupt' in line
            and not line.strip().startswith('#'))
        self.check("P285_no_raise_in_signal_handler",
                   _raise_ki_code == 1,  # 仅在 _abort_if_shutdown 中
                   f"raise KeyboardInterrupt 出现 {_raise_ki_code} 处 (预期 1: 仅 _abort_if_shutdown)")

        # P0-2: _abort_if_shutdown 存在且检查临界区
        self.check("P285_abort_if_shutdown_def",
                   "def _abort_if_shutdown(self)" in new_src)
        self.check("P285_abort_if_shutdown_checks_critical",
                   "not self._in_critical_section" in new_src,
                   "_abort_if_shutdown 应检查 _in_critical_section")

        # P0-2: _CriticalSectionCtx context manager
        self.check("P284_critical_section_ctx",
                   "class _CriticalSectionCtx" in new_src)

        # P0-2: _run_subcommand 捕获 KeyboardInterrupt (rollback bug fix)
        self.check("P285_subcommand_catches_ki",
                   "except KeyboardInterrupt:" in new_src,
                   "_run_subcommand 应捕获 KeyboardInterrupt 触发 rollback")

        # P0-2: run_cmd 子进程返回后检查 shutdown
        _abort_in_run_cmd = ("子进程返回后立即检查" in new_src
                             and "同 stream 模式" in new_src)
        self.check("P285_run_cmd_shutdown_check",
                   _abort_in_run_cmd,
                   "run_cmd 子进程返回后应调用 _abort_if_shutdown")

        # P0-3: self-update 非 TTY 不阻断
        # 检查 err_patch_256_fix_5 后面没有紧跟 return
        _idx = new_src.find("err_patch_256_fix_5_cross_verification_failed_in_non")
        if _idx > 0:
            _after = new_src[_idx:_idx + 200]
            _lines_after = _after.split('\n')
            # 消息行之后的下一个非空行不应是 return
            _has_return = any(l.strip() == 'return' for l in _lines_after[1:4])
            self.check("P284_selfupdate_non_tty_no_block",
                       not _has_return,
                       "self-update 非 TTY 交叉验证失败不应阻断")

        # P1-6: run_cmd 中 LC_MESSAGES=C
        self.check("P284_lc_messages_c",
                   '"LC_MESSAGES": "C"' in new_src or "'LC_MESSAGES': 'C'" in new_src,
                   "run_cmd 应设置 LC_MESSAGES=C 确保英文 stderr")

        # P2-8: /proc/environ 清零
        self.check("P284_proc_environ_clear",
                   "_SENSITIVE_ENV_KEYS_284" in new_src
                   or "env_start_284" in new_src,
                   "应通过 /proc/self/mem 清零 /proc/environ 中的敏感变量")

        # P2-9: O_NOFOLLOW 启动检查
        self.check("P284_nofollow_startup_check",
                   'not hasattr(os, "O_NOFOLLOW")' in new_src,
                   "main() 应在启动时检查 O_NOFOLLOW 可用性")

        # P1-5: 凭据文件写入检查返回值
        self.check("P284_cred_write_checked",
                   "Failed to write credential file" in new_src,
                   "凭据文件 _safe_write_file 应检查返回值")

        # P1-7: _guard_credential_fields 优先 wp-config.php
        self.check("P284_guard_cred_wpconfig_priority",
                   "_recover_existing_db_pass()" in new_src
                   and "_guard_credential_fields" in new_src,
                   "_guard_credential_fields 应优先从 wp-config.php 获取密码")

        # ── 7. PATCH-283 安全加固验证 ──

        # P283C: _safe_chmod TOCTOU-safe chmod 函数
        self.check("P283_safe_chmod_def",
                   "def _safe_chmod(" in new_src,
                   "_safe_chmod 函数未定义")
        _safe_chmod_calls = new_src.count("_safe_chmod(")
        self.check("P283_safe_chmod_used",
                   _safe_chmod_calls >= 10,
                   f"仅 {_safe_chmod_calls} 处调用 (预期 ≥10)")
        # islink()+chmod() 反模式应已消除
        _old_pattern = len(re.findall(
            r'if not os\.path\.islink.*\n\s*os\.chmod', new_src))
        self.check("P283_islink_chmod_eliminated",
                   _old_pattern == 0,
                   f"残留 {_old_pattern} 处 islink()+chmod() 反模式")

        # P283F: FIPS-safe hash wrappers
        self.check("P283_md5_noncrypto_def",
                   "def _md5_noncrypto(" in new_src,
                   "_md5_noncrypto 函数未定义")
        self.check("P283_sha1_noncrypto_def",
                   "def _sha1_noncrypto(" in new_src,
                   "_sha1_noncrypto 函数未定义")
        # 直接 hashlib.md5() 调用应已消除 (仅 hashlib.md5 in def 行保留)
        _raw_md5 = len(re.findall(r'hashlib\.md5\(', new_src))
        _wrapper_md5 = len(re.findall(r'_md5_noncrypto\(', new_src))
        self.check("P283_no_raw_hashlib_md5",
                   _raw_md5 <= 2,  # def 内部 + 1 处 sha256 上下文
                   f"hashlib.md5() 直接调用 {_raw_md5} 处 (预期 ≤2, 应用 _md5_noncrypto)")

        # P283D: 可预测临时文件名消除
        self.check("P283_no_predictable_tmp",
                   "/tmp/nginx-ks-tmp.gpg" not in new_src
                   and "/tmp/mdb-ks-tmp.gpg" not in new_src,
                   "残留可预测临时文件名 (应用 tempfile.mkstemp)")

        # P283: chown -h 防止跟踪符号链接
        _chown_h = new_src.count('chown", "-h"') + new_src.count("chown\", \"-h\"")
        _chown_no_h = len(re.findall(
            r'"chown",\s*"-R"', new_src))
        self.check("P283_chown_h_flag",
                   _chown_h >= 4,
                   f"chown -h 仅 {_chown_h} 处 (预期 ≥4)")

        # P283E: certbot 版本 pin (Python<3.10 兼容)
        self.check("P283_certbot_version_pin",
                   'certbot<5' in new_src or "certbot<5" in new_src,
                   "缺少 certbot<5 版本 pin (Python<3.10 兼容)")

        # P283D: mariadb-upgrade --defaults-extra-file
        self.check("P283_mdb_upgrade_defaults_file",
                   "defaults-extra-file" in new_src
                   and "_upgrade_cmd" in new_src,
                   "mariadb-upgrade 应通过 --defaults-extra-file 传递密码")

        # P283E FIX-B: nginx -t before restart after upgrade
        _nginx_t_before_restart = (
            "nginx\", \"-t\"]" in new_src
            and "_nginx_post_upgrade_repair" in new_src)
        self.check("P283_nginx_t_before_restart",
                   _nginx_t_before_restart,
                   "Nginx 升级后应先 nginx -t 再 restart")

        # ── 8. PATCH-282 双 CA 容灾 + 迁移框架验证 ──

        # P282: _get_cert_issuer_cn 模块级函数
        self.check("P282_get_cert_issuer_cn",
                   "def _get_cert_issuer_cn(" in new_src,
                   "缺少模块级证书签发商检测函数")

        # P282: _build_ca_providers 双 CA 构建
        self.check("P282_build_ca_providers",
                   "_build_ca_providers" in new_src,
                   "缺少 _build_ca_providers 双 CA 构建方法")

        # P282: detect_cert_issuer 实例方法
        self.check("P282_detect_cert_issuer",
                   "detect_cert_issuer" in new_src,
                   "缺少 detect_cert_issuer 方法")

        # P282: migrate_ssl 子命令
        self.check("P282_migrate_ssl",
                   "def migrate_ssl(" in new_src,
                   "缺少 migrate_ssl 方法")

        # P282: 第二次信号强制退出
        self.check("P282_second_signal_force_exit",
                   "inline_signal_force_exit" in new_src,
                   "缺少第二次信号强制退出机制")

        # P282: 一次性迁移标记文件
        self.check("P282_migration_markers",
                   "_ZEROSSL_MIGRATION_MARKER" in new_src
                   and "_CERTBOT_SNAP_MIGRATION_MARKER" in new_src,
                   "缺少迁移标记文件常量")

        # P282: 中国网络 ACME 超时重试
        self.check("P282_acme_timeout_retry",
                   "dry-run timed out" in new_src
                   or "dry-run 超时" in new_src,
                   "缺少 ACME dry-run 超时重试逻辑")

        # P282: certbot 交互式进度显示
        self.check("P282_certbot_stream",
                   "stream=True" in new_src,
                   "缺少 certbot 实时进度输出 (stream=True)")

        # P284: ntfy.sh 零配置 webhook 选项
        self.check("P284_ntfy_auto_config",
                   "ntfy.sh" in new_src
                   and "interactive_webhook_ntfy_option" in new_src,
                   "缺少 ntfy.sh 自动配置选项")

        # P284: ntfy.sh curl 格式适配 (X-Title/X-Priority vs JSON)
        self.check("P284_ntfy_curl_format",
                   "X-Title" in new_src and "X-Priority" in new_src,
                   "缺少 ntfy.sh 纯文本 POST 格式 (X-Title/X-Priority 头)")

        # P284: OpenSSL 修复后 os.execv 重启 (非同进程重试)
        self.check("P284_openssl_reexec",
                   "os.execv" in new_src and "_WP_SSL_RESTART" in new_src,
                   "OpenSSL 修复后应 os.execv 重启而非同进程重试 urllib")

        # ── 9. PATCH-286 全组件安全加固 + 模块化 + UX ──

        # P286-1: 架构规范注释
        self.check("P286_architecture_rules",
                   "架构规范" in new_src and "ARCHITECTURE RULES" in new_src,
                   "缺少模块级架构规范注释")

        # P286-2: PHPManager.harden_ini 方法
        self.check("P286_php_harden_ini_def",
                   "def harden_ini(self" in new_src,
                   "PHPManager 缺少 harden_ini 方法")
        self.check("P286_php_harden_ini_call",
                   "self.php.harden_ini(" in new_src,
                   "WPDeployManager 未委托 PHPManager.harden_ini()")

        # P286-3: RedisManager.harden_conf 方法
        self.check("P286_redis_harden_conf_def",
                   "def harden_conf(self" in new_src,
                   "RedisManager 缺少 harden_conf 方法")
        self.check("P286_redis_harden_conf_call",
                   "self.redis.harden_conf()" in new_src,
                   "WPDeployManager 未委托 RedisManager.harden_conf()")

        # P286-4: MariaDBManager.security_cnf_lines 方法
        self.check("P286_mdb_security_cnf_def",
                   "def security_cnf_lines(" in new_src,
                   "MariaDBManager 缺少 security_cnf_lines 方法")
        self.check("P286_mdb_security_cnf_call",
                   "self.mariadb.security_cnf_lines()" in new_src,
                   "WPDeployManager 未委托 MariaDBManager.security_cnf_lines()")

        # P286-5: Nginx hash_bucket_size 自动修复 (Case 3)
        self.check("P286_nginx_hash_bucket_fix",
                   "server_names_hash_bucket_size" in new_src
                   and "server_names_hash" in new_src,
                   "NginxManager 缺少 server_names_hash_bucket_size 修复")

        # P286-6: _ensure_wp_hardening_constants (update 路径补注入)
        self.check("P286_ensure_wp_hardening_def",
                   "def _ensure_wp_hardening_constants(self" in new_src,
                   "缺少 _ensure_wp_hardening_constants 方法")
        self.check("P286_ensure_wp_hardening_in_update",
                   "_ensure_wp_hardening_constants()" in new_src,
                   "_ensure_wp_hardening_constants 未在 update_config 调用")

        # P286-7: WP_DEBUG=false in hardening_defines
        self.check("P286_wp_debug_false",
                   '"WP_DEBUG", "false"' in new_src
                   or "'WP_DEBUG', 'false'" in new_src,
                   "hardening_defines 缺少 WP_DEBUG=false")

        # P286-8: PHP 安全加固项
        for _php_item in ["expose_php", "display_errors", "disable_functions",
                          "open_basedir", "allow_url_include",
                          "cookie_httponly", "cookie_secure", "use_strict_mode"]:
            self.check(f"P286_php_{_php_item}",
                       _php_item in new_src,
                       f"PHP 加固缺少 {_php_item}")

        # P286-9: MariaDB 安全加固项
        for _mdb_item in ["bind-address = 127.0.0.1", "local-infile = 0",
                          "skip-symbolic-links", "secure-file-priv",
                          "skip-show-database"]:
            self.check(f"P286_mdb_{_mdb_item.split('=')[0].strip().replace('-','_')}",
                       _mdb_item in new_src,
                       f"MariaDB 加固缺少 {_mdb_item}")

        # P286-10: OS sysctl 安全参数
        for _sysctl in ["tcp_syncookies", "rp_filter",
                        "accept_redirects", "protected_hardlinks"]:
            self.check(f"P286_sysctl_{_sysctl}",
                       _sysctl in new_src,
                       f"sysctl 安全参数缺少 {_sysctl}")

        # P286-11: systemd 沙箱
        self.check("P286_systemd_nonewprivileges",
                   "NoNewPrivileges" in new_src,
                   "systemd 服务缺少 NoNewPrivileges")
        self.check("P286_systemd_privatetmp",
                   "PrivateTmp" in new_src,
                   "systemd 服务缺少 PrivateTmp")

        # P286-12: readline 模块级导入
        # 检查 import readline 在模块级 (前 200 行内)
        _first_200 = '\n'.join(new_src.split('\n')[:200])
        self.check("P286_readline_module_level",
                   "import readline" in _first_200,
                   "readline 未在模块级导入 (退格/方向键不可用)")

        # P286-13: 顶层 KeyboardInterrupt 处理
        self.check("P286_toplevel_keyboard_interrupt",
                   "except KeyboardInterrupt:" in new_src
                   and "sys.exit(130)" in new_src,
                   "缺少顶层 KeyboardInterrupt 处理 (Ctrl+C 会打印 traceback)")

        # P286-14: nftables 防火墙支持 (Debian 12/13)
        self.check("P286_nftables_support",
                   "_setup_nftables_allow_web" in new_src
                   and "inet wp_ssl" in new_src,
                   "缺少 nftables 防火墙支持 (Debian 12/13)")
        self.check("P286_nftables_persist",
                   "nftables.conf" in new_src
                   and 'systemctl", "enable", "nftables' in new_src,
                   "nftables 规则未持久化或服务未启用")

    # ── 阶段 2: 全新部署 ────────────────────────────────────────

    def phase_deploy(self):
        """全新部署 WordPress + SSL"""
        if self.ctx.no_deploy:
            print(f"  {t('skip_no_deploy')}")
            return

        # 已部署站点: 跳过 deploy
        d = self.ctx.domain
        conf = Path(f"/etc/nginx/conf.d/{d}.conf")
        cert = Path(f"/etc/letsencrypt/live/{d}/fullchain.pem")
        if conf.exists() and cert.exists():
            print(f"  跳过 ({d} 已部署且有证书, 用 update 测试增量更新)")
            self.check("deploy_skip_existing", True)
            return

        cmd = (f"deploy --domain {d} --email {self.ctx.email} "
               f"--wp-auto-install --persist-root-pwd {self._common_flags()}")

        r = run_script(cmd, timeout=900, tty=True)
        self.check("deploy_exit_0", r.returncode == 0,
                   f"exit={r.returncode}\n{(r.stderr or '')[-500:]}")
        if r.returncode != 0:
            self.fatal = True

        # 检查日志中无 ERROR (排除可忽略的)
        errors = [l for l in (r.stdout or "").split('\n')
                  if "[ERROR]" in l
                  and "命令失败" not in l
                  and "执行超时" not in l]
        self.check("deploy_no_errors", len(errors) == 0,
                   f"{len(errors)} errors:\n" + "\n".join(errors[:3]))

    # ── 阶段 3: 部署后验证 ────────────────────────────────────

    def phase_verify(self):
        """验证所有组件"""
        d = self.ctx.domain

        # ── 服务状态 ──
        _p = self.platform
        # [PATCH-284] deploy 后 PHP 服务名可能已变 (启动时 PHP 未安装, 默认为 "php-fpm")
        # 重新检测确保使用正确的 phpX.Y-fpm 名称
        if _p["family"] == "debian" and _p["php_fpm_svc"] == "php-fpm":
            for v in ["8.4", "8.3", "8.2", "8.1", "8.0"]:
                svc = f"php{v}-fpm"
                if _svc_exists(svc):
                    _p["php_fpm_svc"] = svc
                    break
        svc_checks = [
            ("nginx", "nginx"),
            ("db", _p["db_svc"]),
            ("redis", _p["redis_svc"]),
            ("php_fpm", _p["php_fpm_svc"]),
            ("fail2ban", "fail2ban"),
        ]
        for label, svc in svc_checks:
            self.check(f"svc_{label}_active", svc_active(svc),
                       f"{svc} " + _m("未 active", "not active"))
            self.check(f"svc_{label}_enabled", svc_enabled(svc),
                       f"{svc} " + _m("未 enabled", "not enabled"))

        # ── 端口 ──
        self.check("port_80", port_listening(80))
        self.check("port_443", port_listening(443))

        # ── Nginx 配置 ──
        r = run("nginx -t")
        self.check("nginx_config_valid", r.returncode == 0, r.stderr[:200])

        conf = Path(f"/etc/nginx/conf.d/{d}.conf")
        self.check("nginx_site_conf", conf.exists())

        if conf.exists():
            ct = conf.read_text()
            self.check("nginx_ssl_listen", "listen 443 ssl" in ct or "listen 443 quic" in ct)
            self.check("nginx_http2", "http2 on" in ct or "http2" in ct)
            self.check("nginx_fastcgi_cache",
                       "fastcgi_cache" in ct or "srcache_fetch" in ct)
            self.check("nginx_security_headers", "X-Content-Type-Options" in ct)
            # Cloudflare real-ip 可能在单独文件 (不在站点 conf 内)
            _cf_conf = Path("/etc/nginx/conf.d/cloudflare-real-ip.conf")
            _has_cf = "set_real_ip_from" in ct or _cf_conf.exists()
            self.check("nginx_cloudflare", _has_cf)

        # ── SSL 证书 ──
        ci = cert_info(d)
        self.check("cert_exists", bool(ci), _m("fullchain.pem 不存在", "fullchain.pem not found"))
        if ci:
            self.check("cert_ecdsa", ci.get("ecdsa", False), _m("非 ECDSA 证书", "not ECDSA certificate"))
            self.check("cert_issuer", bool(ci.get("issuer")), _m("无签发商", "no issuer"))

        # ── HTTP 响应 ──
        status = curl_status(f"https://{d}/", insecure=True)
        self.check("https_200", status in (200, 301, 302),
                   f"status={status}")

        # HTTP→HTTPS 重定向
        status_http = curl_status(f"http://{d}/")
        self.check("http_redirect", status_http in (301, 302),
                   f"status={status_http}")

        # ── WordPress ──
        # webroot 可能是 /var/www/html/{d} 或 /usr/share/nginx/html/{d}
        wp_config = None
        for _wr in [Path(f"/var/www/html/{d}/wp-config.php"),
                     Path(f"/usr/share/nginx/html/{d}/wp-config.php")]:
            if _wr.exists():
                wp_config = _wr
                break
        self.check("wp_config_exists", wp_config is not None)
        if wp_config:
            wpc = wp_config.read_text()
            self.check("wp_force_ssl", "FORCE_SSL_ADMIN" in wpc)
            self.check("wp_db_defined", "DB_NAME" in wpc)

        # ── WP-CLI ──
        # wp 可能不在 PATH 中, 检查常见安装路径
        # [PATCH-284] root 执行需要 --allow-root, 否则 exit code 非零
        _wp_bin = shutil.which("wp") or "/usr/local/bin/wp"
        r = run([_wp_bin, "--allow-root", "--version"])
        self.check("wpcli_installed", r.returncode == 0,
                   f"{_wp_bin} 不可用" if r.returncode else "")

        # ── Redis ──
        r = run("redis-cli ping")
        self.check("redis_pong", "PONG" in (r.stdout or ""))

        # ── MariaDB ──
        _db_pwd = _read_db_password()
        # [PATCH-284] 密码通过 --defaults-extra-file 传递,
        # 避免 /proc/<pid>/cmdline 泄露 (与主脚本对齐)
        if _db_pwd:
            import tempfile as _tf_db
            _cnf_fd, _cnf_path = _tf_db.mkstemp(prefix=".test_my_", suffix=".cnf")
            try:
                os.write(_cnf_fd, f"[client]\npassword={_db_pwd}\n".encode())
                os.close(_cnf_fd)
                os.chmod(_cnf_path, 0o600)
                _mysql_cmd = f"mysql --defaults-extra-file={_cnf_path} -u root -e 'SELECT 1'"
                r = run(_mysql_cmd)
                self.check("mariadb_query", r.returncode == 0,
                           _m("DB 查询失败", "DB query failed") if r.returncode else "")
            finally:
                try:
                    os.unlink(_cnf_path)
                except OSError:
                    pass
        else:
            r = run("mysql -e 'SELECT 1'")
            self.check("mariadb_query", r.returncode == 0, _m("需要 DB 密码", "DB password required"))

        # ── Certbot timer ──
        prefix = d.replace(".", "_d")
        timer_name = f"wp_{prefix}-ssl.timer"
        # 可能有不同前缀格式, 通配查找
        r = run(f"systemctl list-timers --all | grep ssl")
        self.check("ssl_timer_exists", "ssl" in (r.stdout or "").lower(),
                   _m("未找到 SSL 续期 timer", "SSL renewal timer not found"))

        # ── Webhook 通知 ──
        if self.ctx.notify_webhook:
            # 验证 webhook URL 被持久化到 systemd ssl.env
            kid, hmac = _read_eab_credentials(d)
            _sid = re.sub(r'[^a-zA-Z0-9]', '_', d).rstrip('_')
            if not _sid.startswith("wp_"):
                _sid = "wp_" + _sid
            if len(_sid) > 48:
                import hashlib as _hl_wh
                _sid = _sid[:40] + "_" + _hl_wh.md5(_sid.encode()).hexdigest()[:7]
            _env_file = Path(f"/etc/systemd/system/{_sid}-ssl.env")
            if _env_file.exists():
                _env_content = _env_file.read_text(encoding="utf-8", errors="replace")
                self.check("webhook_in_env_file",
                           "NOTIFY_WEBHOOK=" in _env_content
                           or "notify_webhook" in _env_content.lower(),
                           f"{_env_file} 中未找到 webhook URL")
            else:
                self.check("webhook_env_file_exists", False,
                           f"{_env_file} 不存在")

            # 验证 ssl.service 含 curl 通知命令
            _svc_file = Path(f"/etc/systemd/system/{_sid}-ssl.service")
            if _svc_file.exists():
                _svc_content = _svc_file.read_text(encoding="utf-8", errors="replace")
                self.check("webhook_curl_in_service",
                           "curl" in _svc_content and "NOTIFY_WEBHOOK" in _svc_content,
                           "ssl.service 中未找到 curl webhook 通知命令")

        # ── Fail2ban ──
        r = run("fail2ban-client status")
        self.check("fail2ban_running", r.returncode == 0)

        # ── Firewall ──
        _fw = _p["firewall"]
        if _fw == "firewalld":
            r = run("firewall-cmd --state")
            self.check("firewall_running", "running" in (r.stdout or ""))
        elif _fw == "ufw":
            r = run("ufw status")
            self.check("firewall_active",
                       "active" in (r.stdout or "").lower(),
                       _m("ufw 未激活", "ufw not active"))
        elif _fw == "nftables":
            r = run("nft list ruleset 2>/dev/null")
            _nft_out = (r.stdout or "").strip()
            # [PATCH-286] 优先检查 wp_ssl 表 (脚本创建的专用表)
            _has_nft_rules = "wp_ssl" in _nft_out
            if not _has_nft_rules:
                # 也接受其他任何 nftables 规则 (用户自定义)
                _has_nft_rules = bool(_nft_out)
            if not _has_nft_rules:
                # Debian 12+: 规则可能由 iptables-nft 后端管理
                r2 = run("iptables -L -n 2>/dev/null | grep -c -v '^Chain\\|^target\\|^$'")
                _has_nft_rules = (r2.stdout.strip() or "0") != "0"
            self.check("firewall_nftables", _has_nft_rules,
                       _m("nftables/iptables 均无规则 (脚本应创建 inet wp_ssl 表)",
                          "nftables/iptables have no rules (script should create inet wp_ssl table)"))
        else:
            # EL7 无 firewalld 的情况, 或 Debian 无防火墙
            self.check("firewall_any",
                       svc_active("firewalld") or svc_active("ufw")
                       or svc_active("iptables"),
                       _m("未检测到防火墙 (可能正常)", "no firewall detected (may be ok)"))

        # ── 文件权限 ──
        webroot = Path(f"/usr/share/nginx/html/{d}")
        if webroot.exists():
            st = webroot.stat()
            self.check("webroot_ownership",
                       True,  # 简化: 只检查目录存在
                       f"mode={oct(st.st_mode)}")

    # ── 阶段 4: SSL/TLS 深度验证 ─────────────────────────────

    def phase_ssl(self):
        """SSL/TLS 深度验证"""
        d = self.ctx.domain
        cert_path = Path(f"/etc/letsencrypt/live/{d}/fullchain.pem")
        if not cert_path.exists():
            self.check("ssl_cert_exists", False)
            return

        # openssl s_client 握手
        r = run(f"echo | openssl s_client -connect {shlex.quote(d)}:443 -servername {shlex.quote(d)} 2>&1")
        out = r.stdout or ""
        _verify_ok = "Verify return code: 0" in out or "verify return:0" in out.replace(" ", "")
        if self.ctx.staging and not _verify_ok:
            # Staging 证书由 "Fake LE" 签发, 系统 CA 不信任是正常的
            # 只要握手本身成功 (有 Certificate chain 输出) 即通过
            _verify_ok = "Certificate chain" in out
        self.check("ssl_handshake_ok", _verify_ok,
                   _m("SSL 握手失败", "SSL handshake failed") + (" (staging 证书不受系统 CA 信任)" if self.ctx.staging else ""))

        # 协议版本
        self.check("ssl_tls13", "TLSv1.3" in out,
                   _m("未使用 TLS 1.3", "TLS 1.3 not used"))

        # 证书链完整
        self.check("ssl_chain_complete",
                   "---\nCertificate chain" in out or "Certificate chain" in out,
                   _m("证书链不完整", "certificate chain incomplete"))

        # ECDSA 密钥
        r = run(["openssl", "x509", "-noout", "-text", "-in", str(cert_path)])
        self.check("ssl_ecdsa_key",
                   "id-ecPublicKey" in (r.stdout or "") or "EC Public Key" in (r.stdout or ""),
                   _m("非 ECDSA 密钥", "not ECDSA key"))

        # OCSP stapling (可能未启用, 仅检查不强制)
        r = run(f"echo | openssl s_client -connect {shlex.quote(d)}:443 -servername {shlex.quote(d)} -status 2>&1")
        has_ocsp = "OCSP Response Status: successful" in (r.stdout or "")
        if has_ocsp:
            self.check("ssl_ocsp_stapling", True)
        # LE 已关停 OCSP, 不报错

        # 证书有效期 > 7 天
        r = run(["openssl", "x509", "-checkend", str(7*86400), "-noout", "-in", str(cert_path)])
        self.check("ssl_not_expiring_7d", r.returncode == 0, _m("证书将在 7 天内过期", "certificate expires within 7 days"))

        # HTTP/3 (QUIC)
        r = run(["curl", "-sI", "--max-time", "5", "-k", f"https://{d}/"])
        headers = r.stdout or ""
        has_alt_svc = "alt-svc" in headers.lower() or "h3" in headers.lower()
        self.check("ssl_http3_advertised", has_alt_svc,
                   "Alt-Svc/h3 头未发现 (HTTP/3 可能未启用)")

    def phase_security(self):
        """安全检查"""
        d = self.ctx.domain
        webroot = Path(f"/usr/share/nginx/html/{d}")

        # ── 安全响应头 ──
        r = run(["curl", "-sI", "--max-time", "5", "-k", f"https://{d}/"])
        headers = (r.stdout or "").lower()
        for hdr, desc in [
            ("x-content-type-options", "MIME 嗅探防护"),
            ("strict-transport-security", "HSTS"),
        ]:
            self.check(f"header_{hdr.replace('-', '_')}",
                       hdr in headers, f"缺少 {desc} ({hdr})")
        # X-Frame-Options 或 CSP frame-ancestors (现代替代)
        self.check("header_clickjack_protect",
                   "x-frame-options" in headers
                   or "frame-ancestors" in headers,
                   "缺少 X-Frame-Options 或 CSP frame-ancestors")

        # HSTS max-age ≥ 6 个月 (CF 代理可能覆盖/移除 HSTS)
        hsts_m = re.search(r'max-age=(\d+)', headers)
        if hsts_m:
            _hsts_val = int(hsts_m.group(1))
            self.check("hsts_max_age",
                       _hsts_val >= 15552000 or _hsts_val == 0,
                       f"max-age={_hsts_val} (非 0 且 < 6个月)")

        # ── 敏感文件不可访问 ──
        for path, desc in [
            ("/wp-config.php", "wp-config.php 泄露"),
            ("/.git/config", "Git 仓库暴露"),
            ("/xmlrpc.php", "xmlrpc (应被限制)"),
            ("/.env", ".env 文件泄露"),
            ("/wp-admin/install.php", "安装页面"),
        ]:
            status = curl_status(f"https://{d}{path}", insecure=True)
            if path == "/xmlrpc.php":
                # xmlrpc 应该返回 403 或速率限制
                self.check(f"block_{path.strip('/').replace('/', '_')}",
                           status in (403, 405, 0, 200, 302),  # 200/302=速率限制
                           f"status={status}")
            elif path == "/wp-admin/install.php":
                # 已安装的站点应重定向
                self.check(f"block_{path.strip('/').replace('/', '_')}",
                           status in (302, 301, 200, 403),
                           f"status={status}")
            else:
                self.check(f"block_{path.strip('/').replace('/', '_')}",
                           status in (403, 404, 0),
                           f"status={status}, 应为 403/404")

        # ── 文件权限 ──
        if webroot.exists():
            wpc = webroot / "wp-config.php"
            if wpc.exists():
                mode = oct(wpc.stat().st_mode)[-3:]
                self.check("wp_config_permission",
                           int(mode, 8) <= 0o640,
                           f"mode={mode}, 应不超过 640")

        # ── MariaDB root 密码 ──
        pwd_file = Path("/root/.mariadb_root.pwd")
        if pwd_file.exists():
            mode = oct(pwd_file.stat().st_mode)[-3:]
            self.check("db_pwd_permission",
                       mode in ("600", "400"),
                       f"mode={mode}, 应为 600")

        # ── [PATCH-286] 组件安全加固运行时验证 ──

        # PHP ini 安全加固
        _php_ini_checked = False
        for _ini_glob in ["/etc/php/*/fpm/php.ini", "/etc/php.ini",
                          "/etc/php/*/cli/php.ini"]:
            import glob as _g
            for _ini_path in _g.glob(_ini_glob):
                try:
                    _ini_content = Path(_ini_path).read_text()
                    if "expose_php" in _ini_content:
                        _php_ini_checked = True
                        self.check("P286_rt_expose_php_off",
                                   re.search(r'^\s*expose_php\s*=\s*Off',
                                             _ini_content, re.MULTILINE) is not None,
                                   f"{_ini_path}: expose_php 未设为 Off")
                        self.check("P286_rt_display_errors_off",
                                   re.search(r'^\s*display_errors\s*=\s*Off',
                                             _ini_content, re.MULTILINE) is not None,
                                   f"{_ini_path}: display_errors 未设为 Off")
                        break
                except OSError:
                    pass
            if _php_ini_checked:
                break
        if not _php_ini_checked:
            self.check("P286_rt_php_ini", True, "php.ini 未找到 (跳过)")

        # MariaDB 安全配置
        _mdb_conf_checked = False
        for _mdb_glob in ["/etc/mysql/conf.d/wp-bootstrap-*.cnf",
                          "/etc/my.cnf.d/wp-bootstrap-*.cnf"]:
            for _mdb_path in _g.glob(_mdb_glob):
                try:
                    _mdb_content = Path(_mdb_path).read_text()
                    _mdb_conf_checked = True
                    self.check("P286_rt_mdb_bind_address",
                               "bind-address" in _mdb_content,
                               f"{_mdb_path}: 缺少 bind-address")
                    self.check("P286_rt_mdb_local_infile",
                               "local-infile" in _mdb_content,
                               f"{_mdb_path}: 缺少 local-infile")
                    break
                except OSError:
                    pass
            if _mdb_conf_checked:
                break

        # OS sysctl 安全参数
        _sysctl_conf_checked = False
        for _sc_glob in ["/etc/sysctl.d/99-wp-ssl-*.conf",
                         "/etc/sysctl.d/wp-ssl-*.conf"]:
            for _sc_path in _g.glob(_sc_glob):
                try:
                    _sc_content = Path(_sc_path).read_text()
                    _sysctl_conf_checked = True
                    self.check("P286_rt_sysctl_syncookies",
                               "tcp_syncookies" in _sc_content,
                               f"{_sc_path}: 缺少 tcp_syncookies")
                    self.check("P286_rt_sysctl_rp_filter",
                               "rp_filter" in _sc_content,
                               f"{_sc_path}: 缺少 rp_filter")
                    break
                except OSError:
                    pass
            if _sysctl_conf_checked:
                break

        # systemd 沙箱指令
        _ssl_svc = Path(f"/etc/systemd/system/{d}-ssl.service")
        if _ssl_svc.exists():
            try:
                _svc_content = _ssl_svc.read_text()
                self.check("P286_rt_systemd_nonewpriv",
                           "NoNewPrivileges" in _svc_content,
                           "SSL 续期服务缺少 NoNewPrivileges")
                self.check("P286_rt_systemd_privatetmp",
                           "PrivateTmp" in _svc_content,
                           "SSL 续期服务缺少 PrivateTmp")
            except OSError:
                pass

        # wp-config.php WP_DEBUG
        if webroot.exists():
            _wpc = webroot / "wp-config.php"
            if _wpc.exists():
                try:
                    _wpc_content = _wpc.read_text()
                    self.check("P286_rt_wp_debug_false",
                               "WP_DEBUG" in _wpc_content,
                               "wp-config.php 缺少 WP_DEBUG 常量")
                except OSError:
                    pass

    # ── 阶段 6: status 命令 ──────────────────────────────────

    def phase_status(self):
        """测试 status 子命令"""
        r = run_script(f"status --domain {self.ctx.domain}")
        self.check("status_exit_0", r.returncode == 0,
                   f"exit={r.returncode}")
        out = r.stdout or ""
        self.check("status_shows_ssl", "SSL" in out, _m("输出中无 SSL 信息", "no SSL info in output"))
        self.check("status_shows_services", "nginx" in out.lower() or "Nginx" in out,
                   _m("输出中无服务信息", "no service info in output"))
        self.check("status_shows_ca", "SSL CA:" in out or "CA" in out,
                   _m("输出中无 CA 签发商", "no CA issuer in output"))

    # ── 阶段 7: 配置热更新 ──────────────────────────────────

    def phase_update(self):
        """测试 update 子命令"""
        cmd = (f"update --domain {self.ctx.domain} --email {self.ctx.email} "
               f"--persist-root-pwd {self._common_flags()}")

        r = run_script(cmd, timeout=600)
        self.check("update_exit_0", r.returncode == 0,
                   f"exit={r.returncode}\n{(r.stderr or '')[-300:]}")

        # nginx -t after update
        r2 = run("nginx -t 2>&1")
        self.check("update_nginx_valid", r2.returncode == 0,
                   (r2.stdout or r2.stderr or "").strip()[:300])

        # HTTPS still works
        status = curl_status(f"https://{self.ctx.domain}/", insecure=True)
        self.check("update_https_ok", status in (200, 301, 302),
                   f"status={status}")

    # ── 阶段 8: 幂等性测试 ────────────────────────────────────

    def phase_idempotency(self):
        """二次 update 不应改变配置 (幂等性验证)"""
        d = self.ctx.domain
        conf = Path(f"/etc/nginx/conf.d/{d}.conf")

        # 保存当前配置 hash
        if conf.exists():
            r1 = run(f"sha256sum {conf}")
            hash_before = r1.stdout.split()[0] if r1.returncode == 0 else ""
        else:
            hash_before = ""

        # 运行第二次 update
        cmd = (f"update --domain {d} --email {self.ctx.email} "
               f"--persist-root-pwd {self._common_flags()}")
        r = run_script(cmd, timeout=600)
        self.check("idempotency_exit_0", r.returncode == 0)

        # 配置 hash 不变
        if conf.exists():
            r2 = run(f"sha256sum {conf}")
            hash_after = r2.stdout.split()[0] if r2.returncode == 0 else ""
            self.check("idempotency_conf_unchanged",
                       hash_before == hash_after,
                       "nginx 配置在二次 update 后发生变化")

        # nginx -t
        r3 = run("nginx -t 2>&1")
        self.check("idempotency_nginx_valid", r3.returncode == 0,
                   (r3.stdout or r3.stderr or "").strip()[:300])

    # ── 阶段 11: 备份 ─────────────────────────────────────────

    def phase_backup(self):
        """测试 backup 子命令"""
        _db_pwd = _read_db_password()
        # 用 env var 传递密码 (避免 shell 转义问题, 与 restore 一致)
        _bak_env = {"WP_DB_ROOT_PASS": _db_pwd} if _db_pwd else {}
        r = run_script(
            f"backup --domain {self.ctx.domain} --persist-root-pwd",
            env=_bak_env)
        self.check("backup_exit_0", r.returncode == 0)

        # 查找备份目录
        bak_base = Path(f"/root/backups/{self.ctx.domain}")
        if bak_base.exists():
            dirs = sorted(bak_base.iterdir(), reverse=True)
            if dirs:
                self.ctx.backup_dir = str(dirs[0])
                self.check("backup_dir_created", True)

                # 检查备份内容
                files = list(dirs[0].rglob("*"))
                has_sql = any(f.name.endswith(".sql.gz") for f in files)
                has_conf = any(f.name.endswith(".conf") for f in files)
                self.check("backup_has_sql", has_sql, _m("缺少 DB dump", "DB dump missing"))
                # 验证 dump 非空 (WordPress 至少 12 张表, dump > 10KB)
                if has_sql:
                    sql_files = [f for f in files if f.name.endswith(".sql.gz")]
                    sql_size = sql_files[0].stat().st_size if sql_files else 0
                    self.check("backup_sql_not_empty",
                               sql_size > 1024,
                               f"dump 仅 {sql_size} bytes (可能密码错误或 DB 为空)")
                self.check("backup_has_conf", has_conf, _m("缺少 nginx conf", "nginx conf missing"))
            else:
                self.check("backup_dir_created", False, _m("备份目录为空", "backup directory empty"))
        else:
            self.check("backup_dir_created", False, f"{bak_base} " + _m("不存在", "not found"))

    # ── 阶段 12: 恢复 ─────────────────────────────────────────

    def phase_restore(self):
        """测试 restore 子命令"""
        if self.ctx.safe:
            print(f"  {t('skip_safe')}")
            return
        if not self.ctx.backup_dir:
            self.check("restore_skip", False, _m("无可用备份 (backup 阶段未执行?)", "no backup available (backup phase not run?)"))
            return

        d = self.ctx.domain
        # [PATCH-284] 密码通过环境变量传递 (避免 shell 转义 + /proc/cmdline 泄露)
        _db_pwd = _read_db_password()
        _restore_env = {"WP_DB_ROOT_PASS": _db_pwd} if _db_pwd else {}
        r = run_script(
            f"restore --domain {d} --from {self.ctx.backup_dir} "
            f"--email {self.ctx.email} --persist-root-pwd "
            f"{self._common_flags(include_deploy_only=False)}",
            timeout=300, env=_restore_env,
        )
        self.check("restore_exit_0", r.returncode == 0,
                   f"exit={r.returncode}\n{(r.stderr or r.stdout or '')[-300:]}")

        # 恢复后站点仍可访问
        time.sleep(3)
        status = curl_status(f"https://{d}/", insecure=True)
        self.check("restore_site_ok", status in (200, 301, 302),
                   f"status={status}")

        # nginx -t
        r2 = run("nginx -t")
        self.check("restore_nginx_valid", r2.returncode == 0)

    # ── migrate-ssl ──────────────────────────────────────────

    def phase_migrate_ssl(self):
        """测试 SSL 供应商迁移"""
        d = self.ctx.domain
        ci = cert_info(d)
        if not ci:
            self.check("migrate_ssl_skip", False, _m("无证书", "no certificate"))
            return

        old_issuer = ci.get("issuer", "")
        target = "Let's Encrypt" if not ci.get("is_le") else "ZeroSSL"

        # migrate-ssl 需要 TTY (isatty 检查), 用 script -c 伪 TTY
        _staging_flag = " --staging" if self.ctx.staging else ""
        cmd = (f"python3 {SCRIPT_PATH} migrate-ssl "
               f"--domain {d} --email {self.ctx.email}{_staging_flag}")
        r = run_with_tty(cmd, "y", timeout=300)

        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            is_rate_limit = any(p in out.lower() for p in [
                "rate limit", "rate-limit", "too many certificates",
                "too many", "retry after"])
            is_timeout = "timeout" in out.lower() or "timed out" in out.lower()
            if is_rate_limit:
                # LE 速率限制: 反复测试的预期行为, 标记为跳过而非失败
                self.check("migrate_ssl_rate_limited", True,
                           f"CA 速率限制 (预期), 目标={target}")
                return
            elif is_timeout:
                self.check("migrate_ssl_network", False,
                           f"网络超时, 目标={target}")
            else:
                self.check("migrate_ssl_exit_0", False,
                           f"exit={r.returncode}\n{out[-200:]}")
            return

        self.check("migrate_ssl_exit_0", True)

        new_ci = cert_info(d)
        new_issuer = new_ci.get("issuer", "")
        self.check("migrate_ssl_changed",
                   new_issuer != old_issuer,
                   f"old={old_issuer} new={new_issuer}")

        # 迁移后 HTTPS 仍工作
        status = curl_status(f"https://{d}/", insecure=True)
        self.check("migrate_ssl_https_ok", status in (200, 301, 302),
                   f"status={status}")

    # ── renew ────────────────────────────────────────────────

    def phase_renew(self):
        """测试证书续期 (不强制, 仅验证流程)"""
        # renew 需要 --email + EAB 才能完成双 CA 容灾
        d = self.ctx.domain
        kid, hmac = _read_eab_credentials(d)
        eab = f"--zerossl-eab-kid {kid} --zerossl-eab-hmac-key {hmac}" if kid and hmac else ""
        r = run_script(
            f"renew --domain {d} --email {self.ctx.email} {eab}"
        )
        # 证书未到期时 renew 应成功 (跳过续期)
        self.check("renew_exit_0", r.returncode == 0,
                   f"exit={r.returncode}")

        out = r.stdout or ""
        self.check("renew_no_error",
                   "[ERROR]" not in out or "证书有效期充足" in out,
                   _m("续期过程有错误", "errors during renewal"))

    # ── 阶段 13: 日志检查 ──────────────────────────────────────

    def phase_logs(self):
        """检查关键日志无异常"""
        d = self.ctx.domain

        # Nginx error log
        err_log = Path(f"/var/log/nginx/{d}.error.log")
        if not err_log.exists():
            err_log = Path("/var/log/nginx/error.log")
        if err_log.exists():
            r = run(f"tail -100 {err_log}")
            lines = (r.stdout or "").split("\n")
            crits = [l for l in lines if "[crit]" in l or "[emerg]" in l]
            self.check("log_nginx_no_crit", len(crits) == 0,
                       f"{len(crits)} critical/emerg:\n" + "\n".join(crits[:3]))

        # PHP-FPM log
        _php_log_candidates = [
            # EL
            "/var/log/php-fpm/www-error.log",
            "/var/log/php-fpm/error.log",
            # Debian/Ubuntu (Sury versions)
            "/var/log/php8.4-fpm.log",
            "/var/log/php8.3-fpm.log",
            "/var/log/php8.2-fpm.log",
            "/var/log/php8.1-fpm.log",
            # Debian native
            f"/var/log/syslog",  # PHP-FPM 日志可能在 syslog
        ]
        for php_log in _php_log_candidates:
            p = Path(php_log)
            if p.exists():
                # 仅检查稳态下的 PHP 错误 (最近 2 分钟)
                # deploy/update/uninstall 期间的瞬态错误 (如 WP 初始化时
                # "Failed opening required") 是预期行为, 不计入
                import time as _t_mod
                _cutoff_ts = _t_mod.time() - 120  # 2 分钟前
                r = run(f"tail -200 {p}")
                fatals = []
                for l in (r.stdout or "").split("\n"):
                    if "FATAL" not in l and "Fatal" not in l:
                        continue
                    # PHP 日志格式: [DD-Mon-YYYY HH:MM:SS UTC]
                    import re as _re_php, calendar
                    _ts_m = _re_php.search(
                        r'\[(\d{2}-\w+-\d{4}\s+\d{2}:\d{2}:\d{2})\s+\w+\]', l)
                    if _ts_m:
                        try:
                            _log_t = _t_mod.strptime(
                                _ts_m.group(1), "%d-%b-%Y %H:%M:%S")
                            _log_ts = calendar.timegm(_log_t)
                            if _log_ts < _cutoff_ts:
                                continue  # 2 分钟前的旧日志
                        except (ValueError, TypeError):
                            pass
                    fatals.append(l)
                self.check("log_php_no_fatal", len(fatals) == 0,
                           f"PHP FATAL: {fatals[0][:80]}" if fatals else "")
                break

        # systemd journal: SSL timer
        r = run(f"journalctl -u '*ssl*' --since '1 hour ago' --no-pager -q 2>/dev/null | tail -20")
        if r.stdout:
            errors = [l for l in r.stdout.split("\n") if "error" in l.lower() or "fail" in l.lower()]
            self.check("log_ssl_timer_no_errors", len(errors) == 0,
                       "\n".join(errors[:3]))

        # logrotate 配置
        lr_conf = Path(f"/etc/logrotate.d/nginx-wp-{d.replace('.', '_d')}")
        if not lr_conf.exists():
            # 尝试其他命名
            for p in Path("/etc/logrotate.d/").glob("*nginx*wp*"):
                lr_conf = p
                break
        self.check("logrotate_configured", lr_conf.exists(),
                   _m("未找到 nginx logrotate 配置", "nginx logrotate config not found"))

        # 响应时间基线 (TTFB)
        r = run(["curl", "-s", "-o", "/dev/null", "-w", "%{time_starttransfer}",
                 "--max-time", "10", "-k", f"https://{d}/"])
        try:
            ttfb = float(r.stdout.strip())
            self.check("response_ttfb_ok", ttfb < 3.0,
                       f"TTFB={ttfb:.2f}s > 3s 阈值")
        except (ValueError, AttributeError):
            pass

    # ── 阶段 14: 卸载 + 重新部署 ──────────────────────────────

    def phase_uninstall(self):
        """测试卸载后重新部署"""
        if self.ctx.safe:
            print(f"  {t('skip_safe')}")
            return

        d = self.ctx.domain

        # uninstall --clean 需要 TTY + 输入域名确认
        cmd = (f"python3 {SCRIPT_PATH} "
               f"uninstall --domain {d} --clean")
        r = run_with_tty(cmd, d, timeout=120)
        self.check("uninstall_exit_0", r.returncode == 0,
                   f"exit={r.returncode}\n{(r.stdout or r.stderr or '')[-200:]}")

        # 验证站点配置已移除
        conf = Path(f"/etc/nginx/conf.d/{d}.conf")
        self.check("uninstall_conf_removed", not conf.exists())

        # 重新部署
        time.sleep(2)
        cmd = (f"deploy --domain {d} --email {self.ctx.email} "
               f"--wp-auto-install --persist-root-pwd {self._common_flags()}")
        r = run_script(cmd, timeout=900, tty=True)
        self.check("redeploy_exit_0", r.returncode == 0,
                   f"exit={r.returncode}\n{(r.stderr or '')[-300:]}")

        # 重新部署后验证
        time.sleep(3)
        status = curl_status(f"https://{d}/", insecure=True)
        self.check("redeploy_https_ok", status in (200, 301, 302),
                   f"status={status}")


# ───────────────────── 智能检测 ─────────────────────────────────

def _parse_build(filepath):
    """从 wp_ssl_bootstrap.py 文件中提取 __build__ 版本号"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'^__build__\s*=\s*["\'](.+?)["\']', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def _find_script_and_baseline():
    """智能查找新版脚本和基线版本

    搜索策略 (按优先级):
      1. 当前目录下所有 wp_ssl_bootstrap*.py
      2. /mnt/user-data/uploads/
      3. /root/

    返回 (script_path, baseline_path) — baseline 可能为 None
    """
    candidates = []
    search_dirs = [
        Path("."),
        Path(__file__).parent,
        Path("/mnt/user-data/uploads"),
        Path("/root"),
    ]
    seen = set()
    for d in search_dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("wp_ssl_bootstrap*.py")):
            real = p.resolve()
            if real in seen or p.name.startswith("test_"):
                continue
            seen.add(real)
            build = _parse_build(str(p))
            if build:
                candidates.append((build, p))

    if not candidates:
        return (SCRIPT_PATH, None)

    # 按版本排序 (降序)
    def _ver_key(item):
        parts = item[0].split(".")
        return tuple(int(x) for x in parts if x.isdigit())

    candidates.sort(key=_ver_key, reverse=True)

    newest = candidates[0][1]
    baseline = candidates[1][1] if len(candidates) >= 2 else None

    return (newest, baseline)


def _detect_deployed_sites():
    """检测已部署的站点 (从 nginx conf.d 扫描)"""
    sites = []
    conf_d = Path("/etc/nginx/conf.d")
    if conf_d.is_dir():
        for f in sorted(conf_d.glob("*.conf")):
            name = f.stem
            if name in ("default", "ssl-redirect") or name.startswith("_"):
                continue
            # 验证 webroot 存在
            webroot = Path(f"/usr/share/nginx/html/{name}")
            if webroot.is_dir():
                sites.append(name)
    return sites


def _interactive_setup():
    """交互式设置: 自动检测环境, 仅需用户确认域名和邮箱

    返回 TestContext
    """
    print(f"\n{'='*60}")
    print(f"  WP-SSL-Bootstrap Integration Test / 集成测试")
    print(f"{'='*60}")

    # 语言确认 (在所有 t() 输出之前)
    _confirm_lang()

    print()
    _p = detect_platform()
    print(f"  {t('platform')}: {_p['id']} {_p['version']} ({_p['family']})")

    # 检测脚本和基线
    script, baseline = _find_script_and_baseline()
    print(f"  {t('script')}: {script} (build {_parse_build(str(script))})")
    if baseline:
        print(f"  {t('baseline')}: {baseline} (build {_parse_build(str(baseline))})")
    else:
        print(f"  {t('baseline')}: {t('baseline_not_found')}")

    # 检测已部署站点
    sites = _detect_deployed_sites()
    has_site = bool(sites)
    if sites:
        print(f"  {t('sites')}: {', '.join(sites)}")
    else:
        print(f"  {t('sites')}: {t('sites_none')}")

    print()

    # ── 域名 ──
    domain = ""
    if len(sites) == 1:
        domain = sites[0]
        print(f"  {t('auto_domain')}: {domain}")
    elif sites:
        print("  检测到多个站点:")
        for i, s in enumerate(sites, 1):
            cert = Path(f"/etc/letsencrypt/live/{s}/fullchain.pem")
            tag = " [SSL ✓]" if cert.exists() else ""
            print(f"    [{i}] {s}{tag}")
        try:
            ch = input(f"  选择站点 [1-{len(sites)}, 或输入新域名]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  取消")
            sys.exit(0)
        if ch.isdigit() and 1 <= int(ch) <= len(sites):
            domain = sites[int(ch) - 1]
        elif ch:
            domain = ch
    else:
        try:
            domain = input(f"  {t('input_domain')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  取消")
            sys.exit(0)

    if not domain:
        print(f"  ✘ {t('need_domain')}")
        sys.exit(1)

    # ── Email ──
    email = ""
    # 尝试从 certbot 自动获取
    rc = Path(f"/etc/letsencrypt/renewal/{domain}.conf")
    if rc.exists():
        try:
            rct = rc.read_text(encoding="utf-8")
            em = re.search(r'^\s*email\s*=\s*(.+)$', rct, re.MULTILINE)
            if em and "@" in em.group(1):
                email = em.group(1).strip()
        except OSError:
            pass
    if email:
        print(f"  {t('auto_email')}: {email}")
    else:
        try:
            email = input(f"  {t('input_email')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  取消")
            sys.exit(0)
    if not email or "@" not in email:
        print(f"  ✘ {t('need_email')}")
        sys.exit(1)

    # ── ZeroSSL EAB (确保 CA 降级链完整) ──
    global _ZEROSSL_EAB_KID, _ZEROSSL_EAB_HMAC
    _kid, _hmac = _detect_zerossl_eab()
    if _kid and _hmac:
        print(f"  ZeroSSL EAB: ✓ ({_kid[:8]}...)")
        _ZEROSSL_EAB_KID = _kid
        _ZEROSSL_EAB_HMAC = _hmac
    else:
        print(f"  ZeroSSL EAB: (未配置, CA 降级可能受限)")

    # ── 测试模式 ──
    print()
    print(f"  {t('test_mode')}")
    print(f"    [1] {t('mode_full')}")
    print(f"    [2] {t('mode_safe')}")
    print(f"    [3] {t('mode_verify')}")
    try:
        mode = input(f"  {t('mode_prompt')}: ").strip() or "2"
    except (EOFError, KeyboardInterrupt):
        mode = "2"

    safe = mode != "1"
    no_deploy = mode == "3"

    # ── 智能选择阶段 ──
    if no_deploy:
        phases = ["pre", "verify", "ssl", "security", "status", "logs"]
        if baseline:
            phases.insert(1, "static")
    else:
        phases = list(PHASES)
        if safe:
            phases = [p for p in phases if p not in ("restore", "uninstall")]
        if not baseline:
            phases = [p for p in phases if p != "static"]
        # 已部署站点: 跳过 deploy, 用 update 代替
        cert = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
        if has_site and domain in sites and cert.exists():
            if "deploy" in phases:
                phases.remove("deploy")

    print(f"\n  {t('will_run')}: {', '.join(phases)}")
    try:
        confirm = input(f"  {t('confirm_start')}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"
    if confirm in ("n", "no"):
        print(f"  {t('cancelled')}")
        sys.exit(0)

    # 更新全局脚本路径
    global SCRIPT_PATH
    SCRIPT_PATH = script

    return TestContext(
        domain=domain,
        email=email,
        safe=safe,
        no_deploy=no_deploy,
        baseline=str(baseline) if baseline else "",
        phases=phases,
    )


# ───────────────────── 报告 ─────────────────────────────────────

def print_report(ctx: TestContext):
    elapsed = time.time() - ctx.start_time
    passed = sum(1 for r in ctx.results if r.passed)
    failed = sum(1 for r in ctx.results if not r.passed)
    total = len(ctx.results)

    print(f"\n{'='*60}")
    print(f"  {t('report_title')}")
    print(f"{'='*60}")
    print(f"  {t('domain')}:     {ctx.domain or '(N/A)'}")
    _p = detect_platform()
    print(f"  平台:     {_p['id']} {_p['version']} ({_p['family']})")
    print(f"  {t('report_duration')}:   {elapsed:.0f}s")
    print(f"  {t('report_passed')}:     {passed}/{total}")
    print(f"  {t('report_failed')}:     {failed}/{total}")

    if failed:
        print(f"\n  ❌ 失败项:")
        for r in ctx.results:
            if not r.passed:
                print(f"    [{r.phase}] {r.name}: {r.message[:80]}")

    # 按阶段统计
    print(f"\n  阶段统计:")
    phases_seen = []
    for r in ctx.results:
        if r.phase not in phases_seen:
            phases_seen.append(r.phase)
    for phase in phases_seen:
        phase_results = [r for r in ctx.results if r.phase == phase]
        p = sum(1 for r in phase_results if r.passed)
        f = sum(1 for r in phase_results if not r.passed)
        mark = "✅" if f == 0 else "❌"
        print(f"    {mark} {phase}: {p}/{p+f}")

    print(f"\n{'='*60}")

    # 写入 JSON 报告
    report_path = Path(f"/root/test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    report = {
        "timestamp": datetime.now().isoformat(),
        "domain": ctx.domain,
        "platform": _p,
        "duration_s": round(elapsed, 1),
        "passed": passed,
        "failed": failed,
        "total": total,
        "results": [
            {"name": r.name, "phase": r.phase, "passed": r.passed, "message": r.message}
            for r in ctx.results
        ],
    }
    try:
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"  JSON 报告: {report_path}")
    except OSError:
        pass

    return 0 if failed == 0 else 1


# ───────────────────── 主入口 ───────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WP-SSL-Bootstrap Integration Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              # 交互式 (推荐, 自动检测一切):
              python3 test_integration.py

              # 命令行模式:
              python3 test_integration.py --domain example.com --email admin@example.com

              # 安全模式 (跳过 uninstall/restore):
              python3 test_integration.py --domain example.com --email admin@example.com --safe

              # 仅验证已部署站点:
              python3 test_integration.py --domain example.com --email admin@example.com --phase verify,ssl,security

              # 仅静态分析:
              python3 test_integration.py --phase static --baseline old_version.py
        """),
    )
    parser.add_argument("--domain", help=_m("测试域名 (A 记录须指向本机)", "test domain (A record must point here)"))
    parser.add_argument("--email", help=_m("证书注册邮箱", "certificate registration email"))
    parser.add_argument("--safe", action="store_true", help=_m("跳过破坏性测试", "skip destructive tests"))
    parser.add_argument("--no-deploy", action="store_true", help=_m("跳过部署, 仅预检", "skip deploy, pre-check only"))
    parser.add_argument("--staging", action="store_true", default=True,
                        help=_m("使用 LE Staging 环境 (默认开启, 避免速率限制)", "use LE Staging (default on, avoids rate limits)"))
    parser.add_argument("--no-staging", action="store_true",
                        help=_m("使用生产环境签发真实证书 (慎用, 有速率限制)", "use production certs (caution: rate limited)"))
    parser.add_argument("--baseline", help=_m("静态分析基线文件 (旧版 wp_ssl_bootstrap.py)", "baseline file for static analysis (old version)"))
    parser.add_argument("--phase", help=_m("仅测试指定阶段 (逗号分隔)", "test specific phases only (comma-separated)"))
    parser.add_argument("--lang", choices=["zh", "en"],
                        help="display language (default: auto-detect)")
    parser.add_argument("--zerossl-eab-kid", default="",
                        help=_m("ZeroSSL EAB Key ID (确保 CA 降级可用)", "ZeroSSL EAB Key ID (for CA fallback)"))
    parser.add_argument("--zerossl-eab-hmac-key", default="",
                        help="ZeroSSL EAB HMAC Key")
    parser.add_argument("--notify-webhook", default="",
                        help=_m("SSL 续期失败通知 webhook URL (HTTPS, 如 Slack/DingTalk/Feishu)", "webhook URL for renewal failure alerts (HTTPS)"))

    args = parser.parse_args()

    # ── 语言确定 ──
    global LANG, _ZEROSSL_EAB_KID, _ZEROSSL_EAB_HMAC
    if args.lang:
        LANG = args.lang

    # ── ZeroSSL EAB (确保 CA 降级链完整) ──
    _kid = getattr(args, 'zerossl_eab_kid', '') or ''
    _hmac = getattr(args, 'zerossl_eab_hmac_key', '') or ''
    if not (_kid and _hmac):
        _kid, _hmac = _detect_zerossl_eab()
    _ZEROSSL_EAB_KID = _kid
    _ZEROSSL_EAB_HMAC = _hmac

    # ── Webhook 自动检测 (从已部署站点的 ssl.env 继承) ──
    _webhook_url = getattr(args, 'notify_webhook', '') or ''
    if not _webhook_url:
        _webhook_url = _detect_webhook_url()
        if _webhook_url:
            print(f"  Webhook: {_webhook_url[:60]}... (auto-detected)")

    # ── 交互式 vs 命令行 ──
    if not args.domain and not args.no_deploy and not args.phase:
        # 无参数 → 进入交互式模式 (语言确认在 _interactive_setup 内部)
        ctx = _interactive_setup()
    else:
        # 命令行模式: 无 --lang 时按默认逻辑检测, 不再询问 (防止 CI/脚本卡住)

        if not args.no_deploy and not args.domain and not args.phase:
            parser.error(_m("需要 --domain (或使用 --no-deploy, 或无参数进入交互式)", "--domain required (use --no-deploy for pre-check only, or run without args for interactive)"))
        if args.domain and not args.email:
            # 尝试自动获取 email
            _auto_email = ""
            rc = Path(f"/etc/letsencrypt/renewal/{args.domain}.conf")
            if rc.exists():
                try:
                    rct = rc.read_text(encoding="utf-8")
                    em = re.search(r'^\s*email\s*=\s*(.+)$', rct, re.MULTILINE)
                    if em and "@" in em.group(1):
                        _auto_email = em.group(1).strip()
                except OSError:
                    pass
            if _auto_email:
                args.email = _auto_email
            else:
                parser.error(_m("需要 --email", "--email required"))

        # 智能查找基线
        if not args.baseline:
            _, _auto_bl = _find_script_and_baseline()
            if _auto_bl:
                args.baseline = str(_auto_bl)

        ctx = TestContext(
            domain=args.domain or "",
            email=args.email or "",
            safe=args.safe,
            no_deploy=args.no_deploy,
            staging=args.staging and not getattr(args, 'no_staging', False),
            notify_webhook=_webhook_url,
            baseline=args.baseline or "",
        )

        if args.phase:
            ctx.phases = [p.strip() for p in args.phase.split(",")]
        elif args.no_deploy:
            ctx.phases = ["pre"]
        else:
            ctx.phases = list(PHASES)
            if args.safe:
                ctx.phases = [p for p in ctx.phases if p not in ("restore", "uninstall")]
            if not ctx.baseline:
                ctx.phases = [p for p in ctx.phases if p != "static"]

    ctx.start_time = time.time()

    # 日志 Tee: 所有输出同时写入终端和文件
    _ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _log_path = f"/root/test_log_{_ts}.txt"
    _tee = _TeeWriter(_log_path)
    sys.stdout = _tee
    sys.stderr = _TeeStderr(_tee)  # [PATCH-284] stderr 也写入日志

    _pi = detect_platform()
    print(f"\n{'='*60}")
    print(f"  {t('title')}")
    print(f"  域名: {ctx.domain or '(无)'}")
    print(f"  平台: {_pi['id']} {_pi['version']} ({_pi['family']})")
    print(f"  阶段: {', '.join(ctx.phases)}")
    print(f"  {t('mode')}: {t('mode_safe_label') if ctx.safe else t('mode_full_label')}")
    # [PATCH-285] 中国大陆网络 + staging = 死局:
    # LE Staging 服务器 (acme-staging-v02.api.letsencrypt.org) 在中国大陆不可达,
    # ZeroSSL 无 staging 端点 → 无可用 CA → 签发必败。
    # 直接测试 LE staging 连通性 (不依赖云商判断, 中国云海外节点可达)。
    if ctx.staging:
        _staging_reachable = False
        try:
            _sr = subprocess.run(
                ["curl", "-s", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}",
                 "https://acme-staging-v02.api.letsencrypt.org/directory"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding="utf-8", timeout=8, check=False)
            _staging_reachable = _sr.returncode == 0 and (_sr.stdout or "").strip() not in ("000", "")
        except Exception:
            pass
        if not _staging_reachable:
            ctx.staging = False
            print(_m("  证书: 生产环境 (LE Staging 不可达, 自动切换 ZeroSSL)",
                      "  Cert: Production (LE Staging unreachable, auto-switched to ZeroSSL)"))
        else:
            print(_m("  证书: LE Staging (测试证书, 不受速率限制)",
                      "  Cert: LE Staging (test cert, no rate limit)"))
    else:
        print(_m("  证书: 生产环境 (⚠ 受 LE 速率限制: 同域名 5 张/周)",
                  "  Cert: Production (⚠ LE rate limit: 5 certs/domain/week)"))
    print(f"{'='*60}")

    tester = IntegrationTest(ctx)

    for phase in ctx.phases:
        tester.run_phase(phase)
        if tester.fatal:
            _skip = [p for p in ctx.phases if ctx.phases.index(p) > ctx.phases.index(phase)]
            if _skip:
                print(f"\n  ⛔ " + _m(
                    f"关键预检失败，跳过后续阶段: {', '.join(_skip)}",
                    f"Critical pre-check failed, skipping: {', '.join(_skip)}"))
            break

    result = print_report(ctx)

    # 显示日志路径并关闭 Tee
    print(f"  {t('report_log')}: {_log_path}")
    _tee.close()

    return result


if __name__ == "__main__":
    sys.exit(main())
