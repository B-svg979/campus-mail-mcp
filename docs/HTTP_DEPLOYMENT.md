# 独立 HTTP 部署

学校平台使用 STDIO / uvx 时无需本页。仅在自己有可被客户端访问的服务器、且服务器能连接邮箱时使用。

先按 README 安装，执行 `campus-mail init --mode demo`。默认监听 `127.0.0.1:8765`，地址为 `/mcp`；从本机生成的 `.env` 读取随机 `CAMPUS_TOKEN`，HTTP 客户端配置 `Authorization: Bearer <Token>`。不要把这个 Token 放进代码、公开 URL 或 Git。

对外使用 HTTPS 反向代理，示例在 `deploy/Caddyfile.example`。在 `.env` 中把真实域名加入 `CAMPUS_ALLOWED_HOSTS`，例如：

```dotenv
CAMPUS_ALLOWED_HOSTS=localhost:*,127.0.0.1:*,mail-tools.example.edu
```

普通服务器调用不需要 Origin。若是浏览器跨域客户端，才把实际 Origin 加入 `CAMPUS_ALLOWED_ORIGINS`。不要设置全通配 Host。

仓库提供 Dockerfile 和 Compose 示例：

```bash
docker compose up -d --build
```

Compose 绑定服务器回环地址，命名卷保存单邮箱缓存。每个邮箱使用独立项目、卷和 Token，例如 `docker compose -p campus-demo …` 与 `docker compose -p campus-live …`。容器默认非 root，根文件系统只读。`/healthz` 不需要 Token，但不返回邮箱内容。

HTTP 和 STDIO 都只提供四个读取工具；每个服务实例只对应一个邮箱。不要把私人邮箱实例的 Token 配给所有访客共用。

此示例不含域名申请、证书账户配置、托管平台部署或多用户认证系统；发布源码不代表已经部署 HTTP 服务。
