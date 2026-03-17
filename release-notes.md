# V3.2.1 — Stability & Security Hardening Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.1

V3.2.1 refines V3.2.0 through 160+ internal iterations, 4 independent security audit rounds, and extensive real-world testing across EL7–10, Ubuntu, and Debian.

🔒 **4 security audit rounds** — 50+ findings fixed: SSRF protection for webhooks, `O_NOFOLLOW` on all write paths, admin password via env var (not `/proc/cmdline`), SQL control character interception, cross-source SHA-256 verification for self-update, tar path traversal detection on restore.

🗄️ **Atomic database restore** — `restore` now imports to a temp database, then swaps tables via a single `RENAME TABLE` statement. Interruption leaves the live database completely intact.

🔐 **ECDSA certificates** — prefers ECDSA P-256 key type (faster TLS handshake); auto-falls back to RSA per-CA if unsupported.

📡 **Renewal failure webhook** — `--notify-webhook URL` sends a JSON POST to Slack / Lark / WeCom when SSL renewal fails. HTTPS enforced; private IPs and internal domains blocked.

🧹 **Full site purge** — `uninstall --purge` drops the database, removes webroot, and deletes certificates (interactive confirmation required). `--revoke` revokes the certificate with Let's Encrypt.

🐧 **EL10 / dnf5 full compatibility** — Redis/Valkey multi-package candidate auto-selection; `php-json` only added for PHP < 8; dnf5 detection elevated to instance attribute.

🔄 **Plugin safe-upgrade** — `update` subcommand upgrades nginx-helper and redis-cache plugins with post-upgrade health checks; auto-rolls back to previous version on failure.

📋 **Pre-operation backup** — `enable-ssl`, `update`, and `restore` automatically create a lightweight backup (DB + Nginx config) before making changes. Skip with `--no-pre-backup`.

🎯 **Smart domain inference** — non-deploy subcommands auto-select the domain when only one site is deployed; `status` without any deployed sites shows a lightweight system health overview.

🔀 **`--no-staging` override** — explicitly switch from staging to production CA without editing systemd unit files.

📊 **Cert SAN alignment** — Nginx `server_name` and WordPress `siteurl`/`home` auto-aligned with certificate SAN, preventing HTTPS redirect loops when cert lacks `www`.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate, OS auto-security-updates — all from a single `deploy` command.

🔒 **Production-grade security** — zero CLI password leakage, atomic config writes with symlink protection, wp-config hardening, Nginx defense-in-depth, certbot error circuit-breaker with multi-CA failover, supply-chain protection via dual-source cross-verification.

🌐 **Multi-distro** — tested on EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux), Ubuntu 20.04–24.04, Debian 11–12.

⚡ **Performance options** — FastCGI page cache, Redis object cache (with source-compile fallback + Valkey support), Brotli compression, ECDSA certificates (all optional, composable).

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

# Two-phase: HTTP first, SSL later
sudo python3 wp_ssl_bootstrap.py deploy --domain example.com --skip-ssl
sudo python3 wp_ssl_bootstrap.py enable-ssl --domain example.com --email admin@example.com

# With webhook notification on renewal failure
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com \
  --notify-webhook https://hooks.slack.com/services/xxx
```

See [deploy-guide.md](./deploy-guide.md) for scenario-based examples and [README.md](./README.md) for full documentation.

## Upgrade from V3.2.0

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

New features (webhook notification, pre-operation backup, plugin safe-upgrade, cert SAN alignment, OS auto-security-updates) activate automatically. Existing SSL timers inherit parameters from previous unit files — no manual reconfiguration needed.

## Upgrade from V3.1.x

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All V3.2.0 + V3.2.1 configs (Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers / webhook) rebuild automatically.

## Key Bug Fixes

- **Atomic DB restore** — `restore` no longer leaves the database in a half-imported state on interruption
- **Cert SAN / Nginx mismatch** — HTTPS config auto-aligns `server_name` with certificate SAN, fixing redirect loops when cert lacks `www`
- **WordPress URL / cert mismatch** — `siteurl`/`home` now set using cert-aware canonical domain after `enable-ssl`
- **Credentials file password loss** — credential rewrite no longer blanks `db_pass`/`db_root_pass`
- **MariaDB version detection** — no longer selects `caching_sha2_password` for MariaDB (which doesn't support it)
- **Timer activation race** — `DISABLE_WP_CRON` no longer reverted to `false` due to systemd activation delay
- **IPv6 bracket handling** — `openssl s_client` and MySQL connections correctly bracket IPv6 addresses

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
