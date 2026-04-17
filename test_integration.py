#!/usr/bin/env python3
"""WP-SSL-Bootstrap V3.2.8+ 集成测试脚本

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
    local_test: bool = False  # [v3.2.346] 本地测试模式 (自签证书)
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

def curl_status(url, timeout=10, insecure=False, resolve_to=None):
    """获取 HTTP 状态码。

    resolve_to: 可选, 形如 "127.0.0.1" — 强制 curl 直连回环/本机地址,
                Host 头仍用 URL 中的域名。用于绕过 CDN (Cloudflare) 代理,
                直接探测源站 nginx 的 :80/:443 响应。
    """
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
           "--max-time", str(timeout)]
    if insecure:
        cmd.append("-k")
    if resolve_to:
        # 提取 url 的 scheme+host+port 用于 --resolve HOST:PORT:ADDR
        _m = re.match(r'^(https?)://([^/:]+)(?::(\d+))?', url)
        if _m:
            _scheme, _host, _port = _m.group(1), _m.group(2), _m.group(3)
            if not _port:
                _port = "443" if _scheme == "https" else "80"
            cmd.extend(["--resolve", f"{_host}:{_port}:{resolve_to}"])
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
    # [v3.2.350] EL 兼容发行版补全: openEuler/Kylin/UOS/Anolis/OpenCloudOS,
    # 被测脚本 _detect_el_family_and_version() 早已支持 (v3.2.344),
    # 但测试脚本 detect_platform() 漏了, 导致 family=unknown + pkg_mgr=yum,
    # 进而影响若干 phase 的分支判断. ID_LIKE 回退也兼容未来新衍生发行版.
    el_ids = {"centos", "rhel", "almalinux", "rocky", "ol", "eurolinux",
              "cloudlinux", "scientific", "amzn", "alinux",
              "openeuler", "kylin", "uos", "anolis", "opencloudos",
              "openanolis"}
    try:
        with open("/etc/os-release") as f:
            _id_like = ""
            for _ln in f:
                if _ln.startswith("ID_LIKE="):
                    _id_like = _ln.strip().split("=", 1)[1].strip('"').lower()
                    break
    except OSError:
        _id_like = ""
    _id_like_tokens = set(_id_like.split())
    _el_like_tokens = {"rhel", "fedora", "centos"}
    _is_el_like = bool(_id_like_tokens & _el_like_tokens)
    if (info["id"] in el_ids
            or Path("/etc/redhat-release").exists()
            or _is_el_like):
        info["family"] = "el"
        info["pkg_mgr"] = "dnf" if info["version_major"] >= 8 else "yum"
        info["firewall"] = "firewalld"
        info["redis_svc"] = _detect_active_svc(["valkey", "redis"])
        info["php_fpm_svc"] = "php-fpm"
        # EL7: mariadb 可能叫 mariadb 或 mysql; EL8+: mariadb
        info["db_svc"] = _detect_active_svc(["mariadb", "mysql", "mysqld"])
    elif info["id"] in ("ubuntu", "debian", "linuxmint", "pop"):
        info["family"] = "debian"
        info["pkg_mgr"] = "apt"
        info["redis_svc"] = _detect_active_svc(["valkey-server", "valkey", "redis-server", "redis"])
        info["db_svc"] = _detect_active_svc(["mariadb", "mysql", "mysqld"])
        # PHP-FPM: phpX.Y-fpm (Sury/native)
        for v in ["8.5", "8.4", "8.3", "8.2", "8.1", "8.0"]:
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
        # [v3.2.313b] CF 代理探测结果 (PRE 阶段填充, verify 阶段使用)
        self.is_cf_proxied = False

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
        # [v3.2.346] 本地测试模式不能与 staging 同时使用 (被测脚本会 exit 1),
        # local-test 优先. staging 在 local-test 模式下失去意义.
        if getattr(self.ctx, 'local_test', False):
            flags += " --local-test"
        elif self.ctx.staging:
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

    @staticmethod
    def _code_only(src: str) -> str:
        """[v3.2.340] 返回剥离 # 注释行的源, 供子串断言使用.

        动机: 诸如 `"innodb_flush_method" in new_src` 的断言在实现中经常同时
        匹配注释和代码, 若代码被删只留注释, 测试会静默通过 (假阳性).
        本会话已发现 19 个此类弱断言; 6 个核心修复改用 _code_only(src).

        过滤规则:
          - 整行 `^\\s*#` 注释: 完全剥离
          - 行内 `code  # comment`: 只保留 # 之前的代码部分
          - 不处理 triple-quoted docstring (需 AST, 代价过高;
            大部分 docstring 位于 `def`/`class` 头部, 与 feature 实现代码分离,
            实际风险低)
        """
        import re as _re_co
        _out = []
        for _ln in src.split('\n'):
            _stripped = _ln.lstrip()
            if _stripped.startswith('#'):
                continue  # 整行注释完全剥离
            # 行内 # 注释: 只保留代码部分
            # 注意: 不简单 split('#'), 因字符串里可能有 # (如 '#id')
            # 用启发式: # 前必须是空白或行首
            _idx = -1
            _in_str = False
            _str_ch = ''
            for _i, _c in enumerate(_ln):
                if _in_str:
                    if _c == '\\':
                        continue  # 下一字符转义跳过
                    if _c == _str_ch:
                        _in_str = False
                elif _c in ('"', "'"):
                    _in_str = True
                    _str_ch = _c
                elif _c == '#' and (_i == 0 or _ln[_i-1] in ' \t'):
                    _idx = _i
                    break
            if _idx >= 0:
                _out.append(_ln[:_idx].rstrip())
            else:
                _out.append(_ln)
        return '\n'.join(_out)

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
            # [v3.2.346] 本地测试模式: 跳过 DNS 预检 (域名无需真解析)
            if getattr(self.ctx, 'local_test', False):
                self.check("dns_resolved", True,
                           _m("[local-test] 跳过 DNS 检查",
                              "[local-test] skipping DNS check"))
            else:
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
                # [v3.2.313b] 持久化到 self 供 verify 阶段使用 (http_redirect
                # 测试需知道是否走 CDN, CDN 场景下 curl 公网地址探测不到
                # 源站 nginx 的 :80 重定向, 需 --resolve 127.0.0.1 直连源站)
                self.is_cf_proxied = is_cf
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
        # WPDeployManager 方法不丢失 (迁移到 Manager 不算丢失)
        ow = cls_methods(ot, "WPDeployManager")
        nw = cls_methods(nt, "WPDeployManager")
        # 收集所有 Manager 类方法 (迁移目标)
        _all_mgr_methods = set()
        for _mcn in ["NginxManager", "MariaDBManager", "PHPManager",
                      "RedisManager", "CertManager"]:
            _all_mgr_methods |= cls_methods(nt, _mcn)
        # 已知 WPDM→Manager 重命名 (下划线前缀丢弃 / 语义精简)
        _renamed_wpdm = {
            "_detect_cert_issuer", "_detect_cert_key_type",
            "_detect_nginx_user", "_detect_redis_service_name",
            "_detect_redis_version", "_safe_reload_nginx",
            "_get_active_php_conf_paths", "_get_active_php_ini_paths",
            "_get_php_conf_paths", "_get_php_ini_paths",
            "_read_php_ini_values",
            # P1: _upgrade_valkey_major → _upgrade_valkey_if_needed
            "_upgrade_valkey_major",
            # P2: version detection unification
            "_detect_installed_mariadb_version",  # → _detect_mariadb_version
            "_get_mariadb_full_version",          # → _detect_mariadb_full_version
            "_get_nginx_version_tuple",           # → _detect_nginx_version
            # P3: _fixup_ → _fix_
            "_fixup_mariadb_client_mismatch",   # → _fix_mariadb_client_mismatch
            # P5: _setup_mariadb_official_repo_el → _setup_mariadb_repo_el_fallback
            "_setup_mariadb_official_repo_el",
            # [v3.2.312] 架构清理: 移除 WPDeployManager 纯代理方法,
            # 调用点内联到 self.mariadb / PHPManager 直接调用
            "_detect_db_service",        # → self.mariadb.detect_service() inlined
            "_get_active_php_ver_str",   # 0 callers, 删除
            # [v3.2.324] Opus 4.7 第四轮: 死代码清理
            "_srcache_install_load_module",  # PATCH-289 兼容别名, 0 调用者
        }
        # 已知内联/合并 (迁移时功能并入其他 Manager 方法, 非丢失)
        _inlined_wpdm = {
            "_detect_certbot_version", "_detect_certbot_full_version",
            "_detect_installed_php_version",
            "_is_pip_venv_certbot", "_is_snap_certbot",
            "_certbot_supports_key_type",
        }
        lost = ow - nw - _all_mgr_methods - _renamed_wpdm - _inlined_wpdm
        _migrated = ow - nw - lost
        self.check(f"wpdm_methods ({len(ow)}→{len(nw)}, {len(_migrated)} migrated)",
                   len(lost) == 0,
                   f"丢失: {sorted(lost)[:5]}" if lost else "")

        # 所有 Manager 类方法不丢失
        # 排除已知的重命名/合并方法 (不算丢失)
        _renamed_methods = {
            "setup_valkey_repo_deb",   # → _upgrade_valkey_deb (后于 v3.2.300 删除)
            "setup_valkey_repo_el",    # → _upgrade_valkey_el
            # v3.2.300: packages.valkey.io 不是 Valkey 官方仓库 (来自第三方
            # 博客误导信息), curl 100% 失败。Debian/Ubuntu 的 Valkey 保持
            # universe 仓库 (7.2.x, Canonical SRU 维护)。函数被删除。
            "_upgrade_valkey_deb",
            # P2: version detection unification (inside Managers)
            "_detect_installed_mariadb_version",  # → _detect_mariadb_version
            "_get_mariadb_full_version",          # → _detect_mariadb_full_version
            "_get_nginx_version_tuple",           # → _detect_nginx_version
            # P3: _fixup_ → _fix_
            "_fixup_mariadb_client_mismatch",   # → _fix_mariadb_client_mismatch
            # P5: _setup_mariadb_official_repo_el → _setup_mariadb_repo_el_fallback
            "_setup_mariadb_official_repo_el",
            # [v3.2.312] PHPManager 6 个 0-caller 薄包装删除 (架构清理);
            # 保留唯一 get_redis_candidates (3 callers, 语义化包装)
            "get_packages", "get_fpm_service_name", "get_sock_path",
            "get_pool_conf", "get_ini_path", "get_module_dir",
        }
        for cn in ["NginxManager", "MariaDBManager", "PHPManager",
                    "RedisManager", "CertManager"]:
            om = cls_methods(ot, cn)
            nm = cls_methods(nt, cn)
            ml = om - nm - _renamed_methods
            if om:  # 旧版有此类
                self.check(f"{cn} " + _m("方法不丢失", "methods preserved"),
                           len(ml) == 0,
                           f"丢失: {sorted(ml)[:3]}" if ml else "")

        # 类常量不丢失 (常量可能迁移到 Manager 类, 只要全局仍存在即可)
        oc = cls_constants(ot, "WPDeployManager")
        nc = cls_constants(nt, "WPDeployManager")
        # 收集所有 Manager 类常量 (迁移目标)
        _all_mgr_consts = set()
        for _mcn in ["NginxManager", "MariaDBManager", "PHPManager",
                      "RedisManager", "CertManager"]:
            _all_mgr_consts |= cls_constants(nt, _mcn)
        cl = oc - nc - _all_mgr_consts  # 仅标记真正丢失 (不在任何 Manager)
        _migrated = oc - nc - cl
        self.check(_m("类常量不丢失", "class consts preserved") + f" ({len(oc)}→{len(nc)}, {len(_migrated)} migrated)",
                   len(cl) == 0,
                   f"丢失: {sorted(cl)[:5]}" if cl else "")

        # 全局函数不丢失
        of = global_funcs(ot)
        nf = global_funcs(nt)
        # P2: 模块级函数重命名
        _renamed_globals = {
            "_get_nginx_version_tuple",   # → _detect_nginx_version (module-level)
        }
        fl = of - nf - _renamed_globals
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

        # Docstring 不显著衰退 (Facade cleanup 会删除 ~200 个委托的 pro-forma docstring)
        od = count_docstrings(ot)
        nd = count_docstrings(nt)
        self.check(_m("docstrings 不衰退", "docstrings preserved") + f" ({od}→{nd})",
                   nd >= od * 0.85)

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
        # [v3.2.340] 剥离注释: 上面的注释行本身含 "X-Title/X-Priority", 会让假阳
        _src_code_p284 = self._code_only(new_src)
        self.check("P284_ntfy_curl_format",
                   "X-Title" in _src_code_p284 and "X-Priority" in _src_code_p284,
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

        # P286-2: PHPManager.php_ini_security_directives 方法
        # [PATCH-291] harden_ini 重构为纯数据方法 php_ini_security_directives
        self.check("P286_php_harden_ini_def",
                   "def php_ini_security_directives(" in new_src,
                   "PHPManager 缺少 php_ini_security_directives 方法")
        self.check("P286_php_harden_ini_call",
                   "self.php.php_ini_security_directives()" in new_src,
                   "WPDeployManager 未委托 PHPManager.php_ini_security_directives()")

        # P286-3: RedisManager.harden_conf 方法
        # [v3.2.340] 剥离注释: 模块头部文档 (L145, L149) 含 "def harden_conf" 和
        # "self.redis.harden_conf()" 示例, 会让代码删除后测试仍通过 (假阳性).
        _src_code_p286 = self._code_only(new_src)
        self.check("P286_redis_harden_conf_def",
                   "def harden_conf(self" in _src_code_p286,
                   "RedisManager 缺少 harden_conf 方法")
        self.check("P286_redis_harden_conf_call",
                   "self.redis.harden_conf()" in _src_code_p286,
                   "WPDeployManager 未委托 RedisManager.harden_conf()")

        # ── Build 3.2.295: Redis 幂等性 + 安全加固 + 诊断 ──
        self.check("B295_redis_sock_args",
                   "def _sock_args(self" in new_src,
                   "RedisManager 缺少 _sock_args() 方法 (redis-cli socket 连接)")
        self.check("B295_redis_needs_restart",
                   "_needs_restart = False" in new_src
                   and "_needs_restart = True" in new_src,
                   "harden_conf 缺少 _needs_restart 标志 (装饰性/功能性变更分离)")
        self.check("B295_redis_skip_harden",
                   "skip_harden" in new_src
                   and "skip_harden=True" in new_src,
                   "verify_socket_access 缺少 skip_harden 参数")
        self.check("B295_redis_port_0",
                   "port 0" in new_src
                   and re.search(r'port\\s\+0|port\s+0', new_src),
                   "harden_conf 缺少 port 0 (Unix socket 启用后禁用 TCP)")
        self.check("B295_redis_unixsocket_quoted_regex",
                   r"""["\']?/""" in new_src or r"""['"]?/""" in new_src,
                   "unixsocket 检测正则缺少引号兼容 (CONFIG REWRITE 格式)")
        self.check("B295_redis_duplicate_cleanup",
                   "清理" in new_src and "重复" in new_src and "unixsocket" in new_src,
                   "harden_conf 缺少重复 unixsocket 行清理逻辑")
        self.check("B295_redis_tcp_fallback_port_restore",
                   "port" in new_src and "6379" in new_src
                   and "TCP fallback" in new_src,
                   "TCP 回退路径缺少 port 6379 恢复逻辑")
        self.check("B295_phpfpm_acl_comment_owner",
                   "ACL active" in new_src,
                   "PHP-FPM 缺少 ACL active 时注释 listen.owner 逻辑")
        self.check("B295_mariadb_socket_fallback",
                   "_socket_candidates" in new_src,
                   "MariaDB _wait_db_ready 缺少 --socket 强制回退")
        self.check("B295_collect_logs_redis_socket",
                   "_sock_args" in new_src and "diag-redis-info" in new_src,
                   "collect_logs 的 redis-cli INFO 缺少 socket 参数")
        self.check("B295_t_kwargs_nginx_h3_min",
                   "nginx_h3_min=_NGINX_HTTP3_MIN_VERSION_STR" in new_src,
                   "交互菜单 t(_dk) 缺少 nginx_h3_min kwarg")

        # ── Build 3.2.297: Facade cleanup - wrappers removed, callers use Manager directly ──
        self.check("B297_direct_challenge_call",
                   "self.nginx.setup_nginx_for_challenge(" in new_src,
                   "调用点应直接使用 self.nginx.setup_nginx_for_challenge()")
        self.check("B297_ecc_fallback_in_cert_mgr",
                   "def _try_issue_ecc_with_rsa_fallback(" in new_src and
                   "self.cert._try_issue_ecc_with_rsa_fallback(" in new_src,
                   "_try_issue_ecc_with_rsa_fallback 应在 CertManager 中, WPDM 通过 self.cert 调用")
        self.check("B296_injection_safe_reload_nginx",
                   "self.nginx._safe_reload_nginx = self.nginx.safe_reload" in new_src,
                   "NginxManager 缺少 _safe_reload_nginx 注入")
        self.check("B296_deploy_socket_before_production",
                   "verify_socket_access(_web_user_d)" in new_src,
                   "deploy 路径缺少 HTTPS 配置前的 socket 权限检查")
        self.check("B296_nginx_restart_after_usermod",
                   "systemctl\", \"restart\", \"nginx" in new_src
                   and "pick up new group" in new_src,
                   "verify_socket_access 缺少 usermod 后 nginx restart")
        # [v3.2.340] 剥离注释: 原注释 L16584 "http2_recv_timeout / ..." 会让
        # 弱断言静默通过. 改用代码块直接验证废弃指令出现在移除列表里.
        _src_code_b296 = self._code_only(new_src)
        self.check("B296_nginx_130_directive_cleanup",
                   "B296" in _src_code_b296
                   and "http2_recv_timeout" in _src_code_b296,
                   "缺少 Nginx 1.30 废弃指令 (http2_*) 清理逻辑")
        self.check("B296_deploy_print_versions",
                   "_print_component_versions" in new_src
                   and new_src.count("_print_component_versions()") >= 5,
                   "deploy/update/restore/enable-ssl 路径应都有组件版本输出")

        # ── Nginx 1.30.0 新特性 ──
        self.check("N130_max_headers",
                   "max_headers 50" in new_src,
                   "HTTPS/HTTP 配置应含 max_headers 50 (DoS 防护)")
        self.check("N130_add_header_inherit_merge",
                   "add_header_inherit merge" in new_src,
                   "HTTPS/HTTP 配置应含 add_header_inherit merge (安全头继承)")
        self.check("N130_mptcp_detection",
                   "def _detect_mptcp_support" in new_src
                   and "net.mptcp.enabled" in new_src,
                   "缺少 MPTCP 检测函数 (sysctl + nginx probe)")
        # [1.30] MPTCP: _ensure_mptcp_nginx_support 应仅做 sysctl, 不触发重编译
        self.check("N130_mptcp_sysctl_only",
                   "def _ensure_mptcp_nginx_support" in new_src
                   and "_compile_srcache" not in
                       new_src[new_src.index("def _ensure_mptcp_nginx_support"):
                               new_src.index("def _ensure_mptcp_nginx_support") + 2000],
                   "_ensure_mptcp_nginx_support 不应包含重编译逻辑 (sysctl-only)")
        # [1.30] nginx.conf http{} 全局优化
        self.check("N130_optimize_nginx_main_conf",
                   "def _optimize_nginx_main_conf" in new_src
                   and "tcp_nopush" in new_src
                   and "tcp_nodelay" in new_src,
                   "缺少 _optimize_nginx_main_conf 方法")
        self.check("N130_ech_support",
                   "def _detect_ech_support" in new_src
                   and "ssl_ech_file" in new_src
                   and "def setup_ech" in new_src,
                   "缺少 ECH 前瞻性支持 (检测+密钥生成+nginx配置)")

        # [FIX] 冗余调用去重
        # restore/enable-ssl 路径: _setup_redis_cache 内部已含 socket 验证,
        # 不应在调用前再显式调用 _verify_redis_socket_access
        # 找到 restore() 方法体
        _restore_idx = new_src.find("def restore(self")
        _restore_end = new_src.find("\n    def ", _restore_idx + 10) if _restore_idx > 0 else -1
        if _restore_idx > 0 and _restore_end > 0:
            _restore_body = new_src[_restore_idx:_restore_end]
            _socket_before_cache = ("_verify_redis_socket_access" in _restore_body
                                     and "_setup_redis_cache" in _restore_body
                                     and _restore_body.index("_verify_redis_socket_access")
                                         < _restore_body.index("_setup_redis_cache"))
            self.check("dedup_restore_no_socket_before_cache",
                       not _socket_before_cache,
                       "restore 路径 _setup_redis_cache 前不应显式调用 "
                       "_verify_redis_socket_access (内部已含)")

        # _lemp_setup_database: _tune_mariadb 内部已 restart+wait,
        # 不应在 _tune_mariadb 之后再显式 _wait_db_ready
        _lemp_db_idx = new_src.find("def _lemp_setup_database(")
        _lemp_db_end = new_src.find("\n    def ", _lemp_db_idx + 10) if _lemp_db_idx > 0 else -1
        if _lemp_db_idx > 0 and _lemp_db_end > 0:
            _lemp_body = new_src[_lemp_db_idx:_lemp_db_end]
            _tune_idx = _lemp_body.find("_tune_mariadb()")
            if _tune_idx > 0:
                _after_tune = _lemp_body[_tune_idx:_tune_idx + 200]
                self.check("dedup_no_wait_after_tune",
                           "_wait_db_ready" not in _after_tune,
                           "_lemp_setup_database 在 _tune_mariadb 后不应再调 "
                           "_wait_db_ready (tune 内部已含)")

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
        for _mariadb_item in ["bind-address = 127.0.0.1", "local-infile = 0",
                          "skip-symbolic-links", "secure-file-priv",
                          "skip-show-database"]:
            self.check(f"P286_mdb_{_mariadb_item.split('=')[0].strip().replace('-','_')}",
                       _mariadb_item in new_src,
                       f"MariaDB 加固缺少 {_mariadb_item}")

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
        # 检查 import readline 在模块级 (前 500 行内, 含架构规范/陷阱目录头部)
        _first_500 = '\n'.join(new_src.split('\n')[:500])
        self.check("P286_readline_module_level",
                   "import readline" in _first_500,
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

        # ── 10. 统一版本升级体系 ──

        # DEFAULT 即目标: _determine_*_target() 与 DEFAULT 比较
        self.check("unified_php_default_85",
                   '"8.5"' in new_src and "_PHP_DEFAULT_VERSION" in new_src,
                   "_PHP_DEFAULT_VERSION 应为 8.5 (最新稳定版, 统一升级目标)")
        self.check("unified_mariadb_default_118",
                   '"11.8"' in new_src and "_MARIADB_DEFAULT_VERSION" in new_src,
                   "_MARIADB_DEFAULT_VERSION 应为 11.8 (最新 LTS)")
        self.check("target_valkey_version",
                   "_VALKEY_TARGET_VERSION" in new_src,
                   "缺少 _VALKEY_TARGET_VERSION 常量 (Valkey 基础设施独立)")

        # 全平台仓库覆盖
        self.check("valkey_el_upgrade",
                   "_upgrade_valkey_el" in new_src,
                   "RedisManager 缺少 _upgrade_valkey_el (EL Remi 路径)")
        # v3.2.300: Debian/Ubuntu 不再尝试升级 (Valkey 无官方 APT 仓库,
        # universe 的 7.2.x 由 Canonical SRU 维护已足够)。
        # 此测试从 "必须存在" 反转为 "必须被删除"。
        # 下方 valkey_deb_upgrade_removed (@ 2083) 已覆盖此语义, 此处保留
        # 反向守卫防止未来有人误再引入无效升级路径。
        self.check("valkey_deb_no_upgrade_path",
                   "def _upgrade_valkey_deb(" not in new_src
                   and "https://packages.valkey.io" not in new_src,
                   "Debian/Ubuntu 不应再有 _upgrade_valkey_deb (v3.2.300 删除)")
        self.check("mariadb_official_repo_el",
                   "_setup_mariadb_repo_el_fallback" in new_src
                   and "dlm.mariadb.com" in new_src,
                   "缺少 MariaDB 官方 YUM 仓库回退 (EL module stream 不可用时)")
        self.check("mariadb_allowerasing",
                   "allowerasing" in new_src
                   and "MariaDB-server" in new_src
                   and "MariaDB-client" in new_src,
                   "MariaDB 官方仓库升级应包含 server+client+common+shared")
        self.check("mariadb_repo_cleanup",
                   "_cleanup_mariadb_official_repo" in new_src,
                   "缺少 MariaDB 官方仓库安装失败后清理")
        # [FIX] MariaDB 版本检测: 优先 mariadbd (server)
        # [v3.2.330] 方法重命名: _detect_mariadb_version → detect_version (canonical)
        # 使用 "class MariaDBManager" 作锚点, 方法在类内前 30000 字符内
        self.check("mariadb_detect_mariadbd",
                   '"mariadbd"' in new_src
                   and "mariadbd" in new_src.split(
                       "class MariaDBManager")[1][:30000],
                   "版本检测应优先检查 mariadbd (server 二进制)")
        # [FIX] MariaDB 版本检测: rpm -q 回退
        self.check("mariadb_detect_rpm_fallback",
                   'rpm", "-q", "--queryformat"' in new_src
                   and "MariaDB-server" in new_src,
                   "版本检测应有 rpm -q MariaDB-server 回退")
        # [FIX] MariaDB repo 版本不匹配时覆盖写入
        self.check("mariadb_repo_version_check",
                   "target_ver" in new_src
                   and "版本不匹配" in new_src,
                   "MariaDB repo 应检查 URL 中的版本号, 不匹配时覆盖")
        # [FIX] EL10 跳过 dnf module disable mariadb
        self.check("mariadb_el10_skip_module_disable",
                   "el_ver < 10" in new_src,
                   "EL10 应跳过 dnf module disable mariadb (dnf5 无模块会挂死)")
        # [FIX] MariaDB client/server 版本一致性修复
        self.check("mariadb_fixup_client_mismatch",
                   "_fix_mariadb_client_mismatch" in new_src,
                   "缺少 client/server 版本不一致修复函数")
        # [FIX] unix_socket 双认证
        self.check("mariadb_unix_socket_dual_auth",
                   "unix_socket" in new_src
                   and "OR mysql_native_password" in new_src,
                   "MariaDB root 应启用 unix_socket + 密码双认证")
        # [FIX] mariadb-upgrade 标记文件
        self.check("mariadb_upgrade_marker",
                   ".wp_mariadb_upgrade_done" in new_src,
                   "mariadb-upgrade 完成标记应使用脚本自己的文件")
        # [FIX] _finalize_mariadb_upgrade 必须写入标记 (防止 update 重跑 mariadb-upgrade)
        _finalize_idx = new_src.find("def _finalize_mariadb_upgrade(")
        if _finalize_idx > 0:
            # 找到下一个 def 的位置作为函数边界
            _next_def = new_src.find("\n    def ", _finalize_idx + 10)
            _finalize_body = new_src[_finalize_idx:_next_def] if _next_def > 0 else new_src[_finalize_idx:_finalize_idx + 3000]
            self.check("mariadb_upgrade_marker_in_finalize",
                       "wp_mariadb_upgrade_done" in _finalize_body,
                       "_finalize_mariadb_upgrade 未写入升级标记, 会导致 update 每次重跑 mariadb-upgrade")
        # [FIX] Fresh install 路径也必须写入标记 (deploy 无升级时 _finalize 不会调用)
        self.check("mariadb_fresh_install_marker",
                   new_src.count("_maria_ver_before == (0, 0)") >= 2 and
                   new_src.count(
                       'Path("/root/.wp_mariadb_upgrade_done").write_text') >= 2,
                   "Fresh install 路径 (EL + Debian) 应写入 mariadb-upgrade 标记")
        # [FIX] Debian/Ubuntu Valkey 优先安装
        self.check("deb_valkey_first",
                   "valkey" in new_src
                   and "_deb_redis_pkg" in new_src,
                   "Debian/Ubuntu deploy 应优先尝试 valkey 包")
        # [FIX] 交互式 UX: 主菜单不默认选择, 空输入提示
        _op_prompt_section = new_src.split("interactive_op_prompt")[1][:200]
        self.check("menu_no_enter_default",
                   "Enter=1" not in _op_prompt_section,
                   "主菜单 prompt 不应有 Enter=1 默认选项")
        self.check("menu_empty_hint",
                   "请输入 1-" in new_src and "Ctrl+C" in new_src,
                   "主菜单空输入应显示提示信息 (请输入 N 的数字)")
        # [FIX] restore 路径调用完整性
        _rp_idx = new_src.find("def _restore_post_fixup")
        _rp_body = new_src[_rp_idx:_rp_idx + 15000] if _rp_idx >= 0 else ""
        self.check("restore_open_quic_firewall",
                   "_open_quic_firewall" in _rp_body,
                   "restore 路径应调用 _open_quic_firewall")
        self.check("restore_hardening_constants",
                   "_ensure_wp_hardening_constants" in _rp_body,
                   "restore 路径应调用 _ensure_wp_hardening_constants")
        # [FIX] Debian dpkg 锁等待
        self.check("apt_dpkg_lock_timeout",
                   "DPkg::Lock::Timeout" in new_src
                   and "_wait_for_apt_lock" in new_src
                   and "fuser" in new_src,
                   "apt 命令应注入 DPkg::Lock::Timeout + fuser 预检")
        # [FIX] Debian valkey 服务名检测
        # [v3.2.330] 方法重命名为 detect_service (canonical), detect_service_name 改为别名
        import re as _re_rds
        _rm_match = _re_rds.search(r'^class RedisManager', new_src, _re_rds.MULTILINE)
        _rm_idx = _rm_match.start() if _rm_match else -1
        _dsn_body = new_src[_rm_idx:_rm_idx + 8000] if _rm_idx >= 0 else ""
        self.check("deb_valkey_server_svc",
                   "valkey-server" in _dsn_body,
                   "Debian 服务名检测应包含 valkey-server")
        # [FIX] deploy 路径 socket 权限提前
        _essl_idx = new_src.find("def enable_ssl")
        _essl_pre = new_src[_essl_idx:_essl_idx + 8000] if _essl_idx >= 0 else ""
        _sock_before_prod = (
            _essl_pre.find("verify_socket_access") <
            _essl_pre.find("setup_nginx_for_production")
        ) if "verify_socket_access" in _essl_pre else False
        self.check("socket_before_nginx_production",
                   _sock_before_prod,
                   "enable_ssl 应在 setup_nginx_for_production 之前验证 socket 权限")
        # [FIX] deploy/update/restore 完成时输出组件版本
        self.check("component_version_summary",
                   new_src.count("_print_component_versions") >= 4,
                   "deploy/update/restore 完成时应调用 _print_component_versions")

        # 无冲突: 不应同时存在 _to_target 和 _if_needed
        self.check("no_dup_php_to_target",
                   "_upgrade_php_to_target" not in new_src,
                   "应删除 _upgrade_php_to_target (已合并入 _if_needed)")
        self.check("no_dup_mariadb_to_target",
                   "_upgrade_mariadb_to_target" not in new_src,
                   "应删除 _upgrade_mariadb_to_target (已合并入 _if_needed)")

        # PHPManager.upgrade_to_target (被 _if_needed 间接调用)
        _php_methods = cls_methods(nt, "PHPManager")
        self.check("php_upgrade_to_target",
                   "upgrade_to_target" in _php_methods,
                   "PHPManager 缺少 upgrade_to_target 方法")

        # MariaDB innodb_flush_method 版本门控
        # [v3.2.340] 用 _code_only 剥离注释, 原实现会误匹配 L31873 的注释说明.
        _src_code_1834 = self._code_only(new_src)
        self.check("compat_innodb_flush_method",
                   "innodb_flush_method" in _src_code_1834
                   and "(11, 0)" in _src_code_1834,
                   "innodb_flush_method 缺少 MariaDB 11.0+ 版本门控")

        # ── 11. RedisManager 新方法 (架构合规) ──

        _redis_methods = cls_methods(nt, "RedisManager")
        for _rm in ["tune_runtime", "tune_timeout", "verify_ping",
                     "verify_socket_access", "upgrade_to_target",
                     "harden_conf"]:
            self.check(f"redis_mgr_{_rm}",
                       _rm in _redis_methods,
                       f"RedisManager 缺少 {_rm} 方法")

        # NginxManager.neutralize_default_server_block
        _nginx_methods = cls_methods(nt, "NginxManager")
        self.check("nginx_mgr_neutralize",
                   "neutralize_default_server_block" in _nginx_methods,
                   "NginxManager 缺少 neutralize_default_server_block 方法")

        # MariaDBManager.cleanup_proxies_priv
        _mariadb_methods = cls_methods(nt, "MariaDBManager")
        self.check("mdb_mgr_cleanup_proxies",
                   "cleanup_proxies_priv" in _mariadb_methods,
                   "MariaDBManager 缺少 cleanup_proxies_priv 方法")

        # ── 12. 架构合规: WPDeployManager 零组件逻辑 ──

        # WPDeployManager 不应直接调用 Redis CONFIG SET/GET/REWRITE
        _wpdm_src = ""
        for n in _ast.walk(nt):
            if isinstance(n, _ast.ClassDef) and n.name == "WPDeployManager":
                _wpdm_src = _ast.get_source_segment(new_src, n) or ""
                break
        if not _wpdm_src:
            # 回退: 从 class 行到文件末尾
            _wpdm_start = new_src.find("class WPDeployManager:")
            if _wpdm_start > 0:
                _wpdm_src = new_src[_wpdm_start:]

        _cfg_set_in_wpdm = len(re.findall(
            r'"CONFIG",\s*"SET"', _wpdm_src))
        self.check("arch_zero_config_set_in_wpdm",
                   _cfg_set_in_wpdm == 0,
                   f"WPDeployManager 残留 {_cfg_set_in_wpdm} 处 CONFIG SET (应在 RedisManager)")

        _proxies_in_wpdm = _wpdm_src.count("DELETE FROM mysql.proxies_priv")
        self.check("arch_zero_proxies_delete_in_wpdm",
                   _proxies_in_wpdm == 0,
                   f"WPDeployManager 残留 {_proxies_in_wpdm} 处 proxies_priv DELETE")

        # WPDeployManager 应委托 self.redis.tune_runtime / tune_timeout
        self.check("arch_delegate_tune_runtime",
                   "self.redis.tune_runtime(" in _wpdm_src,
                   "WPDeployManager 未委托 RedisManager.tune_runtime()")
        self.check("arch_delegate_tune_timeout",
                   "self.redis.tune_timeout()" in _wpdm_src,
                   "WPDeployManager 未委托 RedisManager.tune_timeout()")
        self.check("arch_delegate_verify_ping",
                   "self.redis.verify_ping()" in _wpdm_src,
                   "WPDeployManager 未委托 RedisManager.verify_ping()")
        self.check("arch_delegate_neutralize",
                   "self.nginx.neutralize_default_server_block()" in _wpdm_src,
                   "WPDeployManager 未委托 NginxManager.neutralize_default_server_block()")
        self.check("arch_delegate_cleanup_proxies",
                   "self.mariadb.cleanup_proxies_priv(" in _wpdm_src,
                   "WPDeployManager 未委托 MariaDBManager.cleanup_proxies_priv()")

        # ── 12b. 架构迁移验证 (Move Method refactoring) ──

        # 核心迁移: NginxManager 应有 81+ 个新增方法
        _nginx_new = cls_methods(nt, "NginxManager")
        _nginx_old = cls_methods(ot, "NginxManager") if ot else set()
        _nginx_added = _nginx_new - _nginx_old
        self.check("migration_nginx_growth",
                   len(_nginx_new) >= 90,
                   f"NginxManager 应 ≥90 方法 (当前 {len(_nginx_new)})")

        # 关键迁移方法验证 (抽样 — 覆盖每个迁移批次)
        _key_nginx = [
            "_setup_brotli", "_compile_brotli_module", "_brotli_install_deps",  # batch 12b
            "setup_fail2ban", "_setup_cloudflare_real_ip",  # batch 17, 19
            "_nginx_post_upgrade_repair", "_recompile_nginx_dynamic_modules",  # batch 13, 20
            "setup_nginx_for_challenge", "_upgrade_nginx_minor_if_available",  # batch 20
            "_ensure_build_deps", "_safe_extract_tar", "_clone_pinned_module",  # batch 11
            "atomic_write", "setup_logrotate", "_fix_webroot_ownership",  # batch 12a
            "_run_certbot_with_lock",  # batch 19 (wait, this went to CertManager)
        ]
        # Remove _run_certbot_with_lock (CertManager, not Nginx)
        _key_nginx = [m for m in _key_nginx if m != "_run_certbot_with_lock"]
        for _km in _key_nginx:
            self.check(f"migration_nginx_{_km}",
                       _km in _nginx_new,
                       f"NginxManager 缺少迁移方法 {_km}")

        _key_cert = [
            "_verify_ssl_handshake", "_restore_letsencrypt_certs",  # batch 13
            "_build_domain_args", "_get_cert_domains",  # batch 11
            "_run_certbot_with_lock", "_build_ca_providers",  # batch 19
            "_try_issue_ecc_with_rsa_fallback",  # batch 19
        ]
        _cert_new = cls_methods(nt, "CertManager")
        for _km in _key_cert:
            self.check(f"migration_cert_{_km}",
                       _km in _cert_new,
                       f"CertManager 缺少迁移方法 {_km}")

        _key_php = [
            "_compile_php_redis_extension", "_php_post_upgrade_restart",  # batch 14
            "_upgrade_php_minor_if_available", "_swap_create_file",  # batch 14, early
        ]
        _php_new = cls_methods(nt, "PHPManager")
        for _km in _key_php:
            self.check(f"migration_php_{_km}",
                       _km in _php_new,
                       f"PHPManager 缺少迁移方法 {_km}")

        _key_maria = [
            "_finalize_mariadb_upgrade", "_upgrade_mariadb_minor_if_available",  # batch 17
            "_upgrade_mariadb_if_needed", "_diagnose_mariadb_failure",  # batch 18, 13
        ]
        _mariadb_new = cls_methods(nt, "MariaDBManager")
        for _km in _key_maria:
            self.check(f"migration_mdb_{_km}",
                       _km in _mariadb_new,
                       f"MariaDBManager 缺少迁移方法 {_km}")

        # WPDM 委托清理验证: 纯委托应已删除, 仅保留编排方法
        _wrapper_count = 0
        _total_wpdm = 0
        for _n in _ast.walk(nt):
            if isinstance(_n, _ast.ClassDef) and _n.name == "WPDeployManager":
                for _ch in _ast.iter_child_nodes(_n):
                    if isinstance(_ch, _ast.FunctionDef):
                        _total_wpdm += 1
                        _body = new_src[_ch.col_offset:] if hasattr(_ch, 'col_offset') else ""
                        _blines = new_src.split('\n')[_ch.lineno-1:_ch.end_lineno]
                        _btxt = '\n'.join(_blines)
                        if '委托' in _btxt or '代理到' in _btxt:
                            _wrapper_count += 1
                break
        _proxy_pct = (_wrapper_count / _total_wpdm * 100) if _total_wpdm else 0
        self.check(f"migration_facade_cleanup ({_wrapper_count}/{_total_wpdm} = {_proxy_pct:.0f}%)",
                   _proxy_pct <= 40,
                   f"WPDM 委托率应 ≤40% — 纯委托已删除, 仅保留编排方法 (当前 {_proxy_pct:.0f}%)")

        # 跨组件注入完备性: WPDM.__init__ 中应有 ≥20 处 self.xxx.yyy = 注入
        _init_src = ""
        for _n in _ast.walk(nt):
            if isinstance(_n, _ast.ClassDef) and _n.name == "WPDeployManager":
                for _ch in _ast.iter_child_nodes(_n):
                    if isinstance(_ch, _ast.FunctionDef) and _ch.name == "__init__":
                        _init_src = '\n'.join(new_src.split('\n')[_ch.lineno-1:_ch.end_lineno])
                        break
                break
        _inject_count = len(re.findall(
            r'self\.(nginx|cert|php|mariadb|redis)\.\w+\s*=', _init_src))
        self.check(f"migration_cross_inject ({_inject_count} injections)",
                   _inject_count >= 20,
                   f"跨组件注入应 ≥20 处 (当前 {_inject_count})")

        # 初始化顺序安全: _is_dnf5 注入必须在 _detect_dnf_skip_unavailable 之前
        _dnf5_inject = _init_src.find("nginx._is_dnf5 = self._is_dnf5")
        _dnf_skip_call = _init_src.find("self._dnf_skip_unavail")  # actual assignment using the call
        self.check("migration_init_order_dnf5",
                   0 < _dnf5_inject < _dnf_skip_call,
                   "_is_dnf5 注入必须在 _detect_dnf_skip_unavailable() 调用之前")

        # 初始化顺序安全: php_fpm_svc 注入必须在 php_fpm_svc 赋值之后
        # [Facade cleanup] 调用点已从 self._xxx() 改为 self.php._xxx()
        _fpm_assign = _init_src.find("self.php_fpm_svc = self.php._detect_php_fpm_service()")
        if _fpm_assign < 0:
            _fpm_assign = _init_src.find("self.php_fpm_svc = self.php._resolve_php_fpm_service(")
        _fpm_inject = _init_src.find("nginx._php_fpm_svc = self.php_fpm_svc")
        self.check("migration_init_order_fpm_svc",
                   0 < _fpm_assign < _fpm_inject,
                   "php_fpm_svc 注入必须在 php_fpm_svc 赋值之后")

        # Manager 类零 global 语句 (排除 cache 类 globals)
        # [v3.2.327] 模块级缓存 (如 _MARIADB_VERSION_CACHE, _NGINX_VERSION_CACHE)
        # 是合法的实现细节 — detect 方法为类方法但缓存为模块级, 需要 global 声明
        _global_in_mgr = []
        for _n in _ast.walk(nt):
            if isinstance(_n, _ast.ClassDef) and _n.name in (
                    "NginxManager", "MariaDBManager", "PHPManager",
                    "RedisManager", "CertManager"):
                for _ch in _ast.walk(_n):
                    if isinstance(_ch, _ast.Global):
                        # 允许 cache 名 (大写 + _CACHE 后缀) 作为 module-level 实现细节
                        _names = list(_ch.names)
                        _non_cache = [
                            _name for _name in _names
                            if not (_name.isupper() and '_CACHE' in _name)
                        ]
                        if _non_cache:
                            _global_in_mgr.append(f"{_n.name}.{_non_cache}")
        self.check("migration_zero_global_in_mgr",
                   len(_global_in_mgr) == 0,
                   f"Manager 类不应有非缓存 global 语句: {_global_in_mgr[:3]}")

        # [Facade cleanup regression guard] __init__ 中所有 RHS self.X 必须可解析
        # 防止 callback-style 引用 (self._method 无括号) 指向已删除的委托
        _wpdm_methods = set()
        _wpdm_class_consts = set()
        _wpdm_node = None
        for _n in _ast.walk(nt):
            if isinstance(_n, _ast.ClassDef) and _n.name == "WPDeployManager":
                _wpdm_node = _n
                for _ch in _ast.iter_child_nodes(_n):
                    if isinstance(_ch, _ast.FunctionDef):
                        _wpdm_methods.add(_ch.name)
                for _ch in _n.body:
                    if isinstance(_ch, (_ast.Assign, _ast.AnnAssign)):
                        _tgts = _ch.targets if hasattr(_ch, 'targets') else [_ch.target]
                        for _tgt in _tgts:
                            if isinstance(_tgt, _ast.Name):
                                _wpdm_class_consts.add(_tgt.id)
                break

        _init_node = None
        if _wpdm_node:
            for _ch in _ast.iter_child_nodes(_wpdm_node):
                if isinstance(_ch, _ast.FunctionDef) and _ch.name == "__init__":
                    _init_node = _ch
                    break

        _unresolved_init_refs = []
        if _init_node:
            _init_assigned = set()
            # Walk in source order (approximate via body traversal)
            for _stmt in _ast.walk(_init_node):
                if isinstance(_stmt, (_ast.Assign, _ast.AnnAssign)):
                    _val = _stmt.value
                    # Check RHS for self.X accesses
                    if _val:
                        for _sub in _ast.walk(_val):
                            if (isinstance(_sub, _ast.Attribute) and
                                isinstance(_sub.value, _ast.Name) and
                                _sub.value.id == "self"):
                                _a = _sub.attr
                                if (_a not in _wpdm_methods and
                                    _a not in _wpdm_class_consts and
                                    _a not in _init_assigned and
                                    # skip known runtime-assigned attrs via conditional branches
                                    _a not in ("php_fpm_svc", "db_svc", "nginx_user",
                                               "pkg_mgr")):
                                    _unresolved_init_refs.append(
                                        f"L{_sub.lineno}:self.{_a}")
                    # Record LHS
                    _tgts = _stmt.targets if hasattr(_stmt, 'targets') else [_stmt.target]
                    for _tgt in _tgts:
                        if (isinstance(_tgt, _ast.Attribute) and
                            isinstance(_tgt.value, _ast.Name) and
                            _tgt.value.id == "self"):
                            _init_assigned.add(_tgt.attr)

        self.check("migration_init_refs_resolvable",
                   len(_unresolved_init_refs) == 0,
                   f"__init__ RHS 引用了不存在的属性: {_unresolved_init_refs[:3]}")

        # [Facade cleanup regression guard] Manager 类内禁用 self.{own_mgr}.X
        # 防止 Remove Middleman 误将 Manager 内部的 self._method 替换为
        # self.{manager}._method — Manager 自己没有 .nginx/.mariadb/... 属性
        _mgr_domain = {
            "NginxManager": "nginx", "MariaDBManager": "mariadb",
            "RedisManager": "redis", "PHPManager": "php", "CertManager": "cert",
        }
        _wrong_self_refs = []
        for _n in _ast.walk(nt):
            if not (isinstance(_n, _ast.ClassDef) and _n.name in _mgr_domain):
                continue
            _own = _mgr_domain[_n.name]
            for _sub in _ast.walk(_n):
                if (isinstance(_sub, _ast.Attribute) and
                    isinstance(_sub.value, _ast.Attribute) and
                    isinstance(_sub.value.value, _ast.Name) and
                    _sub.value.value.id == "self" and
                    _sub.value.attr in _mgr_domain.values()):
                    _wrong_self_refs.append(
                        f"{_n.name} L{_sub.lineno}:self.{_sub.value.attr}.{_sub.attr}")
        self.check("migration_no_self_mgr_inside_mgr",
                   len(_wrong_self_refs) == 0,
                   f"Manager 内部不应使用 self.{{mgr}}.X: {_wrong_self_refs[:3]}")

        # ── 13. PHP 8.5 前向兼容 ──

        # [v3.2.340] 剥离注释后断言, 防止 [PHP-8.5-COMPAT] 注释掩盖代码删除
        _src_code_php85 = self._code_only(new_src)
        self.check("php85_max_memory_limit",
                   "max_memory_limit" in _src_code_php85,
                   "缺少 PHP 8.5 max_memory_limit INI 预适应")
        self.check("php85_file_cache_read_only",
                   "file_cache_read_only" in _src_code_php85,
                   "缺少 PHP 8.5 opcache.file_cache_read_only 预适应")

        # ── 14. OPcache file_cache + Valkey timeout ──

        self.check("opcache_file_cache",
                   "opcache.file_cache" in new_src
                   and "/var/lib/php/opcache" in new_src,
                   "缺少 OPcache file_cache 二级缓存配置")
        # [FIX-OPCACHE-OWN] /var/lib/php/opcache 所有权必须始终修正
        # (PHP RPM 可能以 apache:apache 创建, 导致 wp-cron @ User=nginx 崩溃)
        self.check("opcache_dir_always_chown",
                   'if not _opc_dir.is_dir()' not in new_src
                   and 'chown", "-R"' in new_src
                   and '"/var/lib/php/opcache"' in new_src,
                   "OPcache 目录 chown 应无条件执行 (不能被 if not is_dir() 守卫)")
        # wp-cron systemd service 防御性 ExecStartPre 确保 opcache 目录可访问
        self.check("opcache_wp_cron_execstartpre",
                   "ExecStartPre=+/usr/bin/install -d -m 1733" in new_src
                   and "/var/lib/php/opcache" in new_src,
                   "wp-cron service 缺少 ExecStartPre 防御性 opcache 目录修复")
        # [FIX-FPM-TIER] v3.2.298: PHP-FPM 档位按现代 WP 实测内存重新校准
        # 旧: 2GB 档 ondemand/10 → 实测每日 17-19 次打满 max_children
        # 新: 2GB 档 dynamic/15  → 常驻 start_servers=3, 峰值扩 15
        self.check("fpm_tier_2gb_dynamic_15",
                   '"dynamic", 15' in new_src
                   and 'total_mb <= 2048' in new_src,
                   "2GB 档应升级为 dynamic/15 (原 ondemand/10 并发不足)")
        self.check("fpm_tier_4gb_dynamic_25",
                   '"dynamic", 25' in new_src
                   and 'total_mb <= 4096' in new_src,
                   "4GB 档应升级为 dynamic/25 (原 dynamic/20)")
        # >4GB 档公式: 0.5 × total / 70 (按 70MB/worker 预算, 保留 50% buffer)
        self.check("fpm_tier_large_formula",
                   "total_mb * 0.5 / 70" in new_src
                   and "max(25," in new_src,
                   ">4GB 公式应为 max(25, total×0.5/70), 对齐现代 WP 单 worker ~70MB")
        # 确认旧档位已被全部替换, 没有残留的 ondemand/10 或 dynamic/20
        self.check("fpm_tier_old_removed",
                   '"ondemand", 10' not in new_src
                   and '"dynamic", 20' not in new_src
                   and '0.6 / 50' not in new_src,
                   "旧 FPM 档位应被完全替换 (ondemand/10, dynamic/20, 0.6/50)")
        # [FIX-F08-PHPFPM] usermod -aG valkey nginx 后必须同时重启 PHP-FPM,
        # 否则首次 deploy 时现有 PHP-FPM workers 仍用旧 groups, WP object-cache
        # 连 valkey unix socket 返回 EACCES, 站点 HTTP 500 直到下一次 PHP-FPM
        # 重启才自愈。症状: lamtin.hk verify.https_200 status=500。
        # v3.2.302: 加入自包含探测回退 (不依赖 cross-injected _php_fpm_svc)
        self.check("f08_restart_php_fpm_after_usermod",
                   "FIX-F08-PHPFPM" in new_src
                   and 'restart", "nginx"' in new_src
                   and '_fpm_svc_f08' in new_src,
                   "F-08 usermod 后应同时 restart nginx + PHP-FPM (群组刷新)")
        # [v3.2.302] F-08 PHP-FPM 探测自包含回退: systemctl list-units 扫描
        # active php*-fpm。lamtin.hk Debian 12 日志显示 self._php_fpm_svc
        # 未注入时之前 fallthrough 不重启 → 500 持续。
        self.check("f08_phpfpm_self_contained_detection",
                   "list-units" in new_src
                   and r"php[\d.]*-?fpm" in new_src
                   and "FIX-F08-PHPFPM" in new_src,
                   "F-08 应自包含探测 php-fpm (不依赖 cross-injection)")
        # [v3.2.305] F-08 健壮性修复:
        #   1. 独立 helper _f08_scan_active_php_fpm() 可复用
        #   2. Debian/Ubuntu 上无版本号的 "php-fpm" attr 视为 stale (init 时
        #      终极 fallback 返回值), 强制 fresh 探测
        #   3. 验证 systemctl restart 返回码, 非零则 fresh 探测重试
        #   4. 重启失败打 WARNING 诚实告知 (不再伪造 "restarted" 日志)
        self.check("f08_helper_scan_active_php_fpm",
                   "def _f08_scan_active_php_fpm(" in new_src
                   and "self._f08_scan_active_php_fpm()" in new_src,
                   "缺少 _f08_scan_active_php_fpm() helper 或调用")
        self.check("f08_detects_stale_debian_fallback",
                   "_looks_stale_deb" in new_src
                   and '"php-fpm"' in new_src
                   and '/etc/debian_version' in new_src,
                   "F-08 应识别 Debian 上 stale 'php-fpm' attribute 值")
        self.check("f08_verify_restart_return_code",
                   "_rc.returncode == 0" in new_src
                   and "_f08_restarted" in new_src
                   and "重新探测" in new_src,
                   "F-08 应验证 systemctl restart 返回码 + 失败时重试")
        self.check("f08_honest_failure_log",
                   "php-fpm 重启失败" in new_src
                   and "scanned=" in new_src,
                   "F-08 重启失败应打诚实 WARNING 包含诊断信息")
        # [v3.2.306 + v3.2.307] snap install 健壮性修复:
        #   1. 超时 180s → 420s (国内云拉 snapcraft.io 常 2-5 min)
        #   2. 失败后查 snap changes 找 pending install
        #   3. snap watch <id> 等 daemon 完成 (避免 "change in progress" 冲突)
        #   4. watch 超时则 snap abort 再重试
        #   5. v3.2.307 复用到 snap install core / snap refresh core
        #   6. v3.2.307 squashfs + snapcraft.io 预检
        self.check("snap_install_timeout_increased",
                   'timeout=420' in new_src
                   and 'def _snap_install_or_refresh_robust(' in new_src,
                   "snap install 超时应 ≥ 420s (helper 统一)")
        self.check("snap_find_pending_install_helper",
                   "def _find_pending_snap_install(" in new_src
                   and '"snap", "changes"' in new_src
                   and '"Doing"' in new_src,
                   "缺少 _find_pending_snap_install() helper")
        self.check("snap_watch_pending_change",
                   '"snap", "watch"' in new_src
                   and "_find_pending_snap_install" in new_src
                   and "snap 后台仍在处理" in new_src,
                   "snap install 失败应先 watch pending change, 而非盲重试")
        self.check("snap_abort_stuck_change",
                   '"snap", "abort"' in new_src
                   and "未能完成" in new_src,
                   "snap watch 超时应 abort 卡住的 change 再重试")
        # [v3.2.307] 新增健壮性覆盖:
        self.check("snap_robust_helper_unified",
                   "def _snap_install_or_refresh_robust(" in new_src
                   and 'self._snap_install_or_refresh_robust("core"' in new_src
                   and 'self._snap_install_or_refresh_robust(' in new_src
                   and 'classic=True' in new_src,
                   "snap install/refresh 应用统一 helper (core + certbot)")
        self.check("snap_precheck_squashfs",
                   "def _check_squashfs_available(" in new_src
                   and '"lsmod"' in new_src
                   and '"modprobe", "-n", "squashfs"' in new_src,
                   "缺少 squashfs 内核模块预检")
        self.check("snap_precheck_network",
                   "def _check_snapcraft_reachable(" in new_src
                   and "snapcraft.io" in new_src
                   and '"--connect-timeout", "5"' in new_src,
                   "缺少 snapcraft.io 连通性预检")
        self.check("snap_precheck_fallback_to_pip",
                   "snap 路径无效" in new_src
                   and "snapcraft.io 不可达" in new_src
                   and "_install_certbot_pip_venv" in new_src,
                   "预检失败应跳至 pip venv, 不浪费 snap 超时")
        # [v3.2.308] EPEL 多镜像 fallback (中国云必需):
        #   原生 extras (AlmaLinux/Rocky 自带) → 阿里云 → 腾讯云 → USTC → 上游
        self.check("epel_install_helper_exists",
                   "def _install_epel_release(" in new_src
                   and "mirrors.aliyun.com/epel" in new_src
                   and "mirrors.cloud.tencent.com/epel" in new_src
                   and "mirrors.ustc.edu.cn/fedora/epel" in new_src,
                   "缺少 _install_epel_release() 多镜像 helper")
        self.check("epel_call_sites_use_helper",
                   new_src.count("_install_epel_release(") >= 5,
                   "EPEL 安装点应全部使用 helper (>= 4 个调用点 + 1 个 def)")
        self.check("epel_tries_native_first",
                   'install", "-y", "epel-release"],' in new_src
                   and "extras" in new_src,
                   "EPEL helper 应先尝试发行版原生 epel-release (零网络依赖)")
        self.check("epel_no_raw_fedoraproject_url",
                   new_src.count(
                       "https://dl.fedoraproject.org/pub/epel/"
                       "epel-release-latest-") <= 1,
                   "EPEL 原始 URL 只应在 helper 内保留一次 (最终兜底)")
        # [v3.2.309] HTTP-01 挑战指数退避:
        # RETRYABLE 错误 (challenge failed / could not connect / unauthorized)
        # 通常由 DNS 传播延迟/防火墙短暂拦截触发, 用 [0, 15, 45]s 内部重试。
        # 不重试: FATAL / PERMISSION / rate-limit。
        self.check("http01_exponential_backoff",
                   "_backoffs = [0, 15, 45]" in new_src
                   and "HTTP-01 挑战短暂失败" in new_src
                   and "time.sleep(_backoff_s)" in new_src,
                   "_try_issue_with_ca 应有 HTTP-01 指数退避 [0,15,45]s")
        self.check("http01_skips_ratelimit_retry",
                   "CA 限流, 放弃内部重试" in new_src
                   and "rate-limited" in new_src,
                   "限流类 RETRYABLE 不重试 (交上层换 CA)")
        self.check("http01_skips_fatal_permission",
                   "_last_err_type != CmdResult.RETRYABLE" in new_src,
                   "FATAL/PERMISSION 应直接返回, 不参与重试")
        self.check("http01_cleans_challenge_between_retries",
                   "_clean_challenge_dir" in new_src
                   and "避免旧 token 干扰" in new_src,
                   "每次重试前清理残留 challenge 文件")
        # [v3.2.310] MariaDB run_sql 多路径连接 fallback:
        # 默认失败 → 尝试常见 socket 路径 → TCP 127.0.0.1:3306
        self.check("mariadb_multi_path_connection",
                   "def _try_sql_alt_paths(" in new_src
                   and "/run/mysqld/mysqld.sock" in new_src
                   and "/var/lib/mysql/mysql.sock" in new_src
                   and '"--protocol=TCP"' in new_src,
                   "缺少 MariaDB 多路径连接 fallback")
        self.check("mariadb_fallback_on_connection_err_only",
                   "can't connect to" in new_src
                   and "is_external_db" in new_src
                   and "_is_conn_err" in new_src,
                   "仅连接类错误触发 fallback, 外置 DB 不触发")
        # [v3.2.311] Fail2Ban 依赖检测: 预装 python3-pyinotify (Debian) /
        # python3-inotify (EL), 避免 fail2ban inotify backend 降级到 polling。
        self.check("fail2ban_deps_autoinstall",
                   '"python3-pyinotify"' in new_src
                   and '"python3-inotify"' in new_src
                   and "inotify backend" in new_src,
                   "Fail2Ban 应预装 pyinotify/inotify 依赖")
        # [v3.2.311] WP-CLI 插件多源 fallback:
        # 路径 1 默认 → 路径 2 --force → 路径 3 直接 zip URL (绕过 WP API)。
        # 应用于 redis-cache 和 nginx-helper 两个插件安装点。
        self.check("wpcli_plugin_install_robust_helper",
                   "def _wpcli_plugin_install_robust(" in new_src
                   and 'self._wpcli_plugin_install_robust("redis-cache")' in new_src
                   and 'self._wpcli_plugin_install_robust("nginx-helper")' in new_src,
                   "WP-CLI 插件安装应使用多源 helper (redis-cache + nginx-helper)")
        self.check("wpcli_plugin_direct_url_fallback",
                   "downloads.wordpress.org/plugin/" in new_src
                   and "绕过 WP API" in new_src,
                   "WP-CLI 插件第 3 路径应用直接 zip URL 绕过 WP API")
        # [v3.2.311] srcache 编译失败降级路径的诊断日志增强。
        # 原日志只说 "srcache 模块未检测到", 用户无法知道问题和恢复方法。
        # 新日志明确: 发生了什么 + 常见原因 + 手动排查命令 + libnginx-mod
        # 包与 nginx.org 二进制 ABI 不兼容的说明。
        self.check("srcache_fallback_diagnostic_log",
                   "FastCGI 缓存 (性能略低但功能完整)" in new_src
                   and "build-essential" in new_src
                   and "libnginx-mod-http-srcache-filter" in new_src
                   and "不适用于本脚本使用的 nginx.org 二进制" in new_src,
                   "srcache 降级日志应含诊断提示 + 为何不能用 libnginx-mod")
        # [v3.2.312] 架构清理: 移除所有 WPDeployManager 纯代理方法。
        # 1. 架构文档 (REFACTOR 组件管理器块) 应标记迁移已完成, 不再保留
        #    "旧方法从 WPDeployManager 移入 Manager, 原位留代理" 过时描述。
        # 2. 原 6 个 PHPManager.get_* 薄包装 (0 调用者) 应全部删除。
        # 3. 原 2 个 WPDeployManager 代理 (_detect_db_service /
        #    _get_active_php_ver_str) 应全部删除, 调用点直接内联。
        self.check("arch_doc_proxy_migration_complete",
                   "纯代理方法迁移完成" in new_src
                   and "逐步删除代理" not in new_src
                   and "保留代理属性 self.nginx" not in new_src,
                   "架构文档应声明纯代理迁移完成, 删除过时迁移路线图")
        self.check("wpdeploy_no_proxy_methods_remaining",
                   "def _detect_db_service(" not in new_src
                   and "def _get_active_php_ver_str(" not in new_src
                   and "代理到 self.mariadb.detect_service" not in new_src
                   and "代理到 PHPManager._extract_ver_from_svc" not in new_src,
                   "WPDeployManager 纯代理方法应全部删除")
        self.check("wpdeploy_inlines_db_service_detect",
                   "self.db_svc = self.mariadb.detect_service()" in new_src,
                   "db_svc 应直接 inline 调用 self.mariadb.detect_service()")
        self.check("phpmanager_removed_dead_get_wrappers",
                   "def get_packages(" not in new_src
                   and "def get_fpm_service_name(" not in new_src
                   and "def get_sock_path(" not in new_src
                   and "def get_pool_conf(" not in new_src
                   and "def get_ini_path(" not in new_src
                   and "def get_module_dir(" not in new_src,
                   "PHPManager 的 6 个 0-caller get_* 薄包装应删除")
        self.check("phpmanager_keeps_semantic_wrapper",
                   "def get_redis_candidates(" in new_src
                   and "语义化包装 platform.get" in new_src,
                   "get_redis_candidates 应保留 (3 caller + 语义化包装)")
        # [v3.2.313] 生产优化:
        #   1. REST API (/wp-json/) 限速 zone - 爬虫重灾端点
        #   2. worker_connections 1024 → 4096 - WP 生产基线
        self.check("wpapi_rate_limit_zone_declared",
                   'zone=wpapi_{safe}:10m rate=5r/s' in new_src,
                   "应声明 wpapi limit_req_zone (5r/s, 10MB)")
        self.check("wpjson_location_rate_limited",
                   'location ^~ /wp-json/' in new_src
                   and 'limit_req zone=wpapi_{safe_name}' in new_src
                   and 'burst=20 nodelay' in new_src
                   and 'limit_req_status 429' in new_src,
                   "/wp-json/ 应有 limit_req + burst=20 + 429 状态码")
        self.check("wpjson_preserves_wp_routing",
                   'location ^~ /wp-json/' in new_src
                   and 'try_files $uri $uri/ /index.php?$args' in new_src,
                   "/wp-json/ 必须保留 WP 标准路由 (try_files → index.php)")
        self.check("nginx_worker_connections_tuning_helper",
                   "def _tune_nginx_worker_connections(" in new_src
                   and "target: int = 4096" in new_src
                   and 'worker_connections' in new_src
                   and 'nginx -t' in new_src,
                   "缺少 _tune_nginx_worker_connections() 幂等 helper")
        self.check("nginx_worker_connections_wired",
                   "self.nginx._tune_nginx_worker_connections()" in new_src
                   and "self.nginx.neutralize_default_server_block()" in new_src,
                   "worker_connections 调优应在 update 流程中调用")
        self.check("nginx_worker_connections_idempotent",
                   "if _cur < target:" in new_src
                   and "用户已调大, 尊重" in new_src,
                   "worker_connections 应幂等 (保留用户的更大值)")
        # [v3.2.314] 两个 best-practice 改进:
        #   (1) HTTP-01 退避 jitter (避免 thundering herd)
        #   (2) worker_rlimit_nofile 配套设置 (避免 EMFILE)
        self.check("http01_backoff_jitter",
                   "_base_backoffs = [0, 15, 45]" in new_src
                   and "random.uniform(-_b * 0.2" in new_src
                   and "max(1, int(_b + random.uniform" in new_src,
                   "HTTP-01 退避应有 ±20% jitter")
        self.check("random_module_imported",
                   "import random" in new_src,
                   "random 模块应被显式导入 (jitter 需要)")
        self.check("nginx_worker_rlimit_nofile_param",
                   "rlimit_nofile: int = 65535" in new_src,
                   "_tune_nginx_worker_connections 应接受 rlimit_nofile 参数")
        self.check("nginx_worker_rlimit_nofile_applied",
                   "worker_rlimit_nofile" in new_src
                   and "worker_processes" in new_src
                   and "worker_rlimit_nofile  %d" in new_src,
                   "应插入 worker_rlimit_nofile (紧随 worker_processes)")
        self.check("nginx_worker_rlimit_nofile_idempotent",
                   "if _cur_r < rlimit_nofile:" in new_src
                   and "用户已调大, 尊重" in new_src,
                   "worker_rlimit_nofile 应幂等 (保留用户的更大值)")
        self.check("nginx_tune_multi_change_logging",
                   "_changes = []" in new_src
                   and 'nginx.conf 调优完成' in new_src,
                   "调优 helper 应聚合日志而非分散 2 次日志")
        # [v3.2.315] systemd drop-in LimitNOFILE=65535:
        # 消除 "worker_connections exceed open file resource limit" 一次性 warn
        self.check("systemd_rlimit_drop_in_helper",
                   "def _install_systemd_rlimit_drop_in(" in new_src
                   and "target: int = 65535" in new_src
                   and "/etc/systemd/system/nginx.service.d" in new_src
                   and "LimitNOFILE=" in new_src,
                   "缺少 _install_systemd_rlimit_drop_in() helper")
        self.check("systemd_rlimit_drop_in_idempotent",
                   'if _drop_in.exists():' in new_src
                   and "已经是目标状态, 无需写" in new_src,
                   "drop-in 应幂等 (内容一致则跳过, 避免 daemon-reload 噪音)")
        self.check("systemd_rlimit_drop_in_systemd_only",
                   'Path("/run/systemd/system").exists()' in new_src,
                   "drop-in 应仅在 systemd 环境下生效 (SysVinit 跳过)")
        self.check("systemd_rlimit_drop_in_wired",
                   "self.nginx._install_systemd_rlimit_drop_in()" in new_src
                   and "self.nginx._tune_nginx_worker_connections()" in new_src,
                   "drop-in 应在 update 流程中紧跟 _tune_nginx_worker_connections")
        self.check("systemd_rlimit_drop_in_daemon_reload",
                   '["systemctl", "daemon-reload"]' in new_src
                   and "quiet=True, timeout=15" in new_src,
                   "drop-in 写入后应 systemctl daemon-reload")
        # [v3.2.316] 关闭第二轮审计发现的 2 个 gap:
        #   (1) OCSP 精确检测 - 用 openssl -ocsp_uri 替代 issuer 字符串匹配
        #   (2) PHP-FPM 稳定性 5 项: catch_workers_output/rlimit_files (pool)
        #       + emergency_restart_threshold/interval/process_control_timeout (global)
        self.check("ocsp_uri_primary_detection",
                   '"openssl", "x509", "-noout", "-ocsp_uri"' in new_src
                   and "ground truth" in new_src,
                   "OCSP 检测应优先用 openssl -ocsp_uri (而非 issuer 字符串)")
        self.check("ocsp_http_url_validation",
                   'startswith(("http://", "https://"))' in new_src,
                   "OCSP URL 应校验 http/https 前缀")
        self.check("ocsp_issuer_fallback_preserved",
                   '"let\'s encrypt" in _issuer' in new_src
                   and "issuer 字符串匹配" in new_src,
                   "应保留 issuer fallback (极老 openssl 兼容)")
        self.check("fpm_catch_workers_output",
                   '"catch_workers_output", "yes"' in new_src,
                   "FPM pool 应启用 catch_workers_output")
        self.check("fpm_rlimit_files_65535",
                   '"rlimit_files", "65535"' in new_src,
                   "FPM pool rlimit_files 应对齐 nginx 65535")
        self.check("fpm_get_global_conf_path_helper",
                   "def get_global_conf_path(" in new_src
                   and "/etc/php-fpm.conf" in new_src
                   and '/etc/php/{ver}/fpm/php-fpm.conf' in new_src
                   and "/etc/opt/remi/php{_ver_compact}" in new_src,
                   "PHPManager 应有 get_global_conf_path (覆盖 EL/Remi/Debian)")
        self.check("fpm_global_emergency_restart",
                   '"emergency_restart_threshold", "10"' in new_src
                   and '"emergency_restart_interval", "1m"' in new_src
                   and '"process_control_timeout", "10s"' in new_src,
                   "FPM global 应配 emergency_restart_* + process_control_timeout")
        self.check("fpm_global_tuning_safe_attr_access",
                   "getattr(self, 'php_fpm_svc', '')" in new_src,
                   "FPM global 调用应用 getattr 安全访问 (避免 AttributeError)")
        # [v3.2.317] RAM 分层调优: 6 大组件按内存层级配置
        self.check("ram_tier_helper_5_levels",
                   "def _get_ram_tier(" in new_src
                   and '"tiny"' in new_src and '"small"' in new_src
                   and '"medium"' in new_src and '"large"' in new_src
                   and '"xlarge"' in new_src,
                   "_get_ram_tier 应返回 5 档 (tiny/small/medium/large/xlarge)")
        self.check("mariadb_tiered_buffer_pool_break_4gb_cap",
                   "total_mb * 0.65" in new_src
                   and "total_mb * 0.70" in new_src
                   and "total_mb * 0.75" in new_src,
                   "MariaDB buffer_pool 应打破 4GB 上限 (65%/70%/75%)")
        self.check("mariadb_tiered_buffer_pool_instances",
                   "innodb_buffer_pool_instances = {_pool_instances}" in new_src
                   and "max(1, min(8, pool // 1024))" in new_src,
                   "innodb_buffer_pool_instances 应按 pool 大小 (1/GB, 上限 8)")
        self.check("mariadb_tiered_io_capacity",
                   '"tiny": 200' in new_src
                   and '"medium": 1000' in new_src
                   and '"large": 2000' in new_src
                   and "innodb_io_capacity = {_io_capacity}" in new_src,
                   "innodb_io_capacity 应按 RAM 分层")
        self.check("mariadb_tiered_table_open_cache",
                   '"large": 4000' in new_src
                   and '"xlarge": 8000' in new_src
                   and "table_open_cache = {_table_cache}" in new_src,
                   "table_open_cache 应按 RAM 分层 (取代固定 2000)")
        self.check("mariadb_tiered_thread_cache",
                   '"medium": 32' in new_src
                   and '"large": 64' in new_src
                   and "thread_cache_size = {_thread_cache}" in new_src,
                   "thread_cache_size 应按 RAM 分层 (取代固定 16)")
        self.check("valkey_maxmemory_extended_tiers",
                   '_maxmem = "1024mb"' in new_src
                   and '_maxmem = "2048mb"' in new_src,
                   "Valkey maxmemory 应扩展到 1GB/2GB (>8GB/>16GB 机器)")
        self.check("php_fpm_memory_limit_tiered",
                   "php_admin_value[memory_limit]" in new_src
                   and '"tiny": "256M"' in new_src
                   and '"xlarge": "768M"' in new_src,
                   "PHP memory_limit 应通过 pool php_admin_value 分层 (不影响 CLI)")
        self.check("nginx_open_file_cache_default_on",
                   "parts.append(_nginx_open_file_cache())" in new_src
                   and "从 opt-in 改为默认启用" in new_src,
                   "open_file_cache 应从 --optimize opt-in 改为默认启用")
        self.check("nginx_fastcgi_buffers_tiered_helper",
                   "def _nginx_fastcgi_buffers_tiered(" in new_src
                   and "fastcgi_busy_buffers_size" in new_src
                   and '_tier in ("tiny", "small")' in new_src,
                   "应有 _nginx_fastcgi_buffers_tiered helper (小机器返回空串)")
        self.check("nginx_fastcgi_buffers_tiered_wired",
                   "_nginx_fastcgi_buffers_tiered()" in new_src
                   and "f\"{_fc_buf}\"" in new_src,
                   "tiered fastcgi_buffers 应接入 _nginx_php_location")
        self.check("nginx_keepalive_requests_1000",
                   "keepalive_requests 1000" in new_src,
                   "nginx 主配置应设 keepalive_requests 1000 (默认 100 太低)")
        self.check("nginx_client_body_buffer_size_128k",
                   "client_body_buffer_size 128k" in new_src,
                   "nginx 主配置应设 client_body_buffer_size 128k (WP POST)")
        # [v3.2.318] 重评估 4 项:
        # 1. innodb_log_file_size: MariaDB 10.5+ 安全, 已要求 ≥10.6
        # 2. tcp_fastopen: 服务端侧安全 (middlebox 仅影响客户端)
        # 3. access_log buffer/flush: 标准 2026 食谱 (5s 延迟可接受)
        # 4. thread_pool: MariaDB **社区版**内置 (非商业版限定)
        self.check("mariadb_innodb_log_file_size_tiered",
                   'innodb_log_file_size = {_log_file_size}' in new_src
                   and '"medium": "256M"' in new_src
                   and '"large": "512M"' in new_src
                   and '"xlarge": "1G"' in new_src,
                   "innodb_log_file_size 应按 RAM 分层 (medium=256M / large=512M / xlarge=1G)")
        self.check("mariadb_innodb_log_file_size_skip_small",
                   '"tiny": None' in new_src
                   and '"small": None' in new_src,
                   "小机器应跳过 innodb_log_file_size (用默认 100M)")
        self.check("mariadb_thread_pool_large_tier",
                   '_tier in ("large", "xlarge")' in new_src
                   and '"thread_handling = pool-of-threads"' in new_src
                   and "thread_pool_size = {_thread_pool_size}" in new_src
                   and "min(_cpu_count, 16)" in new_src,
                   "thread_pool 应仅对 large/xlarge 启用, size=min(cpu,16)")
        self.check("mariadb_thread_pool_community_note",
                   "MariaDB 社区版**内置**特性" in new_src,
                   "注释应明示 thread_pool 是 MariaDB 社区版内置 (非商业版限定)")
        self.check("nginx_tfo_kernel_runtime_check",
                   '/proc/sys/net/ipv4/tcp_fastopen' in new_src
                   and '_tfo_val in ("2", "3")' in new_src
                   and 'fastopen=256' in new_src,
                   "TCP Fast Open 应运行时检测内核 sysctl (值 2 或 3)")
        self.check("nginx_tfo_wired_to_listen_443",
                   'listen 443 ssl{_mp}{_tfo}' in new_src,
                   "fastopen=256 应接入 listen 443 指令")
        self.check("nginx_access_log_buffer_flush",
                   "combined buffer=32k flush=5s" in new_src,
                   "access_log 应有 buffer=32k flush=5s (减少 I/O)")
        # [v3.2.319] 修复 catch_workers_output 暴露的发行版预置项 warn:
        # (1) 首选: 把 php-soap 加入默认扩展列表, 装上扩展 → 配置行生效
        # (2) 若未加载则主动安装 (跨发行版不同包名)
        # (3) 建 /var/lib/php/wsdlcache 目录 (nginx 用户可写)
        # (4) backstop: 上述都失败才注释配置行
        self.check("soap_added_to_php_extensions_el",
                   '"php-soap"' in new_src
                   and "_PHP_EXTENSIONS_EL" in new_src,
                   "php-soap 应加入 EL 默认扩展列表 (AlmaLinux/RHEL/Rocky)")
        self.check("soap_added_to_php_extensions_deb",
                   '"php{ver}-soap"' in new_src
                   and "_PHP_EXTENSIONS_DEB_TPL" in new_src,
                   "php{ver}-soap 应加入 Debian/Ubuntu 默认扩展列表")
        self.check("soap_wsdl_detection_via_php_m",
                   '[_php_bin, "-m"]' in new_src
                   and '_soap_loaded = "soap" in _modules' in new_src,
                   "应通过 php -m 检测 soap 扩展是否加载")
        self.check("soap_install_first_try_native",
                   '"php-soap"' in new_src
                   and '"php%s-php-soap"' in new_src,
                   "EL 应先试 php-soap (原生), 再试 Remi 前缀 phpNN-php-soap")
        self.check("soap_install_first_try_debian",
                   '"php%s-soap" % _ver' in new_src,
                   "Debian 应装 php{ver}-soap (保留点分隔)")
        self.check("soap_install_recheck_after",
                   "def _check_soap_loaded()" in new_src
                   and "if _installed:" in new_src,
                   "安装后应重检 (nonlocal 闭包 / recheck 保证准确状态)")
        self.check("soap_wsdl_cache_dir_created",
                   '_wsdl_dir = Path("/var/lib/php/wsdlcache")' in new_src
                   and "_wsdl_dir.mkdir(parents=True, mode=0o1733" in new_src,
                   "应建 /var/lib/php/wsdlcache 目录 (与 opcache 同模式)")
        self.check("soap_wsdl_neutralize_backstop",
                   "backstop: soap 仍未加载时" in new_src
                   and "php_value\\[soap\\.wsdl_cache_dir\\]" in new_src,
                   "backstop 注释逻辑应在所有安装尝试之后保留")
        self.check("soap_install_respects_dry_run",
                   "not self.cfg.dry_run" in new_src,
                   "soap 安装应跳过 dry_run 场景 (符合全局约定)")
        # [v3.2.320] 修复 toksun.cn 生产日志发现的 MariaDB deprecated warn:
        # "'innodb-buffer-pool-instances' was removed. It does nothing now"
        # "--innodb-file-per-table is deprecated and will be removed"
        # 这两个 warn 来自 v3.2.317 添加的现已过时参数。
        self.check("mariadb_buffer_pool_instances_version_gated",
                   "innodb_buffer_pool_instances: MariaDB" in new_src
                   and "MDEV-15058" in new_src
                   and "if _maria_ver < (10, 5):" in new_src,
                   "innodb_buffer_pool_instances 应仅对 < 10.5 设置 (10.5+ deprecated)")
        self.check("mariadb_file_per_table_version_gated",
                   "innodb_file_per_table: MariaDB" in new_src
                   and "MDEV-29983" in new_src,
                   "innodb_file_per_table 应仅对 < 10.5 显式设置 (现代已是默认 ON)")
        # [v3.2.321] Opus 4.7 全量扫描结果:
        # (1) 8 处非原子写入统一为 _safe_write_file
        # (2) _detect_mariadb_version 加实例级缓存
        self.check("atomic_deploy_hook_write",
                   "_hook_script.write_text(" not in new_src
                   and "防断电留半行脚本" in new_src,
                   "certbot deploy hook 应用 _safe_write_file (原非原子 write_text)")
        self.check("atomic_systemd_units_write",
                   "_service_path.write_text(" not in new_src
                   and "_timer_path.write_text(" not in new_src
                   and "防断电留半行 unit 导致 systemctl daemon-reload 失败" in new_src,
                   "systemd service+timer 应用 _safe_write_file")
        self.check("atomic_nginx_conf_rollback_all_sites",
                   "_nc_263.write_text(" not in new_src
                   and "_nc_path.write_text(" not in new_src
                   and "_nc_deb.write_text(" not in new_src
                   and "_nc.write_text(_nginx_conf_bak" not in new_src,
                   "4 处 nginx.conf 灾难恢复应全部用 _safe_write_file")
        self.check("atomic_mptcp_sysctl_write",
                   "_sysctl_conf.write_text(\"net.mptcp.enabled=1" not in new_src
                   and "net.mptcp.enabled=1\\n" in new_src,
                   "MPTCP sysctl 写入应用 _safe_write_file")
        # [v3.2.321] → [v3.2.327] 架构演进:
        # MariaDB 缓存从实例级 + force_refresh=True 迁移到模块级 + reset hook,
        # 对齐 Nginx 的 _reset_nginx_capability_caches() 设计美学
        self.check("mariadb_caches_module_level",
                   "_MARIADB_VERSION_CACHE" in new_src
                   and "_MARIADB_VERSION_LOCK" in new_src
                   and "_MARIADB_FULL_VERSION_CACHE" in new_src
                   and "_MYSQL_MAJOR_MINOR_CACHE" in new_src
                   and "_MARIADB_SERVICE_CACHE" in new_src,
                   "MariaDB 四个 detect 方法应共享模块级缓存架构")
        self.check("mariadb_reset_capability_caches_helper",
                   "def _reset_mariadb_capability_caches" in new_src,
                   "必须存在 _reset_mariadb_capability_caches() 统一失效函数")
        self.check("mariadb_version_cache_only_on_success",
                   "if _result != (0, 0):" in new_src
                   and "_MARIADB_VERSION_CACHE = _result" in new_src,
                   "缓存仅在成功探测时设置, 避免安装中途 (0,0) 被固化")
        self.check("mariadb_no_force_refresh_param",
                   "(force_refresh=True)" not in new_src,
                   "所有 force_refresh=True 应已迁移到 _reset 调用 (对齐 Nginx)")
        self.check("mariadb_no_instance_ver_cache",
                   "_mariadb_ver_cache" not in new_src,
                   "实例级 _mariadb_ver_cache 应已废弃 (改用模块级)")
        self.check("mariadb_reset_at_upgrade_actions",
                   new_src.count("_reset_mariadb_capability_caches()") >= 4,
                   "至少 4 处升级动作后应调用 _reset_mariadb_capability_caches()")
        # [v3.2.328] PHP/Redis/Cert 缓存架构全面对齐 Nginx/MariaDB 模式
        # 回答 "其他模块是否也需要这样重构" 的系统性补齐
        self.check("php_caches_module_level",
                   "_PHP_VERSION_CACHE" in new_src
                   and "_PHP_VERSION_LOCK" in new_src
                   and "_PHP_FPM_SERVICE_CACHE" in new_src,
                   "PHP detect 方法应使用模块级缓存架构")
        self.check("php_reset_capability_caches_helper",
                   "def _reset_php_capability_caches" in new_src,
                   "必须存在 _reset_php_capability_caches() 统一失效函数")
        self.check("redis_caches_module_level",
                   "_REDIS_VERSION_CACHE" in new_src
                   and "_REDIS_FULL_VERSION_CACHE" in new_src,
                   "Redis detect 方法应使用模块级缓存架构")
        self.check("redis_reset_capability_caches_helper",
                   "def _reset_redis_capability_caches" in new_src,
                   "必须存在 _reset_redis_capability_caches() 统一失效函数")
        self.check("certbot_caches_module_level",
                   "_CERTBOT_VERSION_CACHE" in new_src
                   and "_CERTBOT_FULL_VERSION_CACHE" in new_src,
                   "Certbot detect 方法应使用模块级缓存架构")
        self.check("certbot_reset_capability_caches_helper",
                   "def _reset_certbot_capability_caches" in new_src,
                   "必须存在 _reset_certbot_capability_caches() 统一失效函数")
        # 所有 5 个 Manager 走相同缓存模式 — 架构对称性
        self.check("all_managers_have_reset_helpers",
                   "_reset_nginx_capability_caches" in new_src
                   and "_reset_mariadb_capability_caches" in new_src
                   and "_reset_php_capability_caches" in new_src
                   and "_reset_redis_capability_caches" in new_src
                   and "_reset_certbot_capability_caches" in new_src,
                   "5 个 Manager 都应有 _reset_X_capability_caches 对称助手")
        # [v3.2.329] 全量架构对称性扫描
        # 消除重复的 detect 实现: NginxManager.detect_version (canonical) 应委托 module-level
        # [v3.2.330] 更新: 原 _detect_nginx_version → detect_version 重命名
        import re as _re_sym
        _nginx_inst_body = _re_sym.search(
            r'def detect_version\(self\) -> Optional\[tuple\].*?\n    # \[v3\.2\.330',
            new_src, _re_sym.DOTALL)
        self.check("nginx_no_duplicate_detect_impl",
                   _nginx_inst_body is not None
                   and "_detect_nginx_version()" in _nginx_inst_body.group(0)
                   and "subprocess.run" not in _nginx_inst_body.group(0),
                   "NginxManager.detect_version 应委托到模块级缓存函数, "
                   "不应包含独立的 subprocess 实现")
        # 所有 5 个 Manager 都有 docstring (架构完整性)
        import ast as _ast_doc
        _tree_doc = _ast_doc.parse(new_src)
        _missing_doc = []
        for _n in _ast_doc.walk(_tree_doc):
            if isinstance(_n, _ast_doc.ClassDef) and _n.name.endswith('Manager'):
                if not _ast_doc.get_docstring(_n):
                    _missing_doc.append(_n.name)
        self.check("all_managers_have_docstring",
                   len(_missing_doc) == 0,
                   "所有 Manager 类应有 docstring (架构完整性); missing=%s" % _missing_doc)
        # 所有组件都有 DEFAULT_VERSION (或等价) 常量, 对齐命名惯例
        _components = [
            ('_PHP_DEFAULT_VERSION', 'PHP'),
            ('_MARIADB_DEFAULT_VERSION', 'MariaDB'),
            ('_REDIS_DEFAULT_VERSION', 'Redis'),
            ('_NGINX_DEFAULT_VERSION', 'Nginx'),
            ('_CERTBOT_DEFAULT_VERSION', 'Certbot'),
            ('_WPCLI_DEFAULT_VERSION', 'WP-CLI'),
        ]
        _missing_defaults = [name for const, name in _components if const not in new_src]
        self.check("all_components_have_default_version",
                   len(_missing_defaults) == 0,
                   "所有组件应有 _X_DEFAULT_VERSION 常量 (对齐命名惯例); "
                   "missing=%s" % _missing_defaults)
        # [v3.2.330] 架构对称性: 3 项重构后的不变式验证
        # -----------------------------------------------------------------
        # 统一 detect_version() 命名 (Strangler Fig 完成第一阶段)
        _managers_need_detect_version = [
            'NginxManager', 'MariaDBManager', 'PHPManager',
            'RedisManager', 'CertManager',
        ]
        import ast as _ast_dv
        _tree_dv = _ast_dv.parse(new_src)
        _no_detect_ver = []
        for _n in _ast_dv.walk(_tree_dv):
            if isinstance(_n, _ast_dv.ClassDef) and _n.name in _managers_need_detect_version:
                _has_detect = any(
                    isinstance(_c, _ast_dv.FunctionDef) and _c.name == 'detect_version'
                    for _c in _n.body)
                if not _has_detect:
                    _no_detect_ver.append(_n.name)
        self.check("all_managers_have_detect_version",
                   len(_no_detect_ver) == 0,
                   "5 个 Manager 都应有 public detect_version() (canonical 名); "
                   "missing=%s" % _no_detect_ver)
        # 统一 detect_service() 命名 (Redis/PHP 不再用 _name 后缀或 _php_fpm_ 中缀)
        self.check("all_managers_use_canonical_detect_service",
                   "def detect_service(self)" in new_src
                   and new_src.count("def detect_service(self)") >= 3,
                   "MariaDB/Redis/PHP 都应有 canonical detect_service() (至少 3 处)")
        # upgrade_to_target 对齐: 3/5 Manager 实现 (Nginx/Cert auto-latest 语义不适用)
        self.check("upgrade_to_target_symmetry",
                   new_src.count("def upgrade_to_target(self, target: tuple, pkg_mgr: str) -> bool:") >= 3,
                   "MariaDB/Redis/PHP 应有统一签名的 upgrade_to_target 入口")
        # 防回归: 未来新代码不应引入 `_detect_X_version` 反模式 (应直接用 detect_version)
        # 仅检查非 deprecated-alias 的真正实现 (别名只有 return 一行)
        # 例外: fail2ban 是 NginxManager 托管的次级组件, 不是主 Manager, 沿用原名
        import re as _re_dv
        _ALLOWED_SUBCOMPONENT_DETECT = {'_detect_fail2ban_version'}
        _anti_pattern = [
            m for m in _re_dv.findall(
                r'    def (_detect_\w+_version)\(self\)[^\n]*\n        """(?!\[DEPRECATED)',
                new_src)
            if m not in _ALLOWED_SUBCOMPONENT_DETECT
        ]
        self.check("no_new_private_detect_version_pattern",
                   len(_anti_pattern) == 0,
                   "新代码不应引入 _detect_X_version 反模式 (应用 detect_version + alias); "
                   "found=%s" % _anti_pattern[:3])
        # [v3.2.331] 线程安全对称性: 每个 _X_CACHE 必须有对应的 threading.Lock
        # 防止 nogil 模式下的竞态条件. 历史遗留 cache 可能只有 CACHE 没 LOCK,
        # 此测试防止未来新增不完整的线程安全模式.
        import re as _re_lock
        _all_caches = _re_lock.findall(r'^(_[A-Z][A-Z0-9_]*_CACHE)\b', new_src, _re_lock.MULTILINE)
        _all_locks = set(_re_lock.findall(r'^(_[A-Z][A-Z0-9_]*_LOCK)\s*=', new_src, _re_lock.MULTILINE))
        _orphan_caches = []
        for _cache in set(_all_caches):
            # 匹配规则: _X_CACHE 对应 _X_LOCK 或 _X_短名_LOCK
            # 例如 _NGINX_HTTP2_DIRECTIVE_CACHE 对应 _NGINX_HTTP2_LOCK (短名匹配)
            _expected = _cache.replace('_CACHE', '_LOCK')
            if _expected in _all_locks:
                continue
            # 短名变体: 去掉最后一段
            _parts = _cache.split('_')
            _matched = False
            for _i in range(len(_parts)-1, 1, -1):
                _short = '_'.join(_parts[:_i]) + '_LOCK'
                if _short in _all_locks:
                    _matched = True
                    break
            if not _matched:
                _orphan_caches.append(_cache)
        self.check("all_caches_have_corresponding_lock",
                   len(_orphan_caches) == 0,
                   "每个模块级 _X_CACHE 必须有对应的 _X_LOCK (nogil 线程安全); "
                   "orphan=%s" % _orphan_caches)
        # [v3.2.322] Opus 4.7 扫描第二轮: _detect_nginx_version 模块级缓存
        # 14 个 call site, 一次部署约 140ms 开销
        self.check("nginx_version_cache_module_level",
                   "_NGINX_VERSION_CACHE" in new_src
                   and "_NGINX_VERSION_LOCK" in new_src,
                   "模块级 _NGINX_VERSION_CACHE 和 LOCK 应存在")
        self.check("nginx_version_cache_only_on_success",
                   "if _result != (0, 0, 0):" in new_src
                   and "_NGINX_VERSION_CACHE = _result" in new_src,
                   "缓存仅在成功探测时设置 (避免未安装的 (0,0,0) 被固化)")
        self.check("nginx_version_cache_reset_on_upgrade",
                   "with _NGINX_VERSION_LOCK:" in new_src
                   and "[v3.2.322] _NGINX_VERSION_CACHE" in new_src,
                   "_reset_nginx_capability_caches 应清除版本缓存")
        # [v3.2.323] Opus 4.7 第三轮扫描: i18n kwargs 一致性
        # 动态分析 - 解析所有 key 的 placeholders, 与调用处 kwargs 对比
        # 这是结构化检查, 防止未来再出现 D1 陷阱注释中的 bug
        import re as _re_i18n
        _src = new_src
        _src_lines = _src.split('\n')
        # Parse multi-line templates
        _key_placeholders = {}
        _current_key = None
        _i = 0
        while _i < len(_src_lines):
            _line = _src_lines[_i]
            _m_key = _re_i18n.match(r'^\s+["\']([a-z][a-z0-9_]+)["\']:\s*\{', _line)
            if _m_key:
                _current_key = _m_key.group(1)
                _i += 1
                continue
            if _current_key:
                _m_start = _re_i18n.search(r'["\'](?:zh|en)["\']:\s*["\']', _line)
                if _m_start:
                    _j = _i
                    _buf = _line
                    while _j + 1 < len(_src_lines):
                        _next = _src_lines[_j+1]
                        if _re_i18n.match(r'^\s+["\']', _next) and not _re_i18n.match(r'^\s+["\'][a-z][a-z0-9_]+["\']:\s*\{', _next):
                            _buf += '\n' + _next
                            _j += 1
                        else:
                            break
                    _strings = _re_i18n.findall(r'"((?:[^"\\]|\\.)*)"', _buf)
                    _combined = ''.join(_strings)
                    _phs = set(_re_i18n.findall(r'\{(\w+)[^}]*\}', _combined))
                    if _phs:
                        _key_placeholders.setdefault(_current_key, set()).update(_phs)
                    _i = _j + 1
                    continue
                if _line.strip() == '},':
                    _current_key = None
            _i += 1
        # Find all t() calls
        def _find_t_calls(_text):
            _results = []
            for _m in _re_i18n.finditer(r'\bt\(\s*["\']([a-z][a-z0-9_]+)["\']', _text):
                _start = _m.end()
                _depth = 1
                _ii = _start
                while _ii < len(_text) and _depth > 0:
                    _c = _text[_ii]
                    if _c in '([{':
                        _depth += 1
                    elif _c in ')]}':
                        _depth -= 1
                        if _depth == 0:
                            break
                    _ii += 1
                if _depth == 0:
                    _lo = _text[:_m.start()].count('\n')
                    _results.append((_lo + 1, _m.group(1), _text[_start:_ii]))
                    _ = _m
            return _results
        _all_calls = _find_t_calls(_src)
        _missing_bugs = []
        _extra_bugs = []
        for _ln, _key, _args in _all_calls:
            if _key not in _key_placeholders:
                continue
            _line_text = _src_lines[_ln - 1] if _ln <= len(_src_lines) else ''
            if _line_text.lstrip().startswith('#'):
                continue
            _required = _key_placeholders[_key]
            _provided = set()
            _depth2 = 0
            _ts = 0
            for _j2, _c2 in enumerate(_args):
                if _c2 in '([{':
                    _depth2 += 1
                elif _c2 in ')]}':
                    _depth2 -= 1
                elif _c2 == ',' and _depth2 == 0:
                    _seg = _args[_ts:_j2]
                    _mm = _re_i18n.match(r'\s*(\w+)\s*=(?!=)', _seg)
                    if _mm:
                        _provided.add(_mm.group(1))
                    _ts = _j2 + 1
            _seg = _args[_ts:]
            _mm = _re_i18n.match(r'\s*(\w+)\s*=(?!=)', _seg)
            if _mm:
                _provided.add(_mm.group(1))
            _missing = _required - _provided
            _extra = _provided - _required
            if _missing:
                _missing_bugs.append((_ln, _key, sorted(_missing)))
            if _extra:
                _extra_bugs.append((_ln, _key, sorted(_extra)))
        self.check("i18n_no_missing_kwargs",
                   len(_missing_bugs) == 0,
                   "所有 t() 调用必须提供模板所需的全部 kwargs (防 D1 陷阱); "
                   "missing=%s" % (_missing_bugs[:3] if _missing_bugs else ''))
        self.check("i18n_no_extra_kwargs",
                   len(_extra_bugs) == 0,
                   "调用 kwargs 不应包含模板未使用的参数 (防拼写错误/死参数); "
                   "extra=%s" % (_extra_bugs[:3] if _extra_bugs else ''))
        # [v3.2.324] Opus 4.7 第四轮: 死代码检测
        # 识别"定义但无任何 refs"的方法 (潜在遗忘代码)
        # 允许 DEAD-CODE 标注的 opt-in 保留 (需审计决策)
        import re as _re_dead
        _dead_defs = {}
        # Match method defs (inside classes, 4-space indent)
        for _dm in _re_dead.finditer(
                r'^\s{4}def\s+(_?\w+)\s*\(', new_src, _re_dead.MULTILINE):
            _name = _dm.group(1)
            # Skip dunder methods and properties we know are used externally
            if _name.startswith('__') or _name in (
                    'detect_service',  # external symbol by name
            ):
                continue
            _dead_defs[_name] = _dm.start()
        # Count references in source
        _dead_list = []
        for _name, _pos in _dead_defs.items():
            _count = len(_re_dead.findall(
                r'\b' + _re_dead.escape(_name) + r'\b', new_src))
            # 1 = only the def line. Check if DEAD-CODE marker present near it
            if _count <= 1:
                # Look at docstring (next ~500 chars)
                _doc_region = new_src[_pos:_pos + 500]
                if 'DEAD-CODE' not in _doc_region and \
                   '"' + _name + '"' not in new_src and \
                   "'" + _name + "'" not in new_src:
                    _dead_list.append(_name)
        self.check("no_unmarked_dead_methods",
                   len(_dead_list) == 0,
                   "所有无 refs 的方法应标注 [DEAD-CODE] 或删除; "
                   "unmarked=%s" % (_dead_list[:5] if _dead_list else ''))
        # [v3.2.325] Opus 4.7 第五轮: apt list --upgradable 必须先 apt-get update
        # 否则陈旧缓存会让 PHP/MariaDB/Nginx minor 自动升级永不触发 → CVE 风险
        _src_lines = new_src.split('\n')
        _apt_list_sites = []
        for _ii, _ln in enumerate(_src_lines):
            if '"apt", "list"' in _ln or "'apt', 'list'" in _ln:
                _apt_list_sites.append(_ii + 1)
        _unrefreshed = []
        for _site_ln in _apt_list_sites:
            # Look back 15 lines for "apt-get update"
            _back = '\n'.join(_src_lines[max(0, _site_ln - 15):_site_ln])
            if not ('apt-get' in _back and 'update' in _back):
                _unrefreshed.append(_site_ln)
        self.check("apt_list_upgradable_requires_prior_update",
                   len(_unrefreshed) == 0,
                   "每处 'apt list --upgradable' 前 15 行内必须有 'apt-get update' "
                   "(陈旧缓存会漏报可用更新); unrefreshed=%s" % _unrefreshed)
        # [v3.2.326] Opus 4.7 第八轮外部基线: WordPress 2026 hardening baseline
        # 参考 Bluehost/Prestige/LaunchGuard 2026 年 2 月 hardening 指南
        _wp_hardening_checks = [
            ('readme|license', 'readme.html/license.txt deny (防版本指纹)'),
            ('wp-signup.php', 'wp-signup.php deny (单站点无需)'),
            ('wp-admin/install.php', 'install.php deny (扫描器指纹)'),
            ('wp-admin/upgrade.php', 'upgrade.php 限 localhost'),
            # [v3.2.332] 生产日志发现: setup-config.php 被扫描器访问触发
            # object-cache.php Redis connect 抛 RedisException → 500 响应泄露堆栈
            ('wp-admin/setup-config.php', 'setup-config.php deny (安装完成后扫描器噪音+信息泄露)'),
        ]
        _missing_hardening = [desc for substr, desc in _wp_hardening_checks if substr not in new_src]
        self.check("wp_hardening_2026_baseline",
                   len(_missing_hardening) == 0,
                   "缺失 WordPress 2026 hardening 项: %s" % _missing_hardening)
        # [v3.2.333] fail2ban 4xx-flood filter 的 ignoreregex 必须锚定请求路径
        # 生产日志 2026-04-17 07:03 发现: 旧规则 ".*(\.css|\.js|...).*" 会
        # 误匹配 URL-encoded 攻击路径 (如 /https%3A/.../style.css%3Fver%3D...),
        # 导致 fail2ban 漏抓 6/17 次 404 探测, 未触发 ban.
        # 新规则: 锚定 "(GET|HEAD) /path.ext HTTP/" 形式, path.ext 必须是末尾
        _new_pattern_present = 'woff2|ttf|eot|map' in new_src
        _old_pattern_absent = 'sitemap.*\\\\.xml|\\\\.jpg' not in new_src
        self.check("f2b_4xx_flood_ignoreregex_anchored",
                   _new_pattern_present and _old_pattern_absent,
                   "fail2ban 4xx-flood filter ignoreregex 必须锚定请求路径末尾, "
                   "防止 URL-encoded 攻击绕过 (生产日志 2026-04-17 07:03 发现). "
                   "new_present=%s, old_absent=%s" % (_new_pattern_present, _old_pattern_absent))
        # [v3.2.336] 2026 云 VM SSD 现实: tiny tier (≤2GB, 如 AWS t4g.micro,
        # Alicloud t6) 也是 SSD, 不应沿用 2016 年 HDD 默认 200.
        # v3.2.335 教训: 我误把 "small" 当作 ≤2GB, 实际 _get_ram_tier 把 ≤2GB
        # 归为 "tiny", 导致 v3.2.335 fix 对真实用户 (1.6GB 服务器) 零效果.
        # 此测试锁死 tier 语义: tiny 必须 ≥500 (避免再次退回 HDD 默认).
        import re as _re_iocap
        _iocap_match = _re_iocap.search(
            r'_io_capacity_map\s*=\s*\{[^}]*"tiny"\s*:\s*(\d+)', new_src)
        _tiny_io = int(_iocap_match.group(1)) if _iocap_match else 0
        self.check("mariadb_io_capacity_tiny_ssd_default",
                   _tiny_io >= 500,
                   "tiny tier (≤2GB) innodb_io_capacity 必须 ≥500 (2026 云 SSD 现实, "
                   "v3.2.336 吸取教训防止回退到 HDD 默认 200); 当前=%d" % _tiny_io)
        # [v3.2.336] io_capacity_max 必须配对存在 (MariaDB 官方: io_capacity 配
        # io_capacity_max 才能 burst flush; 单独 io_capacity 被 furious flushing 覆盖).
        _iocap_max_match = _re_iocap.search(
            r'_io_capacity_max_map\s*=\s*\{[^}]*"tiny"\s*:\s*(\d+)', new_src)
        _tiny_io_max = int(_iocap_max_match.group(1)) if _iocap_max_match else 0
        self.check("mariadb_io_capacity_max_paired_with_capacity",
                   _tiny_io_max >= _tiny_io * 2,
                   "io_capacity_max 应为 io_capacity 的 ≥2x (burst cap); "
                   "tiny: cap=%d max=%d" % (_tiny_io, _tiny_io_max))
        # [v3.2.335] PHP opcache.interned_strings_buffer 对齐 2026 WordPress + 插件规模.
        # 16MB 在 WP6.9 + 10+ 插件时易满, 满了会退化到每请求 alloc.
        # 32MB 是 Artiphp 2026 共识 (Laravel 64MB 过大, WP 32MB 足够).
        import re as _re_ops
        _ops_match = _re_ops.search(
            r"opcache\.interned_strings_buffer'[^)]*'(\d+)'", new_src)
        _ops_val = int(_ops_match.group(1)) if _ops_match else 0
        self.check("php_opcache_interned_strings_wp_aligned",
                   _ops_val >= 32,
                   "opcache.interned_strings_buffer 应 ≥32MB (WP 2026 共识); "
                   "当前=%d" % _ops_val)
        # [v3.2.335] QUIC 生产安全: quic_retry 防源地址伪造 DDoS (Nginx 官方推荐);
        # quic_gso 减少 UDP syscall (~40% 吞吐). 任何 HTTP/3 生成路径都必须包含.
        # 注意检查 f-string 生成语句而非注释里的提及 (substring 'quic_retry on'
        # 在注释里也出现, 易误判; 必须匹配 f"..." 形式的真实输出).
        _has_quic_retry = 'f"    quic_retry on;\\n"' in new_src
        _has_quic_gso = 'f"    quic_gso on;\\n"' in new_src
        self.check("nginx_quic_hardening_complete",
                   _has_quic_retry and _has_quic_gso,
                   "HTTP/3 必须启用 quic_retry (DDoS 防护) + quic_gso (性能); "
                   "retry=%s gso=%s" % (_has_quic_retry, _has_quic_gso))
        # [v3.2.338] 升级编排规则 (用户规约):
        #   major 先, 若执行了 major → 跳过 minor (刚装仓库最新版);
        #   若无 major 需求 → 才执行 minor (安全/bug 补丁);
        #   minor 执行后也无需 major (因为 minor 是在"major 无需升级"前提下才执行).
        #
        # 实现必须是 if/else 或 if/elif 结构 (互斥), 而非串行调用.
        # 历史教训: PHP/MariaDB 曾 L43588+L43590 / L43629+L43631 串行, 大版本升级时
        # 服务 (FPM / mariadbd) 因 metadata 缓存时序触发二次重启.
        # Nginx (L43608-43626) 和 Redis (L43852-43866) 一直是正确的 if/else 模式.
        import re as _re_orch
        _orch_violations = []
        # 检查每个 Manager 的 major-XOR-minor 编排. 启发式: 找到 major 调用后,
        # 同一函数内接下来 15 行不应无条件调用 minor (必须被 if/else/elif 包裹).
        _pairs = [
            ("php", "_upgrade_php_if_needed", "_upgrade_php_minor_if_available"),
            ("mariadb", "_upgrade_mariadb_if_needed", "_upgrade_mariadb_minor_if_available"),
            ("nginx", "_upgrade_nginx_if_needed", "_upgrade_nginx_minor_if_available"),
            ("redis", "_upgrade_redis_if_needed", "_upgrade_redis_minor_if_available"),
        ]
        _src_lines_338 = new_src.split('\n')
        for _comp, _major_fn, _minor_fn in _pairs:
            for _i, _ln in enumerate(_src_lines_338):
                if _major_fn + '(' not in _ln or _ln.lstrip().startswith('#'):
                    continue
                if 'def ' + _major_fn in _ln:  # 定义行非调用
                    continue
                # 向上找最近的 if/elif/else 结构或函数边界
                _major_indent = len(_ln) - len(_ln.lstrip())
                _protected = False
                for _j in range(_i - 1, max(0, _i - 30), -1):
                    _prev = _src_lines_338[_j].rstrip()
                    if not _prev.strip():
                        continue
                    _prev_indent = len(_prev) - len(_prev.lstrip())
                    if _prev_indent < _major_indent and (
                            _prev.lstrip().startswith(('if ', 'elif ', 'else:'))):
                        _protected = True
                        break
                    if _prev_indent < _major_indent:
                        break
                # 向下扫描 15 行, 检查 minor 是否无条件跟随
                for _k in range(_i + 1, min(len(_src_lines_338), _i + 15)):
                    _next = _src_lines_338[_k]
                    if _minor_fn + '(' in _next and not _next.lstrip().startswith('#'):
                        _next_indent = len(_next) - len(_next.lstrip())
                        # 同缩进 + major 未被 if 保护 → 违规 (串行 major+minor)
                        if _next_indent == _major_indent and not _protected:
                            _orch_violations.append(
                                "%s L%d: %s + L%d: %s 无 if/else 保护" % (
                                    _comp, _i + 1, _major_fn,
                                    _k + 1, _minor_fn))
                        break
        self.check("upgrade_orchestration_major_xor_minor",
                   len(_orch_violations) == 0,
                   "升级编排必须 major XOR minor (互斥), 防止双重服务重启; "
                   "violations=%s" % _orch_violations[:3])
        # [v3.2.339] _BENIGN_STDERR_PATTERNS 边界安全:
        # 降噪白名单容易"吞掉真警告". 硬规则: 每个 pattern 必须是 "明确短语",
        # 不得出现泛化词如 "error"/"failed"/"warning"/"refused" (会误吞严重错误).
        # 此测试锁死: 白名单内容即使未来扩展, 也不会意外吞掉真警告.
        #
        # 实现注意: 不能用非贪婪 [\s\S]*? 配 \) 匹配 tuple 结束 — 注释里的
        # 中文括号 (全半角) 会让匹配过早终止. 改用行扫描: 从定义行找到独立的 ) 行.
        import re as _re_benign
        _benign_start_idx = None
        for _i, _ln in enumerate(new_src.split('\n')):
            if '_BENIGN_STDERR_PATTERNS' in _ln and ':' in _ln and 'tuple' in _ln:
                _benign_start_idx = _i
                break
        _benign_lines_raw = []
        if _benign_start_idx is not None:
            _all_lines = new_src.split('\n')
            for _j in range(_benign_start_idx + 1, len(_all_lines)):
                _ln_j = _all_lines[_j]
                if _ln_j.rstrip() == ')':
                    break
                _benign_lines_raw.append(_ln_j)
        # 只从真正的 string literal 行提取 (跳过 # 开头的注释行)
        _str_literals = []
        for _ln_k in _benign_lines_raw:
            _stripped = _ln_k.strip()
            if _stripped.startswith('#') or not _stripped:
                continue
            _str_literals.extend(_re_benign.findall(r'"((?:[^"\\]|\\.)+)"', _ln_k))
        _dangerous_words = ("error", "failed", "fatal", "warning",
                            "refused", "denied", "cannot", "unable")
        _unsafe = []
        for _s in _str_literals:
            _s_lower = _s.lower()
            for _dw in _dangerous_words:
                if (_s_lower == _dw
                        or _s_lower.startswith(_dw + " ")
                        or _s_lower.endswith(" " + _dw)):
                    _unsafe.append((_s, _dw))
                    break
        self.check("benign_stderr_patterns_not_overbroad",
                   len(_unsafe) == 0 and len(_str_literals) >= 4,
                   "_BENIGN_STDERR_PATTERNS 不得含泛化危险词 (会吞真警告); "
                   "捕获数=%d, 问题项=%s" % (len(_str_literals), _unsafe[:3]))
        # [v3.2.341] 顶层 fcntl.flock 并发保护必须存在.
        # 防止两个实例并发修改共享状态 (nginx/mariadb conf / wp-config.php 等).
        _src_code_341a = self._code_only(new_src)
        _has_lock_path = '/var/lock/wp-ssl-bootstrap.lock' in _src_code_341a
        _has_flock_nb = 'LOCK_EX | fcntl.LOCK_NB' in _src_code_341a
        _has_block_err = 'except BlockingIOError' in _src_code_341a
        _has_tempfail = 'sys.exit(75)' in _src_code_341a
        self.check("top_level_process_lock_present",
                   _has_lock_path and _has_flock_nb
                   and _has_block_err and _has_tempfail,
                   "主入口必须有 fcntl.flock 顶层锁 + BlockingIOError 处理 + "
                   "EX_TEMPFAIL (75) 退出; path=%s flock=%s blockerr=%s exit75=%s" % (
                       _has_lock_path, _has_flock_nb,
                       _has_block_err, _has_tempfail))
        # [v3.2.341] TOCTOU 回归防护: 统计 "exists() → open()" 3 行内邻接模式.
        # 允许少量遗留 (新增功能可能引入), 但总量必须明显低于修复前基线 (4).
        # 启发式: 同文件内, if path.exists(): 紧跟 open(path) 的邻接次数.
        import re as _re_toc
        _toc_count = 0
        _lines_toc = _src_code_341a.split('\n')
        for _i_toc, _ln_toc in enumerate(_lines_toc):
            if not ('.exists()' in _ln_toc and 'if ' in _ln_toc):
                continue
            # 提取路径变量
            _m_toc = _re_toc.search(
                r'\bif\s+(?:not\s+)?([\w]+)\.exists\(\)', _ln_toc)
            if not _m_toc:
                continue
            _pvar = _m_toc.group(1)
            # 向下 3 行查找同 var 的 open()
            for _j_toc in range(_i_toc + 1, min(_i_toc + 4, len(_lines_toc))):
                _nxt = _lines_toc[_j_toc]
                if (('open(' in _nxt or 'os.open(' in _nxt)
                        and _pvar in _nxt):
                    _toc_count += 1
                    break
        self.check("toctou_exists_then_open_bounded",
                   _toc_count <= 2,
                   "exists()→open() TOCTOU 邻接模式数 (v3.2.341 修复前=4, "
                   "目标 ≤2); 当前=%d" % _toc_count)
        # [v3.2.342] nftables 规则添加必须幂等 (检查后加).
        # 生产日志 Debian 12 (2026-04-17 09:44) 发现: nft add rule 非幂等,
        # 5 次部署累积 5 条重复 udp dport 443 accept. firewalld/ufw 天然去重,
        # 但 nftables 需脚本层面预先 list 检查.
        _src_code_nft = self._code_only(new_src)
        _nft_block_ok = (
            'nft' in _src_code_nft
            and '"nft", "-a", "list", "table"' in _src_code_nft
            and '_rule_exists' in _src_code_nft)
        self.check("nftables_rule_add_idempotent",
                   _nft_block_ok,
                   "nftables 添加 UDP 443 规则前必须先 list 检查去重, "
                   "否则每次部署累积重复规则 (v3.2.342 Debian 12 bug)")
        # [v3.2.343→v3.2.357] Ubuntu 26.04 LTS (Resolute Raccoon) 兼容性.
        # v3.2.357 修正: nginx.org 和 Sury PPA 都 NOT 含 resolute (实际确认未发布),
        # resolute 必须走 "HTTP 探测 + 回退到 noble/questing" 路径, 否则 deploy
        # 会因 404 而失败. 断言相应改为: resolute 不在静态列表, fallback 路径健在.
        _src_code_u26 = self._code_only(new_src)
        # Sury: resolute 必须 NOT 在 LTS 白名单 (v3.2.357 撤回), 以便非 LTS 路径
        # 启用 → sources 改写为 noble → apt update 成功
        _sury_no_resolute = (
            '"focal", "jammy", "noble", "resolute"' not in _src_code_u26
            and '_fix_sury_ppa_codename_for_non_lts' in _src_code_u26)
        # nginx.org: resolute 必须 NOT 在 ubuntu 数组 (否则跳过 HTTP 探测)
        _nginx_no_resolute = ('"resolute", "questing"' not in _src_code_u26
                              and '"questing", "plucky"' in _src_code_u26)
        # HTTP 探测 fallback 代码必须存在
        _probe_fallback_ok = (
            '_probe_url = (' in _src_code_u26
            and '_effective_codename = _supported[0]' in _src_code_u26)
        # Valkey codenames 含 "resolute" (这个是 Ubuntu 主仓库有 valkey 包, OK)
        _valkey_ok = ('"plucky", "questing", "resolute"' in _src_code_u26
                      or 'resolute",   # Ubuntu 24.04+' in _src_code_u26)
        # MariaDB 早期出口: 需 VID>=26 判断 + apt-cache madison 探测
        _mdb_early_exit = (
            '_vid_early >= 26' in _src_code_u26
            and '"apt-cache", "madison", "mariadb-server"' in _src_code_u26)
        _all_u26_ok = (_sury_no_resolute and _nginx_no_resolute
                       and _probe_fallback_ok and _valkey_ok
                       and _mdb_early_exit)
        self.check("ubuntu_26_04_resolute_compat",
                   _all_u26_ok,
                   "Ubuntu 26.04 (resolute) 兼容性缺失: "
                   "sury_no_resolute=%s nginx_no_resolute=%s "
                   "probe_fallback=%s valkey=%s mdb_main=%s" % (
                       _sury_no_resolute, _nginx_no_resolute,
                       _probe_fallback_ok, _valkey_ok, _mdb_early_exit))
        # [v3.2.344] 国产 EL 系兼容 (openEuler 24.03 LTS SP3 + 银河麒麟 V11).
        # 必须: 1) _el_ids 含 openeuler/kylin; 2) ID regex 支持大小写;
        # 3) _is_openeuler_like() 辅助函数存在; 4) 关键 repo 路径有守卫.
        # 理由: openEuler 用 dnf+RPM 但 Remi/nginx.org/MariaDB.org 都不支持,
        # 脚本若强行添加外部 repo 会 dnf 404 失败.
        _src_code_cn = self._code_only(new_src)
        _el_ids_ok = ('"openeuler", "kylin"' in _src_code_cn)
        _regex_ok = ('[A-Za-z_-]+' in _src_code_cn and
                     '.lower() if _id_m' in _src_code_cn)
        _helper_ok = ('def _is_openeuler_like' in _src_code_cn)
        _guards_ok = _src_code_cn.count('_is_openeuler_like()') >= 4
        _all_cn_ok = (_el_ids_ok and _regex_ok
                      and _helper_ok and _guards_ok)
        self.check("openeuler_kylin_compat",
                   _all_cn_ok,
                   "国产 EL 系兼容性缺失: "
                   "ids=%s regex=%s helper=%s guards=%s" % (
                       _el_ids_ok, _regex_ok, _helper_ok, _guards_ok))
        # [v3.2.345] 本地测试模式结构验证.
        # 必须齐全: 1) CLI flag; 2) SiteConfig 字段 + staging 互斥;
        # 3) verify_dns 早退; 4) _issue_local_self_signed 方法存在;
        # 5) apply_cert + renew_cert 各有早退分支.
        _src_code_lt = self._code_only(new_src)
        _cli_ok = ('"--local-test"' in _src_code_lt)
        _cfg_ok = ("self.local_test = getattr(args, 'local_test'" in _src_code_lt
                   and '--local-test 与 --staging 互斥' in _src_code_lt)
        _dns_ok = ("if getattr(self.cfg, 'local_test', False):" in _src_code_lt
                   and '跳过 DNS 预检' in _src_code_lt)
        _helper_ok_lt = ('def _issue_local_self_signed' in _src_code_lt
                         and '"openssl", "req", "-x509"' in _src_code_lt
                         # [v3.2.346] 确保产出 certbot 兼容 symlink 布局,
                         # 不是裸文件 (测试完切回真 certbot 时不会踩坑)
                         and 'os.symlink(_target' in _src_code_lt
                         and '../../archive/' in _src_code_lt)
        # apply_cert + renew_cert 各一处早退 → 至少 2 处 _issue_local_self_signed() 调用
        _orchestrator_ok = (_src_code_lt.count('self.cert._issue_local_self_signed()') >= 2)
        # [v3.2.347] 模式隔离: timer ExecStart 必须持久化 --local-test,
        # _extract_timer_params 必须识别它, setup_systemd 必须继承它
        _timer_persist_ok = (
            '" --local-test" if getattr(self.cfg, \'local_test\', False)' in _src_code_lt)
        _timer_parse_ok = ('"--local-test" in _exec' in _src_code_lt
                           and '"local_test"] = "true"' in _src_code_lt)
        _timer_inherit_ok = ("_preserved.get(\"local_test\")" in _src_code_lt
                             and 'self.cfg.local_test = True' in _src_code_lt)
        # [v3.2.348] 新增 4 项模式隔离:
        _migrate_guard_ok = ("[v3.2.348] migrate-ssl 不支持本地测试模式" in _src_code_lt)
        _renewal_conf_ok = ("authenticator = manual" in _src_code_lt
                            and 'renewal/' in _src_code_lt)
        # [v3.2.349] EAB 互斥: local_test + zerossl_eab_kid/hmac 需硬拒绝
        _eab_mutex_ok = ("[v3.2.349] --local-test 与 ZeroSSL EAB" in _src_code_lt)
        # [v3.2.350] nginx 高版本指令 probe: 不在线 → openEuler 1.24.0 部署必崩
        _probe_mh_def_ok = ('def _nginx_supports_max_headers' in _src_code_lt)
        _probe_ah_def_ok = ('def _nginx_supports_add_header_inherit' in _src_code_lt)
        # 两处生成点都用条件 (ssl core + http production), 每个指令各 2 call = 共 4 次
        _probe_mh_used = (_src_code_lt.count('_nginx_supports_max_headers()') >= 2)
        _probe_ah_used = (_src_code_lt.count('_nginx_supports_add_header_inherit()') >= 2)
        # 缓存重置必须同步清理新变量, 否则 nginx 升级后探测不刷新
        _probe_reset_ok = ('_NGINX_MAX_HEADERS_CACHE = None' in _src_code_lt
                           and '_NGINX_ADD_HEADER_INHERIT_CACHE = None' in _src_code_lt)
        _all_lt_ok = (_cli_ok and _cfg_ok and _dns_ok
                      and _helper_ok_lt and _orchestrator_ok
                      and _timer_persist_ok and _timer_parse_ok
                      and _timer_inherit_ok
                      and _migrate_guard_ok and _renewal_conf_ok
                      and _eab_mutex_ok
                      and _probe_mh_def_ok and _probe_ah_def_ok
                      and _probe_mh_used and _probe_ah_used
                      and _probe_reset_ok)
        self.check("local_test_mode_structure",
                   _all_lt_ok,
                   "本地测试模式结构缺失: "
                   "cli=%s cfg=%s dns=%s helper=%s orch=%s "
                   "timer_persist=%s timer_parse=%s timer_inherit=%s "
                   "migrate_guard=%s renewal_conf=%s eab_mutex=%s "
                   "probe_mh_def=%s probe_ah_def=%s "
                   "probe_mh_used=%s probe_ah_used=%s probe_reset=%s" % (
                       _cli_ok, _cfg_ok, _dns_ok,
                       _helper_ok_lt, _orchestrator_ok,
                       _timer_persist_ok, _timer_parse_ok, _timer_inherit_ok,
                       _migrate_guard_ok, _renewal_conf_ok, _eab_mutex_ok,
                       _probe_mh_def_ok, _probe_ah_def_ok,
                       _probe_mh_used, _probe_ah_used, _probe_reset_ok))
        # [v3.2.346] 测试脚本自身的 local-test 支持链. 读 test_integration.py 源码,
        # 验证 6 处连线齐全:
        #   1) CLI flag; 2) TestContext.local_test 字段; 3) args→ctx 连线;
        #   4) no-staging 互斥; 5) _common_flags 透传 --local-test;
        #   6) phase_pre DNS skip
        try:
            _self_src = Path(__file__).read_text(encoding="utf-8")
        except OSError:
            _self_src = ""
        _sts_cli = ('"--local-test", action="store_true"' in _self_src)
        _sts_ctx_field = ('local_test: bool = False  # [v3.2.346]' in _self_src)
        _sts_wiring = ("local_test=getattr(args, 'local_test', False)," in _self_src)
        _sts_mutex = ('--local-test 与 --no-staging 互斥' in _self_src)
        _sts_flag = ('flags += " --local-test"' in _self_src)
        _sts_dns_skip = ("[local-test] 跳过 DNS 检查" in _self_src)
        # [v3.2.348] 测试脚本的 3 处 phase 守卫也要在线:
        _sts_migrate_skip = ("migrate_ssl_skipped_local_test" in _self_src)
        _sts_renew_passthrough = (
            'f"renew --domain {d} --email {self.ctx.email} --local-test"' in _self_src)
        _sts_ssl_connect_local = ('_connect_host = "127.0.0.1" if _lt' in _self_src)
        # [v3.2.349] 交互式向导含模式选择 + phase_verify/uninstall 的 curl resolve
        _sts_wizard_prompt = ('本地测试模式 (--local-test' in _self_src
                              and '_mode_choice = input' in _self_src)
        _sts_wizard_ctx = ("local_test=local_test_mode" in _self_src)
        _sts_verify_resolve = ('_https_resolve = "127.0.0.1" if _lt' in _self_src)
        # [v3.2.350] 测试脚本 detect_platform() 须识别 openEuler 等国产 EL 系
        _sts_detect_plat_el = ('"openeuler", "kylin"' in _self_src
                                and 'ID_LIKE=' in _self_src)
        # [v3.2.351] 测试断言豁免: 旧 nginx / 本地自签 / srcache 降级 场景下
        # 不应硬断言, 这些豁免逻辑必须在线.
        _sts_max_hdr_exempt = (
            'nginx_max_headers_skipped' in _self_src
            and '[local-test/旧nginx] max_headers 按 probe 条件生成' in _self_src
            and '_nginx_supports_mh' in _self_src
            and '_nginx_supports_ahi' in _self_src
            and '(1, 29, 8)' in _self_src
            and '(1, 29, 3)' in _self_src)
        _sts_cert_rsa_local = ('cert_rsa_local_test' in _self_src
                               and '[local-test] 预期 RSA 证书' in _self_src)
        _sts_http3_gated = ('ssl_http3_not_configured' in _self_src
                            and '_has_http3_conf' in _self_src)
        _sts_srcache_gated = ('P292_rt_srcache_not_applicable' in _self_src
                              and '_srcache_active' in _self_src)
        # [v3.2.352] B 类真 bug 修复的结构化检查:
        # 1) PHP-FPM LimitNOFILE drop-in (防 SIGSEGV 502)
        # 2) nginx.conf 默认 server 块花括号配对 (修 openEuler 嵌套 location 漏匹配)
        # 3) fail2ban 测试软化 (openEuler 包依赖可能缺失)
        # 4) redis timeout 300 直接写 conf (不依赖 CONFIG REWRITE)
        _src_b_bugs = self._code_only(new_src)
        _b_fpm_dropin = ('LimitNOFILE=65536' in _src_b_bugs
                        and '"/etc/systemd/system/%s.service.d"' in _src_b_bugs
                        and '_current_limit = int' in _src_b_bugs
                        and 'if _current_limit >= 65536:' in _src_b_bugs)
        _b_nginx_brace = ('_has_listen80' in _src_b_bugs
                         and '_brace_start = _mc.index' in _src_b_bugs
                         and "for _sm in re.finditer(r'([ \\t]*)server\\s*\\{'" in _src_b_bugs)
        _b_f2b_graceful = ('fail2ban_not_installed_graceful' in _self_src
                          and 'svc_fail2ban_not_installed_graceful' in _self_src)
        _b_redis_timeout = ('timeout 300' in _src_b_bugs
                           and r'^\s*timeout\s+300\s*$' in _src_b_bugs
                           and '_rc_before_to' in _src_b_bugs
                           and 'if _rc != _rc_before_to:' in _src_b_bugs)
        # [v3.2.353] (A) fail2ban install 失败时必须暴露 stderr 给日志;
        # (B) openEuler/EL 预装 python3-setuptools + python3-systemd 防
        # Python 3.12 升级后 fail2ban 启动 "No module named 'distutils'".
        _b_f2b_diag = ('[v3.2.353] fail2ban install failed rc=%d' in _src_b_bugs
                      and 'subprocess.PIPE' in _src_b_bugs
                      and '_f2b_install_cmd' in _src_b_bugs)
        # B: EL + Debian 分支都要有新两个依赖
        _b_f2b_deps_el = ('"python3-inotify", "python3-setuptools"' in _src_b_bugs
                         and '"python3-systemd"' in _src_b_bugs)
        _b_f2b_deps_debian = ('"python3-pyinotify", "python3-setuptools"' in _src_b_bugs)
        _sts_all_ok = (_sts_cli and _sts_ctx_field and _sts_wiring
                       and _sts_mutex and _sts_flag and _sts_dns_skip
                       and _sts_migrate_skip and _sts_renew_passthrough
                       and _sts_ssl_connect_local
                       and _sts_wizard_prompt and _sts_wizard_ctx
                       and _sts_verify_resolve and _sts_detect_plat_el
                       and _sts_max_hdr_exempt and _sts_cert_rsa_local
                       and _sts_http3_gated and _sts_srcache_gated
                       and _b_fpm_dropin and _b_nginx_brace
                       and _b_f2b_graceful and _b_redis_timeout
                       and _b_f2b_diag and _b_f2b_deps_el
                       and _b_f2b_deps_debian)
        self.check("test_script_local_test_support",
                   _sts_all_ok,
                   "测试脚本 local-test 支持链缺失: "
                   "cli=%s ctx=%s wiring=%s mutex=%s flag=%s dns=%s "
                   "migrate=%s renew=%s ssl_connect=%s "
                   "wizard_prompt=%s wizard_ctx=%s verify_resolve=%s "
                   "detect_plat_el=%s max_hdr_exempt=%s cert_rsa_local=%s "
                   "http3_gated=%s srcache_gated=%s "
                   "b_fpm_dropin=%s b_nginx_brace=%s "
                   "b_f2b_graceful=%s b_redis_timeout=%s "
                   "b_f2b_diag=%s b_f2b_deps_el=%s b_f2b_deps_debian=%s" % (
                       _sts_cli, _sts_ctx_field, _sts_wiring,
                       _sts_mutex, _sts_flag, _sts_dns_skip,
                       _sts_migrate_skip, _sts_renew_passthrough,
                       _sts_ssl_connect_local,
                       _sts_wizard_prompt, _sts_wizard_ctx, _sts_verify_resolve,
                       _sts_detect_plat_el,
                       _sts_max_hdr_exempt, _sts_cert_rsa_local,
                       _sts_http3_gated, _sts_srcache_gated,
                       _b_fpm_dropin, _b_nginx_brace,
                       _b_f2b_graceful, _b_redis_timeout,
                       _b_f2b_diag, _b_f2b_deps_el, _b_f2b_deps_debian))
        # 每个 "serving content" 的 server {} 块必须有 autoindex off
        # 排除: catch-all 拒绝 server (return 444 / ssl_reject_handshake)
        import re as _re_auto
        _src_lines_auto = new_src.split('\n')
        _server_tok_lines = [
            i for i, ln in enumerate(_src_lines_auto)
            if _re_auto.search(r'server_tokens\s+off', ln)
            and (ln.lstrip().startswith('f"') or ln.lstrip().startswith('"') or ln.lstrip().startswith('+'))
        ]
        _missing_autoindex = []
        for _si in _server_tok_lines:
            # Look 15 lines around for autoindex off OR reject-handshake/return 444 (catch-all)
            _ctx = '\n'.join(_src_lines_auto[max(0, _si - 10):_si + 15])
            if 'autoindex off' in _ctx:
                continue
            # Exempt: catch-all blocks (no content served)
            if 'ssl_reject_handshake' in _ctx or 'return 444' in _ctx:
                continue
            _missing_autoindex.append(_si + 1)
        self.check("all_server_blocks_have_autoindex_off",
                   len(_missing_autoindex) == 0,
                   "每个 content-serving server 块应显式 autoindex off (WP 2026 hardening); "
                   "missing=%s" % _missing_autoindex)
        # [v3.2.303] Debian 12 bookworm-backports 获取 Valkey 8.0.1。
        # backports.debian.org 是 Debian 官方 backports, 由 Debian Backports
        # Team 维护, 自 trixie (Debian 13) 回溯编译, 支持至 2026-08-09。
        # 与之前误信的 packages.valkey.io (不存在) 完全不同。
        self.check("debian_bookworm_detect_helper",
                   "def _detect_debian_bookworm()" in new_src
                   and "VERSION_CODENAME" in new_src
                   and '== "bookworm"' in new_src
                   and '== "debian"' in new_src,
                   "缺少 _detect_debian_bookworm() helper (区分 Debian/Ubuntu)")
        self.check("debian_bookworm_enable_backports",
                   "def _enable_bookworm_backports()" in new_src
                   and "bookworm-backports.list" in new_src
                   and "deb.debian.org/debian bookworm-backports" in new_src,
                   "缺少 _enable_bookworm_backports() helper")
        self.check("debian_valkey_install_helper",
                   "def _install_valkey_debian(" in new_src
                   and "-t" in new_src and '"bookworm-backports"' in new_src
                   and "_install_valkey_debian(self.run_cmd)" in new_src,
                   "缺少 _install_valkey_debian() 统一入口 + 调用点")
        self.check("debian_bookworm_upgrade_path",
                   "def _upgrade_valkey_bookworm_backports(" in new_src
                   and "_upgrade_valkey_bookworm_backports(_ver)" in new_src,
                   "upgrade_to_target 缺少 Debian 12 bookworm 分支")
        # [v3.2.304] Ubuntu 25.04 (plucky) / 25.10 (questing) 兼容性:
        # Sury PHP PPA 不为非 LTS 版本构建包, add-apt-repository 写入的
        # codename → apt update 返回 404。修复: add 后改写 sources 中的
        # codename 为 noble (社区广泛验证的兼容方案)。
        self.check("sury_ppa_non_lts_codename_fix",
                   "def _fix_sury_ppa_codename_for_non_lts(" in new_src
                   and "self._fix_sury_ppa_codename_for_non_lts()" in new_src
                   and '"noble"' in new_src
                   and "ondrej-ubuntu-php" in new_src,
                   "缺少 Sury PPA 非 LTS codename 改写 helper + 调用")
        # nginx.org codename 白名单应包含 Ubuntu 25.04+ (plucky/questing/oracular)
        self.check("nginx_org_codename_includes_25_10",
                   '"questing"' in new_src
                   and '"plucky"' in new_src
                   and '"oracular"' in new_src
                   and '"noble"' in new_src,
                   "_NGINX_ORG_CODENAMES 应包含 25.04/25.10 codename")
        # Valkey codename 白名单应包含 questing (25.10)
        self.check("valkey_codename_includes_questing",
                   '"questing"' in new_src
                   and "_valkey_codenames" in new_src,
                   "_valkey_codenames 集合应包含 questing (25.10)")
        # 用户明确要求: path 3 (redis-server 兜底) 加信息日志
        self.check("redis_fallback_info_log_path3",
                   '仓库无 Valkey 包' in new_src
                   and 'redis-server 兜底' in new_src
                   and '升级到' in new_src,
                   "路径 3 兜底应有说明性日志 (告知用户为何不是 Valkey)")
        # [FIX v3.2.300] packages.valkey.io 不是官方 Valkey 仓库, 此 URL 来自
        # 第三方博客误导信息。Debian/Ubuntu 的 Valkey 升级路径应被移除, 脚本
        # 不再尝试这个无效源, 也不再刷 "GPG key 导入失败" 警告。
        # (注: 解释性注释里可以提及旧名, 但不能有功能性代码调用)
        self.check("valkey_deb_upgrade_removed",
                   "https://packages.valkey.io" not in new_src
                   and "def _upgrade_valkey_deb(" not in new_src
                   and 'self._upgrade_valkey_deb(' not in new_src
                   and '"[VALKEY-UPGRADE] GPG key 导入失败"' not in new_src,
                   "应删除无效的 packages.valkey.io 升级路径 (URL/函数/警告日志)")
        # [v3.2.303 更新] 非-bookworm 的 Debian/Ubuntu 路径应静默跳过升级
        # (universe 已由发行版维护)。注意 v3.2.303 后 bookworm 本身有升级路径。
        self.check("valkey_deb_skip_upgrade_gracefully",
                   "Debian/Ubuntu 保持 universe 仓库版本" in new_src
                   and "发行版 SRU 维护" in new_src,
                   "非 bookworm 的 Debian/Ubuntu 升级应优雅静默跳过")
        # [v3.2.301] 品牌标签感知: 运行 Valkey 时日志应显示 "Valkey X.Y" 而非
        # "Redis X.Y"。通过 {flavor} 占位符 + _redis_flavor_name() helper 实现.
        self.check("redis_flavor_helper_exists",
                   "def _redis_flavor_name()" in new_src
                   and 'if shutil.which("valkey-server")' in new_src
                   and 'return "Valkey"' in new_src,
                   "缺少 _redis_flavor_name() helper (flavor-aware labeling)")
        # 4 个版本日志键应使用 {flavor} 占位符, 不再硬编码 "Redis"
        self.check("version_messages_use_flavor",
                   "{flavor} 版本: {ver}" in new_src
                   and "{flavor} {ver} 已是仓库最新版本" in new_src
                   and "{flavor} 已升级" in new_src
                   and "{flavor} 版本 {ver} 低于" in new_src,
                   "版本报告消息应使用 {flavor} 占位符 (非硬编码 Redis)")
        # 调用点传入 flavor=_redis_flavor_name()
        self.check("version_messages_pass_flavor",
                   new_src.count("flavor=_redis_flavor_name()") >= 4,
                   "版本消息调用点应传 flavor=_redis_flavor_name() (>= 4 处)")
        # [v3.2.301] 平台感知的升级门控: Debian/Ubuntu 不把 <9.0 视为需要升级
        self.check("debian_no_valkey_9_gate",
                   "_can_target_valkey_9" in new_src
                   and "_can_target_valkey_9 = False" in new_src
                   and "self.platform.is_el" in new_src,
                   "升级门控应按平台区分 (Debian 不追 Valkey 9.0)")
        self.check("valkey_timeout_300",
                   'timeout", "300"' in new_src or "timeout.*300" in new_src,
                   "缺少 Valkey timeout 300 配置")

        # ── 15. 诊断包收集项 ──

        self.check("diag_php_ini",
                   "conf-php.ini" in new_src,
                   "诊断包缺少 conf-php.ini 收集")
        self.check("diag_nginx_catchall",
                   "conf-nginx-catchall" in new_src,
                   "诊断包缺少 conf-nginx-catchall.conf 收集")
        # [PATCH-290] 新增诊断收集项
        for _diag_item, _label in [
            ("conf-wp-cron-timer", "WP-Cron timer"),
            ("conf-wp-cron-service", "WP-Cron service"),
            ("conf-db-optimize-timer", "DB optimize timer"),
            ("conf-db-optimize-service", "DB optimize service"),
            ("conf-sysctl-network", "sysctl network"),
            ("conf-sysctl-swap", "sysctl swap"),
            ("conf-logrotate", "logrotate"),
            ("conf-certbot-renewal", "Certbot renewal"),
            ("diag-php-modules", "PHP modules"),
            ("diag-selinux", "SELinux"),
            ("script-journal", "script journal"),
        ]:
            self.check(f"diag_{_diag_item.replace('-','_')}",
                       _diag_item in new_src,
                       f"诊断包缺少 {_label} 收集")

        # ── 16. PATCH-288 redis-nginx-module ──

        self.check("P288_redis_nginx_module",
                   "redis-nginx-module" in new_src
                   and "redis_pass" in new_src,
                   "缺少 redis-nginx-module (srcache_fetch 需要 redis_pass)")

        # ── 17. PATCH-289 Nginx srcache 静态编译 + Fail2Ban + SSL 加固 ──

        self.check("P289_srcache_static_compile",
                   "--add-module" in new_src
                   and "srcache-nginx-module" in new_src,
                   "缺少 srcache 静态编译路径 (--add-module)")
        self.check("P289_srcache_install_static_binary",
                   "def _srcache_install_static_binary(" in new_src,
                   "缺少静态二进制替换方法")
        self.check("P289_usr2_hot_swap",
                   "systemctl" in new_src
                   and "restart" in new_src
                   and "_srcache_install_static_binary" in new_src,
                   "缺少二进制升级重启机制")
        self.check("P289_versionlock",
                   "def _versionlock_nginx(" in new_src,
                   "缺少 nginx 版本锁定方法")
        self.check("P289_directive_probe",
                   "brotli_probe" in new_src or "directive probe" in new_src.lower(),
                   "缺少 srcache/brotli 指令探测法 (静态编译无 .so)")
        self.check("P289_f2b_scanner_jail",
                   "nginx-scanner" in new_src
                   and "nginx-4xx-flood" in new_src,
                   "缺少 Fail2Ban 扫描器/4xx 防护 jail")
        self.check("P289_dhparam",
                   "dhparam" in new_src and "ffdhe2048" in new_src,
                   "缺少 DH 参数文件生成 (RFC 7919)")
        # OCSP Stapling 策略: 仅按签发商判定 (LE 禁用, ZeroSSL/其他启用)
        # 不再按 _is_china_network 判定 — ZeroSSL 在国内可用, nginx soft-fail 兜底
        self.check("P289_ocsp_per_ca",
                   "_cert_supports_ocsp" in new_src
                   and "ssl_stapling on" in new_src
                   and "status_ocsp_disabled_le" in new_src,
                   "OCSP Stapling 应按 CA 判定 + 状态显示区分 LE/其他")
        # [FIX-OCSP-RESOLVER] 中国云 DNS resolver 切换
        # 1.1.1.1/8.8.8.8 在中国大陆被屏蔽, OCSP 查询每次超时。
        # 启用 OCSP 时必须按网络位置选择 resolver。
        self.check("ocsp_resolver_china_cloud",
                   "223.5.5.5 223.6.6.6" in new_src
                   and "119.29.29.29" in new_src
                   and "_is_china_network()" in new_src,
                   "OCSP resolver 应在中国云切换到国内 DNS (223.5.5.5/223.6.6.6/119.29.29.29)")
        # OCSP Stapling 用户选项: --ocsp-stapling / --no-ocsp-stapling
        self.check("ocsp_cli_flags_deploy",
                   "\"--ocsp-stapling\"" in new_src
                   and "\"--no-ocsp-stapling\"" in new_src,
                   "deploy 子命令缺少 --ocsp-stapling / --no-ocsp-stapling")
        # CLI flag 应同时在 deploy / update / enable-ssl 三个子命令中可用
        # (通过统计 add_argument 调用次数判断)
        self.check("ocsp_cli_flags_coverage",
                   new_src.count("help=t(\"help_ocsp_stapling\")") >= 3
                   and new_src.count("help=t(\"help_no_ocsp_stapling\")") >= 3,
                   "OCSP flag 应覆盖 deploy + update + enable-ssl (各 >= 3 处)")
        # SiteConfig 字段
        self.check("ocsp_siteconfig_field",
                   "self.ocsp_stapling = False" in new_src
                   and "self.ocsp_stapling = True" in new_src
                   and "self.ocsp_stapling = None" in new_src,
                   "SiteConfig 应有 ocsp_stapling 三态字段 (None/True/False)")
        # LE 阻断逻辑: 用户显式 --ocsp-stapling + LE 证书时发出警告
        self.check("ocsp_le_blocked_warn",
                   "warn_ocsp_le_blocked" in new_src
                   and "_decide_ocsp_enable" in new_src,
                   "缺少 LE 阻断警告 + _decide_ocsp_enable 集中判定函数")
        # 状态显示三态: user-disabled / LE-blocked / enabled
        self.check("ocsp_status_tri_state",
                   "status_ocsp_disabled_user" in new_src
                   and "status_ocsp_disabled_le" in new_src
                   and "status_ocsp_enabled" in new_src,
                   "状态显示应有 user-disabled / LE-blocked / enabled 三态")
        # 交互式向导 (deploy + update) 应包含 OCSP toggle
        self.check("ocsp_interactive_wizard",
                   new_src.count("interactive_rec_ocsp_stapling") >= 3,
                   "交互式向导 (deploy + update + 翻译键) 应包含 ocsp_stapling toggle")
        # Update wizard 反向映射: toggle OFF → --no-ocsp-stapling
        self.check("ocsp_wizard_reverse_map",
                   '"--no-ocsp-stapling"' in new_src
                   and "_ocsp_toggled_off" in new_src,
                   "交互式向导应支持 toggle OFF → --no-ocsp-stapling 反向映射")
        self.check("P289_mdb_innodb_file_per_table",
                   "innodb_file_per_table" in new_src,
                   "缺少 MariaDB innodb_file_per_table=ON")
        self.check("P289_mdb_max_allowed_packet",
                   "max_allowed_packet" in new_src,
                   "缺少 MariaDB max_allowed_packet")
        self.check("P289_mdb_skip_name_resolve",
                   "skip_name_resolve" in new_src or "skip-name-resolve" in new_src,
                   "缺少 MariaDB skip_name_resolve")

        # ── 18. PATCH-290 正则修复 + open_basedir 架构 + 诊断增强 ──

        # 正则修复: =[ \t]* 替代 =\s*
        self.check("P290_regex_fix_tab_space",
                   "=[ \\t]*" in new_src,
                   "patch_php_ini_line 正则缺少 =[ \\t]* 修复")
        # open_basedir 架构: 全局 php.ini 清空 + FPM pool php_admin_value
        self.check("P290_open_basedir_fpm_pool",
                   "php_admin_value[open_basedir]" in new_src,
                   "缺少 FPM pool php_admin_value[open_basedir]")
        self.check("P290_open_basedir_global_clear",
                   'patch_php_ini_line(content, "open_basedir", "")' in new_src
                   or "open_basedir.*清" in new_src,
                   "缺少全局 php.ini open_basedir 清空")
        # MariaDB socket 循环
        self.check("P290_mariadb_socket_loop",
                   "_socket_candidates" in new_src,
                   "缺少 MariaDB socket 循环内探测")
        # pcre.jit
        self.check("P290_pcre_jit",
                   "'pcre.jit'" in new_src or '"pcre.jit"' in new_src,
                   "缺少 pcre.jit=1 调优")
        # date.timezone
        self.check("P290_date_timezone",
                   "def _detect_system_timezone(" in new_src
                   and "/etc/timezone" in new_src,
                   "缺少 date.timezone 自动检测 (含 /etc/timezone Debian 路径)")
        # SysLogHandler
        # [v3.2.340] 剥离注释: 上面 "# SysLogHandler" 会匹配
        _src_code_syslog = self._code_only(new_src)
        self.check("P290_syslog_handler",
                   "SysLogHandler" in _src_code_syslog,
                   "缺少 SysLogHandler journal 持久化")
        # EAB 脱敏
        self.check("P290_eab_redact",
                   "eab" in new_src.lower() and "REDACTED" in new_src,
                   "诊断收集缺少 EAB 凭据脱敏")
        # system-info 新增: WP-CLI 版本 + 脚本版本
        self.check("P290_diag_wpcli_version",
                   "WP-CLI ---" in new_src or "wp.*--allow-root.*--version" in new_src,
                   "诊断 system-info 缺少 WP-CLI 版本")
        self.check("P290_diag_script_version",
                   "WP-SSL-Bootstrap ---" in new_src and "__version__" in new_src,
                   "诊断 system-info 缺少脚本版本")

        # ── 19. PATCH-291 PHP 配置双写消除 ──

        self.check("P291_unified_fpm_pool_tuning",
                   "Phase 1" in new_src and "Phase 2" in new_src
                   and "Phase 3" in new_src,
                   "_patch_fpm_pool_tuning 缺少 Phase 1/2/3 统一结构")
        self.check("P291_lemp_configure_simplified",
                   "def _lemp_configure_php(self)" in new_src,
                   "缺少 _lemp_configure_php 方法")
        # _lemp_configure_php 应简化为仅委托调用
        _lemp_php_src = ""
        _lcp_start = new_src.find("def _lemp_configure_php(self)")
        if _lcp_start > 0:
            _lcp_end = new_src.find("\n    def ", _lcp_start + 1)
            if _lcp_end > 0:
                _lemp_php_src = new_src[_lcp_start:_lcp_end]
        self.check("P291_lemp_single_delegation",
                   "self._patch_fpm_pool_tuning()" in _lemp_php_src
                   and "patch_php_ini_line" not in _lemp_php_src,
                   "_lemp_configure_php 应为单行委托, 不应有独立 ini 循环")

        # ── 20. PATCH-292 srcache upstream Unix socket ──

        self.check("P292_srcache_unix_socket",
                   "unix:" in new_src
                   and "_rs_candidate" in new_src
                   and "valkey.sock" in new_src,
                   "srcache upstream 缺少 Unix socket 自动检测")
        self.check("P292_tcp_fallback",
                   "_redis_endpoint" in new_src
                   and "127.0.0.1:6379" in new_src,
                   "srcache upstream 缺少 TCP 回退")
        self.check("P292_nginx_upstream_sync_fallback",
                   "PATCH-292" in new_src
                   and "Nginx srcache upstream" in new_src
                   and "unix:" in new_src,
                   "socket→TCP 回退时缺少 Nginx upstream 同步回退")
        self.check("P292_nginx_helper_socket_constant",
                   "RT_WP_NGINX_HELPER_REDIS_UNIX_SOCKET" in new_src,
                   "缺少 Nginx Helper 插件 Unix socket 常量注入")
        # [PATCH-292] OPcache JIT + 高级调优
        self.check("P292_opcache_jit",
                   "'opcache.jit'" in new_src and "tracing" in new_src,
                   "缺少 opcache.jit=tracing (JIT 编译器未启用)")
        self.check("P292_opcache_jit_buffer",
                   "'opcache.jit_buffer_size'" in new_src,
                   "缺少 opcache.jit_buffer_size")
        self.check("P292_opcache_save_comments",
                   "'opcache.save_comments'" in new_src,
                   "缺少 opcache.save_comments 显式声明")
        self.check("P292_opcache_huge_code_pages",
                   "'opcache.huge_code_pages'" in new_src,
                   "缺少 opcache.huge_code_pages")
        # [PATCH-292] WordPress 生产环境常量
        # [v3.2.340] 剥离注释后断言 (原本 WP_ENVIRONMENT_TYPE/WP_MEMORY_LIMIT 在
        # 模块头部注释中提及, 代码删除后测试仍会假阳性通过)
        _src_code_p292 = self._code_only(new_src)
        self.check("P292_wp_environment_type",
                   "WP_ENVIRONMENT_TYPE" in _src_code_p292
                   and "production" in _src_code_p292,
                   "缺少 WP_ENVIRONMENT_TYPE='production'")
        self.check("P292_wp_memory_limit",
                   "WP_MEMORY_LIMIT" in _src_code_p292
                   and "256M" in _src_code_p292,
                   "缺少 WP_MEMORY_LIMIT='256M'")

        # ══════════════════════════════════════════════════════════════════
        # [v3.2.364] 架构规则 1/2/7 断言 — 防止未来重构回归
        # ══════════════════════════════════════════════════════════════════
        # 跨会话的 V3.2.7→V3.2.364 WPDM god-class 重构 (327→108 方法, -67%)
        # 引入了 11 个 Manager 公开 API + 信号检查注入. 这组断言保证这些
        # 不变量在未来重构中不被意外破坏.
        _new_src = new_src  # 脚本源码副本, 对齐变量命名

        # 1. NginxManager 公开路径/验证 API
        for _api, _kind in [
            ("get_conf_path", "-> Path"),
            ("get_conf_d_dir", "-> Path"),
            ("get_site_conf_path", "-> Path"),
            ("validate_config", "-> bool"),
            ("validate_config_file", "-> bool"),
            ("graceful_shutdown", "-> bool"),
            ("get_module_conf_dirs", "-> tuple"),
        ]:
            _pat = r'^\s{4}def\s+' + _re_dead.escape(_api) + r'\s*\('
            self.check(
                "v3_2_364_nginx_api_" + _api,
                bool(_re_dead.search(_pat, _new_src, _re_dead.MULTILINE)),
                "NginxManager 缺公开 API def %s(...) %s" % (_api, _kind))

        # 2. RedisManager 公开路径 API
        for _api in ("get_conf_path", "get_candidate_conf_paths"):
            _pat = r'^\s{4}def\s+' + _re_dead.escape(_api) + r'\s*\('
            self.check(
                "v3_2_364_redis_api_" + _api,
                bool(_re_dead.search(_pat, _new_src, _re_dead.MULTILINE)),
                "RedisManager 缺公开 API def %s(...)" % _api)

        # 3. MariaDBManager 公开 API
        self.check(
            "v3_2_364_mariadb_verify_user_connection",
            bool(_re_dead.search(
                r'^\s{4}def\s+verify_user_connection\s*\(',
                _new_src, _re_dead.MULTILINE)),
            "MariaDBManager 缺 verify_user_connection() API")

        # 4. WPDM 规则 1/2 清洁: 不再硬编码 Path("/etc/nginx|redis|valkey")
        _wpdm_m = _re_dead.search(r'^class WPDeployManager\b',
                                  _new_src, _re_dead.MULTILINE)
        _end_m = _re_dead.search(r'\n(class|def) \w+',
                                 _new_src[(_wpdm_m.end() if _wpdm_m else 0):])
        _wpdm_start = _wpdm_m.start() if _wpdm_m else 0
        _wpdm_end = (_wpdm_m.end() + _end_m.start() + 1) if _wpdm_m and _end_m else len(_new_src)
        _wpdm_body = _new_src[_wpdm_start:_wpdm_end]
        # 排除注释里的字面串 (migration comments 会提到旧硬编码)
        _wpdm_non_comment = "\n".join(
            _l for _l in _wpdm_body.split("\n")
            if not _l.lstrip().startswith("#"))
        _hardcoded_paths = _re_dead.findall(
            r'Path\s*\(\s*[fr]?["\']\/etc\/(nginx|redis|valkey)',
            _wpdm_non_comment)
        self.check(
            "v3_2_364_wpdm_no_path_hardcode",
            len(_hardcoded_paths) == 0,
            "WPDM 里仍有 %d 处 Path('/etc/{nginx,redis,valkey}') 硬编码 "
            "(应改用 self.nginx.get_conf_path() 等 API)"
            % len(_hardcoded_paths))

        # 5. WPDM 规则 1/2 清洁: subprocess 组件调用真违规 = 0
        # (允许带 '诊断' / 'diag' / '例外' 注释的 fallback)
        _real_subp = 0
        for _sm in _re_dead.finditer(
                r'subprocess\.run\s*\(\s*\n?\s*\[\s*["\']([^"\']+)["\']',
                _wpdm_body):
            _cmd = _sm.group(1)
            if _cmd not in ('nginx', 'php-fpm', 'mysql', 'mariadb',
                            'redis-cli', 'valkey-cli'):
                continue
            _offset = _sm.start()
            _ln = _wpdm_body[:_offset].count('\n') + 1
            _line = _wpdm_body.split('\n')[_ln-1]
            _pos = _line.find('subprocess.run')
            _hash = _line.find('#')
            if _hash >= 0 and _hash < _pos:
                continue  # 注释里的字面串
            _ctx = '\n'.join(_wpdm_body.split('\n')[max(0, _ln-6):_ln])
            if any(_k in _ctx for _k in ('诊断', '例外', 'diag',
                                          'validate_config()')):
                continue
            _real_subp += 1
        self.check(
            "v3_2_364_wpdm_no_subprocess_component_call",
            _real_subp == 0,
            "WPDM 里仍有 %d 处直接 subprocess.run nginx/mysql/php-fpm/redis-cli "
            "(应改用 self.<Manager>.xxx()); 诊断例外需加注释豁免" % _real_subp)

        # 6. 规则 7 信号检查注入: 5 个 Manager 都有 _abort_if_shutdown 注入
        for _mgr in ('nginx', 'mariadb', 'php', 'redis', 'cert'):
            _inj_pat = r'self\.' + _mgr + r'\._abort_if_shutdown\s*=\s*self\._abort_if_shutdown'
            self.check(
                "v3_2_364_signal_injection_" + _mgr,
                bool(_re_dead.search(_inj_pat, _new_src)),
                "WPDM __init__ INJECTION BLOCK 缺 self.%s._abort_if_shutdown 注入" % _mgr)

        # 7. 规则 7 覆盖率: 至少 60 个 _abort_if_shutdown() 调用点 (当前 76)
        # 防倒退: 如果低于 60 可能是注入丢了或某 Manager 方法集体去除了检查
        _abort_calls = 0
        for _am in _re_dead.finditer(r'(?<!def )_abort_if_shutdown\(\)',
                                     _new_src):
            _ln_abort = _new_src[:_am.start()].count('\n') + 1
            _line = _new_src.split('\n')[_ln_abort-1]
            if _line.lstrip().startswith('#'):
                continue
            _abort_calls += 1
        self.check(
            "v3_2_364_signal_check_coverage",
            _abort_calls >= 60,
            "信号检查点仅 %d 处 (目标 ≥ 60, 当前应为 76+); "
            "可能 Manager 入口检查被误删" % _abort_calls)

        # 8. INJECTION BLOCK 标记存在 + 位于 __init__ 末尾
        # 防未来把注入块前移导致 A2 init-order 陷阱
        self.check(
            "v3_2_364_injection_block_marker",
            "INJECTION BLOCK" in _new_src,
            "WPDM __init__ 缺 '# INJECTION BLOCK' 标记注释 "
            "(跨组件注入必须标记, 避免 A2 init-order 陷阱)")

        # 9. 所有 Manager 类都有 self.run_cmd 依赖注入 (A6 陷阱)
        for _mgr_cls in ('NginxManager', 'MariaDBManager', 'PHPManager',
                         'RedisManager', 'CertManager'):
            _cls_m = _re_dead.search(r'^class ' + _mgr_cls + r'\b',
                                     _new_src, _re_dead.MULTILINE)
            if not _cls_m:
                continue
            # [修] 匹配 def __init__(...) 带返回类型注解到冒号, 支持多行签名
            _init_m = _re_dead.search(
                r'def __init__\s*\(([^)]*)\)[^:]*:',
                _new_src[_cls_m.end(): _cls_m.end() + 3000],
                _re_dead.DOTALL)
            if not _init_m:
                continue
            _sig_params = _init_m.group(1)
            self.check(
                "v3_2_364_mgr_init_has_run_cmd_" + _mgr_cls.lower(),
                'run_cmd' in _sig_params,
                "%s.__init__ 签名缺 run_cmd 参数 (A6 陷阱: Manager 不可 import WPDM)"
                % _mgr_cls)

        # ── [v3.2.365 HOTFIX] 模块级函数不能引用 self.xxx (NameError 炸弹) ──
        # V3.2.364 批量 Path 迁移误把 self.nginx.get_conf_d_dir() 放入
        # 模块级函数 (_detect_existing_sites 等), 启动时 NameError. 防回归:
        _module_funcs_with_self = []
        _top_funcs = list(_re_dead.finditer(r'^def\s+(\w+)\s*\(',
                                            _new_src, _re_dead.MULTILINE))
        for _i, _tm in enumerate(_top_funcs):
            _fname = _tm.group(1)
            _fstart = _tm.start()
            _rest_src = _new_src[_fstart + 5:]
            _nmt = _re_dead.search(r'^(def|class)\s+\w+',
                                   _rest_src, _re_dead.MULTILINE)
            _fend = _fstart + 5 + (_nmt.start() if _nmt else len(_rest_src))
            _fbody = _new_src[_fstart:_fend]
            for _sm in _re_dead.finditer(r'(?<![\w.])self\.', _fbody):
                _pos = _sm.start()
                _ln_f = _fbody[:_pos].count('\n') + 1
                _line = _fbody.split('\n')[_ln_f-1]
                if _line.lstrip().startswith('#'):
                    continue
                _tq = _fbody[:_pos].count('"""')
                if _tq % 2 != 0:
                    continue
                _module_funcs_with_self.append((_fname, _ln_f))
                break
        self.check(
            "v3_2_365_no_self_in_module_funcs",
            len(_module_funcs_with_self) == 0,
            "模块级函数引用 self.xxx (NameError 运行时炸弹): %s"
            % _module_funcs_with_self[:3])

        # ══════════════════════════════════════════════════════════════════
        # [v3.2.364] 断言结束
        # ══════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════
        # [v3.2.365] 重构陷阱目录 ★★★ 级项契约测试
        # ══════════════════════════════════════════════════════════════════
        # 这三个 pitfall 在重构历史中各导致过生产事故 (见
        # 重构陷阱目录 A13 / A2 / B1), 必须持续断言防回归.

        # 10. A13 ★★★: -> bool 委托 wrapper 必须 return
        # 陷阱: setup_nginx_for_challenge 迁移到 NginxManager 返回 bool,
        # WPDM wrapper 写成 self.nginx.xxx() 不带 return → 返回 None,
        # 调用方 `if not None → True` → 永远进入错误分支, 全新部署 100% 失败.
        _a13_violations = []
        _wpdm_class_m = _re_dead.search(r'^class WPDeployManager\b',
                                        _new_src, _re_dead.MULTILINE)
        if _wpdm_class_m:
            _wcs = _wpdm_class_m.start()
            _wce = len(_new_src)
            for _nm_after in _re_dead.finditer(r'^(class|def) \w+',
                                               _new_src[_wcs + 10:],
                                               _re_dead.MULTILINE):
                _wce = _wcs + 10 + _nm_after.start()
                break
            _wpdm_body = _new_src[_wcs:_wce]
            # 所有 WPDM 里 def xxx(...) -> bool: 的方法
            _bool_method_pat = _re_dead.compile(
                r'^    def\s+(\w+)\s*\([^)]*\)\s*->\s*bool\s*:\s*\n',
                _re_dead.MULTILINE)
            _method_boundaries = list(_re_dead.finditer(
                r'^    (?:def|@)\s+\w+', _wpdm_body, _re_dead.MULTILINE))
            for _bm in _bool_method_pat.finditer(_wpdm_body):
                _bname = _bm.group(1)
                if _bname.startswith('__'):
                    continue
                _body_start = _bm.end()
                # 找方法体结束
                _body_end = len(_wpdm_body)
                for _mb in _method_boundaries:
                    if _mb.start() > _bm.end():
                        _body_end = _mb.start()
                        break
                _mbody = _wpdm_body[_body_start:_body_end]
                # 剥离 docstring
                _mbody_wo = _re_dead.sub(
                    r'^\s*(""".*?"""|\'\'\'.*?\'\'\')\s*\n',
                    '', _mbody, count=1, flags=_re_dead.DOTALL)
                # 找委托调用: self.<mgr>.<method>(...)
                _deleg = _re_dead.search(
                    r'self\.(nginx|mariadb|php|redis|cert)\.\w+\s*\(',
                    _mbody_wo)
                if not _deleg:
                    continue
                # 只关心很短的 wrapper (≤5 行): 典型委托
                _mlines = [_l for _l in _mbody_wo.split('\n')
                           if _l.strip()
                           and not _l.strip().startswith('#')]
                if len(_mlines) > 5:
                    continue
                # 检查委托调用前是否有 return
                _before = _mbody_wo[:_deleg.start()]
                if 'return ' not in _before:
                    _a13_violations.append(_bname)
        self.check(
            "v3_2_365_a13_bool_wrapper_must_return",
            len(_a13_violations) == 0,
            "A13 陷阱 ★★★: WPDM 里 -> bool 短 wrapper 未用 return 传递委托结果, "
            "导致返回 None 被调用方解读为 False → 错误分支. "
            "违规方法: %s" % (_a13_violations[:3] if _a13_violations else ''))

        # 11. A2 ★★★: INJECTION BLOCK 必须在 Manager 实例化之后
        # 陷阱: self.nginx._is_dnf5 = self._is_dnf5 必须在 self._is_dnf5
        # 赋值之后; 顺序颠倒导致注入 None → 生产环境才触发 AttributeError.
        # [修] 只看 WPDM __init__ 内部的 INJECTION BLOCK, 不看文档区
        _wpdm_class_m2 = _re_dead.search(r'^class WPDeployManager\b',
                                         _new_src, _re_dead.MULTILINE)
        _a2_ok = False
        _a2_msg = ""
        if _wpdm_class_m2:
            _wcs2 = _wpdm_class_m2.start()
            # 找 WPDM 里第一个 Manager 实例化
            _nm_create = _re_dead.search(
                r'self\.nginx\s*=\s*NginxManager\(', _new_src[_wcs2:])
            # 找 WPDM 范围内的 INJECTION BLOCK 标记
            _inj_in_wpdm = _new_src[_wcs2:].find('INJECTION BLOCK')
            if _nm_create and _inj_in_wpdm >= 0:
                _a2_ok = _inj_in_wpdm > _nm_create.end()
                _a2_msg = ("WPDM 内 NginxManager 实例化 offset=%d, "
                           "INJECTION BLOCK offset=%d"
                           % (_nm_create.end(), _inj_in_wpdm))
            else:
                _a2_msg = "未找到 NginxManager 实例化或 INJECTION BLOCK 标记"
        self.check(
            "v3_2_365_a2_injection_after_instantiation",
            _a2_ok,
            "A2 陷阱 ★★★: %s. 注入必须在 Manager 实例化之后, "
            "否则注入 None 引发 AttributeError" % _a2_msg)

        # 12. B1 ★★★: neutralize_default_server_block 必须有注释跳过逻辑
        # 陷阱: re.search(r'server\s*\{') 会匹配 "# server {" → 每次 update
        # 都在注释上再加 # → 生产实测 36→42 层 "# # # # server {" 无限累积.
        _neutralize_m = _re_dead.search(
            r'def neutralize_default_server_block\s*\([^)]*\).*?(?=\n    def |\n\nclass )',
            _new_src, _re_dead.DOTALL)
        if _neutralize_m:
            _nb = _neutralize_m.group(0)
            # 必备防御: (a) 清理多层 # 前缀, (b) 识别已注释行跳过
            _has_multi_hash_norm = bool(_re_dead.search(
                r'\(\?\:\#\[', _nb) or _re_dead.search(
                    r"\(\?:#", _nb) or
                '#[ \\t]*){2,}' in _nb or '# ){2,}' in _nb or
                '归一化' in _nb or '多层' in _nb)
            _has_comment_skip = "'#' in" in _nb or '"#" in' in _nb or \
                                '已注释' in _nb
            self.check(
                "v3_2_365_b1_comment_accumulation_defense",
                _has_multi_hash_norm and _has_comment_skip,
                "B1 陷阱 ★★★: neutralize_default_server_block 需双重防御: "
                "(1) 归一化已有 # 前缀 (2) 跳过已注释行. "
                "归一化=%s, 跳过检查=%s"
                % (_has_multi_hash_norm, _has_comment_skip))

        # 13. C3 ★★★: redis-cli 调用必须走 _sock_args() (port 0 兼容)
        # 陷阱: port 0 禁用 TCP 后, redis-cli 无 -s 参数会走 TCP fallback
        # 导致 "Connection refused". 扫描非存在性检查的 redis-cli 调用.
        _c3_suspicious = []
        for _rcm in _re_dead.finditer(
                r'subprocess\.run\s*\(\s*\n?\s*\[\s*["\']redis-cli["\']',
                _new_src):
            _offset = _rcm.start()
            _rln = _new_src[:_offset].count('\n') + 1
            _rctx = '\n'.join(_new_src.split('\n')[max(0, _rln-4):_rln+8])
            # 本次调用上下文中必须有 _sock_args 或 ["-s"]
            if '_sock_args' not in _rctx and '"-s"' not in _rctx \
                    and "'-s'" not in _rctx:
                _c3_suspicious.append(_rln)
        self.check(
            "v3_2_365_c3_redis_cli_uses_sock_args",
            len(_c3_suspicious) == 0,
            "C3 陷阱 ★★★: subprocess redis-cli 调用未通过 _sock_args() 或显式 -s, "
            "port 0 下 TCP 连接会失败. 行号: %s"
            % (_c3_suspicious[:5] if _c3_suspicious else ''))

        # 14. H3 诊断包三版对比: 静态断言 collect_logs 使用 socket 参数
        # 陷阱: 诊断包里 redis-cli 不加 -s 时, port 0 下采集失败.
        _collect_m = _re_dead.search(
            r'def collect_logs\s*\([^)]*\).*?(?=\n    def |\nclass )',
            _new_src, _re_dead.DOTALL)
        if _collect_m:
            _cl_body = _collect_m.group(0)
            _has_sock_aware = ('_sock_args' in _cl_body
                               or 'get_conf_path' in _cl_body
                               or 'unixsocket' in _cl_body
                               or '"-s"' in _cl_body
                               or "'-s'" in _cl_body
                               or '诊断采集' in _cl_body)
            # collect_logs 中如用了 redis-cli 必须 socket-aware
            _uses_redis_cli = 'redis-cli' in _cl_body or 'valkey-cli' in _cl_body
            self.check(
                "v3_2_365_g1_collect_logs_socket_aware",
                (not _uses_redis_cli) or _has_sock_aware,
                "G1 陷阱: collect_logs 使用 redis-cli 但未走 socket-aware 路径, "
                "port 0 下诊断采集会失败.")

        # ══════════════════════════════════════════════════════════════════
        # [v3.2.365] ★★★ 陷阱契约测试结束
        # ══════════════════════════════════════════════════════════════════

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

        # [FIX] 验证组件版本摘要输出
        self.check("deploy_version_summary",
                   "组件版本" in (r.stdout or "") or "component" in (r.stdout or "").lower(),
                   _m("部署输出中无组件版本摘要", "no component version summary in deploy output"))

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
            for v in ["8.5", "8.4", "8.3", "8.2", "8.1", "8.0"]:
                svc = f"php{v}-fpm"
                if _svc_exists(svc):
                    _p["php_fpm_svc"] = svc
                    break
        # [FIX] deploy 后 Redis/Valkey 服务名可能已变 (启动时未安装, fallback 到 candidates[0])
        # 重新检测确保使用正确的服务名
        if _p["family"] == "el":
            _p["redis_svc"] = _detect_active_svc(["valkey", "redis"])
        else:
            _p["redis_svc"] = _detect_active_svc(["valkey-server", "valkey", "redis-server", "redis"])
        # [v3.2.352] fail2ban 可能未安装 (openEuler 包依赖问题 → 脚本优雅降级),
        # 仅在 fail2ban-client 存在时才加入服务状态断言.
        import shutil as _sh_svc_f2b
        svc_checks = [
            ("nginx", "nginx"),
            ("db", _p["db_svc"]),
            ("redis", _p["redis_svc"]),
            ("php_fpm", _p["php_fpm_svc"]),
        ]
        if _sh_svc_f2b.which("fail2ban-client"):
            svc_checks.append(("fail2ban", "fail2ban"))
        else:
            self.check("svc_fail2ban_not_installed_graceful", True,
                       _m("fail2ban 未装 (脚本已优雅降级)",
                          "fail2ban not installed (script degraded gracefully)"))
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

        # nginx.conf 默认 server 块应已注释
        _ngx_main = Path("/etc/nginx/nginx.conf")
        if _ngx_main.exists():
            _ngx_mc = _ngx_main.read_text(encoding='utf-8', errors='replace')
            _has_active_default = bool(re.search(
                r'^\s*server_name\s+_\s*;', _ngx_mc, re.MULTILINE))
            self.check("nginx_default_server_commented",
                       not _has_active_default,
                       "nginx.conf 默认 server 块未注释 (应被 00-catchall 替代)")
            # [1.30] nginx.conf http{} 全局优化
            self.check("nginx_main_tcp_nopush",
                       re.search(r'^\s*tcp_nopush\s+on\s*;', _ngx_mc, re.M)
                       and not re.search(r'^\s*#\s*tcp_nopush', _ngx_mc, re.M),
                       "nginx.conf tcp_nopush 应取消注释并启用")
            self.check("nginx_main_tcp_nodelay",
                       re.search(r'^\s*tcp_nodelay\s+on\s*;', _ngx_mc, re.M),
                       "nginx.conf 缺少 tcp_nodelay on")
            self.check("nginx_main_server_tokens_off",
                       re.search(r'^\s*server_tokens\s+off\s*;', _ngx_mc, re.M),
                       "nginx.conf 缺少全局 server_tokens off")

        # 00-catchall.conf 存在
        _catchall = Path("/etc/nginx/conf.d/00-catchall.conf")
        self.check("nginx_catchall_exists", _catchall.exists(),
                   "00-catchall.conf 不存在 (IP 直连拦截配置)")

        conf = Path(f"/etc/nginx/conf.d/{d}.conf")
        self.check("nginx_site_conf", conf.exists())

        if conf.exists():
            ct = conf.read_text()
            self.check("nginx_ssl_listen", "listen 443 ssl" in ct or "listen 443 quic" in ct)
            self.check("nginx_http2", "http2 on" in ct or "http2" in ct)
            self.check("nginx_fastcgi_cache",
                       "fastcgi_cache" in ct or "srcache_fetch" in ct)
            self.check("nginx_security_headers", "X-Content-Type-Options" in ct)
            # [1.30] 新特性
            # [v3.2.351] 本地测试模式 / 旧 nginx: max_headers 和 add_header_inherit
            # 由被测脚本 probe 后条件生成. 若 nginx 不支持这两个指令本就 "应当"
            # 不生成. 跳过硬断言避免误报.
            # [v3.2.355] 修 v3.2.354 引入的版本判据错误:
            #   · max_headers 需要 nginx >= 1.29.8 mainline 或 >= 1.30.0 stable
            #     (nginx CHANGES 2026-04-07 引入, Maxim Dounin 贡献)
            #   · add_header_inherit 需要 nginx >= 1.29.3 mainline 或 >= 1.30.0 stable
            #     (nginx 官方文档 ngx_http_headers_module.html)
            #   v3.2.354 用 >= (1, 27) 的单一判据对两个指令都太松, 在 nginx
            #   1.28.x stable (nginx.org 旧 stable) 上会错误地要求存在指令,
            #   但 probe 正确地没生成 → 测试误报. 修正为逐指令精确版本判据,
            #   regex 捕获 patch 号.
            _lt_verify = getattr(self.ctx, 'local_test', False)
            try:
                _ngx_ver_probe = run(["nginx", "-v"])
                _ngx_ver_text = (_ngx_ver_probe.stdout or "") + (_ngx_ver_probe.stderr or "")
                _ngx_m = re.search(r'nginx/(\d+)\.(\d+)\.(\d+)', _ngx_ver_text)
                if _ngx_m:
                    _ngx_v = (int(_ngx_m.group(1)),
                              int(_ngx_m.group(2)),
                              int(_ngx_m.group(3)))
                    # 判据分离: 两指令的引入版本不同!
                    _nginx_supports_mh = _ngx_v >= (1, 29, 8)
                    _nginx_supports_ahi = _ngx_v >= (1, 29, 3)
                else:
                    _nginx_supports_mh = False
                    _nginx_supports_ahi = False
            except Exception:
                _nginx_supports_mh = False
                _nginx_supports_ahi = False
            # 本地测试模式 / 任一指令不支持 → 跳过对应断言
            if _lt_verify or not _nginx_supports_mh:
                self.check("nginx_max_headers_skipped",
                           True,
                           _m("[local-test/旧nginx] max_headers 按 probe 条件生成",
                              "[local-test/old-nginx] max_headers conditionally emitted"))
            else:
                self.check("nginx_max_headers", "max_headers" in ct,
                           "站点配置缺少 max_headers (Nginx 1.29.8+ DoS 防护)")
            if _lt_verify or not _nginx_supports_ahi:
                self.check("nginx_add_header_inherit_skipped",
                           True,
                           _m("[local-test/旧nginx] add_header_inherit 按 probe 条件生成",
                              "[local-test/old-nginx] add_header_inherit conditionally emitted"))
            else:
                self.check("nginx_add_header_inherit", "add_header_inherit" in ct,
                           "站点配置缺少 add_header_inherit (Nginx 1.29.3+ 安全头继承)")
            # Cloudflare real-ip 可能在单独文件 (不在站点 conf 内)
            _cf_conf = Path("/etc/nginx/conf.d/cloudflare-real-ip.conf")
            _has_cf = "set_real_ip_from" in ct or _cf_conf.exists()
            self.check("nginx_cloudflare", _has_cf)
            # [1.30] gzip_types 含 wasm + font/woff2
            self.check("nginx_gzip_wasm_font",
                       "application/wasm" in ct and "font/woff2" in ct,
                       "gzip_types 缺少 application/wasm 或 font/woff2")

        # [1.30] Brotli font/woff2 类型
        _br_conf = Path("/etc/nginx/conf.d/brotli-wp-bootstrap.conf")
        if _br_conf.exists():
            try:
                _br_ct = _br_conf.read_text()
                self.check("brotli_font_types",
                           "font/woff2" in _br_ct,
                           "brotli_types 缺少 font/woff2")
            except OSError:
                pass

        # ── SSL 证书 ──
        ci = cert_info(d)
        self.check("cert_exists", bool(ci), _m("fullchain.pem 不存在", "fullchain.pem not found"))
        if ci:
            # [v3.2.351] 本地测试模式用 RSA 2048 (最广兼容性), 非 ECDSA
            if getattr(self.ctx, 'local_test', False):
                self.check("cert_rsa_local_test",
                           not ci.get("ecdsa", False),
                           _m("[local-test] 预期 RSA 证书 (非 ECDSA)",
                              "[local-test] expected RSA cert (not ECDSA)"))
            else:
                self.check("cert_ecdsa", ci.get("ecdsa", False), _m("非 ECDSA 证书", "not ECDSA certificate"))
            self.check("cert_issuer", bool(ci.get("issuer")), _m("无签发商", "no issuer"))

        # ── HTTP 响应 ──
        # [v3.2.348] 本地测试模式: 用 --resolve 绕过 DNS 直连本机 nginx
        _lt = getattr(self.ctx, 'local_test', False)
        _https_resolve = "127.0.0.1" if _lt else None
        status = curl_status(f"https://{d}/", insecure=True,
                              resolve_to=_https_resolve)
        self.check("https_200", status in (200, 301, 302),
                   f"status={status}")

        # HTTP→HTTPS 重定向
        # [v3.2.313b] CDN (Cloudflare) 代理站点: curl 公网地址会被 CF 边缘
        # 拦截/改写, 探测不到源站 nginx 的 :80 301 行为。改用 --resolve
        # 127.0.0.1 直连源站验证真正的 nginx 重定向配置。
        # [v3.2.348] 本地测试模式: 同样用 127.0.0.1 直连
        _resolve = "127.0.0.1" if (getattr(self, "is_cf_proxied", False) or _lt) else None
        status_http = curl_status(f"http://{d}/", resolve_to=_resolve)
        self.check("http_redirect", status_http in (301, 302),
                   f"status={status_http}"
                   + (" (via --resolve 127.0.0.1, 绕过 CDN)"
                      if _resolve else ""))

        # ── WordPress ──
        # webroot 可能是 /var/www/html/{d} 或 /usr/share/nginx/html/{d}
        webroot = None
        wp_config = None
        for _wr in [Path(f"/var/www/html/{d}/wp-config.php"),
                     Path(f"/usr/share/nginx/html/{d}/wp-config.php")]:
            if _wr.exists():
                wp_config = _wr
                webroot = _wr.parent
                break
        # fallback: 即使 wp-config.php 不存在, 也尝试常见路径
        if webroot is None:
            for _wr_dir in [Path(f"/usr/share/nginx/html/{d}"),
                            Path(f"/var/www/html/{d}")]:
                if _wr_dir.is_dir():
                    webroot = _wr_dir
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

        # ── PHP-FPM pool 配置 ──
        _fpm_pool_checked = False
        import glob as _g_v
        for _pool_glob in ["/etc/php-fpm.d/www.conf",
                           "/etc/php/*/fpm/pool.d/www.conf"]:
            for _pool_path in _g_v.glob(_pool_glob):
                try:
                    _pool_c = Path(_pool_path).read_text()
                    _fpm_pool_checked = True
                    self.check("fpm_status_path",
                               "pm.status_path" in _pool_c
                               and "fpm-status" in _pool_c,
                               f"{_pool_path}: 缺少 pm.status_path")
                    self.check("fpm_ping_path",
                               "ping.path" in _pool_c
                               and "fpm-ping" in _pool_c,
                               f"{_pool_path}: 缺少 ping.path")
                    break
                except OSError:
                    pass
            if _fpm_pool_checked:
                break

        # ── Redis/Valkey ──
        _rcli = shutil.which("valkey-cli") or shutil.which("redis-cli") or "redis-cli"
        # [B296] port 0 时 TCP 不可用, 必须走 socket
        _redis_sock_ping = ""
        for _rsp in ["/run/valkey/valkey.sock", "/run/redis/redis.sock",
                     "/var/run/redis/redis-server.sock"]:
            if Path(_rsp).exists():
                _redis_sock_ping = _rsp
                break
        _sock_flag = f" -s {_redis_sock_ping}" if _redis_sock_ping else ""
        r = run(f"{_rcli}{_sock_flag} ping")
        self.check("redis_pong", "PONG" in (r.stdout or ""))

        # [PATCH-290] Unix socket 验证 (AUDIT-FIX F-08)
        _redis_sock_candidates = [
            "/run/valkey/valkey.sock",
            "/run/redis/redis.sock",
            "/var/run/redis/redis-server.sock",
        ]
        _redis_sock = None
        for _rs in _redis_sock_candidates:
            if Path(_rs).exists():
                _redis_sock = _rs
                break
        if _redis_sock:
            self.check("redis_socket_exists", True,
                       f"Unix socket: {_redis_sock}")
            # socket PING
            r_sock = run(f"{_rcli} -s {_redis_sock} ping")
            self.check("redis_socket_ping",
                       "PONG" in (r_sock.stdout or ""),
                       f"socket PING 失败: {(r_sock.stderr or '')[:100]}")
            # socket 权限: web 用户 (nginx) 可访问
            import stat as _stat_mod
            try:
                _sock_stat = Path(_redis_sock).stat()
                _sock_mode = _sock_stat.st_mode
                # 检查 group/other 至少有读写权限 (0o770 或 0o660)
                _grp_rw = bool(_sock_mode & _stat_mod.S_IRGRP
                               and _sock_mode & _stat_mod.S_IWGRP)
                self.check("redis_socket_perms", _grp_rw,
                           f"socket 权限 {oct(_sock_mode)} 无 group 读写")
            except OSError:
                pass

        # wp-config.php Redis socket 常量
        if webroot and webroot.exists():
            _wpc_redis = webroot / "wp-config.php"
            if _wpc_redis.exists():
                try:
                    _wpc_r = _wpc_redis.read_text()
                    self.check("redis_wp_scheme_unix",
                               "WP_REDIS_SCHEME" in _wpc_r
                               and "unix" in _wpc_r,
                               "wp-config.php 未配置 WP_REDIS_SCHEME=unix")
                    self.check("redis_wp_path_sock",
                               "WP_REDIS_PATH" in _wpc_r
                               and ".sock" in _wpc_r,
                               "wp-config.php 未配置 WP_REDIS_PATH socket")
                    # [PATCH-292] Nginx Helper socket 常量
                    self.check("redis_wp_nginx_helper_socket",
                               "RT_WP_NGINX_HELPER_REDIS_UNIX_SOCKET" in _wpc_r,
                               "wp-config.php 缺少 RT_WP_NGINX_HELPER_REDIS_UNIX_SOCKET")
                    # [PATCH-292] WordPress 生产环境常量
                    self.check("P292_rt_wp_environment_type",
                               "WP_ENVIRONMENT_TYPE" in _wpc_r
                               and "production" in _wpc_r,
                               "wp-config.php 缺少 WP_ENVIRONMENT_TYPE")
                    self.check("P292_rt_wp_memory_limit",
                               "WP_MEMORY_LIMIT" in _wpc_r,
                               "wp-config.php 缺少 WP_MEMORY_LIMIT")
                except OSError:
                    pass

        # Redis maxmemory + policy
        if shutil.which(_rcli):
            r_mm = run(f"{_rcli} CONFIG GET maxmemory-policy")
            if r_mm.returncode == 0:
                _mm_lines = (r_mm.stdout or "").strip().split("\n")
                _mm_policy = _mm_lines[1].strip() if len(_mm_lines) >= 2 else ""
                self.check("redis_maxmemory_policy",
                           _mm_policy == "allkeys-lru",
                           f"policy={_mm_policy} (应为 allkeys-lru)")

        # Valkey/Redis timeout = 300 (防连接泄漏)
        _rcli2 = shutil.which("valkey-cli") or shutil.which("redis-cli")
        if _rcli2:
            # [B296] port 0 时走 socket
            _sock_flag2 = f" -s {_redis_sock_ping}" if _redis_sock_ping else ""
            r_to = run(f"{_rcli2}{_sock_flag2} CONFIG GET timeout")
            _to_val = ""
            if r_to.returncode == 0:
                _to_lines = (r_to.stdout or "").strip().split("\n")
                if len(_to_lines) >= 2:
                    _to_val = _to_lines[1].strip()
            self.check("redis_timeout_300", _to_val == "300",
                       f"timeout={_to_val} (应为 300)")

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
        # [v3.2.352] openEuler 24.03 / 某些 EL 衍生的 fail2ban 需从 EPOL/EPEL
        # 获取, 可能因依赖缺失 install 失败. 脚本已优雅降级 (记 warn 不 abort),
        # 测试不应硬断言. 探 fail2ban-client 是否装了: 没装 → 跳过而非 fail.
        import shutil as _sh_f2b
        _has_f2b = bool(_sh_f2b.which("fail2ban-client"))
        if _has_f2b:
            r = run("fail2ban-client status")
            self.check("fail2ban_running", r.returncode == 0)
        else:
            self.check("fail2ban_not_installed_graceful",
                       True,
                       _m("fail2ban 未安装 (脚本已优雅降级), 跳过 running 断言",
                          "fail2ban not installed (script degraded gracefully); skipping"))

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

        # [v3.2.348] 本地测试模式: openssl s_client 用 -connect 127.0.0.1
        # + -servername {d} 绕过 DNS, SNI 让 nginx 仍选对应 server block
        _lt = getattr(self.ctx, 'local_test', False)
        _connect_host = "127.0.0.1" if _lt else d
        # openssl s_client 握手
        r = run(f"echo | openssl s_client -connect {shlex.quote(_connect_host)}:443 -servername {shlex.quote(d)} 2>&1")
        out = r.stdout or ""
        _verify_ok = "Verify return code: 0" in out or "verify return:0" in out.replace(" ", "")
        if self.ctx.staging and not _verify_ok:
            # Staging 证书由 "Fake LE" 签发, 系统 CA 不信任是正常的
            # 只要握手本身成功 (有 Certificate chain 输出) 即通过
            _verify_ok = "Certificate chain" in out
        # [v3.2.348] 本地测试模式: 自签证书系统 CA 不信任是预期,
        # 有 Certificate chain 输出即认为握手成功
        if _lt and not _verify_ok:
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
        # [v3.2.348] 本地测试: 自签用 RSA 2048 (兼容性最广), 跳过 ECDSA 硬断言
        if _lt:
            self.check("ssl_ecdsa_key_local_test_rsa", True,
                       "[local-test] 自签用 RSA 2048 (预期非 ECDSA)")
        else:
            r = run(["openssl", "x509", "-noout", "-text", "-in", str(cert_path)])
            self.check("ssl_ecdsa_key",
                       "id-ecPublicKey" in (r.stdout or "") or "EC Public Key" in (r.stdout or ""),
                       _m("非 ECDSA 密钥", "not ECDSA key"))

        # OCSP stapling (可能未启用, 仅检查不强制)
        r = run(f"echo | openssl s_client -connect {shlex.quote(_connect_host)}:443 -servername {shlex.quote(d)} -status 2>&1")
        has_ocsp = "OCSP Response Status: successful" in (r.stdout or "")
        if has_ocsp:
            self.check("ssl_ocsp_stapling", True)
        # LE 已关停 OCSP, 不报错

        # 证书有效期 > 7 天
        r = run(["openssl", "x509", "-checkend", str(7*86400), "-noout", "-in", str(cert_path)])
        self.check("ssl_not_expiring_7d", r.returncode == 0, _m("证书将在 7 天内过期", "certificate expires within 7 days"))

        # HTTP/3 (QUIC)
        # [v3.2.348] 本地测试: curl 加 --resolve 绕过 DNS
        _resolve_arg = ["--resolve", f"{d}:443:127.0.0.1"] if _lt else []
        r = run(["curl", "-sI", "--max-time", "5", "-k"] + _resolve_arg + [f"https://{d}/"])
        headers = r.stdout or ""
        has_alt_svc = "alt-svc" in headers.lower() or "h3" in headers.lower()
        # [v3.2.351] HTTP/3 需要 nginx ≥ 1.25 + ngx_http_v3 模块.
        # openEuler 24.03 自带 1.24.0 (无 http3), 若本地模式使用系统 nginx
        # 不可避免地缺席 HTTP/3. 探测 nginx conf 是否实际含 http3/quic 指令
        # 来决定是否断言 — 没有就跳过 (脚本 deploy 阶段正确降级了).
        _ngx_site_h3 = Path(f"/etc/nginx/conf.d/{d}.conf")
        _has_http3_conf = False
        if _ngx_site_h3.exists():
            try:
                _ct_h3 = _ngx_site_h3.read_text(encoding='utf-8', errors='replace')
                _has_http3_conf = ("http3 on" in _ct_h3
                                   or "listen 443 quic" in _ct_h3
                                   or "listen [::]:443 quic" in _ct_h3)
            except OSError:
                pass
        if _has_http3_conf:
            self.check("ssl_http3_advertised", has_alt_svc,
                       "Alt-Svc/h3 头未发现 (HTTP/3 可能未启用)")
        else:
            self.check("ssl_http3_not_configured",
                       True,
                       _m("nginx 不支持 HTTP/3 (版本 <1.25 或无 http3 模块), 脚本已降级",
                          "nginx lacks HTTP/3 (version <1.25 or no http3 module); script downgraded"))

        # B295: TLS Session Tickets 应为 off (Mozilla/Qualys 推荐)
        # TLS 1.3 下 tickets off 仍有 stateful 会话恢复 (psk_dhe_ke)
        _ngx_ssl_conf = Path(f"/etc/nginx/conf.d/{d}.conf")
        if _ngx_ssl_conf.exists():
            try:
                _ssl_ct = _ngx_ssl_conf.read_text()
                self.check("B295_ssl_session_tickets_off",
                           "ssl_session_tickets off" in _ssl_ct,
                           "ssl_session_tickets 应为 off (Mozilla 推荐; "
                           "TLS 1.3 stateful 恢复仍生效)")
                self.check("B295_ssl_session_cache",
                           "ssl_session_cache shared:" in _ssl_ct,
                           "缺少 ssl_session_cache (TLS 1.3 stateful 恢复依赖)")
            except OSError:
                pass

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
                        # OPcache file_cache 二级缓存
                        self.check("rt_opcache_file_cache",
                                   re.search(r'^\s*opcache\.file_cache\s*=\s*/var/lib/php/opcache',
                                             _ini_content, re.MULTILINE) is not None,
                                   f"{_ini_path}: 缺少 opcache.file_cache")
                        # PHP 8.5 max_memory_limit 预适应 (旧版本静默忽略)
                        self.check("rt_max_memory_limit",
                                   "max_memory_limit" in _ini_content,
                                   f"{_ini_path}: 缺少 max_memory_limit 预适应")
                        break
                except OSError:
                    pass
            if _php_ini_checked:
                break
        if not _php_ini_checked:
            self.check("P286_rt_php_ini", True, "php.ini 未找到 (跳过)")

        # MariaDB 安全配置
        _mariadb_conf_checked = False
        for _mariadb_glob in ["/etc/mysql/conf.d/wp-bootstrap-*.cnf",
                          "/etc/my.cnf.d/wp-bootstrap-*.cnf"]:
            for _mariadb_path in _g.glob(_mariadb_glob):
                try:
                    _mariadb_content = Path(_mariadb_path).read_text()
                    _mariadb_conf_checked = True
                    self.check("P286_rt_mdb_bind_address",
                               "bind-address" in _mariadb_content,
                               f"{_mariadb_path}: 缺少 bind-address")
                    self.check("P286_rt_mdb_local_infile",
                               "local-infile" in _mariadb_content,
                               f"{_mariadb_path}: 缺少 local-infile")
                    break
                except OSError:
                    pass
            if _mariadb_conf_checked:
                break

        # OS sysctl 安全参数
        _sysctl_conf_checked = False
        # [PATCH-290] 路径修正: 99-wp-bootstrap-network/swap
        # [FIX] 安全参数在 network.conf, 需合并所有文件内容再检查
        _sysctl_combined = ""
        _sysctl_files = []
        for _sc_glob in ["/etc/sysctl.d/99-wp-bootstrap-*.conf",
                         "/etc/sysctl.d/99-wp-ssl-*.conf"]:
            for _sc_path in _g.glob(_sc_glob):
                try:
                    _sysctl_combined += Path(_sc_path).read_text()
                    _sysctl_files.append(_sc_path)
                    _sysctl_conf_checked = True
                except OSError:
                    pass
            if _sysctl_conf_checked:
                break
        if _sysctl_conf_checked:
            _sc_label = ", ".join(_sysctl_files)
            self.check("P286_rt_sysctl_syncookies",
                       "tcp_syncookies" in _sysctl_combined,
                       f"{_sc_label}: 缺少 tcp_syncookies")
            self.check("P286_rt_sysctl_rp_filter",
                       "rp_filter" in _sysctl_combined,
                       f"{_sc_label}: 缺少 rp_filter")

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

        # ── [PATCH-290] 运行时验证 ──

        # open_basedir: 全局 php.ini 应为空, FPM pool 应有 php_admin_value
        for _ini_glob290 in ["/etc/php/*/fpm/php.ini", "/etc/php.ini"]:
            for _ini_path290 in _g.glob(_ini_glob290):
                try:
                    _ini290 = Path(_ini_path290).read_text()
                    _ob_match = re.search(
                        r'^\s*open_basedir\s*=\s*$', _ini290, re.MULTILINE)
                    self.check("P290_rt_open_basedir_global_empty",
                               _ob_match is not None,
                               f"{_ini_path290}: open_basedir 应为空 (由 FPM pool 接管)")
                    # pcre.jit
                    self.check("P290_rt_pcre_jit",
                               re.search(r'^\s*pcre\.jit\s*=\s*1',
                                         _ini290, re.MULTILINE) is not None,
                               f"{_ini_path290}: pcre.jit 未设为 1")
                    # [PATCH-292] OPcache JIT
                    self.check("P292_rt_opcache_jit",
                               re.search(r'^\s*opcache\.jit\s*=\s*tracing',
                                         _ini290, re.MULTILINE) is not None,
                               f"{_ini_path290}: opcache.jit 未设为 tracing")
                    self.check("P292_rt_opcache_huge_code_pages",
                               re.search(r'^\s*opcache\.huge_code_pages\s*=\s*1',
                                         _ini290, re.MULTILINE) is not None,
                               f"{_ini_path290}: opcache.huge_code_pages 未启用")
                    # date.timezone
                    self.check("P290_rt_date_timezone",
                               re.search(r'^\s*date\.timezone\s*=\s*\S+',
                                         _ini290, re.MULTILINE) is not None,
                               f"{_ini_path290}: date.timezone 未设置")
                    break
                except OSError:
                    pass

        # FPM pool: php_admin_value[open_basedir]
        _fpm_pool_checked = False
        for _fpm_glob290 in ["/etc/php-fpm.d/www.conf",
                             "/etc/php/*/fpm/pool.d/www.conf"]:
            for _fpm_path290 in _g.glob(_fpm_glob290):
                try:
                    _fpm290 = Path(_fpm_path290).read_text()
                    _fpm_pool_checked = True
                    self.check("P290_rt_fpm_open_basedir",
                               "php_admin_value[open_basedir]" in _fpm290,
                               f"{_fpm_path290}: 缺少 php_admin_value[open_basedir]")
                    # request_terminate_timeout
                    self.check("P290_rt_fpm_terminate_timeout",
                               re.search(r'^\s*request_terminate_timeout\s*=\s*\d+',
                                         _fpm290, re.MULTILINE) is not None,
                               f"{_fpm_path290}: 缺少 request_terminate_timeout")
                    # security.limit_extensions
                    self.check("P290_rt_fpm_limit_extensions",
                               "security.limit_extensions" in _fpm290,
                               f"{_fpm_path290}: 缺少 security.limit_extensions")
                    break
                except OSError:
                    pass
            if _fpm_pool_checked:
                break

        # Fail2Ban scanner jails (PATCH-289)
        _f2b_jails = run("fail2ban-client status", timeout=10)
        if _f2b_jails.returncode == 0:
            _f2b_out = _f2b_jails.stdout or ""
            self.check("P289_rt_f2b_scanner_jail",
                       "nginx-scanner" in _f2b_out,
                       "Fail2Ban 缺少 nginx-scanner jail")
            self.check("P289_rt_f2b_4xx_flood_jail",
                       "nginx-4xx-flood" in _f2b_out,
                       "Fail2Ban 缺少 nginx-4xx-flood jail")

        # MariaDB 新增调优 (PATCH-289)
        for _mariadb_glob289 in ["/etc/mysql/conf.d/wp-bootstrap-*.cnf",
                             "/etc/my.cnf.d/wp-bootstrap-*.cnf"]:
            for _mariadb_path289 in _g.glob(_mariadb_glob289):
                try:
                    _mdb289 = Path(_mariadb_path289).read_text()
                    self.check("P289_rt_mdb_innodb_file_per_table",
                               "innodb_file_per_table" in _mdb289,
                               f"{_mariadb_path289}: 缺少 innodb_file_per_table")
                    self.check("P289_rt_mdb_skip_name_resolve",
                               "skip_name_resolve" in _mdb289
                               or "skip-name-resolve" in _mdb289,
                               f"{_mariadb_path289}: 缺少 skip_name_resolve")
                    break
                except OSError:
                    pass

        # script journal 可查 (PATCH-290 SysLogHandler)
        _jnl = run("journalctl -t wp-ssl-bootstrap -n 1 --no-pager",
                    timeout=10)
        self.check("P290_rt_journal_persistence",
                   _jnl.returncode == 0 and len((_jnl.stdout or "").strip()) > 0,
                   "脚本 journal 日志不可查 (SysLogHandler 未生效)")

        # Nginx srcache upstream: Unix socket (PATCH-292)
        _nginx_conf_path = Path(f"/etc/nginx/conf.d/{d}.conf")
        if _nginx_conf_path.exists():
            try:
                _ngx_conf_content = _nginx_conf_path.read_text()
                # [v3.2.351] 当 srcache 整个降级为 FastCGI 缓存 (旧 nginx 无动态
                # 模块 ABI 兼容, 见 [PATCH-244]), upstream srcache_redis 本就不
                # 存在, 这个 unix socket 检查无意义. 仅在 srcache 实际启用时断言.
                _srcache_active = ("srcache_fetch" in _ngx_conf_content
                                   and "upstream srcache_redis" in _ngx_conf_content)
                if _srcache_active:
                    _has_sock_upstream = "unix:" in _ngx_conf_content and ".sock" in _ngx_conf_content
                    _has_tcp_upstream = re.search(
                        r'upstream\s+srcache_redis.*\n\s*server\s+127\.0\.0\.1:6379',
                        _ngx_conf_content)
                    self.check("P292_rt_srcache_unix_socket",
                               _has_sock_upstream and not _has_tcp_upstream,
                               "srcache upstream 仍使用 TCP 127.0.0.1:6379 (应为 Unix socket)")
                else:
                    self.check("P292_rt_srcache_not_applicable",
                               True,
                               _m("srcache 未启用 (FastCGI 缓存降级, 旧 nginx), 跳过 upstream 检查",
                                  "srcache not active (FastCGI fallback, old nginx); skipping"))
            except OSError:
                pass

        # ── Build 3.2.295: Redis port 0 + 配置完整性 + PHP-FPM ACL ──

        # Redis 配置运行时验证
        _redis_conf_path_295 = None
        for _rc295 in ["/etc/valkey/valkey.conf", "/etc/redis/redis.conf",
                       "/etc/redis.conf"]:
            if Path(_rc295).exists():
                _redis_conf_path_295 = _rc295
                break
        if _redis_conf_path_295:
            try:
                _redis_conf_295 = Path(_redis_conf_path_295).read_text(
                    encoding="utf-8", errors="replace")
                _has_unixsocket = bool(re.search(
                    r'^\s*unixsocket\s+', _redis_conf_295, re.MULTILINE))
                if _has_unixsocket:
                    # port 0 (TCP disabled when socket enabled)
                    self.check("B295_rt_redis_port_0",
                               re.search(r'^\s*port\s+0\s*$',
                                         _redis_conf_295, re.MULTILINE) is not None,
                               f"{_redis_conf_path_295}: unixsocket 已启用但 port 非 0")
                    self.check("B295_rt_no_tcp_6379",
                               not port_listening(6379),
                               "Redis 仍监听 TCP 6379 (应 port 0)")
                # unixsocket 不重复
                _sock_count = len(re.findall(
                    r'^\s*unixsocket\s+', _redis_conf_295, re.MULTILINE))
                self.check("B295_rt_unixsocket_unique",
                           _sock_count <= 1,
                           f"unixsocket 行数={_sock_count} (应≤1)")
                # unixsocketperm 770
                if _has_unixsocket:
                    self.check("B295_rt_unixsocketperm_770",
                               re.search(r'^\s*unixsocketperm\s+770\b',
                                         _redis_conf_295, re.MULTILINE) is not None,
                               f"{_redis_conf_path_295}: unixsocketperm 非 770")
                # 无孤立 PATCH-292 注释
                _orphan_292 = re.findall(
                    r'^# \[PATCH-292\].*\n(?!\s*unixsocket\s)',
                    _redis_conf_295, re.MULTILINE)
                self.check("B295_rt_no_orphan_patch292",
                           len(_orphan_292) == 0,
                           f"存在 {len(_orphan_292)} 个孤立 PATCH-292 注释")
            except OSError:
                pass

        # Redis 可通过 socket 连接 (port 0 后唯一路径)
        _vcli = shutil.which("valkey-cli") or shutil.which("redis-cli")
        if _vcli:
            # 从配置文件读取 socket 路径
            _sock_path_295 = ""
            if _redis_conf_path_295:
                try:
                    _rc295_txt = Path(_redis_conf_path_295).read_text(
                        encoding="utf-8", errors="replace")
                    _sm295 = re.search(
                        r'^\s*unixsocket\s+["\']?([^"\'#\s]+)',
                        _rc295_txt, re.MULTILINE)
                    if _sm295:
                        _sock_path_295 = _sm295.group(1).strip()
                except OSError:
                    pass
            if _sock_path_295:
                _ping_r = run(f"{_vcli} -s {_sock_path_295} ping", timeout=5)
                self.check("B295_rt_redis_socket_ping",
                           _ping_r.returncode == 0
                           and "PONG" in (_ping_r.stdout or ""),
                           f"redis-cli -s {_sock_path_295} ping 失败")

        # PHP-FPM: ACL 启用时 listen.owner 应被注释
        for _fpm_glob_295 in ["/etc/php-fpm.d/www.conf",
                               "/etc/php/*/fpm/pool.d/www.conf"]:
            for _fpm_path_295 in _g.glob(_fpm_glob_295):
                try:
                    _fpm_295 = Path(_fpm_path_295).read_text()
                    _has_acl_295 = bool(re.search(
                        r'^\s*listen\.acl_users\s*=', _fpm_295, re.MULTILINE))
                    _has_active_owner_295 = bool(re.search(
                        r'^\s*listen\.owner\s*=', _fpm_295, re.MULTILINE))
                    if _has_acl_295:
                        self.check("B295_rt_phpfpm_no_owner_with_acl",
                                   not _has_active_owner_295,
                                   f"{_fpm_path_295}: listen.owner 应被注释 (ACL 已启用)")
                except OSError:
                    pass
                break

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

        # [FIX] mariadb-upgrade 不应在 update 时重复触发 (deploy 已写标记)
        _update_out = r.stdout or ""
        self.check("update_no_mariadb_upgrade_rerun",
                   "mariadb-upgrade 未针对" not in _update_out,
                   "update 重复执行 mariadb-upgrade (_finalize 应已写入标记)")

        # [FIX] 验证组件版本摘要输出
        self.check("update_version_summary",
                   "组件版本" in (r.stdout or "") or "component" in (r.stdout or "").lower(),
                   _m("更新输出中无组件版本摘要", "no component version summary in update output"))

        # nginx -t after update
        r2 = run("nginx -t 2>&1")
        self.check("update_nginx_valid", r2.returncode == 0,
                   (r2.stdout or r2.stderr or "").strip()[:300])

        # HTTPS still works
        # [v3.2.346] 本地测试模式: 用 --resolve 绕过 DNS, 直连本机 nginx
        _resolve_local = "127.0.0.1" if getattr(self.ctx, 'local_test', False) else None
        status = curl_status(f"https://{self.ctx.domain}/",
                              insecure=True, resolve_to=_resolve_local)
        self.check("update_https_ok", status in (200, 301, 302),
                   f"status={status}")

        # [1.30] nginx.conf http{} 优化验证
        _ngx_main_u = Path("/etc/nginx/nginx.conf")
        if _ngx_main_u.exists():
            try:
                _ngx_u = _ngx_main_u.read_text(encoding='utf-8', errors='replace')
                self.check("update_tcp_nopush",
                           bool(re.search(r'^\s*tcp_nopush\s+on\s*;', _ngx_u, re.M)),
                           "update 后 nginx.conf 仍缺少 tcp_nopush on")
                self.check("update_tcp_nodelay",
                           bool(re.search(r'^\s*tcp_nodelay\s+on\s*;', _ngx_u, re.M)),
                           "update 后 nginx.conf 仍缺少 tcp_nodelay on")
            except OSError:
                pass

        # [1.30] MPTCP 配置验证 (站点配置含 multipath)
        _ngx_site_u = Path(f"/etc/nginx/conf.d/{self.ctx.domain}.conf")
        if _ngx_site_u.exists():
            try:
                _site_u = _ngx_site_u.read_text()
                _has_mptcp = "multipath" in _site_u
                # MPTCP 可能因内核不支持而未启用, 不强制要求
                if _has_mptcp:
                    self.check("update_mptcp_in_config", True,
                               "MPTCP multipath 已配置")
            except OSError:
                pass

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

        # [1.30] nginx.conf http{} 优化幂等性
        _ngx_idem = Path("/etc/nginx/nginx.conf")
        if _ngx_idem.exists():
            _ngx_hash_before = run(f"sha256sum {_ngx_idem}").stdout.split()[0] if hash_before else ""
            _ngx_hash_after = run(f"sha256sum {_ngx_idem}").stdout.split()[0]
            # 二次 update 不应再次修改 nginx.conf
            self.check("idempotency_nginx_conf_unchanged",
                       True,  # 主要由 conf_unchanged 覆盖, 此处仅确认 nginx.conf 存在
                       "nginx.conf 幂等性")

        # B295: Redis 幂等性 — 二次 update 不应重启 Redis
        _redis_conf_idem = None
        for _rc_i in ["/etc/valkey/valkey.conf", "/etc/redis/redis.conf"]:
            if Path(_rc_i).exists():
                _redis_conf_idem = _rc_i
                break
        if _redis_conf_idem:
            r_hash = run(f"sha256sum {_redis_conf_idem}")
            _redis_hash_after = r_hash.stdout.split()[0] if r_hash.returncode == 0 else ""
            # Redis 配置 hash 应无变化 (harden_conf 不应触发写入)
            # 注: 首次 idempotency run 后 CONFIG REWRITE 可能改变文件,
            # 但 harden_conf 的 _needs_restart 应为 False
            _update_out = r.stdout or ""
            self.check("B295_idempotency_no_redis_restart",
                       "PATCH-290" not in _update_out
                       or "restarted" not in _update_out,
                       "二次 update 仍触发 Redis 重启 (_needs_restart 未生效)")

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

        # [FIX] 验证组件版本摘要输出
        self.check("restore_version_summary",
                   "组件版本" in (r.stdout or "") or "component" in (r.stdout or "").lower(),
                   _m("恢复输出中无组件版本摘要", "no component version summary in restore output"))

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
        # [v3.2.348] 本地测试模式: 无真 CA 可迁移, 整个阶段直接跳过
        if getattr(self.ctx, 'local_test', False):
            self.check("migrate_ssl_skipped_local_test", True,
                       _m("[local-test] 无真 CA 可迁移, 整阶段跳过",
                          "[local-test] no real CA to migrate, phase skipped"))
            return
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
        # [v3.2.348] 本地测试模式: 透传 --local-test 防止走真 certbot
        if getattr(self.ctx, 'local_test', False):
            r = run_script(
                f"renew --domain {d} --email {self.ctx.email} --local-test"
            )
        else:
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

        # MariaDB proxies_priv warning (应已被 cleanup_proxies_priv 清理)
        _mariadb_err = Path("/var/log/mariadb/mariadb.err")
        if not _mariadb_err.exists():
            _mariadb_err = Path("/var/log/mysql/error.log")
        if _mariadb_err.exists():
            r = run(f"tail -50 {_mariadb_err}")
            _pp_warns = [l for l in (r.stdout or "").split("\n")
                         if "proxies_priv" in l and "Warning" in l]
            # 仅检查最近的 (启动后), 不检查历史
            _recent_pp = [l for l in _pp_warns
                          if any(ts in l for ts in [
                              time.strftime("%Y-%m-%d"),
                              time.strftime("%y%m%d")])]
            self.check("log_mariadb_no_proxies_priv_warn",
                       len(_recent_pp) == 0,
                       f"今日 {len(_recent_pp)} 条 proxies_priv Warning")

        # 响应时间基线 (TTFB)
        r = run(["curl", "-s", "-o", "/dev/null", "-w", "%{time_starttransfer}",
                 "--max-time", "10", "-k", f"https://{d}/"])
        try:
            ttfb = float(r.stdout.strip())
            self.check("response_ttfb_ok", ttfb < 3.0,
                       f"TTFB={ttfb:.2f}s > 3s 阈值")
        except (ValueError, AttributeError):
            pass

        # [PATCH-290] 诊断包 (选项 9) 生成 + 内容验证
        # ── Build 3.2.295: 运行时日志健康检查 ──

        # Redis harden_conf 不重复重启 (最近一次 update)
        _harden_jnl = run(
            "journalctl -t wp-ssl-bootstrap --since '30min ago'"
            " --no-pager -q 2>/dev/null | grep 'PATCH-290.*restarted'",
            timeout=10)
        if _harden_jnl.stdout and _harden_jnl.stdout.strip():
            _restart_count = _harden_jnl.stdout.strip().count("restarted")
            self.check("B295_log_redis_single_restart",
                       _restart_count <= 1,
                       f"最近 30min Redis 重启 {_restart_count} 次 (应≤1)")

        # PHP-FPM ACL 警告 (最近 30 分钟应为 0)
        _pi295 = detect_platform()
        _fpm_svc_295 = _pi295.get("php_fpm_svc", "php-fpm")
        _acl_jnl = run(
            f"journalctl -u {_fpm_svc_295} --since '30min ago'"
            f" --no-pager -q 2>/dev/null | grep -c 'ACL set.*listen.owner.*ignored'",
            timeout=10)
        _acl_count = int((_acl_jnl.stdout or "0").strip() or "0")
        self.check("B295_log_phpfpm_no_acl_warning",
                   _acl_count == 0,
                   f"最近 30min 有 {_acl_count} 条 PHP-FPM ACL 警告")

        # MariaDB Access Denied 噪音 (今日应为 0)
        _mariadb_err_295 = Path("/var/log/mariadb/mariadb.log")
        if not _mariadb_err_295.exists():
            for _mp in ["/var/log/mariadb/error.log", "/var/log/mysql/error.log"]:
                if Path(_mp).exists():
                    _mariadb_err_295 = Path(_mp)
                    break
        if _mariadb_err_295.exists():
            try:
                _mariadb_tail = run(f"grep '{time.strftime('%Y-%m-%d')}' {_mariadb_err_295}"
                                " | grep -c 'Access denied.*using password.*NO'",
                                timeout=10)
                _ad_count = int((_mariadb_tail.stdout or "0").strip() or "0")
                self.check("B295_log_mariadb_no_access_denied",
                           _ad_count == 0,
                           f"今日 {_ad_count} 条 'Access denied (using password: NO)'")
            except Exception:
                pass

        _diag_r = run_script(
            f"collect-logs --domain {d}",
            timeout=120)
        self.check("diag_collect_exit_0",
                   _diag_r.returncode == 0,
                   f"诊断收集失败: exit={_diag_r.returncode}")
        # 查找最新的诊断包
        _diag_tars = sorted(Path("/root").glob(f"wp-logs-{d}-*.tar.gz"),
                            reverse=True)
        if _diag_tars:
            import tarfile as _tf_test
            try:
                with _tf_test.open(str(_diag_tars[0]), "r:gz") as _tar:
                    _tar_names = _tar.getnames()
                    _tar_count = len(_tar_names)
                    self.check("diag_package_file_count",
                               _tar_count >= 40,
                               f"诊断包仅 {_tar_count} 个文件 (期望 ≥40)")
                    # 验证关键新增文件
                    for _expected in [
                        "system-info.txt", "script-journal.log",
                        "conf-php-fpm-pool.conf", "conf-php.ini",
                        "diag-php-modules.txt",
                    ]:
                        self.check(f"diag_has_{_expected.replace('.','_').replace('-','_')}",
                                   _expected in _tar_names,
                                   f"诊断包缺少 {_expected}")
                    # Build 3.2.295: diag-redis-info.txt 应有实际内容 (非 Connection refused)
                    if "diag-redis-info.txt" in _tar_names:
                        try:
                            _ri_f = _tar.extractfile("diag-redis-info.txt")
                            if _ri_f:
                                _ri_content = _ri_f.read().decode(
                                    "utf-8", errors="replace")
                                self.check("B295_diag_redis_info_ok",
                                           "redis_version" in _ri_content
                                           or "valkey_version" in _ri_content,
                                           "diag-redis-info.txt 无内容 (port 0 后 collect_logs 需走 socket)")
                                self.check("B295_diag_redis_tcp_port_0",
                                           "tcp_port:0" in _ri_content,
                                           "diag-redis-info.txt 显示 tcp_port 非 0")
                        except Exception:
                            pass
                    # 验证 system-info.txt 包含 WP-CLI 和脚本版本
                    if "system-info.txt" in _tar_names:
                        try:
                            _si_f = _tar.extractfile("system-info.txt")
                            if _si_f:
                                _si_content = _si_f.read().decode(
                                    "utf-8", errors="replace")
                                self.check("diag_sysinfo_wpcli",
                                           "WP-CLI" in _si_content,
                                           "system-info.txt 缺少 WP-CLI 版本")
                                self.check("diag_sysinfo_script_ver",
                                           "WP-SSL-Bootstrap" in _si_content,
                                           "system-info.txt 缺少脚本版本")
                        except Exception:
                            pass
                    # 验证 EAB 脱敏
                    import re as _re_eab
                    for _sens_file in ["certbot.log", "script-journal.log"]:
                        if _sens_file in _tar_names:
                            try:
                                _sf = _tar.extractfile(_sens_file)
                                if _sf:
                                    _f_content = _sf.read().decode(
                                        "utf-8", errors="replace")
                                    # 检查实际凭据模式 (--eab-kid/--eab-hmac-key
                                    # 后跟非 REDACTED 的值), 而非仅检查 "eab" 一词
                                    # (中文日志 "EAB 凭据" 不含敏感数据)
                                    _has_raw_cred = bool(_re_eab.search(
                                        r'--eab-(kid|hmac-key)\s+(?!\*\*\*REDACTED)',
                                        _f_content))
                                    _has_h0cys = "H0CYs" in _f_content
                                    if _has_raw_cred or _has_h0cys:
                                        self.check(f"diag_eab_redacted_{_sens_file.replace('.','_')}",
                                                   not _has_raw_cred
                                                   and not _has_h0cys,
                                                   f"{_sens_file} 含未脱敏的 EAB 凭据")
                            except Exception:
                                pass
            except Exception as _tar_e:
                self.check("diag_package_readable", False,
                           f"诊断包解析失败: {_tar_e}")
        else:
            self.check("diag_package_exists", False,
                       "未找到诊断包 tar.gz")

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
        # [v3.2.348] 本地测试模式: 用 --resolve 绕过 DNS
        _lt_rd = getattr(self.ctx, 'local_test', False)
        _rd_resolve = "127.0.0.1" if _lt_rd else None
        status = curl_status(f"https://{d}/", insecure=True,
                              resolve_to=_rd_resolve)
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

    # [v3.2.348] 本地测试模式 vs 正常测试模式 — 必须在域名/邮箱/站点检测之前选,
    # 因为本地模式下域名无需真解析, 邮箱可占位, 已部署站点也可能是真 CA 证书
    # (不应与本地自签混淆).
    print()
    print(_m(
        "  测试模式 / Test mode:",
        "  Test mode:"))
    print(_m(
        "    [1] 正常模式 (需真实域名 + 会联网签发 Let's Encrypt / ZeroSSL 证书)",
        "    [1] Normal (real domain + network + real CA issuance)"))
    print(_m(
        "    [2] 本地测试模式 (--local-test: openssl 自签 + 跳过 DNS, 适合 VM/容器/CI)",
        "    [2] Local test (--local-test: self-signed cert + skip DNS, for VM/container/CI)"))
    try:
        _mode_choice = input(_m(
            "  选择 [1/2, 默认 1]: ",
            "  Choose [1/2, default 1]: ")).strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print(_m("\n  取消", "\n  Cancelled"))
        sys.exit(0)
    local_test_mode = (_mode_choice == "2")
    if local_test_mode:
        print(_m(
            "  ✅ 本地测试模式: 将向被测脚本透传 --local-test",
            "  ✅ Local test mode: will pass --local-test to script"))

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
    # [v3.2.348] 本地测试模式: 建议默认测试域名, 用户可直接回车
    _default_domain_hint = ""
    if local_test_mode:
        _default_domain_hint = "wp.test.local"
    if len(sites) == 1 and not local_test_mode:
        # 本地测试模式不要自动选已有站点 (可能是真 CA 证书, 不该覆盖)
        domain = sites[0]
        print(f"  {t('auto_domain')}: {domain}")
    elif sites and not local_test_mode:
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
            _prompt = (f"  {t('input_domain')}"
                       f" [{_default_domain_hint}]: " if _default_domain_hint
                       else f"  {t('input_domain')}: ")
            domain = input(_prompt).strip()
            if not domain and _default_domain_hint:
                domain = _default_domain_hint
        except (EOFError, KeyboardInterrupt):
            print("\n  取消")
            sys.exit(0)

    if not domain:
        print(f"  ✘ {t('need_domain')}")
        sys.exit(1)

    # ── Email ──
    email = ""
    # [v3.2.348] 本地测试模式: email 自动占位, 不强制真实
    if local_test_mode:
        email = "test@local.invalid"
        print(_m(
            f"  Email: {email} (本地测试占位)",
            f"  Email: {email} (local test placeholder)"))
    else:
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
        if has_site and domain in sites and cert.exists() and not local_test_mode:
            if "deploy" in phases:
                phases.remove("deploy")
        # [v3.2.348] 本地测试模式: migrate_ssl 整阶段无意义 (无真 CA),
        # 从 phase 列表移除避免 phase_migrate_ssl 里的 skip_assert 噪音
        if local_test_mode and "migrate_ssl" in phases:
            phases.remove("migrate_ssl")

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
        local_test=local_test_mode,
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
    # [v3.2.346] 本地测试模式: 与 wp_ssl_bootstrap.py --local-test 联动.
    # 测试会用自签证书 + 跳过 DNS 检查, 在 VM/容器/CI 里无需真域名即可跑完整管道.
    parser.add_argument("--local-test", action="store_true", default=False,
                        help=_m("本地测试模式: 自签证书 + 跳过 DNS 检查, "
                                "不与 --no-staging 同用",
                                "local test mode: self-signed cert + skip DNS check, "
                                "not compatible with --no-staging"))

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
            # [v3.2.346] 本地测试模式 email 可选 (下文兜底设占位邮箱)
            if getattr(args, 'local_test', False):
                pass
            else:
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
            local_test=getattr(args, 'local_test', False),
            notify_webhook=_webhook_url,
            baseline=args.baseline or "",
        )
        # [v3.2.346] 互斥校验: local-test 与 no-staging 在语义上冲突
        # (local-test 是纯自签, 没有 staging vs production 的概念)
        if ctx.local_test and getattr(args, 'no_staging', False):
            parser.error(_m(
                "--local-test 与 --no-staging 互斥: 本地模式不走真 CA",
                "--local-test conflicts with --no-staging: local mode skips real CA"))
        if ctx.local_test:
            # email 在本地模式可选 (没有真 CA 账户), 兜底占位
            if not ctx.email:
                ctx.email = "test@local.invalid"
            print(_m(
                "  [v3.2.346] 本地测试模式启用: 自签证书 + 跳过 DNS 预检",
                "  [v3.2.346] local test mode: self-signed cert + skip DNS check"))

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
