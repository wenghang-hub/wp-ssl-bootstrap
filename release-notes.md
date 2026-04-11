# V3.2.6 — Architecture Refactoring, Security Audit & OpenSSL Resilience Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.6

V3.2.6 builds on V3.2.5 through 5 patches (PATCH-281–285), delivering a major architecture refactoring, deep security audit, and OpenSSL/Python SSL resilience hardening. The Platform Abstraction Layer centralizes 126 hardcoded platform branches; atomic file writes replace all 24 direct-write call sites; signal handling is rebuilt around safe polling points; a three-layer defense protects against OpenSSL library version mismatches. New features include zero-config ntfy.sh webhook, dual-CA failover (ZeroSSL + Let's Encrypt), certificate CA migration, standalone `fix-openssl` subcommand, and self-update SHA256 pre-check. Net +2,300 lines (40,133→42,421).

🏗️ **Platform Abstraction Layer (PATCH-281)** — consolidated 126 hardcoded `if pkg_mgr == "apt"` / `in ("dnf","yum")` branches into `_PLATFORM_REGISTRY`. Business logic accesses platform-specific values via `self.platform["key"]`; upstream changes require editing one line. Method delegation proxies Nginx/MariaDB/PHP/Redis/Cert methods to their managers.

🔒 **Atomic file writes (PATCH-284)** — `_write_bytes_atomic`: tempfile → `os.fsync()` → `os.replace()` following Python official POSIX best practices. 24 call sites migrated.

🔒 **Signal-safe shutdown (PATCH-285)** — `_shutdown_requested` flag + 21 polling points via `_abort_if_shutdown()`. `_CriticalSectionCtx` protects critical sections. Ensures rollback execution on Ctrl+C.

🔒 **OpenSSL three-layer defense (PATCH-285)** — L0: `ssl.OPENSSL_VERSION` vs `openssl version` comparison (PEP 644), auto `python3-libs` upgrade. L1: `_try_repair_openssl()` with subprocess verification. L2: curl/wget fallback. Standalone `fix-openssl` subcommand for manual diagnosis.

🔔 **ntfy.sh zero-config webhook (PATCH-284)** — interactive wizard auto-generates ntfy.sh topic; plaintext POST with `X-Title`/`X-Priority` headers; Slack/DingTalk/Feishu keep JSON format.

🔀 **Dual-CA failover (PATCH-282)** — ZeroSSL (primary) + Let's Encrypt (fallback) with EAB auto-negotiation, ECC→RSA downgrade, rate-limit detection. `migrate-ssl` subcommand for CA migration.

⚡ **Self-update SHA256 pre-check (PATCH-285)** — downloads remote SHA256 (~64 bytes) first; skips full 1.5MB download if hash matches.

🔒 **Credential hardening (PATCH-283/284)** — `_safe_chmod` eliminates TOCTOU (16 sites); `LC_MESSAGES=C`; `/proc/environ` zeroing; `_md5_noncrypto` with `usedforsecurity=False`.

🌐 **China network detection fix (PATCH-285)** — `_is_china_network()` replaces `_is_china_cloud()` for staging detection; Tencent Cloud overseas nodes no longer falsely blocked.

🐛 **Challenge file cleanup (PATCH-284)** — `_clean_challenge_dir()` at 3 points prevents `FileExistsError` during CA switch / ECC→RSA downgrade.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL, auto-renewal, Fail2Ban, logrotate — single `deploy` command.

🏗️ **Clean architecture** — 126 platform branches centralized; 24 atomic write paths; signal-safe shutdown with 21 polling points.

🔀 **Dual-CA failover** — ZeroSSL + Let's Encrypt with auto-switch, EAB auto-negotiation, `migrate-ssl` for CA migration.

🤖 **Self-healing** — 14 failure auto-remediation patterns + OpenSSL three-layer defense.

⏱️ **Future-proof** — dynamic timer for LE short-lived certs (47-day/6-day); component lifecycle management.

📦 **Ops toolkit** — `deploy`, `enable-ssl`, `renew`, `status`, `backup`, `restore`, `update`, `migrate-ssl`, `fix-openssl`, `self-update`, `uninstall`.

🌐 **Multi-distro** — EL7–10, Ubuntu 20.04–24.04, Debian 11–13. Python 3.6+ compatible.

## Quick Start

```bash
sudo python3 wp_ssl_bootstrap.py                    # Interactive wizard
sudo python3 wp_ssl_bootstrap.py fix-openssl         # Fix SSL issues
sudo python3 wp_ssl_bootstrap.py migrate-ssl \       # Migrate CA
  --domain example.com --email admin@example.com
```

See [deploy-guide.md](./deploy-guide.md) for scenarios and [README.md](./README.md) for full docs.

## Upgrade from V3.2.5

```bash
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All features activate immediately. No manual reconfiguration needed.

## New Subcommands

| Command | Description |
|---|---|
| `fix-openssl` | 4-step OpenSSL/Python SSL diagnosis and repair (no `--domain` needed) |
| `migrate-ssl` | Migrate certificate between CAs (LE ↔ ZeroSSL) |

## OpenSSL Three-Layer Defense

| Layer | When | Action |
|---|---|---|
| L0 Prevention | After `install_packages()` | Version comparison → auto `python3-libs` upgrade |
| L1 Self-Heal | urllib failure | Iterate all repair strategies with subprocess verification |
| L2 Fallback | L1 exhausted | curl/wget takeover |

## Requirements

Root access, Python 3.6+, domain with DNS A records, ports 80/443 open. Everything else is auto-installed.

## License

MIT
