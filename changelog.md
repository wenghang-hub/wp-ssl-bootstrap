# Changelog / 变更日志

All notable changes to WP-SSL-Bootstrap are documented in this file.
本文件记录 WP-SSL-Bootstrap 的所有重要变更。
---

## [V3.2.8]

> **升级说明 / Upgrade note**
> V3.2.8 是 **全栈主要组件升级** + **TLS ECH 隐私增强** + **MPTCP 多路径传输** + **国产系统兼容** + **架构规则 100% 清洁** 版本。
> Build 从 V3.2.7 的 `287` 累计到 `365`（+7,500+ 代码行 / +49 真·新方法，另有 219 个从 WPDeployManager god-class 迁移到各专业 Manager / +11 Manager 公开 API / +10 新 CLI 参数）。
>
> **组件升级 (配置目标版本)**：
> - **nginx 1.28 → 1.30**（HTTP/2 upstream / Early Hints / ECH / keepalive 默认启用 / `max_headers` / `add_header_inherit` / `quic_retry` / `quic_gso`）
> - **PHP 8.4 → 8.5**（2025-11 GA，active support 至 2027-12；新 URI 扩展 / pipe operator `|>` / `#[\NoDiscard]`）
> - **MariaDB 10.11 → 11.8 LTS**（2025-05 GA；**Vector Search** 内建 / JSON_TABLE / 性能增强）
> - **Valkey 新目标 9.0**（BSD 3-Clause 开源许可 / 40% 吞吐提升 / 原子 slot 迁移）
>
> **TLS 隐私增强**：TLS **ECH (Encrypted ClientHello)** 全自动配置链（OpenSSL 4.0+ 检测 → 密钥对生成 → Cloudflare/Route53/阿里云 DNS/DNSPod 四家 API 自动发布 HTTPS 记录 → systemd timer 密钥轮换）。ECH 隐藏 SNI 不被 ISP/中间盒看到，防止被动流量分析和 SNI 过滤。
>
> **传输层增强**：**MPTCP (Multipath TCP)** 运行时内核探测 + sysctl 自动启用 + Nginx listen 带 `mptcp` 选项，多 NIC / 手机蜂窝+Wi-Fi 用户获得断流自愈 + 多径带宽合并。
>
> **OCSP stapling 智能化**：自动探测证书是否含 OCSP responder（`openssl x509 -ocsp_uri`），Let's Encrypt 2025 年起停发 OCSP responder → 自动关闭 stapling；非 LE CA → 自动启用。`--ocsp-stapling` / `--no-ocsp-stapling` 可强制覆盖。
>
> **部署体验**：`--local-test` 自签证书本地测试模式；国产 EL（openEuler 24.03 / 银河麒麟 V11）完整支持；Ubuntu 26.04 LTS HTTP 探测回退预备。
>
> 全部通过 `update` 子命令幂等生效。**V3.2.7 已部署站点升级后预期配置文件字节级零变化**（AlmaLinux 10.1 toksun.cn prod 实测验证，除主动升级的 nginx/PHP/MariaDB 软件包外）。
>
> ---
>
> V3.2.8 is a **full-stack major component upgrade** + **TLS ECH privacy enhancement** + **MPTCP multi-path transport** + **domestic EL support** + **100% architecture rule clean** release.
> Build `287` → `365` (+7,500+ code lines / +49 truly new methods, plus 219 migrated from WPDeployManager god-class to specialized Managers / +11 Manager public APIs / +10 new CLI flags).
>
> **Component upgrades (configured target versions)**:
> - **nginx 1.28 → 1.30** (HTTP/2 upstream / Early Hints / ECH / keepalive default / `max_headers` / `add_header_inherit` / `quic_retry` / `quic_gso`)
> - **PHP 8.4 → 8.5** (GA 2025-11, active support until 2027-12; new URI extension / pipe operator `|>` / `#[\NoDiscard]`)
> - **MariaDB 10.11 → 11.8 LTS** (GA 2025-05; **Vector Search** built-in / JSON_TABLE / performance improvements)
> - **Valkey new target 9.0** (BSD 3-Clause / 40% throughput / atomic slot migration)
>
> **TLS privacy**: TLS **ECH (Encrypted ClientHello)** fully-automated pipeline (OpenSSL 4.0+ detect → keypair generation → auto-publish HTTPS record via Cloudflare / Route53 / Aliyun DNS / DNSPod APIs → systemd timer key rotation). ECH hides SNI from ISPs/middleboxes, defeating passive traffic analysis and SNI filtering.
>
> **Transport enhancement**: **MPTCP (Multipath TCP)** runtime kernel probe + sysctl auto-enable + Nginx listen with `mptcp` option; multi-NIC / mobile cellular+Wi-Fi users gain break resilience + multi-path bandwidth aggregation.
>
> **OCSP stapling intelligence**: auto-probes certificate OCSP responder (`openssl x509 -ocsp_uri`); Let's Encrypt deprecated OCSP 2025 → auto-disable stapling; non-LE CAs → auto-enable. `--ocsp-stapling` / `--no-ocsp-stapling` force override.
>
> **Deployment experience**: `--local-test` self-signed local test mode; full domestic EL support (openEuler 24.03 / Kylin V11); Ubuntu 26.04 LTS HTTP probe fallback.
>
> All apply idempotently via `update`. **Existing V3.2.7 production sites: byte-level zero config change after upgrade** (AlmaLinux 10.1 toksun.cn prod measured; excluding actively-upgraded nginx/PHP/MariaDB packages).

---

### ✅ 最终发布审计 (Build 3.2.365 签字) / Final Release Audit

Build 3.2.365 通过 **四层独立验证**，541+ 项检查 **100% 通过**，确认零架构违规：  
Build 3.2.365 passed **four-layer independent verification**, 541+ checks **100% passing**, confirming zero architecture violations:

| 层 / Layer | 工具 / Tool | 检查项 / Checks | 结果 |
|-----|------|------|-----|
| 1 | `test_integration.py` 契约测试 | 466 | ✅ 466/466 |
| 2 | `full_verify_v2.py` 结构完整性 | 21 | ✅ 21/21 |
| 3 | `verify_refactor_v3.py` 方向感知迁移 | 54 | ✅ 54/54 |
| 4 | 14 架构规则深度审计 | 14 | ✅ 14/14 🟢 |

**生产性能实测 / Production performance**: WordPress `admin-ajax.php`（最重的 endpoint）TTFB 73.78 ms / 端到端 88.00 ms，落在"优秀"区间（50-100 ms）。验证 OPcache JIT + Redis 对象缓存 + MariaDB InnoDB 调优 + PHP-FPM pool auto-sizing 协同工作达到设计目标。  
WordPress `admin-ajax.php` (heaviest endpoint): TTFB 73.78 ms / end-to-end 88.00 ms — "Excellent" tier (50-100 ms). Validates OPcache JIT + Redis object cache + MariaDB InnoDB tuning + auto-sized PHP-FPM pool meeting design performance goals.

---

### 🏗 架构规则清洁冲刺 (Build 3.2.359-365) / Architecture rule compliance push

V3.2.8 后半段（build 359-365，2026-04）对 WPDeployManager god-class 的剩余架构违规做了最终清理, 使 **14 条内部架构规则全部达成 🟢 绿色合规**。这是多轮会话迭代完成的架构硬化工作, 不改变用户可见行为, 但显著提升了脚本的长期可维护性和重构安全性。

**关键里程碑**：

1. **规则 1/2 — WPDeployManager 纯编排** *(build 359-362)*  
   新增 11 个 Manager 公开 API: `NginxManager.{get_conf_path,get_conf_d_dir,get_site_conf_path,validate_config,validate_config_file,graceful_shutdown,get_module_conf_dirs}` / `RedisManager.{get_conf_path,get_candidate_conf_paths}` / `MariaDBManager.verify_user_connection` / 修复 ECH keypair `os.chmod` 走 `_safe_chmod`。WPDM 内 `Path("/etc/{nginx,redis,valkey}/...")` 硬编码从 ~40 处降到 **0** (-100%); `subprocess.run(["nginx|mysql|..."])` 真违规从多处降到 **0** (4 处带注释的诊断例外 - 捕获 stderr/stdout 用于错误分析, `validate_config()` 返 bool 无法替代)。  

2. **规则 7 — 信号检查覆盖率 3.6× 提升** *(build 364)*  
   WPDeployManager `__init__` 末尾新增 `# INJECTION BLOCK` 标记注释的跨组件注入块, 向 5 个 Manager 注入 `self._abort_if_shutdown` 引用。批量在 55 个含 `timeout ≥ 60s` 长操作的 Manager 方法入口加信号检查点（NginxManager 22 + MariaDBManager 11 + PHPManager 10 + CertManager 9 + RedisManager 3）。总 `_abort_if_shutdown()` 调用点从 23 → **77** (+235%), 长操作覆盖率 **8.8% → 32.6%**（超 30% 目标）。Ctrl-C / SIGTERM 响应性大幅改善, 部署中途取消时能在下一个方法入口处理, 避免等待长超时。  

3. **契约测试防回归** *(build 364)*  
   `test_integration.py` 新增 **24 项 v3.2.364 静态断言**（466/466 通过）, 锁定以下不变量防止未来重构误破坏：  
   - 11 个 Manager 公开 API 必须存在 (7 Nginx + 2 Redis + 1 MariaDB + 1 防回归)  
   - WPDM 规则 1/2 清洁 (Path 硬编码 0, subprocess 真违规 0)  
   - 5 个 Manager 都有 `_abort_if_shutdown` 注入 (`INJECTION BLOCK` 标记存在)  
   - 所有 5 个 Manager `__init__` 包含 `run_cmd` 参数 (A6 陷阱: Manager 禁止循环依赖导入 WPDM)  
   - 信号检查覆盖率 ≥ 60 个调用点 (防批量误删)  

4. **v3.2.365 HOTFIX — 4 处模块级函数 NameError 修复** *(build 365, 关键稳定性修复)*  
   Build 364 的批量 Path 硬编码迁移脚本错误地把 `self.nginx.get_conf_d_dir()` 替换放入了 4 个 **模块级函数** (`_detect_existing_sites`, `_cleanup_ghost_sites`, `_detect_site_config` ×2), 导致 `python wp_ssl_bootstrap.py` 启动时立即 `NameError: name 'self' is not defined`。Build 365 全部回退为 `Path("/etc/nginx/conf.d/...")` 硬编码（模块级函数本就无 Manager 实例可用）, 修复同时发现 L48137 原代码的算符优先级 bug（`self.nginx.get_conf_d_dir() / "cloudflare-real-ip.conf".exists()` 等价于 `.exists()` 作用于字符串, AttributeError）。新增 `v3_2_365_no_self_in_module_funcs` 断言防未来同类 bug。**所有 V3.2.8 生产环境必须升级到 build 365+ 或保持在 build 358**（不要停留在 359-364）。  

**架构指标 (V3.2.7 → V3.2.8 build 365)**：

| 指标 | V3.2.7 | V3.2.8 最终 | 变化 |
|---|---|---|---|
| WPDM god-class 方法数 | 327 | **108** | -219 (-67%) |
| Manager 总方法数 | 75 | **242** | +167 (+223%) |
| Manager 公开 API | 0 | **11** | +11 |
| WPDM Path 硬编码 | ~40 | **0** | -100% |
| WPDM subprocess 真违规 | 多处 | **0** | -100% |
| 信号检查调用点 | 23 | **77** | +235% |
| 信号检查覆盖率 | 8.8% | **32.6%** | 3.7× |
| 架构规则清洁度 | 🟡 混合 | **14/14 🟢** | 全绿 |
| 静态测试项数 | 436 | **466** | +30 |
| 跨组件注入 | 分散 | **31 统一** | INJECTION BLOCK 模式 |

---

**Architecture rule compliance push (Build 3.2.359-365)**

The later half of V3.2.8 (builds 359-365, April 2026) finalized the cleanup of remaining architecture rule violations in WPDeployManager god-class, achieving **all 14 internal architecture rules 🟢 green**. This is multi-session architectural hardening work that does not change user-visible behavior but significantly improves long-term maintainability and refactor safety.

**Key milestones**:

1. **Rules 1/2 — WPDeployManager pure orchestration** *(builds 359-362)*  
   Added 11 new Manager public APIs. `Path("/etc/{nginx,redis,valkey}/...")` hardcoded in WPDM dropped from ~40 → **0** (-100%); `subprocess.run(["nginx|mysql|..."])` real violations dropped to **0** (4 documented diagnostic exceptions — stderr/stdout capture for error analysis where `validate_config()` returning bool is insufficient).  

2. **Rule 7 — Signal check coverage 3.6× up** *(build 364)*  
   New `# INJECTION BLOCK`-tagged cross-component injection block at end of WPDeployManager `__init__` injects `self._abort_if_shutdown` reference into all 5 Managers. Batch-added signal check points at entry of 55 Manager methods with `timeout ≥ 60s` long operations. Total `_abort_if_shutdown()` call sites went from 23 → **77** (+235%); long-op coverage **8.8% → 32.6%** (exceeds 30% target). Ctrl-C / SIGTERM responsiveness greatly improved.  

3. **Contract tests against regression** *(build 364)*  
   `test_integration.py` gained **24 new static assertions** (466/466 pass), locking down invariants to prevent future refactor breakage — Manager public API existence, WPDM rule 1/2 cleanliness, `_abort_if_shutdown` injection in all 5 Managers, `INJECTION BLOCK` marker presence (A2 trap defense), all 5 Manager `__init__` have `run_cmd` param (A6 trap: no circular WPDM import), signal coverage ≥ 60 call sites.  

4. **v3.2.365 HOTFIX — 4 module-level NameError fixes** *(build 365, critical stability fix)*  
   Build 364's batch Path migration script incorrectly placed `self.nginx.get_conf_d_dir()` replacements into 4 **module-level functions** (`_detect_existing_sites`, `_cleanup_ghost_sites`, `_detect_site_config` ×2), causing `python wp_ssl_bootstrap.py` to `NameError: name 'self' is not defined` immediately on startup. Build 365 reverts all to `Path("/etc/nginx/conf.d/...")` hardcodes (module-level functions have no Manager instance available). Fix also caught a preexisting operator-precedence bug at L48137. New `v3_2_365_no_self_in_module_funcs` assertion prevents the class of bug. **All V3.2.8 production must upgrade to build 365+ or stay at build 358** (do not linger in 359-364).  

**Architecture metrics (V3.2.7 → V3.2.8 build 365)**:

| Metric | V3.2.7 | V3.2.8 final | Change |
|---|---|---|---|
| WPDM god-class methods | 327 | **108** | -219 (-67%) |
| Manager total methods | 75 | **242** | +167 (+223%) |
| Manager public APIs | 0 | **11** | +11 |
| WPDM Path hardcodes | ~40 | **0** | -100% |
| WPDM subprocess real violations | many | **0** | -100% |
| Signal check call sites | 23 | **77** | +235% |
| Signal check coverage | 8.8% | **32.6%** | 3.7× |
| Architecture rule cleanliness | 🟡 mixed | **14/14 🟢** | all green |
| Static test count | 436 | **466** | +30 |
| Cross-component injection | scattered | **31 unified** | INJECTION BLOCK pattern |

---

### ✨ 新功能 / New Features

- **TLS ECH (Encrypted ClientHello) 全自动配置链 (v3.2.x, nginx 1.30+OpenSSL 4.0)** — RFC 9849 最新隐私协议，把 ClientHello 里的 SNI 加密传输。端到端流程：(1) `_detect_ech_support()` 检测 OpenSSL ≥ 4.0 含 ECH 子命令 + Nginx 1.30 `ssl_ech_file` 支持；(2) `_generate_ech_keypair()` 生成 ECH 密钥对（OpenSSL 原生）；(3) `_extract_ech_config_base64()` 提取 ECHConfig 公钥 → Base64；(4) 自动通过 4 家 DNS API 写 HTTPS 记录（`_cf_upsert_https_record` / `_r53_upsert_https_record` / `_alidns_upsert_https_record` / `_dnspod_upsert_https_record`），无 API token 则打印记录给用户手动添加；(5) `_verify_ech_dns()` 验证 DNS 已全球生效；(6) `_install_ech_rotation_timer()` 安装 systemd timer 自动轮换密钥。CLI：`--ech` 启用，`--cf-api-token` / Route53 EAB-like（`--change-batch` / `--dns-name` / `--hosted-zone-id`）传 API 凭据。**ECH 防止 ISP/防火墙通过 SNI 识别目标站点**，对跨境站点和隐私敏感场景显著。
  **TLS ECH (Encrypted ClientHello) fully-automated pipeline (nginx 1.30 + OpenSSL 4.0)** — RFC 9849 latest privacy protocol, encrypts SNI in ClientHello. End-to-end: (1) `_detect_ech_support()` probes OpenSSL ≥ 4.0 with ECH subcommand + Nginx 1.30 `ssl_ech_file`; (2) `_generate_ech_keypair()` generates ECH keypair (OpenSSL native); (3) `_extract_ech_config_base64()` extracts ECHConfig public key → Base64; (4) auto-publishes HTTPS record via 4 DNS APIs (`_cf_upsert_https_record` / `_r53_upsert_https_record` / `_alidns_upsert_https_record` / `_dnspod_upsert_https_record`); no API token → prints record for manual add; (5) `_verify_ech_dns()` verifies DNS global propagation; (6) `_install_ech_rotation_timer()` installs systemd timer for auto key rotation. CLI: `--ech` to enable, `--cf-api-token` / Route53 (`--change-batch` / `--dns-name` / `--hosted-zone-id`) for credentials. **ECH prevents ISP/firewall SNI-based site identification** — significant for cross-border sites and privacy-sensitive scenarios.

- **MPTCP (Multipath TCP) 支持 (nginx 1.30)** — `_detect_mptcp_support()` 运行时探测：(1) 内核 `net.mptcp.enabled` sysctl 可用；(2) Nginx 构建含 MPTCP 支持（1.30 上游默认）。`_ensure_mptcp_nginx_support()` 自动 `sysctl -w net.mptcp.enabled=1`。Nginx `listen 443 ssl quic mptcp` 指令启用。CLI：`--mptcp`（强制开启，不支持时降级）、`--no-mptcp`（显式禁用）、不指定（auto-detect）。**多 NIC 服务器、4G/5G+Wi-Fi 移动客户端、跨运营商链路聚合场景自动多径化**，单链路故障无感切换。
  **MPTCP (Multipath TCP) support (nginx 1.30)** — `_detect_mptcp_support()` runtime probes: (1) kernel `net.mptcp.enabled` sysctl available; (2) Nginx built with MPTCP (upstream default in 1.30). `_ensure_mptcp_nginx_support()` auto `sysctl -w net.mptcp.enabled=1`. Nginx `listen 443 ssl quic mptcp` directive enables it. CLI: `--mptcp` (force on, degrades if unsupported), `--no-mptcp` (explicit disable), unspecified (auto-detect). **Multi-NIC servers, 4G/5G+Wi-Fi mobile clients, cross-carrier link aggregation get automatic multi-path**; single-link failure transparent failover.

- **nginx 1.28 → 1.30 主要版本升级 [B296]** — `_NGINX_MIN_VERSION` 从 `(1, 28, 0)` → `(1, 30, 0)`。启用：(1) HTTP/2 upstream（`proxy_http_version 2`，向后端保持 HTTP/2，减少 upstream 连接数和延迟）；(2) Early Hints（`103 Early Hints` 响应，预发资源 hint，LCP 指标改善）；(3) ECH (`ssl_ech_file` 指令，见上)；(4) keepalive 默认启用（Nginx 1.30 upstream keepalive 不再需要显式声明）；(5) `max_headers`（1.29.8+，HTTP 头数量上限防内存耗尽）；(6) `add_header_inherit`（1.29.3+，header 从 server→location 继承）；(7) `quic_retry on`（1.30 默认，防 QUIC 源地址伪造 DDoS）；(8) `quic_gso on`（UDP GSO，~40% 吞吐）。废弃的 `http2_*_timeout` / `http2_*_size` 指令由 `_fix_nginx_post_upgrade_compat` 自动清理。
  **nginx 1.28 → 1.30 major version upgrade [B296]** — `_NGINX_MIN_VERSION` from `(1, 28, 0)` → `(1, 30, 0)`. Unlocks: (1) HTTP/2 upstream (`proxy_http_version 2` to backends, reduces upstream conn count + latency); (2) Early Hints (`103 Early Hints` response, preload resource hints, LCP improvement); (3) ECH (`ssl_ech_file` directive, see above); (4) keepalive default (1.30 upstream keepalive no longer needs explicit declaration); (5) `max_headers` (1.29.8+, HTTP header count cap); (6) `add_header_inherit` (1.29.3+, server→location header inheritance); (7) `quic_retry on` (1.30 default, blocks QUIC source-spoofing DDoS); (8) `quic_gso on` (UDP GSO, ~40% throughput). Deprecated `http2_*_timeout` / `http2_*_size` auto-cleaned by `_fix_nginx_post_upgrade_compat`.

- **PHP 8.4 → 8.5 主要版本升级** — `_PHP_DEFAULT_VERSION = "8.5"`（2025-11 GA，active support 至 2027-12-31，security support 至 2029-12-31）。PHP 8.5 新特性：新 `URI` 扩展（内建 URL/URI 解析，RFC 3986 合规）、pipe operator `|>`（`$data |> trim |> strtoupper`）、`#[\NoDiscard]` attribute、closures/casts/first-class callables 在 constant expression 中合法、命名参数解包。现有 8.3/8.4 站点 `update` 后自动升级（不满足 `_PHP_MIN_VERSION = (8, 3)` 才触发安装）。
  **PHP 8.4 → 8.5 major version upgrade** — `_PHP_DEFAULT_VERSION = "8.5"` (GA 2025-11, active support until 2027-12-31, security until 2029-12-31). New features: URI extension (built-in URL/URI parsing, RFC 3986 compliant), pipe operator `|>` (`$data |> trim |> strtoupper`), `#[\NoDiscard]` attribute, closures/casts/first-class callables in constant expressions, named argument unpacking. Existing 8.3/8.4 sites auto-upgrade on `update` (only triggers when below `_PHP_MIN_VERSION = (8, 3)`).

- **MariaDB 10.11 → 11.8 LTS 主要版本升级** — `_MARIADB_DEFAULT_VERSION = "11.8"`（2025-05 GA，LTS 至 2028-05）。MariaDB 11.8 LTS 核心新特性：**Vector Search** 内建（`VECTOR(N)` 列类型 + cosine/Euclidean 距离函数，用于 AI/ML workload，WordPress 插件可直接用），optimizer 改进（`histogram-based optimizer` 默认启用），InnoDB bulk load 40% 提升，parallel replication 增强。升级是 10.11 → 11.8 跨多版本，脚本自动运行 `mariadb-upgrade` 处理系统表和存储引擎兼容。
  **MariaDB 10.11 → 11.8 LTS major version upgrade** — `_MARIADB_DEFAULT_VERSION = "11.8"` (GA 2025-05, LTS until 2028-05). Key features: **Vector Search** built-in (`VECTOR(N)` column type + cosine/Euclidean distance functions for AI/ML workloads, usable by WordPress plugins), optimizer improvements (`histogram-based optimizer` on by default), InnoDB bulk load +40%, enhanced parallel replication. Cross-version upgrade 10.11 → 11.8 auto-runs `mariadb-upgrade` for system tables + storage engine compatibility.

- **Valkey 9.0 升级目标化** — 新常量 `_VALKEY_TARGET_VERSION = (9, 0)`。Valkey 9.0（BSD 3-Clause 开源许可，2025 年替代 Redis 的首选）40% 吞吐提升，原子 slot 迁移，hash field expiration。EL8+ 经 Remi 模块流升级；Debian 12 经 bookworm-backports；Ubuntu 24.04+ 经主仓库。低于目标版本自动触发 `_upgrade_valkey_if_needed()`。
  **Valkey 9.0 upgrade target** — New constant `_VALKEY_TARGET_VERSION = (9, 0)`. Valkey 9.0 (BSD 3-Clause open-source, 2025 Redis replacement of choice) offers 40% throughput gain, atomic slot migration, hash field expiration. EL8+ via Remi module stream; Debian 12 via bookworm-backports; Ubuntu 24.04+ via main repo. Below target auto-triggers `_upgrade_valkey_if_needed()`.

- **OCSP stapling 智能决策 (`_decide_ocsp_enable` + `_cert_supports_ocsp`)** — 2025 年起 Let's Encrypt 停发 OCSP responder，证书里没有 OCSP URI，此时 Nginx `ssl_stapling on` 会在 error log 每次续期都打 warning。改为：`_cert_supports_ocsp()` 用 `openssl x509 -ocsp_uri` 直接读证书 Authority Information Access 扩展（ground truth）；无 OCSP URI → 自动关闭 stapling；非 LE CA（ZeroSSL / 其他）→ 自动启用。`--ocsp-stapling` / `--no-ocsp-stapling` 用户显式覆盖。
  **OCSP stapling smart decision (`_decide_ocsp_enable` + `_cert_supports_ocsp`)** — Let's Encrypt deprecated OCSP responder in 2025; certificates lack OCSP URI, so Nginx `ssl_stapling on` would print error log warnings on every renewal. Changed: `_cert_supports_ocsp()` uses `openssl x509 -ocsp_uri` to read cert's Authority Information Access extension (ground truth); no OCSP URI → auto-off; non-LE CA (ZeroSSL / etc.) → auto-on. `--ocsp-stapling` / `--no-ocsp-stapling` for explicit override.

- **DNS-01 多 DNS 提供商 API 集成（ECH HTTPS 记录发布用）** — 4 家 DNS 提供商 REST API：(1) **Cloudflare** `_cf_api_request` / `_cf_get_zone_id` / `_cf_upsert_https_record`（v4 API + Bearer token）；(2) **AWS Route53** `_r53_upsert_https_record`（`aws route53 change-resource-record-sets` CLI）；(3) **阿里云 DNS** `_alidns_upsert_https_record`（`DescribeDomainRecords` + `AddDomainRecord`）；(4) **DNSPod（腾讯云）** `_dnspod_api` / `_dnspod_upsert_https_record`（v3 API）。自动根据 DNS NS 记录选择 API；无匹配 API 时打印记录给用户手动加。
  **DNS-01 multi-provider API integration (for ECH HTTPS record publish)** — 4 DNS providers' REST APIs: (1) **Cloudflare** `_cf_api_request` / `_cf_get_zone_id` / `_cf_upsert_https_record` (v4 API + Bearer token); (2) **AWS Route53** `_r53_upsert_https_record` (`aws route53 change-resource-record-sets` CLI); (3) **Aliyun DNS** `_alidns_upsert_https_record` (`DescribeDomainRecords` + `AddDomainRecord`); (4) **DNSPod (Tencent Cloud)** `_dnspod_api` / `_dnspod_upsert_https_record` (v3 API). Auto-selects API based on DNS NS records; no matching API → prints record for manual add.

- **本地测试模式 `--local-test` (v3.2.345-349)** — 无公网/无 DNS 环境下用自签证书快速验证部署链路。覆盖 `deploy` / `enable-ssl` / `status` 三个子命令。新增 `_issue_local_self_signed()` 生成 2048-bit RSA 自签证书（7 天有效期，`subjectAltName=DNS:<domain>,DNS:www.<domain>`）。~15 处模式隔离守卫（`site.local_test`）确保不污染生产证书路径、不触发 certbot、不调用 Let's Encrypt。
  **Local-test mode `--local-test` (v3.2.345-349)** — Fast deployment validation with self-signed cert when no public DNS. Covers `deploy` / `enable-ssl` / `status`. New `_issue_local_self_signed()` generates 2048-bit RSA self-signed cert (7-day validity, `subjectAltName=DNS:<domain>,DNS:www.<domain>`). ~15 mode-isolation guards (`site.local_test`) prevent contamination of production cert paths, never trigger certbot or Let's Encrypt.

- **国产 EL 系完整支持 (v3.2.344, 350-351)** — openEuler 24.03 LTS SP3 / 银河麒麟 V11 / UOS / Anolis / OpenCloudOS。`_el_ids` 扩充 `openeuler` / `kylin`，ID 识别正则 `[A-Za-z_-]+` 支持大小写。新增 `_is_openeuler_like()` 辅助函数 + 4 处外部仓库守卫（Remi / nginx.org / MariaDB.org / Valkey.io 跳过添加，使用发行版自带软件，nginx 1.24 / PHP 8.2 / Redis 6 等）。`--local-test` 已在 openEuler 24.03 验证通过。
  **Full domestic EL-family support (v3.2.344, 350-351)** — openEuler 24.03 LTS SP3 / Kylin V11 / UOS / Anolis / OpenCloudOS. `_el_ids` expanded with `openeuler` / `kylin`, ID regex `[A-Za-z_-]+` supports mixed case. New `_is_openeuler_like()` + 4 external-repo guards (Remi / nginx.org / MariaDB.org / Valkey.io skipped, use distro-bundled: nginx 1.24 / PHP 8.2 / Redis 6 etc.). `--local-test` verified on openEuler 24.03.

- **Ubuntu 26.04 LTS (resolute) 预备 (v3.2.343, 357)** — nginx.org 和 Sury PHP PPA 当前尚未发布 `resolute` codename。脚本通过 HTTP 探测 `dists/resolute/` 返回 404 时自动回退：nginx.org 回退到 `questing`，Sury PPA 改写 sources 为 `noble`（跨 LTS ABI 兼容，Sury 官方文档认可）。Valkey codename 列表保留 `resolute`（Ubuntu 26.04 主仓库确认有 Valkey 9.0.3），MariaDB 早期出口亦保留。等上游同步后零配置切换。
  **Ubuntu 26.04 LTS (resolute) preparation (v3.2.343, 357)** — Neither nginx.org nor Sury PPA has published `resolute` yet. Script HTTP-probes `dists/resolute/` and falls back on 404: nginx.org → `questing`, Sury PPA → sources rewritten to `noble` (cross-LTS ABI-compatible). Valkey codename list retains `resolute` (Ubuntu 26.04 main repo confirmed has Valkey 9.0.3); MariaDB early exit retained.

- **LoongArch64 / RISC-V 多架构支持 (v3.2.344)** — 用 `platform.machine()` 动态补当前架构的 multiarch 目录，不再限死 x86_64/aarch64 两种，覆盖 loongarch64 / riscv64 / ppc64le 等国产/新兴架构。
  **LoongArch64 / RISC-V multi-arch support (v3.2.344)** — `platform.machine()` dynamically fills current arch's multiarch dir, no longer hardcoded; covers loongarch64 / riscv64 / ppc64le.

- **WordPress REST API 速率限制 (v3.2.313)** — 新增独立 rate limit zone，`/wp-json/wp/v2/oembed|posts|users` 限 5r/s + burst 20。合法浏览器调用 ~1/s，对正常访问宽松但拦截爬虫批量枚举。
  **WordPress REST API rate limiting (v3.2.313)** — Dedicated rate limit zone; `/wp-json/wp/v2/oembed|posts|users` limited to 5r/s + burst 20. Legitimate calls ~1/s; blocks scraper enumeration.

- **HTTP/2 Early Hints (nginx 1.30+)** — `103 Early Hints` 响应预发 `<link rel="preload">` 给浏览器提前获取关键资源（CSS/JS/字体）。LCP（Largest Contentful Paint）指标显著改善，Chrome/Safari/Firefox 全支持。
  **HTTP/2 Early Hints (nginx 1.30+)** — `103 Early Hints` response preemptively sends `<link rel="preload">` for critical resources (CSS/JS/fonts). Significantly improves LCP metric; Chrome/Safari/Firefox all support.

- **Debian 12 bookworm-backports Valkey 集成 (v3.2.302)** — Debian 12 主仓库无 Valkey、backports 有 Valkey 8.0。`_detect_debian_bookworm()` + `_enable_bookworm_backports()` 幂等启用 backports。
  **Debian 12 bookworm-backports Valkey integration (v3.2.302)** — Debian 12 main repo lacks Valkey; backports has Valkey 8.0. `_detect_debian_bookworm()` + `_enable_bookworm_backports()` idempotent enable.

---

### 🐛 问题修复 / Bug Fixes

- **PHP-FPM SIGSEGV 真 bug 修复 (v3.2.352, 356)** — 低默认 LimitNOFILE 平台（openEuler 1024 / EL8 4096 / Kylin 1024）触发 php-fpm worker `setrlimit(RLIMIT_NOFILE, 65535)=EPERM`，进程退出状态码 139 (SIGSEGV)，**全站 502**。写入 systemd drop-in `LimitNOFILE=65536` + `daemon-reload` + restart。v3.2.356 条件守卫：`systemctl show <fpm-svc> -p LimitNOFILE --value` 探测，≥ 65536 时直接跳过（AlmaLinux 10 / Rocky 9 / Ubuntu 22/24 / Debian 12/13 的 systemd 默认 524288 或 1048576）。**toksun.cn (AlmaLinux 10.1) 从 v240 update 到 v358 实测字节级零变化**。
  **PHP-FPM SIGSEGV real-bug fix (v3.2.352, 356)** — Low default LimitNOFILE platforms (openEuler 1024 / EL8 4096 / Kylin 1024) trigger php-fpm worker `setrlimit(RLIMIT_NOFILE, 65535)=EPERM`, exit 139 (SIGSEGV), **full-site 502**. Writes systemd drop-in `LimitNOFILE=65536` + `daemon-reload` + restart. v3.2.356 conditional guard: `systemctl show <fpm-svc> -p LimitNOFILE --value` probes, ≥ 65536 skips. **toksun.cn (AlmaLinux 10.1) measured byte-level zero change v240 → v358**.

- **nginx 1.30 指令运行时 probe (v3.2.350, 354, 355)** — `max_headers`（1.29.8+）、`add_header_inherit`（1.29.3+）。`NginxManager._nginx_supports_max_headers()` / `_nginx_supports_add_header_inherit()` 通过 `nginx -v` 按精确版本门条件生成。openEuler 24.03 自带 nginx 1.24 / Ubuntu 22.04 自带 1.18 等旧版本上不会 `nginx -t` 失败。测试脚本同步（v3.2.354 错了版本号，v3.2.355 修正到 CHANGES 准确值）。
  **nginx 1.30 directive runtime probe (v3.2.350, 354, 355)** — `max_headers` (1.29.8+), `add_header_inherit` (1.29.3+). `NginxManager._nginx_supports_max_headers()` / `_nginx_supports_add_header_inherit()` conditionally emit via `nginx -v` precise gate. Never fails on nginx 1.24 (openEuler) / 1.18 (Ubuntu 22.04). Test script aligned (v3.2.354 wrong, v3.2.355 corrected per CHANGES).

- **MariaDB 客户端/服务器版本不匹配修复 (`_fix_mariadb_client_mismatch`)** — 10.11 → 11.8 升级过程中存在窗口：server 已升级但 client 包还是旧版，`mariadb -e '...'` 报 `ER_UNKNOWN_SYSTEM_VARIABLE`。升级链路加入 client 包同步升级 + 验证。
  **MariaDB client/server version mismatch fix (`_fix_mariadb_client_mismatch`)** — 10.11 → 11.8 upgrade has window where server upgraded but client still old, `mariadb -e '...'` reports `ER_UNKNOWN_SYSTEM_VARIABLE`. Added client package sync upgrade + verification to upgrade chain.

- **MariaDB 11.x 弃用参数清理 (v3.2.320, `_fix_mariadb_deprecated_options`)** — `innodb_file_per_table` 11.0+ 弃用（MDEV-29983，10.5+ 默认 ON），`innodb_buffer_pool_instances` 10.5+ 弃用+忽略，10.6+ Enterprise 移除（MDEV-15058），11.x 加了触发 error log warn。按版本条件生成；升级后 `_fix_mariadb_deprecated_options()` 清理现有 conf。
  **MariaDB 11.x deprecated params cleanup (v3.2.320, `_fix_mariadb_deprecated_options`)** — `innodb_file_per_table` deprecated in 11.0+ (MDEV-29983, default ON in 10.5+); `innodb_buffer_pool_instances` deprecated in 10.5+, removed in 10.6+ Enterprise (MDEV-15058). Conditionally emitted by version; post-upgrade `_fix_mariadb_deprecated_options()` cleans existing conf.

- **MariaDB major-XOR-minor 升级模式对齐 (v3.2.338)** — 原 bug：major + minor 升级串行执行，大版本升级时 mariadbd 可能重启 2 次。对齐 Nginx/Redis 的 major-XOR-minor：大版本升级后跳过小版本检查。
  **MariaDB major-XOR-minor upgrade mode alignment (v3.2.338)** — Original bug: major + minor upgrades serial → possible double restart. Aligned with Nginx/Redis major-XOR-minor: major upgrade skips subsequent minor check.

- **MariaDB socket 连接 fallback (v3.2.310, `_redis_socket_fallback_to_tcp`)** — 默认 TCP 连接失败时（`/var/run/mysqld/mysqld.sock` 移位）按常见 socket 路径顺序 fallback。Redis 同样加 socket→TCP fallback (`_sock_args`)。
  **MariaDB socket connection fallback (v3.2.310)** — TCP conn fails → fallback through common socket paths. Redis similarly `_redis_socket_fallback_to_tcp` (`_sock_args`).

- **MariaDB 官方仓库清理 (`_cleanup_mariadb_official_repo` + `_setup_mariadb_repo_el_fallback`)** — 升级 10.11 → 11.8 需切换 repo（mariadb-10.11 → mariadb-11.8）；旧 repo 不清理会 priority 冲突。新增清理函数 + EL 系 fallback（mariadb.org 不支持 EL 某架构时走 AppStream）。
  **MariaDB official repo cleanup (`_cleanup_mariadb_official_repo` + `_setup_mariadb_repo_el_fallback`)** — 10.11 → 11.8 needs repo switch (mariadb-10.11 → mariadb-11.8); leftover old repo causes priority conflicts. Added cleanup + EL fallback (when mariadb.org lacks EL arch → uses AppStream).

- **Redis `timeout 300` 绕过 CONFIG REWRITE (v3.2.352, 358)** — `CONFIG REWRITE` 在 openEuler `/etc/redis/redis.conf` 0640 权限下静默失败。改为 `harden_conf()` 以 root 身份直接写 conf + 重启。v3.2.358 before/after 对比守卫，避免 `timeout 300  # comment` 边界场景空替换触发脏标志。
  **Redis `timeout 300` bypasses CONFIG REWRITE (v3.2.352, 358)** — `CONFIG REWRITE` silently fails under openEuler `/etc/redis/redis.conf` 0640. Changed to `harden_conf()` as root direct-write + restart. v3.2.358 before/after diff guard for `timeout 300  # comment` edge case.

- **nginx.conf 默认 server 块花括号配对 regex (v3.2.352)** — 老 regex `r'^\s*server\s*{[^{}]*listen\s+80[^{}]*default_server[^{}]*}'` 不匹配嵌套 `location /`。改为 `_has_listen80` + `_has_default_server` 两段扫描 + 手写 brace counter。`neutralize_default_server_block()` 完成中和。
  **nginx.conf default server brace-counter regex (v3.2.352)** — Old regex can't match nested `location /`. Replaced with `_has_listen80` + `_has_default_server` two-stage scan + hand-written brace counter. `neutralize_default_server_block()` finalizes neutralization.

- **nginx 升级后兼容清理 (`_fix_nginx_post_upgrade_compat`)** — 1.28 → 1.30 升级后，`http2_*_timeout` / `http2_*_size` 等废弃指令在老 conf 中会让 `nginx -t` 失败。自动扫描所有 conf 文件 + 注释掉废弃指令 + 备份原文件。
  **nginx post-upgrade compatibility cleanup (`_fix_nginx_post_upgrade_compat`)** — Post 1.28 → 1.30 upgrade, deprecated `http2_*_timeout` / `http2_*_size` directives in old confs fail `nginx -t`. Auto-scans all conf files + comments out deprecated directives + backs up originals.

- **fail2ban 安装诊断增强 (v3.2.311, 352, 353)** — (1) Python 3.12+ 移除 `distutils`，预装 `python3-setuptools` + `python3-systemd` 防御。(2) `quiet=True` 改为手动 `subprocess.run(stderr=PIPE)`，失败时 `logging.error` 暴露根因。(3) `shutil.which("fail2ban-client")` 未装场景优雅跳过。(4) `python3-pyinotify` 必装，避免 polling backend 高 CPU。
  **fail2ban install diagnostics (v3.2.311, 352, 353)** — (1) Python 3.12+ removed `distutils`; pre-install `python3-setuptools` + `python3-systemd` as defense. (2) `quiet=True` changed to manual `subprocess.run(stderr=PIPE)`, exposes cause on failure. (3) `shutil.which("fail2ban-client")` graceful skip. (4) `python3-pyinotify` required to avoid polling backend high CPU.

- **Debian 12 nftables 加规则幂等 (v3.2.342)** — 生产日志发现 `nft add rule` 在 Debian 12 非幂等，每次 add 都追加重复规则（firewalld/ufw 自动去重）。先 `nft list` 探测再决定 add。
  **Debian 12 nftables add rule idempotent (v3.2.342)** — Prod logs found `nft add rule` non-idempotent on Debian 12, appends on every add (firewalld/ufw auto-dedup). Probe with `nft list` first.

- **io_capacity SSD 默认化 + 边界修复 (v3.2.335, 336)** — 2026 云 VM 99% SSD，从 HDD 默认 200 升级到 SSD 标准 1000/2000。v3.2.336 修正 v3.2.335 边界：1606MB 归 tiny tier（≤2GB），原 v3.2.335 只升级了 small tier。
  **io_capacity SSD default + boundary fix (v3.2.335, 336)** — 2026 cloud VMs 99% SSD. Upgraded from HDD 200 → SSD 1000/2000. v3.2.336 fixed v3.2.335 boundary: 1606MB belongs to tiny tier (≤2GB); v3.2.335 only upgraded small.

- **setup-config.php 扫描器防护 (v3.2.332)** — 生产日志发现扫描器访问 `/wp-admin/setup-config.php` 触发 WP bootstrap → Redis connect → `RedisException` → HTTP 500。Nginx 层封锁。
  **setup-config.php scanner shield (v3.2.332)** — Prod logs: scanners hitting `/wp-admin/setup-config.php` → WP bootstrap → Redis → exception → HTTP 500. Nginx-level block.

- **静态资源 404 白名单规则 (v3.2.333)** — Fail2Ban wordpress-404 过滤器排除合法 404（favicon/robots.txt/assets），锚定请求路径末尾正则防止 URL 编码绕过。
  **Static-asset 404 whitelist (v3.2.333)** — Fail2Ban wordpress-404 filter excludes legitimate 404s (favicon/robots.txt/assets); end-of-line anchored regex blocks URL-encoding bypass.

- **RFC 8615 `/.well-known/` 不整体屏蔽 (v3.2.334)** — 整体 deny 会阻断 security.txt / change-password / openid-configuration 等合法子路径。改为只屏蔽敏感子路径，`^~ /.well-known/acme-challenge/` 高优先级白名单。
  **RFC 8615 `/.well-known/` not blanket-blocked (v3.2.334)** — Blanket deny blocked legitimate sub-paths (security.txt / change-password / openid-configuration). Changed to selective sub-path block; `^~ /.well-known/acme-challenge/` higher-priority whitelist.

- **HTTP-01 挑战指数退避重试 (v3.2.309, 314)** — RETRYABLE 错误（challenge failed / server could not connect / unauthorized）走指数退避 + ±20% jitter（防 thundering herd）。ACME 速率限制突发自动恢复。
  **HTTP-01 challenge exponential backoff (v3.2.309, 314)** — RETRYABLE errors retry with exponential backoff + ±20% jitter. Auto-recovers from ACME rate-limit bursts.

- **OCSP URI 直接读取证书 (v3.2.316)** — CA 切换检测改用 `openssl x509 -ocsp_uri` 从证书 Authority Information Access 扩展直接读，取代脆弱的 issuer DN 正则。
  **OCSP URI direct read from cert (v3.2.316)** — CA switch detection uses `openssl x509 -ocsp_uri` reading cert's Authority Information Access extension instead of fragile issuer DN regex.

- **certbot 首装/卸载 stderr 噪音抑制 (v3.2.339)** — 生产日志 lamtin.hk 2026-04-17 Rocky 9.7 发现首次部署时 certbot 不存在导致 WARNING。降为 DEBUG（预期状态非故障）。
  **certbot first-install stderr noise suppression (v3.2.339)** — Prod log finding (lamtin.hk 2026-04-17 Rocky 9.7): first deploy raised WARNING on missing certbot. Downgraded to DEBUG.

- **Snap 健壮性（squashfs 预检 + 超时 180→420s + 连通性检测）(v3.2.306, 307, `_snap_install_or_refresh_robust`, `_check_snapcraft_reachable`, `_check_squashfs_available`, `_find_pending_snap_install`)** — 国内云 snap 超时 180s 假性失败（正常 2-5 分钟）；OpenVZ/LXC 内核无 squashfs mount 必败。预检不支持 → 跳到 pip venv Certbot。`_check_snapcraft_reachable()` 新增连通性预检避免 DNS 故障时卡死。
  **Snap robustness (`_snap_install_or_refresh_robust`, `_check_snapcraft_reachable`, `_check_squashfs_available`, `_find_pending_snap_install`)** — China cloud snap 180s false fail (normal 2-5 min); OpenVZ/LXC kernels lack squashfs → mount fail. Pre-check unsupported → skip to pip venv Certbot. `_check_snapcraft_reachable()` new connectivity probe avoids DNS-failure deadlock.

- **EPEL 健壮安装 (`_install_epel_release`, v3.2.308)** — 国内云 `dnf install epel-release` 常失败。自动检测原生 extras 仓库 + 下载 RPM 直装兜底。
  **Robust EPEL install (`_install_epel_release`, v3.2.308)** — China cloud often fails `dnf install epel-release`. Auto-detects native extras repo + RPM direct-install fallback.

- **apt lock 等待 (`_wait_for_apt_lock`)** — apt 被 unattended-upgrades 等并发占用时脚本不再立即失败；指数等待 + 超时。
  **apt lock wait (`_wait_for_apt_lock`)** — apt held by unattended-upgrades no longer fails immediately; exponential wait + timeout.

- **apt 缓存刷新对齐 (v3.2.325)** — nginx 主路径有 apt cache refresh，但 PHP/MariaDB 小版本升级路径缺。陈旧 apt 缓存 → MariaDB minor 升级永不触发 → CVE 风险。对齐到所有包管理路径。
  **apt cache refresh alignment (v3.2.325)** — nginx path had it but PHP/MariaDB minor upgrade paths missed. Stale cache → MariaDB minor upgrade never triggers → CVE risk. Aligned across all paths.

- **Valkey/Redis 平台感知升级门 (v3.2.301, 304, `detect_service` + `detect_full_version`)** — EL8+ < `_VALKEY_TARGET_VERSION (9.0)` 触发 Remi 模块流升级。仓库无 Valkey 时告知用户 + 用 redis-server 兜底。`_redis_flavor_name()` 显示名（"Valkey" 或 "Redis"）。
  **Valkey/Redis platform-aware upgrade gate (v3.2.301, 304)** — EL8+ < `_VALKEY_TARGET_VERSION (9.0)` triggers Remi module upgrade. No-Valkey repo → user hint + redis-server fallback. `_redis_flavor_name()` display name.

- **WordPress 插件安装多源 fallback (v3.2.311, `_wpcli_plugin_install_robust`)** — WordPress.org 下载链国内云偶发 5xx，新增镜像源 fallback。
  **WordPress plugin install multi-source fallback (v3.2.311, `_wpcli_plugin_install_robust`)** — WordPress.org download has occasional China-cloud 5xx; mirror source fallback added.

- **soap 扩展跨发行版基线 (v3.2.319, `_check_soap_loaded`)** — AlmaLinux/RHEL 预置 `php_value[soap.wsdl_cache_dir]`；soap 未装时 worker 启动每次报 warning。显式装 soap + `_check_soap_loaded()` 验证。
  **soap extension cross-distro baseline (v3.2.319, `_check_soap_loaded`)** — AlmaLinux/RHEL pre-set `php_value[soap.wsdl_cache_dir]`; unloaded soap → worker warnings. Explicit install + `_check_soap_loaded()` verify.

- **原子写入 hook + systemd unit (v3.2.321)** — certbot deploy hook 和 systemd unit 文件原为普通写入，断电会留半行。全部改用 `_safe_write_file()` 原子写入（tempfile → fsync → os.replace）。
  **Atomic write for hooks + systemd units (v3.2.321)** — Plain-write left half-lines on power loss. Changed to `_safe_write_file()` atomic (tempfile → fsync → os.replace).

- **顶层 flock + TOCTOU 修复 (v3.2.341)** — 模块级全局进程锁 FD 防 GC 提前释放；`try/except FileNotFoundError` 替代 `exists() + open()` 消除 TOCTOU 窗口。
  **Top-level flock + TOCTOU fix (v3.2.341)** — Module-level process-lock FD prevents GC; `try/except FileNotFoundError` replaces `exists() + open()`, eliminates TOCTOU.

- **php*-fpm 服务名动态扫描 (v3.2.305, `_f08_scan_active_php_fpm`)** — 不再硬编码 `php-fpm` / `php8.4-fpm`，扫描 active systemd units 正则 `php\d*[-.]fpm`。覆盖 EL / Ubuntu Sury / Debian 原生 / 未来版本。
  **php*-fpm service name dynamic scan (v3.2.305, `_f08_scan_active_php_fpm`)** — No longer hardcoded; scans active systemd units with `php\d*[-.]fpm`. Covers EL / Ubuntu Sury / Debian native / future.

- **MariaDB 数据目录权限修复 (`_fix_datadir_perms`)** — 某些 restore 场景 `/var/lib/mysql` owner 被 root 持有导致 mariadbd 启动失败。自动 `chown -R mysql:mysql`。
  **MariaDB datadir permission fix (`_fix_datadir_perms`)** — Some restore scenarios leave `/var/lib/mysql` owned by root, mariadbd fails. Auto `chown -R mysql:mysql`.

- **srcache 静态二进制 fallback (`_srcache_install_static_binary`, `_try_install_srcache_packages`)** — 编译 srcache-nginx-module 失败时（GCC 版本/headers 缺）改用预编译静态二进制。
  **srcache static binary fallback (`_srcache_install_static_binary`, `_try_install_srcache_packages`)** — Compile failure (GCC/headers) → pre-compiled static binary.

---

### 🔧 改进 / Improvements

- **open_file_cache 默认启用 (v3.2.317)** — 从 `--optimize` opt-in 改为默认。`max=10000 inactive=60s` 适合 WordPress 典型访问模式。
  **open_file_cache enabled by default (v3.2.317)** — Changed from `--optimize` opt-in. `max=10000 inactive=60s` fits typical WordPress patterns.

- **TCP Fast Open 运行时检测 (v3.2.318)** — 原无条件启用 TFO 老内核 listen fail。运行时检测 `net.ipv4.tcp_fastopen sysctl`；服务端侧安全。
  **TCP Fast Open runtime detection (v3.2.318)** — Unconditional TFO failed on old kernels. Runtime `net.ipv4.tcp_fastopen sysctl` probe; server-side safe.

- **InnoDB log file size 分层 (v3.2.318)** — RAM 分层：tiny 64M / small 128M / medium 256M / large 512M。
  **InnoDB log file size tiering (v3.2.318)** — RAM-tiered: tiny 64M / small 128M / medium 256M / large 512M.

- **opcache interned_strings_buffer 16→32 (v3.2.335)** — WordPress 6.9 + 常见插件生成大量重复字符串，16MB 在 10+ 插件时易满。32MB 是 2026 WP/Laravel 共识下限。
  **opcache interned_strings_buffer 16→32 (v3.2.335)** — WP 6.9 + plugins generate duplicate strings, 16MB fills with 10+ plugins. 32MB is 2026 consensus minimum.

- **QUIC retry + GSO 硬化 (v3.2.335)** — `quic_retry on`（防 QUIC 源地址伪造 DDoS）+ `quic_gso on`（UDP GSO，~40% 吞吐，内核 ≤5.4 自动降级）。
  **QUIC retry + GSO hardening (v3.2.335)** — `quic_retry on` (blocks QUIC spoof DDoS) + `quic_gso on` (UDP GSO, ~40% throughput, auto-degrade on ≤5.4).

- **Nginx/MariaDB/PHP/Redis/Certbot 全链路版本 + 能力探测缓存 (v3.2.322, 327, 328)** — 对齐 Nginx 设计模式。Nginx 14 次 × ~10ms、PHP `detect_installed_version` 14 × ~50ms、Redis `detect_version` 14 × + `_detect_redis_full_version` 10 × + `detect_service_name` 15 ×、MariaDB `_detect_mariadb_full_version` / Certbot `_detect_certbot_full_version` 同样对齐。全部模块级缓存 + 统一失效钩子 (`_reset_mariadb_capability_caches` / `_reset_php_capability_caches` / `_reset_redis_capability_caches` / `_reset_certbot_capability_caches` / `_reset_mptcp_cache`)。**部署期 subprocess 调用减 ~70%**。
  **Nginx/MariaDB/PHP/Redis/Certbot full-chain version + capability probe cache (v3.2.322, 327, 328)** — Follows Nginx design pattern. Nginx 14× ~10ms, PHP 14× ~50ms, Redis 14× + 10× + 15×, MariaDB/Certbot similarly aligned. All module-level caches + unified invalidation hooks. **~70% reduction in deploy-time subprocess calls**.

- **DCL 锁 nogil 安全 (v3.2.331)** — Python 3.13+ nogil 下 `_MPTCP_SUPPORT_LOCK = _threading.Lock()` 对齐双重检查锁定 (DCL) 模式。
  **DCL lock nogil-safe (v3.2.331)** — Python 3.13+ nogil; `_MPTCP_SUPPORT_LOCK = _threading.Lock()` aligned with DCL pattern.

- **Nginx systemd LimitNOFILE drop-in (v3.2.315, `_install_systemd_rlimit_drop_in`)** — `/etc/systemd/system/nginx.service.d/limit-nofile.conf` 写入 `LimitNOFILE=<target>`，master 启动就携带，消除首次 reload 后 warning。泛化成 `_install_systemd_rlimit_drop_in()` 复用到 PHP-FPM / mariadbd。
  **Nginx systemd LimitNOFILE drop-in (v3.2.315, `_install_systemd_rlimit_drop_in`)** — `/etc/systemd/system/nginx.service.d/limit-nofile.conf` carries `LimitNOFILE=<target>` at master start, eliminates first-reload warning. Generalized to `_install_systemd_rlimit_drop_in()` reused for PHP-FPM / mariadbd.

- **autoindex off 显式 (v3.2.326)** — nginx 默认 off，显式声明所有 server block 防未来默认变化。
  **Explicit `autoindex off` (v3.2.326)** — nginx default off; explicit declaration defends against future default changes.

- **Nginx worker_connections + FastCGI buffer 分层 (`_tune_nginx_worker_connections`, `_nginx_fastcgi_buffers_tiered`)** — worker_connections 按 LimitNOFILE 和 CPU 动态；FastCGI buffer 按 RAM 分层（tiny 16 4k / small 64 4k / medium 128 8k / large 256 16k）。
  **Nginx worker_connections + FastCGI buffer tiering (`_tune_nginx_worker_connections`, `_nginx_fastcgi_buffers_tiered`)** — worker_connections dynamic by LimitNOFILE + CPU; FastCGI buffers RAM-tiered.

- **内联代理方法清理 (v3.2.312)** — 清理 `_detect_db_service` / `_detect_installed_php_version` / `_get_nginx_version_tuple` / `_get_mariadb_full_version` 等 30+ 代理方法，统一走 Manager 类 canonical API。
  **Inline proxy method cleanup (v3.2.312)** — Cleaned 30+ proxies (`_detect_db_service` / `_detect_installed_php_version` / `_get_nginx_version_tuple` / `_get_mariadb_full_version` etc.); unified to Manager canonical APIs.

- **Canonical 版本探测 API (v3.2.330, `_detect_nginx_version`, `_detect_mariadb_version`)** — 统一入口返回 `(1, 30, 0)` 元组。外部调用点全部迁移。
  **Canonical version probe API (v3.2.330, `_detect_nginx_version`, `_detect_mariadb_version`)** — Unified entry returns `(1, 30, 0)` tuple. All external call sites migrated.

- **default version 常量对齐 (v3.2.329)** — `_NGINX_DEFAULT_VERSION` / `_PHP_DEFAULT_VERSION` / `_MARIADB_DEFAULT_VERSION` / `_CERTBOT_DEFAULT_VERSION` 命名惯例统一。
  **default version constant alignment (v3.2.329)** — `_NGINX_DEFAULT_VERSION` / `_PHP_DEFAULT_VERSION` / `_MARIADB_DEFAULT_VERSION` / `_CERTBOT_DEFAULT_VERSION` unified.

- **CertManager 架构重构（+33 新方法）** — `_build_ca_providers()` / `_build_domain_args()` / `_default_cert_domain_args()` 等组合化；`_diagnose_ssl_failure()` 失败诊断分离；`_check_certbot_snap_migration()` / `_check_zerossl_migration()` 迁移路径判定；`_cert_valid_days_remaining()` / `_clean_challenge_dir()` 等工具方法抽出。
  **CertManager architecture refactor (+33 new methods)** — Compositional `_build_ca_providers()` / `_build_domain_args()` / `_default_cert_domain_args()`; separated `_diagnose_ssl_failure()`; migration-path deciders `_check_certbot_snap_migration()` / `_check_zerossl_migration()`; extracted utilities `_cert_valid_days_remaining()` / `_clean_challenge_dir()` etc.

- **WPDeployManager god-class 拆分重构** — V3.2.8 最大的架构改动：`WPDeployManager` 从 **327 方法缩减到 133 方法**（-194），组件生命周期逻辑全部迁移到各专业 Manager 类。WPDeployManager 保留为轻量级编排层（orchestration only），逻辑下沉到：
  - **NginxManager 接收 80 个迁移方法** + 13 个真新（Brotli 编译链 / Cloudflare Real IP / 多域证书对齐 / includes 健康检查等继承；真新：`_detect_nginx_version` / `_ensure_mptcp_nginx_support` / `_install_systemd_rlimit_drop_in` / `_optimize_nginx_main_conf` / `_srcache_install_static_binary` / `_tune_nginx_worker_connections` 等）
  - **CertManager 接收 28 个迁移** + 5 个真新（`_build_ca_providers` / `_build_domain_args` / `_cert_valid_days_remaining` / `_check_certbot_snap_migration` 继承；真新：`_snap_install_or_refresh_robust` / `_check_snapcraft_reachable` / `_check_squashfs_available` / `_find_pending_snap_install` / `_issue_local_self_signed`）
  - **PHPManager 接收 17 个迁移** + 9 个真新（`_apply_php_ini_values` / `_build_php_packages` / `_compile_php_redis_extension` 继承；真新：`_detect_php_fpm_service_uncached` / `_fix_sury_ppa_codename_for_non_lts` / `_get_ram_tier` / `_print_component_versions` / `php_ini_security_directives` / `detect_service` / `detect_version` 等）
  - **MariaDBManager 接收 14 个迁移** + 9 个真新（`_diagnose_mariadb_failure` / `_extend_wait_retry` / `_finalize_mariadb_upgrade` / `_fix_datadir_perms` / `_fix_mariadb_deprecated_options` 继承；真新：`_cleanup_mariadb_official_repo` / `_detect_mariadb_full_version` / `_fix_mariadb_client_mismatch` / `_setup_mariadb_repo_el_fallback`）
  - **RedisManager 接收 2 迁移** + 13 个真新（此处以真新为主，配合 Valkey 9.0 升级链：`_upgrade_valkey_bookworm_backports` / `_upgrade_valkey_el` / `_redis_socket_fallback_to_tcp` / `_sock_args` / `detect_full_version` / `detect_service` / `get_data_dir` 等）

  **价值**：单一职责原则（SRP），每个 Manager 只关心自己的组件生命周期；WPDeployManager 仅做跨组件编排；单测可针对单 Manager 独立进行；未来增删组件局部化，不再需要改 WPDM 巨类。
  **Value**: Single Responsibility Principle (SRP), each Manager owns its component's lifecycle; WPDeployManager orchestrates only; unit tests can target single Manager; future component add/remove localized, no more touching the WPDM god-class.

  **WPDeployManager god-class decomposition** — Biggest V3.2.8 architectural change: `WPDeployManager` shrunk from **327 methods to 133** (-194); component lifecycle logic migrated out to specialized Managers. WPDeployManager kept as thin orchestration layer. Distribution: NginxManager (+80 migrated, 13 truly new), CertManager (+28 migrated, 5 truly new), PHPManager (+17 migrated, 9 truly new), MariaDBManager (+14 migrated, 9 truly new), RedisManager (+2 migrated, 13 truly new — Redis is the exception with mostly genuinely new Valkey-9.0-related code).

- **日志收集子工具 (`collect_logs`, `_tail_file`, `_collect_conf`)** — WPDeployManager 新增故障排查辅助：一键打包 nginx/php-fpm/mariadbd/redis 最近日志 + 所有 conf 文件到 `/tmp/wp_ssl_<domain>_<ts>.tar.gz`，方便支持。
  **Log collection helper (`collect_logs`, `_tail_file`, `_collect_conf`)** — WPDeployManager new troubleshooting aid: one-shot bundles recent nginx/php-fpm/mariadbd/redis logs + all confs to `/tmp/wp_ssl_<domain>_<ts>.tar.gz` for support.

- **测试脚本改进 (v3.2.351-355, 357-358)** — 436/436 静态测试通过，18/18 回归模拟全捕获。新增 42 项覆盖 v3.2.345-358 改动的静态断言。`_nginx_supports_mh/ahi` 按 nginx 官方 CHANGES 精确版本判定。Local-test 模式 5 项豁免断言。Ubuntu 26.04 compat 断言反转为"resolute 不在列表 + probe fallback 代码存在"。
  **Test script improvements (v3.2.351-355, 357-358)** — 436/436 static tests pass, 18/18 regression simulations caught. 42 new assertions covering v3.2.345-358. `_nginx_supports_mh/ahi` per upstream CHANGES. Local-test 5 exemptions. Ubuntu 26.04 compat assertion flipped to "no resolute in list + probe fallback exists".

---

### 📊 平台覆盖 / Platform Coverage

| 平台 / Platform | V3.2.8 状态 / Status |
|---|---|
| AlmaLinux 10.1 | ✅ prod 实测（toksun.cn update v240→v358 字节级零配置变化，除主动升级的 nginx/PHP/MariaDB 包外）|
| Rocky 9.7 | ✅ prod |
| Ubuntu 24.04 LTS (noble) | ✅ prod |
| Ubuntu 22.04 LTS (jammy) | ✅ prod |
| Debian 12 (bookworm) | ✅ prod |
| Debian 13 (trixie) | ⚠ 代码就绪（trixie 2025-08 GA）|
| Ubuntu 26.04 LTS (resolute) | ⚠ 代码就绪（2026-04-23 GA）|
| openEuler 24.03 LTS SP3 | ⚠ 代码就绪（`--local-test` 验证通过）|
| 银河麒麟 V11 | ⚠ 代码就绪 |

---

## [V3.2.7]

> **升级说明 / Upgrade note**
> V3.2.7 是全组件安全加固与用户体验优化版本（PATCH-286）。
> 对照 OWASP / CIS Benchmark / 官方文档，为 PHP、MariaDB、Redis、OS、systemd、WordPress 六个组件
> 补齐 55 项安全配置，新增 Nginx 修复链、wp-config update 路径补注入、readline 行编辑、
> Ctrl+C 干净退出、Debian 12/13 nftables 防火墙支持。全部加固通过 `update` 子命令自动生效，无需重新部署。
>
> V3.2.7 is a full-stack security hardening and UX polish release (PATCH-286).
> 55 security checks across PHP, MariaDB, Redis, OS sysctl, systemd, and WordPress — verified against
> OWASP / CIS Benchmark / official docs. New Nginx repair chain, wp-config update-path injection,
> readline line editing, clean Ctrl+C exit. All hardening applies automatically via `update`.

---

### 🔒 安全增强 / Security Enhancements

- **PHP-FPM 安全加固 (PATCH-286)** — 12 项 OWASP PHP Cheat Sheet 加固，委托 `PHPManager.harden_ini()` 实现：expose_php=Off / display_errors=Off / display_startup_errors=Off / allow_url_include=Off / open_basedir（webroot+/tmp+/usr/share/php）/ disable_functions（exec,passthru,shell_exec,system,popen,dl,show_source；保留 proc_open 供 WP-CLI、curl_exec 供 HTTP API）/ session cookie 全量加固（httponly+secure+samesite=Lax+strict_mode+use_only_cookies+use_trans_sid=0）。
  **PHP-FPM security hardening (PATCH-286)** — 12 items per OWASP PHP Cheat Sheet, delegated to `PHPManager.harden_ini()`: expose_php / display_errors / allow_url_include / open_basedir / disable_functions (preserving proc_open for WP-CLI, curl_exec for HTTP API) / session cookie hardening (httponly, secure, samesite, strict_mode).

- **MariaDB 安全加固 (PATCH-286)** — 5 项 CIS MariaDB Benchmark 加固，委托 `MariaDBManager.security_cnf_lines()` 返回：bind-address=127.0.0.1 / local-infile=0 / skip-symbolic-links=1 / secure-file-priv=/dev/null / skip-show-database。
  **MariaDB security hardening (PATCH-286)** — 5 items per CIS MariaDB Benchmark, delegated to `MariaDBManager.security_cnf_lines()`: bind-address / local-infile / skip-symbolic-links / secure-file-priv / skip-show-database.

- **Redis 安全加固 (PATCH-286)** — 4 项 Redis 官方安全指南加固，委托 `RedisManager.harden_conf()` 实现：bind 127.0.0.1 ::1 / rename-command FLUSHALL+FLUSHDB "" / disable THP（transparent_hugepage）。
  **Redis security hardening (PATCH-286)** — 4 items per Redis official security guide, delegated to `RedisManager.harden_conf()`: bind localhost / rename-command FLUSHALL+FLUSHDB / disable THP.

- **OS 内核安全加固 (PATCH-286)** — 7 项 CIS Linux Benchmark sysctl 参数：tcp_syncookies=1 / rp_filter=1（all+default）/ accept_redirects=0（all+default）/ send_redirects=0（all+default）/ icmp_ignore_bogus_error_responses=1 / protected_hardlinks=1 / protected_symlinks=1。
  **OS kernel security hardening (PATCH-286)** — 7 CIS Linux Benchmark sysctl parameters: tcp_syncookies / rp_filter / accept_redirects / send_redirects / icmp_ignore_bogus / protected_hardlinks / protected_symlinks.

- **systemd 沙箱 (PATCH-286)** — SSL 续期服务新增 NoNewPrivileges=true / PrivateTmp=true（不使用 ProtectSystem/ProtectHome，certbot 需写 /etc/letsencrypt）。
  **systemd sandboxing (PATCH-286)** — SSL renewal service: NoNewPrivileges=true / PrivateTmp=true (ProtectSystem/ProtectHome omitted — certbot needs /etc/letsencrypt write access).

- **WordPress WP_DEBUG=false (PATCH-286)** — 生产环境显式禁用调试输出，加入 hardening_defines 列表。
  **WordPress WP_DEBUG=false (PATCH-286)** — Explicitly disable debug output in production, added to hardening_defines list.

---

### 🐛 问题修复 / Bug Fixes

- **Nginx server_names_hash_bucket_size 自动修复 (PATCH-286)** — 域名过长或 server block 过多时 `nginx -t` 报 `could not build server_names_hash`。在 `_diagnose_and_fix_config()` 新增 Case 3：自动检测错误 → 在 nginx.conf http 块插入 `server_names_hash_bucket_size 128` → 备份 `.bak286` → 重新验证。
  **Nginx server_names_hash_bucket_size auto-repair (PATCH-286)** — Added Case 3 to `_diagnose_and_fix_config()`: detects `could not build server_names_hash` → inserts `server_names_hash_bucket_size 128` into nginx.conf → backup `.bak286` → re-validates.

- **wp-config 安全常量 update 路径补注入 (PATCH-286)** — `inject_wp_hardening()` 仅在 deploy 新建 wp-config.php 时调用，老站点 update 后缺少 WP_DEBUG=false 等 8 个常量。新增 `_ensure_wp_hardening_constants()` 在 update 路径幂等补注入。
  **wp-config hardening constants injected during update (PATCH-286)** — Added `_ensure_wp_hardening_constants()` for idempotent injection during update (pattern follows `_ensure_wp_cron_constant()`).

- **readline 行编辑 (PATCH-286)** — `import readline` 提升到模块级，所有 32 处 `input()` 自动获得退格键/方向键/Ctrl+A/Ctrl+E 行编辑支持。修复退格显示 `^H`、方向键显示 `^[[D` 的问题。
  **readline line editing (PATCH-286)** — `import readline` moved to module level; all 32 `input()` calls now support backspace, arrow keys, and standard line editing. Fixes `^H` display on backspace.

- **Ctrl+C 干净退出 (PATCH-286)** — 顶层 `except KeyboardInterrupt: sys.exit(130)` 防止 Python traceback；交互向导 4 处 DB 配置 `pass` 改为 `return []`（退出向导而非静默跳过）。
  **Clean Ctrl+C exit (PATCH-286)** — Top-level `except KeyboardInterrupt: sys.exit(130)` prevents Python traceback; 4 interactive wizard DB prompts changed from `pass` to `return []` (exit wizard instead of silently skipping).

- **Debian 12/13 nftables 防火墙支持 (PATCH-286)** — `setup_firewall()` 新增 nftables 路径（优先级 ufw > firewall-cmd > nft）。创建独立 `inet wp_ssl` 表（policy accept，不锁 SSH）放行 80/443 TCP；持久化到 `/etc/nftables.conf`；`systemctl enable nftables`（Debian 12 默认未启用）。
  **Debian 12/13 nftables firewall support (PATCH-286)** — `setup_firewall()` adds nftables path (priority: ufw > firewall-cmd > nft). Creates dedicated `inet wp_ssl` table (policy accept, won't lock SSH) allowing TCP 80/443; persists to `/etc/nftables.conf`; enables nftables.service (disabled by default on Debian 12).

---

### 🔧 改进 / Improvements

- **架构规范 + 模块化 (PATCH-286)** — 模块级醒目位置插入 8 条架构规范（组件逻辑放 Manager / WPDeployManager 仅编排 / 平台差异查表 / 文件原子写入 / 信号安全 / subprocess timeout / _safe_chmod / 正反示例）。安全加固方法提取到各 Manager 类：`PHPManager.harden_ini()` / `RedisManager.harden_conf()` / `MariaDBManager.security_cnf_lines()` / `NginxManager._diagnose_and_fix_config()` Case 3。WPDeployManager 仅做一行委托调用。
  **Architecture rules + modularization (PATCH-286)** — 8-rule architecture spec at module level (component logic in Managers / WPDM orchestration only / platform registry / atomic writes / signal safety / with positive and negative examples). Security methods extracted to Managers with one-line delegation from WPDeployManager.

- **测试脚本适配 (PATCH-286)** — 新增 28 项 PATCH-286 检查（18 静态 + 10 运行时），覆盖全部加固项的源码存在性和部署后运行时生效性。
  **Test script adaptation (PATCH-286)** — 28 new PATCH-286 checks (18 static + 10 runtime) covering source presence and runtime effectiveness of all hardening items.

---

## [V3.2.6]

> **升级说明 / Upgrade note**
> V3.2.6 是架构重构、安全审计与 OpenSSL 韧性强化版本，包含 PATCH-281 至 PATCH-285。
> 核心主题：平台抽象层重构（126 处硬编码分支集中化）、原子文件写入、信号安全重构、
> OpenSSL/Python SSL 兼容性三层防线、ntfy.sh 零配置 webhook、self-update SHA256 预检优化。
> 从 V3.2.5 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.2.6 is an architecture refactoring, security audit and OpenSSL resilience release (PATCH-281 through PATCH-285).
> Core themes: Platform Abstraction Layer (126 hardcoded branches centralized), atomic file writes,
> signal-safe shutdown, three-layer OpenSSL/Python SSL defense, zero-config ntfy.sh webhook,
> self-update SHA256 pre-check optimization.
> To upgrade from V3.2.5, replace the script and run the `update` subcommand.

---

### ✨ 新功能 / New Features

- **`fix-openssl` 独立子命令 (PATCH-285)** — `python3 wp_ssl_bootstrap.py fix-openssl` 4 步诊断+修复 OpenSSL/Python SSL 兼容性问题：版本比较检测 → `ldd`/`rpm -qf` 诊断 → 自动修复 → 子进程验证。无需 `--domain`/`--email`，直接运行即可。
  **`fix-openssl` standalone subcommand (PATCH-285)** — `python3 wp_ssl_bootstrap.py fix-openssl` provides 4-step diagnosis and repair for OpenSSL/Python SSL mismatch: version comparison → `ldd`/`rpm -qf` diagnostics → auto-repair → subprocess verification. No `--domain`/`--email` required.

- **ntfy.sh 零配置 webhook (PATCH-284)** — 交互式向导新增 `[1] 自动配置 ntfy.sh` 选项，`secrets.token_hex(8)` 生成 64-bit 熵主题名，curl 适配纯文本 POST + `X-Title`/`X-Priority: high`/`X-Tags: warning` 头。Slack/DingTalk/飞书保持 `{"text":"..."}` JSON 格式。部署完成后输出可直接复制的 `update --notify-webhook` 命令。
  **ntfy.sh zero-config webhook (PATCH-284)** — Interactive wizard adds `[1] Auto-configure ntfy.sh` option with `secrets.token_hex(8)` topic generation. Curl adapter uses plaintext POST with `X-Title`/`X-Priority`/`X-Tags` headers. Slack/DingTalk/Feishu keep JSON format. Outputs a copy-paste-ready `update --notify-webhook` command after deploy.

- **Self-update SHA256 预检 (PATCH-285)** — 先下载远程 SHA256 文件（~64 字节）与本地比对，一致则跳过完整脚本下载（1.5MB+），节省带宽和时间。
  **Self-update SHA256 pre-check (PATCH-285)** — Downloads remote SHA256 file (~64 bytes) first and compares with local hash. If identical, skips full script download (1.5MB+), saving bandwidth and time.

- **双 CA 容灾架构 (PATCH-282)** — ZeroSSL (主) + Let's Encrypt (降级) 双 CA 自动切换，EAB 凭据自动获取，ECC→RSA 自动降级，速率限制检测跳过无意义重试。
  **Dual-CA failover architecture (PATCH-282)** — ZeroSSL (primary) + Let's Encrypt (fallback) with auto-switch, EAB auto-negotiation, ECC→RSA auto-downgrade, rate-limit detection to skip futile retries.

- **证书 CA 迁移 `migrate-ssl` (PATCH-282)** — 检测当前证书签发商，支持从 LE 迁移到 ZeroSSL 或反向迁移，保留原有域名列表。
  **Certificate CA migration `migrate-ssl` (PATCH-282)** — Detects current certificate issuer, supports migration from LE to ZeroSSL or vice versa, preserving existing domain list.

---

### 🔒 安全增强 / Security Enhancements

- **原子文件写入 `_write_bytes_atomic` (PATCH-284)** — `tempfile.mkstemp()` → write → `os.fsync()` → `os.replace()` 三步原子写入，24 处调用迁移。符合 Python 官方 `os.replace` + `os.fsync` 最佳实践（POSIX 原子语义）。消除断电/崩溃时文件损坏风险。
  **Atomic file writes `_write_bytes_atomic` (PATCH-284)** — `tempfile.mkstemp()` → write → `os.fsync()` → `os.replace()` three-step atomic write, 24 call sites migrated. Follows Python official `os.replace` + `os.fsync` best practices (POSIX atomic semantics). Eliminates file corruption risk during power loss or crash.

- **信号安全重构 (PATCH-285)** — 移除信号处理器中的 `raise KeyboardInterrupt`，改为标志位 `_shutdown_requested` + 21 个轮询点 `_abort_if_shutdown()`。`_run_subcommand` 捕获 `KeyboardInterrupt` 确保 rollback 执行。`_CriticalSectionCtx` 上下文管理器保护关键区段。
  **Signal-safe shutdown (PATCH-285)** — Removed `raise KeyboardInterrupt` from signal handlers; replaced with `_shutdown_requested` flag + 21 polling points via `_abort_if_shutdown()`. `_run_subcommand` catches `KeyboardInterrupt` to ensure rollback. `_CriticalSectionCtx` context manager protects critical sections.

- **`_safe_chmod` 统一权限设置 (PATCH-283)** — 消除 `islink()+chmod()` TOCTOU 反模式，16 处调用迁移。`_md5_noncrypto` / `_sha1_noncrypto` 显式标记非密码学用途（`usedforsecurity=False` + Python 3.6 回退）。
  **`_safe_chmod` unified permission setting (PATCH-283)** — Eliminates `islink()+chmod()` TOCTOU anti-pattern, 16 call sites migrated. `_md5_noncrypto` / `_sha1_noncrypto` explicitly mark non-cryptographic use (`usedforsecurity=False` with Python 3.6 fallback).

- **凭据安全强化 (PATCH-284)** — `LC_MESSAGES=C` 确保 stderr 英文输出（防止本地化泄露路径）；`/proc/self/mem` 清零 `/proc/environ` 中的敏感环境变量；`O_NOFOLLOW` 启动检查；凭据文件写入返回值检查。
  **Credential hardening (PATCH-284)** — `LC_MESSAGES=C` forces English stderr (prevents localized path leaks); `/proc/self/mem` zeroes sensitive env vars in `/proc/environ`; `O_NOFOLLOW` startup check; credential file write return value verification.

---

### 🐛 问题修复 / Bug Fixes

- **OpenSSL/Python SSL 兼容性三层防线 (PATCH-285)** — 解决 `install_packages()` 升级 `openssl-libs` 后 Python `_ssl.so` ABI 不兼容问题（Rocky Linux / EL9 已知广泛问题）。L0 预防：`ssl.OPENSSL_VERSION` vs `openssl version` 编译时/运行时版本比较（符合 PEP 644 最佳实践），不匹配则自动 `dnf upgrade python3-libs`。L1 自愈：`_try_repair_openssl()` 每次修复后子进程验证，遍历全部策略直到真正修好。L2 降级：curl/wget 接管。
  **OpenSSL/Python SSL three-layer defense (PATCH-285)** — Fixes `install_packages()` upgrading `openssl-libs` breaking Python `_ssl.so` ABI (known widespread issue on Rocky Linux / EL9). L0 prevention: `ssl.OPENSSL_VERSION` vs `openssl version` compile-time/runtime version comparison (per PEP 644 best practice), auto `dnf upgrade python3-libs` on mismatch. L1 self-heal: `_try_repair_openssl()` verifies fix in subprocess after each attempt. L2 fallback: curl/wget takeover.

- **Certbot challenge 文件残留 (PATCH-284)** — ZeroSSL ECC 签发超时后 challenge 文件残留 → RSA 降级时 `FileExistsError`。3 处添加 `_clean_challenge_dir()`：CA 切换前、ECC→RSA 降级前、renew CA 循环开头。
  **Certbot challenge file cleanup (PATCH-284)** — Stale challenge files after ZeroSSL ECC timeout caused `FileExistsError` during RSA fallback. Added `_clean_challenge_dir()` at 3 points: before CA switch, before ECC→RSA downgrade, and at renew CA loop start.

- **Staging/中国大陆网络检测 (PATCH-285)** — 从 `_is_china_cloud()`（云商身份，误杀海外节点）改为 `_is_china_network()`（网络出口位置，精确到 region metadata `cn-` 前缀）。腾讯云香港/新加坡不再被误判为中国大陆网络。
  **Staging / China mainland network detection (PATCH-285)** — Changed from `_is_china_cloud()` (vendor identity, false positive on overseas nodes) to `_is_china_network()` (network egress location, precise to region metadata `cn-` prefix). Tencent Cloud Hong Kong / Singapore no longer falsely detected as China mainland.

- **Self-update 非 TTY 交叉验证 (PATCH-284)** — 非 TTY 环境下交叉验证失败不再阻断更新（降级为 WARNING），避免 cron/CI 场景被卡住。
  **Self-update non-TTY cross-verification (PATCH-284)** — Cross-verification failure in non-TTY mode no longer blocks updates (downgraded to WARNING), preventing cron/CI from stalling.

---

### 🔧 改进 / Improvements

- **平台抽象层重构 (PATCH-281)** — 将分散在 40,000 行中的 126 个 `if pkg_mgr == "apt"` / `in ("dnf","yum")` 硬编码分支集中到 `_PLATFORM_REGISTRY` 注册表。业务逻辑通过 `self.platform["key"]` 访问平台特定值（包名、路径、服务名等），上游改包名/路径时只需改注册表一行。方法委托模式（`[REFACTOR]` 标签）将 Nginx/MariaDB/PHP/Redis/Cert 相关方法代理到各自管理器。
  **Platform Abstraction Layer refactoring (PATCH-281)** — Consolidated 126 hardcoded `if pkg_mgr == "apt"` / `in ("dnf","yum")` branches scattered across 40,000 lines into a centralized `_PLATFORM_REGISTRY`. Business logic accesses platform-specific values (package names, paths, service names) via `self.platform["key"]`; upstream package/path changes require editing only one line. Method delegation pattern (`[REFACTOR]` tags) proxies Nginx/MariaDB/PHP/Redis/Cert methods to their respective managers.

- **OpenSSL 修复策略增强** — L0.5a: `/etc/ld.so.conf.d/` 第三方条目扫描禁用。L0.5b: `LD_LIBRARY_PATH` 污染清理。L0.5c: `/opt/` `/usr/local/` 全盘 OpenSSL 副本扫描。L0.9: `rpm -qf`/`dpkg -S` 孤儿文件诊断+自动移除。L1.5: `dnf downgrade openssl-libs` 强制降级。APT: `libssl3t64` (Ubuntu 24.04+) + `--fix-broken`。
  **OpenSSL repair strategy enhancements** — L0.5a: `/etc/ld.so.conf.d/` third-party entry scan. L0.5b: `LD_LIBRARY_PATH` pollution cleanup. L0.5c: `/opt/` `/usr/local/` full-disk OpenSSL copy scan. L0.9: `rpm -qf`/`dpkg -S` orphan file diagnosis + auto-removal. L1.5: `dnf downgrade openssl-libs` forced rollback. APT: `libssl3t64` (Ubuntu 24.04+) + `--fix-broken`.

- **国际化 (i18n)** — 主脚本 14 处 + 测试脚本 63 处英文模式下的中文硬编码修复。Nginx 模块描述、PATCH-284 日志、WP-CLI 源名等全部改为英文常量。
  **Internationalization (i18n)** — Fixed 14 hardcoded Chinese strings in main script + 63 in test script that leaked in English mode. Nginx module descriptions, PATCH-284 logs, WP-CLI source names all changed to English constants.

- **测试脚本增强** — `--staging` 默认开启（避免 LE 速率限制）；中国大陆网络自动切换生产环境（curl 连通性测试）；staging 证书 SSL 握手验证兼容；DNS 预检/部署失败时提前终止（避免级联失败浪费时间）；37 项 PATCH 静态检查 (P282×8 + P283×11 + P284×13 + P285×5)。
  **Test script enhancements** — `--staging` on by default (avoids LE rate limits); China mainland auto-switches to production (curl connectivity test); staging cert SSL handshake compat; early abort on DNS/deploy failure (avoids cascading waste); 37 PATCH static checks (P282×8 + P283×11 + P284×13 + P285×5).

- **平台兼容性** — `missing_ok=True` → try/except (Python 3.6 EL7/EL8)；无 walrus `:=`、无 `match/case`、无 `capture_output=`；`hashlib usedforsecurity` try/except 回退；`certbot<5` 版本 pin (Python<3.10 兼容)。
  **Platform compatibility** — `missing_ok=True` → try/except (Python 3.6 EL7/EL8); no walrus `:=`, no `match/case`, no `capture_output=`; `hashlib usedforsecurity` try/except fallback; `certbot<5` version pin (Python<3.10 compat).

---

## [V3.2.5]

> **升级说明 / Upgrade note**
> V3.2.5 是 V3.2.4 之后经过 11 轮补丁的自动化与韧性强化版本。
> 核心主题：将脚本从「遇到异常→警告→放弃」升级为「遇到异常→诊断→自动修复→重试」。
> 通过对全部 507 个 `logging.warning` 的穷举审计，为 14 类 warn-and-bail 模式增加了自动修复；
> 新增短寿命证书自动检测与 timer 频率调整（适配 LE 2027/2028 47天/6天证书）、
> 续期失败 journal/email 兜底通知、组件版本全生命周期管理（Certbot snap 迁移 / Redis 版本升级 /
> WP-CLI 版本检测 / fail2ban 版本兼容）；修复了 MariaDB 调优配置「自锁」bug 和 5 处
> Nginx 配置注释行误匹配问题。
> 从 V3.2.4 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.2.5 is an automation and resilience hardening release after V3.2.4, with 11 patches.
> Core theme: upgrading the script from "warn and bail" to "diagnose, auto-fix, retry".
> An exhaustive audit of all 507 `logging.warning` calls yielded 14 warn-and-bail patterns
> with new auto-remediation; adds short-lived certificate auto-detection with dynamic timer
> frequency (for LE 2027/2028 47-day/6-day certs), journal/email fallback notification for
> renewal failures, full component lifecycle management (Certbot snap migration / Redis
> version upgrades / WP-CLI version checks / fail2ban version compat); fixes MariaDB tuning
> config "self-lock" bug and 5 Nginx config comment false-match issues.
> To upgrade from V3.2.4, replace the script and run the `update` subcommand.

---

### ✨ 新功能 / New Features

- **短寿命证书自动检测 + timer 频率动态调整 (PATCH-277)** — 读取当前证书的总有效期（Not After − Not Before），动态决定 systemd timer 的 OnCalendar 和 RandomizedDelaySec。标准 90 天证书使用每日 timer；LE 2027 年 47 天证书切换为每 8 小时；2028 年 6 天证书切换为每 4 小时。续期成功后自动检测证书寿命变化，必要时热更新 timer 频率，无需人工干预。
  **Short-lived certificate auto-detection + dynamic timer frequency (PATCH-277)** — Reads current certificate total lifetime (Not After − Not Before) and dynamically adjusts systemd timer OnCalendar and RandomizedDelaySec. Standard 90-day certs use daily timer; LE 2027 47-day certs switch to every 8 hours; 2028 6-day certs switch to every 4 hours. Auto-detects certificate lifetime changes after renewal and hot-updates timer frequency without manual intervention.

- **续期失败 journal/email 兜底通知 (PATCH-278)** — 未配置 `--notify-webhook` 时，自动安装 systemd OnFailure 服务：续期失败写入 journal（CRIT 级别）+ `logger` 写 syslog + 尝试通过 `mail` 命令发邮件给 root。确保续期失败永远不会完全静默。
  **Journal/email fallback notification for renewal failures (PATCH-278)** — When no `--notify-webhook` is configured, auto-installs a systemd OnFailure service: renewal failures are logged to journal (CRIT priority) + syslog via `logger` + email attempted via `mail(1)` to root. Ensures renewal failures are never completely silent.

- **14 类 warn-and-bail 自动修复 (PATCH-279)** — 对全部 507 个 `logging.warning` 穷举审计，为以下场景增加自动修复能力：
  **14 warn-and-bail auto-remediation patterns (PATCH-279)** — Exhaustive audit of all 507 `logging.warning` calls; auto-fix added for:

  | 场景 / Scenario | 自动修复 / Auto-fix |
  |---|---|
  | `logrotate` 未安装 (日志无限增长) | 自动安装 logrotate 包 + mkdir |
  | `curl` 未安装 (健康检查/WP-CLI 下载跳过) | 自动安装 curl |
  | MariaDB 等待超时 (后续 DB 操作全挂) | 自动 `systemctl restart` + 15 秒二次等待 (含 mysqladmin/mysql 双路径) |
  | `nginx -t` 失败 (reload 被跳过) | 捕获错误输出，自动修复 stale include / duplicate default_server（修改前自动备份 .bak279） |
  | 卸载时文件删除失败 ×9 处 | `_force_unlink()`: 失败后 `chattr -i` 清除 immutable 位再重试 |
  | `DROP DATABASE/USER` 失败 | 自动重启 DB 服务 + 3 秒等待 + 重新尝试两种认证方式 |
  | PHP-FPM 重启失败 | `php-fpm -t` 诊断：修复不存在的用户/组、kill 残留进程 |
  | Redis 启动失败 | 读 journal 诊断：端口冲突→kill 残留进程；配置错误→备份坏配置 |
  | Redis ping 无响应 | 自动 `systemctl restart` + 重新 ping 验证 |
  | MariaDB conf.d 目录不存在 | 自动创建 + `!includedir` 追加到 my.cnf |
  | Nginx 小版本升级失败 | EL: `yum clean all`+重试 / Debian: `apt --fix-broken`+`apt update`+重试 |
  | redis-cache 插件安装失败 | 追加 `--force` 重试 |
  | nginx.list 写入失败 | 自动创建父目录 + 重试 |

- **组件版本全生命周期管理 (PATCH-270)** — Certbot: snap 检测→版本门控→pip venv 迁移（6 步 EFF 官方流程）；Redis/Valkey: 版本检测→小版本升级→EL10+ Valkey 自动切换；WP-CLI: 版本检测→自动更新→SHA-512 校验；fail2ban: 版本探测→旧版兼容适配（0.11 以下）。
  **Full component lifecycle management (PATCH-270)** — Certbot: snap detection → version gating → pip venv migration (6-step EFF official procedure); Redis/Valkey: version detection → minor upgrades → EL10+ Valkey auto-switch; WP-CLI: version detection → auto-update → SHA-512 verification; fail2ban: version probing → legacy compat (below 0.11).

- **脚本分发镜像 (PATCH-271)** — `--serve-dist` 在站点 webroot 创建脚本分发目录，提供 SHA-256 哈希校验。systemd path unit 监听脚本变更自动同步，可作为 self-update 国内备源。
  **Script distribution mirror (PATCH-271)** — `--serve-dist` creates a script distribution directory under the site webroot with SHA-256 hashes. A systemd path unit watches for script changes and auto-syncs, serving as a domestic mirror for self-update.

---

### 🔒 安全增强 / Security Enhancements

- **MariaDB GPG 四级密钥容灾 (PATCH-275)** — Debian/Ubuntu 上 MariaDB 仓库 GPG 密钥导入现有 4 级容灾：① 直连 supplychain.mariadb.com + mariadb.org ② GPG keyserver（ubuntu keyserver → openpgp.org）③ 脚本内嵌 ASCII-armored 公钥 ④ 旧系统 apt-key 兜底。与 Nginx 密钥容灾对齐。
  **MariaDB GPG 4-level key fallback (PATCH-275)** — MariaDB repo GPG key import on Debian/Ubuntu now has 4 fallback levels, aligned with the existing Nginx key fallback: ① direct download from supplychain.mariadb.com + mariadb.org ② GPG keyserver (ubuntu keyserver → openpgp.org) ③ script-embedded ASCII-armored public key ④ legacy apt-key fallback.

- **APT pinning 对齐 nginx.org 官方格式 (PATCH-272)** — `/etc/apt/preferences.d/99nginx` 完全对齐 nginx.org 官方推荐格式（含 `release o=nginx`），修复原双行 `Pin:` 语法非法被 apt 忽略的问题。
  **APT pinning aligned with nginx.org official format (PATCH-272)** — `/etc/apt/preferences.d/99nginx` now fully matches the nginx.org recommended format (including `release o=nginx`), fixing the invalid dual-line `Pin:` syntax that apt silently ignored.

---

### 🐛 问题修复 / Bug Fixes

- **[PATCH-280] MariaDB 调优配置「自锁」bug** — 脚本生成的 `.cnf` 文件中说明注释 `# add a line containing '# User-modified'` 本身就包含标记字符串 `# User-modified`，导致子串匹配命中自己→调优永远被跳过→RAM 变化 / 版本升级后参数不会更新。修复：① 检测逻辑改为行级正则 `^\s*#\s*User-modified\s*$` ② 模板文字改为不含标记原文的说明。
  **MariaDB tuning config "self-lock" bug** — The generated `.cnf` file's instructional comment `# add a line containing '# User-modified'` contained the marker string itself, causing the substring check to always match → tuning perpetually skipped. Fix: ① detection changed to line-level regex ② template text reworded to not embed the literal marker.

- **[PATCH-280] Nginx 配置注释行误匹配 ×5 处** — 5 处对 Nginx 配置原文做 `"directive" in raw_content` 子串检查的代码会命中注释行（如 `# srcache_fetch ...`），导致：status 显示错误缓存模式、日志级别误判、注释行被当作 SSL block。修复：3 处改用 `_strip_nginx_comments_d5()` 剥离注释后检查；1 处增加 `startswith("#")` 跳过；模板注释文字调整。
  **Nginx config comment false-match ×5** — 5 substring `"directive" in raw_content` checks on Nginx config could match commented-out lines (e.g. `# srcache_fetch ...`), causing wrong cache mode in status, incorrect log levels, or commented lines treated as SSL blocks. Fix: 3 sites now use `_strip_nginx_comments_d5()` before checking; 1 site adds `startswith("#")` skip; template comment text adjusted.

- **[PATCH-276] 大规模异常安全加固 (270 处)** — 全脚本 `except Exception` 路径审计：补充缺失的 `logging.debug` 异常记录、修复未捕获的 `subprocess.TimeoutExpired`、确保 `finally` 块清理不因二次异常递归、修复 quiet 模式下命令失败完全静默的问题。
  **Massive exception safety sweep (270 sites)** — Full-script `except Exception` path audit: added missing `logging.debug` for exception recording, caught unhandled `subprocess.TimeoutExpired`, ensured `finally` blocks don't recurse on secondary exceptions, fixed command failures being completely silent in quiet mode.

- **[PATCH-272] EL7 EOL 优雅降级** — EL7 已于 2024-06 EOL。Certbot/PHP/MariaDB/Nginx/Redis 升级路径在 EL7 上优雅跳过并记录警告，而非因仓库不可用而报错。
  **EL7 EOL graceful degradation** — Certbot/PHP/MariaDB/Nginx/Redis upgrade paths on EL7 (EOL 2024-06) now gracefully skip with logged warnings instead of failing due to unavailable repos.

---

### 🔨 工程改进 / Engineering

- **类型注解 (PATCH-277)** — 439 个函数 100% 返回类型注解覆盖。支持 `mypy --config-file mypy.ini` 和 `pyright` 检查。
  **Type annotations (PATCH-277)** — 100% return-type annotation coverage across all 439 functions. Supports `mypy` and `pyright` checking.

- **社区最佳实践合入 (PATCH-275)** — certbot 升级后 symlink 验证（`/usr/local/bin/certbot` 实际指向）、`run_cmd` quiet 模式 stderr 兜底记录、gpg 临时 keyring 清理、certbot snap 首次安装检测优化。
  **Community best practices merge (PATCH-275)** — certbot symlink verification post-upgrade, `run_cmd` quiet-mode stderr fallback logging, gpg temporary keyring cleanup, certbot snap fresh-install detection optimization.

- `__version__` 从 `"3.2.4"` 升至 `"3.2.5"`；`__build__` 从 `"3.2.269"` 升至 `"3.2.280"`。净增约 4,054 行（36,079→40,133），PATCH-270 ~ 280 共 11 轮补丁。

---

## [V3.2.4]

> **升级说明 / Upgrade note**
> V3.2.4 是 V3.2.3 之后经过 8 轮补丁 + i18n 全面审计的稳定性与国际化强化版本。
> 新增 Nginx 动态模块加载错误自动级联修复、FastCGI PHP snippet 去重、
> CSP 安全策略现代化；完成 i18n 系统全面审计：15 个中文 key 重命名 + 英文翻译、
> 3 处硬编码中文消息修复。
> 从 V3.2.3 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.2.4 is a stability and i18n hardening release after V3.2.3, with 8 patches
> plus a comprehensive i18n audit. Adds Nginx dynamic module load error cascade
> auto-repair, FastCGI PHP snippet deduplication, modernized CSP security policy;
> completes full i18n audit: 15 Chinese-character keys renamed with English
> translations, 3 hardcoded Chinese log messages fixed.
> To upgrade from V3.2.3, replace the script and run the `update` subcommand.

---

### ✨ 新功能 / New Features

- **Nginx 动态模块加载错误级联自动修复 (PATCH-268)** — `nginx -t` 检测到动态模块加载失败（ABI 不匹配 / undefined symbol / .so 缺失）时，自动尝试重新安装模块包→失败则移除 .so→清理孤立的 `load_module` 指令和模块专属 directive，多轮迭代直至 `nginx -t` 通过。srcache 编译时使用完整 `nginx -V` 编译参数（替代 `--with-compat` 兜底），提升 ABI 兼容性。
  **Nginx dynamic module load error cascade auto-repair (PATCH-268)** — When `nginx -t` detects dynamic module load failures (ABI mismatch / undefined symbol / missing .so), automatically attempts reinstall→if that fails, removes .so→cleans orphaned `load_module` directives and module-specific directives, iterating until `nginx -t` passes. srcache compilation now uses full `nginx -V` configure arguments (replacing `--with-compat` fallback) for better ABI compatibility.

- **FastCGI PHP snippet 去重 (PATCH-267)** — 将 `location ~ \.php$` 块中重复的 5 行 fastcgi 配置提取到 `/etc/nginx/snippets/fastcgi-php.conf` snippet 文件，所有 location 块通过 `include` 引用，消除跨块配置漂移风险。卸载时自动清理 snippet 文件。
  **FastCGI PHP snippet deduplication (PATCH-267)** — Extracts repeated 5-line fastcgi configuration from `location ~ \.php$` blocks into a `/etc/nginx/snippets/fastcgi-php.conf` snippet file; all location blocks use `include` to reference it, eliminating cross-block config drift. Snippet auto-cleaned on uninstall.

- **Nginx 小版本主动升级 (PATCH-268)** — 当已安装 Nginx 满足最低版本但低于仓库最新 patch 版本时，主动执行小版本升级（如 1.28.0→1.28.1），升级后走统一验证链（`nginx -t` → 模块修复 → graceful restart）。
  **Proactive Nginx minor-version upgrades (PATCH-268)** — When installed Nginx meets the minimum version but is below the latest patch version in the repo, proactively upgrades (e.g. 1.28.0→1.28.1) followed by the unified verification chain (`nginx -t` → module repair → graceful restart).

---

### 🔒 安全增强 / Security Enhancements

- **CSP 安全策略现代化 (PATCH-268/269)** — 移除已废弃的 `X-Frame-Options` 响应头（`frame-ancestors` 完全取代）；移除已废弃的 `X-XSS-Protection`（现代浏览器已内置，该头反而可能引入 XSS 审计侧信道）；CSP 放宽为 WordPress 实用策略（允许 `'unsafe-inline'`/`'unsafe-eval'` 兼容主题/插件 + `img-src data: blob:` 兼容媒体库）；新增 `upgrade-insecure-requests` 自动升级 HTTP 子资源。
  **Modernized CSP security policy (PATCH-268/269)** — Removed deprecated `X-Frame-Options` header (superseded by `frame-ancestors`); removed deprecated `X-XSS-Protection` (built into modern browsers; the header can introduce XSS auditing side-channels); CSP relaxed to WordPress-practical policy (`'unsafe-inline'`/`'unsafe-eval'` for theme/plugin compatibility + `img-src data: blob:` for media library); added `upgrade-insecure-requests` for automatic HTTP→HTTPS sub-resource upgrade.

- **临时 Nginx 配置安全头加固 (PATCH-269)** — ACME challenge 阶段的临时 Nginx 配置现包含基本安全响应头（`X-Content-Type-Options` / `Referrer-Policy` 等），防止部署中断（SIGTERM/SIGKILL）后临时配置长期暴露无安全头的状态。
  **Security headers in temporary Nginx config (PATCH-269)** — ACME challenge phase temporary Nginx config now includes basic security headers, preventing prolonged exposure without security headers if deployment is interrupted.

---

### 🐛 问题修复 / Bug Fixes

- **[PATCH-262 FIX-P5] Debian ABI 锁定模块清理** — Debian 系统 nginx-core→nginx.org 切换后，残留的 ABI 锁定模块包（如 `libnginx-mod-*`）导致 `nginx -t` 失败。现自动检测并移除不兼容模块包。
  **Debian ABI-locked module cleanup** — After switching from Debian nginx-core to nginx.org packages, residual ABI-locked module packages caused `nginx -t` failures. Now auto-detects and removes incompatible module packages.

- **[PATCH-262 FIX-P8] logrotate postrotate 标准化** — `/etc/logrotate.d/nginx` 的 `postrotate` 指令统一为 `USR1` 信号，替代可能因 PID 文件路径差异而失效的 `kill -USR1 $(cat /run/nginx.pid)` 模式。
  **logrotate postrotate normalization** — Standardized postrotate in `/etc/logrotate.d/nginx` to USR1 signal, replacing patterns that could fail due to PID file path differences.

- **[PATCH-263 FIX-2] nginx.org 包缺失 fastcgi.conf** — AppStream `nginx-core` 包含 `fastcgi.conf`，切换到 nginx.org 后该文件可能丢失。`_ensure_fastcgi_conf()` 现在在所有 cache_mode 路径中调用，而非仅 srcache 路径。
  **Missing fastcgi.conf after nginx.org switch** — `_ensure_fastcgi_conf()` now called for all cache_mode paths, not just srcache, ensuring the file exists after switching from AppStream nginx-core.

- **[PATCH-263 FIX-5] srcache 残留 load_module 指令清理** — `_ensure_srcache_modules` 编译失败降级后，`nginx.conf` 中可能残留 `load_module` 指令导致 `nginx -t` 失败。现激进清理 + 快照回退 + 人工修复提示三级容错。
  **Residual srcache load_module directive cleanup** — After srcache compilation failure and degradation, residual `load_module` directives could cause `nginx -t` failures. Now uses aggressive cleanup + snapshot rollback + manual fix hint as three-tier fallback.

- **[PATCH-264 FIX-1] EL10 nginx 模块流禁用** — EL10 系统 `dnf module disable nginx` 避免模块流与 nginx.org 仓库冲突，与 EL8/EL9 路径对齐。
  **EL10 nginx module stream disable** — `dnf module disable nginx` on EL10 to prevent module stream conflicts with nginx.org repo, aligned with EL8/EL9 path.

- **[PATCH-265 FIX-1] EL10 `pcre-devel` 移除** — EL10+ 已移除 `pcre-devel`/`pcre1-devel`，srcache 编译依赖列表现根据 `_el_major` 条件排除，避免 `dnf install` 报错。
  **EL10 pcre-devel removal** — EL10+ removed `pcre-devel`; srcache build dependency list now conditionally excludes it based on `_el_major`.

- **[PATCH-269 FIX-3] 服务未安装状态文本** — `status` 子命令中 Nginx/PHP-FPM 未安装时显示「未安装」/「not installed」，区别于 `inactive`（已安装但未运行）。
  **Service not-installed status text** — `status` subcommand now shows "not installed" for missing Nginx/PHP-FPM, distinguishing from "inactive" (installed but stopped).

---

### 🌐 i18n 全面审计 / Comprehensive i18n Audit

- **15 个中文字符 key 重命名** — `_MESSAGES` 字典中 15 个含中文字符的 key（如 `warn_redis_安装失败_部署将继续_不含_redis`）全部重命名为 ASCII 规范命名（如 `warn_redis_install_failed_continuing_without_redis`），同步更新全部调用点。原 `en` 字段从中文改为真正的英文翻译，`zh` 字段保持不变。
  **15 Chinese-character keys renamed** — 15 `_MESSAGES` keys containing Chinese characters renamed to ASCII-only convention (e.g. `warn_redis_安装失败…` → `warn_redis_install_failed_continuing_without_redis`); all call sites updated. The `en` field replaced with actual English translation; `zh` field unchanged.

- **3 处硬编码中文 `logging.warning()` 修复** — tar 备份路径中 3 处 `logging.warning()` 绕过 `t()` 系统直接写入中文字符串（tar 错误详情 × 2、tar 归档文件变化警告 × 1），英文用户会看到纯中文消息。改为 `t()` 调用，新增 `warn_tar_error_detail` / `warn_tar_letsencrypt_error_detail` / `warn_tar_partial_files_changed` 三个双语条目。
  **3 hardcoded Chinese `logging.warning()` calls fixed** — 3 `logging.warning()` calls in the tar backup path bypassed `t()` and emitted raw Chinese strings, making them invisible to English users. Routed through `t()` with 3 new bilingual entries: `warn_tar_error_detail`, `warn_tar_letsencrypt_error_detail`, `warn_tar_partial_files_changed`.

- **`--skip-ssl` 路径设计文档补充** — `generate_http_production_config()` 的 docstring 补充说明：该函数故意不接受 `http3=` 参数，因为 HTTP/3 (QUIC) 依赖 TLS，仅在 HTTPS 路径 (`generate_https_config`) 有意义。
  **`--skip-ssl` path design documentation** — Added docstring note to `generate_http_production_config()` explaining why it intentionally omits the `http3=` parameter: HTTP/3 (QUIC) requires TLS, making it meaningful only in the HTTPS path.

---

### 🔨 工程改进 / Engineering

- **PATCH-265 下载工作流 i18n** — 下载失败时记录每个端点的具体错误原因（DNS/超时/证书/防火墙），便于运维诊断。新增 `_el_major()` 方法从 `/etc/os-release` 提取 EL 系主版本号，替代 `_is_dnf5` 代理判断。
  **PATCH-265 download workflow i18n** — Download failures now log specific error reasons per endpoint (DNS/timeout/cert/firewall) for ops diagnosis. New `_el_major()` method extracts EL major version from `/etc/os-release`, replacing `_is_dnf5` proxy detection.

- **PATCH-262 PHP 升级后清理** — 新版 PHP-FPM 启动后才清理旧版 PHP 包（保证服务连续性）；升级后验证关键扩展可加载；清除旧版字节码缓存（与新 PHP ABI 不兼容）；SELinux `httpd_cache_t` 上下文自动设置。
  **PATCH-262 post-PHP-upgrade cleanup** — Old PHP packages cleaned only after new PHP-FPM starts (service continuity); critical extensions verified post-upgrade; stale bytecode cache cleared (ABI incompatible); SELinux `httpd_cache_t` context auto-set.

- **48 条新翻译条目** — PATCH-262 ~ 269 新增的模块修复、PHP 管理、下载诊断、CSP 策略等日志消息均通过 `t()` 翻译系统提供 zh + en 双语。i18n 审计额外修正 15 + 3 = 18 条未国际化条目。
  **48 new translation entries** — All new module repair, PHP management, download diagnostics, and CSP policy messages from PATCH-262–269 go through `t()` with zh + en. i18n audit additionally fixed 15 + 3 = 18 un-internationalized entries.

- `__version__` 从 `"3.2.3"` 升至 `"3.2.4"`；`__build__` 从 `"3.2.261f"` 升至 `"3.2.269"`。净增 6946 行（29,133→36,079），PATCH-262 ~ 269 + i18n 审计共 8 轮补丁。

---

## [V3.2.3]

> **升级说明 / Upgrade note**
> V3.2.3 是 V3.2.2 之后经过 10 轮安全审计 + 51 项模式验证的安全与架构强化版本。
> 新增 PHP 自动升级管理（≥8.3 最低要求，自动升级到 8.4）、git tag 固定构建、
> 24 项安全修复（路径遍历 / 符号链接 / gzip 炸弹 / tar 注入等）、4 个统一安全入口函数。
> 从 V3.2.2 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.2.3 is a security and architecture hardening release after V3.2.2, validated through
> 10 audit rounds and 51 pattern checks. Adds automatic PHP upgrade management (≥8.3
> minimum, auto-upgrades to 8.4), git tag-pinned builds, 24 security fixes (path traversal,
> symlink attacks, gzip bombs, tar injection, etc.), and 4 unified security entry-point functions.
> To upgrade from V3.2.2, replace the script and run the `update` subcommand.

---

### ✨ 新功能 / New Features

- **PHP 自动版本管理** — 检测已安装 PHP 版本，低于 8.3 时自动升级到 8.4。EL 系列通过 EPEL + Remi 仓库 + `dnf module enable php:remi-8.4` + `dnf update php*` 原地升级；Ubuntu 通过 Ondrej PPA；Debian 通过 Sury DPA（DEB822 格式）。升级后自动迁移 `php.ini` 自定义设置（`upload_max_filesize` / `post_max_size` / `memory_limit` / `max_execution_time`），停用旧版 PHP-FPM 服务，重启新版服务。`--php-version` 参数现在也能在已装 PHP 满足最低要求时强制触发版本切换。
  **Automatic PHP version management** — Detects installed PHP version; auto-upgrades to 8.4 when below 8.3 minimum. EL via EPEL + Remi repo + `dnf module enable php:remi-8.4` + `dnf update php*`; Ubuntu via Ondrej PPA; Debian via Sury DPA (DEB822 format). Migrates custom `php.ini` settings post-upgrade, disables old PHP-FPM service, restarts new service. `--php-version` now forces version switch even when installed PHP meets minimum requirements.

- **Git tag 固定模块构建 (`_PINNED_MODULES`)** — srcache / Brotli 编译所需的 5 个 OpenResty 模块从 commit hash 改为 git tag 固定（`v0.3.4` / `v0.33` / `v0.64` / `v0.15` / `v0.33`），解决 GitHub 浅克隆拒绝 commit hash 的问题。ngx_brotli 因 v1.0.0rc（2018）在 GCC 13+ 编译失败，使用 HEAD 克隆。echo-nginx-module 升级 v0.63→v0.64。
  **Git tag-pinned module builds (`_PINNED_MODULES`)** — 5 OpenResty modules for srcache/Brotli compilation switched from commit hashes to git tags, fixing GitHub shallow clone rejection of commit hashes. ngx_brotli uses HEAD clone due to v1.0.0rc (2018) failing on GCC 13+. echo-nginx-module upgraded v0.63→v0.64.

- **PHP 版本矩阵覆盖 7 种发行版** — EL8/9 (Remi)、EL10 (原生 8.3+)、Ubuntu 22.04 (Ondrej)、Ubuntu 24.04 (原生 8.3+)、Debian 12 (Sury)、Debian 13 (原生 8.4+) 全覆盖；原生满足最低要求的发行版跳过外部仓库。
  **PHP version matrix covers 7 distros** — EL8/9 (Remi), EL10 (native 8.3+), Ubuntu 22.04 (Ondrej), Ubuntu 24.04 (native 8.3+), Debian 12 (Sury), Debian 13 (native 8.4+) fully covered; distros with native PHP ≥8.3 skip external repos.

---

### 🔒 安全增强 / Security Enhancements (PATCH-256 ~ 260, 24 项 / 24 fixes)

- **4 个统一安全入口函数** — `_safe_rmtree`（父目录白名单 + 符号链接阻断 + `.`/`..` 过滤）、`_safe_copy2`（源 + 目标双向符号链接检查）、`_safe_mkstemp`（`O_NOFOLLOW` + `fchmod` 双重保障）、`_verify_gzip_integrity`（解压前 CRC 完整性校验）。全脚本 45 处调用统一走安全入口。
  **4 unified security entry-point functions** — `_safe_rmtree` (parent whitelist + symlink block + `../` filter), `_safe_copy2` (bidirectional symlink check on src and dst), `_safe_mkstemp` (`O_NOFOLLOW` + `fchmod` dual protection), `_verify_gzip_integrity` (pre-extract CRC integrity check). All 45 call sites unified through these entry points.

- **tar 安全解压 (`_safe_extract_tar`)** — 强制使用 `--no-same-owner --no-same-permissions`、路径遍历检测（`..` / 绝对路径 / 符号链接成员过滤）、输出目录白名单、解压超时、产物验证。覆盖 WordPress / WP-CLI / Nginx 源码 / 编译产物等 6 处解压场景。
  **Secure tar extraction (`_safe_extract_tar`)** — Enforces `--no-same-owner --no-same-permissions`, path traversal detection (`..` / absolute paths / symlink member filtering), output directory whitelist, extraction timeout, and artifact verification. Covers 6 extraction sites: WordPress, WP-CLI, Nginx source, and compiled artifacts.

- **gzip 炸弹防护** — 所有 `.tar.gz` / `.sql.gz` 解压前执行 `gzip -t` 完整性校验，失败则中止。覆盖 WordPress 下载、备份恢复、WP-CLI 解压。
  **Gzip bomb protection** — All `.tar.gz` / `.sql.gz` files validated via `gzip -t` integrity check before extraction. Covers WordPress download, backup restore, and WP-CLI extraction.

- **`_safe_copy2` 目标符号链接攻击防护 (FIX-B2)** — 攻击者在目标路径预先创建符号链接→`shutil.copy2` 跟随→写入任意文件。现检查最终目标路径（含目录+basename 拼接场景）是否为符号链接。
  **`_safe_copy2` destination symlink attack prevention (FIX-B2)** — Attacker pre-creates symlink at destination → `shutil.copy2` follows → arbitrary file write. Now checks final destination path (including dir+basename join) for symlinks.

- **`shutil.rmtree` 安全替换** — 全脚本 `shutil.rmtree` 调用替换为 `_safe_rmtree`，添加父目录白名单（`/tmp` / `/var/cache` / webroot / build 等合法父目录）、根目录保护（拒绝 `/` / `/etc` / `/usr`）、`.`/`..` 遍历检测。
  **`shutil.rmtree` security replacement** — All `shutil.rmtree` calls replaced with `_safe_rmtree`; parent directory whitelist, root directory protection, and `../` traversal detection added.

- **`tempfile.mkstemp` 安全替换** — 全部替换为 `_safe_mkstemp`，强制 `O_NOFOLLOW` + 后置 `fchmod` 双重权限保障。兼容 Python 3.6（无 `opener` 参数）。
  **`tempfile.mkstemp` security replacement** — All calls replaced with `_safe_mkstemp`; enforces `O_NOFOLLOW` + post-creation `fchmod` dual permission guarantee. Python 3.6 compatible.

---

### 🐛 问题修复 / Bug Fixes

- **[PATCH-261d] clean + redeploy PHP 版本绕过** — `_all_critical_deps_present()` 仅检查 `php` 二进制是否存在，不检查版本。clean→redeploy 时 PHP 8.0 仍在→检测通过→跳过 `install_packages()`→PHP 不升级。现新增 PHP ≥8.3 版本检查（与 Nginx ≥1.26 检查对齐）。
  **clean + redeploy PHP version bypass** — `_all_critical_deps_present()` only checked if `php` binary existed, not its version. After clean→redeploy, PHP 8.0 remained→detection passed→`install_packages()` skipped→PHP stayed at 8.0. Now adds PHP ≥8.3 version check (aligned with Nginx ≥1.26 check pattern).

- **[PATCH-261e] `--php-version` 被快速跳过路径吞掉** — 用户指定 `--php-version 8.5`，已装 PHP 8.4 ≥ 8.3→`_all_critical_deps_present` 返回 True→跳过 `install_packages()`→`--php-version` 被静默忽略。现增加 `cfg.php_version` 与已装版本比对，不同时强制走安装路径。
  **`--php-version` swallowed by fast-skip path** — User specifies `--php-version 8.5` but installed PHP 8.4 ≥ 8.3→`_all_critical_deps_present` returned True→`install_packages()` skipped→`--php-version` silently ignored. Now compares `cfg.php_version` against installed version; forces install path when different.

- **[PATCH-261f] `php-redis` apt 路径版本前缀缺失** — `_redis_ensure_running` 的 apt 路径使用无版本前缀 `php-redis`，在 Ondrej PHP 并行安装环境下可能装到旧版本 PHP 的 Redis 扩展。现使用 `_detect_installed_php_version()` 构建版本化包名（如 `php8.4-redis`）。
  **`php-redis` apt path missing version prefix** — `_redis_ensure_running` apt path used unversioned `php-redis`, which could install the Redis extension for the wrong PHP version in Ondrej parallel-install environments. Now uses `_detect_installed_php_version()` to build versioned package name (e.g. `php8.4-redis`).

- **[PATCH-261b FIX-A2] `--php-version` 与已装版本相同时无谓升级** — `_determine_php_target()` 未比对已装版本，`--php-version 8.4` 在已装 8.4 时仍触发 Remi/Ondrej 仓库配置。现先比对，相同则返回空（跳过）。
  **Unnecessary upgrade when `--php-version` matches installed** — `_determine_php_target()` didn't compare against installed version; `--php-version 8.4` on PHP 8.4 still triggered repo setup. Now compares first and skips when matching.

- **[PATCH-261b FIX-A6] EL 原地升级后 PHP-FPM 未重启** — EL 系列 PHP 升级后服务名不变（`php-fpm`→`php-fpm`），`systemctl enable --now` 不会重启已运行的服务→旧 PHP 8.0 二进制继续服务。现检测同名升级场景并显式 `systemctl restart`。
  **PHP-FPM not restarted after EL in-place upgrade** — EL PHP upgrade keeps the same service name (`php-fpm`→`php-fpm`); `systemctl enable --now` doesn't restart an already-running service→old PHP 8.0 binary keeps serving. Now detects same-name upgrade and issues explicit `systemctl restart`.

- **[PATCH-261b FIX-C5] PHP 仓库配置失败时静默继续** — `_setup_php_repo` 返回 False（Remi/Ondrej 安装失败）后未将 `_php_target` 重置为空，后续 `_build_php_packages` 生成了不存在的版本化包名→安装失败。现在两条路径（EL + apt）均检查返回值并 fallback 到系统默认。
  **Silent continuation after PHP repo setup failure** — `_setup_php_repo` returning False didn't reset `_php_target` to empty; subsequent `_build_php_packages` generated non-existent versioned package names→install failure. Both paths (EL + apt) now check return value and fall back to system default.

---

### 🔨 工程改进 / Engineering

- **11 个新方法（PHP 版本管理）** — `_detect_installed_php_version` / `_determine_php_target` / `_setup_php_repo` / `_setup_php_repo_el` / `_setup_php_repo_deb` / `_setup_ondrej_ppa` / `_setup_sury_dpa` / `_build_php_packages` / `_handle_php_version_transition` / `_read_php_ini_values` / `_apply_php_ini_values`。
  **11 new methods (PHP version management)** — Full lifecycle: detect installed version, determine target, setup repos (EL/Deb dispatchers), build package lists, handle version transition with ini migration.

- **模块级常量** — `_PHP_MIN_VERSION = (8, 3)`、`_PHP_DEFAULT_VERSION = "8.4"`、`_PHP_EXTENSIONS_EL` / `_PHP_EXTENSIONS_DEB_TPL` 集中管理，未来 PHP 版本升级仅需修改常量。
  **Module-level constants** — `_PHP_MIN_VERSION`, `_PHP_DEFAULT_VERSION`, `_PHP_EXTENSIONS_EL` / `_PHP_EXTENSIONS_DEB_TPL` centralized; future PHP version bumps require only constant changes.

- **31 条新翻译条目** — 所有新增 PHP 管理、git 克隆、tar 安全检查的日志消息均通过 `t()` 翻译系统，提供 zh + en 双语。
  **31 new translation entries** — All new PHP management, git clone, and tar safety log messages go through the `t()` translation system with zh + en entries.

- `__version__` 从 `"3.2.2"` 升至 `"3.2.3"`；`__build__` 从 `"3.2.255"` 升至 `"3.2.261f"`。净增 1126 行（28,007→29,133），diff 2412 行。
- PATCH-256 ~ 261f 共 10 轮迭代 + 51 项模式验证，累计修复 24 项安全缺陷 + 6 项逻辑缺陷。

---

## [V3.2.2]

> **升级说明 / Upgrade note**
> V3.2.2 是 V3.2.1 之后经过 44 轮内部迭代 + 8 轮独立深度审计的功能与稳定性强化版本。
> 新增 HTTP/3 QUIC 支持、Redis 全页缓存（srcache）、`--no-*` 反向开关；
> 累计修复 40+ 项缺陷，涵盖崩溃安全、凭据继承、配置探测一致性、跨路径对齐等。
> 从 V3.2.1 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.2.2 is a feature and stability hardening release after V3.2.1, refined through
> 44 internal iterations plus 8 independent deep audit rounds. Adds HTTP/3 QUIC,
> Redis full-page cache (srcache), and `--no-*` reverse switches; fixes 40+ defects
> across crash safety, credential inheritance, config detection, and cross-path alignment.
> To upgrade from V3.2.1, replace the script and run the `update` subcommand.

---

### ✨ 新功能 / New Features

- **HTTP/3 QUIC 支持 (`--http3`)** — 自动探测 Nginx `http_v3` 模块，生成 QUIC `listen` 指令和 `Alt-Svc` 响应头；自动开放 UDP 443 防火墙端口（firewalld / ufw / iptables）；多站点共享 `reuseport` 避免冲突；Nginx 不支持时静默忽略。交互式向导根据 Nginx 能力自动推荐。
  **HTTP/3 QUIC support (`--http3`)** — Auto-detects Nginx `http_v3` module; generates QUIC `listen` directives and `Alt-Svc` headers; auto-opens UDP 443 firewall port; shares `reuseport` across multi-site; silently ignored when Nginx lacks support. Interactive wizard auto-recommends based on Nginx capability.

- **Redis 全页缓存 (`--cache redis`)** — 基于 srcache-nginx-module 的 Redis 全页缓存，自动编译 5 个 OpenResty 动态模块（ngx_devel_kit / set-misc / echo / redis2 / srcache），ABI 完整性预检 + 运行时 worker 存活验证；编译失败自动降级为 FastCGI 缓存；Redis 不可用时自动安装并启动，启动失败再降级；nginx-helper 插件自动适配缓存清理协议。
  **Redis full-page cache (`--cache redis`)** — srcache-nginx-module based Redis page cache; auto-compiles 5 OpenResty dynamic modules with ABI pre-check and runtime worker survival verification; auto-degrades to FastCGI on compile failure; auto-installs Redis if unavailable; nginx-helper plugin auto-adapts cache purge protocol.

- **`--no-*` 反向开关** — `update` / `enable-ssl` / `restore` 新增 `--no-redis` / `--no-optimize` / `--no-cloudflare` / `--no-http3` / `--no-allow-xmlrpc` 反向开关，显式禁用自动探测到的功能，阻止 `_apply_auto_detected_config()` 覆盖用户降级意图。
  **`--no-*` reverse switches** — New `--no-redis` / `--no-optimize` / `--no-cloudflare` / `--no-http3` / `--no-allow-xmlrpc` flags for `update`/`enable-ssl`/`restore` to explicitly disable auto-detected features.

- **跨子命令自动配置探测** — `update` / `enable-ssl` / `restore` 通过 `_apply_auto_detected_config()` 从现有 Nginx 配置和 `wp-config.php` 自动继承 `cache` / `redis` / `optimize` / `http3` / `cloudflare` / `allow_xmlrpc`，无需每次重复传参。
  **Cross-subcommand auto config detection** — `_apply_auto_detected_config()` auto-inherits settings from existing Nginx config and `wp-config.php`, eliminating the need to re-pass flags on every run.

- **FastCGI 缓存 WooCommerce 智能排除** — 检测 WooCommerce 购物车/结账/我的账户页面和会话 Cookie，自动跳过缓存，防止购物车内容串用户。
  **FastCGI cache WooCommerce smart exclusion** — Detects WooCommerce cart/checkout/my-account pages and session cookies; auto-bypasses cache to prevent cart data leaking across users.

- **FastCGI 缓存大小动态计算** — `max_size` 按系统内存分级：≤1 GB→64m，≤2 GB→128m，≤4 GB→256m，>4 GB→512m，替代原硬编码 200m。
  **Dynamic FastCGI cache sizing** — `max_size` tiered by system RAM (64m–512m), replacing hardcoded 200m.

- **交互式向导增强** — 部署向导根据系统内存自动推荐 FastCGI（<512 MB）或 Redis srcache（≥512 MB）缓存策略；更新向导支持 Redis srcache 与 FastCGI 互斥 toggle；缓存模式、HTTP/3 等选项按环境能力动态推荐。
  **Enhanced interactive wizard** — Deploy wizard auto-recommends cache strategy by RAM; update wizard supports mutually exclusive Redis srcache / FastCGI toggle; options dynamically recommended by environment capability.

---

### 🔒 安全增强 / Security Enhancements

- **EAB/Webhook 凭据移入 EnvironmentFile** — ZeroSSL EAB 凭据和 Webhook URL 从 systemd ExecStart 移至 `.env` 文件（0o600），防止 `/proc/<pid>/cmdline` 泄露。argparse `default=os.environ.get()` 透明读取。
  **EAB/webhook credentials moved to EnvironmentFile** — Moved from systemd ExecStart to `.env` file (0o600) to prevent `/proc/<pid>/cmdline` exposure. argparse `default=os.environ.get()` reads transparently.

- **继承参数校验** — `setup_systemd()` 从已有 timer 继承 email / webhook / EAB 时，执行 SiteConfig 同等格式校验（email 正则 + 长度 + `..` 检测、webhook SSRF 校验、EAB 白名单校验），拒绝恶意注入。
  **Inherited parameter validation** — Timer parameter inheritance now validates email (regex + length + `..`), webhook (SSRF check), and EAB (charset whitelist) before accepting inherited values.

- **PHP 注释感知 `define()` 检测** — `inject_wp_hardening()` / `_set_force_ssl_admin()` 排除 PHP `//` 和 `/* */` 注释中的 `define()` 调用，防止注释残留的旧常量干扰注入逻辑。
  **PHP comment-aware `define()` detection** — Excludes `define()` calls inside PHP comments from detection, preventing stale commented-out constants from interfering with injection logic.

- **Webhook 通知脚本 POSIX 兼容** — 续期失败通知脚本改用 POSIX sh 兼容语法（`case` 替代 bash `=~`），支持 Alpine / BusyBox 环境。运行时 DNS 重解析 + CDN IP 轮换安全放行 + 私有 IP 阻断。
  **Webhook notification script POSIX compatible** — Rewritten in POSIX sh (Alpine/BusyBox safe) with runtime DNS re-resolve, CDN IP rotation allowance, and private IP blocking.

- **srcache 动态模块 ABI 验证** — 编译后执行 `nginx -t` + worker 进程存活探测（两轮，含 HTTP 请求触发），检测模块与 Nginx 二进制的 ABI 不兼容，不兼容时自动回滚并降级 FastCGI。
  **srcache dynamic module ABI verification** — Post-compile `nginx -t` + two-round worker survival probe (with HTTP request trigger) detects ABI mismatch; auto-rolls back and degrades to FastCGI on mismatch.

---

### 🐛 问题修复 / Bug Fixes

- **[PATCH-165] WP-CLI 更新 + 插件版本检测** — `update` 路径新增 WP-CLI 自身更新检查；nginx-helper / redis-cache 插件区分 "已更新" 和 "已是最新版本"。
  **WP-CLI update + plugin version detection** — `update` path checks for WP-CLI self-update; plugin messages distinguish "updated" from "already latest".

- **[PATCH-186] mysqldump stderr ERROR 误判** — `mysqldump` exit 0 但 stderr 含 ERROR（如 view 依赖缺失）时原实现忽略，导致损坏的备份被保留。现标记为 partial 备份，阻止旧备份清理。
  **mysqldump stderr ERROR false negative** — `mysqldump` exit 0 with stderr ERROR (e.g. view dependency) was silently ignored. Now marked as partial backup, blocking old backup cleanup.

- **[PATCH-190] gzip 管道校验 + heredoc 解析** — 备份管道新增 gzip 退出码校验（原仅检查 mysqldump）；PHP `define()` 注入器新增 heredoc/nowdoc 字符串跳过，防止 heredoc 内容被误修改。
  **gzip pipe verification + heredoc parsing** — Backup pipeline now verifies gzip exit code (was only checking mysqldump); PHP `define()` injector skips heredoc/nowdoc strings.

- **[PATCH-191] MySQL 标识符 64 字符溢出** — `RENAME TABLE` 临时表名生成未考虑 MySQL 64 字符限制，长表名 + `_rt` + 随机后缀溢出导致 `RENAME` 失败。现截断至 45+3+16=64。
  **MySQL identifier 64-char overflow** — `RENAME TABLE` temp name exceeded 64-char MySQL limit for long table names. Now truncated to 45+3+16=64.

- **[PATCH-192] 备份增强** — `mysqldump` 新增 `--routines` / `--triggers` / `--events` 参数保留存储过程/触发器/事件；DB dump 完整性检查增加 gzip CRC 验证 + `Dump completed` 标记检测。
  **Backup enhancements** — `mysqldump` now includes `--routines`/`--triggers`/`--events`; DB dump integrity adds gzip CRC verification and `Dump completed` marker detection.

- **[PATCH-195] VIEW 迁移 + Nginx 注释剥离** — `RENAME TABLE` 原子恢复新增 VIEW 迁移支持（VIEW 不支持 `RENAME`，改用 `CREATE VIEW` + `DROP VIEW`）；Nginx 注释剥离器增加 regex location 上下文追踪，防止 `~*` 模式中的 `#` 被误剥离。
  **VIEW migration + Nginx comment strip** — Atomic `RENAME TABLE` restore now migrates VIEWs (via `CREATE`+`DROP`); Nginx comment stripper tracks regex location context to protect `#` inside `~*` patterns.

- **[PATCH-198] DISABLE_WP_CRON 错误处理** — 3 处 `_write_bytes_to_fd` 写入 `wp-config.php` 失败时原实现 fall-through 到下一分支导致双重注入。现每处失败后立即 `return`。
  **DISABLE_WP_CRON error handling** — 3 `_write_bytes_to_fd` failure sites in wp-config.php fell through to next branch causing double injection. Now each failure returns immediately.

- **[PATCH-199] select-based 管道 drain** — 备份/恢复管道的 stderr 读取从阻塞式 `pipe.read()` 改为 `select.select()` 非阻塞 drain，子进程退出时可靠检测 EOF，消除 drain 线程残留。
  **select-based pipe drain** — Backup/restore pipe stderr drain switched from blocking `pipe.read()` to `select.select()` non-blocking drain; reliably detects EOF on child exit.

- **[PATCH-200] 插件更新去重 + 凭据白名单** — `_update_managed_plugins()` 追踪已处理插件，防止下游 `_install_nginx_helper()` / `_setup_redis_cache()` 重复操作；凭据文件恢复密码增加 `_is_safe_password()` 白名单校验。
  **Plugin update dedup + credential whitelist** — Plugin tracking prevents downstream methods from re-processing; credential file password recovery validates against `_is_safe_password()`.

- **[PATCH-201] 多项安全修复** — `_safe_write_file` 新建路径增加 symlink 二次检查；`_write_mysql_defaults_file` 密码转义增加 `#!$` 特殊字符；`_in_php_comment` 提升为模块级函数消除 5 处重复。
  **Multiple safety fixes** — `_safe_write_file` adds symlink re-check for new paths; MySQL defaults file escapes `#!$` characters; `_in_php_comment` elevated to module-level eliminating 5 duplicates.

- **[PATCH-202] restore DEFINER 剥离 + 自动探测共享** — `RENAME TABLE` 恢复新增 `DEFINER` 子句剥离（防止跨服务器恢复时权限错误）；`_apply_auto_detected_config()` 提取为共享方法，`enable_ssl` / `update_config` 统一调用。
  **restore DEFINER strip + auto-detect shared** — `RENAME TABLE` restore strips `DEFINER` clauses for cross-server compatibility; `_apply_auto_detected_config()` extracted as shared method for `enable_ssl`/`update_config`.

---

### 🔍 八轮深度审计修复 (PATCH-203 ~ 208)
### 🔍 Eight-Round Deep Audit Fix (PATCH-203 ~ 208)

> 基于 build 3.2.202 的八轮系统性代码审计，累计发现并修复 17 项缺陷，净增 131 行。
> Eight rounds of systematic code audit on build 3.2.202, discovering and fixing 17 defects. Net +131 lines.

**PATCH-203 (6 项 / 6 defects)** — `_restore_post_fixup` 注释剥离统一为 `_strip_nginx_comments_d5`（提升为模块级函数）；`restore` 路径补充 `_apply_auto_detected_config()` 调用；`_detect_site_config` 中 `optimize` / `http3` 探测改用注释剥离后文本。
Unified comment stripping to module-level `_strip_nginx_comments_d5`; added missing `_apply_auto_detected_config()` to `restore` path; `optimize`/`http3` detection switched to comment-stripped text.

**PATCH-204 (5 项 / 5 defects)** — **`uninstall()` 回退 `DISABLE_WP_CRON=true`**（卸载后 WordPress cron 永久瘫痪）；srcache 降级再生补充 `_align_nginx_with_cert()`；移除冗余 cache_mode 探测块；`allow_xmlrpc` 探测改用注释剥离后文本。
**`uninstall()` reverts `DISABLE_WP_CRON=true`** (WordPress cron permanently broken after uninstall); srcache degradation regen adds `_align_nginx_with_cert()`; removes duplicate cache_mode block; `allow_xmlrpc` detection uses stripped text.

**PATCH-205 (3 项 / 3 defects)** — **`_ensure_wp_cron_constant_locked` 3 处 O_TRUNC 写入改为原子写入**（OOM Kill 导致 wp-config.php 零字节→白屏 500），新增 `_cron_atomic_write` 辅助函数（tmp+fsync+replace，避免 flock 自阻塞）；`restore` 补充 `_ensure_fastcgi_cache_dir()`；wp-config.php 首次创建改用 `_safe_write_file`。
**3 O_TRUNC writes in `_ensure_wp_cron_constant_locked` replaced with atomic writes** (OOM kill → zero-byte wp-config.php → white screen 500); new `_cron_atomic_write` helper; `restore` adds `_ensure_fastcgi_cache_dir()`; first-time wp-config.php creation uses `_safe_write_file`.

**PATCH-206 (1 项 / 1 defect)** — PATCH-204 引入回归：`allow_xmlrpc` 块提取使用 `_c.find()` 偏移量（原始文本）与 `_c_no_comments` 触发条件不一致，统一在 `_c_no_comments` 上做全部块提取。
PATCH-204 regression: `allow_xmlrpc` block extraction offset mismatch between `_c.find()` (raw text) and `_c_no_comments` trigger; unified all extraction on `_c_no_comments`.

**PATCH-207 (1 项 / 1 defect)** — **`_extract_timer_params` 新增 EnvironmentFile 解析**（PATCH-190 将凭据移至 `.env` 但继承逻辑未同步），`update`/`enable-ssl`/`restore` 重建 timer 时不再丢失 ZeroSSL EAB 和 webhook。含 systemd 双引号转义反解析。
**`_extract_timer_params` adds EnvironmentFile parsing** (PATCH-190 moved credentials to `.env` but inheritance logic not updated); `update`/`enable-ssl`/`restore` no longer lose ZeroSSL EAB and webhook when rebuilding timers.

**PATCH-208 (1 项 / 1 defect)** — `_extract_existing_deploy_params` 域名编码补充 48 字符截断 + MD5 哈希后缀，修复长域名交互式 `update`/`enable-ssl` 静默丢失继承参数。
`_extract_existing_deploy_params` adds 48-char truncation + MD5 hash suffix for domain encoding, fixing silent param loss for long domains in interactive `update`/`enable-ssl`.

---

### 🔨 工程改进 / Engineering

- **srcache 动态模块编译基础设施** — 完整的 5 模块编译流水线（`_compile_srcache_modules`）：从 Nginx `-V` 提取 configure 参数、`--with-cc-opt` 中的 `-D` 宏、依赖包自动安装、编译产物 `load_module` 注入、旧模块清理。
  **srcache dynamic module compilation infrastructure** — Full 5-module build pipeline: extracts configure args from `nginx -V`, `-D` macros from `--with-cc-opt`, auto-installs build deps, injects `load_module`, cleans stale modules.

- **Nginx 注释剥离器 (`_strip_nginx_comments_d5`)** — 逐字符扫描，尊重引号内的 `#`（保护 CSP hash 指令等），替代 6 处不一致的 `re.sub(r'#[^\n]*', '')` 正则。提升为模块级函数供 `_detect_site_config` / `_restore_post_fixup` 共用。
  **Nginx comment stripper (`_strip_nginx_comments_d5`)** — Character-by-character scanner respecting `#` inside quotes (protects CSP hash directives); replaces 6 inconsistent regex substitutions.

- **`select`-based 管道 drain 框架** — 备份/恢复的 Popen stderr 读取从阻塞式线程改为 `select.select()` 非阻塞模式，子进程退出时通过 EOF 可靠检测，消除 drain 线程残留。
  **`select`-based pipe drain framework** — Backup/restore Popen stderr reads switched from blocking threads to `select.select()` non-blocking mode with reliable EOF detection on child exit.

- **`_in_php_comment()` 模块级函数** — 从 `inject_wp_hardening` / `_set_force_ssl_admin` / `_recover_existing_db_pass` 等 5 处重复的 PHP 注释检测逻辑提取为单一实现。
  **`_in_php_comment()` module-level function** — Extracted from 5 duplicate PHP comment detection implementations.

- `__version__` 从 `"3.2.1"` 升至 `"3.2.2"`；`__build__` 从 `"3.2.164"` 升至 `"3.2.255"`。
- PATCH-165 ~ 208 共 44 轮迭代 + 8 轮独立深度审计，累计修复 40+ 项缺陷。

---

## [V3.2.1]

> **升级说明 / Upgrade note**
> V3.2.1 是 V3.2.0 之后经过 160+ 轮内部迭代的稳定性与安全性强化版本，
> 涵盖 4 轮独立安全审计修复、10+ 项关键 Bug 修复、EL10/dnf5 兼容性改进、
> 以及大量工程质量提升。从 V3.2.0 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.2.1 is a stability and security hardening release after V3.2.0, refined through
> 160+ internal iterations. It includes 4 independent security audit rounds, 10+ critical
> bug fixes, EL10/dnf5 compatibility, and extensive engineering improvements.
> To upgrade from V3.2.0, replace the script and run the `update` subcommand.

---

### ✨ 新功能 / New Features

- **外置数据库交互式向导支持** — 交互式向导新增数据库主机、Root 密码、SSL 开关、等待超时等提示，覆盖跨地域/跨 VPC 部署场景。
  **External DB interactive wizard** — Wizard now prompts for DB host, root password, SSL toggle, and wait timeout for cross-region deployments.

- **轻量级系统状态展示** — 未部署站点时 `status` 子命令展示 Nginx/PHP-FPM/MariaDB 服务状态和磁盘空间，帮助首次部署前评估环境就绪度。
  **Lightweight system status** — `status` without deployed sites shows base service health and disk space for pre-deploy assessment.

- **单站点自动域名推断** — 非 deploy 子命令在未指定 `--domain` 且仅检测到一个已部署站点时自动使用该域名，减少重复输入。
  **Single-site auto domain inference** — Non-deploy subcommands auto-select the domain when exactly one site is deployed.

- **数据库恢复原子切换** — `restore` 路径改用 `RENAME TABLE` 原子切换：先导入临时库，再单条 SQL 原子替换正式库表，中断时正式库数据完全不受影响。
  **Atomic DB restore via RENAME TABLE** — Restore imports to a temp database, then atomically swaps tables via a single `RENAME TABLE` statement. Interruption leaves the live database intact.

- **外置数据库备份重试** — 跨地域/跨 VPC 场景下 `mysqldump` 失败时自动重试最多 3 次（指数退避 5s/15s/30s），适应不稳定网络。
  **External DB backup retry** — `mysqldump` failures for external databases retry up to 3 times with exponential backoff (5s/15s/30s).

- **mysqldump 内容完整性校验** — 备份后检查 `.sql.gz` 尾部是否包含 `Dump completed` 标记，检测 OOM/磁盘满/网络中断导致的 SQL 截断。
  **mysqldump content integrity check** — Verifies `Dump completed` marker at EOF to detect truncation from OOM, disk-full, or network interruption.

- **证书 SAN 与 Nginx 对齐** — 生成 HTTPS 配置时自动读取证书 SAN，若证书不含 `www` 则从 Nginx `server_name` 移除 `www` 变体，避免 HTTPS 重定向循环。
  **Cert SAN / Nginx alignment** — HTTPS config auto-reads certificate SAN; removes `www` from `server_name` when cert lacks it, preventing redirect loops.

- **enable-ssl 前置服务检查** — `enable-ssl` 执行前检测 Nginx 和 PHP-FPM 是否运行，未运行时自动启动并诊断修复，替代原先的模糊错误提示。
  **enable-ssl service pre-check** — Verifies Nginx and PHP-FPM are running before SSL setup; auto-starts and diagnoses failures with clear messages.

- **插件更新安全回滚** — `update` 子命令升级 nginx-helper / redis-cache 插件后执行健康检查，失败时自动回滚到升级前版本并还原配置。
  **Plugin update safe rollback** — `update` performs health checks after upgrading managed plugins; auto-rolls back version and config on failure.

---

### 🔒 安全增强 / Security Enhancements

- **4 轮独立安全审计修复** — 累计修复 50+ 项审计发现，涵盖 SSRF 防护、SQL 注入纵深防御、符号链接攻击防护、进程凭据泄露、供应链安全等。
  **4 independent security audit rounds** — 50+ findings fixed across SSRF protection, SQL injection defense-in-depth, symlink attack prevention, credential leak mitigation, and supply-chain security.

- **`self-update` 双源交叉校验** — 脚本从源 A 下载后，必须从源 B 获取 SHA256 哈希进行交叉验证；任一源不可达或哈希不匹配则中止更新，防御单源投毒。
  **`self-update` cross-source verification** — Script downloaded from source A must have its SHA256 cross-verified from source B. Update aborts if cross-verification fails.

- **管理员密码环境变量传递** — `_wp_auto_install()` 改用环境变量 `_WP_ADMIN_PASS` 传递密码，替代 `/proc/<pid>/cmdline` 明文暴露的 `--admin_password` 参数。
  **Admin password via env var** — `_wp_auto_install()` passes password through `_WP_ADMIN_PASS` environment variable instead of exposing it in `/proc/<pid>/cmdline`.

- **Webhook URL SSRF 防护增强** — 强制 HTTPS 协议、拒绝内网域名后缀（`.local`/`.internal`/`.corp` 等）、IPv4-mapped IPv6 绕过检测、配置时预解析 IP + 运行时 `/16` 前缀校验。
  **Webhook SSRF hardening** — Enforces HTTPS, blocks private domain suffixes, detects IPv4-mapped IPv6 bypass, pre-resolves IP at config time with runtime `/16` prefix validation.

- **`O_NOFOLLOW` 全路径覆盖** — `_write_bytes_to_fd()`、`apply_nginx_config_safe()`、`_write_mysql_defaults_file()` 等所有原子写入路径添加 `O_NOFOLLOW`，拒绝写入符号链接目标。
  **`O_NOFOLLOW` across all write paths** — All atomic write functions now use `O_NOFOLLOW` to refuse writing through symlinks.

- **敏感 CLI 参数清洗** — `main()` 入口在 argparse 解析后立即覆盖 `sys.argv` 中的 `--db-root-pass` 和 `--zerossl-eab-hmac-key`，防止 `/proc/<pid>/cmdline` 泄露。
  **Sensitive CLI arg scrubbing** — `--db-root-pass` and `--zerossl-eab-hmac-key` values in `sys.argv` are overwritten with `<REDACTED>` immediately after parsing.

- **SQL 控制字符拦截** — `run_sql()` 入口拦截 NUL (`\x00`)、SUB (`\x1a`) 及全部 C0 控制字符（保留 `\t`/`\n`/`\r`），防止 MySQL 协议截断攻击。
  **SQL control character interception** — `run_sql()` blocks NUL, SUB, and all C0 control characters (except tab/newline/CR) to prevent MySQL protocol truncation.

- **备份路径符号链接防护** — `backup()` 和 `restore()` 拒绝符号链接指向的备份根目录和归档文件，防止路径穿越覆盖敏感文件。
  **Backup path symlink protection** — `backup()` and `restore()` refuse symlinked backup roots and archives to prevent path traversal.

- **tar 路径遍历检测** — `restore` 解压前扫描归档成员，拒绝含 `../` 路径或指向外部的符号链接成员。
  **tar path traversal detection** — `restore` scans archive members before extraction, refusing entries with `../` paths or external symlinks.

---

### 🐛 问题修复 / Bug Fixes

- **[PATCH-158 FIX-2] `restore` 数据库半导入态** — 原 `gunzip | mysql` 管道中断时数据库处于半导入态。改用临时库 + `RENAME TABLE` 原子切换，中断时正式库完全不受影响。
  **[PATCH-158 FIX-2] restore DB partial import** — Direct pipe interruption left DB in partial state. Now uses temp DB + atomic `RENAME TABLE`; live DB unaffected on interruption.

- **[PATCH-162 FIX-2] Nginx `server_name` 与证书 SAN 不一致** — 证书不含 `www` 时 Nginx 仍配置 `www` 变体，导致 HTTPS 重定向循环。现自动对齐。
  **[PATCH-162 FIX-2] Nginx server_name / cert SAN mismatch** — Nginx configured `www` variant even when cert lacked it, causing redirect loops. Now auto-aligned.

- **[PATCH-163 FIX-1] `enable-ssl` 后 WordPress URL 与证书不一致** — `siteurl`/`home` 可能设为 `https://www.domain` 但证书仅覆盖裸域名。现通过 `_https_canonical_domain()` 证书感知选择。
  **[PATCH-163 FIX-1] WordPress URL / cert domain mismatch after enable-ssl** — `siteurl`/`home` could be set to `https://www.domain` when cert only covers bare domain. Now cert-aware.

- **[PATCH-162 FIX-4] 凭据文件密码覆写为空** — `enable-ssl` / `update` 路径重写凭据文件时，`db_pass` / `db_root_pass` 可能为空，覆盖原有有效密码。现增加 `_guard_credential_fields()` 从旧文件恢复。
  **[PATCH-162 FIX-4] Credentials file password overwrite** — Credential rewrite could blank `db_pass`/`db_root_pass`. Added `_guard_credential_fields()` to recover from existing file.

- **[PATCH-164] 凭据文件 certbot 命令与证书 SAN 不一致** — 凭据文件中的手动续期命令硬编码 `-d www.domain`，但证书可能不含 `www`。现从证书 SAN 动态生成。
  **[PATCH-164] Credential file certbot command / cert SAN mismatch** — Manual renewal command in credentials file hardcoded `-d www.domain`. Now dynamically generated from cert SAN.

- **[PATCH-159 FIX-1] `ALTER USER` 成功但密码未同步到 `wp-config.php`** — 密码恢复验证失败时 `ALTER USER` 成功，但因后续 `GRANT` 失败导致函数返回 `False`，新密码未写入配置。现 `ALTER USER` 成功后立即同步。
  **[PATCH-159 FIX-1] ALTER USER success but password not synced** — ALTER USER succeeded but GRANT failure caused function to return False without writing the new password to wp-config.php. Now syncs immediately.

- **[PATCH-159 FIX-2] `systemctl enable` 后 timer 未被检测为 active** — `setup_wp_cron_timer()` 刚 `enable --now` 后 systemd 可能尚未标记 timer 为 active，导致 `_ensure_wp_cron_constant` 误将 `DISABLE_WP_CRON` 回退为 `false`。现通过运行内标志跳过竞态窗口。
  **[PATCH-159 FIX-2] Timer not detected as active after enable** — Timer marked inactive immediately after `enable --now` due to systemd activation delay. Added run-internal flag to skip race window.

- **[PATCH-161 FIX-1] 证书 SAN 解析失败时续期域名列表回退** — `openssl x509` 失败时直接使用默认域名列表，可能与实际证书不一致。现增加 `certbot certificates` 中间回退层。
  **[PATCH-161 FIX-1] Cert SAN parse failure domain list fallback** — Added `certbot certificates` as intermediate fallback when `openssl x509` fails, before defaulting to standard domain list.

- **[PATCH-161 FIX-2] `status` 证书到期时间在中文 locale 下解析失败** — `strptime("%b")` 在 `zh_CN` locale 下期望中文月份名。改用固定映射表替代，消除 locale 依赖。
  **[PATCH-161 FIX-2] Certificate expiry date parse failure under zh_CN locale** — Replaced `strptime("%b")` with fixed month mapping to eliminate locale dependency.

- **[V3.2.124 FIX-1] Redis drop-in 检测路径错误** — `_detect_site_config()` 中 `.parent.parent` 多上溯一层，导致 `object-cache.php` 路径永远不存在。修正为 `.parent`。
  **[V3.2.124 FIX-1] Redis drop-in detection path error** — `.parent.parent` overshot by one level; fixed to `.parent`.

- **[V3.2.122 FIX-1] IPv6 地址缺少方括号** — `_verify_ssl_handshake()` 传递裸 IPv6 地址给 `openssl s_client -connect`，`:443` 被误解析为 IPv6 地址的一部分。现统一加方括号。
  **[V3.2.122 FIX-1] IPv6 address missing brackets** — Bare IPv6 in `openssl s_client -connect` caused port misparse. Now wrapped in brackets.

- **[V3.2.121 FIX-2] MariaDB 版本检测误判** — `mysql --version` 输出含 `"MariaDB"` 时仍被正则匹配为 MySQL 版本号 `(15, 1)`，导致选择 MariaDB 不支持的 `caching_sha2_password` 插件。现检测 MariaDB 字样后返回 `(0, 0)` 走保守路径。
  **[V3.2.121 FIX-2] MariaDB version detection false positive** — `mysql --version` with MariaDB output matched as MySQL version `(15, 1)`, causing selection of unsupported `caching_sha2_password`. Now returns `(0, 0)` for MariaDB.

- **[P126-1] `db-optimize` timer 密码文件格式错误** — `global_root_pwd_file` 是裸密码文本而非 INI 格式，`--defaults-extra-file` 读取失败。现创建域名级专用 `.cnf` 文件。
  **[P126-1] db-optimize timer password file format** — Global password file is plaintext, not INI format. Now creates a domain-specific `.cnf` file with proper `[client]` section.

---

### 🔨 工程改进 / Engineering

- **EL10 / dnf5 全面兼容** — `_detect_is_dnf5()` 提升为实例属性，`install_packages()` / `_brotli_install_deps()` / `_compile_php_redis_extension()` 统一引用；`php-json` 仅在 PHP < 8 时追加；Redis/Valkey 多包名候选自动适配。
  **EL10 / dnf5 full compatibility** — `_detect_is_dnf5()` elevated to instance attribute; `php-json` only added for PHP < 8; Redis/Valkey multi-package candidate auto-selection.

- **密码字符集白名单单一事实来源** — `_RE_SAFE_PASSWORD` / `_is_safe_password()` / `_generate_secure_password()` 提取为模块级函数，替代 7 处重复的 `re.fullmatch` 和 3 处重复的 `secrets.choice` 循环。
  **Password charset whitelist single source of truth** — `_is_safe_password()` / `_generate_secure_password()` extracted as module-level functions, replacing 7 duplicate regex checks and 3 duplicate generation loops.

- **共享转义/反转义工具** — `_escape_single_quoted()` / `_escape_double_quoted()` / `_unescape_single_quoted()` 从 6 处内联 `.replace()` 链提取，统一反斜杠优先处理顺序。
  **Shared escape/unescape utilities** — Extracted from 6 inline `.replace()` chains with unified backslash-first processing order.

- **`_write_bytes_to_fd()` 底层统一** — 从 `_write_lang_file` / `_safe_write_file` / `atomic_write` 三处重复的 fd 操作模式提取为单一实现，含 `O_NOFOLLOW` + `fchmod` + `fsync`。
  **`_write_bytes_to_fd()` unified primitive** — Extracted from 3 duplicate fd operation patterns into single implementation with `O_NOFOLLOW` + `fchmod` + `fsync`.

- **`_encode_domain_id()` 共享编码** — `SiteConfig.__init__` 和 `_nginx_safe_name()` 的域名编码逻辑合并为单一函数，消除两处独立维护的编码规则分歧风险。
  **`_encode_domain_id()` shared encoding** — Domain encoding logic from `SiteConfig.__init__` and `_nginx_safe_name()` merged into single function.

- **`_run_subcommand()` 统一框架** — 所有子命令（含 deploy/renew）统一走 `setup_signals → acquire_lock → operation → rollback → cleanup` 框架，消除 `run()` 方法的平行错误处理路径。
  **`_run_subcommand()` unified framework** — All subcommands (including deploy/renew) now use the unified signal → lock → operation → rollback → cleanup framework. Legacy `run()` method removed.

- **`_install_systemd_timer()` 通用方法** — `setup_systemd()` / `setup_wp_cron_timer()` / `setup_db_optimize_timer()` 三处重复的 `atomic_write → daemon-reload → enable --now` 尾部逻辑提取为单一方法。
  **`_install_systemd_timer()` generic method** — Extracted duplicate `atomic_write → daemon-reload → enable --now` tail logic from 3 timer setup methods.

- **`_fetch_wp_version()` 合并** — 原 `_fetch_wp_latest_version` / `_fetch_wp_zh_version` 两个 90% 重复的方法合并为参数化单一实现。
  **`_fetch_wp_version()` merged** — Two 90%-duplicate version fetch methods merged into single parameterized implementation.

- **`_try_issue_ecc_with_rsa_fallback()` 共享** — `apply_cert()` 和 `renew_cert()` 的 ECC→RSA 逐 CA 降级逻辑提取为独立方法。
  **`_try_issue_ecc_with_rsa_fallback()` shared** — ECC→RSA per-CA fallback logic extracted from `apply_cert()` and `renew_cert()`.

- **`_pre_backup()` 统一** — `enable_ssl` / `update_config` / `restore` 三处 pre-backup 逻辑统一为单一方法，含 `_exit_code` 隔离保护。
  **`_pre_backup()` unified** — Pre-backup logic from 3 subcommands unified with `_exit_code` isolation.

- **SiteConfig 属性提取** — `credentials_file` / `le_live_dir` / `le_archive_dir` / `le_renewal_conf` 提升为 `@property`，消除 15+ 处硬编码路径拼接。
  **SiteConfig property extraction** — `credentials_file` / `le_live_dir` / `le_archive_dir` / `le_renewal_conf` elevated to `@property`, eliminating 15+ hardcoded path concatenations.

- **GIL 禁用运行时检测** — 检测 `sys._is_gil_enabled()` (PEP 703)，GIL 禁用时跳过无锁快速路径，确保 `_is_china_cloud` / `_detect_nginx_http2_directive` 双重检查锁的正确性。
  **GIL-disabled runtime detection** — Checks `sys._is_gil_enabled()` (PEP 703); skips lock-free fast paths when GIL is disabled.

- **版本轻量检查频率限制** — `_lightweight_version_check()` 通过时间戳文件限制为每 7 天最多一次，避免 systemd timer 每日 renew 时重复 HTTP 请求。
  **Version check rate limiting** — `_lightweight_version_check()` limited to once per 7 days via timestamp file.

---

### Internal 内部

- `__version__` 从 `"3.2.0"` 升至 `"3.2.1"`；`__build__` 升至 `"3.2.164"`。
- `concurrent.futures` 替换为 `threading.Thread`（单个 stderr drain 不值得线程池开销）。
- `typing.Optional` 直接导入，移除 Python 3.6 fallback 死代码。
- 备份校验增加 DB dump 期望存在性检查：外置 DB 因密码不可用导致 dump 跳过时不清理旧备份。
- `_nginx_reset_conflicting_conf()` 增加成对冲突检测和 `nginx.conf` 自身错误预检。
- `_ensure_wp_cron_constant()` 增加旁路锁文件 `flock` 保护 read-modify-write 周期。
- `certbot` 锁等待改用 `LOCK_NB` 轮询 + 指数退避 + 随机抖动，替代无超时 `LOCK_EX`。
- `_do_self_update()` 语法校验 (`compile()`) 在版本比较和 SHA256 校验之后执行。
- `show_status()` 证书到期时间转换为本地时区并按语言格式化显示。
- `_detect_existing_sites()` 增加 5 秒进程内缓存，消除交互向导重复扫描开销。
- 日志脱敏：`_log_journal_tail()` 替换含密码的日志字段；`_SENSITIVE_CLI_ARGS` 清洗 `sys.argv`。

## [V3.2.0]

> **升级说明 / Upgrade note**
> V3.2.0 是自 V3.1.1 以来的重大功能更新，内部经过 60+ 轮迭代打磨，涵盖新功能、安全增强、
> Bug 修复和工程质量改进。从 V3.1.x 升级时，直接替换脚本文件并执行 `update` 子命令即可，
> 所有新配置（Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers）将自动重建。
>
> V3.2.0 is a major feature update since V3.1.1, refined through 60+ internal iterations.
> To upgrade from V3.1.x, replace the script and run the `update` subcommand.
> All new configs (Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers) rebuild automatically.

---

### ✨ 新功能 / New Features

- **交互式向导 / Interactive wizard** — 未指定子命令时自动进入 TTY 交互向导（非 TTY 打印帮助）。通过菜单引导用户完成域名、邮箱、SSL 策略选择，降低首次使用门槛。
  When no subcommand is given, TTY users enter an interactive wizard that guides domain, email, and SSL policy selection. Non-TTY prints help.

- **两阶段部署：`deploy --skip-ssl` + `enable-ssl`** — 新增 `--skip-ssl` 标志跳过 SSL 签发，生成完整 HTTP 生产配置；后续通过新子命令 `enable-ssl` 随时补签证书并自动切换至 HTTPS（含 `FORCE_SSL_ADMIN` 恢复、siteurl/home 更新）。适用于 DNS 尚未生效或需分步验证的场景。
  **Two-phase deployment: `deploy --skip-ssl` + `enable-ssl`** — New `--skip-ssl` flag generates full HTTP production config. New `enable-ssl` subcommand signs the certificate and switches to HTTPS on demand.

- **ZeroSSL 备用 CA 与自动 EAB 协商** — 通过 `--zerossl-eab-kid` / `--zerossl-eab-hmac-key` 或提供 `--email` 自动调用 ZeroSSL API 获取 EAB 凭据。Let's Encrypt 签发失败后自动 fallback 到 ZeroSSL，再失败则尝试 BuyPass Go（国内 DNS 不可达时已移除）。Certbot 错误分类引擎区分致命/可重试/非 CA 侧错误，非 CA 侧错误（端口占用、DNS 未解析、webroot 不可达）立即熔断跳出 CA 循环。
  **ZeroSSL backup CA with automatic EAB negotiation** — Provides EAB credentials via CLI flags or auto-fetches them from ZeroSSL API using `--email`. Automatic fallback chain: Let's Encrypt → ZeroSSL → (BuyPass Go, removed for China DNS issues). Certbot error classifier distinguishes fatal/retryable/non-CA-side errors; non-CA-side errors (port conflict, DNS failure, webroot unreachable) break out of the CA loop immediately.

- **多语言支持 (i18n)** — 200+ 条消息全量双语化（中/英）。优先级：`--lang` CLI 参数 > 持久配置文件 `/root/.wp_ssl_lang` > `WP_LANG` 环境变量 > 系统 `LANG`。首次指定后自动持久化，后续无需重复。
  **Internationalization (i18n)** — 200+ messages fully bilingual (zh/en). Priority: `--lang` CLI > persisted config > `WP_LANG` env > system `LANG`. Auto-persisted on first use.

- **域名智能归一化** — 输入 `www.example.com` 时自动剥离前缀归一为 `example.com`，`www` 作为别名自动添加到 certbot `-d` 列表。子域名（如 `blog.example.com`）自动识别并跳过 `www` 变体，避免 DNS 验证失败。
  **Smart domain normalization** — `www.example.com` input auto-normalized to `example.com`; `www` added as certbot alias. Subdomains (e.g. `blog.example.com`) detected and skip `www` variant to avoid DNS validation failure.

- **国内云检测扩展** — 新增天翼云、京东云、火山引擎、UCloud、百度云、金山云识别（DMI sysfs + 厂商专有元数据端点），自动切换国内 WordPress 下载源和 certbot 镜像。
  **Expanded China cloud detection** — Added CTYun, JD Cloud, Volcengine, UCloud, Baidu Cloud, Kingsoft Cloud detection (DMI sysfs + vendor-specific metadata endpoints). Auto-switches to China WordPress and certbot mirrors.

- **PHP Redis 扩展源码编译兜底** — 预编译包 `php-redis` 不可用时，自动通过 PECL 或源码编译安装 `phpredis`，确保 `--redis` 在所有发行版上可用。
  **PHP Redis extension source compilation fallback** — When `php-redis` packages are unavailable, auto-compiles from PECL/source to ensure `--redis` works on all distros.

- **dnf5 兼容 (EL10+)** — 自动检测 EL10+ 的 dnf5 包管理器，调整模块安装命令（`dnf5 module` 语法差异），支持 RHEL 10 / Fedora 41+ 等新一代发行版。
  **dnf5 compatibility (EL10+)** — Auto-detects dnf5 package manager on EL10+, adapts module install commands for RHEL 10 / Fedora 41+.

---

### 🔒 安全增强 / Security Enhancements

- **HTTP/HTTPS 公共安全响应头统一** — 将安全头（CSP / nosniff / Referrer-Policy / Permissions-Policy）提取为共享函数，HTTP 和 HTTPS 配置均调用。HTTP 配置不含 HSTS，HTTPS 配置追加 HSTS + `frame-ancestors`。消除原 HTTP-only 部署无安全头的盲区。
  **Unified security headers for HTTP/HTTPS** — Security headers extracted into a shared function called by both HTTP and HTTPS configs. Eliminates the gap where HTTP-only deployments had no security headers.

- **MySQL 密码文件 `fsync` 落盘** — `run_sql()` 创建的 `--defaults-extra-file` 临时密码文件和 `_wp_auto_install()` 追加的凭据文件在 `os.write()` 后补充 `os.fsync()`，防止断电后密码文件截断或空白。
  **MySQL password file `fsync`** — Temporary password files and credential files now `fsync()` after write, preventing truncation on power loss.

- **Nginx 配置原子写入 + 精确权限** — `apply_nginx_config_safe()` 从 `write_text()` 改为 `os.open(O_CREAT|O_TRUNC, 0o644)` + `os.fsync()` + `os.replace()` 原子替换，消除 umask 依赖和断电数据丢失风险。
  **Nginx config atomic write + precise permissions** — `apply_nginx_config_safe()` switched from `write_text()` to `os.open()` with explicit `0o644` mode + `fsync` + atomic `os.replace()`.

---

### 🐛 问题修复 / Bug Fixes

- **[Bug-1] `restore` 路径 WP-CLI 缺失** — 恢复后 `setup_wp_cron_timer()` 总是降级到 PHP fallback（因从未调用 `_ensure_wpcli()`），已修复。
  **[Bug-1] restore path missing `_ensure_wpcli()`** — WP-Cron timer always fell back to PHP after restore. Fixed.

- **[Bug-2] `restore` 路径 certbot deploy hook 缺失** — HTTPS 站点恢复后 certbot deploy hook 丢失，证书续期后 Nginx 不会自动 reload，已修复。
  **[Bug-2] restore path missing `_install_certbot_deploy_hook()`** — Certbot deploy hook lost after HTTPS site restore. Fixed.

- **[Bug-3] `uninstall()` 双重 `cleanup_and_exit()`** — 方法内部调用 `cleanup_and_exit(0)` 与 `main()` 的 `finally` 块重复，已移除内部调用，与其他子命令统一。
  **[Bug-3] `uninstall()` double `cleanup_and_exit()`** — Removed redundant internal call; cleanup now handled uniformly by `main()` finally block.

- **[Bug-4] `enable-ssl` 缺少 `--wp-auto-install`** — `deploy` 和 `update` 均支持此参数但 `enable-ssl` 遗漏。已补齐 argparser 定义和方法调用。
  **[Bug-4] `enable-ssl` missing `--wp-auto-install`** — Added to argparser and method body, consistent with `deploy` and `update`.

- **[Bug-5] `restore` 路径 `--redis` 无效** — `restore` 子命令接受 `--redis` 参数但 `_restore_post_fixup()` 从未调用 `_setup_redis_cache()`，已修复。
  **[Bug-5] restore path `--redis` flag ineffective** — `_setup_redis_cache()` was never called in `_restore_post_fixup()`. Fixed.

- **[Bug-6] `enable-ssl` 中 `_wp_auto_install()` 排序错误** — 健康检查在自动安装之前执行，产生误导性日志。已移至 `verify_site_health()` 之前，与 `deploy` 路径一致。
  **[Bug-6] `enable-ssl` `_wp_auto_install()` ordering** — Health checks ran before auto-install, producing misleading logs. Moved before `verify_site_health()`, consistent with `deploy` path.

- **`enable-ssl` 后续步骤完整性** — `enable-ssl` 成功后缺少 Fail2Ban、logrotate、nginx-helper、Redis 缓存等配置步骤，已与 `deploy` HTTPS 路径完全对齐。
  **`enable-ssl` post-setup completeness** — Missing Fail2Ban, logrotate, nginx-helper, Redis setup after `enable-ssl` success. Now fully aligned with `deploy` HTTPS path.

- **`wp-config.php` salt 注入 off-by-one** — `inject_salts()` 中 `rfind()` 返回 0（`require` 行在文件开头）时被误判为未找到，salt 注入失败。已修正判断条件。
  **`wp-config.php` salt injection off-by-one** — `rfind()` returning 0 (require at file start) was misinterpreted as not-found. Fixed.

- **Certbot 错误正则误匹配** — `"port 80"` 会误匹配 `"port 8080"`、`"404"` 会误匹配 `"4048"` 等端口号。已改用全词匹配正则。
  **Certbot error regex false positives** — `"port 80"` matched `"port 8080"`, `"404"` matched `"4048"`. Fixed with word-boundary regex.

---

### 🔨 工程改进 / Engineering

- **大型方法拆分** — `setup_lemp_and_wp()`、`backup()`、`restore()`、`download_and_verify_wordpress()`、`enable_ssl()` 等拆分为多个职责单一的子方法，提升可读性和可测试性。
  **Large method decomposition** — `setup_lemp_and_wp()`, `backup()`, `restore()`, `download_and_verify_wordpress()`, `enable_ssl()` split into focused sub-methods.

- **跨路径一致性审计** — 系统对比 `deploy`（HTTP/HTTPS）、`enable-ssl`、`update`、`restore` 五条路径的后置步骤序列，确保 `_ensure_wpcli` / `_install_certbot_deploy_hook` / `_setup_redis_cache` / `_wp_auto_install` 排序和完整性一致。
  **Cross-path consistency audit** — Systematic comparison of post-setup step sequences across all 5 command paths, ensuring consistent ordering and completeness.

- **线程安全缓存** — `_is_china_cloud()` 和 `_detect_nginx_http2_directive()` 的结果缓存加入 `threading.Lock` + 双重检查锁，防止未来多线程调用时数据竞争。
  **Thread-safe caching** — `_is_china_cloud()` and `_detect_nginx_http2_directive()` caches protected with `threading.Lock` + double-checked locking.

- **常量/路径重构** — 全局锁文件、MySQL 临时凭据目录、certbot 锁超时等硬编码值提升为类级常量（`_GLOBAL_LOCK_FILE`、`_MYSQL_TMP_DIR`、`_CERTBOT_LOCK_TIMEOUT`），统一管理。
  **Constants/paths refactored** — Hardcoded values (lock files, temp dirs, timeouts) elevated to class-level constants for centralized management.

- **`subprocess` 编码统一** — 全量清理，所有 `subprocess.run()` / `Popen()` 统一使用 `encoding='utf-8', errors='replace'`，消除非 UTF-8 locale 下的 `UnicodeDecodeError` 风险。
  **`subprocess` encoding standardization** — All `subprocess` calls unified to `encoding='utf-8', errors='replace'`, eliminating `UnicodeDecodeError` risk under non-UTF-8 locales.

- **`_sd_escape()` 提升为模块级函数** — 原为 `setup_wp_cron_timer()` 内嵌函数，导致 `setup_systemd()` 无法访问，systemd `ExecStart` 路径中的 `%` / `$` 字符未转义。
  **`_sd_escape()` elevated to module-level** — Previously nested inside `setup_wp_cron_timer()`, making it inaccessible to `setup_systemd()`. Systemd `ExecStart` paths now properly escape `%` / `$` characters.

- 版本号 `__version__` 从 `"3.1.1"` 升至 `"3.2.0"`。

---

## [V3.1.1]

> **升级说明 / Upgrade note**
> V3.1.1 是基于外部安全审计报告的专项修复版本，涵盖 10 项审计发现（2 高 / 4 中 / 4 低）
> 及 3 项审计后复查修复。从 V3.1.0 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.1.1 is a security-focused release addressing all 10 findings from an external security audit
> (2 high / 4 medium / 4 low) plus 3 post-audit review fixes.
> To upgrade from V3.1.0, replace the script and run the `update` subcommand.

---

### 🔴 高优先级修复 / High Priority Fixes

- **[Issue 1] Certbot deploy-hook 绝对路径 + 持久化 renewal hook** — `renew_cert()` 的 `--deploy-hook` 从裸命令 `nginx` / `systemctl` 改为绝对路径 `/usr/sbin/nginx` / `/bin/systemctl`，修复 Snap confinement 环境下 PATH 受限导致 hook 静默失败的问题。新增 `_install_certbot_deploy_hook()` 方法，在 deploy 和 update 时写入 `/etc/letsencrypt/renewal-hooks/deploy/01-reload-nginx.sh`，确保无论由脚本 timer 还是 certbot 自身 timer 触发续期，Nginx 均能可靠 reload。
  **Certbot deploy-hook absolute paths + persistent renewal hook** — Fixed silent hook failure in Snap confinement by using absolute paths. New `_install_certbot_deploy_hook()` writes a persistent shell hook to `/etc/letsencrypt/renewal-hooks/deploy/`, ensuring Nginx reload works regardless of which timer triggers renewal.

- **[Issue 2] CSP 从 Report-Only 升级为 enforcement 模式** — `Content-Security-Policy-Report-Only` 改为 `Content-Security-Policy`。原 Report-Only 模式缺少 `report-uri` 端点，浏览器检测到违规后报告静默丢弃，监控完全失效。
  **CSP upgraded from Report-Only to enforcement** — `Content-Security-Policy-Report-Only` changed to `Content-Security-Policy`. The Report-Only mode had no `report-uri` endpoint, making violation reports silently discarded.

---

### 🟡 中优先级修复 / Medium Priority Fixes

- **[Issue 3] `admin-ajax.php` 速率限制** — 新增 `limit_req_zone wpadmin_{safe}:10m rate=10r/s` 及独立 `location = /wp-admin/admin-ajax.php` 块（`burst=20 nodelay`），封堵此前未受保护的高频 DoS 攻击面。
  **`admin-ajax.php` rate limiting** — New rate limit zone and dedicated location block protect this previously unguarded high-frequency endpoint.

- **[Issue 4] Fail2Ban 封禁时间 1h → 24h + 渐进式封禁** — `bantime` 从 `3600` 提升至 `86400`，启用 `bantime.increment = true` 和 `bantime.rndtime = 1800`，对持续性攻击者实施递增封禁。
  **Fail2Ban ban duration 1h → 24h + progressive banning** — Enables `bantime.increment` for escalating bans against persistent attackers.

- **[Issue 5] FastCGI `cache_lock` 防惊群** — 在 `_nginx_php_location()` 的 FastCGI 缓存指令块中新增 `fastcgi_cache_lock on` 和 `fastcgi_cache_lock_timeout 5s`，防止高并发下同一缓存 key 过期时多个请求同时穿透到 PHP-FPM。
  **FastCGI `cache_lock` anti-stampede** — Prevents multiple concurrent requests from hitting PHP-FPM when the same cache key expires simultaneously.

- **[Issue 6] MariaDB 重启后等待就绪** — `_tune_mariadb()` 中 `systemctl restart` 之后补充 `self._wait_db_ready()` 调用，消除后续 SQL 操作在数据库尚未就绪时失败的竞态条件。
  **MariaDB restart wait-for-ready** — Added `_wait_db_ready()` call after `systemctl restart` in `_tune_mariadb()`, eliminating race condition with subsequent SQL operations.

---

### 🟢 低优先级修复 / Low Priority Fixes

- **[Issue 7] `X-Permitted-Cross-Domain-Policies` 安全响应头** — 在 `_nginx_security_headers()` 和字体 location 的安全头重声明块中新增 `add_header X-Permitted-Cross-Domain-Policies "none" always`，补全 OWASP 推荐的标准安全头集合。
  **`X-Permitted-Cross-Domain-Policies` header** — Added to both server-level and font location security headers, completing the OWASP-recommended header set.

- **[Issue 8] `self-update` 强制 SHA-256 校验** — 校验文件获取失败时从 `logging.warning` + 继续更新 改为 `logging.error` + 中止更新，防止 DNS 劫持 / CDN 入侵场景下未校验的恶意脚本以 root 执行。
  **`self-update` mandatory SHA-256 verification** — Hash fetch failure now aborts the update instead of proceeding without verification, preventing supply-chain attacks.

- **[Issue 9] HTTP 请求方法过滤** — 在 `_nginx_ssl_core()` 中新增 `if ($request_method !~ ^(GET|POST|HEAD|OPTIONS)$) { return 444; }`，封锁 `DELETE` / `PUT` / `TRACE` 等 WordPress 不需要的方法（WordPress REST API 通过 POST + `_method` 隧道化）。保留 `OPTIONS` 以支持 CORS preflight。
  **HTTP method filtering** — Blocks non-standard methods with Nginx's connection-drop `444`. `OPTIONS` retained for CORS preflight; WordPress REST API tunnels `PUT`/`DELETE` via POST.

- **[Issue 10] `wp-includes/*.php` 直接访问拦截** — 新增 `location ~* /wp-includes/.*\.php$ { deny all; }`，阻止攻击者直接执行 `wp-includes/` 下的 PHP 文件。通过独立的精确匹配 location 保留 `wp-includes/ms-files.php`（WordPress Multisite 媒体文件服务所需），并包含完整的 `fastcgi_pass` 指令确保 PHP 正常执行。
  **`wp-includes/*.php` direct access deny** — Blocks direct PHP execution in `wp-includes/` while preserving `ms-files.php` for WordPress Multisite media serving via a dedicated exact-match location with full `fastcgi_pass` directives.

---

### 🔨 审计后复查修复 / Post-Audit Review Fixes

- **[Fix A] HTTP 方法过滤补充 `OPTIONS`** — 原始审计建议仅允许 `GET|POST|HEAD`，复查发现缺少 `OPTIONS` 会阻断浏览器 CORS preflight 请求，导致跨域 REST API 调用和 Gutenberg 编辑器在 CDN 场景下静默失败。
  **HTTP method filter adds `OPTIONS`** — Original audit omitted `OPTIONS`, which would break browser CORS preflight requests for cross-origin REST API calls and Gutenberg editor behind CDN.

- **[Fix B+C] `wp-includes` 拦截规则的 `ms-files.php` 异常处理** — 初始实现使用嵌套 location `{ allow all; }`，缺少 `fastcgi_pass` 导致 Nginx 无法将 ms-files.php 作为 PHP 执行。重构为两个同级 location：精确匹配 `location =`（含完整 FastCGI 指令）+ 正则 deny，利用 Nginx `=` 优先级高于 `~*` 的规则确保正确路由。
  **`ms-files.php` exception restructured with PHP processing** — Initial nested location lacked `fastcgi_pass`. Restructured as sibling locations: exact-match with full FastCGI directives + regex deny. Nginx `=` priority over `~*` ensures correct routing.

---

### Internal 内部

- 新增 i18n 键：`err_self_update_hash_unavailable`（Issue 8 强制校验错误）、`info_certbot_deploy_hook`（Issue 1 hook 安装确认）。
- `_nginx_wp_security()` 函数签名不变，内部新增 admin-ajax、wp-includes 两个 location 块。
- `_nginx_preamble()` 新增 `wpadmin_{safe}` rate limit zone，与现有 `wplogin_{safe}` / `xmlrpc_{safe}` 保持一致的命名规范。
- 版本号 `__version__` 从 `"3.1.0"` 升至 `"3.1.1"`。

---

### 🔧 维护修复 / Maintenance Fixes

> 以下修复在安全审计发布后基于代码复查及同类工具最佳实践调研追加，统一纳入 V3.1.1。
> The following fixes were added post-audit during code review and best-practice research, consolidated under V3.1.1.

- **[P1] Certbot deploy hook 绝对路径改为运行时探测** — Issue 1 的初始修复将 `nginx` / `systemctl` 替换为硬编码的 `/usr/sbin/nginx` / `/bin/systemctl`。进一步改为在 `SiteConfig.__init__` 通过 `shutil.which()` 探测实际路径并缓存（`self.nginx_bin` / `self.systemctl_bin`），hook 脚本写入时使用缓存值。硬编码路径在 OpenSUSE（`/usr/bin/nginx`）等非标布局发行版上会静默失败。
  **Certbot deploy hook: hardcoded paths → runtime detection** — Initial Issue 1 fix used hardcoded `/usr/sbin/nginx` / `/bin/systemctl`. Now detected via `shutil.which()` at `SiteConfig.__init__` (cached as `nginx_bin` / `systemctl_bin`). Hardcoded paths fail silently on non-standard distros (e.g. OpenSUSE uses `/usr/bin/nginx`).

- **[P2] 移除 `renew_cert()` 内联 `--deploy-hook` 防双重 reload** — `renew_cert()` 原有 `--certbot … --deploy-hook "nginx -t && systemctl reload nginx"` 与 Issue 1 新写入的持久 `renewal-hooks/deploy/01-reload-nginx.sh` 构成双重触发：certbot 续期成功后先执行持久 hook、再执行内联 hook，nginx 被无谓 reload 两次。已移除内联参数，统一由持久 hook 负责。
  **Remove inline `--deploy-hook` in `renew_cert()` to prevent double reload** — The inline `--deploy-hook` and the persistent `renewal-hooks/deploy/` hook (Issue 1) both fired on renewal, causing two consecutive nginx reloads. Inline parameter removed; persistent hook is now the sole reload trigger.

- **[P3] 升级边界：`renew_cert()` 开头确保持久 hook 存在** — 从旧版本升级后若直接执行 `renew` 而未执行 `update`/`deploy`，持久 hook 文件尚未写入，续期成功后 nginx 不会 reload，证书虽已更新但服务仍使用旧证书。`renew_cert()` 开头补调 `_install_certbot_deploy_hook()`，幂等、低开销，彻底消除此升级边界。
  **Upgrade boundary: ensure persistent hook exists at `renew_cert()` start** — Upgrading from older versions and running `renew` before `update`/`deploy` left the persistent hook absent: renewal succeeded but nginx kept serving the old certificate. Added `_install_certbot_deploy_hook()` call at the top of `renew_cert()` (idempotent, low overhead).

- **[P7] `setup_db_optimize_timer()` 中 `mysqlcheck` 改用绝对路径** — systemd 单元 `ExecStart` 的默认 PATH 仅为 `/usr/bin:/bin`，某些发行版将 `mysqlcheck` 安装在 `/usr/local/bin`。在 `SiteConfig.__init__` 通过 `shutil.which("mysqlcheck")` 探测并缓存为 `self.mysqlcheck_bin`，写入 service 文件的两个分支（有/无密码文件）均替换为绝对路径，保持与 P1 相同的严谨度。
  **`setup_db_optimize_timer()`: `mysqlcheck` absolute path** — systemd unit `ExecStart` uses a narrow default PATH. Some distros place `mysqlcheck` in `/usr/local/bin`. Detected via `shutil.which()` at `SiteConfig.__init__` (cached as `mysqlcheck_bin`); both exec branches (with/without password file) now write the absolute path into the service unit.

- **[P8] 移除 `_nginx_security_headers()` 中冗余的 `X-Frame-Options`** — `X-Frame-Options: SAMEORIGIN` 与 CSP `frame-ancestors 'self'` 功能完全等价；现代浏览器（Chrome 40+、Firefox 33+、Safari 10.1+）优先采用 CSP 策略。同时保留两者不会出错，但在需要调整 iframe 策略（如 Elementor 预览）时须两处同步修改，增加维护负担。已移除 `X-Frame-Options` 行，保留 CSP `frame-ancestors`。如需兼容 IE11 及以下可手动恢复。
  **Remove redundant `X-Frame-Options` from `_nginx_security_headers()`** — `X-Frame-Options: SAMEORIGIN` is functionally equivalent to `frame-ancestors 'self'` in CSP; modern browsers prioritize CSP. Keeping both creates dual maintenance points (e.g. for Elementor iframe preview). `X-Frame-Options` line removed; CSP `frame-ancestors` retained. Restore manually if IE11 compatibility is required.

- **[P9] 禁用 OCSP Stapling（Let's Encrypt 2025-08-06 关停服务）** ★ — Let's Encrypt 于 2025-05-07 起不再在新签发证书中内嵌 OCSP URL，2025-08-06 完全关停 OCSP 响应服务。`_nginx_ssl_params()` 中保留 `ssl_stapling on` 将产生 `nginx: [warn] "ssl_stapling" ignored, no OCSP responder URL` 日志，在 resolver 无响应时还可能阻塞 `nginx reload`。已注释 `ssl_stapling on/off`、`ssl_stapling_verify`、`resolver`、`resolver_timeout` 四行，保留原文便于追溯。证书吊销验证职责已由 LE 转移至客户端 CRL 机制。
  **Disable OCSP Stapling (Let's Encrypt retired service 2025-08-06)** ★ — Let's Encrypt stopped embedding OCSP URLs in certificates (2025-05-07) and shut down the OCSP responder entirely (2025-08-06). Retaining `ssl_stapling on` produces `nginx: [warn] … no OCSP responder URL` and can block `nginx reload` when the resolver is unreachable. All four directives commented out with explanation. Certificate revocation checking now falls entirely to client-side CRL.

- **[P10] `Permissions-Policy` 补全三项高风险特性** — 参照 OWASP Secure Headers Project 2025 建议，在原有四项（`camera` / `microphone` / `geolocation` / `payment`）基础上追加：`interest-cohort=()`（禁用 Google FLoC 用户画像追踪，WordPress 隐私保护最佳实践）、`usb=()`（禁用 WebUSB，WordPress 无此 API 使用场景）、`display-capture=()`（禁用屏幕录制，WordPress 无此 API 使用场景）。同步更新 `_nginx_security_headers()` 主块与 `_nginx_static_cache_headers()` 字体 location 重声明块（后者若不同步，Nginx 继承规则将导致字体请求返回更宽松的策略）。
  **`Permissions-Policy` expanded with three additional directives** — Per OWASP Secure Headers Project 2025: added `interest-cohort=()` (disables Google FLoC profiling; WordPress privacy best practice), `usb=()` (no WebUSB use case in WordPress), and `display-capture=()` (no screen-capture use case in WordPress). Both `_nginx_security_headers()` (server block) and the font location re-declaration block in `_nginx_static_cache_headers()` updated in sync (the font location uses `add_header`, which overrides parent-block headers in Nginx).

---

## [V3.1.0]

> **升级说明 / Upgrade note**
> V3.1.0 是 V3.0.15 之后所有增量更新的统一发布版本（原内部版本 V3.0.16–V3.0.19 已合并至本条目），
> 并在发布前完成了一轮系统级代码审查，额外修复了 6 项遗留问题。
> 从 V3.0.15 升级时，直接替换脚本文件并执行 `update` 子命令即可。
>
> V3.1.0 consolidates all incremental updates after V3.0.15 (internal versions V3.0.16–V3.0.19)
> into a single release, with an additional code-review pass that fixed 6 residual issues.
> To upgrade from V3.0.15, replace the script and run the `update` subcommand.

---

### 🔴 代码质量修复 / Code Quality Fixes (V3.1.0 review pass)

- **[P1] 删除死代码 `_resolve_cert_file()`** — 该静态方法自 V3.0.19 重构后已无任何调用者，予以删除，消除维护负担。
  **Dead code removal: `_resolve_cert_file()`** — This static method had no callers after the V3.0.19 refactor and has been removed.

- **[P2] 修复 `_resolve_cert_paths()` 硬编码 certbot 路径** — 函数内部硬编码了 `["certbot", ...]` 命令，在 Snap 环境下 certbot 不在 PATH 时探测失败。新增可选参数 `certbot_bin`，未传入时自动按 `which` → `/snap/bin` → `certbot-auto` → 兜底的优先级探测，与 `_detect_certbot_bin()` 一致。
  **Fix `_resolve_cert_paths()` hardcoded certbot path** — Hardcoded `["certbot", ...]` failed silently in Snap environments. Now accepts optional `certbot_bin`; performs the same priority detection as `_detect_certbot_bin()` when omitted.

- **[P3] `_setup_cloudflare_real_ip()` 统一使用 `_safe_reload_nginx()` 门控** — 原代码直接调用 `systemctl reload nginx`，绕过了 V3.0.16 P8 建立的统一 `nginx -t` 预检门控。已替换为 `_safe_reload_nginx()`，与其余所有 reload 路径保持一致。
  **`_setup_cloudflare_real_ip()` now uses `_safe_reload_nginx()` gate** — Previously bypassed the unified `nginx -t` pre-check gate (V3.0.16 P8). Now consistently uses `_safe_reload_nginx()`.

- **[P4] 消除 `_resolve_cert_paths()` 与 `_probe_cert_paths()` 逻辑重叠** — 两函数包含几乎相同的三级探测逻辑。重构后 `_resolve_cert_paths()` 直接委托 `SiteConfig._probe_cert_paths()` 执行，建立单一事实来源。
  **Eliminate logic duplication between `_resolve_cert_paths()` and `_probe_cert_paths()`** — Refactored: `_resolve_cert_paths()` now delegates to `SiteConfig._probe_cert_paths()`, establishing a single source of truth.

- **[P5] 修正 `_get_cert_domains()` docstring** — docstring 仍描述读取硬编码路径 `/etc/letsencrypt/live/{domain}/fullchain.pem`，与 V3.0.19 改为读取 `self.cfg.cert_chain` 的实际代码不一致，已更正。
  **Fix `_get_cert_domains()` docstring** — Was still describing a hardcoded path, inconsistent with the V3.0.19 change to use `self.cfg.cert_chain`. Corrected.

- **[P6] 处理 BTRFS `chattr +C` 返回值** — 返回值此前被忽略。失败时 btrfs swap 文件缺少 nocow 属性，后续 `swapon` 可能报 "swapfile has holes" 错误。现捕获返回值并在失败时发出 `WARNING` 日志。
  **Handle BTRFS `chattr +C` return value** — Previously ignored. On failure, the swap file lacks the nocow attribute, potentially causing `swapon` to fail. Now emits a `WARNING` log on failure.
- **[N1] 修复 9 处 `read_text()`/`open()` 缺少 `encoding='utf-8'`** — AST 全量扫描发现 7 处 `Path.read_text()` 和 2 处 `open()` 文本模式读取未指定编码。在 `LC_ALL=C` 的 CentOS 7 最小安装环境下 Python 默认编码为 ASCII，虽然涉及的文件内容（密码文件、哈希文件、`/proc` 虚拟文件）均为纯 ASCII 字符集，实际触发 `UnicodeDecodeError` 概率接近零，但属于潜在地雷。已统一添加 `encoding='utf-8'`。涉及位置：`_saved_lang()`、`_tune_kernel_network()`、`init_mariadb_root()`、`_install_wpcli()`、`download_and_verify_wordpress()`、`backup()`、`restore()`、`_get_fs_type()`、`_get_total_ram_mb()`。
  **[N1] Fix 9 `read_text()`/`open()` calls missing `encoding='utf-8'`** — Full AST scan found 7 `Path.read_text()` and 2 `open()` text-mode reads without explicit encoding. On CentOS 7 minimal installs with `LC_ALL=C`, Python defaults to ASCII. Although all affected files (password files, hash files, `/proc` virtual files) contain only ASCII content, the missing encoding is a latent risk. All 9 call sites now specify `encoding='utf-8'`.

- **[N2] 审计 `backup()` Popen 管道 encoding 风格（不改动）** — `backup()` 中 `p_dump = subprocess.Popen(...)` 的 stdout 管道连接到 `p_gzip.stdin`，必须保持 bytes 模式（无法使用 `text=True`）。`stderr.read()` 返回 bytes 后用 `.decode("utf-8", errors="replace")` 处理，功能正确。与代码库其余使用 `text=True, encoding='utf-8'` 的 `subprocess` 调用风格不一致，但属于管道场景的正确做法，不做改动。
  **[N2] Audit `backup()` Popen pipe encoding style (no change)** — The `p_dump` stdout pipe connects to `p_gzip.stdin` and must stay in bytes mode (`text=True` is not applicable). `stderr.read()` returns bytes handled via `.decode("utf-8", errors="replace")`, which is correct. Style inconsistency 
---

### ✨ 新功能 / New Features (merged from V3.0.16)

- **[P1] Nginx 静态资源浏览器长缓存** — 图片 365 天、JS/CSS 30 天、字体 365 天 + CORS。消除静态资源走 PHP-FPM 的浪费。字体 location 重新声明全部关键安全响应头（HSTS、nosniff、Referrer-Policy、Permissions-Policy），防止 Nginx `add_header` 继承丢失。
  **Nginx static resource browser caching** — Images 365d, JS/CSS 30d, fonts 365d + CORS. Font location re-declares all critical security headers to prevent `add_header` inheritance loss.

- **[P2] WordPress Cron 系统定时器** — 注入 `DISABLE_WP_CRON=true`，创建 15 分钟 systemd 定时器（WP-CLI `wp cron event run --due-now` / `php wp-cron.php` 兜底），消除每次请求触发 wp-cron.php 的性能开销。
  **WordPress Cron systemd timer** — Injects `DISABLE_WP_CRON=true`, creates a 15-minute systemd timer. Eliminates per-request wp-cron.php overhead.

- **[P3] PHP-FPM 按内存动态调参** — 根据系统内存自动计算 `pm.max_children`：≤1 GB→ondemand/5，≤2 GB→ondemand/10，≤4 GB→dynamic/20，>4 GB→公式计算，防止小 VPS OOM。
  **PHP-FPM dynamic pool tuning** — Auto-calculates `pm.max_children` based on RAM tiers. Prevents OOM kills on small VPS.

- **[P4] Swap 自动创建** — ≤2 GB 内存且无 swap 时自动创建 swapfile（≤1 GB → 1 GB，≤2 GB → 2 GB），持久化到 `/etc/fstab`，设置 `vm.swappiness=10`，失败时非阻塞。
  **Automatic swap creation** — Creates and persists swapfile on ≤2GB RAM systems with no swap. Non-blocking on failure.

- **[P5] 内核网络参数调优** — 写入 sysctl drop-in：BBR 拥塞控制（kernel 4.9+）、TCP backlog/keepalive 优化、`fd-max=500000`。BBR 不可用时静默跳过。
  **Linux kernel network tuning** — BBR congestion control, TCP optimization, fd-max=500000. BBR unavailable → silent skip.

- **[P6] MariaDB 基础调优** — 写入 `wp-bootstrap-tuning.cnf`：`innodb_buffer_pool_size` 按内存分级（128 M–50%），`skip_name_resolve`，小服务器关闭 `performance_schema`，`max_connections` 分级。外置数据库时跳过。
  **MariaDB auto-tuning** — Writes tiered InnoDB/connection/performance config. External DB → skip.

- **[P7] `--wp-auto-install`** — 通过 `wp core install` 自动完成 WordPress 安装向导，随机生成管理员密码并写入凭据文件。需要 WP-CLI；已安装时跳过。
  **`--wp-auto-install`** — Completes WordPress setup wizard via WP-CLI. Generates random admin password saved to credentials file.

- **[P9] `--optimize` 启用 Nginx `open_file_cache`** — `max=10000 inactive=60s valid=30s`，减少静态资源密集站点的内核 `stat()` 系统调用。
  **`--optimize` flag** — Enables Nginx `open_file_cache`. Reduces `stat()` syscalls for static-heavy sites.

- **[P10] `self-update` 子命令** — 从远端下载最新版脚本，SHA-256 校验后原子替换。支持 `WP_UPDATE_URL` / `--url` 自定义源。
  **`self-update` subcommand** — Downloads latest script, SHA-256 verification, atomic replacement. Supports custom mirrors via `WP_UPDATE_URL` / `--url`.

- **[P11] MySQL 周度优化定时器** — systemd 定时器每周日 03:00 执行 `mysqlcheck --optimize --single-transaction`，回收碎片空间。外置数据库时跳过。
  **MySQL weekly optimize timer** — systemd timer runs `mysqlcheck --optimize` every Sunday 03:00. External DB → skip.

- **[P12] `--cloudflare` 标志** — 自动从 Cloudflare 官方 API 获取最新 IP 段，写入 `set_real_ip_from` + `real_ip_header CF-Connecting-IP` 到全局 Nginx 配置。获取失败时回退内置默认值。
  **`--cloudflare` flag** — Auto-fetches Cloudflare IP ranges, writes global Nginx Real IP config. Falls back to built-in defaults on fetch failure.

---

### 🔒 安全修复 / Security Fix (merged from V3.0.18)

- **FastCGI 缓存穿透漏洞修复** — 收紧 `_nginx_fastcgi_cache_block` 正则：将 `$request_uri` 替换为已规范化的 `$uri`，对各子模式添加行首锚点 `^`（xmlrpc 额外加 `$` 尾锚），封堵通过恶意查询参数（如 `/?test=/xmlrpc.php`）绕过缓存规则的攻击向量。
  **FastCGI cache bypass fix** — Replaced `$request_uri` with normalized `$uri`; added `^` anchors (xmlrpc also gets `$`). Closes the malicious query-param cache bypass vector.

---

### 🐛 问题修复 / Bug Fixes (merged from V3.0.17)

- **Cloudflare Real IP 配置时序修正** — 修复全新部署时写入 Cloudflare 配置后缺少 Nginx reload，导致真实 IP 还原首次部署不生效的 Bug。（V3.1.0 P3 进一步升级为 `_safe_reload_nginx()`。）
  **Cloudflare Real IP timing fix** — Fixed missing Nginx reload after writing Cloudflare config on first deploy. (Further upgraded to `_safe_reload_nginx()` in V3.1.0 P3.)

- **多语言 WPLANG 兜底失败修复** — 修复跨语言兜底下载（英文包缺少 WPLANG 常量）时 `patch_wplang()` 静默失败的问题，改用智能追加 `define('WPLANG', 'zh_CN');` 逻辑。
  **WPLANG patch silent-fail fix** — Fixed `patch_wplang()` failing silently when a cross-language fallback package was downloaded. Now uses smart-append logic.

- **BTRFS Swap 创建兼容性支持** — 修复在 BTRFS 上 `dd` 创建 swapfile 失败的问题，在分配空间前注入 `chattr +C` 禁用 COW 属性，配合优雅降级。（V3.1.0 P6 补充了返回值处理。）
  **BTRFS swap compatibility** — Fixed `dd` swapfile creation failure on BTRFS by injecting `chattr +C` before allocation. (V3.1.0 P6 adds return value handling.)

---

### 🏗️ 架构重构 / Architecture (merged from V3.0.19)

- **配置中心化（SiteConfig）** — 将 certbot 路径与证书路径探测前置至 `SiteConfig.__init__`，一次探测、全程共享，消除各部署阶段重复调用子进程的开销。
  **SiteConfig centralization** — All environment probing moved to `SiteConfig.__init__`. Probe once, share everywhere.

- **解除 certbot 路径硬编码** — 新增 `_detect_certbot_bin()` 静态方法，自动探测标准环境（`which`）、Ubuntu Snap（`/snap/bin/certbot`）及旧版独立安装（`/usr/local/bin/certbot-auto`）。
  **Certbot path auto-detection** — New `_detect_certbot_bin()` covers standard PATH, Ubuntu Snap, and legacy certbot-auto installs.

- **智能证书路径探测** — 新增 `_probe_cert_paths()`，三级短路设计（标准路径 → `certbot certificates` 解析 → 首次部署回退），兼容非标 `--config-dir` 等场景。
  **Smart cert path probing** — New `_probe_cert_paths()` with three-tier short-circuit design, compatible with non-standard `--config-dir` setups.

- **下游调用点统一** — 清理全部硬编码的 `/etc/letsencrypt/live/...` 魔法字符串，11 个调用点统一替换为 `self.cfg.certbot_bin` 和 `self.cfg.cert_chain`。
  **Downstream call-site unification** — All 11 downstream sites now use `self.cfg.certbot_bin` / `self.cfg.cert_chain`. No more magic strings.

---

### 🔨 改进 / Improvements (merged from V3.0.16)

- **[P8] `_safe_reload_nginx()` 统一门控** — 所有 `apply_nginx_config_safe()` 之外的 reload 路径统一经过 `nginx -t` 预检，防止配置错误导致 Nginx 在 restore/update/uninstall 场景中宕机。
  **`_safe_reload_nginx()` unified gate** — All reload paths outside `apply_nginx_config_safe()` now pass through `nginx -t` pre-check.

- **[Fix]** 字体 location 补充 `Referrer-Policy` 和 `Permissions-Policy` 重声明 — Nginx location 块 `add_header` 会覆盖所有 server 级头；之前版本仅重声明了 HSTS 和 `X-Content-Type-Options`。
  **Font location security header re-declaration** — Added missing `Referrer-Policy` and `Permissions-Policy`.

- **[Fix]** `_tune_mariadb()` 移除 `innodb_log_file_size` — 在 MariaDB < 10.6 上变更该参数会导致重启失败。
  **`_tune_mariadb()` removes `innodb_log_file_size`** — Changing this on MariaDB < 10.6 causes startup failure.

- **[Fix]** `_do_self_update()` 下载超时控制 — 将无超时的 `urlretrieve` 替换为 `urlopen` + 手动写入（60 s 超时）。
  **`_do_self_update()` download timeout** — Replaced `urlretrieve` (no timeout) with `urlopen` + manual write (60s).

- **[Fix]** `setup_lemp_and_wp()` 在 MariaDB 调优重启后重新等待数据库就绪，防止后续 SQL 操作失败。
  **`setup_lemp_and_wp()` re-waits for DB** after `_tune_mariadb()` restart.

- **[Fix]** `uninstall()` 保留 `cloudflare-real-ip.conf`（多域名共享，卸载单域名时不删除）；清理 wp-cron 和 db-optimize 定时器文件。
  **`uninstall()` preserves `cloudflare-real-ip.conf`** (shared across domains); cleans up wp-cron and db-optimize timer files.

### Internal 内部

- `_get_total_ram_mb()` 静态方法，统一内存探测逻辑（供 P3/P4/P6 使用）。
- `_detect_redis_service_name()` 统一辅助方法，消除 3 处内联重复。
- `_run_deploy_branch()` 从 `run()` 提取，使早返回流程更清晰。
- `_get_cert_domains()` 从已有证书 SAN 读取域名列表，精确续期。

---

## [V3.0.15]

- **[Fix]** `download_and_verify_wordpress()` / `_wpcli_download_wordpress()`: WordPress download now respects `_LANG` setting. English mode downloads the global (en) package first with zh_CN as fallback; Chinese mode preserves previous behavior.
  WordPress 下载适配语言设置。英文模式优先下载全球主源（英文包），中文包兜底；中文模式保持原有行为。
- **[Fix]** New `patch_wplang()`: forces `WPLANG` in `wp-config.php` to match `_LANG`, preventing language mismatch when a cross-language fallback source is used.
  新增 `patch_wplang()`：强制 wp-config.php 中 WPLANG 与 `_LANG` 一致，防止跨语言兜底下载导致安装语言错乱。
- **[Robustness]** `setup_lemp_and_wp()`: `php.ini` and `www.conf` writes switched to `_safe_write_file()` atomic write, preventing PHP-FPM from reading truncated config on power loss.
  `php.ini` 和 `www.conf` 写入改用 `_safe_write_file()` 原子写入，防止断电时 PHP-FPM 读到截断配置。
- **[Fix]** `classify_certbot_error()`: clarified `"unauthorized"` — refers to ACME challenge failure (CA-side HTTP 403), not local permission errors; RETRYABLE is intentional.
  `classify_certbot_error()` 澄清 `"unauthorized"` 注释：指 ACME challenge 验证失败（CA 端 HTTP 403），非本地权限错误。
- **[Fix]** `acquire_lock()`: explicitly releases `global_lock_fd` before `sys.exit(1)` on per-domain lock failure.
  `acquire_lock()` 在 per-domain 锁失败退出前显式释放全局锁，不依赖内核隐式清理。
- **[i18n]** `print_final_summary()` credential file content fully internationalized; disk check labels, rollback descriptions, OSError messages, and `run_cmd` sensitive-mode marker switched from hardcoded Chinese to `t()`.
  `print_final_summary()` 凭据文件内容完整国际化；磁盘检查标签、回滚描述、OSError 消息、脱敏标记从硬编码中文改为 `t()`。

## V3.0.14

- **[i18n]** `_mysql_escape_value` ValueError: hardcoded Chinese → `t("err_escape_control_char")`
- **[i18n]** `_run_wpcli` CmdResult.stderr: hardcoded Chinese → `t("err_wpcli_unavailable")`
- **[i18n]** `_run_certbot_with_lock` CmdResult.stderr: hardcoded Chinese → `t("err_certbot_lock")`

> These 3 strings were missed during the V3.0.5 full i18n migration. They surface via `{err}` placeholders in user-visible logs, causing Chinese fragments in English environments.
> 以上 3 处是 V3.0.5 全量 i18n 迁移的遗漏，英文环境下经 `{err}` 占位符格式化后出现在用户日志中。

## V3.0.13

- **[Fix]** `renew_cert()` reads domain list from existing certificate SAN instead of hardcoding `www`. Prevents renewal failure when the certificate only covers the main domain.
  `renew_cert()` 从已有证书 SAN 读取域名列表，不再硬编码 www。

## V3.0.12

- **[Compat]** f-string nested quote fix for Python 3.11 compatibility.
- **[Fix]** `verify_dns()` returns `(main_ok, www_ok)` tuple; `apply_cert(include_www)` dynamically trims certbot `-d` list.
- **[Fix]** `backup()` cleans up corrupted `.sql.gz` on dump failure.
- **[Fix]** `restore()` logs warning and sets exit code when `nginx -t` fails.
- **[Fix]** `backup()` extras/ `mkdir` + `chmod` deduplicated.

## V3.0.11

- **[Fix]** `restore()` only restarts fail2ban when f2b rule files were actually restored.
- **[Fix]** `update_config()` adds `_setup_redis_cache()` call, allowing `update --redis` to install Redis cache post-deploy.
- **[Security]** `backup()` extras/ subdirectory explicitly `chmod 0700`.
- **[Perf]** `_detect_nginx_http2_directive()` result cached at module level to avoid repeated fork.
- **[Security]** `setup_fail2ban()` failregex lines anchored with `$`.
- **[Perf]** `_write_mysql_defaults_file()` only `chmod` on newly created tmpdir.

## V3.0.10

- **[Fix]** Version string updated in 2 locations (docstring + `parser_description`).
- **[Fix]** `backup()` `total_size` uses `rglob` to include extras/ subdirectory files.
- **[Fix]** `restore()` DB recovery `TimeoutExpired` / `Exception` paths now set `_exit_code = 1`.
- **[Fix]** `_nginx_http_redirect()` adds `server_tokens off`.
- **[Fix]** `restore()` restarts fail2ban after restoring extras config.

## V3.0.9

- **[Fix]** `uninstall` branch in `main()` adds `setup_signals()` + `acquire_lock()` + `try/finally`.
- **[Refactor]** New `_detect_redis_service_name()` replaces 3 inline duplicates.
- **[Fix]** `backup()` and `restore()`: all "partial failure" paths now set `_exit_code = 1` (7 locations).
- **[Fix]** `update_config()` uses `_ensure_wpcli()` instead of `_detect_wpcli()`.
- **[Feature]** New `_detect_nginx_http2_directive()`: auto-fallback to `listen 443 ssl http2` for Nginx < 1.25.1.
- **[Feature]** `backup()` / `restore()` step 4: Fail2Ban filter/jail + logrotate config backed up to `extras/` and restored by prefix.
- **[Fix]** `update_config()` appends `setup_systemd()` call to sync renewal unit.
- **[Compat]** 2 occurrences of `Path.unlink(missing_ok=True)` rewritten for Python 3.6 compatibility.

## V3.0.8

- **[Security]** `inject_salts()`: `assert` → `if/raise`, prevents `-O` mode from skipping validation.
- **[Security]** `_write_mysql_defaults_file()`: control character interception prevents `.cnf` truncation.
- **[Security]** `atomic_write()`: cleans up `.aw_bak` after success; dump file `fchmod 0600` immediately.
- **[Fix]** `verify_dns()`: www subdomain failure downgraded to warning (does not block deployment).
- **[Fix]** `restore`/`update`/`backup` subcommands correctly propagate non-zero exit codes on exception.
- **[Robustness]** `run_cmd`/`run_sql` use `encoding='utf-8', errors='replace'`.

## V3.0.7

- **[Fix]** `restore` subcommand adds `--cache` / `--redis` / `--allow-xmlrpc` arguments.
- **[Fix]** `_write_lang_file()`: fallback to direct write when `os.replace` fails; temp file cleanup in `finally`.
- **[Fix]** `t()`: explicit `None` check instead of `or` chain.

## V3.0.6

- **[i18n]** ~50 hardcoded Chinese/mixed-language messages migrated to `_MESSAGES` + `t()`.
- **[Fix]** `update` subcommand adds `--php-version` argument.
- **[Security]** Language config file writes use atomic `_write_lang_file()` with 0600 permissions.
- **[Perf]** SHA-256/SHA-512 checksum chunk size 4096 → 65536 bytes.
- **[Misc]** Version number extracted to `__version__` constant.

## V3.0.5

- **[Feature]** Built-in i18n system: auto-detects language from `LANG` / `LC_ALL` / `LANGUAGE` / `WP_LANG`. Supports Chinese and English.
  内置 i18n 系统：通过环境变量自动切换中英双语。
- **[Feature]** Translations cover all user-visible messages (~500 entries).
- **[Feature]** Language persistence: `--lang` writes to `/root/.wp_ssl_lang`.
- **[Feature]** Language change detection: interactive prompt on preference mismatch.

## V3.0.4

- **[Fix]** `logrotate` `create` directive: auto-select log group by package manager (apt→adm, dnf/yum→root).
- **[Feature]** Backup path supports `WP_BACKUP_DIR` env var and `--backup-dir` CLI argument.
- **[Misc]** MIT License header added to script.

## V3.0.3

- **[Feature]** `--allow-xmlrpc`: switches from deny to rate-limited (1r/s burst=10) PHP-FPM passthrough.
  `--allow-xmlrpc`：xmlrpc 从 deny 改为速率限制透传，支持 Jetpack / 移动 App。
- **[Security]** Dedicated `limit_req_zone` for xmlrpc when `--allow-xmlrpc` is set.
- **[Security]** Fail2Ban filter: xmlrpc matches 429 (rate-limited) instead of 200.

## V3.0.2

- **[Fix]** `update`/`status` subcommands add `--cache`/`--redis` arguments.
- **[Fix]** Redis service name compatible with Debian/Ubuntu `redis-server`.
- **[Security]** `backup`/`restore`/`update` subcommands acquire global process lock.

## V3.0.1

- **[Fix]** `wp-cron.php` location adds `fastcgi_pass` (was silently broken).
- **[Fix]** `Permissions-Policy` `payment()` syntax corrected.
- **[Fix]** `restore()` Popen variables pre-initialized to prevent `NameError` in `finally`.
- **[Security]** `atomic_write()` cleans up `.aw_tmp` on exception path.
- **[Security]** `find chmod 644` excludes `wp-config.php` to eliminate permission window.

## V3.0.0

- **[Refactor]** `generate_https_config()` split into 10 independent fragment functions.
  `generate_https_config()` 拆分为 10 个独立片段函数，每个可独立测试。
- **[Feature]** `--skip-deps` flag: skip system package installation.

## V2.9.9

- **[Fix]** `restore()` pipe deadlock: `stderr=DEVNULL` + process cleanup.
- **[Fix]** `uninstall()` cleans up logrotate config file.
- **[Feature]** `show_status()` conditionally displays Redis service status.
- **[Feature]** Brotli installation adds dnf/yum branch.

## V2.9.8

- **[Feature]** `--redis` enables Redis object cache (composable with FastCGI page cache).
  `--redis` 启用 Redis 对象缓存，可与 FastCGI 页面缓存叠加。
- **[Feature]** Brotli compression auto-detected; enabled globally when module is available.
- **[Feature]** New `restore` subcommand.
- **[Feature]** New `update` subcommand.

## V2.9.7

- **[Security]** `wp-config.php` injected with 6 hardening constants (`DISALLOW_FILE_EDIT`, `FORCE_SSL_ADMIN`, etc.).
- **[Perf]** Nginx HTTPS config adds OCSP Stapling.
- **[Security]** Nginx adds `Content-Security-Policy-Report-Only` header.
- **[Feature]** Auto-configured logrotate for per-domain Nginx logs.
- **[Security]** Database grants reduced to minimal privilege set.

## V2.9.6

- **[Security]** `patch_php_fpm_pool_user()` uses lambda to eliminate backreference injection.
- **[Security]** `wp-config.php` written via `_safe_write_file(mode=0o440)`.

## V2.9.5

- **[Security]** Domain length validation: 253-char DNS limit.
- **[Security]** `prctl(PR_SET_DUMPABLE, 0)` blocks `/proc/self/mem` reads.
- **[Security]** New `_safe_write_file()` atomic write helper; all credential files use atomic write with immediate 0600 permissions.
- **[Feature]** `run_cmd` adds `sensitive` parameter for log redaction.
- **[Feature]** `--version` global argument.

## V2.9.4

- **[Fix]** `backup()` now reads `cfg.db_root_pass_input` (was silently ignored since V2.9.3).
- **[Fix]** `_wait_db_ready()`: skip `mysqladmin` loop when binary is not available.
- **[Fix]** `backup()` mysqldump stderr: async read via `concurrent.futures` eliminates pipe deadlock.
- **[Security]** SSL ciphers replaced with Mozilla Intermediate recommended list.
- **[Security]** `ssl_session_tickets off` added.
- **[Feature]** `install_packages()` adds WordPress-recommended PHP extensions: `php-curl`, `php-zip`, `php-intl`, `php-opcache`.
- **[Feature]** PHP ini patches: `memory_limit=256M`, `max_execution_time=300`, OPcache settings.

## V2.9.3

- **[Fix]** `inject_salts()` regex and token length corrected.
- **[Fix]** `--db-root-pass` added to common arguments for `backup`/`renew`/`status`.
- **[Security]** Nginx `limit_req_zone` for `wp-login.php` (1r/s, burst=5 nodelay).

## V2.9.2

- **[Security]** Nginx `server_tokens off`.
- **[Security]** Nginx blocks PHP execution in `wp-content/uploads/`.
- **[Security]** Nginx restricts `wp-cron.php` to localhost.
- **[Security]** `wp-config.php` enforced to `chmod 0440`.

## V2.9.1

- **[Security]** Core dump disabled: `RLIMIT_CORE=0` + `PR_SET_DUMPABLE=0`.
- **[Security]** Password entropy increased from 24 → 32 bytes.
- **[Security]** Root password not saved to disk by default; `--persist-root-pwd` required.
- **[Security]** `apply_nginx_config_safe()` introduces `flock` to eliminate TOCTOU race.
- **[Security]** Certbot and global deployment file-level locks.

## V2.8.0

- **[Security]** New `_mysql_escape_value()` for defense-in-depth SQL injection prevention.
- **[Fix]** `_recover_existing_db_pass()` regex supports PHP-escaped passwords.
- **[Fix]** `verify_http_challenge()` detects Nginx listen address from config.
- **[Fix]** `_detect_webroot_base()` prioritizes `/etc/os-release` for distro detection.

## V2.7.x

- **[Feature]** WP-CLI multi-mirror download: GitHub raw → jsDelivr CDN fallback.
- **[Feature]** `--db-wait-timeout` CLI argument and `WP_DB_WAIT_TIMEOUT` env var.
- **[Security]** `.cnf` password values double-quoted; `patch_wp_config()` PHP-escapes values.
- **[Fix]** Idempotent re-run: recovered password verified against database before reuse.

## V2.6

- **[Feature]** FastCGI Cache: auto-installs `nginx-helper` plugin via WP-CLI.
- **[Feature]** External database support: `--db-host` / `WP_DB_HOST`.

## V2.5

- **[Feature]** Webroot path adapts to distro: Debian→`/var/www/html`, RHEL→`/usr/share/nginx/html`.
- **[Feature]** `--db-root-pass` / `WP_DB_ROOT_PASS` for pre-secured MariaDB.

## V2.4

- **[Feature]** `backup --keep N` auto-removes old backups beyond retention count.
- **[Feature]** `--php-version` forces specific PHP-FPM version.

## V2.3

- **[Feature]** Fail2Ban integration: auto-configured WordPress brute-force protection.
- **[Feature]** `backup` subcommand.
- **[Feature]** `--cache fastcgi` enables Nginx FastCGI page cache.

## V2.2

- **[Security]** Nginx blocks `xmlrpc.php`; adds `Permissions-Policy` header.
- **[Feature]** `renew --force` flag; `status` subcommand.

## V2.1

- **[Refactor]** CLI subcommands (`deploy` / `renew` / `uninstall`) replace legacy `--uninstall` flag.
- **[Fix]** Nginx `.pending` temp file cleanup in `apply_nginx_config_safe()` finally block.