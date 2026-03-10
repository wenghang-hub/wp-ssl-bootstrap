# Changelog / 变更日志

All notable changes to WP-SSL-Bootstrap are documented in this file.
本文件记录 WP-SSL-Bootstrap 的所有重要变更。

---

## V3.0.15

- **[Fix]** `download_and_verify_wordpress()` / `_wpcli_download_wordpress()`: WordPress download now respects `_LANG` setting. English mode downloads the global (en) package first with zh_CN as fallback; Chinese mode preserves previous behavior.
  WordPress 下载适配语言设置。英文模式优先下载全球主源（英文包），中文包兜底；中文模式保持原有行为。
- **[Fix]** New `patch_wplang()`: forces `WPLANG` in `wp-config.php` to match `_LANG`, preventing language mismatch when a cross-language fallback source is used (e.g. user chose English but Chinese package downloaded as fallback).
  新增 `patch_wplang()`：强制 wp-config.php 中 WPLANG 与 `_LANG` 一致，防止跨语言兜底下载导致安装语言错乱。
- **[Robustness]** `setup_lemp_and_wp()`: `php.ini` and `www.conf` writes switched from `Path.write_text()` to `_safe_write_file()` atomic write, preventing PHP-FPM from reading truncated config on power loss.
  `php.ini` 和 `www.conf` 写入改用 `_safe_write_file()` 原子写入，防止断电时 PHP-FPM 读到截断配置。
- **[Fix]** `classify_certbot_error()`: clarified comments for `"unauthorized"` keyword — this refers to ACME challenge verification failure (CA-side HTTP 403), not local filesystem permission errors; RETRYABLE classification is intentional.
  `classify_certbot_error()` 澄清 `"unauthorized"` 注释：指 ACME challenge 验证失败（CA 端 HTTP 403），非本地权限错误；RETRYABLE 归类为有意为之。
- **[Fix]** `acquire_lock()`: explicitly releases `global_lock_fd` before `sys.exit(1)` on per-domain lock failure, avoiding reliance on kernel implicit cleanup.
  `acquire_lock()` 在 per-domain 锁失败退出前显式释放全局锁，不依赖内核隐式清理。
- **[i18n]** `print_final_summary()` credential file content fully internationalized; `check_disk_space` labels, `_register_rollback` descriptions, `_safe_write_file` OSError messages, and `run_cmd` sensitive-mode `[参数已隐藏]` marker switched from hardcoded Chinese to `t()` / English.
  `print_final_summary()` 凭据文件内容完整国际化；磁盘检查标签、回滚描述、OSError 消息、`run_cmd` 脱敏标记从硬编码中文改为 `t()` / 英文。

## V3.0.14

- **[i18n]** `_mysql_escape_value` ValueError: hardcoded Chinese → `t("err_escape_control_char")`
  `_mysql_escape_value` 的 ValueError 硬编码中文改为 `t("err_escape_control_char")`
- **[i18n]** `_run_wpcli` CmdResult.stderr: hardcoded Chinese → `t("err_wpcli_unavailable")`
  `_run_wpcli` 的 CmdResult.stderr 硬编码中文改为 `t("err_wpcli_unavailable")`
- **[i18n]** `_run_certbot_with_lock` CmdResult.stderr: hardcoded Chinese → `t("err_certbot_lock")`
  `_run_certbot_with_lock` 的 CmdResult.stderr 硬编码中文改为 `t("err_certbot_lock")`

> These 3 strings were missed during the V3.0.5 full i18n migration. They surface in user-visible logs via `{err}` placeholders, causing Chinese fragments in English environments.
> 以上 3 处是 V3.0.5 全量 i18n 迁移的遗漏，stderr 值经 `{err}` 占位符格式化后出现在用户日志中，英文环境下会混入中文。

## V3.0.13

- **[Fix]** `renew_cert()` reads domain list from existing certificate SAN instead of hardcoding `www`. Prevents renewal failure when the certificate only covers the main domain.
  `renew_cert()` 从已有证书 SAN 读取域名列表，不再硬编码 www；避免仅主域名证书续期时因 www 验证失败导致中断。

## V3.0.12

- **[Compat]** f-string nested quote fix for Python 3.11 compatibility.
  f-string 嵌套引号修复，兼容 Python 3.11。
- **[Fix]** `verify_dns()` returns `(main_ok, www_ok)` tuple; `apply_cert(include_www)` dynamically trims certbot `-d` list; deploy flow extracted to `_run_deploy_branch()`.
  `verify_dns()` 返回元组；`apply_cert(include_www)` 动态裁剪 certbot `-d` 列表；部署流程提取为 `_run_deploy_branch()`。
- **[Fix]** `backup()` cleans up corrupted `.sql.gz` on dump failure.
  `backup()` dump 失败时清理损坏的 `.sql.gz`。
- **[Fix]** `restore()` logs warning and sets exit code when `nginx -t` fails.
  `restore()` 在 `nginx -t` 失败时记录警告并设置退出码。
- **[Fix]** `backup()` extras/ `mkdir` + `chmod` deduplicated.
  `backup()` extras/ 目录 `mkdir` + `chmod` 去重。

## V3.0.11

- **[Fix]** `restore()` only restarts fail2ban when f2b rule files were actually restored.
  `restore()` 仅在实际恢复了 fail2ban 规则文件时才重启。
- **[Fix]** `update_config()` adds `_setup_redis_cache()` call, allowing `update --redis` to install Redis cache post-deploy.
  `update_config()` 补充 `_setup_redis_cache()` 调用，允许通过 `update --redis` 补装。
- **[Security]** `backup()` extras/ subdirectory explicitly `chmod 0700`.
  `backup()` extras/ 子目录显式 `chmod 0700`。
- **[Perf]** `_detect_nginx_http2_directive()` result cached at module level to avoid repeated fork.
  `_detect_nginx_http2_directive()` 结果模块级缓存，避免重复 fork。
- **[Security]** `setup_fail2ban()` failregex lines anchored with `$`.
  `setup_fail2ban()` failregex 所有行补齐行尾锚点 `$`。
- **[Perf]** `_write_mysql_defaults_file()` only `chmod` on newly created tmpdir.
  `_write_mysql_defaults_file()` 仅在新建 tmpdir 时 chmod。

## V3.0.10

- **[Fix]** Version string updated in 2 locations (docstring + `parser_description`).
  版本号字符串更新（模块 docstring + `parser_description`）。
- **[Fix]** `backup()` step comment numbering corrected.
  `backup()` 步骤注释编号修正。
- **[Fix]** `backup()` `total_size` uses `rglob` to include extras/ subdirectory files.
  `backup()` 大小统计改用 `rglob` 递归包含 extras/ 子目录。
- **[Fix]** `restore()` DB recovery `TimeoutExpired` / `Exception` paths now set `_exit_code = 1`.
  `restore()` 数据库恢复的超时/异常路径补充 `_exit_code = 1`。
- **[Fix]** `_nginx_http_redirect()` adds `server_tokens off`.
  `_nginx_http_redirect()` 补加 `server_tokens off`。
- **[Fix]** `restore()` restarts fail2ban after restoring extras config.
  `restore()` 恢复 extras 配置后重启 fail2ban。

## V3.0.9

- **[Fix]** `uninstall` branch in `main()` adds `setup_signals()` + `acquire_lock()` + `try/finally`, aligned with other write subcommands.
  `main()` 中 `uninstall` 分支补加信号处理、进程锁和 try/finally，与其他写操作子命令对齐。
- **[Refactor]** New `_detect_redis_service_name()` method replaces 3 inline duplicates in `_setup_redis_cache`, `setup_lemp_and_wp`, `show_status`.
  新增 `_detect_redis_service_name()` 方法，替代三处内联重复的 Redis 服务名检测逻辑。
- **[Fix]** `backup()` and `restore()`: all "partial failure" warning paths now set `_exit_code = 1` (7 locations).
  `backup()` 和 `restore()` 所有"部分失败"路径补充 `_exit_code = 1`（共 7 处）。
- **[Fix]** `update_config()` uses `_ensure_wpcli()` instead of `_detect_wpcli()`, allowing WP-CLI installation during update.
  `update_config()` 改用 `_ensure_wpcli()`，允许在 update 时补装 WP-CLI。
- **[Feature]** New `_detect_nginx_http2_directive()`: parses `nginx -v` version, auto-fallback to `listen 443 ssl http2` for Nginx < 1.25.1.
  新增 `_detect_nginx_http2_directive()`：解析 Nginx 版本号，< 1.25.1 时自动回退到内联 http2 语法。
- **[Fix]** `generate_http_only_config()` adds `server_tokens off`.
  `generate_http_only_config()` 补加 `server_tokens off`。
- **[Feature]** `backup()` step 4: backs up Fail2Ban filter/jail + logrotate config to `extras/` subdirectory; `restore()` step 4: routes files back to system directories by prefix.
  `backup()` 新增步骤：备份 Fail2Ban 和 logrotate 配置到 extras/ 子目录；`restore()` 新增步骤：按前缀路由回系统目录。
- **[Fix]** `update_config()` appends `setup_systemd()` call to sync renewal unit after script path changes.
  `update_config()` 末尾追加 `setup_systemd()` 调用，同步续期单元。
- **[Refactor]** `import json` moved to module top level.
  `import json` 移至模块顶层。
- **[i18n]** `warn_recover_pwd_bad_chars` message clarifies `[a-zA-Z0-9]` restriction and reason.
  `warn_recover_pwd_bad_chars` 消息明确说明字符集限制及原因。
- **[Fix]** `atomic_write()` `.aw_bak` cleanup failure logged as warning instead of silently ignored.
  `atomic_write()` 中 `.aw_bak` 删除失败改为记录警告。
- **[Fix]** `patch_php_fpm_pool_user()` adds optional `group` parameter; loop uses default-param lambda to avoid closure late-binding.
  `patch_php_fpm_pool_user()` 新增可选 `group` 参数；lambda 使用默认参数捕获循环变量。
- **[Compat]** 2 occurrences of `Path.unlink(missing_ok=True)` rewritten for Python 3.6 compatibility.
  2 处 `Path.unlink(missing_ok=True)` 改写以兼容 Python 3.6。

## V3.0.8

- **[Security]** `inject_salts()`: `assert` → `if/raise`, prevents `-O` mode from skipping validation.
  `inject_salts()` 的 `assert` 改为 `if/raise`，防止 `-O` 模式跳过校验。
- **[Security]** `setup_lemp_and_wp()`: defensive validation on `db_grant_host` value.
  `setup_lemp_and_wp()` 中 `db_grant_host` 增加防御性取值校验。
- **[Security]** `_write_mysql_defaults_file()`: control character interception prevents `.cnf` truncation.
  `_write_mysql_defaults_file()` 拦截控制字符，防止截断 `.cnf`。
- **[Security]** `atomic_write()`: cleans up `.aw_bak` after success to prevent credential leakage.
  `atomic_write()` 成功后清理 `.aw_bak` 残留。
- **[Security]** `backup()`: dump file `fchmod 0600` immediately after creation.
  `backup()` dump 文件创建后显式 `fchmod 0600`。
- **[Fix]** `patch_php_ini_line()`: commented line regex tightened from `[;\s]+` to `\s*;\s*`.
  `patch_php_ini_line()` 注释行正则收紧。
- **[Fix]** `update_config()` adds `_detect_wpcli` + `_install_nginx_helper`.
  `update_config()` 补充 WP-CLI 检测和 nginx-helper 安装。
- **[Fix]** `verify_dns()`: www subdomain failure downgraded to warning (does not block deployment).
  `verify_dns()` 中 www 子域解析失败降级为警告，不阻断部署。
- **[Fix]** `restore`/`update`/`backup` subcommands correctly propagate non-zero exit codes on exception.
  `restore`/`update`/`backup` 子命令异常时正确传递非零退出码。
- **[Robustness]** `run_cmd`/`run_sql` use `encoding='utf-8', errors='replace'`.
  `run_cmd`/`run_sql` 改用 `encoding='utf-8', errors='replace'`。
- **[Robustness]** `_wait_db_ready()` fallback: loop-wait instead of single attempt.
  `_wait_db_ready()` 回退路径从单次尝试改为循环等待。

## V3.0.7

- **[Fix]** `restore` subcommand adds `--cache` / `--redis` / `--allow-xmlrpc` arguments; prints config update hint after restore.
  `restore` 子命令补充缓存和 XML-RPC 参数；恢复后打印配置更新提示。
- **[Fix]** `_write_lang_file()`: fallback to direct write when `os.replace` fails; temp file cleanup moved to `finally`.
  `_write_lang_file()` 增加 `os.replace` 失败回退路径；临时文件清理移入 `finally`。
- **[Fix]** `t()`: explicit `None` check instead of `or` chain, preventing false skip on empty-string translations.
  `t()` 翻译查找改为显式 `None` 检查。
- **[Fix]** `verify_http_challenge()` log `match` parameter uses `t("label_yes")` / `t("label_no")`.
  `verify_http_challenge()` 日志匹配参数改用翻译函数。

## V3.0.6

- **[i18n]** ~50 hardcoded Chinese/mixed-language messages migrated to `_MESSAGES` + `t()`.
  ~50 处硬编码中文消息迁移至 `_MESSAGES` + `t()`。
- **[Fix]** `show_status()` database label uses `t("label_database")`.
  `show_status()` 数据库标签改用翻译函数。
- **[Fix]** `update` subcommand adds `--php-version` argument.
  `update` 子命令补充 `--php-version` 参数。
- **[Security]** Language config file writes use atomic `_write_lang_file()` with 0600 permissions.
  语言配置文件写入改用原子写入（0600 权限）。
- **[Perf]** SHA-256/SHA-512 checksum chunk size increased from 4096 → 65536 bytes.
  SHA-256/SHA-512 校验 chunk size 从 4096 提升至 65536 字节。
- **[Misc]** Version number extracted to `__version__` constant; `--version` references it.
  版本号提取为 `__version__` 常量。
- **[Compat]** `_saved_lang` type annotation changed to comment form for Python 3.6–3.9 compatibility.
  `_saved_lang` 类型注解改为注释形式，兼容 Python 3.6–3.9。

## V3.0.5

- **[Feature]** Built-in i18n system: auto-detects language from `LANG` / `LC_ALL` / `LANGUAGE` / `WP_LANG` environment variables. Supports Chinese and English.
  内置 i18n 系统：通过环境变量自动切换中英双语。
- **[Feature]** Translations cover all `print()`, `logging.*`, and `argparse help` user-visible messages (~500 entries).
  翻译覆盖全部用户可见消息（~500 条）。
- **[Feature]** Language persistence: `--lang` writes preference to `/root/.wp_ssl_lang`; subsequent runs auto-detect.
  语言持久化：`--lang` 写入配置文件，后续运行自动检测。
- **[Feature]** Language change detection: interactive prompt when environment language differs from saved preference.
  语言变更检测：环境语言与已保存偏好不一致时交互提示。

## V3.0.4

- **[Fix]** `logrotate` `create` directive: auto-select log group by package manager (apt→adm, dnf/yum→root).
  logrotate `create` 指令按包管理器自动选择日志组。
- **[Feature]** Backup path supports `WP_BACKUP_DIR` env var and `--backup-dir` CLI argument.
  备份路径支持 `WP_BACKUP_DIR` 环境变量和 `--backup-dir` 参数。
- **[Misc]** MIT License header added to script.
  脚本顶部新增 MIT 协议声明。
- **[Misc]** `apply_nginx_config_safe()` finally block uses `logging.debug()` instead of silent `pass`.
  `apply_nginx_config_safe()` finally 块改用 `logging.debug()`。

## V3.0.3

- **[Feature]** `--allow-xmlrpc` flag: default continues to deny `xmlrpc.php`; when set, switches to rate-limited (1r/s burst=10) + PHP-FPM passthrough for Jetpack / mobile app support.
  新增 `--allow-xmlrpc` 标志：默认继续 deny；启用后改为速率限制 + PHP-FPM 透传。
- **[Security]** Dedicated `limit_req_zone` for xmlrpc when `--allow-xmlrpc` is set.
  `--allow-xmlrpc` 模式下新增独立速率限制 zone。
- **[Security]** Fail2Ban filter updated: xmlrpc matches 429 (rate-limited) instead of 200 when `--allow-xmlrpc` is active.
  Fail2Ban 规则联动更新：xmlrpc 匹配 429 而非 200。

## V3.0.2

- **[Fix]** `update`/`status` subcommands add `--cache`/`--redis` arguments.
  `update`/`status` 子命令补充 `--cache`/`--redis` 参数。
- **[Fix]** `setup_lemp_and_wp()` Redis service name compatible with Debian/Ubuntu `redis-server`.
  Redis 服务启用兼容 Debian/Ubuntu `redis-server`。
- **[Fix]** `_nginx_preamble()` eliminates extra blank lines.
  `_nginx_preamble()` 消除多余空行。
- **[Security]** `backup`/`restore`/`update` subcommands acquire global process lock.
  `backup`/`restore`/`update` 子命令入口增加全局进程锁。
- **[Fix]** `apply_nginx_config_safe()` backup failure path adds `logging.error` with root cause.
  `apply_nginx_config_safe()` 备份失败路径补充根因日志。

## V3.0.1

- **[Fix]** `wp-cron.php` location adds `fastcgi_pass` (was silently broken).
  `wp-cron.php` location 补充 `fastcgi_pass`。
- **[Fix]** `Permissions-Policy` `payment()` syntax corrected.
  `Permissions-Policy` `payment()` 语法修正。
- **[Fix]** `restore()` Popen variables pre-initialized to prevent `NameError` in `finally`.
  `restore()` Popen 变量预初始化。
- **[Fix]** `show_status()` Redis service name compatible with Debian/Ubuntu.
  `show_status()` Redis 服务名兼容 Debian/Ubuntu。
- **[Security]** `atomic_write()` cleans up `.aw_tmp` on exception path.
  `atomic_write()` 异常路径清理 `.aw_tmp` 残留。
- **[Security]** `_install_nginx_helper()` uses `json.dumps` instead of raw string concatenation.
  `_install_nginx_helper()` 改用 `json.dumps`。
- **[Security]** `find chmod 644` excludes `wp-config.php` to eliminate permission window.
  `find chmod 644` 排除 `wp-config.php`。

## V3.0.0

- **[Refactor]** `generate_https_config()` split into 10 independent fragment functions, each independently testable.
  `generate_https_config()` 拆分为 10 个独立片段函数。
- **[Feature]** `--skip-deps` flag: skip system package installation for advanced users with pre-installed dependencies.
  新增 `--skip-deps` 参数，允许跳过系统包安装。

## V2.9.9

- **[Fix]** `restore()` pipe deadlock: `stderr=DEVNULL` + process cleanup.
  `restore()` 管道死锁修复。
- **[Fix]** `uninstall()` cleans up logrotate config file.
  `uninstall()` 清理 logrotate 配置。
- **[Fix]** `update_config()` adds 3 missing OPcache parameters to match `deploy`.
  `update_config()` 补齐 OPcache 参数。
- **[Feature]** `show_status()` conditionally displays Redis service status.
  `show_status()` 条件显示 Redis 服务状态。
- **[Feature]** Brotli installation adds dnf/yum branch.
  Brotli 安装补充 dnf/yum 分支。

## V2.9.8

- **[Feature]** `--redis` enables Redis object cache (composable with FastCGI page cache).
  `--redis` 启用 Redis 对象缓存。
- **[Feature]** Brotli compression auto-detected; enabled globally when module is available.
  Brotli 压缩自动检测。
- **[Feature]** New `restore` subcommand: one-command restore from backup.
  新增 `restore` 子命令。
- **[Feature]** New `update` subcommand: hot-update config templates without touching data.
  新增 `update` 子命令。

## V2.9.7

- **[Security]** `wp-config.php` injected with 6 hardening constants (`DISALLOW_FILE_EDIT`, `FORCE_SSL_ADMIN`, etc.).
  `wp-config.php` 注入 6 项安全加固常量。
- **[Perf]** Nginx HTTPS config adds OCSP Stapling.
  Nginx 新增 OCSP Stapling。
- **[Security]** Nginx adds `Content-Security-Policy-Report-Only` header.
  Nginx 新增 CSP-RO 响应头。
- **[Feature]** Auto-configured logrotate for per-domain Nginx logs.
  新增 logrotate 自动配置。
- **[Security]** Database grants reduced from `GRANT ALL` to minimal privilege set.
  数据库授权从 `GRANT ALL` 收窄为最小权限集。

## V2.9.6

- **[Fix]** `run()` finally: `_rollback_deploy` exception protection ensures cleanup always runs.
  `run()` 中回滚异常保护，确保清理必达。
- **[Security]** `patch_php_fpm_pool_user()` uses lambda to eliminate backreference injection.
  `patch_php_fpm_pool_user()` 消除反向引用注入隐患。
- **[Security]** `wp-config.php` written via `_safe_write_file(mode=0o440)`.
  `wp-config.php` 改用原子写入（0440 权限）。

## V2.9.5

- **[Security]** Domain length validation: 253-char DNS limit.
  域名长度校验：253 字符 DNS 上限。
- **[Security]** `prctl(PR_SET_DUMPABLE, 0)` blocks `/proc/self/mem` reads.
  `prctl(PR_SET_DUMPABLE, 0)` 阻止内存读取。
- **[Misc]** Log output switched from stdout to stderr.
  日志输出从 stdout 切换到 stderr。
- **[Security]** New `_safe_write_file()` atomic write helper eliminates permission windows.
  新增 `_safe_write_file()` 原子写入辅助方法。
- **[Security]** All credential/password files use atomic write with immediate 0600 permissions.
  所有凭据文件改用原子写入。
- **[Feature]** `run_cmd` adds `sensitive` parameter for log redaction.
  `run_cmd` 新增 `sensitive` 参数用于日志脱敏。
- **[Feature]** `--version` global argument.
  新增 `--version` 全局参数。

## V2.9.4

- **[Fix]** `backup()` now reads `cfg.db_root_pass_input` (was silently ignored since V2.9.3).
  `backup()` 修复 `--db-root-pass` 实际未读取的问题。
- **[Fix]** `_wait_db_ready()`: skip `mysqladmin` loop when binary is not available.
  `_wait_db_ready()` 在 `mysqladmin` 不可用时立即跳出。
- **[Fix]** `backup()` finally: only `kill()` processes that are still running (`poll()` check).
  `backup()` 仅对存活进程调用 `kill()`。
- **[Fix]** `backup()` mysqldump stderr: async read via `concurrent.futures` eliminates pipe deadlock.
  `backup()` mysqldump stderr 异步读取，消除管道死锁。
- **[Security]** SSL ciphers replaced with Mozilla Intermediate recommended list (pure TLS 1.2).
  SSL 密码套件替换为 Mozilla 推荐列表。
- **[Security]** `ssl_session_tickets off` added.
  补充 `ssl_session_tickets off`。
- **[Feature]** `install_packages()` adds WordPress-recommended PHP extensions: `php-curl`, `php-zip`, `php-intl`, `php-opcache`.
  安装 WordPress 官方推荐的 PHP 扩展。
- **[Feature]** PHP ini patches add `memory_limit=256M`, `max_execution_time=300`, OPcache settings.
  PHP 配置补充重型插件所需参数和 OPcache 设置。

## V2.9.3

- **[Fix]** `inject_salts()` regex and token length corrected.
  `inject_salts()` 正则和 token 长度修正。
- **[Fix]** `backup()` directory permissions explicit `chmod 0700`.
  `backup()` 备份目录显式 `chmod 0700`。
- **[Fix]** `--db-root-pass` added to common arguments for `backup`/`renew`/`status`.
  `--db-root-pass` 提升为公共参数。
- **[Security]** Nginx `limit_req_zone` for `wp-login.php` (1r/s, burst=5 nodelay).
  Nginx 对 `wp-login.php` 增加速率限制。
- **[Misc]** Systemd renewal service adds `StandardOutput/StandardError=journal`.
  续期服务补充 journal 日志输出。

## V2.9.2

- **[Security]** Nginx `server_tokens off`.
  Nginx 隐藏版本号。
- **[Security]** Nginx blocks PHP execution in `wp-content/uploads/`.
  Nginx 禁止 uploads 目录执行 PHP。
- **[Security]** Nginx restricts `wp-cron.php` to localhost.
  Nginx 限制 `wp-cron.php` 仅本机访问。
- **[Security]** `wp-config.php` enforced to `chmod 0440`.
  `wp-config.php` 强制 `chmod 0440`。

## V2.9.1

- **[Security]** Core dump disabled: `RLIMIT_CORE=0`.
  禁用 Core dump。
- **[Security]** Password entropy increased from 24 → 32 bytes.
  密码随机熵提升至 32 字节。
- **[Security]** `_mysql_escape_value()` rejects ASCII control characters.
  `_mysql_escape_value()` 拦截控制字符。
- **[Security]** Root password not saved to disk by default; `--persist-root-pwd` required.
  Root 密码默认不落盘。
- **[Security]** Nginx adds `wp-config.php` deny rule.
  Nginx 增加 `wp-config.php` 拦截规则。
- **[Security]** Temp credential directory moved to `/run/wp-bootstrap` (tmpfs, 0700).
  临时凭据目录迁移至 tmpfs。
- **[Security]** `apply_nginx_config_safe()` introduces `flock` to eliminate TOCTOU race.
  `apply_nginx_config_safe()` 引入 `flock`。
- **[Security]** Certbot and global deployment file-level locks.
  Certbot 和全局部署增加文件级锁。

## V2.8.0

- **[Security]** New `_mysql_escape_value()` for defense-in-depth SQL injection prevention.
  新增 `_mysql_escape_value()` SQL 注入纵深防御。
- **[Fix]** `_recover_existing_db_pass()` regex supports PHP-escaped passwords.
  `_recover_existing_db_pass()` 正则支持 PHP 转义后的密码。
- **[Fix]** `backup()` subprocess pipe FD leak fixed.
  `backup()` 子进程管道文件描述符泄漏修复。
- **[Fix]** `atomic_write()` temp file suffix changed to `.aw_tmp`/`.aw_bak` to avoid namespace collision.
  `atomic_write()` 临时文件后缀更改避免命名冲突。
- **[Fix]** `verify_http_challenge()` detects Nginx listen address from config.
  `verify_http_challenge()` 从 Nginx 配置探测 listen 地址。
- **[Fix]** `--db-wait-timeout` validates positive integer.
  `--db-wait-timeout` 增加正整数校验。
- **[Fix]** `_detect_webroot_base()` prioritizes `/etc/os-release` for distro detection.
  `_detect_webroot_base()` 优先从 `/etc/os-release` 识别发行版。

## V2.7.x

- **[Feature]** WP-CLI multi-mirror download: GitHub raw → jsDelivr CDN fallback.
  WP-CLI 多镜像下载。
- **[Feature]** `--db-wait-timeout` CLI argument and `WP_DB_WAIT_TIMEOUT` env var.
  新增数据库等待超时参数。
- **[Security]** `.cnf` password values double-quoted to prevent truncation by `#` or `;`.
  `.cnf` 密码值加双引号防截断。
- **[Security]** `patch_wp_config()` PHP-escapes replacement values.
  `patch_wp_config()` 对替换值做 PHP 转义。
- **[Fix]** Idempotent re-run: recovered password verified against database before reuse.
  幂等重跑：恢复密码验证数据库后复用。
- **[Fix]** WP-CLI installation uses atomic copy+rename.
  WP-CLI 安装改用原子写入。

## V2.6

- **[Feature]** `patch_php_ini_line()` supports uncommenting `;`-commented directives and appending missing ones.
  `patch_php_ini_line()` 支持取消注释和追加。
- **[Feature]** FastCGI Cache: auto-installs `nginx-helper` plugin via WP-CLI for cache purge on publish.
  FastCGI Cache 自动安装 nginx-helper 插件。
- **[Feature]** External database support: `--db-host` / `WP_DB_HOST`.
  外置数据库支持。

## V2.5

- **[Feature]** Webroot path adapts to distro: Debian→`/var/www/html`, RHEL→`/usr/share/nginx/html`.
  Webroot 路径跨发行版适配。
- **[Feature]** `--db-root-pass` / `WP_DB_ROOT_PASS` for pre-secured MariaDB.
  支持外部传入 MariaDB root 密码。
- **[Fix]** Stale lock file auto-cleanup on `SIGKILL` remnant detection.
  锁文件残留自动清理。

## V2.4

- **[Feature]** `backup --keep N` auto-removes old backups beyond retention count.
  备份清理策略。
- **[Feature]** `--php-version` forces specific PHP-FPM version.
  支持强制指定 PHP 版本。

## V2.3

- **[Feature]** Fail2Ban integration: auto-configured WordPress brute-force protection.
  Fail2Ban 集成。
- **[Feature]** `backup` subcommand.
  新增 `backup` 子命令。
- **[Feature]** `--cache fastcgi` enables Nginx FastCGI page cache.
  FastCGI 页面缓存。

## V2.2

- **[Security]** Nginx blocks `xmlrpc.php`; adds `Permissions-Policy` header.
  Nginx 封禁 `xmlrpc.php` 并新增安全头。
- **[Feature]** `renew --force` flag; certificate expiry pre-check logging.
  续期增加 `--force` 标志和到期预检日志。
- **[Feature]** `status` subcommand.
  新增 `status` 子命令。

## V2.1

- **[Refactor]** CLI subcommands (`deploy` / `renew` / `uninstall`) replace legacy `--uninstall` flag.
  CLI 子命令化。
- **[Fix]** Nginx `.pending` temp file cleanup in `apply_nginx_config_safe()` finally block.
  Nginx `.pending` 临时文件清理。
