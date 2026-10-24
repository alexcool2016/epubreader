# EPUB Reader（Python + PyQt6）

一个面向 Windows 的 EPUB 阅读器桌面程序，使用 **PyQt6 + QtWebEngine** 渲染书籍页面，支持**全书搜索**、**目录导航**与多种阅读设置。

EPUB 解析层完全基于 Python 标准库实现（`zipfile` / `xml.etree` / `html.parser`），不依赖 ebooklib、BeautifulSoup 等第三方解析库。

---

## 功能

### 阅读

- 打开 `.epub`（支持文件对话框、命令行参数、拖拽入窗口、最近打开列表）
- 按 spine 顺序渲染正文，保留原书内联样式、图片与超链接
- 自动注入排版样式：字号、行距、版心宽度、两端对齐均可调
- 4 套主题：明亮 / 羊皮纸 / 夜间 / 护眼（配色同时作用于阅读区与滚动条）
- 内链跳转（含 `#fragment` 锚点）、外链在状态栏提示后忽略
- 翻页滚动、上一章 / 下一章、本书开头 / 结尾
- 自动记忆每本书的阅读位置（章节 + 段内比例），下次打开自动恢复
- 记住窗口几何、侧边栏状态、主题与排版设置

### 全文搜索

- 在整本书内搜索，结果按章节分组显示
- 选项：区分大小写、匹配整词
- 结果列表显示章节名、正文进度百分比与上下文摘要，**关键词高亮**
- 摘要按标点智能截断（`。！？；，、：!?;,:.\n`），不会从词中间切断
- 点击结果直接跳转到对应段落并闪烁定位，页内所有匹配项同时高亮
- `F3` / `Shift+F3` 在匹配项之间循环，`Esc` 清除高亮
- 搜索在后台线程执行，带进度条且可取消，界面不卡顿

### 中文友好

- 整词匹配对中日韩文字做特殊处理：CJK 字符本身属于 `\w`，因此不对其施加 `\b` 边界，改用 ASCII 前后视断言（`(?<![0-9A-Za-z_])` / `(?![0-9A-Za-z_])`），避免中文整词搜索永远匹配不到
- 摘要宽度按字符宽度逐字累计，中文混排不会错位
- 文本规范化在解析阶段完成，搜索偏移量可直接映射回 DOM 块元素（`id="erbN"`），实现精确定位

### 目录导航

- 同时支持 EPUB3（`nav.xhtml`，`epub:type="toc"`）与 EPUB2（`toc.ncx`）
- 多级目录以树形展示，自动展开前两层
- 目录带过滤输入框，输入即筛选
- 当前章节在目录中自动高亮并滚动到可见位置
- 工具栏章节下拉框可快速跳转，悬停显示章节标题

---

## 安装与运行

```bat
pip install -r requirements.txt
python main.py
```

打开指定文件：

```bat
python main.py "D:\books\某本书.epub"
```

也可以使用 `python -m epubreader` 启动。

### 依赖

| 包 | 版本 |
| --- | --- |
| Python | 3.10+（开发环境为 3.14） |
| PyQt6 | >= 6.6 |
| PyQt6-WebEngine | >= 6.6 |

---

## 打包为独立 exe

打包后目标机器**不需要安装 Python**，双击 `EpubReader.exe` 即可运行。

```bat
pip install pyinstaller pillow
python build_exe.py
python build_exe.py --zip      :: 额外生成 zip 分发包
```

产物：

| 路径 | 说明 |
| --- | --- |
| `dist\EpubReader\EpubReader.exe` | 主程序，约 356 MB（onedir，共 146 个文件） |
| `dist\EpubReader-1.0.0-win64.zip` | 压缩包，约 139 MB（`--zip` 时生成） |
| `assets\app.ico` / `assets\app.png` | 程序图标（由 `tools/make_icon.py` 生成） |

### 可选参数

| 参数 | 说明 |
| --- | --- |
| `--zip` | 生成 zip 分发包 |
| `--onefile` | 打成单个 exe（启动时需解压约 340 MB 到临时目录，**更慢且易被杀软误报，不推荐**） |
| `--console` | 保留控制台窗口，便于排查启动问题 |
| `--no-prune` | 跳过裁剪，用于对比排查（体积会回到 566 MB） |

### 为什么默认是 onedir 而不是 onefile

QtWebEngine 内置完整的 Chromium，`Qt6WebEngineCore.dll` 单个就有 **194 MB**，加上 `resources\*.pak`、ICU 数据、语言包等共约 340 MB。onefile 模式下每次启动都要把这 340 MB 解压到临时目录，首次启动可能超过 10 秒，且高频文件写入容易被杀毒软件拦截。onedir 只是把文件放在 exe 旁边，启动快、可控。

### 体积是怎么压下来的

初始 PyInstaller 输出为 566 MB / 3717 个文件，`build_exe.py` 的 `prune()` 做了三件事，降到 356 MB / 146 个文件：

1. **翻译文件白名单**：`translations\` 里原本 231 个 `.qm`，只保留 `qtbase_zh_CN/TW/en`、`qt_zh_CN/TW/en`、`qt_help_zh_CN` 共 7 个（省约 54 MB）。
2. **删除调试资源**：`qtwebengine_devtools_resources.debug.pak`（72 MB）、其余 `*.debug.pak` / `*.debug.bin`、`qtwebengine_devtools_resources*.pak`（省约 88 MB）。
3. **删除未使用的 Qt 模块**：Designer、UiTools、Quick3D、ShaderTools、VirtualKeyboard、Sql、Test、Bluetooth 等 16 个 DLL，以及 assetimporters / geometryloaders / sceneparsers / sqldrivers 等插件目录和对应 QML 目录。

> ⚠️ `Qt6Pdf`、`Qt6Multimedia`、`Qt6Quick`、`Qt6Qml`、`Qt6OpenGL`、`Qt6WebSockets`、`Qt6PrintSupport` 是 `Qt6WebEngineCore` 的**隐式依赖**，删掉后启动会直接报
> `ImportError: DLL load failed while importing QtWebEngineWidgets`。
> `build_exe.py` 的 `DROP_DLLS` 里已用注释标注，改动裁剪列表时请勿加入这些模块。

### 验证打包结果

`--windowed` 构建没有控制台输出，因此程序内置了自检模式：它会依次检查资源定位、EPUB 解析、后台搜索、WebEngine 渲染与页内高亮，并把每一步写入 `selftest_report.txt`（在当前工作目录），最后以退出码表示结果。

```bat
cd dist\EpubReader
EpubReader.exe --self-test
type selftest_report.txt
```

预期结尾为：

```
search_hits=4
chapter_rendered=0
mark_count=3
result=PASS
```

源码环境下同样可跑：`python main.py --self-test`。

端到端检查（启动真实 exe、打开示例书、抓桌面截图判断是否真的画出了内容、再结束进程）：

```bat
python tools/exe_test.py
```

```
桌面尺寸=1920x1080 灰度方差=11769.5
截图：...\build_shots\exe_desktop.png
打包程序端到端检查通过 ✅
```

> 注意：`--windowed` 程序**不能**用 `| more` 之类的管道接收输出，管道会让进程提前退出（退出码 255）且拿不到任何文字。要读取输出请重定向到文件：`EpubReader.exe --self-test > st.log 2>&1`。

---

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+O` | 打开 EPUB |
| `Ctrl+W` | 关闭当前书籍 |
| `Ctrl+Q` | 退出 |
| `Ctrl+F` | 全文搜索（聚焦侧边栏搜索框） |
| `Ctrl+Shift+F` | 切换到搜索面板 |
| `F3` / `Shift+F3` | 下一个 / 上一个匹配 |
| `Esc` | 清除搜索高亮 |
| `Ctrl+T` | 显示 / 隐藏侧边栏 |
| `Ctrl+Up` / `Ctrl+Down` | 上一章 / 下一章 |
| `PageUp` / `PageDown` | 上一页 / 下一页 |
| `Home` / `End` | 本书开头 / 结尾 |
| `Ctrl++` / `Ctrl+-` | 放大 / 缩小字号 |
| `Ctrl+0` | 重置字号 |
| `Ctrl+,` | 阅读设置 |
| `F11` | 全屏 |

阅读区内也可直接使用 `↑ ↓ ← →`、`Space`、`PageUp/PageDown` 滚动，滚到边界自动翻章。选中文字后在右键菜单中选择“搜索选中内容…”可直接搜索。

---

## 项目结构

```
epubreader/
  __main__.py     程序入口；QtWebEngine 导入顺序、OpenGL 上下文、AppID 与自检分发
  mainwindow.py   主窗口：菜单、工具栏、侧边栏、状态栏、搜索与导航调度
  reader.py       阅读视图（QWebEngineView + QWebChannel 桥接 + 注入式 JS）
  bridge.py       JS ↔ Python 的 QObject 桥（滚动、翻页、链接、快捷键）
  webassets.py    主题配色、样式表生成、注入的阅读器 JavaScript（window.ER）
  panels.py       目录树面板与搜索结果面板（自绘 Delegate）
  book.py         EPUB 解析：OPF / spine / 目录 / 正文提取 / HTML 预处理
  search.py       全文搜索引擎与后台线程服务
  loader.py       后台加载线程
  paths.py        数据目录、缓存键、进度持久化、打包后资源定位（resource_path）
  selftest.py     打包后自检：资源 / 解析 / 搜索 / 渲染 / 高亮全链路验证
main.py           启动包装
build_exe.py      PyInstaller 打包脚本（版本信息、裁剪、zip）
assets/
  app.ico         多尺寸程序图标（16~256）
  app.png         同款图标的 PNG 版本
tools/
  make_icon.py         生成程序图标（Pillow 绘制）
  make_sample_epub.py  生成示例书籍
  smoke_test.py        无界面解析 + 搜索自检
  gui_test.py          界面自动化自检（可截图）
  exe_test.py          打包产物端到端检查（启动 + 桌面截图 + 结束）
samples/sample.epub   示例书籍（3 章中文）
```

### 工作原理

1. **解析**：`EpubBook.open()` 读取 `META-INF/container.xml` 定位 OPF，解析元数据、manifest、spine，并把正文解压到缓存目录。
2. **预处理**：每个章节 HTML 经 `HTMLParser` 净化（移除 `script`/`iframe`/事件属性），注入 `<base>` 与 `<meta charset>`，并给每个块级元素分配 `id="erbN"`；同时抽取规范化纯文本，记录 `(文本偏移 → 块 id)` 映射表。
3. **搜索**：在纯文本上用正则查找 → 得到偏移 → 通过映射表定位到具体块及其块内比例 → 跳到该位置并高亮。
4. **渲染**：章节 HTML 通过 `file://` 加载，加载完成后注入 `window.ER` 脚本与主题 CSS，再恢复阅读位置。
5. **高亮**：在 DOM 文本节点中包裹 `span.er-hl`，跨节点场景由脚本内部的文本游标处理。

---

## 数据存放位置

| 内容 | 路径 |
| --- | --- |
| 解压后的书籍缓存 | `%LOCALAPPDATA%\EpubReader\cache\<哈希>\` |
| 阅读进度 | `%LOCALAPPDATA%\EpubReader\progress.json` |
| 界面设置 | 注册表 / `QSettings("EpubReader", "EpubReader")` |

缓存键由文件路径 + 大小 + 修改时间计算，书籍更新后会自动重建。删除 `cache` 目录不会影响阅读，只是下次打开会重新解压。

---

## 自检

```bat
python tools/smoke_test.py        :: 解析 + 搜索（无需图形界面）
python tools/gui_test.py --shots  :: 界面自动化，截图输出到 build_shots\
python main.py --self-test        :: 渲染链路自检，结果写入 selftest_report.txt
python tools/exe_test.py          :: 打包产物端到端检查
```

示例书籍可通过 `python tools/make_sample_epub.py` 重新生成。

---

## 已知限制

- 不支持带 DRM 加密的 EPUB（如 Adobe ADEPT、Apple FairPlay）。
- 固定版式（Fixed Layout，`rendition:layout=pre-paged`）书籍按流式排版显示，版式与纸书不完全一致。
- 搜索结果上限 800 条，超出后仅提示总数。
- 仅在 Windows + Python 3.14 + PyQt6 6.11 上验证；其他平台未做适配。
- 打包产物只能在 **64 位 Windows** 上运行；分发时需整个 `dist\EpubReader\` 目录一起拷贝，不能只复制 exe。
- 程序未做数字签名，首次运行时 Windows SmartScreen 可能提示“未知发布者”，选择“更多信息 → 仍要运行”即可。

---

## 实现要点备忘

若要在其他 PyQt6 环境中复用本项目的做法，以下四个问题值得注意：

1. **QtWebEngine 必须在 `QApplication` 之前导入**，并设置 `Qt.ApplicationAttribute.AA_ShareOpenGLContexts`，否则进程会以 `0xC0000409` 直接崩溃。

   ```python
   from PyQt6 import QtWebEngineWidgets  # noqa: F401
   QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
   app = QApplication(sys.argv)
   ```

2. **自定义 `QWebEnginePage` 时不要覆盖 `QWebEngineView.page()`**。若需要一个“向下翻一屏”的方法，请另取名（本项目为 `scroll_page()`），否则 `page()` 返回 `None`，视图将无法工作。

3. **`QStyledItemDelegate.paint()` 中避免使用 `QTextDocument.drawContents()`**。在本项目验证的 PyQt6 6.11 / Qt 6.11 组合下该调用会触发 `STATUS_STACK_BUFFER_OVERRUN` 崩溃。搜索结果的富文本摘要改用 `QFontMetrics` 逐字符排版 + `drawText` 分段绘制实现。

4. **打包裁剪 Qt 模块时要留意隐式依赖**。`Qt6WebEngineCore` 在加载阶段会间接依赖 `Qt6Pdf`、`Qt6Multimedia`、`Qt6Quick`、`Qt6Qml`、`Qt6OpenGL`、`Qt6WebSockets` 等模块，被裁掉后不会表现为“缺少某个功能”，而是直接

   ```
   ImportError: DLL load failed while importing QtWebEngineWidgets: 找不到指定的模块。
   ```

   排查方法：先用 `python build_exe.py --console` 打一个带控制台的版本，就能看到真实的导入错误；确认后再调整 `build_exe.py` 里的 `DROP_DLLS` / `DROP_PLUGIN_DIRS`。
