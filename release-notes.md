# WP-SSL-Bootstrap V3.2.8 Release Notes

> 全栈主要组件升级 + TLS ECH 隐私增强 + MPTCP 多路径传输 + 架构规则 100% 清洁
> Full-stack major component upgrade + TLS ECH privacy + MPTCP multi-path + 100% architecture rule clean

**Build**: `3.2.365`（从 V3.2.7 `build 287` 起 +7,500+ 代码行 / +49 真·新方法（+219 从 WPDeployManager god-class 迁移到各专业 Manager）/ +11 Manager 公开 API / +10 新 CLI 参数）
**Build**: `3.2.365` (+7,500+ LOC / +49 truly new methods (+219 migrated from WPDeployManager god-class to specialized Managers) / +11 Manager public APIs / +10 new CLI flags since V3.2.7 `build 287`)

> **⚠️ 重要版本说明 / Important version note**: V3.2.8 生产部署请使用 **build 365+** 或保持在 **build 358**。Build 359-364 包含架构清理的中间状态, 其中 build 364 有启动期 NameError 问题 (已在 365 修复)。  
> V3.2.8 production deployment should use **build 365+** or stay at **build 358**. Builds 359-364 are architectural cleanup intermediate states; build 364 contains a startup NameError (fixed in 365).

## 核心升级 / Core Upgrades

### 🚀 组件栈升级（主要版本号）/ Component stack upgrade (major versions)

| 组件 | V3.2.7 目标 | V3.2.8 目标 | 新特性 |
|-----|-----------|-----------|-------|
| **nginx** | 1.28 | **1.30** | HTTP/2 upstream、Early Hints（103）、ECH、keepalive 默认、`max_headers` / `add_header_inherit`、`quic_retry` / `quic_gso` |
| **PHP** | 8.4 | **8.5** | 新 URI 扩展、pipe operator `\|>`、`#[\NoDiscard]`、closures/casts/first-class callables in constant expressions（2025-11 GA，active support 至 2027-12）|
| **MariaDB** | 10.11 LTS | **11.8 LTS** | **Vector Search** 内建（`VECTOR(N)` + cosine/Euclidean 距离）、JSON_TABLE、InnoDB bulk load +40%、parallel replication 增强（2025-05 GA，LTS 至 2028-05）|
| **Valkey** | （自动检测）| **9.0 (target)** | BSD 3-Clause 开源许可、40% 吞吐提升、原子 slot 迁移、hash field expiration |

---

| Component | V3.2.7 target | V3.2.8 target | New features |
|-----------|---------------|---------------|--------------|
| **nginx** | 1.28 | **1.30** | HTTP/2 upstream, Early Hints (103), ECH, keepalive default, `max_headers` / `add_header_inherit`, `quic_retry` / `quic_gso` |
| **PHP** | 8.4 | **8.5** | New URI extension, pipe operator `\|>`, `#[\NoDiscard]`, closures/casts/first-class callables in constant expressions (GA 2025-11, active support until 2027-12) |
| **MariaDB** | 10.11 LTS | **11.8 LTS** | **Vector Search** built-in (`VECTOR(N)` + cosine/Euclidean distance), JSON_TABLE, InnoDB bulk load +40%, enhanced parallel replication (GA 2025-05, LTS until 2028-05) |
| **Valkey** | (auto) | **9.0 (target)** | BSD 3-Clause, 40% throughput, atomic slot migration, hash field expiration |

### 🔐 TLS ECH (Encrypted ClientHello) — 全自动配置链

RFC 9849 最新隐私协议，把 ClientHello 里的 SNI 加密传输。**ECH 防止 ISP / 防火墙通过 SNI 识别目标站点**，对跨境站点和隐私敏感场景显著。

端到端流程：
1. `_detect_ech_support()` 检测 OpenSSL ≥ 4.0 含 ECH + Nginx 1.30 `ssl_ech_file`
2. `_generate_ech_keypair()` 生成 ECH 密钥对（OpenSSL 原生）
3. `_extract_ech_config_base64()` 提取 ECHConfig 公钥 → Base64
4. 自动通过 4 家 DNS API 写 HTTPS 记录：**Cloudflare** / **AWS Route53** / **阿里云 DNS** / **DNSPod（腾讯云）**
5. `_verify_ech_dns()` 验证 DNS 已全球生效
6. `_install_ech_rotation_timer()` systemd timer 自动密钥轮换

CLI：
- `--ech` 启用
- `--cf-api-token <TOKEN>` Cloudflare API
- Route53: `--change-batch` / `--dns-name` / `--hosted-zone-id`
- 无 API token → 打印记录给用户手动添加

---

RFC 9849 latest privacy protocol encrypts SNI in ClientHello. **ECH prevents ISP/firewall SNI-based site identification** — significant for cross-border sites and privacy-sensitive scenarios.

End-to-end pipeline:
1. `_detect_ech_support()` probes OpenSSL ≥ 4.0 with ECH + Nginx 1.30 `ssl_ech_file`
2. `_generate_ech_keypair()` generates ECH keypair (OpenSSL native)
3. `_extract_ech_config_base64()` extracts ECHConfig public key → Base64
4. Auto-publishes HTTPS record via 4 DNS APIs: **Cloudflare** / **AWS Route53** / **Aliyun DNS** / **DNSPod (Tencent Cloud)**
5. `_verify_ech_dns()` verifies global DNS propagation
6. `_install_ech_rotation_timer()` systemd timer auto key rotation

CLI: `--ech` to enable; `--cf-api-token <TOKEN>` for Cloudflare; Route53 `--change-batch` / `--dns-name` / `--hosted-zone-id`; no API token → prints record for manual add.

### 📡 MPTCP (Multipath TCP) 支持

运行时内核支持探测 + Nginx MPTCP 自动启用。**多 NIC 服务器、4G/5G+Wi-Fi 移动客户端、跨运营商链路聚合场景自动多径化**，单链路故障无感切换。

- `_detect_mptcp_support()` 运行时探测 `net.mptcp.enabled` + Nginx 构建 MPTCP
- `_ensure_mptcp_nginx_support()` 自动 `sysctl -w net.mptcp.enabled=1`
- Nginx `listen 443 ssl quic mptcp` 指令启用
- CLI：`--mptcp`（强制开启/降级）、`--no-mptcp`（禁用）、不指定（auto）

---

Runtime kernel probe + Nginx MPTCP auto-enable. **Multi-NIC servers, 4G/5G+Wi-Fi mobile clients, cross-carrier link aggregation get automatic multi-path**; transparent failover on single-link failure.

- `_detect_mptcp_support()` probes `net.mptcp.enabled` + Nginx MPTCP build
- `_ensure_mptcp_nginx_support()` auto `sysctl -w net.mptcp.enabled=1`
- Nginx `listen 443 ssl quic mptcp` directive
- CLI: `--mptcp` (force/degrade), `--no-mptcp` (disable), unspecified (auto)

### 🎯 OCSP stapling 智能决策

2025 年起 Let's Encrypt 停发 OCSP responder，证书里没有 OCSP URI，Nginx `ssl_stapling on` 会在 error log 打 warning。

- `_cert_supports_ocsp()` 用 `openssl x509 -ocsp_uri` 读证书 Authority Information Access 扩展（ground truth）
- 无 OCSP URI → 自动关闭 stapling
- 非 LE CA（ZeroSSL 等）→ 自动启用
- CLI：`--ocsp-stapling` / `--no-ocsp-stapling` 用户显式覆盖

---

2025: Let's Encrypt deprecated OCSP responder; certificates lack OCSP URI; Nginx `ssl_stapling on` would log warnings on every renewal.

- `_cert_supports_ocsp()` reads cert's Authority Information Access via `openssl x509 -ocsp_uri` (ground truth)
- No OCSP URI → auto-disable stapling
- Non-LE CA (ZeroSSL / etc.) → auto-enable
- CLI: `--ocsp-stapling` / `--no-ocsp-stapling` for explicit override

### 🧪 本地测试模式 `--local-test`

无公网/无 DNS 环境用 2048-bit RSA 自签证书快速验证部署链路（`subjectAltName=DNS:<domain>,DNS:www.<domain>`，7 天有效期）。~15 处模式隔离守卫确保不污染生产证书路径、不触发 certbot、不调用 Let's Encrypt。覆盖 `deploy` / `enable-ssl` / `status`。

Fast deployment validation with 2048-bit RSA self-signed cert when no public DNS (`subjectAltName=DNS:<domain>,DNS:www.<domain>`, 7-day validity). ~15 mode-isolation guards prevent contamination of production cert paths, never trigger certbot or Let's Encrypt. Covers `deploy` / `enable-ssl` / `status`.

### 🇨🇳 国产 EL 系完整支持

**openEuler 24.03 LTS SP3 / 银河麒麟 V11 / UOS / Anolis / OpenCloudOS**。`_el_ids` 扩充 `openeuler` / `kylin`，ID 识别支持大小写。`_is_openeuler_like()` 辅助函数 + 4 处外部仓库守卫（Remi / nginx.org / MariaDB.org / Valkey.io 跳过添加，使用发行版自带 nginx 1.24 / PHP 8.2 等）。

**LoongArch64 / RISC-V / ppc64le 多架构**：用 `platform.machine()` 动态补当前架构的 multiarch 目录。

---

**openEuler 24.03 LTS SP3 / Kylin V11 / UOS / Anolis / OpenCloudOS**. `_el_ids` expanded with `openeuler` / `kylin`, case-insensitive ID matching. `_is_openeuler_like()` helper + 4 external-repo guards (Remi / nginx.org / MariaDB.org / Valkey.io skipped, use distro-bundled nginx 1.24 / PHP 8.2 etc.).

**LoongArch64 / RISC-V / ppc64le multi-arch**: `platform.machine()` dynamically fills current arch's multiarch dir.

## 其他主要改进 / Other Major Improvements

### 🐛 Bug 修复亮点 / Bug fix highlights

- **PHP-FPM SIGSEGV 真 bug 修复**（v3.2.352, 356）— openEuler/EL 低默认 LimitNOFILE 触发 `setrlimit(RLIMIT_NOFILE, 65535)=EPERM` 导致全站 502；systemd drop-in + 条件守卫，成熟平台零变动
- **MariaDB 客户端/服务器版本不匹配修复** — 10.11 → 11.8 升级过程中 client 与 server 可能短暂错版本
- **MariaDB 11.x 弃用参数清理**（v3.2.320）— `innodb_file_per_table` / `innodb_buffer_pool_instances` 按版本条件生成 + 升级后清理
- **Redis `timeout 300` 绕过 CONFIG REWRITE**（v3.2.352, 358）— openEuler `/etc/redis/redis.conf` 0640 权限下 CONFIG REWRITE 静默失败；直接写 conf + 幂等守卫
- **nginx 1.30 指令运行时 probe**（v3.2.350, 355）— `max_headers` / `add_header_inherit` 按精确版本门条件生成
- **Debian 12 nftables 加规则幂等**（v3.2.342）— 生产日志发现非幂等，先 `nft list` 探测再 add

---

- **PHP-FPM SIGSEGV real-bug fix** (v3.2.352, 356) — openEuler/EL low default LimitNOFILE → full-site 502; systemd drop-in + conditional guard, zero changes on healthy platforms
- **MariaDB client/server version mismatch fix** — Window during 10.11 → 11.8 upgrade when client and server briefly mismatch
- **MariaDB 11.x deprecated params cleanup** (v3.2.320) — `innodb_file_per_table` / `innodb_buffer_pool_instances` conditionally emitted by version + post-upgrade cleanup
- **Redis `timeout 300` bypasses CONFIG REWRITE** (v3.2.352, 358) — Silent failure under 0640 perm; direct write + idempotency guard
- **nginx 1.30 directive runtime probe** (v3.2.350, 355) — `max_headers` / `add_header_inherit` per precise version gate
- **Debian 12 nftables add rule idempotent** (v3.2.342) — Prod logs found non-idempotent; `nft list` probe first

### 🛡 业务层防护强化 / Business-layer hardening

- **WordPress REST API 速率限制**（v3.2.313）— `/wp-json/wp/v2/{oembed,posts,users}` 限 5r/s + burst 20
- **setup-config.php 扫描器封锁**（v3.2.332）— 防止触发 Redis connect → HTTP 500
- **静态资源 404 白名单**（v3.2.333）— Fail2Ban wordpress-404 过滤器排除合法 404
- **RFC 8615 `/.well-known/` 放行合法子路径**（v3.2.334）— 保留 acme-challenge 同时放 security.txt / change-password / openid-configuration
- **QUIC retry + GSO 硬化**（v3.2.335）— 防 QUIC 源地址伪造 DDoS + ~40% 吞吐

### ⚡ 性能与缓存 / Performance & caching

- **Nginx/MariaDB/PHP/Redis/Certbot 全链路版本探测 + 能力探测缓存**（v3.2.322, 327, 328）— 部署期 subprocess 调用减 **~70%**
- **open_file_cache 默认启用**（v3.2.317）— `max=10000 inactive=60s`
- **TCP Fast Open 运行时检测**（v3.2.318）
- **InnoDB log file size RAM 分层**（v3.2.318）— tiny 64M / small 128M / medium 256M / large 512M
- **opcache interned_strings_buffer 16→32**（v3.2.335）— WP 6.9 + 10+ 插件共识
- **SSD io_capacity 1000/2000**（v3.2.335, 336）— 2026 云 VM 99% SSD

### ☁ 仓库健壮性 / Repo robustness

- **Debian 12 bookworm-backports Valkey 集成**（v3.2.302）
- **Snap 健壮性**（v3.2.306, 307）— squashfs 预检 + 超时 180→420s + connectivity 检测 + pending install 轮询
- **EPEL 国内云兜底**（v3.2.308）
- **apt 缓存刷新对齐**（v3.2.325）
- **apt lock 等待**（`_wait_for_apt_lock`）

### 📦 架构重构 / Architecture refactor

**WPDeployManager god-class 拆分** — V3.2.8 最大的架构改动：`WPDeployManager` 从 **327 方法缩减到 133 方法**（-194，缩减 59%），组件生命周期逻辑全部迁移到各专业 Manager 类，WPDeployManager 保留为轻量级编排层（orchestration only）。

| 目标 Manager | 从 WPDM 迁入 | 真新方法 | 真新亮点 |
|---|---|---|---|
| NginxManager | 80 | 13 | `_detect_nginx_version`、`_ensure_mptcp_nginx_support`、`_install_systemd_rlimit_drop_in`、`_optimize_nginx_main_conf`、`_tune_nginx_worker_connections` |
| CertManager | 28 | 5 | `_snap_install_or_refresh_robust`、`_check_snapcraft_reachable`、`_check_squashfs_available`、`_issue_local_self_signed` |
| PHPManager | 17 | 9 | `_detect_php_fpm_service_uncached`、`_fix_sury_ppa_codename_for_non_lts`、`_print_component_versions`、`php_ini_security_directives` |
| MariaDBManager | 14 | 9 | `_cleanup_mariadb_official_repo`、`_detect_mariadb_full_version`、`_fix_mariadb_client_mismatch`、`_setup_mariadb_repo_el_fallback` |
| RedisManager | 2 | **13**（此 Manager 以真新为主）| Valkey 9.0 升级链：`_upgrade_valkey_bookworm_backports`、`_upgrade_valkey_el`、`_redis_socket_fallback_to_tcp`、`_sock_args`、`detect_full_version`、`detect_service`、`get_data_dir` |

**价值**：单一职责原则（SRP），每个 Manager 只管自己组件的生命周期；WPDeployManager 只做跨组件编排；单测可针对单 Manager 独立进行；未来增删组件局部化。

- **日志收集子工具** (`collect_logs`, `_tail_file`, `_collect_conf`) — 一键打包 nginx/php-fpm/mariadbd/redis 最近日志 + 所有 conf 到 `/tmp/wp_ssl_<domain>_<ts>.tar.gz` 方便支持

---

**WPDeployManager god-class decomposition** — Biggest V3.2.8 architectural change: `WPDeployManager` shrunk from **327 methods to 133** (-194, -59%); component lifecycle logic migrated to specialized Managers, WPDeployManager kept as thin orchestration layer.

| Target Manager | Migrated from WPDM | Truly new | New highlights |
|---|---|---|---|
| NginxManager | 80 | 13 | `_detect_nginx_version`, `_ensure_mptcp_nginx_support`, `_install_systemd_rlimit_drop_in`, `_optimize_nginx_main_conf`, `_tune_nginx_worker_connections` |
| CertManager | 28 | 5 | `_snap_install_or_refresh_robust`, `_check_snapcraft_reachable`, `_check_squashfs_available`, `_issue_local_self_signed` |
| PHPManager | 17 | 9 | `_detect_php_fpm_service_uncached`, `_fix_sury_ppa_codename_for_non_lts`, `_print_component_versions`, `php_ini_security_directives` |
| MariaDBManager | 14 | 9 | `_cleanup_mariadb_official_repo`, `_detect_mariadb_full_version`, `_fix_mariadb_client_mismatch`, `_setup_mariadb_repo_el_fallback` |
| RedisManager | 2 | **13** (mostly truly new) | Valkey 9.0 upgrade chain: `_upgrade_valkey_bookworm_backports`, `_upgrade_valkey_el`, `_redis_socket_fallback_to_tcp`, `_sock_args`, `detect_full_version`, `detect_service`, `get_data_dir` |

**Value**: Single Responsibility Principle (SRP); each Manager owns its component's lifecycle; WPDeployManager orchestrates only; unit tests target single Managers; future component add/remove is localized.

- **Log collection helper** (`collect_logs`, `_tail_file`, `_collect_conf`) — One-shot bundles recent nginx/php-fpm/mariadbd/redis logs + all confs to `/tmp/wp_ssl_<domain>_<ts>.tar.gz` for support

---

### 🧹 架构规则清洁冲刺（build 3.2.359-365）/ Architecture rule compliance push

V3.2.8 后半段（build 359-365，**2026-04 多轮迭代完成**）做了最终的架构硬化, 把 WPDeployManager god-class 的残余违规清理到零。**用户可见行为无变化**, 但脚本长期可维护性和未来重构安全性显著提升。

V3.2.7 → V3.2.8 build 365 最终状态:
- WPDM god-class: 327 → **108** 方法（-67%）
- Manager 总方法: 75 → **242**（+223%）
- **11 个 Manager 公开 API**: `NginxManager.{get_conf_path, get_conf_d_dir, get_site_conf_path, validate_config, validate_config_file, graceful_shutdown, get_module_conf_dirs}` / `RedisManager.{get_conf_path, get_candidate_conf_paths}` / `MariaDBManager.verify_user_connection`
- WPDM Path 硬编码: ~40 → **0**（-100%）
- WPDM subprocess 真违规: 多处 → **0**（保留 4 处带注释的诊断例外）
- 信号检查调用点: 23 → **77**（+235%），覆盖率 **8.8% → 32.6%**
- 14 条内部架构规则: 🟡 混合 → **14/14 🟢 全绿**
- 静态测试: 436 → **466**（+30 项契约断言防未来重构回归）

**v3.2.365 HOTFIX 说明**: build 364 批量迁移脚本误把 `self.nginx.get_conf_d_dir()` 放入 4 个模块级函数（`_detect_existing_sites` / `_cleanup_ghost_sites` / `_detect_site_config` ×2）, 导致启动 NameError。Build 365 全部回退为硬编码 Path（模块级函数本就无 Manager 可用）+ 新增防回归断言 `v3_2_365_no_self_in_module_funcs`。**生产环境请跳过 build 359-364**, 直接用 build 358 或 build 365+。

---

**Architecture rule compliance push (build 3.2.359-365)**

V3.2.8's later stage (builds 359-365, **multiple April 2026 sessions**) finalized architectural hardening by eliminating remaining WPDeployManager god-class violations. **No user-visible behavior change**, but significantly improves long-term maintainability and refactor safety.

V3.2.7 → V3.2.8 build 365 final state:
- WPDM god-class: 327 → **108** methods (-67%)
- Manager total: 75 → **242** (+223%)
- **11 Manager public APIs**: `NginxManager.{get_conf_path, get_conf_d_dir, get_site_conf_path, validate_config, validate_config_file, graceful_shutdown, get_module_conf_dirs}` / `RedisManager.{get_conf_path, get_candidate_conf_paths}` / `MariaDBManager.verify_user_connection`
- WPDM Path hardcodes: ~40 → **0** (-100%)
- WPDM subprocess real violations: many → **0** (4 documented diagnostic exceptions preserved)
- Signal check sites: 23 → **77** (+235%), coverage **8.8% → 32.6%**
- 14 internal architecture rules: 🟡 mixed → **14/14 🟢 all green**
- Static tests: 436 → **466** (+30 contract assertions against future refactor regression)

**v3.2.365 HOTFIX note**: build 364 batch migration script incorrectly placed `self.nginx.get_conf_d_dir()` into 4 module-level functions (`_detect_existing_sites` / `_cleanup_ghost_sites` / `_detect_site_config` ×2), causing startup NameError. Build 365 reverts all to hardcoded Path (module-level functions have no Manager available) + new regression-prevention assertion `v3_2_365_no_self_in_module_funcs`. **Production should skip builds 359-364**; use build 358 or 365+.

## 兼容性矩阵 / Compatibility Matrix

| 平台 / Platform | 实测 / Tested | 脚本行为 / Script Behavior |
|---|---|---|
| AlmaLinux 10.1 | ✅ toksun.cn prod（update v240→v358 字节级零配置变化，除主动升级的 nginx/PHP/MariaDB 包外）| nginx.org EL10 + Remi PHP 8.5 + valkey 9.0 |
| Rocky 9.7 | ✅ 2 次 prod | nginx.org EL9 + Remi PHP 8.5 + valkey |
| Ubuntu 24.04 LTS | ✅ prod | nginx.org noble + Sury noble PHP 8.5 + valkey |
| Ubuntu 22.04 LTS | ✅ prod | nginx.org jammy + Sury jammy + VID 兜底 redis |
| Debian 12 (bookworm) | ✅ prod | nginx.org bookworm + Sury noble + backports Valkey 8.0 |
| Debian 13 (trixie) | ⚠ 代码就绪（trixie 2025-08 GA）| nginx.org trixie + Sury noble + valkey |
| Ubuntu 26.04 LTS (resolute) | ⚠ 代码就绪（2026-04-23 GA）| HTTP 探测 → questing 回退 + Sury noble 改写 |
| openEuler 24.03 LTS SP3 | ⚠ 代码就绪（`--local-test` 验证通过）| distro nginx 1.24 + probe 跳过新指令 |
| 银河麒麟 V11 | ⚠ 代码就绪 | 同 openEuler EL 路径 |

## 升级指南 / Upgrade Guide

```bash
# 从 V3.2.7 (build 287+) 升级
# From V3.2.7 (build 287+)

cp wp_ssl_bootstrap.py wp_ssl_bootstrap.py.bak327
# 下载 V3.2.8 新版覆盖 / Download V3.2.8 and overwrite

# 选项 1: 自更新 / Option 1: Self-update
python3 wp_ssl_bootstrap.py self-update

# 选项 2: 手动 update 触发所有新探测 + 组件升级 / Manual update
python3 wp_ssl_bootstrap.py update --domain YOUR_DOMAIN --email YOUR_EMAIL

# 选项 3: 启用新功能 / Enable new features
# TLS ECH with Cloudflare:
python3 wp_ssl_bootstrap.py update --domain YOUR_DOMAIN --ech --cf-api-token CF_TOKEN

# MPTCP:
python3 wp_ssl_bootstrap.py update --domain YOUR_DOMAIN --mptcp
```

**预期变化 / Expected changes** (AlmaLinux 10.1 toksun.cn prod 实测参考 / based on toksun.cn prod measurements):
- **nginx 从 1.28.x 升级到 1.30.x**（主动升级，生产验证链路：`nginx -t` → graceful reload → 验证）/ **nginx upgrades from 1.28.x to 1.30.x** (active upgrade, verified via `nginx -t` → graceful reload → verify)
- **PHP 从 8.4.x 升级到 8.5.x**（不中断 php-fpm 服务，迁移自定义 `php.ini` 设置）/ **PHP upgrades from 8.4.x to 8.5.x** (non-disruptive php-fpm migration, custom `php.ini` settings preserved)
- **MariaDB 从 10.11.x 升级到 11.8.x**（跨版本升级，`mariadb-upgrade` 自动运行处理系统表）/ **MariaDB upgrades from 10.11.x to 11.8.x** (cross-version upgrade, `mariadb-upgrade` handles system tables automatically)
- **Valkey 自动升级到 9.0**（如可用；EL8+ 走 Remi 模块流，Debian 12 走 backports，Ubuntu 24.04+ 走主仓库）/ **Valkey auto-upgrades to 9.0** (if available; EL8+ via Remi, Debian 12 via backports, Ubuntu 24.04+ via main)
- 零 systemd drop-in 新建（systemd 默认 LimitNOFILE=524288 ≥ 65536）/ Zero new systemd drop-ins (systemd default ≥ 65536)
- Nginx/PHP/MariaDB 配置文件**字节级零变化**（除版本升级自带的 conf 默认）/ Nginx/PHP/MariaDB conf files byte-level unchanged (except defaults shipped with upgraded packages)

## 测试覆盖 / Test Coverage

- 静态检查 / Static assertions: **466 项 / items** (v3.2.364 新增 24 项架构契约测试 + v3.2.365 新增 1 项 HOTFIX 回归防御 / v3.2.364 added 24 architecture contract tests + v3.2.365 added 1 HOTFIX regression guard)
- 回归模拟 / Regression simulations: **18/18** 全捕获 / caught
- 实测平台 / Prod validations: AlmaLinux 10.1（字节级 diff 两次验证 + 全栈升级）+ 跨平台静态验证
- 边界 case 审计 / Edge-case audit: systemctl show --value 异常值 × 7 + nginx -v 解析 × 6 + redis timeout regex × 7

## 🛡 四层独立审计 / 4-Layer Independent Audit (Build 3.2.365)

V3.2.8 final 在 build 3.2.365 通过**四层独立验证**确认零架构违规：  
V3.2.8 final passed **four independent verification layers** at build 3.2.365 with zero architecture violations:

| 层 / Layer | 工具 / Tool | 检查项 / Checks | 结果 / Result |
|-----|------|------|------|
| 1 | `test_integration.py` 契约测试 / contract tests | 466 | ✅ **466/466** |
| 2 | `full_verify_v2.py` 结构完整性 / structural integrity | 21 | ✅ **21/21** |
| 3 | `verify_refactor_v3.py` 方向感知迁移 / direction-aware migration | 54 | ✅ **54/54** |
| 4 | 14 条架构规则深度审计 / 14-rule deep audit | — | ✅ **14/14 🟢** |
| **总计 / Total** | — | **541+** | **100%** |

独立深度审计 10 处 `os.chmod` 误报全部判定合规（1 误报 + 2 atomic_write tmp / 5 letsencrypt archive / 2 self-update, 全部合规场景）。  
Deep audit's 10 flagged `os.chmod` sites all verified compliant (1 docstring false positive + 2 atomic_write tmp file + 5 letsencrypt archive + 2 self-update — all legitimate patterns).

## 🚀 生产性能验证 / Production Performance Validation

V3.2.365 实测 WordPress `admin-ajax.php`（最吃性能的 endpoint，走完整 WP bootstrap + DB 查询）：  
V3.2.365 measured `admin-ajax.php` (heaviest endpoint — full WP bootstrap + DB queries):

| 指标 / Metric | 实测 / Measured | 评级 / Rating |
|-----|------|------|
| **TTFB** (服务器响应 / server response) | **73.78 ms** | ✅ 优秀 / Excellent (50-100ms 区间) |
| 连接复用 / Connection reuse | 10.58 ms | ✅ 正常 / Normal (keep-alive) |
| 内容下载 / Content download | 0.74 ms | ✅ 极低 / Minimal |
| 端到端总计 / End-to-end total | **88.00 ms** | ✅ 生产就绪 / Production-ready |

这个结果验证了 V3.2.8 的性能承诺：OPcache JIT + Redis 对象缓存 + MariaDB 调优 + PHP-FPM pool 自动 sizing 全部按预期生效。  
This validates V3.2.8's performance promise: OPcache JIT + Redis object cache + MariaDB tuning + auto-sized PHP-FPM pool all working as designed.

## 已知限制 / Known Limitations

- **Ubuntu 26.04 LTS** 正式发布 2026-04-23；nginx.org 与 Sury 同步通常滞后 1-3 个月。生产部署推荐 **26.04.1** 点版本（2026-08）后 / GA 2026-04-23; nginx.org/Sury typically lag 1-3 months. Production recommended after **26.04.1** point release (2026-08)
- **openEuler/Kylin** 暂无 nginx.org/Remi 仓库支持；脚本使用发行版自带 nginx（1.24）+ PHP（8.2）。`--local-test` 验证通过但未上过真实流量站点 / No nginx.org/Remi support; uses distro nginx 1.24 + PHP 8.2. `--local-test` passed but no real traffic yet
- **ECH 依赖 OpenSSL 4.0+**（截至 2026-04 仍是 RC 阶段）；实际可用场景：Debian sid、Arch、自编译 OpenSSL 4.0。OpenSSL 3.x 运行时 `_detect_ech_support()` 返回 False，跳过 ECH / ECH requires OpenSSL 4.0+ (RC as of 2026-04); practical: Debian sid, Arch, self-built. OpenSSL 3.x: `_detect_ech_support()` returns False, ECH skipped
- **MPTCP 依赖 Linux kernel ≥ 5.6**（MPTCP v1 merged）；建议 ≥ 6.0 以获得稳定性。内核不支持时 `_detect_mptcp_support()` 返回 False / MPTCP needs Linux ≥ 5.6; ≥ 6.0 recommended. Kernel unsupported → `_detect_mptcp_support()` returns False
- **通配符证书** 不支持（仅 webroot HTTP-01 验证；DNS-01 API 仅用于 ECH HTTPS 记录发布）/ Wildcard certs not supported (webroot HTTP-01 only; DNS-01 APIs used only for ECH HTTPS record publish)

## 兼容性 / Compatibility

- Python 3.6+ (EL7/EL8) ~ 3.13+ (Debian 13 / Ubuntu 26.04)
- 无新增外部依赖 / No new external dependencies
- 向后兼容 V3.2.7 配置文件与凭据 / Backward-compatible with V3.2.7 configs and credentials
- 现有 V3.2.7 prod 站点 `update` 后配置文件字节级不变（除主动升级的 nginx/PHP/MariaDB 软件包外）/ Existing V3.2.7 prod sites: byte-level unchanged configs after `update` (excluding actively-upgraded packages)
