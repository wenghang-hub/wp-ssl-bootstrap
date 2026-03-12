# WP-SSL-Bootstrap

一条命令完成 WordPress + HTTPS 全站部署。
One command to deploy WordPress with HTTPS, auto-renewal, and production-grade security.

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## Features

- **Zero-config HTTPS** — Let's Encrypt → ZeroSSL automatic failover with EAB auto-negotiation; certbot error classification with circuit-breaker logic; Snap/certbot-auto/standard installs auto-detected
- **Two-phase deployment** — `deploy --skip-ssl` for HTTP-only first, then `enable-ssl` when DNS is ready; or full HTTPS in one shot
- **Interactive wizard** — no subcommand? TTY users get a guided menu for domain, email, and SSL policy
- **Multi-distro** — EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux) / Ubuntu / Debian; dnf5 (EL10+) auto-detected
- **Database security** — auth_socket/unix_socket auto-detection; credentials never exposed in process list (`--defaults-extra-file`)
- **Multi-source download** — Chinese mirror + global fallback with SHA-256 verification; WP-CLI fallback when tar.gz sources fail
- **Strict permissions** — wp-config.php locked to 0440 from creation; SELinux booleans auto-configured
- **Nginx hardening** — rate limiting on wp-login.php + admin-ajax.php, HSTS, CSP enforcement, wp-config/uploads/xmlrpc/wp-includes deny, HTTP method filtering, FastCGI cache (optional), Brotli (optional)
- **Fail2Ban** — auto-configured WordPress brute-force protection with progressive banning (24h + escalation)
- **Auto-renewal** — systemd daily timer with randomized delay, `--cert-name` precision renewal, persistent deploy hook
- **Backup & restore** — one-command backup (DB + files + Nginx + Fail2Ban/logrotate); one-command restore with `--redis` support
- **Config hot-update** — `update` subcommand applies new templates without touching data
- **Redis object cache** — optional `--redis`, composable with FastCGI page cache; PHP Redis source-compile fallback
- **Performance tuning** — PHP-FPM pool auto-sized by RAM, MariaDB InnoDB tuning, BBR + TCP sysctl, swap auto-creation, Nginx `open_file_cache` (`--optimize`)
- **WordPress Cron offload** — systemd 15-min timer replaces per-request wp-cron.php
- **Bilingual UI** — Chinese/English; auto-detected from locale, persistable via `--lang`
- **Smart domain handling** — `www.example.com` auto-normalized to `example.com`; subdomains skip `www` variant
- **External database** — `--db-host` for RDS/remote MySQL, auto SSL transport
- **Idempotent** — safe to re-run; existing passwords and databases are preserved

## Quick Start

```bash
# Interactive wizard (just run without arguments)
sudo python3 wp_ssl_bootstrap.py

# Or specify everything on the command line
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com
```

With FastCGI cache + Redis:

```bash
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --cache fastcgi --redis
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
| `status` | Show certificate expiry, service health, disk space |
| `backup` | Back up DB + files + Nginx config + Fail2Ban/logrotate |
| `restore` | Restore from backup (auto-selects latest, or `--from PATH`) |
| `update` | Hot-update config templates after script upgrade |
| `self-update` | Download latest script version with SHA-256 verification and atomic replace |
| `uninstall` | Remove daemon components; preserves data and certificates |

## Options

```
--domain DOMAIN         Site domain (env: WP_DOMAIN)
--email EMAIL           Contact email for cert (env: WP_EMAIL)
--db-host HOST          Database host, default: localhost (env: WP_DB_HOST)
--db-root-pass PASS     MariaDB/MySQL root password (env: WP_DB_ROOT_PASS)
--cache {none,fastcgi}  Nginx cache mode
--redis                 Enable Redis object cache
--cloudflare            Fetch Cloudflare IP ranges and configure real IP restoration
--allow-xmlrpc          Allow xmlrpc.php with rate limiting (default: deny)
--wp-auto-install       Complete WordPress setup wizard automatically via WP-CLI
--optimize              Enable Nginx open_file_cache for static-heavy sites
--skip-ssl              Deploy HTTP-only (skip SSL); use enable-ssl later
--force                 Force certificate renewal regardless of expiry (renew/enable-ssl)
--persist-root-pwd      Save MariaDB root password to disk
--zerossl-eab-kid KID   ZeroSSL EAB Key ID for backup CA (env: WP_ZEROSSL_EAB_KID)
--zerossl-eab-hmac-key  ZeroSSL EAB HMAC Key (env: WP_ZEROSSL_EAB_HMAC_KEY)
--php-version X.Y       Force specific PHP-FPM version
--skip-deps             Skip package installation
--backup-dir PATH       Backup root directory (default: /root/backups)
--keep N                Number of backups to retain (backup subcommand)
--dry-run               Simulate without making changes
--staging               Use Let's Encrypt staging environment
--lang {zh,en}          Interface language (persisted after first use)
--quiet                 Only WARNING and above
--url URL               Custom source URL for self-update (env: WP_UPDATE_URL)
```

## Examples

```bash
# Status check
sudo python3 wp_ssl_bootstrap.py status --domain example.com

# Backup (keep 7 copies)
sudo python3 wp_ssl_bootstrap.py backup --domain example.com --keep 7

# Restore from latest
sudo python3 wp_ssl_bootstrap.py restore --domain example.com

# Hot-update configs
sudo python3 wp_ssl_bootstrap.py update --domain example.com --cache fastcgi --redis

# Force certificate renewal
sudo python3 wp_ssl_bootstrap.py renew --domain example.com --force

# HTTP-only deploy, then add SSL later
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --skip-ssl --wp-auto-install
sudo python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com --email admin@example.com

# External database
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --db-host rds.example.com --db-root-pass 'YourPassword'

# Cloudflare reverse proxy + auto-complete WordPress wizard
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --cloudflare --wp-auto-install

# ZeroSSL as backup CA (auto-failover from Let's Encrypt)
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --zerossl-eab-kid YOUR_KID --zerossl-eab-hmac-key YOUR_HMAC

# Update to latest script version
sudo python3 wp_ssl_bootstrap.py self-update

# Uninstall (keeps data + certs)
sudo python3 wp_ssl_bootstrap.py uninstall --domain example.com
```

## Security Design

- **Cryptographic credentials** — `secrets` module for all passwords and salts
- **Zero CLI leakage** — DB passwords via `--defaults-extra-file` temp files (0600, tmpfs)
- **Zero SQL injection** — strict character whitelist on all identifiers and passwords
- **Atomic writes** — all config files with backup + rollback
- **wp-config.php hardening** — `DISALLOW_FILE_EDIT`, `FORCE_SSL_ADMIN`, `DISALLOW_UNFILTERED_HTML`, etc.
- **Core dump disabled** — `RLIMIT_CORE=0` + `PR_SET_DUMPABLE=0`
- **Nginx defense-in-depth** — `server_tokens off`, uploads PHP blocked, wp-cron localhost-only, login rate limiting
- **Certbot circuit-breaker** — non-CA fatal errors break out immediately; Snap/certbot-auto paths auto-detected; ZeroSSL automatic fallback

## Known Limitations

- **xmlrpc.php** blocked by default. Use `--allow-xmlrpc` for Jetpack / mobile app.
- **WordPress Multisite** not supported (single instance per domain).
- **Wildcard certificates** not supported (webroot validation only).

## Credentials

After deployment, credentials are saved to `/root/.wp_credentials_<domain>.txt` (mode 0600). **Keep it safe.**

## File Structure

```
/etc/nginx/conf.d/<domain>.conf              Nginx HTTPS config
/etc/systemd/system/<prefix>-ssl.service     Renewal service
/etc/systemd/system/<prefix>-ssl.timer       Daily renewal timer
/etc/systemd/system/<prefix>-wpcron.*        WordPress Cron timer
/etc/systemd/system/<prefix>-dboptimize.*    Weekly DB optimize timer
/etc/fail2ban/filter.d/wordpress-*.conf      Fail2Ban filter
/etc/fail2ban/jail.d/wordpress-*.conf        Fail2Ban jail
/etc/logrotate.d/nginx-wp-*                  Log rotation
/root/.wp_credentials_*.txt                  Site credentials
```

## License

[MIT](./LICENSE)

---

<a id="中文"></a>

## 功能特性

- **零配置 HTTPS** — Let's Encrypt → ZeroSSL 自动容灾（EAB 自动协商）；certbot 错误分类熔断；自动探测 Snap/certbot-auto/标准安装
- **两阶段部署** — `deploy --skip-ssl` 先部署 HTTP，DNS 就绪后 `enable-ssl` 补签证书；或一步到位全量 HTTPS
- **交互式向导** — 不指定子命令时自动进入 TTY 引导菜单，选择域名、邮箱和 SSL 策略
- **多发行版** — EL7–10（RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux）/ Ubuntu / Debian；自动识别 dnf5（EL10+）
- **数据库安全** — auth_socket/unix_socket 自适应；凭据不暴露于进程列表（`--defaults-extra-file`）
- **多源下载** — 中文镜像 + 全球主源 fallback，SHA-256 校验；WP-CLI 兜底
- **严格权限** — wp-config.php 创建即 0440；SELinux 布尔值自动配置
- **Nginx 加固** — wp-login.php + admin-ajax.php 速率限制、HSTS、CSP 强制执行、wp-config/uploads/xmlrpc/wp-includes 拦截、HTTP 方法过滤、FastCGI 缓存（可选）、Brotli（可选）
- **Fail2Ban** — 自动配置 WordPress 暴力破解防护，渐进式封禁（24h + 递增）
- **自动续期** — systemd 每日定时器，随机延迟，`--cert-name` 精准续期，持久化 deploy hook
- **备份恢复** — 一键备份（数据库 + 文件 + Nginx + Fail2Ban/logrotate）；一键恢复，支持 `--redis`
- **配置热更新** — `update` 子命令应用新模板，不触碰数据
- **Redis 对象缓存** — 可选 `--redis`，可与 FastCGI 页面缓存叠加；PHP Redis 源码编译兜底
- **性能调优** — PHP-FPM 按内存动态调参、MariaDB InnoDB 调优、BBR + TCP sysctl、Swap 自动创建、Nginx `open_file_cache`（`--optimize`）
- **WordPress Cron 卸载** — systemd 15 分钟定时器替代每请求触发 wp-cron.php
- **双语界面** — 中英文自动切换，`--lang` 持久化
- **域名智能归一化** — 输入 `www.example.com` 自动归一为 `example.com`；子域名自动跳过 `www` 变体
- **外置数据库** — `--db-host` 支持 RDS/远程 MySQL，自动 SSL 传输
- **幂等重跑** — 安全重复执行；已有密码和数据库自动保留

## 快速开始

```bash
# 交互式向导（直接运行即可）
sudo python3 wp_ssl_bootstrap.py

# 或在命令行指定所有参数
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com
```

启用 FastCGI 缓存 + Redis：

```bash
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --cache fastcgi --redis
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
| `status` | 查看证书到期、服务状态、磁盘空间 |
| `backup` | 备份数据库 + 站点文件 + Nginx 配置 + Fail2Ban/logrotate |
| `restore` | 从备份恢复（自动选最新，或 `--from 路径`） |
| `update` | 热更新配置模板（脚本升级后使用） |
| `self-update` | 下载最新版脚本，SHA-256 校验后原子替换 |
| `uninstall` | 卸载守护组件（保留数据与证书） |

## 常用参数

```
--domain DOMAIN         站点域名（环境变量: WP_DOMAIN）
--email EMAIL           证书申请邮箱（环境变量: WP_EMAIL）
--db-host HOST          数据库主机，默认 localhost（环境变量: WP_DB_HOST）
--db-root-pass PASS     MariaDB/MySQL root 密码（环境变量: WP_DB_ROOT_PASS）
--cache {none,fastcgi}  Nginx 缓存模式
--redis                 启用 Redis 对象缓存
--cloudflare            从 Cloudflare API 获取 IP 段并配置真实 IP 还原
--allow-xmlrpc          放开 xmlrpc.php（默认拒绝，启用后为速率限制透传）
--wp-auto-install       通过 WP-CLI 自动完成 WordPress 安装向导
--optimize              启用 Nginx open_file_cache，适合静态资源密集站点
--skip-ssl              仅部署 HTTP（跳过 SSL）；后续用 enable-ssl 补签
--force                 强制续期证书，忽略到期时间（renew/enable-ssl）
--persist-root-pwd      将 MariaDB root 密码保存至磁盘
--zerossl-eab-kid KID   ZeroSSL EAB Key ID，备用 CA（环境变量: WP_ZEROSSL_EAB_KID）
--zerossl-eab-hmac-key  ZeroSSL EAB HMAC Key（环境变量: WP_ZEROSSL_EAB_HMAC_KEY）
--php-version X.Y       强制指定 PHP-FPM 版本
--skip-deps             跳过系统包安装
--backup-dir PATH       备份根目录（默认: /root/backups）
--keep N                备份保留份数（backup 子命令）
--dry-run               演练模式，不执行写操作
--staging               使用 Let's Encrypt Staging 环境
--lang {zh,en}          界面语言（首次指定后自动持久化）
--quiet                 静默模式，仅输出 WARNING 及以上
--url URL               自更新自定义源地址（环境变量: WP_UPDATE_URL）
```

## 使用示例

```bash
# 查看站点状态
sudo python3 wp_ssl_bootstrap.py status --domain example.com

# 备份（保留 7 份）
sudo python3 wp_ssl_bootstrap.py backup --domain example.com --keep 7

# 从最新备份恢复
sudo python3 wp_ssl_bootstrap.py restore --domain example.com

# 热更新配置
sudo python3 wp_ssl_bootstrap.py update --domain example.com --cache fastcgi --redis

# 强制续期证书
sudo python3 wp_ssl_bootstrap.py renew --domain example.com --force

# 先部署 HTTP，后补签 SSL
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --skip-ssl --wp-auto-install
sudo python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com --email admin@example.com

# 外置数据库
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --db-host rds.example.com --db-root-pass 'YourPassword'

# Cloudflare 反代 + 自动完成安装向导
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --cloudflare --wp-auto-install

# ZeroSSL 备用 CA（Let's Encrypt 失败时自动切换）
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com --email admin@example.com \
  --zerossl-eab-kid YOUR_KID --zerossl-eab-hmac-key YOUR_HMAC

# 更新脚本至最新版
sudo python3 wp_ssl_bootstrap.py self-update

# 卸载守护组件（保留数据和证书）
sudo python3 wp_ssl_bootstrap.py uninstall --domain example.com
```

## 安全设计

- **密码学安全** — `secrets` 模块生成所有密码和 Salt
- **零命令行泄露** — 数据库密码通过 `--defaults-extra-file` 临时文件传递（0600, tmpfs）
- **零 SQL 注入** — 严格字符白名单校验
- **原子写入** — 所有配置文件带备份与回滚
- **wp-config.php 加固** — `DISALLOW_FILE_EDIT`、`FORCE_SSL_ADMIN`、`DISALLOW_UNFILTERED_HTML` 等
- **禁用 Core dump** — `RLIMIT_CORE=0` + `PR_SET_DUMPABLE=0`
- **Nginx 纵深防御** — 隐藏版本号、uploads 禁 PHP、wp-cron 限本机、登录速率限制
- **certbot 错误熔断** — 非 CA 侧致命错误立即跳出；自动探测 Snap/certbot-auto/标准安装路径；ZeroSSL 自动 fallback

## 已知限制

- **xmlrpc.php** 默认拒绝。使用 Jetpack 或移动 App 需添加 `--allow-xmlrpc`。
- **WordPress 多站点**不支持（每域名单实例）。
- **通配符证书**不支持（仅 webroot 验证）。

## 凭据文件

部署完成后凭据保存在 `/root/.wp_credentials_<域名>.txt`（权限 0600）。**请妥善保管。**

## 文件结构

```
/etc/nginx/conf.d/<域名>.conf                Nginx HTTPS 配置
/etc/systemd/system/<前缀>-ssl.service       续期服务
/etc/systemd/system/<前缀>-ssl.timer         每日续期定时器
/etc/systemd/system/<前缀>-wpcron.*          WordPress Cron 定时器
/etc/systemd/system/<前缀>-dboptimize.*      每周数据库优化定时器
/etc/fail2ban/filter.d/wordpress-*.conf      Fail2Ban 过滤规则
/etc/fail2ban/jail.d/wordpress-*.conf        Fail2Ban jail 规则
/etc/logrotate.d/nginx-wp-*                  日志轮转配置
/root/.wp_credentials_*.txt                  站点凭据
```

## 许可证

[MIT](./LICENSE)
