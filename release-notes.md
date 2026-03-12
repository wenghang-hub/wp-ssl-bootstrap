# V3.2.0 — Feature Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## What's New in V3.2.0

🧙 **Interactive wizard** — run without arguments and a guided menu walks you through domain, email, SSL, and cache options.

🔄 **Two-phase deployment** — `deploy --skip-ssl` builds a full HTTP site first; `enable-ssl` adds the certificate whenever DNS is ready. Or do it all in one shot — your choice.

🛡️ **ZeroSSL backup CA** — Let's Encrypt → ZeroSSL automatic failover with EAB auto-negotiation. Certbot error classifier distinguishes fatal / retryable / non-CA-side errors; non-CA-side errors break out of the CA loop immediately.

🌐 **Smart domain handling** — `www.example.com` input auto-normalized to `example.com`; subdomains (e.g. `blog.example.com`) skip the `www` variant to avoid DNS validation failure.

🌏 **Expanded China cloud detection** — CTYun, JD Cloud, Volcengine, UCloud, Baidu Cloud, Kingsoft Cloud; auto-switches to domestic mirrors.

🐧 **dnf5 compatibility** — EL10+ (RHEL 10 / Fedora 41+) auto-detected and supported.

🔒 **Security hardening** — CSP upgraded from Report-Only to enforcement; admin-ajax.php rate limiting; wp-includes PHP execution blocked; HTTP method filtering; Fail2Ban progressive banning (24h + escalation); atomic Nginx config writes with `fsync`.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate — all from a single `deploy` command.

🔒 **Production-grade security** — zero CLI password leakage, atomic config writes, wp-config hardening, Nginx defense-in-depth, certbot error circuit-breaker with multi-CA failover.

🌐 **Multi-distro** — tested on EL7–10 (RHEL / CentOS / AlmaLinux / Rocky / Alibaba Cloud Linux), Ubuntu 20.04–24.04, Debian 11–12.

⚡ **Performance options** — FastCGI page cache, Redis object cache (with source-compile fallback), Brotli compression (all optional, composable).

📦 **Ops toolkit** — `backup`, `restore`, `update`, `enable-ssl`, `status`, `self-update`, `uninstall` subcommands for day-2 operations.

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
```

See [README.md](./README.md) for full documentation, examples, and all available options.

## Upgrade from V3.1.x

```bash
# Replace script file, then:
sudo python3 wp_ssl_bootstrap.py update --domain example.com
```

All new configs (Brotli / Cloudflare / Fail2Ban / logrotate / systemd timers) rebuild automatically.

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
