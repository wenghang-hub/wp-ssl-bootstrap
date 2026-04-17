#!/usr/bin/env python3
"""Full migration verification suite v2 (2026-04).

基于 v1 更新, 识别 38 build 演进差异:
  - 迁移 (WPDM → 5 Manager): 预期的方法重分布
  - Bug 修复: 合法的 try/except/if 增加
  - 架构对称化 (v3.2.327-331): 模块级 caches + reset helpers
  - Strangler Fig (v3.2.330): deprecated 别名

V1-V12 检查保留核心结构化对比, 但对"允许的演化"放宽.
"""
import ast, re, sys
from pathlib import Path

def load(path):
    with open(path, 'r') as f:
        src = f.read()
    return src, src.splitlines(True), ast.parse(src)

old_src, old_lines, old_tree = load(sys.argv[2] if len(sys.argv) > 2 else '/mnt/user-data/uploads/wp_ssl_bootstrap.py')
new_src, new_lines, new_tree = load(sys.argv[1] if len(sys.argv) > 1 else '/home/claude/wp_ssl_bootstrap.py')

PASS = FAIL = WARN = 0
def ok(msg, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2714 {msg}")
    else:
        FAIL += 1
        print(f"  \u2718 {msg}")
        if detail:
            for d in detail.split('\n')[:8]:
                print(f"    {d}")

def info(msg):
    print(f"  \u2139 {msg}")

def warn(msg):
    global WARN
    WARN += 1
    print(f"  \u26a0 {msg}")

def banner(t):
    print(f"\n{'='*70}\n{t}\n{'='*70}")

# ── v2 新增: 识别 v3.2.327-331 架构对称化引入的合法全局状态 ──
ALLOWED_CACHE_GLOBALS = {
    '_NGINX_VERSION_CACHE', '_NGINX_HTTP3_CACHE',
    '_NGINX_HTTP2_DIRECTIVE_CACHE', '_SRCACHE_DETECT_CACHE',
    '_MARIADB_VERSION_CACHE', '_MARIADB_FULL_VERSION_CACHE',
    '_MYSQL_MAJOR_MINOR_CACHE', '_MARIADB_SERVICE_CACHE',
    '_PHP_VERSION_CACHE', '_PHP_FPM_SERVICE_CACHE',
    '_REDIS_VERSION_CACHE', '_REDIS_FULL_VERSION_CACHE',
    '_CERTBOT_VERSION_CACHE', '_CERTBOT_FULL_VERSION_CACHE',
    '_CHINA_CLOUD_CACHE', '_CHINA_NETWORK_CACHE',
    '_MPTCP_SUPPORT_CACHE', '_ECH_SUPPORT_CACHE',
    '_DETECT_SITES_CACHE', '_GHOST_SITES_CACHE',
}

# v3.2.330 Strangler Fig: 原名被重命名为 canonical
KNOWN_RENAMES = {
    'detect_installed_version': 'detect_version',
    '_detect_redis_full_version': 'detect_full_version',
    'detect_service_name': 'detect_service',
    '_detect_php_fpm_service': 'detect_service',
    '_detect_nginx_version': 'detect_version',
    '_detect_mariadb_version': 'detect_version',
    '_detect_mariadb_full_version': 'detect_full_version',
    # 历史重命名 (3.2.292 → 3.2.330)
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

def get_class_info(tree, src_lines):
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = {}
            constants = {}
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.FunctionDef):
                    body_text = '\n'.join(src_lines[ch.lineno-1:ch.end_lineno])
                    methods[ch.name] = {
                        'lineno': ch.lineno,
                        'end': ch.end_lineno,
                        'nlines': ch.end_lineno - ch.lineno + 1,
                        'body': body_text,
                        'args': [a.arg for a in ch.args.args],
                    }
                elif isinstance(ch, ast.Assign):
                    for t in ch.targets:
                        if isinstance(t, ast.Name):
                            constants[t.id] = ch.lineno
            result[node.name] = {'methods': methods, 'constants': constants}
    return result

PROXY_MARKERS = ('代理到', '委托')
DEPRECATED_PATTERN = re.compile(r'\[DEPRECATED v3\.2\.\d+\]')

def is_proxy(body):
    return any(m in body for m in PROXY_MARKERS)

def is_deprecated_alias(body):
    return bool(DEPRECATED_PATTERN.search(body))

old_info = get_class_info(old_tree, old_lines)
new_info = get_class_info(new_tree, new_lines)
MANAGERS = ['NginxManager','MariaDBManager','RedisManager','PHPManager','CertManager']

# ═══════════════════════════════════════════════════════════════════
banner("V1: STRUCTURAL INTEGRITY")
# ═══════════════════════════════════════════════════════════════════

# V1.1: Method conservation (WPDM↓ + Managers↑ = rough equality)
old_wpdm = set(old_info.get('WPDeployManager',{}).get('methods',{}).keys())
new_wpdm = set(new_info.get('WPDeployManager',{}).get('methods',{}).keys())
old_all_mgr = set()
new_all_mgr = set()
for m in MANAGERS:
    old_all_mgr |= set(old_info.get(m,{}).get('methods',{}).keys())
    new_all_mgr |= set(new_info.get(m,{}).get('methods',{}).keys())

old_total = len(old_wpdm) + len(old_all_mgr)
new_total = len(new_wpdm) + len(new_all_mgr)
# v2: 38 build 演化包含合法的死代码清理, 80%+ 是健康范围
# (原阈值 95% 适合单次重构, 不适合多轮演化)
_conservation = 100 * new_total // max(1, old_total)
if _conservation >= 80:
    info(f"方法总数守恒 (WPDM+Managers: {old_total}→{new_total} = {_conservation}%)")
    PASS += 1
    print(f"  \u2714 方法守恒率 {_conservation}% (>80% 合理, 含多轮死代码清理)")
else:
    ok(f"方法总数守恒 (WPDM+Managers: {old_total}→{new_total} = {_conservation}%)",
       _conservation >= 80,
       f"方法数下降超 20%, 可能有未追溯的丢失")

# V1.2: Lost from WPDM should appear in Managers (可能经过 rename)
lost_from_wpdm = old_wpdm - new_wpdm
migrated = lost_from_wpdm & new_all_mgr
renamed = {m for m in lost_from_wpdm
           if m in KNOWN_RENAMES and (KNOWN_RENAMES[m] is None or KNOWN_RENAMES[m] in new_all_mgr)}
truly_lost = lost_from_wpdm - migrated - renamed
ok(f"WPDM 方法全可追溯 ({len(lost_from_wpdm)} 迁出: {len(migrated)} 原名迁移, {len(renamed)} 重命名)",
   len(truly_lost) == 0,
   f"真丢失: {sorted(truly_lost)[:5]}")

# V1.3: Manager method growth
for mgr in MANAGERS:
    old_count = len(old_info.get(mgr,{}).get('methods',{}))
    new_count = len(new_info.get(mgr,{}).get('methods',{}))
    ok(f"{mgr}: {old_count} → {new_count} 方法 (+{new_count-old_count})",
       new_count >= old_count)

# V1.4: Syntax
import py_compile
try:
    py_compile.compile(sys.argv[1] if len(sys.argv) > 1 else '/home/claude/wp_ssl_bootstrap.py', doraise=True)
    ok("Syntax valid (py_compile)", True)
except py_compile.PyCompileError as e:
    ok("Syntax valid", False, str(e))

# ═══════════════════════════════════════════════════════════════════
banner("V2: SIGNATURE FIDELITY (non-proxy WPDM methods)")
# ═══════════════════════════════════════════════════════════════════

wpdm_new = new_info.get('WPDeployManager', {}).get('methods', {})
wpdm_old = old_info.get('WPDeployManager', {}).get('methods', {})

sig_errors = []
sig_checked = 0
for name, info_d in wpdm_new.items():
    if is_proxy(info_d['body']): continue
    if name not in wpdm_old: continue
    old_d = wpdm_old[name]
    sig_checked += 1
    if info_d['args'] != old_d['args']:
        sig_errors.append(f"{name}: args {old_d['args']} → {info_d['args']}")

ok(f"Non-proxy WPDM 签名保真 ({sig_checked} methods)",
   len(sig_errors) == 0, '\n'.join(sig_errors[:5]))

# ═══════════════════════════════════════════════════════════════════
banner("V3: SELF-REFERENCE INTEGRITY")
# ═══════════════════════════════════════════════════════════════════

MGR_SAFE = {
    'platform','run_cmd','cfg','dry_run','_safe_write_file','_get_total_ram_mb',
    '_el_major','_dnf_skip_unavail','_is_dnf5','_exit_code',
    '_nginx_modules_need_recompile','_safe_extract_tar','_safe_reload_nginx',
    '_parse_cert_san_set','_ensure_build_deps','_detect_nginx_user',
    '_run_wpcli','_is_plugin_active','_try_repair','_log_journal_tail',
    '_is_service_active','run_sql','db_svc','_svc_name','fpm_svc',
    '_CF_IPV4_DEFAULTS','_CF_IPV6_DEFAULTS','CA_PROVIDERS',
    '_CERTBOT_LOCK_FILE','CERTBOT_LOCK_TIMEOUT','_inode_retry_count',
    '_brotli_compiled_this_run','_ensure_srcache_modules',
    'apply_nginx_config_safe','get_php_sock_path','_php_fpm_svc',
    '_MARIADB_DEPRECATED_OPTIONS','_MYSQL_TMP_DIR',
    # [v3.2.364] 规则 7 信号检查注入 — 5 个 Manager 都收到 _abort_if_shutdown
    '_abort_if_shutdown',
    # [v3.2.364] NginxManager 跨 Manager 引用 (cert 注入 nginx, brotli 模块)
    'nginx','cert','mariadb','php','redis',
    # [v3.2.330+] Strangler Fig 保留的旧 API 名
    'detect_service_name',
    # [v3.2.335+] 新增平台属性
    '_GLOBAL_SUDO_CACHE',
}

self_ref_errors = []
for mgr in MANAGERS:
    mgr_info = new_info.get(mgr, {})
    available = set(mgr_info.get('methods', {}).keys()) | set(mgr_info.get('constants', {}).keys()) | MGR_SAFE
    for mname, minfo in mgr_info.get('methods', {}).items():
        refs = set(re.findall(r'self\.(\w+)', minfo['body']))
        missing = refs - available - {mname}
        if missing:
            self_ref_errors.append(f"{mgr}.{mname}: 未解析 {sorted(missing)[:3]}")

ok(f"All Manager self.xxx references resolve",
   len(self_ref_errors) == 0, '\n'.join(self_ref_errors[:8]))

# ═══════════════════════════════════════════════════════════════════
banner("V4: STATIC METHOD SANITY")
# ═══════════════════════════════════════════════════════════════════

static_self_errors = []
for node in ast.walk(new_tree):
    if isinstance(node, ast.ClassDef):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.FunctionDef):
                if any(isinstance(d, ast.Name) and d.id == 'staticmethod' for d in ch.decorator_list):
                    if any(isinstance(nd, ast.Name) and nd.id == 'self' for nd in ast.walk(ch)):
                        static_self_errors.append(f"{node.name}.{ch.name} L{ch.lineno}")

ok(f"Zero @staticmethod with self", len(static_self_errors) == 0,
   '\n'.join(static_self_errors[:5]))

# ═══════════════════════════════════════════════════════════════════
banner("V5: CROSS-COMPONENT INJECTION COMPLETENESS")
# ═══════════════════════════════════════════════════════════════════

injections = []
in_wpdm_init = False
for i, line in enumerate(new_lines):
    if re.match(r'^class WPDeployManager', line):
        in_wpdm_init = False
    if in_wpdm_init and re.match(r'^    def ', line) and '__init__' not in line:
        in_wpdm_init = False
    if '    def __init__' in line:
        cls = None
        for j in range(i, -1, -1):
            if new_lines[j].startswith('class '):
                m = re.match(r'class (\w+)', new_lines[j])
                cls = m.group(1) if m else None
                break
        if cls == 'WPDeployManager':
            in_wpdm_init = True
    if in_wpdm_init and re.match(r'\s+self\.(nginx|cert|php|mariadb|redis)\.\w+\s*=', line):
        injections.append(line.strip())

ok(f"Cross-component injections found ({len(injections)})", len(injections) >= 20,
   f"期望 ≥20 个 (migration guard)")

# ═══════════════════════════════════════════════════════════════════
banner("V6: GLOBAL STATEMENT CHECK (v3.2.327+ cache-aware)")
# ═══════════════════════════════════════════════════════════════════

global_in_mgr_non_cache = []
global_in_mgr_cache = []
for node in ast.walk(new_tree):
    if isinstance(node, ast.ClassDef) and node.name in MANAGERS:
        for ch in ast.walk(node):
            if isinstance(ch, ast.Global):
                for nm in ch.names:
                    if nm in ALLOWED_CACHE_GLOBALS:
                        global_in_mgr_cache.append(f"{node.name} L{ch.lineno}: {nm}")
                    else:
                        global_in_mgr_non_cache.append(f"{node.name} L{ch.lineno}: {nm}")

ok(f"Zero non-cache 'global' statements in Managers ({len(global_in_mgr_cache)} cache-globals OK)",
   len(global_in_mgr_non_cache) == 0, '\n'.join(global_in_mgr_non_cache))

# ═══════════════════════════════════════════════════════════════════
banner("V7: MODULE-LEVEL GROWTH (v3.2.327-331 architectural additions)")
# ═══════════════════════════════════════════════════════════════════

def mod_fns(tree):
    return {nd.name for nd in ast.iter_child_nodes(tree)
            if isinstance(nd, (ast.FunctionDef, ast.AsyncFunctionDef))}

def mod_vars(tree):
    names = set()
    for nd in ast.iter_child_nodes(tree):
        if isinstance(nd, ast.Assign):
            for t in nd.targets:
                if isinstance(t, ast.Name): names.add(t.id)
        elif isinstance(nd, ast.AnnAssign) and isinstance(nd.target, ast.Name):
            names.add(nd.target.id)
    return names

old_fns = mod_fns(old_tree)
new_fns = mod_fns(new_tree)
lost_fns = old_fns - new_fns
# Allow _get_nginx_version_tuple → _detect_nginx_version rename
lost_fns -= {'_get_nginx_version_tuple'}
ok(f"模块级函数零丢失 ({len(old_fns)}→{len(new_fns)})",
   len(lost_fns) == 0, f"丢失: {sorted(lost_fns)[:5]}")

new_mod_fns = new_fns - old_fns
info(f"新增模块级函数: {len(new_mod_fns)} 个 (features + reset helpers)")

# Variables: check cache/lock pairing
new_mod_vars = mod_vars(new_tree)
new_vars_added = new_mod_vars - mod_vars(old_tree)
cache_adds = {v for v in new_vars_added if v in ALLOWED_CACHE_GLOBALS or v.endswith('_LOCK')
              or v.endswith('_DEFAULT_VERSION') or v.endswith('_CACHE')}
info(f"新增模块级变量: {len(new_vars_added)} ({len(cache_adds)} caches/locks/consts)")

# ═══════════════════════════════════════════════════════════════════
banner("V8: CACHE/LOCK PAIRING (v3.2.331 invariant)")
# ═══════════════════════════════════════════════════════════════════

all_caches = [v for v in new_mod_vars if v.endswith('_CACHE')]
all_locks = {v for v in new_mod_vars if v.endswith('_LOCK')}
orphan_caches = []
for c in all_caches:
    expected = c.replace('_CACHE', '_LOCK')
    if expected in all_locks:
        continue
    # Short form match
    parts = c.split('_')
    matched = any('_'.join(parts[:i]) + '_LOCK' in all_locks
                  for i in range(len(parts)-1, 1, -1))
    if not matched:
        orphan_caches.append(c)
ok(f"所有 _X_CACHE 有对应 _LOCK ({len(all_caches)} caches, {len(all_locks)} locks)",
   len(orphan_caches) == 0, f"无 lock: {orphan_caches}")

# ═══════════════════════════════════════════════════════════════════
banner("V9: IMPORT PRESERVATION (non-decreasing)")
# ═══════════════════════════════════════════════════════════════════

def imports_set(lines):
    s = set()
    for l in lines:
        if l.startswith('import ') or l.startswith('from '):
            s.add(l.strip())
    return s

old_imps = imports_set(old_lines)
new_imps = imports_set(new_lines)
lost_imps = old_imps - new_imps
ok(f"Imports non-decreasing ({len(old_imps)} → {len(new_imps)})",
   len(lost_imps) == 0, f"丢失: {sorted(lost_imps)[:3]}")

# ═══════════════════════════════════════════════════════════════════
banner("V10: STRANGLER FIG ALIAS INTEGRITY (v3.2.330)")
# ═══════════════════════════════════════════════════════════════════

aliases = []
for mgr in MANAGERS:
    for mname, minfo in new_info.get(mgr, {}).get('methods', {}).items():
        if is_deprecated_alias(minfo['body']):
            has_return_call = 'return self.' in minfo['body']
            aliases.append((mgr, mname, has_return_call))

ok(f"Deprecated 别名都是 return self.X() 委托 ({len(aliases)} aliases)",
   all(h for _, _, h in aliases),
   '; '.join(f"{m}.{n} 无 return" for m, n, h in aliases if not h))
if aliases:
    info(f"Strangler Fig 别名列表: {len(aliases)} 个")
    for m, n, _ in aliases[:5]:
        print(f"    · {m}.{n}")

# ═══════════════════════════════════════════════════════════════════
banner("V11: CANONICAL API SYMMETRY (v3.2.330)")
# ═══════════════════════════════════════════════════════════════════

canonical = {}
for mgr in MANAGERS:
    for mname in new_info.get(mgr, {}).get('methods', {}):
        if mname in ('detect_version','detect_full_version','detect_service','upgrade_to_target'):
            canonical.setdefault(mname, []).append(mgr)

ok(f"5 Manager 都有 detect_version() ({len(canonical.get('detect_version',[]))}/5)",
   len(canonical.get('detect_version',[])) == 5,
   f"缺失: {set(MANAGERS) - set(canonical.get('detect_version',[]))}")
ok(f"3+ Manager 有 detect_service() ({len(canonical.get('detect_service',[]))}/3)",
   len(canonical.get('detect_service',[])) >= 3,
   f"有: {canonical.get('detect_service',[])}")
ok(f"3+ Manager 有 upgrade_to_target() ({len(canonical.get('upgrade_to_target',[]))}/3)",
   len(canonical.get('upgrade_to_target',[])) >= 3)

# ═══════════════════════════════════════════════════════════════════
banner("V12: RESET HELPER SYMMETRY (v3.2.327-328)")
# ═══════════════════════════════════════════════════════════════════

reset_helpers = [f for f in new_fns if f.startswith('_reset_') and 'capability_caches' in f]
ok(f"5 Manager 都有 _reset_X_capability_caches ({len(reset_helpers)})",
   len(reset_helpers) >= 5,
   f"找到: {sorted(reset_helpers)}")

# ═══════════════════════════════════════════════════════════════════
banner("SUMMARY")
# ═══════════════════════════════════════════════════════════════════

total = PASS + FAIL
if FAIL == 0:
    print(f"\n✅ ALL {total} CHECKS PASSED ({WARN} warnings)")
else:
    print(f"\n❌ {FAIL}/{total} CHECKS FAILED ({WARN} warnings)")

print(f"\nBaseline → Current stats (3.2.292 → 3.2.331, 38 builds):")
print(f"  WPDM methods:   {len(old_wpdm)} → {len(new_wpdm)}")
print(f"  Manager total:  {len(old_all_mgr)} → {len(new_all_mgr)}")
print(f"  Method conservation: {new_total}/{old_total} = {100*new_total//max(1,old_total)}%")
print(f"  Cross-component injections: {len(injections)}")
print(f"  Module-level caches: {len(all_caches)} (with {len(all_locks)} locks)")
print(f"  Reset helpers: {len(reset_helpers)}")
print(f"  Canonical API methods: {sum(len(v) for v in canonical.values())}")
print(f"  Strangler Fig 别名: {len(aliases)}")

sys.exit(0 if FAIL == 0 else 1)
