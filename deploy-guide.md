# WP-SSL-Bootstrap V3.1.1 — 全新建站参数指南
# WP-SSL-Bootstrap V3.1.1 — New Site Deployment Guide

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

脚本输出凭据文件路径，例如 `/root/.wp_credentials_example_com.txt`，其中包含：  
The script prints the path to a credentials file, e.g. `/root/.wp_credentials_example_com.txt`, containing:

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
  --cloudflare \
  --wp-auto-install \
  --persist-root-pwd
```

### 相比场景一新增的参数 / Additional Parameters vs. Scenario 1

| 参数 / Parameter | 说明 / Description |
|---|---|
| `--redis` | 启用 Redis 对象缓存，与 FastCGI 页面缓存**叠加**：FastCGI 缓存完整 HTML，Redis 缓存数据库查询；已登录用户（绕过 FastCGI 缓存）同样受益。<br>Enables Redis object cache on top of FastCGI page cache. FastCGI caches full HTML; Redis caches DB queries. Logged-in users (who bypass FastCGI) also benefit. |
| `--optimize` | 启用 Nginx `open_file_cache`（`max=10000 inactive=60s`），减少静态文件密集请求时的内核 `stat()` 调用。<br>Enables Nginx `open_file_cache` (`max=10000 inactive=60s`), reducing kernel `stat()` calls for static-asset-heavy traffic. |
| `--cloudflare` | 自动从 Cloudflare API 拉取最新 IP 段，写入全局 `real_ip_from` + `CF-Connecting-IP` 配置，确保日志和 Fail2Ban 记录访客真实 IP 而非 CF 节点 IP；获取失败时回退内置默认值。<br>Auto-fetches Cloudflare IP ranges and writes a global `real_ip_from` + `CF-Connecting-IP` config so logs and Fail2Ban see visitor IPs, not Cloudflare node IPs. Falls back to built-in defaults on fetch failure. |

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

调试完成后执行一次不带 `--staging` 的 `deploy` 或 `renew --force` 替换为正式证书。Staging 证书不受浏览器信任，仅用于流程验证。  
Once debugging is complete, run `deploy` (or `renew --force`) without `--staging` to replace it with a trusted certificate. Staging certificates are not browser-trusted.

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

---

## 常用后续操作 / Common Post-Deployment Operations

```bash
# 首次备份（部署完成后立即执行）
# First backup (run immediately after deployment)
python3 wp_ssl_bootstrap.py backup \
  --domain example.com \
  --keep   7

# 查看站点状态 / Check site status
python3 wp_ssl_bootstrap.py status \
  --domain example.com

# 手动触发证书续期（正常情况 systemd timer 自动执行；--force 忽略到期时间）
# Manual certificate renewal (normally handled by systemd timer; --force ignores expiry)
python3 wp_ssl_bootstrap.py renew \
  --domain example.com \
  --force

# 事后追加 Redis 缓存（无需重新完整部署）
# Add Redis cache after the fact (no full redeploy needed)
python3 wp_ssl_bootstrap.py update \
  --domain example.com \
  --cache  fastcgi \
  --redis

# 脚本自更新 / Self-update the script
python3 wp_ssl_bootstrap.py self-update
```

---

## 参数速查表 / Parameter Reference

| 参数 / Parameter | 类型 / Type | 默认值 / Default | 适用子命令 / Subcommands |
|---|---|---|---|
| `--domain` | 字符串 / string | `$WP_DOMAIN` | 全部 / all |
| `--email` | 字符串 / string | `$WP_EMAIL` | `deploy` |
| `--cache` | `none` / `fastcgi` | `none` | `deploy` / `update` |
| `--redis` | 开关 / flag | 关 / off | `deploy` / `update` |
| `--optimize` | 开关 / flag | 关 / off | `deploy` / `update` |
| `--cloudflare` | 开关 / flag | 关 / off | `deploy` / `update` |
| `--wp-auto-install` | 开关 / flag | 关 / off | `deploy` |
| `--persist-root-pwd` | 开关 / flag | 关 / off | `deploy` |
| `--allow-xmlrpc` | 开关 / flag | 关（封锁）/ off (blocked) | `deploy` / `update` |
| `--php-version` | `X.Y` | 自动探测最高版本 / auto-detect highest | `deploy` / `update` |
| `--db-host` | 字符串 / string | `localhost` | `deploy` / `backup` |
| `--db-root-pass` | 字符串 / string | `$WP_DB_ROOT_PASS` | `deploy` / `backup` |
| `--db-wait-timeout` | 秒 / seconds | 本地 30s / 外置 60s<br>30s local / 60s external | `deploy` |
| `--backup-dir` | 路径 / path | `/root/backups` | `backup` / `restore` |
| `--keep` | 整数 / integer | `5` | `backup` |
| `--staging` | 开关 / flag | 关 / off | `deploy` |
| `--dry-run` | 开关 / flag | 关 / off | 全部 / all |
| `--force` | 开关 / flag | 关 / off | `renew` |
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
| **PHP-FPM 进程数调优** / PHP-FPM pool tuning | 按内存分级设置 `pm.max_children`，防止小 VPS OOM<br>Sets `pm.max_children` based on RAM tier to prevent OOM kills on small VPS |
| **MariaDB 缓冲池调优** / MariaDB buffer pool tuning | `innodb_buffer_pool_size` 按内存分级配置<br>Tiers `innodb_buffer_pool_size` according to available RAM |
| **TCP / BBR 内核调优** / Kernel network tuning | 写入 sysctl drop-in，开启 BBR 拥塞控制（内核 4.9+）<br>Writes sysctl drop-in enabling BBR congestion control (kernel 4.9+) |
| **Fail2Ban** | 自动配置 WordPress 暴力破解防护，封禁时间 24h + 递增封禁<br>Configures WordPress brute-force protection with 24h ban duration and progressive escalation |
| **systemd 续期定时器** / Certificate renewal timer | 每天检查证书到期，到期前 30 天自动续期<br>Checks certificate expiry daily; auto-renews from 30 days before expiry |
| **WP-Cron 定时器** / WP-Cron systemd timer | 15 分钟 systemd timer 替代 HTTP 触发，消除每次请求触发 wp-cron 的性能开销<br>15-minute systemd timer replaces HTTP-triggered wp-cron, eliminating per-request overhead |
| **mysqlcheck 周度优化** / Weekly DB optimize | 每周日 03:00 自动执行碎片回收（外置数据库时跳过）<br>Runs `mysqlcheck --optimize` every Sunday at 03:00; skipped for external databases |
| **Certbot 持久化 deploy hook** / Persistent certbot hook | 证书续期后自动 reload Nginx，无论由脚本 timer 还是 certbot 自身 timer 触发<br>Reloads Nginx after every renewal regardless of which timer triggered it |
| **静态资源长缓存** / Static asset caching | 图片 365 天、JS/CSS 30 天、字体 365 天 + CORS<br>Images 365d, JS/CSS 30d, fonts 365d + CORS headers |
| **安全响应头** / Security headers | HSTS / CSP / X-Content-Type-Options / Referrer-Policy / Permissions-Policy 全套<br>Full suite: HSTS, CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy |
