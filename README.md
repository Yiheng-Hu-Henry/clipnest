# clipnest

Windows 剪贴板历史管理器。**零第三方依赖** —— 只用 Python 标准库（`ctypes` + `sqlite3` + `http.server`）。

复制过的文字自动进库，随时搜回来；密钥、密码、身份证号这类内容在入库前就被拦掉，不会落盘。

```
   ID  KIND   HITS    AGE  PREVIEW
    3  text      0     1s  今天下午三点评审
    2  code      0     3s  def hello(): print("hi")
    1  url       0     5s  https://github.com/Yiheng-Hu-Henry
```

## 为什么

Windows 自带的 `Win+V` 只保留二十几条、不支持搜索、也没法导出。市面上的工具大多要装一堆依赖或者常驻后台吃内存。这个项目的目标很简单：**一个文件、一个 SQLite 库、一个能搜的界面**。

## 安装

需要 Python 3.9+（Windows）。

```bash
git clone https://github.com/Yiheng-Hu-Henry/clipnest.git
cd clipnest
pip install -e .
```

不装也能直接跑：`python -m clipnest --help`。

## 用法

```bash
# 开始采集（前台，Ctrl+C 退出）
clipnest watch

# 打开本地界面（默认 http://127.0.0.1:8765）
clipnest serve

# 看看攒了什么
clipnest list -n 20
clipnest list -s 关键字 --kind url
clipnest stats

# 管理
clipnest pin 12              # 置顶，清理时豁免
clipnest rm 12
clipnest purge --days 30 --max 500
clipnest clear               # 清空，置顶保留

# 备份
clipnest export backup.json
```

采集进程和界面是分开的两个命令，所以你可以让 `watch` 挂在后台、需要时再开 `serve` 翻历史。

## 界面

`clipnest serve` 起一个只监听回环地址的 HTTP 服务，浏览器里搜索、预览、置顶、复制、删除。快捷键：

| 键 | 作用 |
|---|---|
| `/` | 聚焦搜索框 |
| `↑` `↓` | 切换条目 |
| `Enter` | 复制选中条目到剪贴板 |
| `Delete` | 删除选中条目 |
| `Esc` | 清空搜索 |

## 设计说明

**去重靠内容哈希。** 每条记录的键是内容的 SHA-256。同一段文字反复复制不会产生新行，而是累加 `hits` 并刷新 `last_used_at` —— 常用片段自然往浮到顶部，不需要额外的收藏机制。

**监听必须记住上次内容。** 轮询式采集最容易踩的坑是：每 0.6 秒读到同一份内容，就把它当新记录写一遍。`ClipboardWatcher` 保存上一次的内容指纹，只有真正变化时才入库；`prime()` 还会在启动时把当前剪贴板标记为「已见过」，避免开机就把旧内容收进来。

**敏感内容在入库前拦截。** `filter.py` 里是一组保守的正则：PEM 私钥、AWS / GitHub / Slack / OpenAI 令牌、JWT、带密码的连接串、`password = ...` 这类赋值、18 位身份证号、16~19 位连续数字。命中即跳过 —— 宁可多跳过一条普通文本，也不要把一条密钥写进磁盘。代价是订单号之类会被误判，用 `--allow-sensitive` 可以关掉这层过滤。

**ctypes 调 Win32 必须声明 `restype`。** 不写 `restype` 时句柄返回值会被当成 32 位整数，64 位进程下指针被截断，表现为读到空字符串或直接访问违例。`reader.py` 里每个 API 都显式声明了参数类型与返回类型。

**SQLite 连接跨线程要加锁。** 监听线程和 Web 请求线程共享同一个 `Store`，所以连接用 `check_same_thread=False` 打开，并用一把 `RLock` 串行化所有访问 —— 比给每个线程各开一个连接简单，也避开了 WAL 模式下的写冲突。

## 测试

```bash
python -m unittest discover -s tests -t .
```

66 个用例，覆盖存储层去重与清理、敏感规则、内容分类、监听去重逻辑、Web API 全路由。剪贴板写入用 mock 替身，跑测试不会动你真实的剪贴板。

## 限制

- 目前只处理**文本**。图片、文件列表尚未支持。
- 仅 Windows（`reader.py` 依赖 user32）。存储层和过滤层是平台无关的，其它系统上只缺采集。
- 没有开机自启，需要的话丢一个快捷方式到 `shell:startup` 里，目标写 `clipnest watch`。

## 许可

MIT
