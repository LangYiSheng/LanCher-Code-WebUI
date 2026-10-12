# 验收记录

2026-10-12，新 LanCher Code WebUI 完成以下验证。旧 Agent Lab 的演示模型与 Docker 记录属于备份，没有用作本版本通过的依据。

## 侧栏搜索、关于与实验入口清理

侧栏顶端改为“搜索聊天”按钮，打开独立搜索弹窗；新建按钮明示 `Ctrl+N`，`Ctrl+K` 保留快速操作。正式侧栏与搜索排除归档和草稿，归档仍在设置中查看。搜索支持中文、全角字符、多关键词及项目/模型/Web/SDK 身份，按置顶、更新时间与 id 稳定排序。

本轮前端完整测试 **59 项全部通过，507.8581 毫秒**：此前 51 项，加 [搜索边界 5 项](frontend/tests/chatSearch.test.mjs) 与 [发布元数据 3 项](frontend/tests/releaseMetadata.test.mjs)；TypeScript 检查与 Vite 构建通过，最终资源为 `index-CzjdmyyJ.js` / `index-DypmFN58.css`。搜索测试验证未登记项目排除、多字段所有关键词匹配、中文与 NFKC 规范化、身份定位，以及冻结输入不被修改、输入顺序改变后排序仍确定。

“关于”分别显示 WebUI **0.2.0**、LanCher Code SDK **0.1.0** 和完整固定提交 `f3329bc9bcc8b2ef7afd08cc80d3c9f85bcfd61b`。发布元数据由 [releaseMetadata.mjs](frontend/releaseMetadata.mjs) 读取项目版本与固定 SDK wheel；前端 package/lock 同步为 0.2.0。无效版本、SDK 依赖与 wheel 不一致、缺失完整提交会拒绝生成元数据，避免展示误导信息。设置仍有八类可配置领域，“关于”是独立只读信息页。

旧实验历史的设置入口、bootstrap 字段与后端读取接口已从源码移除。[移除回归](tests/test_legacy_api_removal.py) 连同原生归档、会话锁与 bootstrap 场景共 **5 passed，10.57 秒**，仅有既有 Starlette 弃用提示。新测试以读路径守卫证明 bootstrap 不读取实验内容，`/api/legacy` 与明细接口返回 404，同时所有备份文件、来源记录和临时共享配置字节保持不变。新增 1 项后，后端 **64 项均有通过证据**，来自此前 63 项与本轮新增定向回归，未重复执行完整 64 项。旧实验数据只保留磁盘备份，以下历史阶段证据保留原 SDK 和场景来源。

主任务在实际 IAB 使用独立 8767 fixture 完成本轮验收，保留真实 SDK 归档样本，使用虚拟配置，没有刷新用户的生产页面：

- 主品牌旁的搜索按钮可打开弹窗，常驻搜索栏数量为 0，旧侧栏收起按钮数量为 0，新建标注为 `Ctrl+N`。折叠侧栏与手机侧栏都有可用的搜索入口。
- 弹窗初始焦点位于搜索输入，Esc 关闭后回到搜索按钮。中文“原生读写”返回一项；搜索仍归档的“第二段”得到零项，Enter 不跳转。ArrowDown 选择 `UI 草稿验收 A`，Enter 打开对应聊天标题。
- 在搜索中触发 Ctrl+N，新建专用 A 草稿后弹窗关闭；正式搜索数仍为 3，草稿没有进入侧栏或结果。
- “关于”实际显示 WebUI 0.2.0、SDK 0.1.0 与完整 f3329bc 提交，不显示保存栏。“数据与历史”只有归档与浏览器输入草稿，旧实验区块数量为 0。新后端 `/api/legacy` 返回 404，bootstrap 不再包含 `legacy_count`，原生归档记录仍保留。
- About 和搜索页在 390×844 下文档宽度均为 390px，无横向溢出；控制台 error 为 0。视口已恢复、验收页已关闭，没有外部模型调用。

| 本轮实际截图 | 内容 |
|---|---|
| [聊天搜索](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-chat-search.jpg) | 独立搜索弹窗与正式聊天结果 |
| [关于](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-about.jpg) | WebUI 与 SDK 版本、完整固定提交 |
| [数据与历史](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-history-clean.jpg) | 归档与输入草稿，旧实验入口已移除 |
| [窄屏关于](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-about-mobile.jpg) | 390px 版本信息 |
| [窄屏聊天搜索](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-chat-search-mobile.jpg) | 手机搜索与结果布局 |

实际记录见 [browser-comments-qa.json](data/ui-acceptance/browser-comments-qa.json)。这份本机离线验收没有改写下文初版 00e0797 SDK 的在线 16 项来源。

最后在即时检查任务与后台进程均为空后，主任务正常重启正式 8765，实际 PID **59040**、launcher **70464**。状态与 bootstrap 均为 200，config_error=null，首页提供 `index-CzjdmyyJ.js`，SDK 来源仍为完整 f3329bc；`/api/legacy` 返回 404，bootstrap 不含 `legacy_count`。本轮实验读取链移除和此前 MCP 显式清空超时恢复默认补丁已经加载。正式服务随后已有用户新任务，没有再次重启或强制刷新用户页面。

独立 8767 经关闭接口返回 200 后，实际 PID 59776 与 launcher 54868 均结束，端口无监听。启动与停止脚本的本机检查改为直连，避免系统代理影响就绪判断；两份 PowerShell 脚本语法检查无错误，实际直连状态检查为 200，没有修改用户代理设置。最终结果见 [服务证明](data/ui-acceptance/browser-comments-service-proof.json)。本轮修改与提交范围仅为独立 WebUI，原核心源码、环境和用户现有并行改动均保留。


## 设置工作区与归档入口

设置阶段前端 **51 项全部通过，TypeScript 检查与 Vite 构建通过**，资源为 `index-CIndxtVz.js` / `index-Uv7-4tK4.css`。设置采用三组导航、八类配置和模型目录/详情布局，归档入口集中在“数据与历史”。下面的核心同步与初版章节保留各阶段证据；本节保留设置工作区改版时的界面与交互证据。

后端测试库 **63 项均有通过证据**：核心同步完整 55 项，加复审新增 4 项、归档新增 2 项、MCP 新增 2 项；没有单次完整执行 63 项。本轮按变动范围复验：

- [归档回归](tests/test_archive_settings.py) 与原草稿、历史关闭和配置冲突场景共 **5 passed，7.68 秒**，见 [输出](data/settings-archive-regression-fixed.stdout.txt)。真实 SDK 归档写入一次原生事件，读取不改历史；Web 恢复保留 UUID 和原生 archived 标记，重启后能继续原会话。忙时归档返回 409，不中断正在执行的任务。
- [MCP 设置回归](tests/test_configuration.py) 共 **7 passed，0.78 秒**，见 [输出](data/mcp-settings-regression.stdout.txt)。删除 env/header 键后保留其他掩码密钥与 `${ENV}` 引用，SDK 读回正确展开。显式清空三类超时恢复默认；省略这些字段保留既有超时。全部配置与工程都在专用临时目录。

主任务在实际 IAB 使用 `http://127.0.0.1:8767` 的独立数据库、fixture home、虚拟密钥和工程完成以下交互，没有写真实用户配置或调用外部模型：

- 模型、输入显示与无效执行 JSON 三份草稿在切换分类、关闭及重开后独立保留。HTTP 读回确认未保存阶段模型仍为 `fixture-one-ui`、时间戳仍启用、命令配置仍为空，没有提前写入。
- 只保存模型后，显示名变为 `Fixture One · 设置草稿验收`；未保存的时间戳草稿仍为未勾选，无效 JSON 原文仍在且该分类保存不可用。确认放弃输入显示只清理当前分类，执行 JSON 草稿继续保留。
- 全局 MCP 的 `ui-draft-only` 只在内存；切换项目后为空，用键盘 Home/Enter 返回全局仍是原草稿。HTTP 连接高级区只显示请求头，不显示环境变量；三类超时显示恢复默认提示。没有保存这份 MCP 草稿。
- 未保存的深色外观跨分类继续预览；从品牌入口退出设置后恢复已保存浅色，重开设置继续深色草稿，选择浅色回到基线。设置草稿仅在当前页面内存中保留，不宣称浏览器刷新后持久化，密钥不写入浏览器存储。
- 归档初始两项，搜索“原生读写”得到一项，项目 A 筛选得到空状态。打开归档显示原有两条消息及 read/write 工具卡；输入区数量为 0，检查器不可用，普通侧栏没有归档开关。
- 恢复第一项后，同一 Web id 与 SDK UUID 返回侧栏，剩余归档一项。独立 HTTP 读回确认两份原生历史 SHA256 与工程文件 SHA256 全部不变。
- 模型与归档页面在 390×844 下文档宽度均为 390px，无横向溢出，Native select 数为 0；浏览器控制台 error 为 0。验收页已关闭、视口恢复，没有刷新用户正在使用的生产页。

| 最新实际截图 | 内容 |
|---|---|
| [浅色模型设置](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-settings-models-light.jpg) | 分组导航、模型目录与详情 |
| [深色模型设置](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-settings-models-dark.jpg) | 未保存外观草稿预览 |
| [归档设置](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-settings-archives.jpg) | 项目筛选、搜索与恢复入口 |
| [归档只读记录](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-archive-readonly.jpg) | 原生工具记录，无输入与运行控制 |
| [窄屏模型设置](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-settings-models-mobile.jpg) | 390px 模型详情 |
| [窄屏归档设置](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-webui-settings-archives-mobile.jpg) | 390px 归档列表 |

证据为 [实际浏览器记录](data/ui-acceptance/settings-redesign-browser-qa.json)、[保存前基线](data/ui-acceptance/settings-redesign-baseline.json)、[未保存阶段读回](data/ui-acceptance/settings-redesign-unsaved.json) 和 [保存与恢复后读回](data/ui-acceptance/settings-redesign-readback.json)。归档样本由 [独立种子脚本](scripts/ui_archive_seed.py) 调用真实 SDK 生成，记录在 [archive-proof.json](data/ui-acceptance/archive-proof.json)。初版在线 16 项仍属于 00e0797 SDK，本轮离线设置验收没有改写这项来源。Windows 原生中文 IME 候选确认仍需人工验证。

设置阶段独立 8767 已经关闭接口优雅退出：实际 PID 58224 与 launcher 73316 均结束，端口无监听。正式 8765 仍为 PID 64668，状态 200，当时已从静态目录提供该设置阶段前端资源。重启前检查发现用户正在运行和排队的任务，以及 Node 开发服务，主任务立即取消重启，没有执行关闭或停止。该阶段 MCP 显式清空超时恢复默认的后端补丁已落盘并通过上述回归，当时保留的进程尚未加载；后续已由本轮最终部署加载。其他已运行能力未受中断。见 [最终服务状态](data/ui-acceptance/settings-final-service-proof.json)。

本轮所有修改限于独立 WebUI；没有修改或回滚原核心仓库及其依赖环境。当前原仓库已有的用户与并行工作未提交变更保留，SDK wheel 仍只包含固定的已提交 f3329bc 归档。

## 核心同步 f3329bc

先将已验收 WebUI 成果提交为 `b1961e3`，再同步核心最近三个提交。新版 wheel 固定到 `f3329bc9bcc8b2ef7afd08cc80d3c9f85bcfd61b`，使用 `git archive` 从已提交源码归档到本项目 ignored `vendor/sdk-f3329bc`，没有从工作区未提交代码构建。

- wheel SHA256：`d9a79a6e64f60c539e354107dea51f72b904a11a74831844739af7323a1cdb70`，记录在 [vendor/snapshot.json](vendor/snapshot.json)。SDK 版本仍为 0.1.0，安装保留按哈希校验及单包显式重装。
- 核心依赖声明未变，`requirements.lock.txt` 的 44 项版本与直接 wheel 路径保持不变。专用新环境 `data/sdk-update-f3329bc/venv` 安装及 pip check 全部兼容；六份关键安装代码的哈希与固定归档一致，见 [构建来源证明](data/sdk-update-f3329bc/build-proof.json)。
- 新环境完整后端回归 **55 passed，139.22 秒**，见 [完整输出](data/sdk-update-f3329bc/pytest-final.stdout.txt)。复审新增恢复继承 1 项、校验脱敏 2 项、认证失效恢复 1 项，连同相关发现/推理/fixture 共 **12 passed，5.70 秒**，见 [定向输出](data/sdk-update-f3329bc/pytest-review-fixed.stdout.txt)。该同步阶段 **59 项均有通过证据**，没有声称单次执行完整 59 项。
- [新版契约测试](tests/test_sdk_update.py) 覆盖草稿推理控制、原生首任务与同 UUID 恢复、能力不支持时回 auto、忙时拒绝及命令补全；压缩实际继承 high 与所选 API 形式。发现通过真实本机 HTTP 和原生 SDK client 验证分页、ENV 密钥引用、同源模型更新与独立连接保护、合并不保存、显式 PATCH、scope/revision/connection/token 失效。
- 认证 401 后旧票据立即失效，默认重开仍向远端确认；随后 500 不可用旧 stale 列表，fresh 200 才恢复缓存。422 校验错误使用固定提示，不回显含密钥 input。发现合并保留 auto、None、空名称和密钥恢复继承意图，保存后由 SDK 读回确认有效。
- 缓存率按同批有效 input/cache 样本计算，保留估算标志与样本数。真实本机 SSE 5 请求汇总为 input 400/output 71/cache 107，总量仍 471；估算缓存率 107/400，4 个有效样本来自 5 个请求，不把缓存、推理子项再次计入总量。
- 专用 [UI fixture 脚本](scripts/ui_acceptance_fixture.py) 的 `--model-api` 必须显式启用，默认不改 preset、不增加模型路由。启用时只改 fixture home 的 test 连接，保留虚拟密钥，在同端口返回有档位、明确无档位、custom ultra 和未知能力四类列表；[范围测试](tests/test_ui_model_fixture.py) 已通过。

前端新版 **33 项测试、TypeScript 与 Vite 构建通过**，资源为 `index-DYibOGIn.js` / `index-CNVSh9j_.css`。以下初版在线 16 项测试与截图保留原 SDK 00e0797 来源，不能作为新版在线重跑的证据。

新版实际 IAB 验收使用专用新环境与 8767 fixture，模型列表接口和密钥都是本机虚拟数据，全程没有外部模型请求：

- 列表展示 4 项、2 项已加入，区分 low/high、明确不支持、自定义 ultra 与未知能力。先勾选 Mini，再搜索 unknown，隐藏选择仍保留 1 项；加入只修改设置草稿，HTTP 读回确认未提前写入 metadata。
- 显式保存后新增 Mini，并更新两个同源既有模型 metadata；默认模型 `test/one` 与手动显示名 `fixture-one-ui` 保留。最终独立 HTTP 读回 one/two/Mini 三项，two 档位为空、Mini 为 low/ultra，API Key 仍只显示已配置而无原文。
- 同一原生对话 high 刷新后保留，换到明确无档位的 fixture-two 时只有 auto 且核心提示回退；换到 Mini 时自定义选择器显示 auto/low/ultra。裸 `/effort` 打开推理选择面板，没有模型请求。
- 草稿 `6d5b05005be9469c9c434fd8ad3d9193` 的中文输入与 high 刷新后保留，不进入正式历史侧栏；正式对话仍为 A/C 两项。Native select 数为 0，390px 窄屏无溢出，控件换行后权限选择仍可操作。控制台 error 为 0。

| 新版实际截图 | 内容 |
|---|---|
| [发现模型](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-model-discovery.jpg) | 四类能力声明与已加入状态 |
| [推理强度](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-effort.jpg) | Mini 自定义 auto/low/ultra 下拉菜单 |
| [窄屏推理控制](C:/Users/LanCher/.codex/visualizations/2026/10/12/01a12ec2-dc0e-7083-a0c4-4556d3d2f944/lancher-code-webui-effort-mobile.jpg) | 390px 草稿与换行控件 |

证据为 [新版实际浏览器记录](data/sdk-update-f3329bc/browser-qa.json)、[脱敏设置读回](data/sdk-update-f3329bc/ui-model-settings-readback.json) 与 [验收实例关闭](data/sdk-update-f3329bc/ui-shutdown.json)。8767 已优雅关闭，actual PID 67256 与 launcher 66792 都结束、端口无监听；正式 8765 只读检查返回 200。

主任务在确认正式服务无任务和后台进程后完成生产升级：优雅关闭、只对 current wheel 执行 `--no-deps --reinstall`、44 包 pip check 兼容，再启动 8765。该次升级 actual PID 64668、launcher 42432，只监听本机；SDK 状态返回完整 f3329bc SHA，首页 200 且使用新版 bundle，config_error=null，14 条命令含 effort。构建仅取已提交 f3329bc 归档，不包含原核心仓库后来产生的未提交变更。以上生产升级由主任务执行，验收任务只操作独立环境和 fixture。 [生产安装来源证明](data/sdk-update-f3329bc/production-proof.json) 记录正式 `.venv` 的安装路径及六份 SDK 文件与固定归档的哈希一致结果。

## 初版自动化与原生工具

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

## 初版前端与真实浏览器

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

设置验收使用 `http://127.0.0.1:8767` 独立实例，专用数据库、fixture home、虚拟密钥和工程，MCP 连接关闭。初版 SDK 阶段的 6 类真实 UI 保存全部返回 200：模型、输入显示、Agent 行为、全局 MCP、用户规则和执行配置。独立 HTTP 读回确认模型显示名 `fixture-one-ui`、时间戳启用、默认阶段 plan、空 MCP/用户规则及执行配置原样保存的重启提示，密钥原文未发给页面。常用/高级分组、独立连接、思考覆盖、继承恢复与密钥保留状态均在真实页面检查。没有写真实用户配置。

独立检查器正例由 [scripts/ui_editor_seed.py](scripts/ui_editor_seed.py) 在 fixture 项目 C 中生成：注入测试 Provider 调用真实 SDK 的 read/edit/delete/write 工具，留下原生历史和文件基线，新增、修改、删除各一项。服务重启后 HTTP 读回仍为 A1/M1/D1。此前真实在线 A/B 历史产生于基线功能加载之前，其变更列表为空；没有回填或伪造基线。

证据为 [六域保存读回](data/ui-acceptance/settings-readback.json)、[原生检查器样本](data/ui-acceptance/editor-proof.json)、[差异预览](data/ui-acceptance/editor-previews.json)、[实际浏览器记录](data/ui-acceptance/browser-qa.json) 与 [最终关闭记录](data/ui-acceptance/final-shutdown.json)。最终已通过关闭接口优雅退出：实际 PID 71488 与 launcher PID 73668 均结束，8767 无监听，8765 仍返回 200。可用 [scripts/ui_acceptance_fixture.py](scripts/ui_acceptance_fixture.py) 重建专用验收服务；进程 stdin/停止由临时配置后端测试验证。

## 固定 SDK 边界

当前固定 f3329bc SDK 仍没有原生取消归档接口；三个同步提交未改变 archive_session 接口，也没有新增 unarchive。网页恢复归档时恢复 Web 导航，保留 SDK archived 标记；TUI 可以按 UUID 恢复完整历史。宿主没有编造 SDK 事件。

原生命令运行在本机，权限属于 SDK 应用层检查，Docker 不是运行依赖。原开发仓库代码、环境与 Git 状态保持独立。旧 `D:\Dev\LanCher Agent Lab` 与本项目 `data/legacy/data/` 仅保留磁盘备份。本轮已从当前产品移除旧实验历史入口及后端读取链，历史阶段的验收证据仍保留原来源，不改写为当前产品能力。
