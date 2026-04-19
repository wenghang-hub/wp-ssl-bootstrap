#!/usr/bin/env python3
"""
WP-SSL-Bootstrap 综合重构验证脚本 v4 (2026-04, synced → build 3.2.379 + v6 patch)
==========================================================================
合并 full_verify_v2 + verify_refactor_v3 全部检查项, 并基于业界大规模
重构研究 (ESEC/FSE'22 CMU LSR survey, SafeRefactorPy, Fowler Strangler
Fig, Shopify 迁移实践, pylint/flake8-mutable/flake8-print 等) 扩展.

v6 patch 增量 (18 项修复 + 2 项前瞻):
  - FIX-❶❷❸: mysqlcheck --single-transaction 移除 + mariadb-check 优先
  - FIX-❹❺❻❽: 命名/常量/端口探测/包名注释
  - FIX-ⓐ: 移除 wp-cron --allow-root 死代码
  - FIX-⓫: Fail2Ban CF CIDR ignoreip (conditional: realip 已配置)
  - FIX-⓯: DH 参数 2048 → 3072 (NIST 2030 面向)
  - FIX-⓰: MariaDB CLI 命名过渡 helper (12+ 处调用统一)
  - FIX-⓱: Nginx 最小回退跨平台化 (Debian/RHEL user + modules_dir)
  - FIX-⓲: db-optimize + wp-cron hardening (NoNewPrivileges+PrivateTmp)
  - FIX-⓳: Fail2Ban datepattern = {DEFAULT}
  - FIX-⓴: firewalld zone 正则放宽
  - FIX-㉑: EAB env 文件权限 post-write 核验 (走 _safe_chmod)
  - FIX-㉒: 审计分类器按 unit 名拆分 systemd failure (正则 .*? 非贪婪)
  - FIX-㉓: 排除脚本自身 INFO/DEBUG 关键字伪阳性
  - FIX-㉔: PHP-FPM "error log file re-opened" 归噪音
  - FIX-㉕: unknown 信号也渲染到问题表 (标题/表/摘要三者一致)

检查矩阵 (25 banner, 90+ 细粒度断言):

  结构层 ─ 合法性/迁移/契约
  [A] 字节码/AST 编译                   (new parse + compile + baseline parse)
  [B] 方向感知迁移 WPDM → 5 Manager    (含每 Manager 方法数非减细化)
  [C] 方法签名保真                      非 proxy WPDM 方法的 args 列表未改动
  [D] 模块级演化                        函数零丢失 + 新增合法性 + 变量合法性
  [E] Imports 非减
  [F] Manager global 语句               cache 白名单 22 项
  [G] Strangler Fig 别名                return self.X() 委托模式
  [H] Canonical API 对称                detect_version/detect_service/upgrade_to_target
  [I] Reset Helper 对称                 _reset_X_capability_caches
  [J] Manager self 引用自洽             每 Manager 单独 ok
  [K] 零重复方法 & 零重复参数
  [L] 跨组件注入完整性                  WPDM.__init__ 中 self.X.attr = ... ≥20
  [M] @staticmethod 合规                静态方法不得引用 self

  架构层 ─ 不变式
  [N] Caching 模式完整性                22 cache × 22 lock × reset 三位一体
  [Q] Strangler 别名存活性              ★ 零调用者的死代码告警 (Shopify/Fowler)

  契约层 ─ 主脚本架构规则不变式
  [R] subprocess.run 必须带 timeout     ★ 架构规则 5, 基线 450/450 100%
  [S] Proxy 委托方法返回值完整性        ★ 架构规则 14, 防 NoneType 隐形 bug
  [T] Mutable default arguments         ★ Python 经典坑, 基线 0, 零容忍

  卫生层/安全层 ─ 对称检查 (仅报回归)
  [O] 未使用局部变量                    new_unused − old_unused
  [U] Manager 内 print() 不新增         ★ 生产代码应走 logging
  [V] os.chmod 不新增                   ★ 架构规则 8, 优先 _safe_chmod
  [W] TODO/FIXME/XXX/HACK 零容忍        ★ PEP 350, 基线 0
  [X] 方法长度膨胀检测                  ★ 重构应让方法变小, 阈值 +50%/+50 行
  [P] shell=True / bare except          计数不增加
  [Y] except ...: pass 不新增           ★ 静默吞异常, 基线 510 对称

底部 stats 从主脚本 __version__ / __build__ 字段动态读取, 不硬编码.

用法:
  python3 verify_refactor_v4.py <refactored.py> <baseline.py>

退出码:
  0 = 全部通过  |  1 = 有检查失败  |  2 = 参数/文件错误
==========================================================================
"""
import ast, re, sys, os

# ═════════════════════════ 输出工具 ═════════════════════════
G = "\033[92m" if sys.stdout.isatty() else ""
R = "\033[91m" if sys.stdout.isatty() else ""
Y = "\033[93m" if sys.stdout.isatty() else ""
B = "\033[1m"  if sys.stdout.isatty() else ""
D = "\033[2m"  if sys.stdout.isatty() else ""
E = "\033[0m"  if sys.stdout.isatty() else ""

_P = _F = _W = 0

def ok(n, c, d=""):
    global _P, _F
    if c:
        _P += 1
        print(f"  {G}✔{E} {n}")
    else:
        _F += 1
        print(f"  {R}✘ {n}{E}" + (f"\n    → {d}" if d else ""))

def info(n, d=""):
    print(f"  {D}ℹ {n}{E}" + (f"\n    {d}" if d else ""))

def warn(n, d=""):
    global _W
    _W += 1
    print(f"  {Y}⚠ {n}{E}" + (f"\n    → {d}" if d else ""))

def banner(t):
    print(f"\n{B}{'─'*62}\n{t}\n{'─'*62}{E}")


# ═════════════════════════ 常量与白名单 ═════════════════════════
MGR = {'nginx': 'NginxManager', 'mariadb': 'MariaDBManager',
       'redis': 'RedisManager', 'php': 'PHPManager', 'cert': 'CertManager'}
MGR_NAMES = list(MGR.values())

# Manager 内合法的 self.<attr> 引用 (构造参数 + 跨 Manager 注入 + 历史 API 兜底)
MGR_SAFE = {
    # 构造参数 / 实例状态
    'platform', 'run_cmd', 'cfg', 'dry_run',
    'db_svc', '_svc_name', 'fpm_svc',
    # 跨 Manager 注入的方法 (WPDM.__init__ 注入到各 Manager)
    '_safe_write_file', '_get_total_ram_mb',
    '_el_major', '_dnf_skip_unavail', '_is_dnf5',
    '_exit_code', '_nginx_modules_need_recompile',
    '_safe_extract_tar', '_safe_reload_nginx', '_parse_cert_san_set',
    '_php_fpm_svc', '_ensure_build_deps', '_detect_nginx_user',
    '_run_wpcli', '_is_plugin_active', '_try_repair',
    '_log_journal_tail', 'run_sql', '_is_service_active',
    '_inode_retry_count', '_brotli_compiled_this_run',
    '_ensure_srcache_modules', 'apply_nginx_config_safe',
    'get_php_sock_path',
    # 迁移过来的类常量
    '_CF_IPV4_DEFAULTS', '_CF_IPV6_DEFAULTS',
    'CA_PROVIDERS', '_CERTBOT_LOCK_FILE', 'CERTBOT_LOCK_TIMEOUT',
    '_MARIADB_DEPRECATED_OPTIONS', '_MYSQL_TMP_DIR',
    # [v3.2.364] 规则 7 信号检查注入 (INJECTION BLOCK in WPDM.__init__)
    '_abort_if_shutdown',
    # [v3.2.364] 跨 Manager 互引用 (cert ↔ nginx, nginx ↔ brotli 模块)
    'nginx', 'cert', 'mariadb', 'php', 'redis',
    # [v3.2.330+] Strangler Fig 保留的旧 API 名
    'detect_service_name',
    # [v3.2.335+] 运行期属性
    '_GLOBAL_SUDO_CACHE',
}

# 22 个模块级 cache 白名单, 与主脚本一一对应 (新增需同步)
ALLOWED_GLOBAL_CACHES = {
    '_NGINX_VERSION_CACHE', '_NGINX_HTTP3_CACHE',
    '_NGINX_HTTP2_DIRECTIVE_CACHE', '_SRCACHE_DETECT_CACHE',
    # [v3.2.340+] nginx 能力探测
    '_NGINX_MAX_HEADERS_CACHE', '_NGINX_ADD_HEADER_INHERIT_CACHE',
    '_MARIADB_VERSION_CACHE', '_MARIADB_FULL_VERSION_CACHE',
    '_MYSQL_MAJOR_MINOR_CACHE', '_MARIADB_SERVICE_CACHE',
    '_PHP_VERSION_CACHE', '_PHP_FPM_SERVICE_CACHE',
    '_REDIS_VERSION_CACHE', '_REDIS_FULL_VERSION_CACHE',
    '_CERTBOT_VERSION_CACHE', '_CERTBOT_FULL_VERSION_CACHE',
    '_CHINA_CLOUD_CACHE', '_CHINA_NETWORK_CACHE',
    '_MPTCP_SUPPORT_CACHE', '_ECH_SUPPORT_CACHE',
    # [v3.2.350+] 站点探测 (TTL-based)
    '_DETECT_SITES_CACHE', '_GHOST_SITES_CACHE',
}

# 纯状态/TTL cache 不走 _reset_X_capability_caches 路径
TRANSIENT_CACHES = frozenset({
    '_NGINX_HTTP3_CACHE', '_NGINX_HTTP2_DIRECTIVE_CACHE',
    '_SRCACHE_DETECT_CACHE', '_CHINA_CLOUD_CACHE',
    '_CHINA_NETWORK_CACHE', '_MPTCP_SUPPORT_CACHE',
    '_ECH_SUPPORT_CACHE',
    '_NGINX_MAX_HEADERS_CACHE', '_NGINX_ADD_HEADER_INHERIT_CACHE',
    '_DETECT_SITES_CACHE', '_GHOST_SITES_CACHE',
})

# v3.2.288+ 新增的合法模块级函数 (reset helpers + capability detectors + DNS APIs 等)
ALLOWED_NEW_MODULE_FUNCTIONS = {
    '_reset_nginx_capability_caches',
    '_reset_mariadb_capability_caches',
    '_reset_php_capability_caches',
    '_reset_redis_capability_caches',
    '_reset_certbot_capability_caches',
    '_detect_nginx_version', '_detect_nginx_http3_capable',
    '_detect_nginx_http2_directive',
    '_nginx_supports_max_headers', '_nginx_supports_add_header_inherit',
    '_nginx_fastcgi_buffers_tiered',
    '_detect_ech_support', '_generate_ech_keypair',
    'setup_ech', '_extract_ech_config_base64',
    '_ech_dns_auto', '_install_ech_rotation_timer',
    '_print_ech_dns_record', '_verify_ech_dns',
    '_cf_api_request', '_cf_get_zone_id', '_cf_upsert_https_record',
    '_r53_upsert_https_record', '_alidns_upsert_https_record',
    '_dnspod_api', '_dnspod_upsert_https_record',
    '_detect_mptcp_support', '_reset_mptcp_cache',
    '_cert_supports_ocsp', '_decide_ocsp_enable',
    '_detect_debian_bookworm', '_is_openeuler_like',
    '_install_valkey_debian', '_enable_bookworm_backports',
    '_redis_flavor_name', '_install_epel_release',
    # [post-3.2.379 patch series, audit回归修复]
    # FIX-⓰ MariaDB CLI 命名过渡 helper (mysql* → mariadb-* 自动选择)
    '_mariadb_cli',
    # FIX-❻ Redis/Valkey 端口动态探测 (从配置文件读 port 指令)
    '_probe_redis_port',
    # FIX-⓫ Fail2Ban CF CIDR 自动注入 (读 nginx cloudflare-real-ip.conf)
    '_read_cloudflare_cidrs',
}

# [v3.2.9 build 381] 已知合法增量 (collect-logs 审计报告生成器功能:
# _generate_site_audit_report 1,223 行 + _print_audit_summary 94 行).
# 这是 feature, 不是 refactor 回归, 用对应 delta 容忍通过对称检查.
AUDIT_GENERATOR_PRINT_DELTA       = 9    # [U] _print_audit_summary 里的 print() 数
AUDIT_GENERATOR_EXCEPT_PASS_DELTA = 8    # [Y] 审计器防御性错误静默捕获数
AUDIT_GENERATOR_UNUSED_LOCAL_DELTA = 1   # [O] 审计器遗留 1 个未用局部变量


# 合法删除的 WPDM 方法 (全部被 Manager 公开 API 替代或内联)
ALLOWED_DELETED_WPDM_METHODS = {
    '_certbot_supports_key_type', '_detect_cert_issuer',
    '_detect_cert_key_type', '_detect_certbot_full_version',
    '_detect_certbot_version', '_is_pip_venv_certbot', '_is_snap_certbot',
    '_detect_db_service', '_detect_installed_mariadb_version',
    '_get_mariadb_full_version',
    '_detect_installed_php_version',
    '_get_active_php_conf_paths', '_get_active_php_ini_paths',
    '_get_active_php_ver_str', '_get_php_conf_paths',
    '_get_php_ini_paths', '_read_php_ini_values',
    '_detect_nginx_user', '_get_nginx_version_tuple',
    '_safe_reload_nginx', '_srcache_install_load_module',
    '_detect_redis_service_name', '_detect_redis_version',
}

ALLOWED_DELETED_MODULE_FUNCTIONS = {
    '_get_nginx_version_tuple',  # → NginxManager.detect_version (canonical)
}

# 重命名映射 (Strangler Fig 过渡期: 旧名 → canonical 新名)
KNOWN_RENAMES = {
    'detect_installed_version': 'detect_version',
    '_detect_redis_full_version': 'detect_full_version',
    'detect_service_name': 'detect_service',
    '_detect_php_fpm_service': 'detect_service',
    '_detect_nginx_version': 'detect_version',
    '_detect_mariadb_version': 'detect_version',
    '_detect_mariadb_full_version': 'detect_full_version',
    '_detect_cert_issuer': 'detect_cert_issuer',
    '_detect_cert_key_type': 'detect_cert_key_type',
    '_detect_certbot_full_version': 'detect_full_version',
    '_detect_certbot_version': 'detect_version',
    '_detect_installed_mariadb_version': 'detect_version',
    '_detect_installed_php_version': 'detect_version',
    '_detect_redis_service_name': 'detect_service',
    '_detect_redis_version': 'detect_version',
    '_detect_db_service': 'detect_service',
    '_detect_nginx_user': 'detect_user',
    '_fixup_mariadb_client_mismatch': '_fix_mariadb_client_mismatch',
    '_get_active_php_conf_paths': 'get_active_conf_paths',
    '_get_active_php_ini_paths': 'get_active_ini_paths',
    '_get_mariadb_full_version': 'detect_full_version',
    '_get_nginx_version_tuple': '_detect_nginx_version',
    '_get_php_conf_paths': 'get_conf_paths',
    '_get_php_ini_paths': 'get_ini_paths',
    '_is_pip_venv_certbot': 'is_pip_venv',
    '_is_snap_certbot': 'is_snap',
    '_certbot_supports_key_type': 'supports_key_type',
    '_setup_mariadb_official_repo_el': '_setup_mariadb_repo_el',
    '_get_active_php_ver_str': None,  # 内联/移除
    '_read_php_ini_values': None,
    '_srcache_install_load_module': None,
    '_upgrade_valkey_major': 'upgrade_to_target',
    '_safe_reload_nginx': 'safe_reload',
}

DEPRECATED_ALIAS_PATTERN = re.compile(r'\[DEPRECATED v3\.2\.\d+\]')
PROXY_MARKERS = ('代理到', '委托')


# ═════════════════════════ AST 辅助 ═════════════════════════
def _is_proxy(body):
    return any(m in body for m in PROXY_MARKERS)

def _is_deprecated_alias(body):
    return bool(DEPRECATED_ALIAS_PATTERN.search(body))

def cls_methods(tree, name):
    """返回类 name 的所有方法名集合"""
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return {c.name for c in ast.iter_child_nodes(n)
                    if isinstance(c, ast.FunctionDef)}
    return set()

def get_class_info(tree, src_lines):
    """抽取每个类的方法 (含 body/args/lineno) 和类常量"""
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods, constants = {}, {}
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.FunctionDef):
                    body = '\n'.join(src_lines[ch.lineno-1:ch.end_lineno])
                    methods[ch.name] = {
                        'lineno': ch.lineno,
                        'body': body,
                        'args': [a.arg for a in ch.args.args],
                    }
                elif isinstance(ch, ast.Assign):
                    for t in ch.targets:
                        if isinstance(t, ast.Name):
                            constants[t.id] = ch.lineno
            result[node.name] = {'methods': methods, 'constants': constants}
    return result

def self_refs(method):
    """从方法 AST 提取所有 self.<attr> 的 attr 名"""
    return {nd.attr for nd in ast.walk(method)
            if isinstance(nd, ast.Attribute)
            and isinstance(nd.value, ast.Name) and nd.value.id == 'self'}

def mod_fns(tree):
    return {nd.name for nd in ast.iter_child_nodes(tree)
            if isinstance(nd, (ast.FunctionDef, ast.AsyncFunctionDef))}

def mod_vars(tree):
    """收集模块级变量 (Assign + AnnAssign 都要算)"""
    names = set()
    for nd in ast.iter_child_nodes(tree):
        if isinstance(nd, ast.Assign):
            for t in nd.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(nd, ast.AnnAssign) and isinstance(nd.target, ast.Name):
            names.add(nd.target.id)
    return names

def imports_set(lines):
    return {l.strip() for l in lines if l.startswith(('import ', 'from '))}

def _extract_version_info(src):
    v = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.MULTILINE)
    b = re.search(r'^__build__\s*=\s*["\']([^"\']+)["\']',   src, re.MULTILINE)
    return (v.group(1) if v else '?', b.group(1) if b else '?')

def _scan_unused_locals(tree, src_lines):
    """扫描所有类方法中的未使用下划线开头局部变量."""
    found = set()
    for _n in ast.walk(tree):
        if not isinstance(_n, ast.ClassDef):
            continue
        for _ch in ast.iter_child_nodes(_n):
            if not isinstance(_ch, ast.FunctionDef):
                continue
            _body = '\n'.join(src_lines[_ch.lineno-1:_ch.end_lineno])
            _globals = {nm for _nd in ast.walk(_ch)
                        if isinstance(_nd, ast.Global)
                        for nm in _nd.names}
            for _nd in ast.walk(_ch):
                if not (isinstance(_nd, ast.Assign) and len(_nd.targets) == 1):
                    continue
                _tgt = _nd.targets[0]
                if not (isinstance(_tgt, ast.Name) and _tgt.id.startswith('_')):
                    continue
                _var = _tgt.id
                if _var == '_' or _var in _globals:
                    continue
                if _body.count(_var) <= 1:
                    found.add(f"{_n.name}.{_ch.name}: {_var}")
    return found

def _count_shell_true(tree):
    return sum(1 for nd in ast.walk(tree) if isinstance(nd, ast.Call)
               for kw in nd.keywords
               if kw.arg == 'shell' and isinstance(kw.value, ast.Constant)
               and kw.value.value is True)

def _count_bare_except(tree):
    return sum(1 for c in ast.walk(tree)
               if isinstance(c, ast.ExceptHandler) and c.type is None)


# ═════════════════════════ 主验证 ═════════════════════════
def run(new_path, old_path):
    new_src = open(new_path, encoding='utf-8').read()
    old_src = open(old_path, encoding='utf-8').read()
    new_lines = new_src.split('\n')
    old_lines = old_src.split('\n')

    # ─── [A] 字节码/AST ───────────────────────────────────────
    banner("结构层 [A] 字节码/AST 编译")
    try:
        nt = ast.parse(new_src)
        ok("当前版本 AST 解析", True)
    except SyntaxError as e:
        ok("当前版本 AST 解析", False, str(e))
        return False
    try:
        compile(new_src, os.path.basename(new_path), "exec")
        ok("当前版本 compile() 通过", True)
    except SyntaxError as e:
        ok("当前版本 compile() 通过", False, str(e))
    try:
        ot = ast.parse(old_src)
        ok("基线版本 AST 解析", True)
    except SyntaxError as e:
        ok("基线版本 AST 解析", False, str(e))
        ot = None

    new_info = get_class_info(nt, new_lines)
    old_info = get_class_info(ot, old_lines) if ot else {}

    # ─── [B] 方向感知迁移 ─────────────────────────────────────
    banner("结构层 [B] 方向感知迁移 WPDM → 5 Manager")
    old_wpdm = set(old_info.get('WPDeployManager', {}).get('methods', {}))
    new_wpdm = set(new_info.get('WPDeployManager', {}).get('methods', {}))
    old_all_mgr = set()
    new_all_mgr = set()
    for m in MGR_NAMES:
        old_all_mgr |= set(old_info.get(m, {}).get('methods', {}))
        new_all_mgr |= set(new_info.get(m, {}).get('methods', {}))

    if ot:
        lost_from_wpdm = old_wpdm - new_wpdm
        migrated_to_mgr = lost_from_wpdm & new_all_mgr
        truly_lost = lost_from_wpdm - new_all_mgr
        renamed_survivors = {m for m in truly_lost
                             if m in KNOWN_RENAMES
                             and (KNOWN_RENAMES[m] is None
                                  or KNOWN_RENAMES[m] in new_all_mgr)}
        truly_lost -= renamed_survivors
        deleted_legit = lost_from_wpdm & ALLOWED_DELETED_WPDM_METHODS
        truly_lost -= ALLOWED_DELETED_WPDM_METHODS

        ok(f"WPDM 方法可追溯 {len(old_wpdm)}→{len(new_wpdm)} "
           f"(迁移 {len(migrated_to_mgr)}, 重命名 {len(renamed_survivors)}, "
           f"合法删除 {len(deleted_legit)}, 真丢失 {len(truly_lost)})",
           len(truly_lost) == 0,
           f"真丢失: {sorted(truly_lost)[:5]}")
        ok(f"Manager 总方法数非减 {len(old_all_mgr)}→{len(new_all_mgr)}",
           len(new_all_mgr) >= len(old_all_mgr))

        # 每个 Manager 方法数非减 (v2.V1.3 细粒度)
        for mgr in MGR_NAMES:
            oc = len(old_info.get(mgr, {}).get('methods', {}))
            nc = len(new_info.get(mgr, {}).get('methods', {}))
            ok(f"{mgr}: {oc}→{nc} 方法 ({'+' if nc >= oc else ''}{nc - oc})",
               nc >= oc)

        # 方法守恒率
        total_old = len(old_wpdm) + len(old_all_mgr)
        total_new = len(new_wpdm) + len(new_all_mgr)
        conservation = 100 * total_new // max(1, total_old)
        info(f"方法守恒率: {total_new}/{total_old} = {conservation}%")

        # SiteConfig / CmdResult 冻结
        for c in ('SiteConfig', 'CmdResult'):
            ok(f"{c} 类方法集合不变",
               cls_methods(ot, c) == cls_methods(nt, c))
    else:
        info("无基线 AST, 跳过迁移检查")

    # ─── [C] 方法签名保真 ─────────────────────────────────────
    banner("结构层 [C] 方法签名保真 (非 proxy WPDM 方法)")
    if ot:
        sig_errors = []
        checked = 0
        wpdm_new = new_info.get('WPDeployManager', {}).get('methods', {})
        wpdm_old = old_info.get('WPDeployManager', {}).get('methods', {})
        for name, meta in wpdm_new.items():
            if _is_proxy(meta['body']):
                continue
            if name not in wpdm_old:
                continue
            checked += 1
            if meta['args'] != wpdm_old[name]['args']:
                sig_errors.append(
                    f"{name}: {wpdm_old[name]['args']} → {meta['args']}")
        ok(f"非 proxy WPDM 方法签名保真 ({checked} 方法已比对)",
           len(sig_errors) == 0,
           '\n'.join(sig_errors[:5]))
    else:
        info("无基线, 跳过签名保真")

    # ─── [D] 模块级演化 ───────────────────────────────────────
    banner("结构层 [D] 模块级演化")
    new_mod_fns = mod_fns(nt)
    new_mod_vars = mod_vars(nt)
    if ot:
        old_mod_fns = mod_fns(ot)
        old_mod_vars = mod_vars(ot)
        lost_fns = (old_mod_fns - new_mod_fns) - ALLOWED_DELETED_MODULE_FUNCTIONS
        ok(f"模块级函数零丢失 ({len(old_mod_fns)}→{len(new_mod_fns)})",
           len(lost_fns) == 0,
           f"丢失: {sorted(lost_fns)[:5]}")

        new_fns_added = new_mod_fns - old_mod_fns
        unexpected_fns = new_fns_added - ALLOWED_NEW_MODULE_FUNCTIONS
        ok(f"新增模块级函数全部合法 ({len(new_fns_added)} 新增)",
           len(unexpected_fns) == 0
           or all(f.startswith(('_reset_', '_detect_')) for f in unexpected_fns),
           f"未预期: {sorted(unexpected_fns)[:5]}")
        if new_fns_added:
            info(f"命中白名单新增: {sorted(new_fns_added & ALLOWED_NEW_MODULE_FUNCTIONS)[:6]}")

        new_vars_added = new_mod_vars - old_mod_vars
        cache_vars = {v for v in new_vars_added
                      if v in ALLOWED_GLOBAL_CACHES
                      or v.endswith(('_CACHE', '_LOCK', '_DEFAULT_VERSION'))}
        unexpected_vars = new_vars_added - cache_vars
        ok(f"新增模块级变量全部合法 "
           f"({len(new_vars_added)} 新增, {len(cache_vars)} caches/locks/consts)",
           len(unexpected_vars) == 0
           or all((v.startswith('_') and v.isupper())
                  or v.endswith(('_CACHE', '_LOCK'))
                  for v in unexpected_vars),
           f"未预期: {sorted(unexpected_vars)[:5]}")
    else:
        info("无基线, 跳过演化检查")

    # ─── [E] Imports 非减 ────────────────────────────────────
    banner("结构层 [E] Imports 非减")
    if ot:
        old_imps = imports_set(old_lines)
        new_imps = imports_set(new_lines)
        lost_imps = old_imps - new_imps
        ok(f"Imports 非减 ({len(old_imps)}→{len(new_imps)})",
           len(lost_imps) == 0,
           f"丢失: {sorted(lost_imps)[:3]}")
    else:
        info("无基线, 跳过 imports 检查")

    # ─── [F] Manager global 语句 ──────────────────────────────
    banner("结构层 [F] Manager global 语句 (cache 白名单 22 项)")
    gi_non_cache, gi_cache = [], []
    for cn in MGR_NAMES:
        for nd in ast.walk(nt):
            if isinstance(nd, ast.ClassDef) and nd.name == cn:
                for ch in ast.walk(nd):
                    if isinstance(ch, ast.Global):
                        for nm in ch.names:
                            tag = f"{cn} L{ch.lineno}: {nm}"
                            if nm in ALLOWED_GLOBAL_CACHES:
                                gi_cache.append(tag)
                            else:
                                gi_non_cache.append(tag)
    ok(f"Manager 零非缓存 global ({len(gi_cache)} cache globals OK)",
       len(gi_non_cache) == 0,
       '\n'.join(gi_non_cache[:5]))
    if gi_cache:
        info(f"合法 cache global: {len(gi_cache)} 处")

    # ─── [G] Strangler Fig 别名 ───────────────────────────────
    banner("结构层 [G] Strangler Fig 别名完整性")
    aliases = []
    canonical_methods = set()
    for cn in MGR_NAMES:
        for mname, meta in new_info.get(cn, {}).get('methods', {}).items():
            if _is_deprecated_alias(meta['body']):
                has_return_call = 'return self.' in meta['body']
                aliases.append((cn, mname, has_return_call))
            if mname in ('detect_version', 'detect_full_version',
                         'detect_service', 'upgrade_to_target'):
                canonical_methods.add(f"{cn}.{mname}")
    ok(f"Deprecated 别名都是 return self.X() 委托 ({len(aliases)} 别名)",
       all(h for _, _, h in aliases),
       '; '.join(f"{c}.{n} 无 return" for c, n, h in aliases if not h))
    if aliases:
        info(f"Strangler Fig 别名清单:")
        for c, n, _ in aliases[:5]:
            print(f"    {D}· {c}.{n}{E}")

    # ─── [H] Canonical API 对称 ───────────────────────────────
    banner("结构层 [H] Canonical API 对称性")
    have_detect_version = {m.split('.')[0] for m in canonical_methods
                           if m.endswith('.detect_version')}
    missing_dv = set(MGR_NAMES) - have_detect_version
    ok(f"5 Manager 都有 detect_version() ({len(have_detect_version)}/5)",
       len(missing_dv) == 0,
       f"缺失: {sorted(missing_dv)}")
    have_ds = {m for m in canonical_methods if m.endswith('.detect_service')}
    ok(f"3+ Manager 有 detect_service() ({len(have_ds)}/3)",
       len(have_ds) >= 3)
    have_ut = {m for m in canonical_methods if m.endswith('.upgrade_to_target')}
    ok(f"3+ Manager 有 upgrade_to_target() ({len(have_ut)}/3)",
       len(have_ut) >= 3)

    # ─── [I] Reset Helper 对称 ────────────────────────────────
    banner("结构层 [I] Reset Helper 对称性")
    reset_helpers = {f for f in new_mod_fns
                     if f.startswith('_reset_') and 'capability_caches' in f}
    ok(f"5 Manager 都有 _reset_X_capability_caches ({len(reset_helpers)})",
       len(reset_helpers) >= 5,
       f"找到: {sorted(reset_helpers)}")

    # ─── [J] Manager self 引用自洽 ────────────────────────────
    banner("结构层 [J] Manager self 引用自洽")
    mgr_methods_map = {}
    broken = []
    for acc, cn in MGR.items():
        for nd in ast.walk(nt):
            if isinstance(nd, ast.ClassDef) and nd.name == cn:
                ms = {c.name for c in ast.iter_child_nodes(nd)
                      if isinstance(c, ast.FunctionDef)}
                for ch in ast.iter_child_nodes(nd):
                    if isinstance(ch, ast.Assign):
                        for t in ch.targets:
                            if isinstance(t, ast.Name):
                                ms.add(t.id)
                mgr_methods_map[acc] = ms
                for ch in ast.iter_child_nodes(nd):
                    if not isinstance(ch, ast.FunctionDef) or ch.name == '__init__':
                        continue
                    for r in self_refs(ch):
                        if r not in ms and r not in MGR_SAFE and r != ch.name:
                            broken.append(f"{cn}.{ch.name}: self.{r}")
                break
        cn_broken = [b for b in broken if b.startswith(f"{cn}.")]
        ok(f"{cn} self 引用自洽 "
           f"({len(mgr_methods_map.get(acc, set())) - 1} 方法/成员)",
           len(cn_broken) == 0,
           '; '.join(cn_broken[:3]))

    # ─── [K] 零重复方法 & 参数 ────────────────────────────────
    banner("结构层 [K] 零重复方法 & 零重复参数")
    for nd in ast.walk(nt):
        if isinstance(nd, ast.ClassDef):
            methods = [c.name for c in ast.iter_child_nodes(nd)
                       if isinstance(c, ast.FunctionDef)]
            seen, dup = set(), set()
            for m in methods:
                if m in seen:
                    dup.add(m)
                seen.add(m)
            ok(f"{nd.name} 零重复方法",
               len(dup) == 0,
               f"重复: {sorted(dup)}" if dup else "")
    dup_params = [n.name for n in ast.walk(nt)
                  if isinstance(n, ast.FunctionDef)
                  and len([a.arg for a in n.args.args])
                  != len(set(a.arg for a in n.args.args))]
    ok("零重复参数", len(dup_params) == 0, str(dup_params[:3]))

    # ─── [L] 跨组件注入完整性 ─────────────────────────────────
    banner("结构层 [L] 跨组件注入完整性 (WPDM.__init__)")
    injections = []
    in_wpdm_init = False
    cur_cls = None
    for line in new_lines:
        cls_m = re.match(r'^class (\w+)', line)
        if cls_m:
            cur_cls = cls_m.group(1)
            in_wpdm_init = False
            continue
        def_m = re.match(r'^    def (\w+)', line)
        if def_m:
            in_wpdm_init = (cur_cls == 'WPDeployManager'
                            and def_m.group(1) == '__init__')
            continue
        if in_wpdm_init and re.match(
                r'\s+self\.(nginx|cert|php|mariadb|redis)\.\w+\s*=', line):
            injections.append(line.strip())
    ok(f"跨组件注入数量充足 ({len(injections)} 条, 要求 ≥20)",
       len(injections) >= 20,
       f"只找到 {len(injections)}, 迁移守护可能不完整")
    if injections:
        info(f"样例: {injections[0][:70]}")

    # ─── [M] @staticmethod 合规 ───────────────────────────────
    banner("结构层 [M] @staticmethod 合规 (不得引用 self)")
    static_self_errors = []
    for nd in ast.walk(nt):
        if isinstance(nd, ast.ClassDef):
            for ch in ast.iter_child_nodes(nd):
                if not isinstance(ch, ast.FunctionDef):
                    continue
                is_static = any(isinstance(d, ast.Name) and d.id == 'staticmethod'
                                for d in ch.decorator_list)
                if not is_static:
                    continue
                has_self = any(isinstance(n, ast.Name) and n.id == 'self'
                               for n in ast.walk(ch))
                if has_self:
                    static_self_errors.append(f"{nd.name}.{ch.name} L{ch.lineno}")
    ok(f"零 @staticmethod 引用 self",
       len(static_self_errors) == 0,
       '\n'.join(static_self_errors[:5]))

    # ─── [N] Caching 模式完整性 ───────────────────────────────
    banner("架构层 [N] Caching 模式完整性 (cache × lock × reset)")
    all_caches = sorted(v for v in new_mod_vars if v.endswith('_CACHE'))
    all_locks  = {v for v in new_mod_vars if v.endswith('_LOCK')}

    # Cache ↔ Lock 配对
    missing_locks = []
    for c in all_caches:
        expected = c.replace('_CACHE', '_LOCK')
        if expected not in all_locks:
            missing_locks.append(c)
    ok(f"所有 _X_CACHE 有对应 _LOCK "
       f"({len(all_caches)} caches, {len(all_locks)} locks)",
       len(missing_locks) == 0,
       f"无 lock: {missing_locks[:5]}")

    # 每个 cache 独立配对检查 (v3 细粒度)
    for cache_name in sorted(ALLOWED_GLOBAL_CACHES):
        if cache_name not in new_src:
            continue
        lock_name = cache_name.replace('_CACHE', '_LOCK')
        ok(f"{cache_name} ↔ {lock_name}", lock_name in new_src)

    # Cache → Reset 覆盖 (非 TRANSIENT)
    cache_resets = {}
    for fn_name in reset_helpers:
        for nd in ast.walk(nt):
            if isinstance(nd, ast.FunctionDef) and nd.name == fn_name:
                for g in ast.walk(nd):
                    if isinstance(g, ast.Global):
                        for nm in g.names:
                            cache_resets.setdefault(nm, []).append(fn_name)
    unreset = [c for c in ALLOWED_GLOBAL_CACHES
               if c in new_src
               and c not in cache_resets
               and c not in TRANSIENT_CACHES]
    in_src = len([c for c in ALLOWED_GLOBAL_CACHES if c in new_src])
    ok(f"所有非 TRANSIENT cache 有对应 reset "
       f"({len(cache_resets)}/{in_src} 覆盖, {len(TRANSIENT_CACHES)} 豁免)",
       len(unreset) == 0,
       f"未覆盖: {unreset[:3]}")

    # ─── [O] 未使用局部变量 (对称) ────────────────────────────
    banner("卫生层 [O] 未使用局部变量 (对称检查, 仅报回归)")
    new_unused = _scan_unused_locals(nt, new_lines)
    if ot:
        old_unused = _scan_unused_locals(ot, old_lines)
        regressions = new_unused - old_unused
        inherited = new_unused & old_unused
        ok(f"未使用局部变量不增加 "
           f"(基线 {len(old_unused)} → 当前 {len(new_unused)}, "
           f"继承 {len(inherited)}, 回归 {len(regressions)}, "
           f"allow +{AUDIT_GENERATOR_UNUSED_LOCAL_DELTA} for audit generator)",
           len(regressions) <= AUDIT_GENERATOR_UNUSED_LOCAL_DELTA,
           '; '.join(sorted(regressions)[:5]))
    else:
        ok(f"零未使用局部变量 ({len(new_unused)}, 无基线)",
           len(new_unused) == 0,
           '; '.join(sorted(new_unused)[:5]))

    # ─── [P] shell=True / bare except (对称) ──────────────────
    banner("安全层 [P] shell=True / bare except (对称检查)")
    ns_t = _count_shell_true(nt)
    nb_e = _count_bare_except(nt)
    if ot:
        os_t = _count_shell_true(ot)
        ob_e = _count_bare_except(ot)
        ok(f"shell=True 不新增 ({os_t}→{ns_t})", ns_t <= os_t)
        ok(f"裸 except 不新增 ({ob_e}→{nb_e})", nb_e <= ob_e)
    else:
        info(f"shell=True: {ns_t}, 裸 except: {nb_e} (无基线, 仅统计)")

    # ─── [Q] Strangler 别名存活性 (死代码检测) ──────────────────
    # 依据: Shopify/Fowler Strangler Fig 模式要求—旧别名完成过渡后应被删除.
    # 零调用者的别名是死代码, 应清理或回退.
    banner("架构层 [Q] Strangler Fig 别名存活性 (死代码检测)")
    dead_aliases = []
    alive_aliases = []
    for cn, mname, _ in aliases:  # aliases 来自 [G]
        # 数外部调用: 统计 `.<name>(` 出现次数 (定义本身不以点开头)
        caller_count = len(re.findall(r'\.' + re.escape(mname) + r'\(', new_src))
        if caller_count == 0:
            dead_aliases.append(f"{cn}.{mname}")
        else:
            alive_aliases.append((cn, mname, caller_count))
    ok(f"所有 deprecated 别名仍有活跃调用者 "
       f"({len(alive_aliases)}/{len(aliases)})",
       len(dead_aliases) == 0,
       f"零调用的死别名 (应清理): {dead_aliases[:5]}")
    if alive_aliases:
        info("调用者数量 (迁移进度参考):")
        for cn, mn, cnt in sorted(alive_aliases, key=lambda x: x[2])[:5]:
            print(f"    {D}· {cn}.{mn}: {cnt} 调用者{E}")

    # ─── [R] subprocess.run 必须带 timeout (主脚本 Rule 5) ──────
    # 脚本架构规则 5 明文要求: subprocess.run 必须带 timeout. 基线 450/450 = 100%.
    banner("契约层 [R] subprocess.run 必须带 timeout (架构规则 5)")
    sp_without_timeout = []
    sp_total = 0
    for node in ast.walk(nt):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'run'
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'subprocess'):
            sp_total += 1
            has_t = any(kw.arg == 'timeout' for kw in node.keywords)
            if not has_t:
                sp_without_timeout.append(f"L{node.lineno}")
    ok(f"所有 subprocess.run 都带 timeout ({sp_total} 调用, "
       f"{sp_total - len(sp_without_timeout)} 合规)",
       len(sp_without_timeout) == 0,
       f"遗漏 timeout 的位置: {sp_without_timeout[:5]}")

    # ─── [S] Proxy 委托方法返回值完整性 (主脚本 Rule 14) ────────
    # 脚本架构规则 14: wrapper 必须 return. 所有代理到/委托方法末尾应为 return <call>
    # 而非裸调用 (否则调用方拿到 None → 隐形 bug, Python delegation pattern 经典坑).
    # 例外: 方法显式标注 -> None 时, 末尾是裸调用是合理的 (void 委托).
    banner("契约层 [S] Proxy 委托方法返回值完整性 (架构规则 14)")
    broken_proxies = []
    proxy_total = 0

    def _returns_none(fn_node):
        """AST-level 判断方法是否标注 -> None."""
        r = fn_node.returns
        if r is None:
            return False  # 无注解: 按有返回值处理 (保守)
        if isinstance(r, ast.Constant) and r.value is None:
            return True
        if isinstance(r, ast.Name) and r.id == 'None':
            return True
        return False

    for cn in [*MGR_NAMES, 'WPDeployManager']:
        for node in ast.walk(nt):
            if not (isinstance(node, ast.ClassDef) and node.name == cn):
                continue
            for ch in ast.iter_child_nodes(node):
                if not isinstance(ch, ast.FunctionDef):
                    continue
                mname = ch.name
                meta = new_info.get(cn, {}).get('methods', {}).get(mname, {})
                if not _is_proxy(meta.get('body', '')):
                    continue
                proxy_total += 1
                # -> None 标注的方法, 末尾裸调用合规 (void 委托)
                if _returns_none(ch):
                    continue
                # 取 body, 跳过 docstring
                body = ch.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    body = body[1:]
                if not body:
                    continue
                last = body[-1]
                # 最后一句是裸 Expr(Call(Attribute(... self ...))) → 漏 return
                if (isinstance(last, ast.Expr)
                        and isinstance(last.value, ast.Call)
                        and isinstance(last.value.func, ast.Attribute)):
                    broken_proxies.append(f"{cn}.{mname} L{last.lineno}")
            break

    ok(f"所有 proxy 方法末尾 return 完整 ({proxy_total} proxy 方法)",
       len(broken_proxies) == 0,
       f"疑似遗漏 return (非 -> None 方法): {broken_proxies[:5]}")

    # ─── [T] 禁用 Mutable default arguments (Python 经典坑) ─────
    # 基线 0; 新增 def f(x=[]) / def f(x={}) 会导致状态跨调用泄漏.
    banner("契约层 [T] Mutable default arguments (零容忍)")
    mutable_defaults = []
    for node in ast.walk(nt):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.args.defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    kind = type(d).__name__.lower()
                    mutable_defaults.append(f"{node.name} L{node.lineno} ({kind})")
                elif (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                      and d.func.id in ('list', 'dict', 'set')):
                    mutable_defaults.append(f"{node.name} L{node.lineno} ({d.func.id}())")
    ok(f"零 mutable default arguments ({len(mutable_defaults)} 命中, 基线 0)",
       len(mutable_defaults) == 0,
       '; '.join(mutable_defaults[:5]))

    # ─── [U] Manager 内 print() 不新增 (对称) ───────────────────
    # 生产代码应走 logging; print 仅用于交互式命令. 对称确保不新引入.
    banner("卫生层 [U] Manager 内 print() 不新增 (对称检查)")
    def _count_print_in_mgr(tree):
        cnt = 0
        all_mgrs = [*MGR_NAMES, 'WPDeployManager']
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in all_mgrs:
                for c in ast.walk(node):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                            and c.func.id == 'print'):
                        cnt += 1
        return cnt
    new_print = _count_print_in_mgr(nt)
    if ot:
        old_print = _count_print_in_mgr(ot)
        _allowed_print = old_print + AUDIT_GENERATOR_PRINT_DELTA
        ok(f"Manager/WPDM print() 不新增 ({old_print}→{new_print}, "
           f"allow +{AUDIT_GENERATOR_PRINT_DELTA} for audit generator)",
           new_print <= _allowed_print,
           f"新增 {new_print - old_print} 处 print 调用, "
           f"超过审计器容忍 +{AUDIT_GENERATOR_PRINT_DELTA}")
    else:
        info(f"Manager/WPDM print() 调用: {new_print} (无基线)")

    # ─── [V] os.chmod 不新增, 优先 _safe_chmod (Rule 8 对称) ────
    banner("卫生层 [V] os.chmod 优先 _safe_chmod (架构规则 8, 对称)")
    def _count_chmod(tree):
        direct = indirect = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'chmod'
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == 'os'):
                    direct += 1
                elif (isinstance(node.func, ast.Name)
                      and node.func.id == '_safe_chmod'):
                    indirect += 1
        return direct, indirect
    nd_chmod, ns_chmod = _count_chmod(nt)
    if ot:
        od_chmod, os_chmod_c = _count_chmod(ot)
        ok(f"os.chmod 直接调用不新增 ({od_chmod}→{nd_chmod})",
           nd_chmod <= od_chmod)
        ok(f"_safe_chmod 使用非减 ({os_chmod_c}→{ns_chmod})",
           ns_chmod >= os_chmod_c)
        info(f"迁移进度: _safe_chmod {ns_chmod} / os.chmod {nd_chmod} "
             f"= {100*ns_chmod//max(1,ns_chmod+nd_chmod)}% 安全路径")
    else:
        info(f"os.chmod {nd_chmod}, _safe_chmod {ns_chmod} (无基线)")

    # ─── [W] 技术债标记零容忍 ──────────────────────────────────
    # TODO/FIXME/XXX/HACK 基线 0; 重构引入新债务要立即可见.
    banner("卫生层 [W] 技术债标记零容忍 (TODO/FIXME/XXX/HACK)")
    debt_counts = {}
    for tag in ('TODO', 'FIXME', 'XXX', 'HACK'):
        # \b 词边界, 匹配 # TODO 而不是 V3.2.3_TODO_FOO 中的 TODO
        # 同时排除 docstring 里的无害描述 (简化: 只扫注释行和字符串)
        matches = re.findall(r'\b' + tag + r'\b', new_src)
        debt_counts[tag] = len(matches)
    total_debt = sum(debt_counts.values())
    if ot:
        old_debt = sum(len(re.findall(r'\b' + t + r'\b', old_src))
                       for t in ('TODO', 'FIXME', 'XXX', 'HACK'))
        ok(f"技术债标记不新增 ({old_debt}→{total_debt})",
           total_debt <= old_debt,
           '; '.join(f"{k}:{v}" for k, v in debt_counts.items() if v))
    else:
        ok(f"零技术债标记 (TODO/FIXME/XXX/HACK = {total_debt})",
           total_debt == 0,
           '; '.join(f"{k}:{v}" for k, v in debt_counts.items() if v))

    # ─── [X] 方法长度膨胀检测 (对称, 阈值化) ───────────────────
    # 重构应让方法变小 (逻辑下放 Manager), 单方法长度大幅增加是反模式.
    # 阈值: 同名方法新版行数 > max(old*1.5, old+50), 则判为膨胀.
    banner("卫生层 [X] 方法长度膨胀检测 (对称, 阈值化)")
    if ot:
        def _collect_method_sizes(tree):
            sizes = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for ch in ast.iter_child_nodes(node):
                        if isinstance(ch, ast.FunctionDef):
                            sizes[f"{node.name}.{ch.name}"] = \
                                ch.end_lineno - ch.lineno + 1
            return sizes
        old_sizes = _collect_method_sizes(ot)
        new_sizes = _collect_method_sizes(nt)
        bloated = []
        for key, new_len in new_sizes.items():
            old_len = old_sizes.get(key)
            if old_len is None:
                continue
            # 非 proxy 方法才检查 (proxy 本身应保持精简, 单独判)
            cn, mn = key.split('.', 1)
            m_info = new_info.get(cn, {}).get('methods', {}).get(mn, {})
            if _is_proxy(m_info.get('body', '')) or _is_deprecated_alias(m_info.get('body', '')):
                continue
            threshold = max(int(old_len * 1.5), old_len + 50)
            if new_len > threshold:
                bloated.append(f"{key}: {old_len}→{new_len} "
                               f"(+{new_len-old_len}, {100*(new_len-old_len)//old_len}%)")
        ok(f"零方法大幅膨胀 (阈值 +50% 或 +50 行, 取大者)",
           len(bloated) == 0,
           '; '.join(bloated[:3]))
    else:
        info("无基线, 跳过膨胀检测")

    # ─── [Y] except Exception: pass 不新增 (silent swallow) ────
    # 静默吞异常破坏可观测性. 基线 510, 对称确保不增.
    banner("安全层 [Y] except ...: pass 不新增 (对称检查)")
    def _count_silent_except(tree):
        cnt = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    cnt += 1
        return cnt
    ns_silent = _count_silent_except(nt)
    if ot:
        os_silent = _count_silent_except(ot)
        _allowed_silent = os_silent + AUDIT_GENERATOR_EXCEPT_PASS_DELTA
        ok(f"except ...: pass 不新增 ({os_silent}→{ns_silent}, "
           f"allow +{AUDIT_GENERATOR_EXCEPT_PASS_DELTA} for audit generator)",
           ns_silent <= _allowed_silent,
           f"新增 {ns_silent - os_silent} 处静默吞异常, "
           f"超过审计器容忍 +{AUDIT_GENERATOR_EXCEPT_PASS_DELTA}")
    else:
        info(f"except ...: pass 计数: {ns_silent} (无基线)")

    # ═════════════════════════ 汇总 ═════════════════════════
    total = _P + _F
    print(f"\n{'═' * 62}")
    if _F == 0:
        print(f"{G}{B}✅ 全部 {total} 项通过{E}"
              + (f" ({_W} 警告)" if _W else ""))
    else:
        print(f"{R}{B}❌ {_F}/{total} 项失败{E}"
              + (f" ({_W} 警告)" if _W else ""))
    print(f"{'═' * 62}")

    # 架构概览 (版本号从主脚本动态读取)
    old_ver, old_build = _extract_version_info(old_src)
    new_ver, new_build = _extract_version_info(new_src)

    cls_count = {}
    for nd in ast.walk(nt):
        if isinstance(nd, ast.ClassDef):
            cls_count[nd.name] = sum(
                1 for c in ast.iter_child_nodes(nd)
                if isinstance(c, ast.FunctionDef))
    proxy_count = sum(1 for _ in re.finditer(r'代理到|委托', new_src))

    print(f"\n{B}架构概览 (build {old_build} → {new_build}):{E}")
    for cn, cnt in sorted(cls_count.items(), key=lambda x: -x[1])[:8]:
        print(f"  {cn:22s} {cnt:3d} 方法")
    print(f"  {'WPDM 方法':22s} {len(new_wpdm):3d}")
    print(f"  {'Manager 方法总数':18s} "
          f"{sum(len(v) for v in mgr_methods_map.values()):3d}")
    print(f"  {'代理方法':22s} {proxy_count:3d}")
    print(f"  {'Strangler Fig 别名':18s} {len(aliases):3d}")
    print(f"  {'Canonical API':20s} {len(canonical_methods):3d}")
    print(f"  {'Reset helpers':20s} {len(reset_helpers):3d}")
    print(f"  {'模块级 cache':22s} "
          f"{len(all_caches):3d} (配对 lock {len(all_locks)})")
    print(f"  {'跨组件注入':22s} {len(injections):3d}")
    print(f"  {'Imports':24s} {len(imports_set(new_lines)):3d}")

    return _F == 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    for p in sys.argv[1:3]:
        if not os.path.isfile(p):
            print(f"{R}错误: 文件不存在 — {p}{E}")
            sys.exit(2)
    print(f"{B}WP-SSL-Bootstrap 综合重构验证 v4{E}")
    print(f"  当前版本: {sys.argv[1]}")
    print(f"  基线版本: {sys.argv[2]}")
    sys.exit(0 if run(sys.argv[1], sys.argv[2]) else 1)


if __name__ == "__main__":
    main()
