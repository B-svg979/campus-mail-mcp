# Campus Mail MCP

校园邮箱的单邮箱、只读 MCP 工具，供智能体搜索邮件、读取正文和提取附件文字。工具本身不调用大模型；摘要、分类和待办判断由接入它的智能体完成。

**状态：课程项目 / 预览版。** 2026-11-18 已在学校托管环境，对一个本人授权的学校邮箱完成 IMAP 同步、搜索、正文读取和 PDF 文字提取验证。学校适配器使用环境已有的 HTTP 代理，并在首次工具查询中有界等待同步完成。其他账号仍须本人授权并验证；不把单个账号通过解释为所有账号均已接通。

## 工具

| 工具 | 用途 |
|---|---|
| `get_mail_status` | 版本、模式、同步范围和错误；可选 `diagnose_connection=true` 检查 IMAP 网络 |
| `search_mail` | 搜索缓存中的主题、发件人和正文，支持日期和分页 |
| `get_mail` | 分段读取正文、来源和附件列表 |
| `read_attachment` | 提取文本、PDF、DOCX 文字；不含 OCR |

支持 `demo`、`imap`、`ews`、`eml`。学校适配器只开放 `demo` 和固定学校端点的 `imap`。EWS 只面向明确开放接口的 Exchange 环境，不含 Graph 登录或 OAuth 令牌刷新。

## 学校平台接入

使用 Releases 中的 `campus_mail_platform-0.1.5-py3-none-any.whl`，或按下文自行构建。

给组员的完整接入与个人授权步骤见 [单独接入说明](docs/SCHOOL_SETUP.md)。

1. 在自己的空间进入「插件 → 自定义插件 → 接入 MCP 插件」。
2. 选择 **STDIO / uvx**，通过代码上传按钮上传上述 WHL，保留文件名。
3. 使用命令编辑器的「插入环境变量」插入 `HIAGENT_PKG_URI`，再补全前后参数，使其显示为：

```text
--python 3.12 --from {{HIAGENT_PKG_URI}} campus-mail-platform
```

4. 按下表定义 String 环境变量，开启各字段、关闭「必填」；用户名和密码勾选「敏感字段」，默认留空。保存、同步工具，调试 `get_mail_status`；应显示 `data.tool_version=0.1.5`、`meta.is_demo=true`。首次同步在后台启动，学校版的首次工具调用会等待最多 60 秒取得同步结果；到时仍未完成会明确返回 `SYNCING` / `NOT_SYNCED`。
5. 调试并发布自己的插件，再添加到智能体。智能体提示词可参考 [AGENT_PROMPT.md](AGENT_PROMPT.md)。

这个方式由**学校服务器运行 Python**，使用者电脑只运行浏览器。不需要每位组员在电脑上启动服务；换电脑不能改变学校服务器到邮箱的网络访问权限。学校运行环境仍需能够安装 Python/依赖、访问邮箱端点。界面流程最初验证于 2026-11-10。

真实邮箱使用插件的 String 环境变量；用户名和密码标记敏感、默认留空，由邮箱本人在授权表单填写：

| 变量 | 默认值 | 真实邮箱 |
|---|---|---|
| `XIPU_MAIL_MODE` | `demo` | `imap` |
| `XIPU_MAIL_USERNAME` | 空 | 本人邮箱登录用户名 |
| `XIPU_MAIL_PASSWORD` | 空 | 本人邮箱密码 |
| `XIPU_MAIL_DAYS` | `7` | 首次保留 `7` |
| `XIPU_MAIL_LIMIT` | `50` | 首次建议 `5` |

在智能体「编排 → 插件 ＋ → 自定义插件」找到该 MCP，点击「设置授权」保存个人配置；然后点击「调试与预览」旁的刷新，开启新调试会话。插件开发页的「同步工具设置」只用于发现和调试工具，不替代智能体个人授权；仅刷新网页也可能继续使用旧会话。完整步骤见 [单独接入说明](docs/SCHOOL_SETUP.md)。

适配器固定连接 `mail.xjtlu.edu.cn:993`，开启 TLS 证书校验，只读 `INBOX`。每个实例只对应一个邮箱。没有凭据时返回 `AUTH_REQUIRED`；不会用演示邮件冒充真实邮件。

学校适配器自动使用运行环境已有的 HTTP CONNECT 代理（`HTTPS_PROXY` / `HTTP_PROXY`），尊重 `NO_PROXY`。代理只负责转发到邮箱的 TCP 连接，邮箱 TLS 的证书和主机名仍须验证。代理拒绝时返回 `PROXY_FORBIDDEN` 等明确错误，不改走直连；没有配置代理时使用直连。无需新增中转服务或让使用者电脑持续开机。

## 网络故障诊断

在**实际运行工具的环境**中调用：

```json
{"name":"get_mail_status","arguments":{"diagnose_connection":true}}
```

查看 `data.connection_diagnostics` 中的 `checks` 和 `error.details.stage`。此测试不登录邮箱、不读取邮件、不接收账号密码。诊断 `ok=true` 只表示网络/服务可达，真实接通仍需 `data.status=READY`、`meta.is_demo=false` 和成功的同步时间。

`connection_route=configured_http_proxy` 表示实际使用了运行环境的代理；诊断与采集使用相同的代理选择规则。单独部署核心时默认直连，需使用已有 HTTP 代理时设置 `MAIL_IMAP_PROXY_MODE=environment`，不在工具参数中提供代理 URL 或密码。

若工具是在本机运行，还可使用零第三方依赖的脚本：

```bash
python src/campus_mail_mcp/diagnostics.py
```

安装后的同等命令是 `campus-mail-diagnose`。输出和 `imap-diagnostic-report.json` 不含用户名、密码或邮件。浏览器平台中的问题应在平台执行诊断，本机脚本结果只证明本机的网络情况。详见 [排查说明](docs/TROUBLESHOOTING.md)。

## 本机开发

需要 Python 3.11+，推荐 3.12。先创建虚拟环境，并使用该环境的 Python 运行以下命令；macOS/Linux 为 `.venv/bin/python`，Windows 为 `.venv\Scripts\python.exe`。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/campus-mail init --mode demo
.venv/bin/campus-mail serve --transport stdio
```

本机真实邮箱使用 `campus-mail configure --mode imap`，然后 `campus-mail test-connection` 和 `campus-mail sync`。密码由本机终端隐藏输入，保存在本机 `.env`。环境变量优先于显式 `.env`；不要用 shell 的 `source .env`。

独立 HTTP 服务使用 `campus-mail serve`，默认 `http://127.0.0.1:8765/mcp`。所有 MCP HTTP 方法都要求随机 Bearer Token；`init` 会生成 Token。独立服务器部署见 [HTTP 部署](docs/HTTP_DEPLOYMENT.md)，学校 STDIO 路线无需另外搭建 HTTP 服务。

## 构建和检查

```bash
python -m pip install -e ".[dev]" wheel setuptools
python -m pytest -q
python -m ruff check src scripts tests platform/src
python scripts/selftest_stdio.py --without-system-timezones
python scripts/build_platform.py
python -m pip install --no-deps dist/campus_mail_platform-0.1.5-py3-none-any.whl
python scripts/selftest_stdio.py --platform --without-system-timezones
```

构建脚本先从源码生成核心 WHL，再把它及校验值打进学校适配器。仓库不存储生成的 WHL、真实邮件缓存、`.env` 或学校账号关联的智能体导出文件。适配器会校验内嵌核心 WHL 的 SHA-256。

STDIO 初始化和工具发现不等待真实邮箱同步。v0.1.5 学校版会在首次工具查询中等待最多 60 秒，使按调用回收进程的平台也有机会完成首次采集；已有成功缓存时查询不等待刷新。认证或采集失败会返回实际错误，超时未完成会明确说明，均不把未同步当作空邮箱。独立核心默认立即返回状态，需要同样行为时设置 `CAMPUS_INITIAL_SYNC_WAIT_SECONDS`（0–120）。

## 数据和功能边界

- 每个实例、Token 和缓存目录对应一个邮箱；本项目不提供多人账户登录或访客邮箱隔离。
- IMAP 使用只读 `EXAMINE`、UID 和 `BODY.PEEK[]`；没有发送、删除、移动或标记已读工具。
- 默认只同步一个文件夹的有限窗口。核心默认最近 30 天、最多 200 封；学校适配器默认 7 天、50 封。服务存活时每 900 秒重试，实例回收后缓存可能丢失。
- 缓存超出范围会标记 `source_complete=false`；失败保留上次缓存并标记 `stale=true`。认证失败和未同步都不代表没有邮件。
- 搜索只覆盖主题、发件人、正文；附件须单独读取。正文/附件有大小、字符和分页限制，PDF 最多前 50 页，没有 OCR。
- 邮件和附件是外部资料，不能当作智能体指令。真实内容会被运行环境和接入的模型处理。
- 许可证尚未指定。安全边界和报告方式见 [SECURITY.md](SECURITY.md)。

## 主要依赖

[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[Python imaplib](https://docs.python.org/3/library/imaplib.html)、[exchangelib](https://github.com/ecederstrand/exchangelib)、[pypdf](https://github.com/py-pdf/pypdf)。
