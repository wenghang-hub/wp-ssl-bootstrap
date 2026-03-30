# V3.2.4 — Stability & i18n Hardening Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.4

V3.2.4 refines V3.2.3 through 8 patches (PATCH-262–269) plus a comprehensive i18n audit, adding Nginx dynamic module auto-repair, FastCGI snippet deduplication, modernized CSP security policy, proactive Nginx minor-version upgrades, and a full i18n system cleanup. Net +6,946 lines (29,133→36,079).

🔧 **Nginx dynamic module auto-repair (PATCH-268)** — when `nginx -t` detects dynamic module load failures (ABI mismatch / undefined symbol / missing .so), automatically attempts reinstall → if that fails, removes .so → cleans orphaned `load_module` directives and module-specific directives, iterating until `nginx -t` passes. srcache compilation now uses full `nginx -V` configure arguments (replacing `--with-compat` fallback) for better ABI compatibility.

📎 **FastCGI PHP snippet deduplication (PATCH-267)** — extracts repeated 5-line fastcgi configuration from `location ~ \.php$` blocks into `/etc/nginx/snippets/fastcgi-php.conf`; all location blocks reference it via `include`, eliminating cross-block config drift. Auto-cleaned on uninstall.

⬆️ **Proactive Nginx minor-version upgrades (PATCH-268)** — when installed Nginx meets the minimum version but is below the repo's latest patch version, proactively upgrades (e.g. 1.28.0→1.28.1) followed by the unified verification chain (`nginx -t` → module repair → graceful restart).

🛡️ **Modernized CSP security policy (PATCH-268/269)** — removed deprecated `X-Frame-Options` (superseded by `frame-ancestors`) and `X-XSS-Protection` (built into modern browsers; the header can introduce XSS auditing side-channels). CSP relaxed to WordPress-practical policy (`'unsafe-inline'`/`'unsafe-eval'` for theme/plugin compatibility + `img-src data: blob:` for media library). Added `upgrade-insecure-requests` for automatic HTTP→HTTPS sub-resource upgrade. Temporary ACME-challenge Nginx config now includes basic security headers to prevent exposure after interrupted deployments.

🌐 **Comprehensive i18n audit** — 15 `_MESSAGES` keys containing Chinese characters renamed to ASCII convention with proper English translations; 3 hardcoded Chinese `logging.warning()` calls routed through `t()` with new bilingual entries; `generate_http_production_config()` docstring documents why `http3=` is intentionally omitted (QUIC requires TLS).

🐛 **Debian ABI-locked module cleanup (PATCH-262 FIX-P5)** — after switching from Debian `nginx-core` to nginx.org packages, residual ABI-locked module packages (`libnginx-mod-*`) caused `nginx -t` failures. Now auto-detects and removes incompatible packages.

🐛 **Missing fastcgi.conf after nginx.org switch (PATCH-263 FIX-2)** — `_ensure_fastcgi_conf()` now called for all `cache_mode` paths, not just srcache, ensuring the file exists after switching from AppStream `nginx-core`.

🐛 **srcache residual directive cleanup (PATCH-263 FIX-5)** — after srcache compilation failure and degradation, residual `load_module` directives could leave Nginx in a broken state. Now uses aggressive cleanup + snapshot rollback + manual fix hint as three-tier fallback.

🐛 **EL10 nginx module stream conflict (PATCH-264 FIX-1)** — `dnf module disable nginx` on EL10 prevents module stream conflicts with nginx.org repo, aligned with EL8/EL9 path.

🐛 **EL10 pcre-devel removal (PATCH-265 FIX-1)** — EL10+ removed `pcre-devel`; srcache build dependency list now conditionally excludes it based on `_el_major`.

🐛 **Service not-installed status (PATCH-269 FIX-3)** — `status` subcommand now shows "not installed" for missing Nginx/PHP-FPM, distinguishing from "inactive" (installed but stopped).

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate, OS auto-security-updates — all from a single `deploy` command.

🔒 **Production-grade security** — modernized CSP policy with `frame-ancestors` and `upgrade-insecure-requests`; zero CLI password leakage, atomic config writes with symlink protection, wp-config hardening, Nginx defense-in-depth with dynamic module auto-repair, certbot error circuit-breaker with multi-CA failover, supply-chain protection via dual-source cross-verification.

🔧 **Self-healing Nginx** — dynamic module load errors (ABI mismatch after upgrades, missing .so files, orphaned directives) are automatically diagnosed and repaired through a multi-iteration cascade: reinstall → remove → directive cleanup → `nginx -t` verification. Proactive minor-version upgrades keep Nginx at the latest patch level.

🐘 **PHP lifecycle management** — automatic version detection, repository setup (Remi/Ondrej/Sury), in-place upgrade with `php.ini` migration, old service cleanup. Future PHP bumps require only constant changes (`_PHP_MIN_VERSION`, `_PHP_DEFAULT_VERSION`).

🌐 **Multi-distro** — tested on EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux), Ubuntu 20.04–24.04, Debian 11–13.

⚡ **Performance options** — FastCGI page cache, Redis full-page cache (srcache), Redis object cache (with source-compile fallback + Valkey support), HTTP/3 QUIC, Brotli compression, ECDSA certificates (all optional, composable).

📦 **Ops toolkit** — `backup`, `restore`, `update`, `enable-ssl`, `status`, `self-update`, `uninstall` subcommands for day-2 operations — with atomic DB restore, plugin safe-upgrade, and webhook alerting.

🌍 **Bilingual** — full Chinese/English interface, auto-detected from system locale. V3.2.4 completes the i18n audit: zero hardcoded Chinese in logging paths, all message keys use ASCII naming convention.

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

# Enable HTTP/3 on existing site
sudo python3 wp_ssl_bootstrap.py update --domain example.com --http3

# Disable auto-detected Redis during update
sudo python3 wp_ssl_bootstrap.py update --domain example.com --no-redis
```

See [deploy-guide.md](./deploy-guide.md) for scenario-based examples and [README.md](./README.md) for full documentation.

## Upgrade from V3.2.3

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

Nginx module auto-repair activates immediately — any existing dynamic module load errors will be diagnosed and fixed on next `update` or `deploy`. CSP headers are updated automatically. The i18n fixes are transparent: English users who previously saw Chinese log messages in tar backup paths will now see proper English. No manual reconfiguration needed.

## Upgrade from V3.2.2

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.3 + V3.2.4 features activate automatically. PHP auto-upgrade runs on next deploy/redeploy if installed PHP is below 8.3.

## Upgrade from V3.2.1

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.2 + V3.2.3 + V3.2.4 features activate automatically. Existing timers inherit parameters from EnvironmentFile — no manual reconfiguration needed.

## Upgrade from V3.2.0

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.1 + V3.2.2 + V3.2.3 + V3.2.4 features activate automatically. Existing SSL timers inherit parameters from previous unit files.

## Upgrade from V3.1.x

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.x configs (Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers / webhook / HTTP/3 / srcache / PHP upgrade / Nginx module repair) rebuild automatically.

## Key Bug Fixes (V3.2.4)

- **Debian ABI-locked modules (PATCH-262 FIX-P5)** — residual `libnginx-mod-*` packages after nginx-core→nginx.org switch now auto-removed
- **logrotate postrotate (PATCH-262 FIX-P8)** — standardized to USR1 signal, replacing PID-file-dependent patterns
- **Missing fastcgi.conf (PATCH-263 FIX-2)** — `_ensure_fastcgi_conf()` now runs for all cache modes, not just srcache
- **srcache orphaned directives (PATCH-263 FIX-5)** — aggressive cleanup + snapshot rollback + manual fix hint on compilation failure
- **EL10 nginx module stream (PATCH-264 FIX-1)** — `dnf module disable nginx` prevents repo conflict on EL10
- **EL10 pcre-devel (PATCH-265 FIX-1)** — removed from srcache build deps on EL10+ (package no longer exists)
- **Service status display (PATCH-269 FIX-3)** — "not installed" vs "inactive" now correctly distinguished

## i18n Fixes (V3.2.4)

- **15 Chinese-character keys renamed** — `_MESSAGES` keys like `warn_redis_安装失败_部署将继续_不含_redis` renamed to ASCII convention (`warn_redis_install_failed_continuing_without_redis`); `en` field replaced with actual English translation; all call sites updated
- **3 hardcoded Chinese `logging.warning()` fixed** — tar backup error messages (`warn_tar_error_detail`, `warn_tar_letsencrypt_error_detail`, `warn_tar_partial_files_changed`) now routed through `t()` with bilingual entries
- **`--skip-ssl` path documented** — `generate_http_production_config()` docstring explains `http3=` omission (QUIC requires TLS)

## Security Enhancements (V3.2.4)

- **CSP modernization** — removed deprecated `X-Frame-Options` and `X-XSS-Protection`; added `frame-ancestors 'self'`, `upgrade-insecure-requests`; relaxed CSP for WordPress theme/plugin compatibility
- **Temporary config security headers (PATCH-269)** — ACME challenge phase Nginx config now includes security headers to prevent exposure after deployment interruption
- **srcache ABI improvement (PATCH-268)** — compilation uses full `nginx -V` configure arguments instead of `--with-compat` fallback

## Requirements

- Root access, Python 3.6+
- Domain with DNS records pointing to your server
- Ports 80 and 443 open

Everything else is installed automatically. PHP < 8.3 is automatically upgraded to 8.4.

## Checksums

```
SHA256: 88210d30acf269bf411e671627482a17712d9aaf3ddb75011e2ca605288fb09d  wp_ssl_bootstrap.py
```

## License

MIT
