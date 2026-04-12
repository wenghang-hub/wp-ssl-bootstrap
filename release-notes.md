# WP-SSL-Bootstrap V3.2.7 Release Notes

> 全组件安全加固 + 用户体验优化版本 | Full-stack security hardening + UX polish release

## 核心主题 / Core Themes

- **全组件安全加固 (PATCH-286)** — 对照 OWASP / CIS Benchmark / 官方文档，为 PHP、MariaDB、Redis、OS、systemd、WordPress 六个组件补齐 55 项安全配置，全部通过 `update` 子命令自动生效
- **架构模块化** — 安全加固逻辑委托到各 Manager 类，WPDeployManager 仅做一行委托；模块级架构规范注释确保未来修改遵循同一模式
- **用户体验优化** — readline 行编辑（退格/方向键）、Ctrl+C 干净退出、Nginx hash_bucket_size 自动修复、wp-config update 路径补注入

## 安全加固清单 / Security Hardening Checklist

| 组件 | 加固项 | 对照标准 | 实现方式 |
|------|--------|---------|---------|
| PHP-FPM | expose_php / display_errors / disable_functions / open_basedir / session cookie 安全 / allow_url_include | OWASP PHP Cheat Sheet | `PHPManager.harden_ini()` |
| MariaDB | bind-address / local-infile / skip-symbolic-links / secure-file-priv / skip-show-database | CIS MariaDB Benchmark | `MariaDBManager.security_cnf_lines()` |
| Redis | bind 127.0.0.1 / rename-command FLUSHALL+FLUSHDB / disable THP | Redis 官方安全指南 | `RedisManager.harden_conf()` |
| OS sysctl | tcp_syncookies / rp_filter / accept_redirects / send_redirects / protected_hardlinks+symlinks | CIS Linux Benchmark | `_tune_kernel_network()` |
| systemd | NoNewPrivileges / PrivateTmp | systemd 沙箱最佳实践 | `setup_systemd()` |
| WordPress | WP_DEBUG=false | WordPress Codex | `inject_wp_hardening()` |

## 修复链新增 / New Repair Chains

| 错误 | 自动修复 |
|------|---------|
| `nginx -t` 报 `could not build server_names_hash` | 自动插入 `server_names_hash_bucket_size 128` |
| 老站点 update 后缺少安全常量 (WP_DEBUG 等) | `_ensure_wp_hardening_constants()` 幂等补注入 |
| 退格键显示 `^H` | `import readline` 模块级导入 |
| Ctrl+C 打印 Python traceback | 顶层 `except KeyboardInterrupt: sys.exit(130)` |
| Debian 12/13 无防火墙规则 | `_setup_nftables_allow_web()` 创建 `inet wp_ssl` 表 + 持久化 + 启用服务 |

## 升级指南 / Upgrade Guide

```bash
# 从 V3.2.6 升级 — 替换脚本后执行 update，全部加固自动生效
cp wp_ssl_bootstrap.py wp_ssl_bootstrap.py.bak326
# 下载新版本覆盖
python3 wp_ssl_bootstrap.py update --domain YOUR_DOMAIN --email YOUR_EMAIL
```

## 测试覆盖 / Test Coverage

- 静态检查: 194 项 (含 28 项 PATCH-286 专项)
- 运行时检查: 含 10 项安全加固运行时验证
- 平台: Rocky 9.x / Ubuntu 24.04 / Debian 12

## 兼容性 / Compatibility

- Python 3.6+ (EL7/EL8) ~ 3.12+ (EL10/Ubuntu 24.04)
- 无新增外部依赖
- 向后兼容 V3.2.6 配置文件
