# V3.2.3 — Security & Architecture Hardening Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.3

V3.2.3 refines V3.2.2 through 10 audit rounds and 51 pattern-verified checks, adding automatic PHP version management, 24 security fixes, git tag-pinned builds, and 6 logic defect fixes. Net +1,126 lines (28,007→29,133).

🐘 **Automatic PHP upgrade** — detects installed PHP version; auto-upgrades to 8.4 when below 8.3 minimum. EL via EPEL + Remi repo + `dnf module enable php:remi-8.4` + `dnf update php*`; Ubuntu via Ondrej PPA; Debian via Sury DPA (DEB822). Migrates custom `php.ini` settings (`upload_max_filesize`, `post_max_size`, `memory_limit`, `max_execution_time`) post-upgrade, disables old PHP-FPM service, restarts new service. Covers 7 distros: EL8/9 (Remi), EL10 (native), Ubuntu 22.04 (Ondrej), Ubuntu 24.04 (native), Debian 12 (Sury), Debian 13 (native). `--php-version` now forces version switch even when installed PHP meets minimum.

📌 **Git tag-pinned module builds** — 5 OpenResty modules for srcache/Brotli compilation switched from commit hashes to git tags (`v0.3.4` / `v0.33` / `v0.64` / `v0.15` / `v0.33`), fixing GitHub shallow-clone rejection. ngx_brotli uses HEAD clone (v1.0.0rc from 2018 fails on GCC 13+). echo-nginx-module upgraded v0.63→v0.64.

🛡️ **4 unified security entry-point functions** — `_safe_rmtree` (parent whitelist + symlink block + `../` filter), `_safe_copy2` (bidirectional symlink check on src and dst), `_safe_mkstemp` (`O_NOFOLLOW` + `fchmod` dual protection), `_verify_gzip_integrity` (pre-extract CRC check). All 45 call sites unified through these entry points.

🔒 **Secure tar extraction (`_safe_extract_tar`)** — enforces `--no-same-owner --no-same-permissions`, path traversal detection (`..` / absolute paths / symlink member filtering), output directory whitelist, extraction timeout, artifact verification. Covers WordPress, WP-CLI, Nginx source, and compiled artifacts (6 sites).

💣 **Gzip bomb protection** — all `.tar.gz` / `.sql.gz` files validated via `gzip -t` integrity check before extraction. Covers WordPress download, backup restore, and WP-CLI extraction.

🔗 **Destination symlink attack prevention (FIX-B2)** — `_safe_copy2` now checks final destination path (including dir+basename join) for symlinks, preventing attacker-planted symlinks from redirecting file writes.

🐛 **clean+redeploy PHP bypass fix (PATCH-261d)** — `_all_critical_deps_present()` previously only checked if `php` binary existed, not its version. After `clean`→`redeploy`, PHP 8.0 remained and was never upgraded. Now checks PHP ≥8.3 (aligned with Nginx ≥1.26 check pattern).

🐛 **`--php-version` skip-path fix (PATCH-261e)** — `--php-version 8.5` was silently ignored when PHP 8.4 was already installed (≥8.3 triggered fast-skip). Now compares requested version against installed and forces install path when different.

🐛 **`php-redis` version prefix fix (PATCH-261f)** — apt path used unversioned `php-redis` which could install the Redis extension for the wrong PHP version in Ondrej parallel-install environments. Now builds versioned package name (e.g. `php8.4-redis`).

🐛 **EL in-place PHP-FPM restart (FIX-A6)** — EL PHP upgrade keeps the same service name (`php-fpm`→`php-fpm`); `systemctl enable --now` doesn't restart an already-running service. Now issues explicit `systemctl restart` for same-name upgrades.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate, OS auto-security-updates — all from a single `deploy` command.

🔒 **Production-grade security** — 24 new security fixes in this release; zero CLI password leakage, atomic config writes with symlink protection, wp-config hardening, Nginx defense-in-depth, certbot error circuit-breaker with multi-CA failover, supply-chain protection via dual-source cross-verification.

🐘 **PHP lifecycle management** — automatic version detection, repository setup (Remi/Ondrej/Sury), in-place upgrade with `php.ini` migration, old service cleanup. Future PHP bumps require only constant changes (`_PHP_MIN_VERSION`, `_PHP_DEFAULT_VERSION`).

🌐 **Multi-distro** — tested on EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux), Ubuntu 20.04–24.04, Debian 11–13.

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

## Upgrade from V3.2.2

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

PHP auto-upgrade activates automatically on next deploy/redeploy — if installed PHP is below 8.3, it will be upgraded to 8.4 via Remi (EL) or Ondrej/Sury (Deb/Ubuntu). Existing sites with PHP ≥8.3 are unaffected. All 24 security fixes (safe rmtree/copy/mkstemp/tar, gzip validation, symlink protection) apply immediately.

## Upgrade from V3.2.1

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.2 + V3.2.3 features activate automatically. Existing timers inherit parameters from EnvironmentFile — no manual reconfiguration needed.

## Upgrade from V3.2.0

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.1 + V3.2.2 + V3.2.3 features activate automatically. Existing SSL timers inherit parameters from previous unit files.

## Upgrade from V3.1.x

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.x configs (Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers / webhook / HTTP/3 / srcache / PHP upgrade) rebuild automatically.

## Key Bug Fixes (V3.2.3)

- **clean+redeploy PHP bypass (PATCH-261d)** — `_all_critical_deps_present` now checks PHP version (≥8.3), not just binary existence; PHP 8.0 after clean→redeploy is now properly upgraded
- **`--php-version` skip-path bypass (PATCH-261e)** — `--php-version 8.5` no longer silently ignored when installed PHP 8.4 ≥ 8.3 triggers fast-skip
- **`php-redis` wrong version (PATCH-261f)** — apt path now uses versioned `php8.4-redis` instead of unversioned `php-redis` in Ondrej parallel-install environments
- **EL PHP-FPM not restarted (FIX-A6)** — same-name service upgrade (`php-fpm`→`php-fpm`) now triggers explicit restart instead of no-op `enable --now`
- **PHP repo failure silent continuation (FIX-C5)** — Remi/Ondrej setup failure now properly falls back to system default packages instead of generating non-existent versioned package names
- **`--php-version` unnecessary upgrade (FIX-A2)** — `--php-version 8.4` on already-installed PHP 8.4 no longer triggers redundant repo setup

## Security Fixes (V3.2.3, PATCH-256~260)

- **`_safe_rmtree`** — parent directory whitelist, root protection, `../` traversal detection, symlink blocking (replaces all `shutil.rmtree` calls)
- **`_safe_copy2`** — bidirectional symlink check on source AND destination (FIX-B2: attacker-planted dst symlink attack)
- **`_safe_mkstemp`** — `O_NOFOLLOW` + post-creation `fchmod` dual permission guarantee (Python 3.6 compatible)
- **`_safe_extract_tar`** — `--no-same-owner --no-same-permissions`, path traversal filtering, output whitelist, timeout, artifact verification (6 extraction sites)
- **`_verify_gzip_integrity`** — pre-extraction `gzip -t` CRC check for all `.tar.gz` / `.sql.gz` files
- **Git tag pinning** — 5 OpenResty modules pinned to release tags instead of commit hashes; immune to GitHub shallow-clone restrictions

## Requirements

- Root access, Python 3.6+
- Domain with DNS records pointing to your server
- Ports 80 and 443 open

Everything else is installed automatically. PHP < 8.3 is automatically upgraded to 8.4.

## Checksums

```
SHA256: 86121a2efb984bbfe1294e62ec583082c190b648ba8a05be451b65ae9059c9c4  wp_ssl_bootstrap.py
```

## License

MIT
