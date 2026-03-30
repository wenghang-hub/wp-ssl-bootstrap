# Changelog / 变更日志

All notable changes to WP-SSL-Bootstrap are documented in this file.
本文件记录 WP-SSL-Bootstrap 的所有重要变更。
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