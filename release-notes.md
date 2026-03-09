# V3.0.14 — Initial Public Release

One-command WordPress + HTTPS deployment engine for production Linux servers.

## Highlights

🚀 **Full-stack deployment** — Nginx, PHP-FPM, MariaDB, WordPress, SSL certificate, systemd auto-renewal, Fail2Ban, logrotate — all from a single `deploy` command.

🔒 **Production-grade security** — zero CLI password leakage, atomic config writes, wp-config hardening, Nginx defense-in-depth, certbot error circuit-breaker.

🌐 **Multi-distro** — tested on Alibaba Cloud Linux 3, CentOS 7–9, RHEL 8/9, Ubuntu 20.04–24.04, Debian 11–12.

⚡ **Performance options** — FastCGI page cache, Redis object cache, Brotli compression (all optional, composable).

📦 **Ops toolkit** — `backup`, `restore`, `update`, `status`, `uninstall` subcommands for day-2 operations.

🌍 **Bilingual** — full Chinese/English interface, auto-detected from system locale.

## Quick Start

```bash
sudo python3 wp_ssl_bootstrap.py deploy \
  --domain example.com \
  --email admin@example.com
```

See [README.md](./README.md) for full documentation, examples, and all available options.

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
