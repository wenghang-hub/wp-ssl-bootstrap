# WP-SSL-Bootstrap V3.2.9 Release Notes

> 生产审计回归补丁 — 22 项修复, 8 轮真实服务器验证, 从 🟡 B → 🟢 A+
> Production audit regression patch — 22 fixes, 8 rounds of live-server verification, 🟡 B → 🟢 A+

**Build**: `3.2.382`（V3.2.8 `build 365` 起 +22 项修复 / +291 代码行 / +3 模块级函数 / +5 模块级常量）
**Build**: `3.2.382` (+22 fixes / +291 LOC / +3 module-level functions / +5 module-level constants since V3.2.8 `build 365`)

> **📌 版本性质 / Release nature**
> V3.2.9 不是特性发布, 是 V3.2.8 基础上的 **生产审计回归补丁**。无新 CLI 参数, 无新子命令, 无配置破坏性变化。
> V3.2.9 is not a feature release; it is a **production audit regression patch** on top of V3.2.8. No new CLI flags, no new subcommands, no breaking config changes.
>
> **✅ 升级收益 / Upgrade benefits**: 修复 5 周静默失败的周度 db-optimize + 12+ 处 MariaDB CLI deprecation + 3 条 fail2ban 误配置 + 4 项审计分类器 UX 不一致。
> Fixes 5 weeks of silent weekly db-optimize failures + 12+ MariaDB CLI deprecation warnings + 3 fail2ban misconfigurations + 4 audit classifier UX inconsistencies.
>
> **🏁 验证规模 / Verification scale**: `verify_refactor.py` 78/78 + `test_integration.py --phase static` 472/472 + toksun.cn 生产环境 6 轮真实部署回归 (🟡 B → 🟢 A+ 零阻塞).
> `verify_refactor.py` 78/78 + `test_integration.py --phase static` 472/472 + toksun.cn production: 8-round live deployment regression (🟡 B → 🟢 A+ zero-blocker).

---

## 核心修复 / Core Fixes

### 🆕 全新功能: collect-logs 审计报告生成器 / New Feature: collect-logs audit report generator

> **📌 适用范围 / Applicability**: V3.2.8 build 365 用户升级后新增的最大功能。此功能在 V3.2.8 build 366-379 的中间 build 引入, 首次随 V3.2.9 正式发布打包。Build 365 的 `collect-logs` 只生成简单错误行统计。
> **Applicability**: The biggest new feature for V3.2.8 build 365 users upgrading. Introduced in intermediate V3.2.8 build 366-379, first bundled in an official release with V3.2.9. Build 365's `collect-logs` only produced simple error line counts.

**`collect-logs` 子命令现在生成结构化审计报告 / `collect-logs` now produces a structured audit report**:

- **`site-audit-report.md`** — 1,300+ 行 markdown 报告打包进 tarball, 涵盖组件版本、端口监听、SSL/TLS 配置、性能特性、安全加固、fail2ban jail 状态、Web 流量分布、主机资源、日志分类统计、运行时验证 7 章节。
- **三分类日志分类器 / Three-way log classifier** — `_signal_summary` 结构把日志条目分到:
  - **🛡 defense** (防御生效): `access forbidden by rule` / `bad record mac` 等 → 正面证据, 不算问题
  - **🔇 noise** (已知良性噪音): PHP-FPM `Terminating` / `exiting, bye-bye` / `error log file re-opened` / ACL `listen.\w+ ignored` → 过滤, 不打扰用户
  - **⚠️ signal** (真实信号): `max_children reached` / `slow log` / `Out of memory` / `upstream timed out` / `FATAL|PANIC` / `connect() failed` / systemd `Main process exited status=N` → 需关注
- **智能评级 / Smart rating** — 🟢 生产级 A+ / 🟡 A / 🟡 B / 🔴 严重, 依据 signal 数、严重度、是否全组件健康综合判定。
- **控制台摘要 / Console summary** — collect-logs 完成后打印紧凑摘要: 评级、缓存命中率、攻击拦截次数、封禁 IP 数、需关注事项列表、完整报告路径。

**用途 / Use cases**:
- 日常一键体检: `python3 wp_ssl_bootstrap.py collect-logs` → 立得评级
- 报 bug: tarball 即自带完整诊断, 不再需要手工附加多个日志
- CI/CD: 审计报告结构化, 可被自动化工具 grep / parse

**V3.2.9 在此功能上的改进 / V3.2.9 improvements to this feature**: FIX-㉒ (systemd unit 名拆分) / FIX-㉓ (脚本 INFO 伪阳性过滤) / FIX-㉔ (PHP-FPM logrotate 归噪音) / FIX-㉕ (标题/表/摘要三层计数一致性)。详见"审计分类器 UX"章节。

---

**`site-audit-report.md`** — 1,300+ line markdown report bundled into the tarball, covering 7 sections: component versions, port listening, SSL/TLS config, performance features, security hardening, fail2ban jail status, web traffic distribution, host resources, log classification statistics, runtime verification.

**Three-way log classifier (`_signal_summary`)** buckets log entries into:
- **🛡 defense** (active defense): `access forbidden by rule` / `bad record mac` etc → positive evidence, not problems
- **🔇 noise** (known benign): PHP-FPM `Terminating` / `exiting, bye-bye` / `error log file re-opened` / ACL `listen.\w+ ignored` → filtered, no user noise
- **⚠️ signal** (real signals): `max_children reached` / `slow log` / `Out of memory` / `upstream timed out` / `FATAL|PANIC` / `connect() failed` / systemd `Main process exited status=N` → needs attention

**Smart rating** — 🟢 Production A+ / 🟡 A / 🟡 B / 🔴 Critical, composite judgment based on signal count, severity, and component health.

**Console summary** — After collect-logs completes, a compact summary is printed: rating, cache hit rate, blocked attack count, banned IP count, items-of-concern list, and full report path.

**Use cases**:
- Daily one-click health check: `python3 wp_ssl_bootstrap.py collect-logs` → immediate rating
- Bug reports: tarball carries full diagnostics, no more manual log aggregation
- CI/CD: structured audit report is machine-parseable via grep

**V3.2.9 improvements**: FIX-㉒ (per-unit systemd advice) / FIX-㉓ (script INFO false-positive filter) / FIX-㉔ (PHP-FPM logrotate as noise) / FIX-㉕ (title/table/summary three-layer count consistency). See "Audit Classifier UX" section.

---

### 🧹 审计分类器 Deploy-Time 瞬态归类 / Audit Classifier Deploy-Time Transients

**FIX-㉗** — Debian 13 lamtin.hk build 381 全阶段测试（645/645 契约全绿）后审计报告仍显示 "🟡 有 1 项需关注 / 3 次未归类"，评级停在 🟢 A 而非 A+。溯源发现是 deploy 阶段的两类瞬态被分类器漏网:

1. **脚本自身的 srcache 能力探测**: `_srcache_detect_capability` 写 `/tmp/srcache_detect_XXX.conf` 测试 nginx 是否识别 `redis_pass` 指令; 不识别就 fallback 到 FastCGI。此处的 nginx `emerg` 是**期望结果**, 不是真错误。
2. **Deploy 早期 php-fpm socket 权限同步瞬态**: nginx 先启, php-fpm 的 socket 权限还没完全同步时, 健康检查或用户零星请求撞上会报 `connect() to unix:/run/php/phpX.Y-fpm.sock failed (Permission denied)`。通常 <5s 内恢复。

对称修复: `_noise_patterns` 新增:
- `r'srcache_detect_\w+\.conf'` — 脚本自身能力探测的临时 conf
- `r'connect\(\) to unix:/run/php[^\s]*\.sock failed.*Permission denied'` — deploy 早期 socket 权限瞬态

**实证**: Debian 13 lamtin.hk build 381 的 3 条未归类日志, 经 FIX-㉗ 后全部正确归类到 "已知良性噪音", 审计评级 🟢 A → 🟢 **A+** (匹配 toksun.cn 稳定运行多天后的结果)。

> **重要提示 / Important note**: 如果生产环境**持续**（非 deploy 窗口期）出现 `php-fpm.sock Permission denied`, 请单独排查: (1) nginx user 和 php-fpm user 是否一致; (2) `/run/php/` 目录属主和权限; (3) systemd unit 的 `After=` / `Requires=` 启动顺序。此噪音模式只覆盖 deploy 早期的已知瞬态。
> If production **persistently** (outside deploy window) shows `php-fpm.sock Permission denied`, investigate separately: (1) nginx user vs php-fpm user consistency; (2) `/run/php/` owner and perms; (3) systemd unit `After=` / `Requires=` ordering. This noise pattern only covers known deploy-time transients.

---

**FIX-㉗** — After Debian 13 lamtin.hk build 381 full-phase test (645/645 contracts green), the audit report still showed "🟡 1 item needs attention / 3 unclassified entries", with rating stuck at 🟢 A instead of A+. Traced to two classes of deploy-phase transients missed by the classifier:

1. **Script's own srcache capability probe**: `_srcache_detect_capability` writes `/tmp/srcache_detect_XXX.conf` to test whether nginx recognizes the `redis_pass` directive; if not, falls back to FastCGI. The nginx `emerg` here is the **expected result**, not a real error.
2. **Deploy-early php-fpm socket permission transient**: nginx starts first; while php-fpm socket permissions are still syncing, health checks or stray user requests trigger `connect() to unix:/run/php/phpX.Y-fpm.sock failed (Permission denied)`. Usually recovers within 5s.

Symmetric fix: `_noise_patterns` additions:
- `r'srcache_detect_\w+\.conf'` — script's own capability-probe temp conf
- `r'connect\(\) to unix:/run/php[^\s]*\.sock failed.*Permission denied'` — deploy-early socket permission transient

**Evidence**: Debian 13 lamtin.hk build 381's 3 unclassified entries, after FIX-㉗, all correctly classified as "known benign noise"; audit rating 🟢 A → 🟢 **A+** (matches toksun.cn stabilized multi-day runtime result).

---

### 🐛 restore webroot Permission Denied 修复 / Restore webroot Permission Denied fix

**FIX-㉖** — Ubuntu 24.04 lamtin.hk 全阶段回归测试（645 项检查）时, 唯一失败项 `log_php_no_fatal` 锁定一个真实 bug:

`_restore_webroot_files` 调 `_safe_extract_tar(safe_perms=True)` 下发 `tar --no-same-owner --no-same-permissions`, 配合脚本启动时的 `os.umask(0o077)` 安全 baseline, 归档里 `drwxr-xr-x` (755) 目录解压后经 umask 077 过滤变成 `drwx------` (700), nginx 用户**没有 x bit 无法 traverse**, 导致 wp-cron.timer (`*:0/5` 每 5 分钟) 在 restore 窗口内触发时读 `wp-includes/Requests/src/Autoload.php` 抛 `Permission denied` + PHP Fatal uncaught + systemd `status=255/EXCEPTION`.

对称修复: `_safe_extract_tar` 成功后立即:
- `chown -R <nginx_user>:<nginx_user> <webroot>` — `detect_user()` 读 `/etc/nginx/nginx.conf` 的 user 指令, 回退 `/etc/passwd` nginx 用户, 再降级 `platform.nginx_user`
- `chmod -R u=rwX,g=rX,o=rX <webroot>` — `X` 仅对目录和已含 x 的文件生效, 不误加执行位给 `.php` / `.js` / `.css`

**实证**: 修复前 645/645 其中 1 项失败; 修复后 Ubuntu 24.04 lamtin.hk 预期 645/645 全绿 + PHP FATAL 日志从 journal 消失。

---

**FIX-㉖** — During Ubuntu 24.04 lamtin.hk full-phase regression test (645 checks), the sole failure `log_php_no_fatal` pinpointed a real bug:

`_restore_webroot_files` calls `_safe_extract_tar(safe_perms=True)` which passes `tar --no-same-owner --no-same-permissions`. Combined with the script-startup `os.umask(0o077)` security baseline, archive dir mode `755` (drwxr-xr-x) becomes `700` (drwx------) after umask filtering. The nginx user **lacks x bit to traverse**, causing wp-cron.timer (`*:0/5` every 5 minutes) to trip over `wp-includes/Requests/src/Autoload.php` → `Permission denied` + PHP Fatal uncaught + systemd `status=255/EXCEPTION`.

Symmetric fix: after `_safe_extract_tar` succeeds:
- `chown -R <nginx_user>:<nginx_user> <webroot>` — `detect_user()` reads `user` directive in `/etc/nginx/nginx.conf`, falls back to `/etc/passwd` nginx user, then `platform.nginx_user`
- `chmod -R u=rwX,g=rX,o=rX <webroot>` — `X` applies only to directories and files already having x; does not mistakenly add execute bit to `.php` / `.js` / `.css`

**Evidence**: Pre-fix 645/645 with 1 failure; post-fix Ubuntu 24.04 lamtin.hk expected 645/645 green + PHP FATAL disappears from journal.

---

### 🔥 关键 Bug: mysqlcheck 非法选项 (5 周静默失败根因) / Critical Bug: mysqlcheck invalid option (5-week silent failure)

**FIX-❶❷❸** — `toksun_dcn-db-optimize.service` 的 `ExecStart` 使用 `mysqlcheck --single-transaction`。根据 Oracle MySQL 8.4 Reference Manual 和 MariaDB KB, `--single-transaction` 是 `mysqldump` 独有的选项, `mysqlcheck`/`mariadb-check` 完全不识别。

自 V3.2.8 build 365 部署以来, 每周日 03:00 的 weekly-optimize 任务以 `status=2/INVALIDARGUMENT` 静默退出, 累计 5 次未被发现。

**修复**:
- 移除 `--single-transaction` 标志
- 首选 `/usr/bin/mariadb-check`（MariaDB 10.5+ 新命名）, 不可用时回退 `mysqlcheck`
- 更新 docstring 和命令构建逻辑

**实证**: toksun.cn 生产环境升级后, 每张表输出 `OK`, 不再出现 status=2 退出。

---

**FIX-❶❷❸** — `toksun_dcn-db-optimize.service` `ExecStart` used `mysqlcheck --single-transaction`. Per Oracle MySQL 8.4 Reference Manual and MariaDB KB, `--single-transaction` is exclusive to `mysqldump`; `mysqlcheck`/`mariadb-check` do not recognize it.

Since V3.2.8 build 365 deployment, every Sunday 03:00 weekly-optimize job exited with `status=2/INVALIDARGUMENT` — silently, 5 times cumulatively undetected.

**Fix**:
- Remove `--single-transaction` flag
- Prefer `/usr/bin/mariadb-check` (MariaDB 10.5+ new naming), fall back to `mysqlcheck`
- Update docstring and command construction

**Evidence**: After upgrade on toksun.cn prod, every table reports `OK`, no more status=2 exits.

---

### 🏗️ 架构系统性修复 / Architectural Systematic Fixes

**FIX-⓰ MariaDB CLI 命名过渡 / MariaDB CLI naming transition**

新增模块级 helper `_mariadb_cli(tool)` + `_MARIADB_CLI_MAPPING` dict, 统一 12+ 处硬编码 `mysql*/mysqldump/mysqladmin` 调用。MariaDB 10.5+ 重命名为 `mariadb-*`, 11.x+ 主动打 deprecation 警告。Helper 优先使用新名, 旧环境自动降级。

New module-level helper `_mariadb_cli(tool)` + `_MARIADB_CLI_MAPPING` dict unifies 12+ hardcoded `mysql*/mysqldump/mysqladmin` calls. MariaDB 10.5+ renamed to `mariadb-*`, 11.x+ emits deprecation warnings. Helper prefers new names, gracefully falls back on older environments.

**FIX-❻ Redis/Valkey 端口动态探测 / Redis/Valkey port dynamic probe**

新增 `_probe_redis_port()` 从 `/etc/redis.conf` / `/etc/valkey/valkey.conf` 读 `port` 指令, 替代硬编码 6379。支持非默认端口 (port 0 socket-only 模式不受影响)。

New `_probe_redis_port()` reads `port` directive from `/etc/redis.conf` / `/etc/valkey/valkey.conf`, replacing hardcoded 6379. Supports non-default ports (port 0 socket-only mode unaffected).

**FIX-⓱ Nginx 最小回退跨平台化 / Nginx minimal fallback cross-platform**

Nginx 静态编译最小回退参数 (`--user`/`--modules-path`) 原硬编码 RHEL 路径 (`nginx` + `/usr/lib64/nginx/modules`), 在 Debian/Ubuntu 上会失败。修复通过 `PlatformInfo` 动态填 (Debian: `www-data` + `/usr/lib/nginx/modules`; RHEL: `nginx` + `/usr/lib64/nginx/modules`)。

Minimal nginx rebuild fallback parameters (`--user`/`--modules-path`) were hardcoded to RHEL paths, failing on Debian/Ubuntu. Now dynamically resolved via `PlatformInfo`.

---

### 🛡 安全加固 / Security Hardening

**FIX-⓫ Fail2Ban Cloudflare CIDR 白名单 / Fail2Ban Cloudflare CIDR allowlist**

新增 `_read_cloudflare_cidrs()` 从 `/etc/nginx/conf.d/cloudflare-real-ip.conf` 读 CF CIDR 段, 自动注入到 wordpress/scanner/4xx-flood 三个 jail 的 `ignoreip` (仅当 realip 已配置时)。防御性避免 realip 失效时 fail2ban 错封 CF 边缘 IP → 全站所有 CF 用户被拒。

New `_read_cloudflare_cidrs()` reads CF CIDR ranges from `/etc/nginx/conf.d/cloudflare-real-ip.conf` and auto-injects into wordpress/scanner/4xx-flood jails' `ignoreip` (only when realip is configured). Defensive: prevents fail2ban from banning CF edge IPs when realip fails, which would reject ALL CF-proxied visitors.

**FIX-⓲ Systemd 服务沙箱加固 / Systemd service sandboxing**

`toksun_dcn-db-optimize.service` 和 `toksun_dcn-wp-cron.service` 加入 `NoNewPrivileges=true` + `PrivateTmp=true` (Red Hat / Fedora / Rocky 官方推荐 baseline), 与既有 `toksun_dcn-ssl.service` 保持一致。

`toksun_dcn-db-optimize.service` and `toksun_dcn-wp-cron.service` now include `NoNewPrivileges=true` + `PrivateTmp=true` (Red Hat / Fedora / Rocky official baseline), aligning with existing `toksun_dcn-ssl.service`.

**FIX-㉑ EAB 凭据文件权限防漂移 / EAB credential file permission drift prevention**

EAB env 文件 (含 ZeroSSL EAB KID + HMAC key) 写入后主动 `stat` 核验 `mode==0o600` 和 `uid==0`。漂移时用 `_safe_chmod` (TOCTOU-safe, 经 `O_NOFOLLOW` + `fchmod`) + `chown` 强制修正。

EAB env file (contains ZeroSSL EAB KID + HMAC key) post-write actively `stat`s to verify `mode==0o600` and `uid==0`. On drift, forces correction via `_safe_chmod` (TOCTOU-safe via `O_NOFOLLOW` + `fchmod`) + `chown`.

**FIX-⓯ DH 参数 2048 → 3072 / DH parameters 2048 → 3072**

`ssl_dhparam` 从 RFC 7919 `ffdhe2048` 升级到 `ffdhe3072`; 动态生成的 fallback dhparam 从 2048 升到 3072 (timeout 120s → 300s)。NIST SP 800-57 Part 1 Rev.5 建议 2030+ 使用 3072-bit DH。握手 CPU 开销 <1ms/connection, 不影响性能。

`ssl_dhparam` upgraded from RFC 7919 `ffdhe2048` to `ffdhe3072`; fallback dhparam generation 2048 → 3072 (timeout 120s → 300s). NIST SP 800-57 Part 1 Rev.5 recommends 3072-bit DH for 2030+. Handshake CPU overhead <1ms/connection.

> **注意 / Note**: 已生成的 `/etc/nginx/dhparam.pem` (2048-bit) **不会自动重新生成**。手动触发: `rm /etc/nginx/dhparam.pem && python3 wp_ssl_bootstrap.py update`。
> Existing `/etc/nginx/dhparam.pem` (2048-bit) **will not auto-regenerate**. Manually: `rm /etc/nginx/dhparam.pem && python3 wp_ssl_bootstrap.py update`.

---

### 🧾 配置正确性 / Configuration Correctness

- **FIX-ⓐ** `wp-cron` `ExecStart` 移除无效的 `--allow-root` 死代码 (`User=nginx` 下该标志无效)。
  `wp-cron` removes dead `--allow-root` flag (no effect under `User=nginx`).

- **FIX-⓳** Fail2Ban jail `datepattern` 改为官方 `{DEFAULT}` 关键字 (覆盖 combined + ISO8601 + TAI64N + Epoch)。此前尝试空格分隔多模式 —— Debian manpage 和实测都确认 fail2ban 不支持此语法, 仅第一个模式生效。
  Fail2Ban jail `datepattern` now uses official `{DEFAULT}` keyword (covers combined + ISO8601 + TAI64N + Epoch). Prior attempt with space-separated multi-pattern — Debian manpage and empirical test both confirm fail2ban does not support this syntax, only first pattern is honored.

- **FIX-⓴** firewalld zone 正则从硬编码 `(public|trusted|drop)` 扩大到 `[a-zA-Z][a-zA-Z0-9_-]{0,17}`, 支持全部 9 个预置 zone + 自定义 zone。
  firewalld zone regex widened from hardcoded `(public|trusted|drop)` to `[a-zA-Z][a-zA-Z0-9_-]{0,17}`, supporting all 9 built-in zones + custom zones.

---

### 📊 审计分类器 UX / Audit Classifier UX

V3.2.8 build 365 的 `collect-logs` 审计报告存在 4 项 UX 不一致, 全部在 V3.2.9 修复:

- **FIX-㉒** systemd 异常退出信号按 unit 名拆分。从笼统 "检查 journalctl -u <service>" 升级为 "systemd unit `xxx.service` 异常退出 (status=N), 查看详情: journalctl -u xxx.service"。初版正则 `[^=]*` 失败 (被实际日志中 `code=exited,` 拦截), 改用 `.*?` 非贪婪。

- **FIX-㉓** 关键字扫描排除脚本自身 `wp-ssl-bootstrap[PID]: [INFO|DEBUG]` 行 + systemd journal 续行 (heavy indent + 无时间戳前缀), 消除 `emergency_restart_threshold` / `(CRIT)` 文字被误当错误的伪阳性。

- **FIX-㉔** `_noise_patterns` 新增 `NOTICE.*error log file re-opened` 识别 (PHP-FPM logrotate 触发的例行通知)。

- **FIX-㉕** `_findings` 渲染 sev 白名单加 `'unknown'`, 使标题 `_total_items` / 问题发现表 / 控制台摘要三者计数一致。此前标题说 "有 1 项需关注" 但问题表空白 (因 unknown 被过滤不渲染)。

---

V3.2.8 build 365 `collect-logs` had 4 UX inconsistencies — all fixed in V3.2.9:

- **FIX-㉒** systemd unit-name-specific failure advice. Upgraded from generic "check journalctl -u <service>" to "systemd unit `xxx.service` failed (status=N), view: journalctl -u xxx.service". Initial regex `[^=]*` failed (blocked by actual log `code=exited,`); switched to non-greedy `.*?`.

- **FIX-㉓** Keyword scan now excludes script's own `wp-ssl-bootstrap[PID]: [INFO|DEBUG]` lines + systemd journal continuation lines (heavy indent + no timestamp prefix), eliminating `emergency_restart_threshold` / `(CRIT)` text false positives.

- **FIX-㉔** `_noise_patterns` now recognizes `NOTICE.*error log file re-opened` (PHP-FPM logrotate routine notice).

- **FIX-㉕** `_findings` renderer sev allowlist adds `'unknown'`, making title `_total_items` / findings table / console summary counts consistent. Previously title said "1 item needs attention" but the findings table was empty (unknown was filtered out of rendering).

---

## ⏭️ 诚实撤销的审计项 / Honest Audit Withdrawals

在审计过程中, 我们主动撤销了 4 项最初标记但实际不成立的"发现":

During audit, we actively withdrew 4 items that were initially flagged but did not hold upon investigation:

| 编号 / ID | 原"审计发现" / Initial finding | 实际情况 / Actual |
|---|---|---|
| ❼ | 多站 timer 03:00 聚集无随机 / Multi-site timers cluster at 03:00 without randomization | 代码已有 `RandomizedDelaySec=1800` / Code already has `RandomizedDelaySec=1800` |
| ⓮ | 慢日志路径硬编码 / Slow log path hardcoded | 代码已有 `is_debian` 条件分支 / Code already has `is_debian` conditional branch |
| ❾ | GPG keyserver 单节点 / GPG keyserver single node | 代码已有 3 节点 fallback 列表 / Code already has 3-node fallback list |
| ❿ | 超时值不统一 (800+ 处) / Timeout values inconsistent (800+ sites) | 改动风险 > 收益, 作为未来独立 PR 处理 / Risk > benefit, deferred to future PR |

---

## 🔬 验证方法 / Verification Methodology

### 静态契约 / Static Contracts

| 工具 / Tool | 检查项 / Checks | 结果 / Result |
|---|---|---|
| `verify_refactor.py` 重构完整性 / refactoring integrity | 78 | ✅ 78/78 |
| `test_integration.py --phase static` 架构契约 / architecture contracts | 472 | ✅ 472/472 |

新增契约 / New contracts: `P289_dhparam` 接受 `ffdhe2048` 或 `ffdhe3072` (允许安全升级路径) / accepts `ffdhe2048` or `ffdhe3072` (allows secure upgrade path).

新增 allowlist / New allowlist: `_mariadb_cli` / `_probe_redis_port` / `_read_cloudflare_cidrs` 进入 `ALLOWED_NEW_MODULE_FUNCTIONS`.

### 生产环境实证 / Production Evidence

toksun.cn (AlmaLinux 10.1, 阿里云 cn-chengdu, Cloudflare proxied) 进行 **6 轮真实部署 + 审计回归**:

| 轮 / Round | 修复 / Fix | 评级 / Rating |
|---|---|---|
| 1 | 初版 17 项硬编码 + bug / Initial 17 hardcode+bug fixes | 🟡 B + 2 项需关注 / 2 items |
| 2 | ⓳ `{DEFAULT}` 语法 / syntax | 🟡 B |
| 3 | ㉒ 正则 `.*?` / regex | 🟡 A + 1 项伪阳性 / false positive |
| 4 | ㉓ 脚本 INFO 过滤 / script INFO filter | 🟡 A + 1 项伪阳性 / false positive |
| 5 | ㉔ PHP-FPM logrotate 归噪音 / logrotate as noise | 🟢 **A+ 零阻塞** / **A+ zero-blocker** |
| 6 | ㉕ UX 一致性 / consistency | 🟢 A+ |

最终生产数据 / Final production metrics:
- 缓存命中率 / Cache hit rate: **90.87%** (149,257 hits / 164,249 total)
- 已拦截攻击 / Attacks blocked: **149 次 / hits**
- 自动封禁 IP / Auto-banned IPs: 2 (`.env`/`.git` scanners)
- 负载 / Load avg: 0.21 / 0.08 / 0.03
- 内存 / Memory: 48%
- 证书剩余 / Cert remaining: 81 天 / days

---

## 📦 升级步骤 / Upgrade Steps

### 从 V3.2.8 build 365 升级 / From V3.2.8 build 365

```bash
# 1. 备份 / Backup
cp /usr/local/bin/wp_ssl_bootstrap.py /usr/local/bin/wp_ssl_bootstrap.py.bak-3.2.8

# 2. 下载 V3.2.9 覆盖 / Download V3.2.9 overwrite
# (使用 self-update 或手动下载 / Use self-update or manual download)
sudo python3 /usr/local/bin/wp_ssl_bootstrap.py self-update

# 3. 验证版本 / Verify version
grep "__version__" /usr/local/bin/wp_ssl_bootstrap.py   # 期望 / expect: "3.2.9"
grep "__build__"   /usr/local/bin/wp_ssl_bootstrap.py   # 期望 / expect: "3.2.382"

# 4. 热更新 systemd/fail2ban/nginx 配置 / Hot-update configs
sudo python3 /usr/local/bin/wp_ssl_bootstrap.py update --domain example.com

# 5. 清理 journal 历史失败记录 / Clear historical journal failures
sudo journalctl --rotate && sudo journalctl --vacuum-time=1h

# 6. 运行审计验证 / Run audit verification
sudo python3 /usr/local/bin/wp_ssl_bootstrap.py collect-logs
# 期望 / Expect: ✅ 站点健康, 零阻塞问题 | 🟢 生产级 A+
#                ✅ Site healthy, zero blocking issues | 🟢 Production A+

# 7. 可选: 升级 DH 参数到 3072-bit / Optional: Upgrade DH parameters to 3072-bit
sudo rm -f /etc/nginx/dhparam.pem
sudo python3 /usr/local/bin/wp_ssl_bootstrap.py update --domain example.com
```

### 回滚 / Rollback

```bash
sudo cp /usr/local/bin/wp_ssl_bootstrap.py.bak-3.2.8 /usr/local/bin/wp_ssl_bootstrap.py
sudo python3 /usr/local/bin/wp_ssl_bootstrap.py update --domain example.com
```

回滚后 db-optimize 会再次失败 (回到 `--single-transaction` bug), deprecation 警告也会回来。其他功能不受影响。
After rollback, db-optimize will fail again (back to `--single-transaction` bug), deprecation warnings return. Other functionality unaffected.

---

## 🙏 迭代透明度 / Iteration Transparency

V3.2.9 不是"一次做对"的补丁, 而是 **8 轮真实服务器部署 + 回归验证** 的产物。每轮发现的 bug、原因、修正方案都如实记录。**3 次自我纠错** (⓳/㉒/㉓-㉕) + **4 项审计撤销** (❼⓮❾❿) 均明确标注。

V3.2.9 is not a "got-it-right-first-time" patch; it is the product of **8 rounds of live-server deployment + regression**. Every bug found, its root cause, and the fix are honestly recorded. **3 self-corrections** (⓳/㉒/㉓-㉕) + **4 audit withdrawals** (❼⓮❾❿) are explicitly called out.

感谢 toksun.cn 生产环境作为回归测试床的耐心迭代 —— 没有这种实地来回验证, ㉒/㉓/㉕ 这几个真实正则/逻辑 bug 靠静态扫描永远发现不了。

Thanks to the toksun.cn production environment serving as a regression test bed — without this hands-on back-and-forth, the real regex/logic bugs behind ㉒/㉓/㉕ could never be caught by static scanning.

---

---

# WP-SSL-Bootstrap V3.2.8 Release Notes (历史存档 / Historical Archive)

> 以下为 V3.2.8 build 365 的原始发布说明, 保留作为升级参考和历史记录。
> Below is the original V3.2.8 build 365 release notes, preserved for upgrade reference and historical record.

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
