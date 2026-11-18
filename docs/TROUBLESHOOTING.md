# 连接故障排查

## 先确定程序在哪里运行

学校平台上传 WHL，选择 STDIO / uvx：Python 在学校服务器。组员的 Mac 或 Windows 只打开网页。本机安装 Python 并启动 `campus-mail`：Python 在那台电脑。独立 HTTP：Python 在服务地址所对应的服务器。

因此“网页能打开 OWA”不能证明 MCP 服务能连接 IMAP 993；两者可能来自不同机器、使用不同端口。

## 取得原始诊断

v0.1.5 保留四个原有工具；同步工具后，在插件调试页调用 `get_mail_status`，设置布尔参数 `diagnose_connection=true`。也可让智能体执行该调用并展示 `data.connection_diagnostics` 原始结果。

检查的是配置的 IMAP 端点，不登录、不使用邮箱凭据、不读取正文。不要用自然语言转述替代原始工具结果。

| 结果 | 表示什么 | 下一步 |
|---|---|---|
| `DNS_ERROR` / `DNS_LOOKUP` | 运行环境不能解析域名 | 检查该环境的 DNS；平台环境由平台管理员处理 |
| `CONNECTION_TIMEOUT` / `TCP_CONNECT` | 993 连接没有及时建立 | 核对运行环境的出站规则、邮箱访问范围和端口开放情况 |
| `CONNECTION_REFUSED` | 目标或中间设备拒绝连接 | 核对端点和服务端策略 |
| `PROXY_FORBIDDEN` / `PROXY_CONNECT` | 环境代理拒绝 CONNECT 到邮箱端点 | 交由平台管理员检查该目标和端口的代理权限；不关闭代理或换端口绕过 |
| `PROXY_AUTH_REQUIRED` | 环境代理要求认证 | 平台管理员核对代理配置；不在智能体聊天中提交代理凭据 |
| `PROXY_CONFIG_ERROR` | 已配置代理的格式或类型不受支持 | 当前支持 HTTP CONNECT 代理；检查环境代理，不会自动降级直连 |
| `PERMISSION_DENIED` | 运行环境拒绝套接字操作 | 检查容器/平台网络出站权限；不要关闭 TLS 校验 |
| `TLS_ERROR` / `TLS_HANDSHAKE` | TCP 成功，但 TLS 握手或证书校验失败 | 检查 CA、系统时间、证书链和 TLS 支持 |
| `IMAP_PROTOCOL_ERROR` | TCP/TLS 成功但没有 IMAP 就绪响应 | 核对端口与协议、服务端状态 |
| 诊断 `ok=true`，同步 `AUTH_REQUIRED` | 网络可达，账号认证/访问未通过 | 本人核对授权字段和学校 IMAP 权限；不在聊天中提交密码 |
| 诊断 `ok=true`，同步仍失败 | 单次网络测试通过，故障可能发生在登录或同步阶段 | 查看 `meta.latest_error` 的类型、编号和发生时间；检查是否间歇失败 |

`details.errno` / `winerror` 是系统编号；报告不会回显底层异常文本，避免其中意外包含凭据。v0.1.1 把多种网络异常都显示为 `CONNECTION_FAILED`，仅凭该截图不能确定具体根因。

2026-11-18 的学校环境实测表明，容器内直接 TCP 被拒绝，但平台配置的 HTTP 代理允许 CONNECT 到学校 IMAP。v0.1.4 学校适配器使用 `MAIL_IMAP_PROXY_MODE=environment`，诊断应显示 `connection_route=configured_http_proxy`。旧版本忽略代理的直连失败不代表邮箱服务或账号不可用。代理路径中仍保持邮箱端到端 TLS 校验，不需要第三方隧道。

## 插件调试是真实邮箱，智能体却仍是 demo

两处授权和运行会话需要分别检查。智能体中打开「编排 → 插件 ＋ → 自定义插件 → 对应 MCP → 设置授权」，由本人填写 `XIPU_MAIL_MODE=imap` 及个人凭据。插件开发页的「同步工具设置」不会自动替代此授权。

保存后，点击「调试与预览」标题旁的刷新，新建调试会话；仅刷新浏览器页面仍可能复用旧演示实例。再次实际调用 `get_mail_status`，核对 `mode=imap`、`is_demo=false`、`status=READY` 和成功时间，再验收搜索与正文读取。不要通过把密码放进插件公共默认值、提示词或工具参数来处理。

## 本机运行时

用运行 MCP 的同一个 Python 执行 `src/campus_mail_mcp/diagnostics.py`。切换到另一个 Python 可能改变 CA 和网络设置。脚本会生成不含密码和邮件的 JSON 报告。

需要检查该环境已配置的 HTTP 代理时使用 `python src/campus_mail_mcp/diagnostics.py --proxy-mode environment`。默认仍为直连；`NO_PROXY` 中匹配的目标按环境配置直连。代理主机名、URL、认证头与密码不会返回给智能体。

## 学校平台进程启动失败

若“同步工具”阶段就出现 `initialize: EOF`、退出码或容器日志，诊断函数尚未运行，应先查看平台日志。不要把容器启动失败当作 IMAP 密码错误。只有成功发现工具并实际调用之后，才能取得邮箱网络诊断。

连续重复“再试一次”也可能只读到上次同步失败的缓存状态；旧版同步周期为 900 秒。查看 `last_attempt_at`，不要把同一时间戳当作新的连接测试。

如果多次请求的 `last_attempt_at` 每次变化，却始终没有成功缓存，可能是平台按调用启动或回收进程，后台同步还没完成请求就结束了。v0.1.5 学校版在首次工具调用中等待最多 60 秒，让查询取得采集结果后返回；MCP 握手仍立即完成。已有成功缓存不等待刷新，认证失败会明确返回错误。
