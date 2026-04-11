# WP-SSL-Bootstrap V3.2.6 — 全新建站参数指南
# WP-SSL-Bootstrap V3.2.6 — New Site Deployment Guide

---

## 前置检查 / Prerequisites

部署前请确认以下三点，脚本本身无法替你完成：  
Confirm the following before running the script — these cannot be automated:

1. **域名 DNS 已解析到本机公网 IP**（A 记录：`example.com` + `www.example.com`）  
   **Domain DNS points to this server's public IP** (A records for both `example.com` and `www.example.com`)

2. **服务器 80 / 443 端口对外开放**（安全组 / 防火墙）  
   **Ports 80 and 443 are open** (security group / firewall rules)

3. **以 root 身份运行**（脚本强制检查 `geteuid == 0`）  
   **Run as root** (the script enforces `geteuid == 0`)

> **💡 交互式向导 / Interactive Wizard**  
> 不确定该用哪些参数？直接运行 `sudo python3 wp_ssl_bootstrap.py`，脚本会自动进入引导菜单。  
> Not sure which flags to use? Just run `sudo python3 wp_ssl_bootstrap.py` and the interactive wizard will guide you.

> **💡 域名智能归一化 / Smart Domain Normalization**  
> 输入 `www.example.com` 时脚本自动归一为 `example.com`，`www` 作为别名写入证书。子域名（如 `blog.example.com`）自动跳过 `www` 变体。  
> Input `www.example.com` is auto-normalized to `example.com`; `www` is added as a certificate alias. Subdomains (e.g. `blog.example.com`) automatically skip the `www` variant.

> **💡 单站点自动推断 / Single-Site Auto Inference** *(V3.2.1+ 起 / Since V3.2.1)*  
> 除 `deploy` 外的子命令，若未指定 `--domain` 且服务器上仅有一个已部署站点，脚本自动使用该域名，无需重复输入。  
> For non-deploy subcommands, if `--domain` is omitted and only one site is deployed, the script auto-selects it.

---

## 场景一：标准建站（推荐起点）
## Scenario 1: Standard Site (Recommended Starting Point)

适合大多数个人站、企业官网。资源适中（≥1 GB RAM），无特殊需求。  
Suitable for most personal sites and corporate homepages. Requires ≥1 GB RAM with no special requirements.

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --cache  fastcgi \
  --wp-auto-install \
  --persist-root-pwd
```

### 各参数作用 / Parameter Breakdown

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--domain example.com` | 主域名。脚本自动探测 `www` DNS，若解析正常则一并签入证书。<br>Primary domain. The script auto-detects `www` DNS and includes it in the certificate if resolved. |
| `--email admin@example.com` | Let's Encrypt 证书到期提醒邮箱。不填则使用 `--register-unsafely-without-email`。<br>Contact email for Let's Encrypt expiry reminders. Omitting uses `--register-unsafely-without-email`. |
| `--cache fastcgi` | 启用 Nginx FastCGI 页面缓存，同步安装 `nginx-helper` 插件（发布文章时自动清缓存）。<br>Enables Nginx FastCGI page cache and auto-installs the `nginx-helper` plugin for cache purging on publish. |
| `--wp-auto-install` | 通过 WP-CLI 自动完成 WordPress 安装向导，随机生成管理员密码并写入凭据文件。<br>Completes the WordPress setup wizard via WP-CLI with a randomly generated admin password saved to the credentials file. |
| `--persist-root-pwd` | 将 MariaDB root 密码明文存入 `/root/.mariadb_root.pwd`，方便后续 `backup` 子命令自动读取。不加此参数，密码仅在本次会话中驻留内存，`backup` 将跳过数据库 dump。<br>Saves the MariaDB root password to `/root/.mariadb_root.pwd` for use by the `backup` subcommand. Without this flag, the password exists only in memory and database backups will be silently skipped. |

### 部署完成后 / After Deployment

脚本输出凭据文件路径，例如 `/root/.wp_credentials_example_d_com.txt`，其中包含：  
The script prints the path to a credentials file, e.g. `/root/.wp_credentials_example_d_com.txt`, containing:

- WordPress 管理员用户名 / 密码 / WordPress admin username and password
- 数据库名、用户名、密码 / Database name, user, and password
- MariaDB root 密码 / MariaDB root password
- 常用运维命令（备份、续期、卸载）/ Common ops commands (backup, renew, uninstall)

---

## 场景二：高流量博客 / 电商（全功能）
## Scenario 2: High-Traffic Blog / E-commerce (Full Feature Set)

适合有一定并发量、追求最优性能的场景。  
For sites with significant traffic that require maximum performance.

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain  shop.example.com \
  --email   ops@example.com \
  --cache   fastcgi \
  --redis \
  --optimize \
  --http3 \
  --cloudflare \
  --wp-auto-install \
  --persist-root-pwd \
  --notify-webhook https://hooks.slack.com/services/xxx
```

### 相比场景一新增的参数 / Additional Parameters vs. Scenario 1

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--redis` | 启用 Redis 对象缓存，与 FastCGI 页面缓存**叠加**：FastCGI 缓存完整 HTML，Redis 缓存数据库查询；已登录用户（绕过 FastCGI 缓存）同样受益。<br>Enables Redis object cache on top of FastCGI page cache. FastCGI caches full HTML; Redis caches DB queries. Logged-in users (who bypass FastCGI) also benefit. |
| `--optimize` | 启用 Nginx `open_file_cache`（`max=10000 inactive=60s`），减少静态文件密集请求时的内核 `stat()` 调用。<br>Enables Nginx `open_file_cache` (`max=10000 inactive=60s`), reducing kernel `stat()` calls for static-asset-heavy traffic. |
| `--http3` | *(V3.2.2+ 起 / Since V3.2.2)* 启用 HTTP/3 QUIC 协议（需 Nginx 支持 `http_v3` 模块）。自动开放 UDP 443 防火墙端口，多站点自动共享 `reuseport`。Nginx 不支持时静默忽略。<br>Enables HTTP/3 QUIC protocol (requires Nginx `http_v3` module). Auto-opens UDP 443 firewall port; shares `reuseport` across sites. Silently ignored if Nginx lacks support. |
| `--cloudflare` | 自动从 Cloudflare API 拉取最新 IP 段，写入全局 `real_ip_from` + `CF-Connecting-IP` 配置，确保日志和 Fail2Ban 记录访客真实 IP 而非 CF 节点 IP；获取失败时回退内置默认值。<br>Auto-fetches Cloudflare IP ranges and writes a global `real_ip_from` + `CF-Connecting-IP` config so logs and Fail2Ban see visitor IPs, not Cloudflare node IPs. Falls back to built-in defaults on fetch failure. |
| `--notify-webhook` | 续期失败时发送 Webhook 通知（Slack / 飞书 / 企微等）。仅允许 HTTPS URL，内网地址会被安全策略拒绝。**未配置时**脚本自动安装 journal/email 兜底通知（CRIT 级别写 journal + 尝试 `mail` 发邮件给 root），确保续期失败永不静默。<br>Sends a Webhook notification on renewal failure (Slack / Lark / WeCom). HTTPS only; internal URLs are blocked by security policy. **When not configured**, the script auto-installs a journal/email fallback notification (CRIT-level journal entry + email attempted via `mail(1)` to root), ensuring renewal failures are never silent. |

> **注意 / Note**：`--cloudflare` 写入全局 Nginx 配置，同台服务器多个域名共享，只需在**首个域名**部署时加，后续域名无需重复。  
> `--cloudflare` writes a global Nginx config shared across all domains on the server. Only add it when deploying the **first domain**; subsequent domains on the same server do not need it.

---

## 场景三：低配 VPS（≤1 GB RAM）
## Scenario 3: Low-Memory VPS (≤1 GB RAM)

512 MB / 1 GB 小鸡首推。脚本会自动创建 Swap、按内存分级调整 PHP-FPM 进程数和 MariaDB 缓冲池——无需任何额外参数，由 `setup_lemp_and_wp()` 自动判断执行。  
Recommended for 512 MB / 1 GB VPS. The script automatically creates swap, tunes PHP-FPM worker count, and adjusts the MariaDB buffer pool based on available RAM — all without any extra flags.

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain  blog.example.com \
  --email   me@example.com \
  --wp-auto-install \
  --persist-root-pwd
```

`--cache fastcgi` 在此场景下**有意省略**：512 MB 内存下 FastCGI 缓存目录与 PHP-FPM 竞争有限内存，收益可能低于损耗。待升配后通过 `update` 子命令开启。  
`--cache fastcgi` is **intentionally omitted** here: on a 512 MB server the FastCGI cache directory competes with PHP-FPM for limited RAM and may cost more than it saves. Enable it later via the `update` subcommand after upgrading.

---

## 场景四：演练 / 测试（不产生任何真实变更）
## Scenario 4: Dry Run / Test (Zero Side Effects)

首次在陌生服务器上运行时，建议先演练一遍确认脚本行为。  
Always recommended before the first real deployment on an unfamiliar server.

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  test@example.com \
  --cache  fastcgi \
  --dry-run
```

`--dry-run` 跳过所有真实写操作（文件写入、systemctl、certbot、数据库 SQL），仅打印将要执行的步骤，**不产生任何副作用**。  
`--dry-run` skips all real write operations (file writes, systemctl, certbot, database SQL) and only prints what would be executed. **No side effects.**

---

## 场景五：反复测试时使用 Staging 证书
## Scenario 5: Staging Certificate for Repeated Testing

Let's Encrypt 生产环境对同一域名每周最多签发 5 次证书。调试部署流程时加 `--staging` 使用测试证书，不受速率限制：  
Let's Encrypt production limits issuance to 5 certificates per domain per week. Use `--staging` during debugging to avoid hitting this limit:

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  test@example.com \
  --staging
```

调试完成后执行一次不带 `--staging` 的 `deploy` 或 `renew --force --no-staging` 替换为正式证书。Staging 证书不受浏览器信任，仅用于流程验证。  
Once debugging is complete, run `deploy` (or `renew --force --no-staging`) without `--staging` to replace it with a trusted certificate. Staging certificates are not browser-trusted.

> **`--no-staging`** *(V3.2.1+ 起 / Since V3.2.1)* — 显式覆盖从已有定时器继承的 `--staging` 标志，强制切换回生产 CA。  
> Explicitly overrides `--staging` inherited from existing timer config, forcing production CA.

> **💡 自动配置探测 / Automatic Config Detection** *(V3.2.2+ 起 / Since V3.2.2)*
> `update` / `enable-ssl` / `restore` 子命令会自动从现有 Nginx 配置和 `wp-config.php` 中探测 `cache` / `redis` / `optimize` / `http3` / `cloudflare` / `allow_xmlrpc` 等设置，无需每次重复传参。若需显式**关闭**某项自动探测到的功能，使用 `--no-*` 反向开关（如 `--no-http3`、`--no-redis`）。
> `update` / `enable-ssl` / `restore` automatically detect `cache`/`redis`/`optimize`/`http3`/`cloudflare`/`allow_xmlrpc` from existing Nginx config and `wp-config.php` — no need to re-pass flags each time. To explicitly **disable** an auto-detected feature, use `--no-*` reverse flags (e.g. `--no-http3`, `--no-redis`).

---

## 场景六：已有 MariaDB root 密码的服务器
## Scenario 6: Server with an Existing MariaDB Root Password

服务器上已有其他 MariaDB 实例，或安全策略要求显式传入 root 密码：  
Use this when the server already has a MariaDB instance, or your security policy requires providing the root password explicitly:

```bash
# 密码直接作为参数传入 / Pass password as argument
python3 wp_ssl_bootstrap.py deploy \
  --domain       example.com \
  --email        admin@example.com \
  --db-root-pass 'YourExistingRootPassword' \
  --cache        fastcgi \
  --wp-auto-install
```

**推荐：通过环境变量传入，避免密码出现在 shell 历史记录中。**  
**Recommended: pass via environment variable to keep the password out of shell history.**

```bash
export WP_DB_ROOT_PASS='YourExistingRootPassword'

python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --cache  fastcgi \
  --wp-auto-install
```

---

## 场景七：外置数据库（RDS / 云托管 MySQL）
## Scenario 7: External Database (RDS / Managed MySQL)

数据库不在本机，使用云厂商托管 MySQL / MariaDB：  
When the database is hosted externally (e.g. Alibaba Cloud RDS, AWS RDS):

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain          example.com \
  --email           admin@example.com \
  --db-host         rm-xxxx.mysql.rds.aliyuncs.com \
  --db-root-pass    'RdsRootPassword' \
  --db-wait-timeout 120 \
  --cache           fastcgi \
  --wp-auto-install
```

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--db-host` | 外置数据库主机地址。脚本检测到非 `localhost` / `127.0.0.1` 时，自动跳过本地 MariaDB 安装、调优及 mysqlcheck 定时器。<br>External database host. When not `localhost`/`127.0.0.1`, the script skips local MariaDB installation, tuning, and the mysqlcheck timer. |
| `--db-wait-timeout 120` | 跨地域云数据库连接延迟较高，默认 60s 可能不够，建议设为 120～300。<br>Cross-region cloud databases have higher latency. The default 60s may be insufficient; 120–300 is recommended. |
| `--no-db-ssl` | 内网直连场景下禁用数据库 SSL 传输（默认外置 DB 自动启用 SSL）。<br>Disables SSL transport for external DB connections (default: SSL auto-enabled for external DB). Use for LAN/VPC direct connections. |

---

## 场景八：两阶段部署（DNS 未就绪时先上线 HTTP）
## Scenario 8: Two-Phase Deployment (Go Live on HTTP While DNS Propagates)

DNS 刚修改、还在传播中，或需要先验证站点再签证书：  
When DNS has just been changed and is still propagating, or you want to verify the site before signing a certificate:

```bash
# 阶段 1: 仅部署 HTTP（不签证书）
# Phase 1: Deploy HTTP-only (no certificate)
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --skip-ssl \
  --cache   fastcgi \
  --wp-auto-install \
  --persist-root-pwd

# （等待 DNS 生效后……）
# (After DNS propagation…)

# 阶段 2: 补签证书，切换至 HTTPS
# Phase 2: Sign certificate and switch to HTTPS
python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com \
  --email  admin@example.com
```

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--skip-ssl` | 跳过 SSL 签发，生成完整的 HTTP 生产 Nginx 配置。`wp-config.php` 中 `FORCE_SSL_ADMIN` 设为 `false`。<br>Skips SSL issuance; generates a full HTTP production Nginx config. `FORCE_SSL_ADMIN` is set to `false` in `wp-config.php`. |
| `enable-ssl` | 新子命令：为已有 HTTP 站点签发证书并切换至 HTTPS。自动恢复 `FORCE_SSL_ADMIN`、更新 siteurl/home、安装 systemd 续期定时器。<br>New subcommand: signs a certificate for an existing HTTP site and switches to HTTPS. Auto-restores `FORCE_SSL_ADMIN`, updates siteurl/home, installs systemd renewal timer. |

> **注意 / Note**：`enable-ssl` 支持与 `deploy` 相同的 `--cache` / `--redis` / `--cloudflare` / `--optimize` / `--http3` / `--wp-auto-install` / `--notify-webhook` 标志，以及 `--no-*` 反向开关。
> `enable-ssl` supports the same `--cache` / `--redis` / `--cloudflare` / `--optimize` / `--http3` / `--wp-auto-install` / `--notify-webhook` flags as `deploy`, plus `--no-*` reverse switches.

---

## 场景九：ZeroSSL 备用 CA（Let's Encrypt 签发受限时）
## Scenario 9: ZeroSSL Backup CA (When Let's Encrypt Hits Rate Limits)

Let's Encrypt 对同一域名每周限 5 次签发。ZeroSSL 作为备用 CA，可通过 EAB 凭据启用：  
Let's Encrypt limits issuance to 5 certificates per domain per week. ZeroSSL serves as a backup CA via EAB credentials:

```bash
# 方式 1: 手动提供 EAB 凭据（从 app.zerossl.com/developer 获取）
# Method 1: Provide EAB credentials manually (from app.zerossl.com/developer)
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --zerossl-eab-kid       YOUR_EAB_KID \
  --zerossl-eab-hmac-key  YOUR_EAB_HMAC_KEY

# 方式 2: 仅提供 email，脚本自动调用 ZeroSSL API 获取 EAB 凭据
# Method 2: Just provide email; the script auto-fetches EAB credentials from ZeroSSL API
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com
```

> **自动容灾 / Automatic Failover**：即使不提供 ZeroSSL 参数，当 Let's Encrypt 签发失败且提供了 `--email` 时，脚本会自动尝试通过 ZeroSSL API 获取 EAB 凭据并 fallback 到 ZeroSSL。  
> Even without ZeroSSL flags, when Let's Encrypt fails and `--email` is provided, the script automatically attempts to fetch EAB credentials from ZeroSSL API and falls back to ZeroSSL.

---

## 场景十：续期失败 Webhook 通知
## Scenario 10: Renewal Failure Webhook Notification

需要在 SSL 续期失败时第一时间收到告警（Slack / 飞书 / 企微 / 自定义 Webhook）：  
Get alerted immediately when SSL renewal fails (Slack / Lark / WeCom / custom Webhook):

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --cache  fastcgi \
  --wp-auto-install \
  --persist-root-pwd \
  --notify-webhook https://hooks.slack.com/services/T00/B00/xxxxx
```

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--notify-webhook URL` | 续期失败时发送 JSON POST（`{"text": "..."}`）到指定 URL。仅允许 HTTPS，内网地址 / `localhost` / 私有域名后缀会被安全策略拒绝。也可通过环境变量 `WP_NOTIFY_WEBHOOK` 传入。<br>Sends a JSON POST on renewal failure. HTTPS only; localhost, private IPs, and internal domain suffixes are blocked. Also accepts `WP_NOTIFY_WEBHOOK` env var. |

> **注意 / Note**：`--skip-ssl` 模式下无 SSL 续期定时器，Webhook 暂不生效；后续执行 `enable-ssl` 后自动激活。  
> In `--skip-ssl` mode there is no SSL renewal timer, so the webhook is inactive until `enable-ssl` is run.

---

## 场景十一：彻底清理站点 / 证书吊销
## Scenario 11: Full Site Purge / Certificate Revocation

卸载守护组件的同时彻底删除数据库、站点文件和证书（**不可逆**）：  
Remove daemon components AND permanently delete database, files, and certificates (**irreversible**):

```bash
# 彻底清理（需交互确认域名）
# Full purge (requires interactive domain confirmation)
python3 wp_ssl_bootstrap.py uninstall \
  --domain example.com \
  --purge

# 仅吊销证书（需输入 yes 确认）
# Revoke certificate only (requires yes confirmation)
python3 wp_ssl_bootstrap.py uninstall \
  --domain example.com \
  --revoke
```

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--purge` | 删除数据库、站点文件、Let's Encrypt 证书目录和凭据文件。需在 TTY 中输入域名确认。<br>Drops database, removes webroot, deletes certificate directories and credentials file. Requires typing the domain name to confirm in TTY. |
| `--revoke` | 吊销 Let's Encrypt 证书并删除本地证书文件。需输入 `yes` 确认。<br>Revokes the Let's Encrypt certificate and deletes local cert files. Requires typing `yes` to confirm. |

---

## 场景十二：ntfy.sh 零配置 Webhook 通知 *(V3.2.6 新增)*
## Scenario 12: ntfy.sh Zero-Config Webhook *(New in V3.2.6)*

无需注册第三方服务。交互式向导自动生成 ntfy.sh 主题并配置通知：
No third-party service registration needed. The interactive wizard auto-generates an ntfy.sh topic:

```bash
# 交互式向导会提示: [1] 自动配置 ntfy.sh  [2] 自定义 URL  [Enter] 跳过
# The wizard will prompt: [1] Auto-configure ntfy.sh  [2] Custom URL  [Enter] Skip
python3 wp_ssl_bootstrap.py

# 或在命令行直接指定 / Or specify on command line
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --notify-webhook https://ntfy.sh/your-topic
```

部署完成后，脚本输出可直接复制的 `update --notify-webhook` 命令。在手机上安装 [ntfy 应用](https://ntfy.sh) 并订阅相同主题即可收到推送通知。
After deploy, the script outputs a copy-paste-ready `update --notify-webhook` command. Install the [ntfy app](https://ntfy.sh) on your phone and subscribe to the same topic for push notifications.

---

## 场景十三：证书 CA 迁移 *(V3.2.6 新增)*
## Scenario 13: Certificate CA Migration *(New in V3.2.6)*

从 Let's Encrypt 迁移到 ZeroSSL（或反向）：
Migrate from Let's Encrypt to ZeroSSL (or vice versa):

```bash
python3 wp_ssl_bootstrap.py migrate-ssl \
  --domain example.com \
  --email  admin@example.com
```

脚本自动检测当前证书签发商、保留域名列表、使用目标 CA 重新签发。
The script auto-detects the current issuer, preserves the domain list, and re-issues with the target CA.

---

## 场景十四：OpenSSL 修复 *(V3.2.6 新增)*
## Scenario 14: OpenSSL Repair *(New in V3.2.6)*

系统升级后 Python SSL 模块报错（常见于 Rocky/EL9 系统 `openssl-libs` 升级后）：
Python SSL module errors after system upgrade (common on Rocky/EL9 after `openssl-libs` upgrade):

```bash
# 无需 --domain 或 --email，直接运行
# No --domain or --email needed
python3 wp_ssl_bootstrap.py fix-openssl
```

4 步诊断+修复：版本比较检测 → ldd/rpm 诊断 → 自动修复 → 子进程验证。
4-step diagnosis and repair: version comparison → ldd/rpm diagnostics → auto-repair → subprocess verification.

---

## 常用后续操作 / Common Post-Deployment Operations

```bash
# 首次备份（部署完成后立即执行）
# First backup (run immediately after deployment)
python3 wp_ssl_bootstrap.py backup \
  --domain example.com \
  --keep   7

# 查看站点状态（单站点时可省略 --domain）
# Check site status (--domain optional when only one site deployed)
python3 wp_ssl_bootstrap.py status

# 手动触发证书续期（正常情况 systemd timer 自动执行；--force 忽略到期时间）
# Manual certificate renewal (normally handled by systemd timer; --force ignores expiry)
python3 wp_ssl_bootstrap.py renew \
  --domain example.com \
  --force

# 为 HTTP-only 站点补签 SSL 证书 / Add SSL to an HTTP-only site
python3 wp_ssl_bootstrap.py enable-ssl \
  --domain example.com \
  --email  admin@example.com

# 证书 CA 迁移 (V3.2.6+) / Migrate certificate CA
python3 wp_ssl_bootstrap.py migrate-ssl \
  --domain example.com \
  --email  admin@example.com

# 事后追加 Redis 缓存（无需重新完整部署）
# Add Redis cache after the fact (no full redeploy needed)
python3 wp_ssl_bootstrap.py update \
  --domain example.com \
  --cache  fastcgi \
  --redis

# 切换到 Redis 全页缓存（替代 FastCGI，V3.2.2+ 起）
# Switch to Redis full-page cache (replaces FastCGI, since V3.2.2)
python3 wp_ssl_bootstrap.py update \
  --domain example.com \
  --cache  redis

# 事后开启 HTTP/3（V3.2.2+ 起）
# Enable HTTP/3 after the fact (since V3.2.2)
python3 wp_ssl_bootstrap.py update \
  --domain example.com \
  --http3

# 从备份恢复 / Restore from backup
python3 wp_ssl_bootstrap.py restore \
  --domain example.com

# OpenSSL 修复 (V3.2.6+) / Fix OpenSSL issues
python3 wp_ssl_bootstrap.py fix-openssl

# 脚本自更新 / Self-update the script
python3 wp_ssl_bootstrap.py self-update
```

---

## 参数速查表 / Parameter Reference

| 参数 / Parameter | 类型 / Type | 默认值 / Default | 适用子命令 / Subcommands |
|---|---|---|---|
| `--domain` | 字符串 / string | `$WP_DOMAIN` | 全部 / all |
| `--email` | 字符串 / string | `$WP_EMAIL` | `deploy` / `enable-ssl` / `renew` / `update` / `restore` |
| `--cache` | `none` / `fastcgi` / `redis` | `none` | `deploy` / `update` / `enable-ssl` / `restore` |
| `--redis` | 开关 / flag | 关 / off | `deploy` / `update` / `enable-ssl` / `restore` |
| `--optimize` | 开关 / flag | 关 / off | `deploy` / `update` / `enable-ssl` / `restore` |
| `--cloudflare` | 开关 / flag | 关 / off | `deploy` / `update` / `enable-ssl` / `restore` |
| `--http3` | 开关 / flag | 关 / off | `deploy` / `update` / `enable-ssl` / `restore` |
| `--wp-auto-install` | 开关 / flag | 关 / off | `deploy` / `update` / `enable-ssl` / `restore` |
| `--persist-root-pwd` | 开关 / flag | 关 / off | `deploy` / `enable-ssl` / `backup` / `restore` |
| `--skip-ssl` | 开关 / flag | 关 / off | `deploy` / `restore` |
| `--allow-xmlrpc` | 开关 / flag | 关（封锁）/ off (blocked) | `deploy` / `update` / `enable-ssl` / `restore` |
| `--php-version` | `X.Y` | 自动升级到 8.4（已满足 ≥8.3 时跳过）/ auto-upgrade to 8.4 (skipped if ≥8.3) | `deploy` / `update` / `enable-ssl` / `restore` |
| `--db-host` | 字符串 / string | `localhost` | 全部 / all |
| `--db-root-pass` | 字符串 / string | `$WP_DB_ROOT_PASS` | 全部 / all |
| `--no-db-ssl` | 开关 / flag | 关 / off | 全部 / all |
| `--db-wait-timeout` | 秒 / seconds | 本地 30s / 外置 60s<br>30s local / 60s external | `deploy` / `enable-ssl` / `update` / `restore` |
| `--zerossl-eab-kid` | 字符串 / string | `$WP_ZEROSSL_EAB_KID` | `deploy` / `enable-ssl` / `renew` / `update` / `restore` |
| `--zerossl-eab-hmac-key` | 字符串 / string | `$WP_ZEROSSL_EAB_HMAC_KEY` | `deploy` / `enable-ssl` / `renew` / `update` / `restore` |
| `--notify-webhook` | URL | `$WP_NOTIFY_WEBHOOK` | `deploy` / `enable-ssl` / `renew` / `update` / `restore` |
| `--no-pre-backup` | 开关 / flag | 关 / off | `deploy` / `enable-ssl` / `update` / `restore` |
| `--backup-dir` | 路径 / path | `/root/backups` | 全部 / all |
| `--keep` | 整数 / integer | `5` | `backup` |
| `--staging` | 开关 / flag | 关 / off | `deploy` / `enable-ssl` |
| `--no-staging` | 开关 / flag | 关 / off | `renew` / `update` / `restore` / `enable-ssl` |
| `--no-redis` | 开关 / flag | 关 / off | `update` / `enable-ssl` / `restore` |
| `--no-optimize` | 开关 / flag | 关 / off | `update` / `enable-ssl` / `restore` |
| `--no-cloudflare` | 开关 / flag | 关 / off | `update` / `enable-ssl` / `restore` |
| `--no-http3` | 开关 / flag | 关 / off | `update` / `enable-ssl` / `restore` |
| `--no-allow-xmlrpc` | 开关 / flag | 关 / off | `update` / `enable-ssl` / `restore` |
| `--dry-run` | 开关 / flag | 关 / off | 全部 / all |
| `--force` | 开关 / flag | 关 / off | `renew` |
| `--purge` | 开关 / flag | 关 / off | `uninstall` |
| `--revoke` | 开关 / flag | 关 / off | `uninstall` |
| `--skip-deps` | 开关 / flag | 关 / off | `deploy` |
| `--lang` | `zh` / `en` | 自动检测 / auto-detect | 全部（全局）/ all (global) |

---

## 自动执行（无需额外参数）
## Always-On Features (No Extra Flags Required)

以下功能在 `deploy` 时**无条件自动运行**，不需要任何参数：  
The following run **unconditionally** during `deploy` without any flags:

| 功能 / Feature | 说明 / Description |
|---|---|
| **Swap 自动创建** / Auto swap creation | 内存 ≤2 GB 且无 Swap 时自动创建 swapfile（≤1 GB RAM→1 GB swap，≤2 GB→2 GB swap）<br>Creates swapfile when RAM ≤2 GB and no swap exists (≤1 GB RAM→1 GB, ≤2 GB RAM→2 GB) |
| **PHP 自动升级** / Auto PHP upgrade *(V3.2.3 新增 / New in V3.2.3)* | 检测已装 PHP < 8.3 时自动升级到 8.4（EL: Remi 仓库；Ubuntu: Ondrej PPA；Debian: Sury DPA）。升级后迁移自定义 `php.ini` 设置，禁用旧版 PHP-FPM，重启新版服务。PHP ≥ 8.3 时跳过。<br>Detects installed PHP < 8.3 and auto-upgrades to 8.4 (EL: Remi repo; Ubuntu: Ondrej PPA; Debian: Sury DPA). Migrates custom `php.ini` settings, disables old PHP-FPM, restarts new service. Skipped when PHP ≥ 8.3. |
| **Nginx 小版本主动升级** / Proactive Nginx minor upgrade *(V3.2.4 新增 / New in V3.2.4)* | 已安装 Nginx 满足最低版本但低于仓库最新 patch 版本时，主动升级（如 1.28.0→1.28.1），升级后自动走统一验证链（`nginx -t` → 模块修复 → graceful restart）。<br>When installed Nginx meets the minimum but is below the repo's latest patch version, proactively upgrades (e.g. 1.28.0→1.28.1) followed by the unified verification chain (`nginx -t` → module repair → graceful restart). |
| **Nginx 动态模块自动修复** / Nginx module auto-repair *(V3.2.4 新增 / New in V3.2.4)* | `nginx -t` 检测到动态模块加载失败（ABI 不匹配 / undefined symbol / .so 缺失）时，自动重装→移除→清理孤立指令，多轮迭代直至通过。<br>When `nginx -t` detects dynamic module load failures (ABI mismatch / undefined symbol / missing .so), auto-reinstalls→removes→cleans orphaned directives, iterating until passing. |
| **PHP-FPM 进程数调优** / PHP-FPM pool tuning | 按内存分级设置 `pm.max_children`，防止小 VPS OOM<br>Sets `pm.max_children` based on RAM tier to prevent OOM kills on small VPS |
| **MariaDB 缓冲池调优** / MariaDB buffer pool tuning | `innodb_buffer_pool_size` 按内存分级配置<br>Tiers `innodb_buffer_pool_size` according to available RAM |
| **TCP / BBR 内核调优** / Kernel network tuning | 写入 sysctl drop-in，开启 BBR 拥塞控制（内核 4.9+）<br>Writes sysctl drop-in enabling BBR congestion control (kernel 4.9+) |
| **Fail2Ban** | 自动配置 WordPress 暴力破解防护，封禁时间 24h + 递增封禁<br>Configures WordPress brute-force protection with 24h ban duration and progressive escalation |
| **systemd 续期定时器** / Certificate renewal timer | 定时器频率随证书寿命自适应：标准 90 天证书每日检查；LE 2027 年 47 天证书每 8 小时；2028 年 6 天证书每 4 小时。续期成功后自动检测寿命变化并热更新 timer。<br>Timer frequency auto-adapts to certificate lifetime: daily for standard 90-day certs; every 8h for LE 2027 47-day certs; every 4h for 2028 6-day certs. Auto-detects lifetime changes after renewal and hot-updates the timer. |
| **续期失败兜底通知** / Renewal failure fallback *(V3.2.6 新增 / New in V3.2.6)* | 未配置 `--notify-webhook` 时，自动安装 systemd OnFailure 服务：续期失败写 journal（CRIT）+ syslog + 尝试 `mail` 发邮件给 root。确保证书到期风险永不静默。<br>When no `--notify-webhook` is configured, auto-installs a systemd OnFailure service: renewal failures logged to journal (CRIT) + syslog + email attempted via `mail(1)` to root. Ensures certificate expiry risk is never silent. |
| **自愈引擎** / Self-healing engine *(V3.2.6 新增 / New in V3.2.6)* | 14 种常见故障自动诊断修复：缺失 logrotate/curl 自动安装、DB 超时自动重启、`nginx -t` 错误自动修复（失效 include / 重复 default_server）、文件删除失败自动清除 immutable 位重试、PHP-FPM/Redis 故障自动诊断（配置测试 + journal 检查）。<br>14 common failure scenarios auto-diagnosed and repaired: missing logrotate/curl auto-installed, DB timeout auto-restarted, `nginx -t` errors auto-fixed (stale includes / duplicate default_server), file deletion retried with `chattr -i`, PHP-FPM/Redis failures auto-diagnosed via config test and journal inspection. |
| **组件生命周期管理** / Component lifecycle *(V3.2.6 新增 / New in V3.2.6)* | Certbot: snap 迁移 + pip venv 兜底（EFF 官方 6 步流程）；Redis/Valkey: 版本感知升级 + EL10 Valkey 自动切换；WP-CLI: 版本检测 + 自动更新 + SHA-512 校验；fail2ban: 版本探测 + 0.11 以下旧版兼容。<br>Certbot: snap migration + pip venv fallback (EFF official 6-step); Redis/Valkey: version-aware upgrades + EL10 Valkey auto-switch; WP-CLI: version detection + auto-update + SHA-512 verification; fail2ban: version probing + legacy compat below 0.11. |
| **WP-Cron 定时器** / WP-Cron systemd timer | 15 分钟 systemd timer 替代 HTTP 触发，消除每次请求触发 wp-cron 的性能开销<br>15-minute systemd timer replaces HTTP-triggered wp-cron, eliminating per-request overhead |
| **mysqlcheck 周度优化** / Weekly DB optimize | 每周日 03:00 自动执行碎片回收（外置数据库时跳过）<br>Runs `mysqlcheck --optimize` every Sunday at 03:00; skipped for external databases |
| **Certbot 持久化 deploy hook** / Persistent certbot hook | 证书续期后自动 reload Nginx，无论由脚本 timer 还是 certbot 自身 timer 触发<br>Reloads Nginx after every renewal regardless of which timer triggered it |
| **静态资源长缓存** / Static asset caching | 图片 365 天、JS/CSS 30 天、字体 365 天 + CORS<br>Images 365d, JS/CSS 30d, fonts 365d + CORS headers |
| **安全响应头** / Security headers | HSTS / CSP (`frame-ancestors` / `upgrade-insecure-requests`) / X-Content-Type-Options / Referrer-Policy / Permissions-Policy 全套；已移除废弃的 X-Frame-Options 和 X-XSS-Protection<br>Full suite: HSTS, CSP (`frame-ancestors`, `upgrade-insecure-requests`), X-Content-Type-Options, Referrer-Policy, Permissions-Policy. Deprecated X-Frame-Options and X-XSS-Protection removed. |
| **OS 自动安全更新** / OS auto security updates | Debian/Ubuntu: unattended-upgrades；RHEL 系: dnf-automatic / yum-cron<br>Debian/Ubuntu: unattended-upgrades; RHEL: dnf-automatic / yum-cron |
| **操作前自动备份** / Pre-operation backup | `enable-ssl` / `update` / `restore` 执行前自动轻量备份（DB + Nginx 配置），可通过 `--no-pre-backup` 跳过<br>Lightweight auto-backup (DB + Nginx config) before `enable-ssl` / `update` / `restore`; skip with `--no-pre-backup` |
| **ECC 证书** / ECDSA certificates | 优先使用 ECDSA P-256 密钥签发（TLS 握手更快），certbot 不支持时自动降级 RSA<br>Prefers ECDSA P-256 key type (faster TLS handshake); auto-falls back to RSA if unsupported |
