# V3.2.2 — Feature & Stability Hardening Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.2

V3.2.2 refines V3.2.1 through 44 internal iterations plus 8 independent deep audit rounds, adding major new features and fixing 40+ defects across crash safety, credential inheritance, config detection, and cross-path alignment.

🚀 **HTTP/3 QUIC (`--http3`)** — auto-detects Nginx `http_v3` module; generates QUIC `listen` directives and `Alt-Svc` headers; auto-opens UDP 443 firewall port (firewalld/ufw/iptables); shares `reuseport` across multi-site; silently ignored when unsupported. Interactive wizard auto-recommends based on Nginx capability.

🗄️ **Redis full-page cache (`--cache redis`)** — srcache-nginx-module based Redis page cache; auto-compiles 5 OpenResty dynamic modules (ngx_devel_kit / set-misc / echo / redis2 / srcache) with ABI pre-check and runtime worker survival verification; auto-degrades to FastCGI on compile failure; auto-installs Redis if unavailable; nginx-helper plugin auto-adapts cache purge protocol.

🔀 **`--no-*` reverse switches** — new `--no-redis` / `--no-optimize` / `--no-cloudflare` / `--no-http3` / `--no-allow-xmlrpc` flags for `update`/`enable-ssl`/`restore` to explicitly disable auto-detected features and prevent `_apply_auto_detected_config()` from overriding user intent.

🔍 **Auto config detection** — `update`/`enable-ssl`/`restore` automatically inherit `cache`/`redis`/`optimize`/`http3`/`cloudflare`/`allow_xmlrpc` from existing Nginx config and `wp-config.php` — no need to re-pass flags each time.

🛒 **WooCommerce cache exclusion** — FastCGI cache automatically detects WooCommerce cart/checkout/my-account pages and session cookies; bypasses cache to prevent cart data leaking across users.

🔒 **EAB/webhook credentials secured** — ZeroSSL EAB and webhook URL moved from systemd ExecStart to EnvironmentFile (0o600), preventing `/proc/<pid>/cmdline` exposure. Timer parameter inheritance now reads from EnvironmentFile with systemd double-quote unescape.

💥 **Crash-safe wp-config writes** — 3 O_TRUNC write sites in `_ensure_wp_cron_constant_locked` replaced with atomic tmp+fsync+replace, preventing zero-byte wp-config.php on OOM kill (white screen 500).

🔧 **`uninstall` cron fix** — `uninstall` now reverts `DISABLE_WP_CRON=true` in wp-config.php; previously WordPress built-in cron was permanently broken after uninstall (auto-updates, scheduled posts, trash cleanup all disabled).

🔗 **EnvironmentFile inheritance** — `_extract_timer_params` now reads credentials from `.env` files (PATCH-190 moved them from ExecStart but inheritance was not updated); `update`/`enable-ssl`/`restore` no longer silently lose ZeroSSL CA failover and webhook notifications.

📊 **8-round deep audit** — 17 defects found and fixed across comment stripping consistency, xmlrpc detection regression, fastcgi cache dir alignment, long-domain systemd prefix truncation, and more.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate, OS auto-security-updates — all from a single `deploy` command.

🔒 **Production-grade security** — zero CLI password leakage, atomic config writes with symlink protection, wp-config hardening, Nginx defense-in-depth, certbot error circuit-breaker with multi-CA failover, supply-chain protection via dual-source cross-verification.

🌐 **Multi-distro** — tested on EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux), Ubuntu 20.04–24.04, Debian 11–12.

⚡ **Performance options** — FastCGI page cache, Redis full-page cache (srcache), Redis object cache (with source-compile fallback + Valkey support), HTTP/3 QUIC, Brotli compression, ECDSA certificates (all optional, composable).

📦 **Ops toolkit** — `backup`, `restore`, `update`, `enable-ssl`, `status`, `self-update`, `uninstall` subcommands for day-2 operations — with atomic DB restore, plugin safe-upgrade, and webhook alerting.

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

# Enable HTTP/3 on existing site
sudo python3 wp_ssl_bootstrap.py update --domain example.com --http3

# Disable auto-detected Redis during update
sudo python3 wp_ssl_bootstrap.py update --domain example.com --no-redis
```

See [deploy-guide.md](./deploy-guide.md) for scenario-based examples and [README.md](./README.md) for full documentation.

## Upgrade from V3.2.1

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

New features (HTTP/3, Redis srcache, auto config detection, `--no-*` switches, WooCommerce cache exclusion) activate automatically. Existing timers inherit parameters from EnvironmentFile — no manual reconfiguration needed. PATCH-203~208 fixes (crash-safe wp-config writes, uninstall cron revert, credential inheritance) apply immediately.

## Upgrade from V3.2.0

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.1 + V3.2.2 features activate automatically. Existing SSL timers inherit parameters from previous unit files.

## Upgrade from V3.1.x

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.0 + V3.2.1 + V3.2.2 configs (Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers / webhook / HTTP/3 / srcache) rebuild automatically.

## Key Bug Fixes (V3.2.2)

- **Crash-safe wp-config writes** — 3 O_TRUNC sites replaced with atomic tmp+fsync+replace (OOM kill no longer produces zero-byte file)
- **`uninstall` cron revert** — `DISABLE_WP_CRON=true` now reverted on uninstall (WordPress cron no longer permanently broken)
- **EnvironmentFile credential inheritance** — ZeroSSL EAB and webhook no longer silently lost when timers are rebuilt
- **xmlrpc detection regression** — `allow_xmlrpc` no longer false-negative when Nginx comments contain `xmlrpc` far from actual location block
- **restore path alignment** — `_apply_auto_detected_config()`, `_ensure_fastcgi_cache_dir()`, `_align_nginx_with_cert()` all added to restore path
- **Long-domain systemd prefix** — interactive `update`/`enable-ssl` no longer silently loses inherited params for domains >48 chars after encoding
- **mysqldump stderr ERROR** — exit 0 with stderr ERROR now detected and marked as partial backup
- **MySQL identifier overflow** — `RENAME TABLE` temp names truncated to 64-char MySQL limit
- **VIEW migration in restore** — VIEWs now migrated via `CREATE`+`DROP` (not supported by `RENAME TABLE`)
- **DEFINER clause stripping** — cross-server restore no longer fails on `DEFINER` permission errors
- **gzip pipe verification** — backup pipeline now verifies both mysqldump and gzip exit codes
- **select-based pipe drain** — stderr drain threads no longer leak on child process exit

## Requirements

- Root access, Python 3.6+
- Domain with DNS records pointing to your server
- Ports 80 and 443 open

Everything else is installed automatically.

## Checksums

```
SHA256: <fill after build>  wp_ssl_bootstrap.py
```

## License

MIT
