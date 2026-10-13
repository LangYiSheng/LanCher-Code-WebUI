# LanCher Code Desktop 便携预览

桌面版与 WebUI 共用 React 前端和 Python 后端，通过独立宿主提供原生窗口、托盘和单实例管理。固定 SDK 来源与 WebUI 一致，不引用原 LanCher Code 源码目录。

## 使用

当前 0.3.0 便携 EXE：`data/desktop-build/dist/LanCher Code Desktop/LanCher Code Desktop.exe`；压缩包为 `data/desktop-build/LanCher Code Desktop-0.3.0.zip`。保留同目录的 `_internal`，双击 EXE 即可启动；启动应用不需要安装 Python、Node 或 Docker。Windows 需要 WebView2 Runtime 和 .NET Framework 4.6.2 及以上，本机已验证；预览版暂不携带 WebView2 安装器。

顶部左侧提供侧栏开关、上一页、下一页和工作台菜单，右侧提供原生最小化、最大化/还原和关闭。标题区域可拖动，边缘可缩放。重复双击会唤醒已有实例。菜单可收起到托盘，双击托盘图标恢复。退出时有前台任务或后台进程则显示内置选择：取消、继续后台运行、停止并退出。

第一次启动使用独立配置。左上角菜单“导入模型配置副本”经过确认后复制现有用户模型配置，原文件保持不变。MCP、Skills 和权限不自动导入，可在桌面设置中配置。项目仍使用自己目录中的 `.lancher/sessions` 和 SDK 会话锁。项目开发所需的 Git、Node 等工具按工程要求安装，与应用自身启动依赖分别处理。

## 数据与隔离

默认桌面数据为 `%LOCALAPPDATA%/LanCherCodeDesktop`：`data/webui.sqlite3` 保存项目登记，`home/.lancher` 保存专用配置，`webview` 保存窗口浏览器数据，`ui-state.json` 保存草稿、布局等前端状态。前端状态由专用后端按序落盘，随机端口变化不丢失草稿；退出前等待保存，失败保留窗口并允许重试。

桌面只监听自己的本机随机端口，使用会话 Cookie 和来源检查，不占用或连接当前 8765 服务。单实例按数据目录区分；`--data-dir` 可指定独立预览目录。原始 WebUI 继续使用原数据库、用户配置和静态资源，原 LanCher Code 仓库及运行环境保持独立。

## 构建

在本仓库运行 `./build-desktop.ps1`。脚本校验固定 wheel 的 SHA256，在 `data/desktop-build/venv` 创建独立 Python 3.14 环境；即使 SDK 包版本号相同，也重新安装已校验 wheel 并检查依赖。前端输出到 `data/desktop-build/frontend-dist`，不覆盖 `frontend/dist`，再构建目录式 EXE。

桌面依赖版本见 `desktop/requirements.txt`，Python/.NET/WebView2 与冻结程序已在本机真实运行验证。浏览器和桌面共用前端业务；`DesktopBar`、宿主接口、持久化与导航为各自职责，窗口桥接不提供通用 Shell 或文件操作接口。

## 验收边界

通过真实 WebView2 和最终冻结 EXE 检查窗口按钮、导航、侧栏、托盘、截图、单实例唤醒及专用工程 SDK 文件读写和原生 Shell。使用注入的确定性 Provider，不调用外部模型。记录位于被忽略的 `data/desktop-build/`。

首版为本机便携预览，暂未制作安装器、自动升级或在无 WebView2 的干净 Windows 系统上验收。普通窗口的原生圆角、真实鼠标标题栏拖动、顶部客户区无白缝、原生文件夹选择与回填已加入实际窗口验收。中文输入法、多屏 DPI、拖动贴靠和边缘缩放仍需进一步体验。

## 标题栏与文件夹修正

标题栏共用工作台背景；原生非客户区不再留下顶部空白，Windows 11 普通窗口显式使用系统圆角，最大化沿用系统规则。鼠标捕获释放、窗口移动和目录选择均在窗口 UI 线程执行。共享 `/api/projects/pick` 在桌面宿主通过原生文件夹对话框实现，不把冻结 EXE 当成 Python 子进程。

## 0.3.0 更新

Desktop 与 WebUI 共用 0.3.0 版本，固定 SDK 为 0.1.0 / `f984bb72b46d8eff8d82d148782da83a62a3d308`。本版包含工作台动画、模型与推理等级组合选择、进程视图、统一圆角，以及精简提示和每轮思考折叠；完成态“已思考”前不显示图标，复制回答仅取最后正文。

最终 EXE 已在独立配置和工程中通过 19 项真实桌面检查，包含 WebView2、窗口按钮、标题栏拖动、托盘、单实例、原生文件夹选择以及 SDK 文件读写和 Shell。记录位于 `data/desktop-build/release-0.3.0-smoke/acceptance/result.json`，未调用外部模型。旧便携目录保留在 `data/desktop-build/before-0.3.0`。

本次浏览器版 8765 也已更新至相同 SDK，继续提供预览；Desktop 沿用自己的独立端口、配置与数据目录。
