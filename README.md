# WP-SSL-Bootstrap

一条命令完成 WordPress + HTTPS 全站部署。
One command to deploy WordPress with HTTPS, auto-renewal, and production-grade security.

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## Features

- **Zero-config HTTPS** — Let's Encrypt → ZeroSSL automatic failover with EAB auto-negotiation; ECDSA (P-256) preferred with RSA fallback; certbot error classification with circuit-breaker logic; Snap/certbot-auto/standard installs auto-detected
- **Two-phase deployment** — `deploy --skip-ssl` for HTTP-only first, then `enable-ssl` when DNS is ready; or full HTTPS in one shot
- **Interactive wizard** — no subcommand? TTY users get a guided menu for domain, email, SSL policy, and external database
- **Multi-distro** — EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux) / Ubuntu / Debian; dnf5 (EL10+) auto-detected; Redis/Valkey multi-package fallback
- **Automatic PHP upgrade** — detects installed PHP version; auto-upgrades to 8.4 when below 8.3 minimum. EL via EPEL + Remi repo + `dnf module enable`; Ubuntu via Ondrej PPA; Debian via Sury DPA. Migrates custom `php.ini` settings, disables old PHP-FPM, restarts new service. Covers EL8–10, Ubuntu 22.04–24.04, Debian 12–13.
- **Database security** — auth_socket/unix_socket auto-detection; credentials never exposed in process list (`--defaults-extra-file`); admin password via environment variable (not `/proc/cmdline`)
- **Multi-source download** — Chinese mirror + global fallback with SHA-256 verification; cross-source hash verification for self-update; WP-CLI fallback when tar.gz sources fail
- **Strict permissions** — wp-config.php locked to 0440 from creation; `O_NOFOLLOW` on all atomic write paths; SELinux booleans auto-configured
- **Unified security entry points** — `_safe_rmtree` (parent whitelist + symlink block), `_safe_copy2` (bidirectional symlink check), `_safe_mkstemp` (`O_NOFOLLOW` + `fchmod`), `_verify_gzip_integrity` (pre-extract CRC check), `_safe_extract_tar` (path traversal + symlink member + timeout protection). 45 call sites across the script use these entry points.
- **Git tag-pinned builds** — srcache/Brotli compilation modules pinned to git tags (not commit hashes), immune to GitHub shallow-clone restrictions
- **Nginx hardening** — rate limiting on wp-login.php + admin-ajax.php, HSTS, CSP enforcement (`frame-ancestors` / `upgrade-insecure-requests`), wp-config/uploads/xmlrpc/wp-includes deny, HTTP method filtering, cert SAN / server_name auto-alignment, dynamic module load error cascade auto-repair (ABI mismatch → reinstall → remove → orphaned directive cleanup), proactive minor-version upgrades, FastCGI cache (optional), Redis srcache full-page cache (optional), Brotli (optional), HTTP/3 QUIC (optional)
- **Firewall auto-config** — ufw (Ubuntu), firewalld (EL), nftables (Debian 12/13) auto-detected and configured; ports 80/443 TCP opened with persistence; nftables uses dedicated `inet wp_ssl` table (policy accept, won't lock SSH)
- **Fail2Ban** — auto-configured WordPress brute-force protection with progressive banning (24h + escalation)
- **Auto-renewal** — systemd timer with frequency auto-tuned to certificate lifetime (daily for 90-day, every 8h for 47-day, every 4h for 6-day certs), `--cert-name` precision renewal, persistent deploy hook, post-renewal Nginx certificate verification; renewal failure notification via `--notify-webhook` or auto-installed journal/email fallback (never silent)
- **Backup & restore** — one-command backup (DB + files + Nginx + Fail2Ban/logrotate + Let's Encrypt certs); atomic DB restore via RENAME TABLE; external DB retry with exponential backoff
- **Config hot-update** — `update` subcommand applies new templates without touching data; managed plugin safe-upgrade with health-check rollback
- **Redis object cache** — optional `--redis`, composable with FastCGI page cache; PHP Redis source-compile fallback; Valkey (EL10+) auto-detection
- **Redis full-page cache** — optional `--cache redis`, srcache-nginx-module based; auto-compiles 5 OpenResty dynamic modules with ABI verification; auto-degrades to FastCGI on failure
- **HTTP/3 QUIC** — optional `--http3`; auto-detects Nginx `http_v3` module; auto-opens UDP 443 firewall port; multi-site `reuseport` sharing; silently ignored when unsupported
- **`--no-*` reverse switches** — `--no-redis` / `--no-optimize` / `--no-cloudflare` / `--no-http3` / `--no-allow-xmlrpc` to explicitly disable auto-detected features during `update`/`enable-ssl`/`restore`
- **Performance tuning** — PHP-FPM pool auto-sized by RAM, MariaDB InnoDB tuning, BBR + TCP sysctl, swap auto-creation, Nginx `open_file_cache` (`--optimize`)
- **Self-healing** — 15 common failure scenarios auto-diagnosed and repaired: missing logrotate/curl auto-installed, failed DB auto-restarted, `nginx -t` errors auto-fixed (stale includes, duplicate default_server, server_names_hash_bucket_size), uninstall file deletion retried with `chattr -i`, PHP-FPM/Redis failures auto-diagnosed via config test and journal inspection
- **Full-stack security hardening** — 55 security checks across 6 components, verified against OWASP / CIS Benchmark / official docs: PHP (expose_php, display_errors, disable_functions, open_basedir, session cookie security, allow_url_include), MariaDB (bind-address, local-infile, skip-symbolic-links, secure-file-priv, skip-show-database), Redis (bind localhost, rename-command, disable THP), OS sysctl (tcp_syncookies, rp_filter, accept_redirects, protected_hardlinks), systemd (NoNewPrivileges, PrivateTmp), WordPress (WP_DEBUG=false). All applied automatically via `update`.
- **OpenSSL/Python SSL resilience** — Three-layer defense against `openssl-libs` upgrade breaking Python `_ssl.so`: L0 compile-time vs runtime version comparison (PEP 644) with auto `python3-libs` upgrade; L1 `_try_repair_openssl()` with subprocess verification after each strategy; L2 curl/wget fallback. Standalone `fix-openssl` subcommand for manual diagnosis.
- **Component lifecycle** — Certbot snap migration with pip venv fallback; Redis/Valkey version-aware upgrades; WP-CLI auto-update with SHA-512 verification; fail2ban version detection with legacy compat; short-lived certificate auto-detection with timer frequency adjustment
- **Dual-CA failover** — ZeroSSL (primary) + Let's Encrypt (fallback) with EAB auto-negotiation; ECC→RSA auto-downgrade; rate-limit detection; `migrate-ssl` subcommand for CA migration
- **ntfy.sh zero-config webhook** — Interactive wizard offers one-click ntfy.sh setup with auto-generated topic; also supports Slack/DingTalk/Feishu JSON webhooks
- **Atomic file writes** — All credential and config writes use `_write_bytes_atomic` (tempfile → fsync → os.replace) following Python official POSIX atomic semantics; signal-safe shutdown with 21 polling points
- **WordPress Cron offload** — systemd 15-min timer replaces per-request wp-cron.php
- **Bilingual UI** — Chinese/English; auto-detected from locale, persistable via `--lang`
- **Smart domain handling** — `www.example.com` auto-normalized to `example.com`; subdomains skip `www` variant; single-site auto domain inference
- **External database** — `--db-host` for RDS/remote MySQL, auto SSL transport, `--no-db-ssl` for LAN
- **Idempotent** — safe to re-run; existing passwords and databases are preserved
- **Full purge** — `uninstall --purge` drops DB + files + certs; `--revoke` revokes the certificate

## Quick Start

```bash
# Interactive wizard (just run without arguments)
sudo python3 wp_ssl_bootstrap.py

# Or specify everything on the command line
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com
```

With FastCGI cache + Redis + HTTP/3:

```bash
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --cache fastcgi --redis --http3
```

Two-phase deployment (HTTP first, SSL later):

```bash
# Phase 1: deploy without SSL (DNS not ready yet)
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --skip-ssl

# Phase 2: sign certificate when DNS is ready
sudo python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com --email admin@example.com
```

After deployment, visit `https://example.com` to complete the WordPress setup wizard.

## Requirements

- Root access
- Python 3.6+
- Domain with DNS A/AAAA records pointing to your server
- Ports 80 and 443 open

All other dependencies (Nginx, PHP-FPM, MariaDB, certbot, etc.) are installed automatically.

## Subcommands

| Command | Description |
|---|---|
| `deploy` | Full deployment: deps → WordPress → DB → SSL → production Nginx |
| `enable-ssl` | Sign SSL certificate for an existing HTTP-only site and switch to HTTPS |
| `renew` | Certificate renewal check (called daily by systemd timer) |
| `status` | Show certificate expiry, service health, disk space (works without `--domain` when single site) |
| `backup` | Back up DB + files + Nginx config + Fail2Ban/logrotate + Let's Encrypt certs |
| `restore` | Restore from backup with atomic DB swap (auto-selects latest, or `--from PATH`) |
| `update` | Hot-update config templates and safely upgrade managed plugins |
| `self-update` | Download latest script with cross-source SHA-256 verification and atomic replace |
| `migrate-ssl` | Migrate certificate between CAs (e.g. Let's Encrypt → ZeroSSL) |
| `fix-openssl` | Diagnose and repair OpenSSL/Python SSL library mismatch (no `--domain` needed) |
| `uninstall` | Remove daemon components; `--purge` for full cleanup, `--revoke` to revoke certificate |

## Options

```
--domain DOMAIN           Site domain (env: WP_DOMAIN)
--email EMAIL             Contact email for cert (env: WP_EMAIL)
--db-host HOST            Database host, default: localhost (env: WP_DB_HOST)
--db-root-pass PASS       MariaDB/MySQL root password (env: WP_DB_ROOT_PASS)
--no-db-ssl               Disable SSL for external DB (for LAN/VPC direct connect)
--db-wait-timeout SECS    DB readiness timeout (default: 30s local, 60s external)
--cache {none,fastcgi,redis}    Nginx cache mode (redis = srcache full-page cache)
--redis                   Enable Redis object cache
--cloudflare              Fetch Cloudflare IP ranges and configure real IP restoration
--allow-xmlrpc            Allow xmlrpc.php with rate limiting (default: deny)
--wp-auto-install         Complete WordPress setup wizard automatically via WP-CLI
--optimize                Enable Nginx open_file_cache for static-heavy sites
--http3                   Enable HTTP/3 QUIC (requires Nginx http_v3 module)
--skip-ssl                Deploy HTTP-only (skip SSL); use enable-ssl later
--force                   Force certificate renewal regardless of expiry (renew)
--persist-root-pwd        Save MariaDB root password to disk
--zerossl-eab-kid KID     ZeroSSL EAB Key ID for backup CA (env: WP_ZEROSSL_EAB_KID)
--zerossl-eab-hmac-key    ZeroSSL EAB HMAC Key (env: WP_ZEROSSL_EAB_HMAC_KEY)
--notify-webhook URL      Webhook URL for renewal failure alerts (env: WP_NOTIFY_WEBHOOK)
--no-pre-backup           Skip automatic pre-operation backup
--php-version X.Y         Force specific PHP version (default: auto-upgrade to 8.4 if <8.3)
--skip-deps               Skip package installation
--backup-dir PATH         Backup root directory (default: /root/backups)
--keep N                  Number of backups to retain (backup subcommand)
--dry-run                 Simulate without making changes
--staging                 Use Let's Encrypt staging environment
--no-staging              Override inherited --staging, force production CA
--no-redis                Explicitly disable Redis (override auto-detection)
--no-optimize             Explicitly disable Nginx optimizations
--no-cloudflare           Explicitly disable Cloudflare Real IP
--no-http3                Explicitly disable HTTP/3 QUIC
--no-allow-xmlrpc         Explicitly block xmlrpc.php
--purge                   Full cleanup: drop DB + remove files + delete certs (uninstall)
--revoke                  Revoke and delete Let's Encrypt certificate (uninstall)
--lang {zh,en}            Interface language (persisted after first use)
--quiet                   Only WARNING and above
```

## Examples

```bash
# Status check (--domain auto-inferred when single site)
sudo python3 wp_ssl_bootstrap.py status

# Backup (keep 7 copies)
sudo python3 wp_ssl_bootstrap.py backup --domain example.com --keep 7

# Restore from latest (atomic DB swap)
sudo python3 wp_ssl_bootstrap.py restore --domain example.com

# Hot-update configs + safely upgrade managed plugins
sudo python3 wp_ssl_bootstrap.py update --domain example.com --cache fastcgi --redis

# Force certificate renewal
sudo python3 wp_ssl_bootstrap.py renew --domain example.com --force

# Switch from staging to production CA
sudo python3 wp_ssl_bootstrap.py renew --domain example.com --force --no-staging

# HTTP-only deploy, then add SSL later
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --skip-ssl --wp-auto-install
sudo python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com --email admin@example.com

# External database
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --db-host rds.example.com --db-root-pass 'YourPassword' \
  --db-wait-timeout 120

# Cloudflare reverse proxy + auto-complete WordPress wizard + webhook
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --cloudflare --http3 --wp-auto-install \
  --notify-webhook https://hooks.slack.com/services/xxx

# Redis full-page cache (srcache) instead of FastCGI
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --cache redis

# Enable HTTP/3 on existing site
sudo python3 wp_ssl_bootstrap.py update --domain example.com --http3

# Disable auto-detected Redis during update
sudo python3 wp_ssl_bootstrap.py update --domain example.com --no-redis

# ZeroSSL as backup CA (auto-failover from Let's Encrypt)
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --zerossl-eab-kid YOUR_KID --zerossl-eab-hmac-key YOUR_HMAC

# Update to latest script version
sudo python3 wp_ssl_bootstrap.py self-update

# Uninstall (keeps data + certs)
sudo python3 wp_ssl_bootstrap.py uninstall --domain example.com

# Full purge (irreversible — drops DB, removes files and certs)
sudo python3 wp_ssl_bootstrap.py uninstall --domain example.com --purge
```

## Security Design

- **Cryptographic credentials** — `secrets` module for all passwords and salts
- **Zero CLI leakage** — DB passwords via `--defaults-extra-file` temp files (0600, tmpfs); admin password via environment variable; sensitive args scrubbed from `/proc/cmdline`
- **Zero SQL injection** — strict character whitelist on all identifiers and passwords; control character interception in `run_sql()`
- **Atomic writes** — all config files with `O_NOFOLLOW` + `fsync` + backup/rollback; symlink targets refused
- **wp-config.php hardening** — `DISALLOW_FILE_EDIT`, `FORCE_SSL_ADMIN`, `DISALLOW_UNFILTERED_HTML`, etc.
- **Core dump disabled** — `RLIMIT_CORE=0` + `PR_SET_DUMPABLE=0`
- **Nginx defense-in-depth** — `server_tokens off`, uploads PHP blocked, wp-cron localhost-only, login rate limiting, cert SAN / server_name alignment
- **Certbot circuit-breaker** — non-CA fatal errors break out immediately; ECDSA preferred with per-CA RSA fallback; ZeroSSL automatic failover
- **Supply-chain protection** — self-update uses dual hardcoded sources with mandatory cross-source SHA-256 verification
- **Webhook SSRF protection** — HTTPS enforced; private IPs, internal domains, and IPv4-mapped IPv6 blocked
- **Backup integrity** — gzip validation, `Dump completed` EOF marker check, path traversal detection in tar archives
- **Secure tar extraction** — `_safe_extract_tar` enforces `--no-same-owner --no-same-permissions`, filters `..` / absolute paths / symlink members, applies timeout and artifact verification across all 6 extraction sites
- **Unified `rmtree` / `copy` / `mkstemp`** — all filesystem operations use hardened wrappers with parent-directory whitelists, bidirectional symlink checks, and `O_NOFOLLOW` enforcement

## Known Limitations

- **xmlrpc.php** blocked by default. Use `--allow-xmlrpc` for Jetpack / mobile app.
- **WordPress Multisite** not supported (single instance per domain).
- **Wildcard certificates** not supported (webroot validation only).

## Credentials

After deployment, credentials are saved to `/root/.wp_credentials_<domain>.txt` (mode 0600). **Keep it safe.**

## File Structure

```
/etc/nginx/conf.d/<domain>.conf                 Nginx HTTPS config
/etc/systemd/system/<prefix>-ssl.service         Renewal service
/etc/systemd/system/<prefix>-ssl.timer           Daily renewal timer
/etc/systemd/system/<prefix>-ssl-notify-fail.*   Renewal failure notification
/etc/systemd/system/<prefix>-wp-cron.*           WordPress Cron timer
/etc/systemd/system/<prefix>-db-optimize.*       Weekly DB optimize timer
/etc/fail2ban/filter.d/wordpress-*.conf          Fail2Ban filter
/etc/fail2ban/jail.d/wordpress-*.conf            Fail2Ban jail
/etc/logrotate.d/nginx-wp-*                      Log rotation
/root/.wp_credentials_*.txt                      Site credentials
```

## License

[MIT](./LICENSE)

---

<a id="中文"></a>

## 功能特性

- **零配置 HTTPS** — Let's Encrypt → ZeroSSL 自动容灾（EAB 自动协商）；优先 ECDSA P-256 密钥，不支持时自动降级 RSA；certbot 错误分类熔断；自动探测 Snap/certbot-auto/标准安装
- **两阶段部署** — `deploy --skip-ssl` 先部署 HTTP，DNS 就绪后 `enable-ssl` 补签证书；或一步到位全量 HTTPS
- **交互式向导** — 不指定子命令时自动进入 TTY 引导菜单，选择域名、邮箱、SSL 策略和外置数据库配置
- **多发行版** — EL7–10（RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux）/ Ubuntu / Debian；自动识别 dnf5（EL10+）；Redis/Valkey 多包名自动适配
- **PHP 自动升级** — 检测已安装 PHP 版本，低于 8.3 时自动升级到 8.4。EL 通过 EPEL + Remi 仓库 + `dnf module enable`；Ubuntu 通过 Ondrej PPA；Debian 通过 Sury DPA。升级后自动迁移自定义 `php.ini` 设置，停用旧版 PHP-FPM，重启新版服务。覆盖 EL8–10、Ubuntu 22.04–24.04、Debian 12–13
- **数据库安全** — auth_socket/unix_socket 自适应；凭据不暴露于进程列表（`--defaults-extra-file`）；管理员密码通过环境变量传递（不经 `/proc/cmdline`）
- **多源下载** — 中文镜像 + 全球主源 fallback，SHA-256 校验；self-update 双源交叉哈希验证；WP-CLI 兜底
- **严格权限** — wp-config.php 创建即 0440；所有原子写入路径 `O_NOFOLLOW` 防符号链接攻击；SELinux 布尔值自动配置
- **统一安全入口** — `_safe_rmtree`（父目录白名单 + 符号链接阻断）、`_safe_copy2`（双向符号链接检查）、`_safe_mkstemp`（`O_NOFOLLOW` + `fchmod`）、`_verify_gzip_integrity`（解压前 CRC 校验）、`_safe_extract_tar`（路径遍历 + 符号链接成员 + 超时保护）。全脚本 45 处调用统一走安全入口
- **Git tag 固定构建** — srcache / Brotli 编译模块使用 git tag 固定版本（非 commit hash），不受 GitHub 浅克隆限制
- **Nginx 加固** — wp-login.php + admin-ajax.php 速率限制、HSTS、CSP 强制执行、wp-config/uploads/xmlrpc/wp-includes 拦截、HTTP 方法过滤、证书 SAN 与 server_name 自动对齐、FastCGI 缓存（可选）、Redis srcache 全页缓存（可选）、Brotli（可选）、HTTP/3 QUIC（可选）
- **防火墙自动配置** — 自动检测并配置 ufw（Ubuntu）/ firewalld（EL）/ nftables（Debian 12/13）；开放 80/443 TCP 并持久化；nftables 使用独立 `inet wp_ssl` 表（policy accept，不锁 SSH）
- **Fail2Ban** — 自动配置 WordPress 暴力破解防护，渐进式封禁（24h + 递增）
- **自动续期** — systemd 定时器频率随证书寿命自适应（90 天每日、47 天每 8 小时、6 天每 4 小时），`--cert-name` 精准续期，持久化 deploy hook，续期后自动验证 Nginx 证书加载；失败通知：`--notify-webhook` 或自动安装的 journal/email 兜底（永不静默）
- **备份恢复** — 一键备份（数据库 + 文件 + Nginx + Fail2Ban/logrotate + Let's Encrypt 证书）；RENAME TABLE 原子恢复；外置 DB 指数退避重试
- **配置热更新** — `update` 子命令应用新模板，不触碰数据；托管插件安全升级 + 健康检查回滚
- **Redis 对象缓存** — 可选 `--redis`，可与 FastCGI 页面缓存叠加；PHP Redis 源码编译兜底；Valkey（EL10+）自动检测
- **Redis 全页缓存** — 可选 `--cache redis`，基于 srcache-nginx-module；自动编译 5 个 OpenResty 动态模块并做 ABI 验证；编译失败自动降级 FastCGI
- **HTTP/3 QUIC** — 可选 `--http3`；自动探测 Nginx `http_v3` 模块；自动开放 UDP 443 防火墙端口；多站点共享 `reuseport`；不支持时静默忽略
- **`--no-*` 反向开关** — `--no-redis` / `--no-optimize` / `--no-cloudflare` / `--no-http3` / `--no-allow-xmlrpc` 可在 `update`/`enable-ssl`/`restore` 中显式禁用自动探测到的功能
- **性能调优** — PHP-FPM 按内存动态调参、MariaDB InnoDB 调优、BBR + TCP sysctl、Swap 自动创建、Nginx `open_file_cache`（`--optimize`）
- **自愈能力** — 15 种常见故障场景自动诊断修复：缺失 logrotate/curl 自动安装、DB 超时自动重启、`nginx -t` 错误自动修复（失效 include / 重复 default_server / server_names_hash_bucket_size）、卸载删除失败自动 `chattr -i` 重试、PHP-FPM/Redis 故障自动诊断（配置测试 + journal 检查）
- **全组件安全加固** — 对照 OWASP / CIS Benchmark / 官方文档，55 项安全检查覆盖 6 个组件：PHP（expose_php / display_errors / disable_functions / open_basedir / session cookie 安全 / allow_url_include）、MariaDB（bind-address / local-infile / skip-symbolic-links / secure-file-priv / skip-show-database）、Redis（bind 本地 / rename-command / 禁用 THP）、OS sysctl（tcp_syncookies / rp_filter / accept_redirects / protected_hardlinks）、systemd（NoNewPrivileges / PrivateTmp）、WordPress（WP_DEBUG=false）。全部通过 `update` 自动生效
- **OpenSSL/Python SSL 韧性** — 三层防线应对 `openssl-libs` 升级破坏 Python `_ssl.so`：L0 编译时/运行时版本比较（PEP 644）自动 `python3-libs` 升级；L1 `_try_repair_openssl()` 子进程验证修复；L2 curl/wget 降级。`fix-openssl` 独立子命令手动诊断
- **组件生命周期** — Certbot snap 迁移 + pip venv 兜底；Redis/Valkey 版本感知升级；WP-CLI 自动更新 + SHA-512 校验；fail2ban 版本探测 + 旧版兼容；短寿命证书自动检测 + timer 频率调整
- **双 CA 容灾** — ZeroSSL (主) + Let's Encrypt (降级) 自动切换，EAB 凭据自动获取，ECC→RSA 自动降级，速率限制检测，`migrate-ssl` 子命令支持 CA 迁移
- **ntfy.sh 零配置 webhook** — 交互式向导一键配置 ntfy.sh 通知，自动生成主题名；同时支持 Slack/DingTalk/飞书 JSON webhook
- **原子文件写入** — 所有凭据和配置写入使用 `_write_bytes_atomic`（tempfile → fsync → os.replace），符合 Python 官方 POSIX 原子语义；信号安全关闭 + 21 个轮询点
- **WordPress Cron 卸载** — systemd 15 分钟定时器替代每请求触发 wp-cron.php
- **双语界面** — 中英文自动切换，`--lang` 持久化
- **域名智能处理** — 输入 `www.example.com` 自动归一为 `example.com`；子域名自动跳过 `www` 变体；单站点自动推断域名
- **外置数据库** — `--db-host` 支持 RDS/远程 MySQL，自动 SSL 传输，`--no-db-ssl` 支持内网直连
- **幂等重跑** — 安全重复执行；已有密码和数据库自动保留
- **彻底清理** — `uninstall --purge` 删除数据库 + 文件 + 证书；`--revoke` 吊销证书

## 快速开始

```bash
# 交互式向导（直接运行即可）
sudo python3 wp_ssl_bootstrap.py

# 或在命令行指定所有参数
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com
```

启用 FastCGI 缓存 + Redis + HTTP/3：

```bash
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --cache fastcgi --redis --http3
```

两阶段部署（先 HTTP，后补签 SSL）：

```bash
# 阶段 1: 不签证书先部署（DNS 尚未生效）
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --skip-ssl

# 阶段 2: DNS 就绪后签发证书
sudo python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com --email admin@example.com
```

部署完成后，访问 `https://example.com` 完成 WordPress 安装向导。

## 系统要求

- Root 权限
- Python 3.6+
- 域名 A/AAAA 记录已指向服务器
- 80 和 443 端口开放

其他依赖（Nginx、PHP-FPM、MariaDB、certbot 等）由脚本自动安装。

## 子命令

| 命令 | 说明 |
|---|---|
| `deploy` | 完整部署：安装依赖 → 下载 WordPress → 配置数据库 → 签发 SSL → 挂载生产 Nginx |
| `enable-ssl` | 为已部署的 HTTP-only 站点签发 SSL 证书并切换至 HTTPS |
| `renew` | 证书续期检查（systemd 定时器每日调用） |
| `status` | 查看证书到期、服务状态、磁盘空间（单站点时可省略 `--domain`） |
| `backup` | 备份数据库 + 站点文件 + Nginx 配置 + Fail2Ban/logrotate + Let's Encrypt 证书 |
| `restore` | 从备份原子恢复（自动选最新，或 `--from 路径`） |
| `update` | 热更新配置模板，安全升级托管插件 |
| `self-update` | 下载最新版脚本，双源交叉 SHA-256 校验后原子替换 |
| `migrate-ssl` | 在 CA 之间迁移证书（如 Let's Encrypt → ZeroSSL） |
| `fix-openssl` | 诊断并修复 OpenSSL/Python SSL 库兼容性问题（无需 `--domain`） |
| `uninstall` | 卸载守护组件；`--purge` 彻底清理，`--revoke` 吊销证书 |

## 常用参数

```
--domain DOMAIN           站点域名（环境变量: WP_DOMAIN）
--email EMAIL             证书申请邮箱（环境变量: WP_EMAIL）
--db-host HOST            数据库主机，默认 localhost（环境变量: WP_DB_HOST）
--db-root-pass PASS       MariaDB/MySQL root 密码（环境变量: WP_DB_ROOT_PASS）
--no-db-ssl               禁用外置数据库 SSL 传输（内网直连场景）
--db-wait-timeout SECS    数据库就绪等待超时（默认: 本地 30s / 外置 60s）
--cache {none,fastcgi,redis}    Nginx 缓存模式（redis = srcache 全页缓存）
--redis                   启用 Redis 对象缓存
--cloudflare              从 Cloudflare API 获取 IP 段并配置真实 IP 还原
--allow-xmlrpc            放开 xmlrpc.php（默认拒绝，启用后为速率限制透传）
--wp-auto-install         通过 WP-CLI 自动完成 WordPress 安装向导
--optimize                启用 Nginx open_file_cache，适合静态资源密集站点
--http3                   启用 HTTP/3 QUIC 协议（需 Nginx http_v3 模块）
--skip-ssl                仅部署 HTTP（跳过 SSL）；后续用 enable-ssl 补签
--force                   强制续期证书，忽略到期时间（renew）
--persist-root-pwd        将 MariaDB root 密码保存至磁盘
--zerossl-eab-kid KID     ZeroSSL EAB Key ID，备用 CA（环境变量: WP_ZEROSSL_EAB_KID）
--zerossl-eab-hmac-key    ZeroSSL EAB HMAC Key（环境变量: WP_ZEROSSL_EAB_HMAC_KEY）
--notify-webhook URL      续期失败 Webhook 通知 URL（环境变量: WP_NOTIFY_WEBHOOK）
--no-pre-backup           跳过操作前自动备份
--php-version X.Y         强制指定 PHP 版本（默认: < 8.3 时自动升级到 8.4）
--skip-deps               跳过系统包安装
--backup-dir PATH         备份根目录（默认: /root/backups）
--keep N                  备份保留份数（backup 子命令）
--dry-run                 演练模式，不执行写操作
--staging                 使用 Let's Encrypt Staging 环境
--no-staging              覆盖继承的 --staging，强制使用生产 CA
--no-redis                显式禁用 Redis（覆盖自动探测）
--no-optimize             显式禁用 Nginx 优化
--no-cloudflare           显式禁用 Cloudflare Real IP
--no-http3                显式禁用 HTTP/3 QUIC
--no-allow-xmlrpc         显式封锁 xmlrpc.php
--purge                   彻底清理: 删除数据库 + 文件 + 证书（uninstall）
--revoke                  吊销并删除 Let's Encrypt 证书（uninstall）
--lang {zh,en}            界面语言（首次指定后自动持久化）
--quiet                   静默模式，仅输出 WARNING 及以上
```

## 使用示例

```bash
# 查看站点状态（单站点时可省略 --domain）
sudo python3 wp_ssl_bootstrap.py status

# 备份（保留 7 份）
sudo python3 wp_ssl_bootstrap.py backup --domain example.com --keep 7

# 从最新备份恢复（原子 DB 切换）
sudo python3 wp_ssl_bootstrap.py restore --domain example.com

# 热更新配置 + 安全升级插件
sudo python3 wp_ssl_bootstrap.py update --domain example.com --cache fastcgi --redis

# 强制续期证书
sudo python3 wp_ssl_bootstrap.py renew --domain example.com --force

# 从 staging 切换到生产 CA
sudo python3 wp_ssl_bootstrap.py renew --domain example.com --force --no-staging

# 先部署 HTTP，后补签 SSL
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --skip-ssl --wp-auto-install
sudo python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com --email admin@example.com

# 外置数据库
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --db-host rds.example.com --db-root-pass 'YourPassword' \
  --db-wait-timeout 120

# Cloudflare 反代 + HTTP/3 + 自动完成安装向导 + 失败通知
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --cloudflare --http3 --wp-auto-install \
  --notify-webhook https://hooks.slack.com/services/xxx

# Redis 全页缓存（srcache，替代 FastCGI）
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --cache redis

# 事后开启 HTTP/3
sudo python3 wp_ssl_bootstrap.py update --domain example.com --http3

# 更新时显式关闭自动探测到的 Redis
sudo python3 wp_ssl_bootstrap.py update --domain example.com --no-redis

# ZeroSSL 备用 CA（Let's Encrypt 失败时自动切换）
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --zerossl-eab-kid YOUR_KID --zerossl-eab-hmac-key YOUR_HMAC

# 更新脚本至最新版
sudo python3 wp_ssl_bootstrap.py self-update

# 卸载守护组件（保留数据和证书）
sudo python3 wp_ssl_bootstrap.py uninstall --domain example.com

# 彻底清理（不可逆 — 删除数据库、文件和证书）
sudo python3 wp_ssl_bootstrap.py uninstall --domain example.com --purge
```

## 安全设计

- **密码学安全** — `secrets` 模块生成所有密码和 Salt
- **零命令行泄露** — 数据库密码通过 `--defaults-extra-file` 临时文件传递（0600, tmpfs）；管理员密码通过环境变量传递；敏感参数从 `/proc/cmdline` 清洗
- **零 SQL 注入** — 严格字符白名单校验；`run_sql()` 入口控制字符拦截
- **原子写入** — 所有配置文件使用 `O_NOFOLLOW` + `fsync` + 备份/回滚；拒绝写入符号链接目标
- **wp-config.php 加固** — `DISALLOW_FILE_EDIT`、`FORCE_SSL_ADMIN`、`DISALLOW_UNFILTERED_HTML` 等
- **禁用 Core dump** — `RLIMIT_CORE=0` + `PR_SET_DUMPABLE=0`
- **Nginx 纵深防御** — 隐藏版本号、uploads 禁 PHP、wp-cron 限本机、登录速率限制、证书 SAN 与 server_name 自动对齐、CSP 现代化策略（`frame-ancestors` 取代 X-Frame-Options、`upgrade-insecure-requests` 自动升级子资源、移除废弃的 X-XSS-Protection）、动态模块加载错误级联自动修复
- **certbot 错误熔断** — 非 CA 侧致命错误立即跳出；ECDSA 优先 + 逐 CA RSA 降级；ZeroSSL 自动 fallback
- **供应链安全** — self-update 使用硬编码双源 + 强制交叉 SHA-256 校验
- **Webhook SSRF 防护** — 强制 HTTPS；拒绝私有 IP、内网域名后缀、IPv4-mapped IPv6
- **备份完整性** — gzip 格式校验、`Dump completed` EOF 标记检测、tar 路径遍历拦截
- **安全 tar 解压** — `_safe_extract_tar` 强制 `--no-same-owner --no-same-permissions`，过滤 `..` / 绝对路径 / 符号链接成员，超时保护 + 产物验证，覆盖全部 6 处解压场景
- **统一 `rmtree` / `copy` / `mkstemp`** — 所有文件系统操作使用加固包装器：父目录白名单、双向符号链接检查、`O_NOFOLLOW` 强制

## 已知限制

- **xmlrpc.php** 默认拒绝。使用 Jetpack 或移动 App 需添加 `--allow-xmlrpc`。
- **WordPress 多站点**不支持（每域名单实例）。
- **通配符证书**不支持（仅 webroot 验证）。

## 凭据文件

部署完成后凭据保存在 `/root/.wp_credentials_<域名>.txt`（权限 0600）。**请妥善保管。**

## 文件结构

```
/etc/nginx/conf.d/<域名>.conf                    Nginx HTTPS 配置
/etc/systemd/system/<前缀>-ssl.service           续期服务
/etc/systemd/system/<前缀>-ssl.timer             每日续期定时器
/etc/systemd/system/<前缀>-ssl-notify-fail.*     续期失败通知服务
/etc/systemd/system/<前缀>-wp-cron.*             WordPress Cron 定时器
/etc/systemd/system/<前缀>-db-optimize.*         每周数据库优化定时器
/etc/fail2ban/filter.d/wordpress-*.conf          Fail2Ban 过滤规则
/etc/fail2ban/jail.d/wordpress-*.conf            Fail2Ban jail 规则
/etc/logrotate.d/nginx-wp-*                      日志轮转配置
/root/.wp_credentials_*.txt                      站点凭据
```

## 许可证

[MIT](./LICENSE)
