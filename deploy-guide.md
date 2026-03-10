# WP-SSL-Bootstrap V3.1.1 — 全新建站参数指南

---

## 前置检查

部署前请确认以下三点，脚本本身无法替你完成：

1. **域名 DNS 已解析到本机公网 IP**（A 记录，`example.com` + `www.example.com`）
2. **服务器 80/443 端口对外开放**（安全组/防火墙）
3. **以 root 身份运行**（脚本强制检查 `geteuid == 0`）

---

## 场景一：标准建站（推荐起点）

适合大多数个人站、企业官网。资源适中（≥1 GB RAM），无特殊需求。

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --cache  fastcgi \
  --wp-auto-install \
  --persist-root-pwd
```

### 各参数作用

| 参数 | 说明 |
|---|---|
| `--domain example.com` | 主域名。脚本自动探测 `www.example.com` DNS，若解析正常则一并签入证书 |
| `--email admin@example.com` | Let's Encrypt 证书到期提醒邮箱（不填则使用 `--register-unsafely-without-email`） |
| `--cache fastcgi` | 启用 Nginx FastCGI 页面缓存；同步安装 `nginx-helper` 插件（发布文章时自动清缓存） |
| `--wp-auto-install` | 通过 WP-CLI 自动完成 WordPress 安装向导，随机生成管理员密码并写入凭据文件，无需手动访问 `/wp-admin/install.php` |
| `--persist-root-pwd` | 将 MariaDB root 密码明文存入 `/root/.mariadb_root.pwd`，方便后续 `backup` 子命令自动读取；不加此参数则密码仅在本次会话中驻留内存 |

### 部署完成后

脚本输出凭据文件路径，例如 `/root/.wp_credentials_example_com.txt`，其中包含：

- WordPress 管理员用户名 / 密码
- 数据库名、用户名、密码
- MariaDB root 密码
- 常用运维命令（备份、续期、卸载）

---

## 场景二：高流量博客 / 电商（全功能）

适合有一定并发量、追求最优性能的场景。

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

### 相比场景一新增的参数

| 参数 | 说明 |
|---|---|
| `--redis` | 启用 Redis 对象缓存，与 FastCGI 页面缓存**叠加**：FastCGI 缓存完整 HTML 页面，Redis 缓存数据库查询结果；登录用户（绕过 FastCGI 缓存）也能受益 |
| `--optimize` | 启用 Nginx `open_file_cache`（`max=10000 inactive=60s`），减少静态文件密集请求时的内核 `stat()` 调用 |
| `--cloudflare` | 自动从 Cloudflare API 拉取最新 IP 段，写入全局 `real_ip_from` + `CF-Connecting-IP` 配置，确保日志和 Fail2Ban 记录访客真实 IP 而非 CF 节点 IP；获取失败时回退内置默认值 |

> **注意**：`--cloudflare` 写入的是全局 Nginx 配置，同台服务器多个域名共享，只需在第一个域名部署时加，后续域名无需重复加。

---

## 场景三：低配 VPS 首次部署（≤1 GB RAM）

512 MB / 1 GB 小鸡首推。脚本会自动创建 Swap（≤1 GB 内存时创建 1 GB swapfile）、按内存分级调整 PHP-FPM 进程数和 MariaDB 缓冲池，以上均**无需手动参数**，由 `setup_lemp_and_wp()` 自动判断执行。

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain  blog.example.com \
  --email   me@example.com \
  --wp-auto-install \
  --persist-root-pwd
```

不加 `--cache fastcgi` 的原因：512 MB 内存下 FastCGI 缓存目录占用与 PHP-FPM 竞争有限内存，收益可能低于损耗；待升配后再通过 `update` 子命令开启。

---

## 场景四：演练 / 测试（不产生真实变更）

首次在陌生服务器上运行时，建议先 dry-run 确认脚本行为：

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  test@example.com \
  --cache  fastcgi \
  --dry-run
```

`--dry-run` 跳过所有真实写操作（文件写入、systemctl、certbot、数据库 SQL），仅打印将要执行的步骤。**不产生任何副作用**，适合 CI 检查或部署前预演。

---

## 场景五：使用 Staging 证书调试

反复测试部署流程时，Let's Encrypt 生产环境有速率限制（同域名每周最多 5 次证书签发）。用 `--staging` 绕过限制，签发不受浏览器信任的测试证书：

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  test@example.com \
  --staging
```

调试完成后执行一次不带 `--staging` 的 `deploy` 或 `renew --force` 替换为正式证书。

---

## 场景六：已有 MariaDB root 密码的服务器

服务器上已有其他 MariaDB 实例，或安全策略不允许脚本自动设置 root 密码：

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain       example.com \
  --email        admin@example.com \
  --db-root-pass 'YourExistingRootPassword' \
  --cache        fastcgi \
  --wp-auto-install
```

`--db-root-pass` 也可以通过环境变量传入，避免密码出现在 shell 历史：

```bash
export WP_DB_ROOT_PASS='YourExistingRootPassword'
python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email  admin@example.com \
  --cache  fastcgi \
  --wp-auto-install
```

---

## 场景七：外置数据库（RDS / 云数据库）

数据库不在本机，使用云厂商托管 MySQL/MariaDB：

```bash
python3 wp_ssl_bootstrap.py deploy \
  --domain       example.com \
  --email        admin@example.com \
  --db-host      rm-xxxx.mysql.rds.aliyuncs.com \
  --db-root-pass 'RdsRootPassword' \
  --db-wait-timeout 120 \
  --cache        fastcgi \
  --wp-auto-install
```

| 参数 | 说明 |
|---|---|
| `--db-host` | 外置数据库主机地址；脚本检测到非 `localhost`/`127.0.0.1` 时自动跳过本地 MariaDB 安装和调优、mysqlcheck 定时器 |
| `--db-wait-timeout 120` | 跨地域云数据库连接延迟较高，默认 60s 可能不够；建议设为 120～300 |

---

## 常用后续操作

```bash
# 首次备份（部署完成后立即执行）
python3 wp_ssl_bootstrap.py backup \
  --domain example.com \
  --keep   7

# 查看站点状态
python3 wp_ssl_bootstrap.py status \
  --domain example.com

# 手动触发证书续期（正常情况无需手动，systemd timer 自动执行）
python3 wp_ssl_bootstrap.py renew \
  --domain example.com \
  --force

# 事后追加 Redis 缓存（无需重新部署）
python3 wp_ssl_bootstrap.py update \
  --domain example.com \
  --cache  fastcgi \
  --redis

# 脚本自更新
python3 wp_ssl_bootstrap.py self-update
```

---

## 参数速查表

| 参数 | 类型 | 默认值 | 适用子命令 |
|---|---|---|---|
| `--domain` | 字符串 | `$WP_DOMAIN` | 全部 |
| `--email` | 字符串 | `$WP_EMAIL` | `deploy` |
| `--cache` | `none`/`fastcgi` | `none` | `deploy` / `update` |
| `--redis` | 开关 | 关 | `deploy` / `update` |
| `--optimize` | 开关 | 关 | `deploy` / `update` |
| `--cloudflare` | 开关 | 关 | `deploy` / `update` |
| `--wp-auto-install` | 开关 | 关 | `deploy` |
| `--persist-root-pwd` | 开关 | 关 | `deploy` |
| `--allow-xmlrpc` | 开关 | 关（deny） | `deploy` / `update` |
| `--php-version` | `X.Y` | 自动探测最高版本 | `deploy` / `update` |
| `--db-host` | 字符串 | `localhost` | `deploy` / `backup` |
| `--db-root-pass` | 字符串 | `$WP_DB_ROOT_PASS` | `deploy` / `backup` |
| `--db-wait-timeout` | 秒数 | 本地 30 / 外置 60 | `deploy` |
| `--backup-dir` | 路径 | `/root/backups` | `backup` / `restore` |
| `--keep` | 整数 | `5` | `backup` |
| `--staging` | 开关 | 关 | `deploy` |
| `--dry-run` | 开关 | 关 | 全部 |
| `--force` | 开关 | 关 | `renew` |
| `--skip-deps` | 开关 | 关 | `deploy` |
| `--lang` | `zh`/`en` | 自动检测 | 全部（全局） |

---

## 自动执行（无需额外参数）

以下功能在 `deploy` 时**无条件自动运行**，不需要任何参数：

- **Swap 自动创建**：内存 ≤2 GB 且无 Swap 时自动创建 swapfile
- **PHP-FPM 进程数调优**：按内存分级设置 `pm.max_children`，防止小 VPS OOM
- **MariaDB 缓冲池调优**：`innodb_buffer_pool_size` 按内存分级配置
- **TCP/BBR 内核调优**：写入 sysctl drop-in，开启 BBR 拥塞控制（内核 4.9+）
- **Fail2Ban**：自动配置 WordPress 暴力破解防护，封禁时间 24h + 递增封禁
- **systemd 续期定时器**：每天检查证书到期，到期前 30 天自动续期
- **WP-Cron 定时器**：15 分钟 systemd timer 替代 HTTP 触发，消除 WP-Cron 性能开销
- **mysqlcheck 周度优化**：每周日 03:00 自动执行碎片回收（外置数据库时跳过）
- **Certbot 持久化 deploy hook**：证书续期后自动 reload Nginx
- **静态资源长缓存**：图片 365 天、JS/CSS 30 天、字体 365 天 + CORS
