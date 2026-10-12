# LanCher Agent Lab

独立的本地 Agent 工作台，直接调用固定快照的 `lancher_code.sdk`。当前 LanCher Code 仓库不参与运行，不共用虚拟环境、配置、权限、Skills、MCP 或会话。

## 启动

```powershell
cd 'D:\Dev\LanCher Agent Lab'
.\start.ps1
```

打开 http://127.0.0.1:8765 。`start.ps1 -Port 8766` 可更换端口。端口只监听本机；跨站浏览器请求被拒绝。

已有 `.venv` 可直接启动。重建环境用 `setup.ps1`，需要 Python 3.14、uv 和已运行的 Docker Desktop。它安装 `vendor/wheels` 中固定并校验 SHA256 的 SDK wheel，不链接原项目。首次运行需要 `docker pull python:3.14-slim`；依赖版本记录在 `requirements.lock.txt`。

## 可以试什么

- 新建演示会话，发送“从零创建一个 Todo 后端并运行测试”。Agent 会生成 app.py、HTTP 接口测试和 README，测试执行需要在网页审批。
- 发送“故意失败再修复后端”，观察第一次 HTTP 测试失败、Agent 修改文件、第二次测试通过。
- 发送“慢慢运行，我要测试停止”，运行中追加任务、关闭页面重连或按停止，检查队列暂停与恢复。
- 发送“测试审批”，拒绝请求。工具不会执行，并记录真实的 SDK 拒绝结果。
- 查看文件、代码差异、工具输出、审批、会话和模型用量。演示模型没有真实 token 计费，未知用量保持未知。

演示模式使用确定性的本地 Provider，经过真实 SDK 的模型响应解析、工具执行、审批、事件、会话和取消流程。它用于可重复验收，不评价模型自主编程能力。在线模式使用 `data/model.yaml` 中的真实供应商与模型，可直接提交自己的编程任务；配置已从当前有效配置复制成独立副本，修改它不会改原配置。密钥只在后端，文件与运行数据全部被 Git 忽略。

## 执行边界

宿主没有注册任意 Shell。文件工具逐次限制到当前实验目录，拒绝绝对路径、父目录、隐藏元数据、符号链接和目录连接。用户即使批准越界访问，适配器仍拒绝实际 I/O。

`run_tests` 只执行固定入口 `python -m unittest discover -s tests -v`。它先复制可见项目文件，再用 Docker 只读挂载副本；不挂载原仓库、SDK 状态、模型配置或 Docker socket，不传入模型密钥。容器关闭网络和持久化日志、使用只读根文件系统、删除 Linux capabilities、限制内存/CPU/进程数，允许容量受限的临时内存目录，45 秒后终止。没有 Docker 时明确报错，不在宿主机执行生成代码。工具拒绝和测试失败都作为事件返回，任务完成不等于测试通过。

## 架构

浏览器通过 HTTP 提交操作，通过 SSE 接收后端持久化事件。后端独立 asyncio Task 持续消费 Agent，页面断线不会取消任务。SDK 事件序号被保留为 sdk_sequence，宿主 sequence 跨启动递增；Last-Event-ID/after 用于重放。

一个实验会话一个 Agent 实例与专用 workspace；会话内串行，最多 4 个会话并行。成功后 SDK 推进 follow-up 队列，失败/取消暂停队列。关闭服务先停止任务、清理容器、保存 SDK 会话并释放锁。重启恢复历史，不自动重放中断任务。通过“恢复”继续暂停队列。

主要目录：

- `lab/`：Web API、任务管理、受限工具、演示 Provider。
- `web/`：无需构建的浏览器界面。
- `tests/`：SDK/API 生命周期与隔离检查。
- `scripts/acceptance.py`：真实 SDK + Docker 的端到端验收。
- `vendor/snapshot.json`：固定的 SDK commit。
- `vendor/wheels/`：固定 SDK 安装包，可直接复现。
- `vendor/sdk-src/`：只读来源快照，保留作分析参考，不纳入此实验 Git。
- `data/`：私有配置、实验文件、SDK 会话、Web 事件和验收证据。

## 检查

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts\acceptance.py
```

接口文档： http://127.0.0.1:8765/docs 。验收证据保存在 `data/acceptance.json`；当前验收结论另见 `ACCEPTANCE.md`。



