# 单独接入学校邮件 MCP（v0.1.4）

使用文件：`campus_mail_platform-0.1.4-py3-none-any.whl`。这是独立 MCP 工具包，已经内嵌核心代码；不需要再上传核心 WHL 或智能体 ZIP。Python 由学校服务器运行，使用者电脑只需浏览器。

## 创建自己的插件

1. 登录学校 AI 平台，在自己的空间打开「插件 → 自定义插件 → 接入 MCP 插件」。
2. 选择 **STDIO / uvx**，使用代码上传按钮上传上述 WHL。
3. 添加以下环境变量。类型均为 **String**，「开启」打开，「必填」关闭：

| 变量名 | 敏感字段 | 默认值 |
|---|---|---|
| XIPU_MAIL_MODE | 否 | demo |
| XIPU_MAIL_USERNAME | 是 | 留空 |
| XIPU_MAIL_PASSWORD | 是 | 留空 |
| XIPU_MAIL_DAYS | 否 | 7 |
| XIPU_MAIL_LIMIT | 否 | 50 |

4. 点击命令编辑器的「插入环境变量」，插入 **HIAGENT_PKG_URI**。在其前后填写参数，使完整命令为：

```text
--python 3.12 --from {{HIAGENT_PKG_URI}} campus-mail-platform
```

5. 保存并同步工具。应发现 `get_mail_status`、`search_mail`、`get_mail`、`read_attachment` 四个只读工具。调试各工具后发布插件，将它添加到自己的智能体。

## 授权自己的真实邮箱

1. 插件页「同步工具」旁的齿轮打开个人「同步工具设置」。
2. 把 `XIPU_MAIL_MODE` 改成 **imap**，在表单中填写自己的学校邮箱登录用户名和密码。密码不填到智能体聊天，不放入默认值、提示词、源码或发给组员的包。
3. 首次测试建议 `XIPU_MAIL_DAYS=7`、`XIPU_MAIL_LIMIT=5`，点击「开始同步」。若同步覆盖范围被截断，工具会明确返回限制。
4. 调用 `get_mail_status(diagnose_connection=true)`。核对版本 **0.1.4**，以及 `mode=imap`、`is_demo=false`、`status=READY`、成功的同步时间。再搜索邮件并读取一封正文，才能确认真实邮件已读通。

仅 `demo / READY` 或网络诊断 `ok=true` 均不代表真实邮箱已经接通。登录失败看 `latest_error`；首次同步中的 `SYNCING` 是暂态。更改个人授权后，已经运行的实例可能需要重新同步或重启。

## 连接与分享

学校版使用运行环境已有的 HTTP CONNECT 代理，尊重 `NO_PROXY`，邮箱 TLS 的证书和主机名校验保持开启。v0.1.4 修复了旧版绕过环境代理、直接 TCP 连接被拒绝的问题。不需要 Cloudflare、个人电脑中转或单独公网服务器。

每个服务实例只对应一个邮箱。组员应在各自空间接入工具并分别授权，个人凭据不随 WHL、ZIP 或 GitHub 发布。公开链接供多人使用时，须先确认学校平台提供独立的用户授权和实例隔离；本工具不实现多用户登录，个人真实邮箱实例不可作为全员共用邮箱服务。

工具只读 `INBOX`，不会发送、删除、移动邮件或标为已读；默认最近 7 天、最多 50 封。附件支持文本、PDF、DOCX 的文字提取，不含 OCR。代理 URL、认证头和邮箱密码不会返回给智能体。
