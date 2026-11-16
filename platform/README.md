# 学校托管适配器

从仓库根目录运行 `python scripts/build_platform.py`，生成标准平台 WHL。先构建核心工具，再将核心 WHL 和校验值打入此包。请勿直接在未构建核心的目录安装适配器。

入口：`campus-mail-platform`。默认 `demo`，支持由本人授权的固定学校 IMAP 端点，缓存使用每个进程独立的临时目录。运行方式及变量见根目录 README。
