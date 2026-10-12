# 验收记录

2026-10-12，新 LanCher Code WebUI 完成以下验证。旧 Agent Lab 的演示模型与 Docker 记录属于备份，没有用作本版本通过的依据。

## 自动化与原生工具

最终完整执行后端测试：**47 项全部通过，151.54 秒**，包括此前 42 项和新增草稿生命周期 5 项。早期完整 31 项输出仍保存在 [data/pytest-final.stdout.txt](data/pytest-final.stdout.txt)；真实本机 SSE 用量、文件语义、只读上下文与草稿测试分别位于 [tests/test_usage_http.py](tests/test_usage_http.py)、[tests/test_file_change_semantics.py](tests/test_file_change_semantics.py)、[tests/test_context_preview.py](tests/test_context_preview.py) 与 [tests/test_drafts.py](tests/test_drafts.py)。

所有测试都使用显式临时 home、临时共享配置与临时工程；模型边界使用测试注入 Provider 或真实本机 HTTP/SSE 服务。真实 SDK 执行了文件读取、写入、局部编辑、glob/grep、计划、压缩、Skills/MCP、本地离线 wheel 安装和托管进程。没有运行时固定生成脚本。

验证覆盖：

- 修改基线的 `-beta/+gamma` 差异、新文件 added 差异和列表状态；SDK 与网页预览遵守同一永久 ReadFile 拒绝规则，拒绝文件不出现在列表。
- 创建临时 venv 后离线安装本地 wheel、实际 import 得到 42；显式禁用 pip 缓存及版本检查。
- turn 进程在活跃轮次转入后台，真实 HTTP 服务跨轮次继续；stdin 回显、日志、停止与端口失效。
- 同项目严格 FIFO、不同项目并行；A 运行、B 已排队、A 后追加 follow_up 时按 A/B/A后续执行；四个前台槽位占用时取消第五项目，不启动其模型请求。
- 停止保留输入与显式恢复；空队列保存配置后才追加的 follow_up 仍能继续；人工暂停空队列后新增输入保持暂停，只有显式恢复才运行。
- 审批拒绝、陈旧审批、配置修订冲突、密钥/环境值掩码与保留、项目规则作用范围、模型 URL 与密钥继承。
- 原生会话写入锁；另一个 SDK 宿主模拟 TUI 接管并写入历史，Web 再恢复同一 UUID；服务重启保留完整历史。
- 已删除的历史模型回退到当前默认模型，保留原会话消息。
- 回答/会话/项目/服务用量，已报告缓存量和未知字段；完整命令目录、补全与控制派发。
- 全局事件单调序列、游标回放与过期重置；独立 uvicorn 进程真实启动、HTTP 请求及优雅退出。
- 空白草稿读取、改名、模型/阶段/权限与 Skills 控制不登记 Web 历史、不创建 SDK UUID；首条任务接受时立即转正式，即使排队或随后失败也保留记录；取消后服务重启可恢复待处理任务。
- 草稿身份重建、项目作用范围与正式/SDK UUID 碰撞拒绝；旧空白记录保守迁移，已有原生历史、待处理任务或文件基线的记录均保留。

文件/上下文改动按必要范围复验，未为视觉样式编写镜像测试：

- [tests/test_file_change_semantics.py](tests/test_file_change_semantics.py)：新增 8 项，验证恢复原文与失败编辑不算修改、递归删除记录后代、临时新增再删除净零、原有空文件删除、无末尾换行标准 marker、外部 Git 差异不归本对话、聊天/项目作用范围。首批新 6 项加原文件/永久拒绝/删除恢复 3 项共 **9 passed，40.46 秒**；两项边界 **2 passed，7.57 秒**。输出为 [data/change-semantics.stdout.txt](data/change-semantics.stdout.txt) 与 [data/change-edge.stdout.txt](data/change-edge.stdout.txt)。
- [tests/test_context_preview.py](tests/test_context_preview.py)：新增 2 项，原生工具任务释放后估算 tokens 大于 0、容量来自 fixture 模型且与活跃估算接近；TUI 实际持有 UUID 写入锁时，详情读取成功，native events 文件字节不变。连同旧 TUI 互操作和真实 OpenAI SSE 回归共 **4 passed，16.17 秒**，输出为 [data/context-preview.stdout.txt](data/context-preview.stdout.txt)。

“项目文件”只浏览当前存在的工程文件；“本对话变更”按原生文件工具首次编辑前文本基线统计 added/modified/deleted。恢复原样会退出变更列表，未编辑文件不借用 Git 工作区差异。递归删除只记录可预览、权限允许的后代，单文件 1 MiB、单次总预算 16 MiB；Shell 和旧 TUI 历史没有 Web 基线，不自动归为当前对话变化。

只读历史上下文沿用 SDK 的请求投影和估算函数，复制状态后计算，不创建 Agent、不取得会话写入锁、不调用模型。主任务还对真实在线 B 会话核验了保存快照：tokens 11650、window 128000、source usage_calibrated、snapshot true；历史字节与原 state 对象都未改变。

新增测试使用默认 OpenAIProvider 与真实本机 SSE，依次覆盖 429 失败、用户重新提交后的 EOF 不完整流、再次提交成功、同 UUID 切换第二模型成功及流中取消。5 个请求按 request_id 去重；验证跨模型和四种作用范围账本、累计用量覆盖、未知字段、部分流与重复读取/释放恢复不膨胀。总 input 400、output 71、cache 107、cache creation 33、reasoning 24；总 token 为 471，子项没有重复叠加。这是用户恢复重试，SDK 不会自动重试通用 429/EOF。

测试输出包含 Starlette TestClient 对 httpx 兼容层的未来弃用提示；没有测试失败。

## 真实在线双项目

模型：`intern-ai/deepseek-v4-flash-0731`。SDK 固定快照：`00e079718869c75343dbc629b0cfd6ee084ac6fa`。

运行 [scripts/acceptance.py](scripts/acceptance.py)，两个不同项目同时处于运行状态，各自自主编写标准库 Todo 后端与 HTTP 测试。两边原生 `run_command` 都返回退出码 0、`Ran 8 tests` 和 `OK`，**合计 16 项真实 HTTP 测试通过**。

| 专用工程 | Web 对话 | 实际结果 |
|---|---|---|
| `data/acceptance_projects/20261012T084647Z-todo-a` | `a5616c6c3eac423f9c263feecf8fdf8a` | 8 个真实 HTTP 测试，退出 0 |
| `data/acceptance_projects/20261012T084647Z-todo-b` | `dd0d156e74934dcda9d1760bf9ab44f6` | 8 个真实 HTTP 测试，退出 0 |

脚本还核验了源码恰有 8 个 test 方法且使用实际 HTTP 请求、完整 SDK 会话目录、无运行中进程，以及 SSE 连续回放序列 818、819。两个 owner 已释放。证据为 [data/acceptance.json](data/acceptance.json)，`passed=true`、`overlap_seen=true`。

验收只在上述新建专用目录工作，没有修改用户共享配置或原 LanCher Code 开发仓库。

## 前端与真实浏览器

前端完整执行 **25 项测试全部通过**：状态/快照/归属 6 项、检查器契约 6 项、用量语义 7 项、面板宽度与草稿恢复 6 项；TypeScript 检查与 Vite 构建通过。最终构建为 `index-D754RdNf.js` 与 `index-dNoHAKTX.css`。

最终工作台使用轻雾背景与统一圆角，侧栏融入背景，聊天与检查器顶部齐平；主面板 12px、内容区 10px、控件 6px。品牌和欢迎入口使用原 LC 图形的 luminance mask，随 currentColor 适配浅暗主题；favicon 复用原 ICO。助手消息使用 Sparkles 图标和 LanCher 名称。正式 `lucide-react` 图标按文件、编辑、搜索、命令、进程、计划、Skills 和 MCP 等语义显示。检查器左侧预览、右侧目录树连续连接，实际测得 treeLeft 等于 viewerRight、间距 0。

主任务在实际 IAB 完成以下交互验收；没有使用假截图或替代浏览器驱动：

- 浅色检查器显示新增、修改、删除各一项及真实差异；深色“项目文件”显示当前源码和目录。600px 检查器宽度的最终截图见下表。
- files/changes 标签切换保持 540px 宽度。键盘 Home 调为 280px，End 调为 746px 并保留 420px 聊天空间；拖到原始 220px 自动关闭，重新打开为 280px。新草稿首次只打开“新标签页”选择页，没有预置内容标签。
- 页面 Native select 元素为 0。自定义模型菜单用 End/Enter 选择 `test/two`，阶段菜单可选计划，权限菜单 Esc 关闭且不改变值。
- 空白 A 草稿不进入历史侧栏，重复新建复用该草稿并保留文本。刷新及第二次服务重启后，同一 Web id 的 `test/two`、plan 与输入恢复；客户端对重启后的 404 重建同一草稿身份。
- 重启恢复后将 A 阶段改为讨论并提交首条测试消息。虚拟端点 `127.0.0.1:1` 连接失败，正式历史仍保留：draft=false、status=failed，原生 UUID `88b0daaefbdc4fe3a97ae29d7c74f7e0`，消息数 2。这是首条失败保留正例，没有在线模型请求，属于独立 UI 验收。
- 390×844 窄屏无横向溢出，376px 检查器覆盖面板可以返回聊天。侧栏关闭后从辅助功能与键盘导航移除；从侧栏进入设置后没有残留遮罩。
- 内置项目改名弹窗实际打开，原生 JS dialog 为 undefined，背景菜单为 0。用量浮卡保留未知子项，显示缓存率与只读上下文来源；截图中的 28.6% 缓存率、55/128000 上下文来自注入测试 Provider，只作显示语义验证。
- 浏览器控制台 error 为 0。既有 A/B 输入隔离、聊天滚动恢复、检查器 tab/file 恢复、键盘补全与命令面板行为仍有实际浏览器记录。

| 最终实际截图 | 验证内容 |
|---|---|
| [浅色工作台](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-workbench-light.jpg) | 原生 A1/M1/D1 与修改差异 |
| [深色工作台](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-workbench-dark.jpg) | 项目源码与目录树 |
| [新标签页](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-new-tab.jpg) | 新草稿选择入口，无预置标签 |
| [移动端](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-mobile.jpg) | 390×844 检查器与返回聊天 |
| [内置弹窗](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-dialog.jpg) | 项目改名与背景交互隔离 |
| [用量浮卡](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-usage.jpg) | 缓存、未知子项与只读上下文 |

已验证中文文本草稿；真实 Windows 中文 IME 候选确认未直接验收，当前工具不能控制系统 IME，代码用 isComposing 防止候选确认触发误发送。

设置验收使用 `http://127.0.0.1:8767` 独立实例，专用数据库、fixture home、虚拟密钥和工程，MCP 连接关闭。此前 6 类真实 UI 保存全部返回 200：模型、输入显示、Agent 行为、全局 MCP、用户规则和执行配置。独立 HTTP 读回确认模型显示名 `fixture-one-ui`、时间戳启用、默认阶段 plan、空 MCP/用户规则及执行配置原样保存的重启提示，密钥原文未发给页面。常用/高级分组、独立连接、思考覆盖、继承恢复与密钥保留状态均在真实页面检查。没有写真实用户配置。

独立检查器正例由 [scripts/ui_editor_seed.py](scripts/ui_editor_seed.py) 在 fixture 项目 C 中生成：注入测试 Provider 调用真实 SDK 的 read/edit/delete/write 工具，留下原生历史和文件基线，新增、修改、删除各一项。服务重启后 HTTP 读回仍为 A1/M1/D1。此前真实在线 A/B 历史产生于基线功能加载之前，其变更列表为空；没有回填或伪造基线。

证据为 [六域保存读回](data/ui-acceptance/settings-readback.json)、[原生检查器样本](data/ui-acceptance/editor-proof.json)、[差异预览](data/ui-acceptance/editor-previews.json)、[实际浏览器记录](data/ui-acceptance/browser-qa.json) 与 [最终关闭记录](data/ui-acceptance/final-shutdown.json)。最终已通过关闭接口优雅退出：实际 PID 71488 与 launcher PID 73668 均结束，8767 无监听，8765 仍返回 200。可用 [scripts/ui_acceptance_fixture.py](scripts/ui_acceptance_fixture.py) 重建专用验收服务；进程 stdin/停止由临时配置后端测试验证。

## 固定 SDK 边界

固定 00e0797 SDK 没有原生取消归档接口。网页恢复归档时恢复 Web 导航，保留 SDK archived 标记；TUI 可以按 UUID 恢复完整历史。宿主没有编造 SDK 事件。

原生命令运行在本机，权限属于 SDK 应用层检查，Docker 不是运行依赖。原开发仓库代码、环境与 Git 状态保持独立。旧 `D:\Dev\LanCher Agent Lab` 因文件句柄未改名，仍保留为历史备份，旧数据在本项目 `data/legacy/data/` 只读展示。
