# V3.2.5 — Automation & Resilience Hardening Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.5

V3.2.5 refines V3.2.4 through 11 patches (PATCH-270–280), transforming the script from "warn and bail" to "diagnose, auto-fix, retry". An exhaustive audit of all 507 `logging.warning` calls yielded 14 auto-remediation patterns; adds short-lived certificate support with dynamic timer frequency, journal/email fallback notification for renewal failures, full component lifecycle management, and fixes a MariaDB tuning "self-lock" bug plus 5 Nginx config comment false-match issues. 100% type annotation coverage (439/439 functions). Net +4,054 lines (36,079→40,133).

🤖 **14 warn-and-bail auto-remediation patterns (PATCH-279)** — exhaustive audit of every `logging.warning` in the script. Where the script previously warned and gave up, it now diagnoses and auto-fixes: missing logrotate/curl auto-installed, failed DB auto-restarted, `nginx -t` errors auto-repaired (stale includes, duplicate default_server — with backup before modification), file deletion retried with `chattr -i` (immutable bit removal), PHP-FPM failures auto-diagnosed via `php-fpm -t` (wrong user/group, socket conflict), Redis start failures diagnosed via journal (port conflict, bad config), Redis ping failures auto-restarted, MariaDB conf.d auto-created with `!includedir`, Nginx minor upgrade retried after `apt --fix-broken`/`yum clean all`, redis-cache plugin retried with `--force`, nginx.list parent dir auto-created.

⏱️ **Short-lived certificate auto-detection + dynamic timer (PATCH-277)** — reads certificate total lifetime (Not After − Not Before) and auto-adjusts systemd timer: daily for standard 90-day certs, every 8h for LE 2027 47-day certs, every 4h for 2028 6-day certs. Auto-detects lifetime changes after each renewal and hot-updates the timer frequency — zero manual intervention needed for the upcoming Let's Encrypt short-lived certificate transition.

📣 **Journal/email fallback for renewal failures (PATCH-278)** — when no `--notify-webhook` is configured, auto-installs a systemd OnFailure service: renewal failures are logged to journal at CRIT priority + syslog via `logger` + email attempted via `mail(1)` to root. Ensures renewal failures are **never completely silent**, even on minimal installs without external monitoring.

🔄 **Full component lifecycle management (PATCH-270)** — Certbot: snap detection → version gating → pip venv migration (6-step EFF official procedure); Redis/Valkey: version detection → minor upgrades → EL10+ Valkey auto-switch; WP-CLI: version detection → auto-update → SHA-512 verification; fail2ban: version probing → legacy compat (below 0.11).

🔑 **MariaDB GPG 4-level key fallback (PATCH-275)** — MariaDB repo GPG key import on Debian/Ubuntu now has 4 fallback levels, aligned with the existing Nginx key fallback: ① direct download from supplychain.mariadb.com + mariadb.org ② GPG keyserver (ubuntu keyserver → openpgp.org) ③ script-embedded ASCII-armored public key ④ legacy `apt-key` fallback. APT pinning aligned with nginx.org official format (PATCH-272).

🐛 **MariaDB tuning "self-lock" bug (PATCH-280)** — the generated `.cnf` file's instructional comment `# add a line containing '# User-modified'` contained the marker string itself, causing the substring check to always match → tuning **perpetually skipped** → RAM changes and version upgrades never updated MariaDB parameters. Fix: detection changed to line-level regex `^\s*#\s*User-modified\s*$`; template text reworded to not embed the literal marker.

🐛 **Nginx config comment false-match ×5 (PATCH-280)** — 5 substring checks on raw Nginx config could match commented-out directives (e.g. `# srcache_fetch ...`), causing wrong cache mode in `status` output, incorrect log levels, or commented lines treated as SSL blocks. Fix: 3 sites now use `_strip_nginx_comments_d5()` before checking; 1 site adds `startswith("#")` skip.

🐛 **Massive exception safety sweep (PATCH-276, 270 sites)** — full-script `except Exception` path audit: added missing `logging.debug` for exception recording, caught unhandled `subprocess.TimeoutExpired`, ensured `finally` blocks don't recurse on secondary exceptions, fixed command failures being completely silent in quiet mode.

🐛 **EL7 EOL graceful degradation (PATCH-272)** — Certbot/PHP/MariaDB/Nginx/Redis upgrade paths on EL7 (EOL 2024-06) now gracefully skip with logged warnings instead of failing due to unavailable repos.

📐 **100% type annotation coverage (PATCH-277)** — all 439 functions have return-type annotations. Supports `mypy` and `pyright` checking.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate, OS auto-security-updates — all from a single `deploy` command.

🤖 **Self-healing** — 14 common failure scenarios are now automatically diagnosed and repaired, from missing system packages to crashed database services to Nginx config syntax errors. The script recovers from failures that previously required manual intervention.

🔒 **Production-grade security** — modernized CSP policy, zero CLI password leakage, atomic config writes with symlink protection, wp-config hardening, Nginx defense-in-depth with dynamic module auto-repair, certbot error circuit-breaker with multi-CA failover, supply-chain protection via dual-source cross-verification, GPG key 4-level fallback for Nginx and MariaDB repos.

⏱️ **Future-proof certificates** — automatic detection and adaptation for Let's Encrypt's upcoming short-lived certificate transition (47-day in 2027, 6-day in 2028), with dynamic timer frequency adjustment and guaranteed failure alerting.

🔄 **Component lifecycle** — automatic version management for Certbot (snap migration + pip venv), Redis/Valkey (version-aware upgrades), WP-CLI (auto-update + SHA-512), PHP (auto-upgrade to 8.4), Nginx (proactive minor upgrades), MariaDB (version-aware repo setup), fail2ban (legacy compat).

🐘 **PHP lifecycle management** — automatic version detection, repository setup (Remi/Ondrej/Sury), in-place upgrade with `php.ini` migration, old service cleanup.

🌐 **Multi-distro** — tested on EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux), Ubuntu 20.04–24.04, Debian 11–13.

⚡ **Performance options** — FastCGI page cache, Redis full-page cache (srcache), Redis object cache (with source-compile fallback + Valkey support), HTTP/3 QUIC, Brotli compression, ECDSA certificates (all optional, composable).

📦 **Ops toolkit** — `backup`, `restore`, `update`, `enable-ssl`, `status`, `self-update`, `uninstall` subcommands for day-2 operations — with atomic DB restore, plugin safe-upgrade, and webhook alerting (with journal/email fallback).

🌍 **Bilingual** — full Chinese/English interface, auto-detected from system locale.

## Quick Start

```bash
# Interactive wizard
sudo python3 wp_ssl_bootstrap.py

# Or specify everything
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com

# Full performance stack: FastCGI + Redis + HTTP/3
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --cache fastcgi --redis --http3

# Redis full-page cache (srcache, replaces FastCGI)
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --cache redis

# Two-phase: HTTP first, SSL later
sudo python3 wp_ssl_bootstrap.py deploy --domain example.com --skip-ssl
sudo python3 wp_ssl_bootstrap.py enable-ssl --domain example.com --email admin@example.com
```

See [deploy-guide.md](./deploy-guide.md) for scenario-based examples and [README.md](./README.md) for full documentation.

## Upgrade from V3.2.4

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.5 features activate immediately:
- **MariaDB tuning** will regenerate on next `update` (the "self-lock" bug prevented all previous updates from taking effect)
- **Self-healing** activates automatically — existing failure scenarios that required manual intervention will now auto-repair
- **Certificate timer** adjusts automatically if you have a short-lived certificate
- **Renewal failure notification** auto-installs the journal/email fallback if no `--notify-webhook` was configured
- **Component lifecycle** checks will run: Certbot version, Redis version, WP-CLI version, fail2ban compatibility
- No manual reconfiguration needed

## Upgrade from V3.2.3

```bash
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.4 + V3.2.5 features activate automatically.

## Upgrade from V3.2.2 / V3.2.1 / V3.2.0 / V3.1.x

```bash
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All accumulated features activate automatically. Existing SSL timers inherit parameters from previous unit files.

## Self-Healing Scenarios (V3.2.5)

| Failure | Previous Behavior | V3.2.5 Behavior |
|---|---|---|
| logrotate not installed | Warn, skip → logs grow unbounded | Auto-install package + mkdir |
| curl not available | Warn, skip health check | Auto-install curl |
| MariaDB wait timeout | Warn, return False | Restart DB service + 15s retry |
| `nginx -t` fails | Warn, skip reload | Capture error, fix stale include / dup default_server, re-test |
| File deletion blocked | Warn ×9, exit_code=1 | `chattr -i` + retry (all 9 cleanup sites) |
| DROP DATABASE fails | Warn, leave residual | Restart DB + retry both auth methods |
| PHP-FPM won't restart | Warn, return | `php-fpm -t` diagnose → fix user/group or kill stale processes |
| Redis won't start | Warn, return | Journal inspect → kill port conflict or backup bad config |
| Redis ping fails | Warn, skip object cache | Restart service + re-verify |
| MariaDB conf.d missing | Warn, skip tuning | Create dir + add `!includedir` to my.cnf |
| Nginx upgrade fails | Warn, skip | `apt --fix-broken` / `yum clean all` + retry |
| Redis plugin fails | Warn, skip | Retry with `--force` |
| nginx.list write fails | Warn, skip repo | Create parent dir + retry |

## Key Bug Fixes (V3.2.5)

- **MariaDB tuning self-lock (PATCH-280)** — instructional comment in generated `.cnf` contained the `# User-modified` marker string, causing tuning to be perpetually skipped
- **Nginx config comment false-match ×5 (PATCH-280)** — substring checks on raw config matched commented-out directives, causing wrong status display, log level errors, and SSL block misidentification
- **Exception safety sweep (PATCH-276, 270 sites)** — full `except Exception` path audit with missing debug logging, unhandled timeouts, recursive finally blocks, and silent quiet-mode failures
- **EL7 EOL degradation (PATCH-272)** — component upgrade paths on EL7 now gracefully skip instead of erroring on unavailable repos

## Security Enhancements (V3.2.5)

- **MariaDB GPG 4-level key fallback (PATCH-275)** — direct download → keyserver → embedded key → apt-key, aligned with Nginx key fallback
- **APT pinning (PATCH-272)** — aligned with nginx.org official format; fixes invalid dual-line `Pin:` syntax silently ignored by apt
- **Nginx config auto-fix safety (PATCH-279)** — all auto-modifications create `.bak279` backup before writing; stale include fix uses precise regex targeting; default_server fix restricted to site-owned config files

## Requirements

- Root access, Python 3.6+
- Domain with DNS records pointing to your server
- Ports 80 and 443 open

Everything else is installed automatically. PHP < 8.3 is automatically upgraded to 8.4.

## License

MIT
