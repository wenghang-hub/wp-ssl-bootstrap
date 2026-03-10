# Changelog / 变更日志

All notable changes to WP-SSL-Bootstrap are documented in this file.
本文件记录 WP-SSL-Bootstrap 的所有重要变更。

---

## [V3.1.0] - 2026-03-10

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

## [V3.0.15] - 2026-02-xx

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
