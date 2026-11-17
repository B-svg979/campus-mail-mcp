# 学校托管适配器

从仓库根目录运行 `python scripts/build_platform.py`，在全新的临时目录构建核心和适配器，输出标准平台 WHL 到 `dist`。每次只内嵌当前版本的一个核心 WHL，并验证校验值。安装生成的 WHL；不要直接从这个源码目录安装适配器。

入口：`campus-mail-platform`。默认 `demo`，支持由本人授权的固定学校 IMAP 端点，缓存使用每个进程独立的临时目录。运行方式及变量见根目录 README。
