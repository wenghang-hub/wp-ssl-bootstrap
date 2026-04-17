#!/usr/bin/env python3
"""
WP-SSL-Bootstrap 重构验证脚本 v3 (2026-04)
==========================================================================
基于 v2 更新, 增加对 v3.2.327-330 架构对称化重构的识别:

  ✓ 模块级缓存 (_X_VERSION_CACHE + _X_LOCK) — 合法添加
  ✓ Reset helpers (_reset_X_capability_caches) — 合法添加
  ✓ Manager 内 `global _X_CACHE` 语句 — 由缓存架构要求 (白名单)
  ✓ Deprecated 别名 (Strangler Fig) — 返回值委托模式
  ✓ Canonical detect_version/detect_service/upgrade_to_target — 对称 API

还原 WPDM → 5 Manager 迁移检测 (方向感知):
  WPDM 方法数应当 ↓ (迁移出), Manager 方法数应当 ↑ (迁移入)
  总方法数保持近似相等

用法:
  python3 verify_refactor_v3.py <refactored.py> <original.py>
==========================================================================
"""
import ast, re, sys, os, difflib

# ── 输出 ──
G = "\033[92m" if sys.stdout.isatty() else ""
R = "\033[91m" if sys.stdout.isatty() else ""
Y = "\033[93m" if sys.stdout.isatty() else ""
B = "\033[1m" if sys.stdout.isatty() else ""
D = "\033[2m" if sys.stdout.isatty() else ""
E = "\033[0m" if sys.stdout.isatty() else ""
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

MGR = {'nginx':'NginxManager','mariadb':'MariaDBManager',
       'redis':'RedisManager','php':'PHPManager','cert':'CertManager'}

# MGR_SAFE: 跨 Manager 注入的属性 (WPDM.__init__ 中 self.X.attr = ... 模式)
MGR_SAFE = {
    # 构造函数参数
    'platform', 'run_cmd', 'cfg',
    # 实例状态
    'db_svc', '_svc_name', 'fpm_svc',
    # 跨 Manager 注入的方法
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
    # [v3.2.364] 跨 Manager 互引用: cert 注入 nginx, 反之亦然
    'nginx', 'cert', 'mariadb', 'php', 'redis',
    # [v3.2.330+] Strangler Fig 保留的旧 API 名
    'detect_service_name',
    # [v3.2.335+] 新增平台/运行期属性
    '_GLOBAL_SUDO_CACHE',
}

# [v3] v3.2.327-330 架构对称化: 允许的模块级缓存 global 白名单
ALLOWED_GLOBAL_CACHES = {
    '_NGINX_VERSION_CACHE', '_NGINX_HTTP3_CACHE',
    '_NGINX_HTTP2_DIRECTIVE_CACHE', '_SRCACHE_DETECT_CACHE',
    '_MARIADB_VERSION_CACHE', '_MARIADB_FULL_VERSION_CACHE',
    '_MYSQL_MAJOR_MINOR_CACHE', '_MARIADB_SERVICE_CACHE',
    '_PHP_VERSION_CACHE', '_PHP_FPM_SERVICE_CACHE',
    '_REDIS_VERSION_CACHE', '_REDIS_FULL_VERSION_CACHE',
    '_CERTBOT_VERSION_CACHE', '_CERTBOT_FULL_VERSION_CACHE',
    '_CHINA_CLOUD_CACHE', '_CHINA_NETWORK_CACHE',
    '_MPTCP_SUPPORT_CACHE', '_ECH_SUPPORT_CACHE',
}

# [v3] v3.2.327-330 新增的合法模块级函数 (reset helpers)
# [v3.2.364] 扩展: v3.2.288+ 新增的 33 个模块级函数 (ECH/MPTCP/DNS APIs 等)
ALLOWED_NEW_MODULE_FUNCTIONS = {
    # Reset helpers (v3.2.327-328)
    '_reset_nginx_capability_caches',
    '_reset_mariadb_capability_caches',
    '_reset_php_capability_caches',
    '_reset_redis_capability_caches',
    '_reset_certbot_capability_caches',
    # nginx capability detection (module-level cached)
    '_detect_nginx_version',
    '_detect_nginx_http3_capable',
    '_detect_nginx_http2_directive',
    '_nginx_supports_max_headers',
    '_nginx_supports_add_header_inherit',
    '_nginx_fastcgi_buffers_tiered',
    # [v3.2.292+] ECH (Encrypted ClientHello) full automation
    '_detect_ech_support',
    '_generate_ech_keypair',
    'setup_ech',
    '_extract_ech_config_base64',
    '_ech_dns_auto',
    '_install_ech_rotation_timer',
    '_print_ech_dns_record',
    '_verify_ech_dns',
    # [v3.2.292+] DNS provider APIs for ECH HTTPS record upsert
    '_cf_api_request',
    '_cf_get_zone_id',
    '_cf_upsert_https_record',
    '_r53_upsert_https_record',
    '_alidns_upsert_https_record',
    '_dnspod_api',
    '_dnspod_upsert_https_record',
    # [v3.2.292+] MPTCP runtime detection
    '_detect_mptcp_support',
    '_reset_mptcp_cache',
    # [v3.2.292+] OCSP smart decision
    '_cert_supports_ocsp',
    '_decide_ocsp_enable',
    # [v3.2.292+] Platform detection helpers
    '_detect_debian_bookworm',
    '_is_openeuler_like',
    # [v3.2.292+] Valkey/Redis/EPEL installation helpers
    '_install_valkey_debian',
    '_enable_bookworm_backports',
    '_redis_flavor_name',
    '_install_epel_release',
}

# [v3.2.364] 合法删除的 WPDM 方法 (全部由 Manager 公开 API 替换或已内联)
ALLOWED_DELETED_WPDM_METHODS = {
    # 已被 CertManager 公开 API 替代
    '_certbot_supports_key_type',      # → CertManager.supports_key_type (inlined)
    '_detect_cert_issuer',             # → CertManager.detect_cert_issuer
    '_detect_cert_key_type',           # → inlined
    '_detect_certbot_full_version',    # → CertManager.detect_full_version
    '_detect_certbot_version',         # → CertManager.detect_version
    '_is_pip_venv_certbot',            # → CertManager internal
    '_is_snap_certbot',                # → CertManager internal
    # 已被 MariaDBManager 公开 API 替代
    '_detect_db_service',              # → MariaDBManager.detect_service
    '_detect_installed_mariadb_version',  # → MariaDBManager.detect_version
    '_get_mariadb_full_version',       # → MariaDBManager.detect_full_version
    # 已被 PHPManager 公开 API 替代
    '_detect_installed_php_version',   # → PHPManager.detect_version
    '_get_active_php_conf_paths',      # → PHPManager internal
    '_get_active_php_ini_paths',       # → PHPManager internal
    '_get_active_php_ver_str',         # → 0 调用者, 彻底删除
    '_get_php_conf_paths',             # → PHPManager internal
    '_get_php_ini_paths',              # → PHPManager internal
    '_read_php_ini_values',            # → PHPManager internal
    # 已被 NginxManager 公开 API 替代
    '_detect_nginx_user',              # → NginxManager.detect_user
    '_get_nginx_version_tuple',        # → NginxManager.detect_version
    '_safe_reload_nginx',              # → NginxManager.safe_reload (+ cross-inject)
    '_srcache_install_load_module',    # → NginxManager internal (inlined)
    # 已被 RedisManager 公开 API 替代
    '_detect_redis_service_name',      # → RedisManager.detect_service_name (Strangler)
    '_detect_redis_version',           # → RedisManager.detect_version
}

# [v3.2.364] 合法删除的模块级函数
ALLOWED_DELETED_MODULE_FUNCTIONS = {
    '_get_nginx_version_tuple',  # → NginxManager.detect_version (canonical API)
}

# [v3] v3.2.330 Strangler Fig: deprecated 别名模式
DEPRECATED_ALIAS_PATTERN = re.compile(
    r'\[DEPRECATED v3\.2\.\d+\].*?别名'
)

_PROXY_MARKERS = ('代理到', '委托')

def _is_proxy(text):
    return any(m in text for m in _PROXY_MARKERS)

def _is_deprecated_alias(body_text):
    """Check if this method is a deprecated alias (Strangler Fig)."""
    return bool(DEPRECATED_ALIAS_PATTERN.search(body_text))

# ── AST helpers ──
def cls_methods(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return {c.name for c in ast.iter_child_nodes(n) if isinstance(c, ast.FunctionDef)}
    return set()

def self_attrs(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == name:
            r = set()
            for ch in ast.iter_child_nodes(n):
                if isinstance(ch, ast.FunctionDef):
                    r.add(ch.name)
                    for nd in ast.walk(ch):
                        targets = []
                        if isinstance(nd, (ast.AugAssign, ast.AnnAssign)) and hasattr(nd, 'target') and nd.target:
                            targets = [nd.target]
                        elif isinstance(nd, ast.Assign):
                            targets = nd.targets
                        for t in targets:
                            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
                                r.add(t.attr)
                elif isinstance(ch, ast.Assign):
                    for t in ch.targets:
                        if isinstance(t, ast.Name): r.add(t.id)
            return r
    return set()

def self_refs(method):
    return {nd.attr for nd in ast.walk(method)
            if isinstance(nd, ast.Attribute) and isinstance(nd.value, ast.Name) and nd.value.id == 'self'}

def get_method_bodies(src, cls_name):
    tree = ast.parse(src)
    lines = src.split('\n')
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls_name:
            return {ch.name: lines[ch.lineno-1:ch.end_lineno]
                    for ch in ast.iter_child_nodes(n) if isinstance(ch, ast.FunctionDef)}
    return {}

# ══════════════════════════════════════════════════════════════
# 主验证
# ══════════════════════════════════════════════════════════════

def run(new_path, old_path):
    with open(new_path, encoding="utf-8") as f: new_src = f.read()
    with open(old_path, encoding="utf-8") as f: old_src = f.read()
    nl = new_src.split('\n')

    # ═══════════════════════════ 结构层 ═══════════════════════════

    banner("结构层 [A] compile() — 字节码编译")
    try:
        nt = ast.parse(new_src)
        ok("AST 解析", True)
    except SyntaxError as e:
        ok("AST 解析", False, str(e))
        return False
    try:
        compile(new_src, os.path.basename(new_path), "exec")
        ok("compile()", True)
    except SyntaxError as e:
        ok("compile()", False, str(e))
    try:
        ot = ast.parse(old_src)
        ok("基线 AST", True)
    except SyntaxError as e:
        ok("基线 AST", False, str(e))
        ot = None

    # ═══════════════════════════ 方向感知迁移检测 ═══════════════════════════

    banner("结构层 [B] 方向感知迁移完整性 (WPDM→Managers)")
    if ot:
        # WPDM 方法应↓, Manager 方法应↑, 总和应近似
        ow = cls_methods(ot, 'WPDeployManager')
        nw = cls_methods(nt, 'WPDeployManager')
        lost_from_wpdm = ow - nw

        # Collect total Manager methods in new tree
        new_all_mgr = set()
        for cn in MGR.values():
            new_all_mgr |= cls_methods(nt, cn)
        old_all_mgr = set()
        for cn in MGR.values():
            old_all_mgr |= cls_methods(ot, cn)

        # Lost from WPDM should appear in Managers
        migrated_to_mgr = lost_from_wpdm & new_all_mgr
        truly_lost = lost_from_wpdm - new_all_mgr

        # Some methods may be renamed (Strangler Fig), exclude those whose
        # canonical equivalent exists
        _rename_map = {
            'detect_installed_version': 'detect_version',
            '_detect_redis_full_version': 'detect_full_version',
            'detect_service_name': 'detect_service',
            '_detect_php_fpm_service': 'detect_service',
        }
        # If something is "lost" but its canonical rename exists in any Manager, OK
        renamed_survivors = set()
        for m in truly_lost:
            if m in _rename_map and _rename_map[m] in new_all_mgr:
                renamed_survivors.add(m)
        truly_lost -= renamed_survivors
        # [v3.2.364] 合法清理白名单: 明确删除/内联的旧 WPDM 方法
        truly_lost -= ALLOWED_DELETED_WPDM_METHODS

        ok(f"WPDM 方法数 {len(ow)}→{len(nw)} (迁移 {len(migrated_to_mgr)}, 真丢失 {len(truly_lost)})",
           len(truly_lost) == 0,
           f"真丢失: {sorted(truly_lost)[:5]}" if truly_lost else "")
        ok(f"Manager 总方法数 {len(old_all_mgr)}→{len(new_all_mgr)} (增长)",
           len(new_all_mgr) >= len(old_all_mgr))
        info(f"方法守恒率: {(len(new_all_mgr) + len(nw))}/{(len(old_all_mgr) + len(ow))} = "
             f"{100 * (len(new_all_mgr) + len(nw)) // max(1, (len(old_all_mgr) + len(ow)))}%")

        # SiteConfig 和 CmdResult 应保持不变
        for c in ('SiteConfig','CmdResult'):
            ok(f"{c} 不变", cls_methods(ot, c) == cls_methods(nt, c))

    # ═══════════════════════════ 模块级演化 (新增合法性) ═══════════════════════════

    banner("结构层 [C] 模块级演化 (v3.2.327-330 架构对称化)")
    if ot:
        def mod_level_names(tree, node_types):
            names = set()
            for nd in ast.iter_child_nodes(tree):
                if isinstance(nd, node_types):
                    if hasattr(nd, 'name'):
                        names.add(nd.name)
                    elif isinstance(nd, ast.Assign):
                        for t in nd.targets:
                            if isinstance(t, ast.Name): names.add(t.id)
                    elif isinstance(nd, ast.AnnAssign) and isinstance(nd.target, ast.Name):
                        names.add(nd.target.id)
            return names

        old_mod_fns = mod_level_names(ot, (ast.FunctionDef, ast.AsyncFunctionDef))
        new_mod_fns = mod_level_names(nt, (ast.FunctionDef, ast.AsyncFunctionDef))
        lost_fns = old_mod_fns - new_mod_fns
        new_fns = new_mod_fns - old_mod_fns
        # [v3.2.364] 合法删除白名单
        lost_fns -= ALLOWED_DELETED_MODULE_FUNCTIONS

        ok(f"模块级函数零丢失 ({len(old_mod_fns)}→{len(new_mod_fns)})",
           len(lost_fns) == 0,
           f"丢失: {sorted(lost_fns)[:5]}")

        unexpected_new = new_fns - ALLOWED_NEW_MODULE_FUNCTIONS
        ok(f"新增模块级函数全部合法 ({len(new_fns)} 新增)",
           len(unexpected_new) == 0 or all(f.startswith(('_reset_', '_detect_')) for f in unexpected_new),
           f"未预期新增: {sorted(unexpected_new)[:5]}")
        if new_fns:
            info(f"本次新增: {sorted(new_fns & ALLOWED_NEW_MODULE_FUNCTIONS)[:6]}")

        # 模块级变量 (caches, constants)
        old_mod_vars = mod_level_names(ot, (ast.Assign, ast.AnnAssign))
        new_mod_vars = mod_level_names(nt, (ast.Assign, ast.AnnAssign))
        new_vars = new_mod_vars - old_mod_vars
        cache_vars = {v for v in new_vars if v in ALLOWED_GLOBAL_CACHES or v.endswith(('_CACHE', '_LOCK', '_DEFAULT_VERSION'))}
        unexpected_vars = new_vars - cache_vars
        ok(f"新增模块级变量全部合法 ({len(new_vars)} 新增, {len(cache_vars)} cache/const)",
           len(unexpected_vars) == 0 or all(
               v.startswith('_') and v.isupper() or v.endswith(('_CACHE', '_LOCK'))
               for v in unexpected_vars),
           f"未预期: {sorted(unexpected_vars)[:5]}")

    # ═══════════════════════════ Manager global 语句 (cache-aware) ═══════════════════════════

    banner("结构层 [D] Manager global 语句 (v3.2.327+ cache 白名单)")
    gi_non_cache = []
    gi_cache = []
    for cn in MGR.values():
        for nd in ast.walk(nt):
            if isinstance(nd, ast.ClassDef) and nd.name == cn:
                for ch in ast.iter_child_nodes(nd):
                    if isinstance(ch, ast.FunctionDef):
                        for n in ast.walk(ch):
                            if isinstance(n, ast.Global):
                                for nm in n.names:
                                    if nm in ALLOWED_GLOBAL_CACHES:
                                        gi_cache.append(f"{cn}.{ch.name}: {nm}")
                                    else:
                                        gi_non_cache.append(f"{cn}.{ch.name}: {nm}")
    ok(f"Manager 零非缓存 global 语句 ({len(gi_cache)} cache globals OK)",
       len(gi_non_cache) == 0,
       "\n".join(f"    {g}" for g in gi_non_cache[:5]))
    if gi_cache:
        info(f"合法缓存 global: {len(gi_cache)} 处 (v3.2.327-330 对称架构)")

    # ═══════════════════════════ Strangler Fig 别名检测 ═══════════════════════════

    banner("结构层 [E] Strangler Fig 别名完整性")
    deprecated_aliases = []
    canonical_methods = set()
    for cn in MGR.values():
        for nd in ast.walk(nt):
            if isinstance(nd, ast.ClassDef) and nd.name == cn:
                for ch in ast.iter_child_nodes(nd):
                    if isinstance(ch, ast.FunctionDef):
                        body_src = '\n'.join(nl[ch.lineno-1:ch.end_lineno])
                        if _is_deprecated_alias(body_src):
                            # Verify delegation pattern: return self.X()
                            has_return_call = any(
                                isinstance(s, ast.Return) and isinstance(s.value, ast.Call)
                                for s in ast.walk(ch)
                            )
                            deprecated_aliases.append((cn, ch.name, has_return_call))
                        elif ch.name in ('detect_version', 'detect_full_version', 'detect_service', 'upgrade_to_target'):
                            canonical_methods.add(f"{cn}.{ch.name}")
    ok(f"Deprecated 别名都是 return 委托 ({len(deprecated_aliases)} 别名)",
       all(has_ret for _, _, has_ret in deprecated_aliases),
       "; ".join(f"{c}.{m} 无 return" for c, m, h in deprecated_aliases if not h))
    if deprecated_aliases:
        info(f"Strangler Fig 别名: {len(deprecated_aliases)} 个")
        for c, m, _ in deprecated_aliases[:5]:
            print(f"    {D}· {c}.{m}{E}")

    # ═══════════════════════════ Canonical API 对称 ═══════════════════════════

    banner("结构层 [F] Canonical API 对称性")
    need_detect_version = set(MGR.values())
    have_detect_version = {m.split('.')[0] for m in canonical_methods if m.endswith('.detect_version')}
    missing = need_detect_version - have_detect_version
    ok(f"5 Manager 都有 detect_version() canonical API",
       len(missing) == 0,
       f"缺失: {sorted(missing)}")
    ok(f"3 Manager 有 detect_service() (MariaDB/Redis/PHP)",
       len({m for m in canonical_methods if m.endswith('.detect_service')}) >= 3,
       f"")
    ok(f"3 Manager 有 upgrade_to_target() (MariaDB/Redis/PHP)",
       len({m for m in canonical_methods if m.endswith('.upgrade_to_target')}) >= 3,
       f"")

    # ═══════════════════════════ Reset 对称性 ═══════════════════════════

    banner("结构层 [G] Reset Helper 对称性")
    reset_helpers = {f for f in new_mod_fns if f.startswith('_reset_') and 'capability_caches' in f}
    ok(f"5 Manager 都有 _reset_X_capability_caches ({len(reset_helpers)})",
       len(reset_helpers) >= 5,
       f"找到: {sorted(reset_helpers)}")

    # ═══════════════════════════ Manager self 引用 ═══════════════════════════

    banner("结构层 [H] Manager self 引用自洽")
    mm = {}
    broken = []
    for acc, cn in MGR.items():
        for n in ast.walk(nt):
            if isinstance(n, ast.ClassDef) and n.name == cn:
                ms = {c.name for c in ast.iter_child_nodes(n) if isinstance(c, ast.FunctionDef)}
                for ch in ast.iter_child_nodes(n):
                    if isinstance(ch, ast.Assign):
                        for t in ch.targets:
                            if isinstance(t, ast.Name): ms.add(t.id)
                mm[acc] = ms
                for ch in ast.iter_child_nodes(n):
                    if not isinstance(ch, ast.FunctionDef) or ch.name == '__init__': continue
                    for r in self_refs(ch):
                        if r not in ms and r not in MGR_SAFE and r != ch.name:
                            broken.append(f"{cn}.{ch.name}: self.{r}")
                break
        ok(f"{cn} self 引用自洽 ({len(mm.get(acc, set()))-1}m)",
           not any(b.startswith(f"{cn}.") for b in broken))

    # ═══════════════════════════ 重复方法/参数检查 ═══════════════════════════

    banner("结构层 [I] 零重复方法 & 零重复参数")
    for n in ast.walk(nt):
        if isinstance(n, ast.ClassDef):
            ms = [c.name for c in ast.iter_child_nodes(n) if isinstance(c, ast.FunctionDef)]
            seen, d = set(), set()
            for m in ms:
                if m in seen: d.add(m)
                seen.add(m)
            ok(f"{n.name} 零重复方法", len(d) == 0, f"重复: {sorted(d)}" if d else "")
    dp = [n.name for n in ast.walk(nt) if isinstance(n, ast.FunctionDef)
          and len([a.arg for a in n.args.args]) != len(set(a.arg for a in n.args.args))]
    ok("零重复参数", len(dp) == 0, str(dp[:3]) if dp else "")

    # ═══════════════════════════ Caching 架构不变式 ═══════════════════════════

    banner("架构层 [J] Caching 模式完整性")
    # For each *_CACHE, should have matching *_LOCK and reset path
    for cache_name in sorted(ALLOWED_GLOBAL_CACHES):
        if cache_name not in new_src: continue
        lock_name = cache_name.replace('_CACHE', '_LOCK')
        ok(f"{cache_name} 有对应 {lock_name}", lock_name in new_src)

    # Each cache should be reset by at least one helper
    cache_resets = {}
    for fn_name in reset_helpers:
        for n in ast.walk(nt):
            if isinstance(n, ast.FunctionDef) and n.name == fn_name:
                for g in ast.walk(n):
                    if isinstance(g, ast.Global):
                        for nm in g.names:
                            cache_resets.setdefault(nm, []).append(fn_name)
    unreset = [c for c in ALLOWED_GLOBAL_CACHES if c in new_src and c not in cache_resets
               and c not in ('_NGINX_HTTP3_CACHE', '_NGINX_HTTP2_DIRECTIVE_CACHE',
                             '_SRCACHE_DETECT_CACHE', '_CHINA_CLOUD_CACHE',
                             '_CHINA_NETWORK_CACHE', '_MPTCP_SUPPORT_CACHE',
                             '_ECH_SUPPORT_CACHE')]
    ok(f"所有 detect 缓存有对应 reset ({len(cache_resets)}/{len([c for c in ALLOWED_GLOBAL_CACHES if c in new_src])} 覆盖)",
       len(unreset) == 0,
       f"未覆盖: {unreset[:3]}")

    # ═══════════════════════════ 代码卫生 ═══════════════════════════

    banner("卫生层 [K] 未使用局部变量")
    _unused_locals = []
    for _n in ast.walk(nt):
        if isinstance(_n, ast.ClassDef):
            for _ch in ast.iter_child_nodes(_n):
                if not isinstance(_ch, ast.FunctionDef): continue
                _body_lines = nl[_ch.lineno-1:_ch.end_lineno]
                _body_str = '\n'.join(_body_lines)
                _globals = set()
                for _nd in ast.walk(_ch):
                    if isinstance(_nd, ast.Global):
                        _globals.update(_nd.names)
                for _nd in ast.walk(_ch):
                    if isinstance(_nd, ast.Assign) and len(_nd.targets) == 1:
                        _tgt = _nd.targets[0]
                        if isinstance(_tgt, ast.Name) and _tgt.id.startswith('_'):
                            _var = _tgt.id
                            if _var == '_' or _var in _globals: continue
                            _count = _body_str.count(_var)
                            if _count <= 1:
                                _unused_locals.append(
                                    f"{_n.name}.{_ch.name}: {_var}")
    ok(f"零未使用局部变量 ({len(_unused_locals)} found)",
       len(_unused_locals) == 0,
       "; ".join(_unused_locals[:5]))

    # ═══════════════════════════ Shell/Security ═══════════════════════════

    banner("安全层 [L] shell=True / bare except 对等")
    def count_shell_true(tree):
        return sum(1 for nd in ast.walk(tree) if isinstance(nd, ast.Call)
                   for kw in nd.keywords if kw.arg == 'shell'
                   and isinstance(kw.value, ast.Constant) and kw.value.value is True)
    if ot:
        os_t, ns_t = count_shell_true(ot), count_shell_true(nt)
        ok(f"shell=True 不新增 ({os_t}→{ns_t})", ns_t <= os_t)
        def bare_exc(tree):
            return sum(1 for c in ast.walk(tree) if isinstance(c, ast.ExceptHandler) and c.type is None)
        ob, nb = bare_exc(ot), bare_exc(nt)
        ok(f"裸 except 不新增 ({ob}→{nb})", nb <= ob)

    # ═══════════════════════════ 汇总 ═══════════════════════════

    total = _P + _F
    print(f"\n{'═' * 62}")
    if _F == 0:
        print(f"{G}{B}✅ 全部 {total} 项通过{E}{f' ({_W} 警告)' if _W else ''}")
    else:
        print(f"{R}{B}❌ {_F}/{total} 项失败{E}{f' ({_W} 警告)' if _W else ''}")
    print(f"{'═' * 62}")

    # 架构概览
    cc = {}
    for n in ast.walk(nt):
        if isinstance(n, ast.ClassDef):
            cc[n.name] = sum(1 for c in ast.iter_child_nodes(n) if isinstance(c, ast.FunctionDef))
    px = sum(1 for _ in re.finditer(r'代理到|委托', new_src))
    print(f"\n{B}架构概览:{E}")
    for c, num in sorted(cc.items(), key=lambda x: -x[1])[:8]:
        print(f"  {c:20s} {num:3d} 方法")
    print(f"  {'代理方法':18s} {px:3d}")
    print(f"  {'Manager 方法':16s} {sum(len(v) for v in mm.values()):3d}")
    print(f"  {'Deprecated 别名':16s} {len(deprecated_aliases):3d}")
    print(f"  {'Canonical API':16s} {len(canonical_methods):3d}")
    print(f"  {'Reset helpers':16s} {len(reset_helpers):3d}")
    print(f"  {'模块级缓存':18s} {sum(1 for c in ALLOWED_GLOBAL_CACHES if c in new_src):3d}")
    return _F == 0

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    for p in sys.argv[1:3]:
        if not os.path.isfile(p):
            print(f"{R}错误: 文件不存在 — {p}{E}")
            sys.exit(2)
    print(f"{B}WP-SSL-Bootstrap 重构验证 v3{E}")
    print(f"  重构版: {sys.argv[1]}")
    print(f"  基线版: {sys.argv[2]}")
    sys.exit(0 if run(sys.argv[1], sys.argv[2]) else 1)

if __name__ == "__main__":
    main()
