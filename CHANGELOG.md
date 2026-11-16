# 更新记录

## 0.1.2 — 2026-11-16

- `get_mail_status` 增加可选 `diagnose_connection`，在实际运行环境检查 IMAP DNS、TCP、TLS 和协议响应，不使用邮箱凭据。
- 区分 DNS、超时、连接拒绝、权限和 TLS 故障；返回安全的异常类型和系统编号，不回显底层异常文本。
- IMAP 会话中断不再直接误报为密码错误。
- 扩大 Git/Docker 忽略规则，覆盖实际生成的 `data-*` 邮件缓存。
- 补充学校 STDIO / uvx、独立 HTTP、网络排查和源码构建说明；增加自动化验证。
- 真实学校托管环境的 IMAP 同步仍待验收，保持预览状态。

## 0.1.1

- 标准 Python WHL 学校适配器、显式时区依赖和独立临时缓存。
- STDIO 标准输出保留给 JSON-RPC。

## 0.1.0

- 四个只读邮件工具；demo、IMAP、EWS、EML 和认证 HTTP MCP。
