# 学校托管适配器

从仓库根目录运行 `python scripts/build_platform.py`，在全新的临时目录构建核心和适配器，输出标准平台 WHL 到 `dist`。每次只内嵌当前版本的一个核心 WHL，并验证校验值。安装生成的 WHL；不要直接从这个源码目录安装适配器。

入口：`campus-mail-platform`。默认 `demo`，支持由本人授权的固定学校 IMAP 端点，缓存使用每个进程独立的临时目录。运行方式及变量见根目录 README。

自动启用 `MAIL_IMAP_PROXY_MODE=environment`，使用学校运行环境已有的 HTTP CONNECT 代理并尊重 `NO_PROXY`。没有环境代理时直连，代理拒绝时不会回退直连；邮箱 TLS 证书校验始终开启。代理 URL 和凭据不作为 MCP 参数，也不返回给智能体。

`CAMPUS_INITIAL_SYNC_WAIT_SECONDS=60` 让首次工具调用等待有界的同步结果，初始化与工具发现仍不阻塞；用于服务进程可能在单次调用后回收的平台。有成功缓存时不等待刷新。
