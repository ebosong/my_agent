# My Agent · HarnessX

轻量、可追踪的 Python Agent 执行框架。HarnessX 将模型调用、工具执行、上下文管理与会话记录组织为完整的任务循环，适用于本地自动化、文件处理和 Agent 原型开发。

使用 Python 3.10+，运行时仅依赖标准库，通过支持工具调用的 OpenAI 兼容 Chat Completions 接口连接模型。仓库名称为 `my_agent`，Python 包和命令行名称为 `harnessx`。

## 核心能力

- **任务循环**：支持单轮多个工具调用、统一错误反馈，以及步数、估算费用和运行时间限制。
- **文件操作**：读取、写入、列目录与精确文本编辑；校验唯一匹配和重叠，保留 UTF-8 BOM 与换行格式。
- **代码执行**：通过子进程运行 Python 或 Shell，支持超时处理和输出截断。
- **会话追踪**：JSONL 追加记录消息、工具调用与执行结果，支持可读轨迹和会话恢复。
- **上下文压缩**：保留系统指令、原始任务和最近完整交互轮次，支持模型摘要与规则摘要。
- **按需技能加载**：提供技能索引，通过工具加载 `SKILL.md` 正文。

## 快速开始

```bash
git clone https://github.com/ebosong/my_agent.git
cd my_agent
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

Linux / macOS：

```bash
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

编辑 `.env`，填写服务地址、实际可用的模型名称与 API 密钥：

```dotenv
HARNESSX_BASE_URL=https://api.deepseek.com
HARNESSX_MODEL=your-model-name
HARNESSX_API_KEY=your-api-key
```

客户端会在 `BASE_URL` 后追加 `/chat/completions`。如果服务要求 `/v1` 前缀，请将其包含在 `BASE_URL` 中。所选模型需要支持 `tools` 工具调用协议。

```bash
harnessx doctor --no-model
harnessx run "创建 hello.py，输出 Hello, world!，运行并检查结果" --workspace ./workspace
```

`harnessx` 也可写成 `python -m harnessx`。运行 `harnessx doctor` 会额外发送一次模型工具调用探测请求，产生相应 API 用量。

## 命令行

### 运行任务

```bash
harnessx run "整理目录中的文本文件并生成摘要" --workspace ./workspace --max-steps 20
```

启用上下文压缩：

```bash
harnessx run "分析工作区中的代码" --workspace ./workspace --context-limit 6000 --summarizer llm
```

限制可用工具：

```bash
harnessx run "阅读文件并给出说明" --workspace ./workspace --tools read_file,list_dir
```

`submit` 始终保留。可用 `--no-edit` 禁用精确编辑，或用 `--no-skills` 禁用技能工具。完整参数见 `harnessx run --help`。

### 查看与恢复会话

会话文件位于 `<workspace>/.harnessx/sessions/`，任务结束时打印具体路径：

```bash
harnessx trace ./workspace/.harnessx/sessions/session_YYYYMMDD_HHMMSS.jsonl
harnessx resume ./workspace/.harnessx/sessions/session_YYYYMMDD_HHMMSS.jsonl --task "继续完成剩余工作"
```

恢复时重建消息链与压缩状态，为中断后缺失的工具结果补充中断说明；不会回滚已执行的文件修改或命令。

任务以 `Submitted` 或 `FinalAnswer` 结束时退出码为 `0`，其他运行停止原因返回 `1`；缺少密钥等部分前置检查错误返回 `2`。

## 配置

配置来源依次为命令行参数、环境变量、工作区 `.env`、源码仓库 `.env` 和内置默认值。推荐统一使用 `HARNESSX_` 前缀；`MYAGENT_` 为兼容前缀，同一配置同时存在两种前缀时优先使用 `HARNESSX_`。

主要配置项及内置默认值：

- `HARNESSX_BASE_URL`、`HARNESSX_MODEL`、`HARNESSX_API_KEY`：模型连接配置。
- `HARNESSX_MAX_STEPS=30`：最大执行步数。
- `HARNESSX_MAX_COST=0.5`：估算费用上限。
- `HARNESSX_MAX_SECONDS=600`：任务运行时间限制。
- `HARNESSX_TOOL_TIMEOUT=60`：单次工具超时秒数。
- `HARNESSX_REQUEST_TIMEOUT=120`：单次模型请求超时秒数。
- `HARNESSX_CONTEXT_LIMIT=0`：压缩触发阈值，`0` 表示关闭。
- `HARNESSX_KEEP_TURNS=2`：压缩时原样保留的最近交互轮次。
- `HARNESSX_SUMMARIZER=llm`：摘要方式，可选 `llm` 或 `rule`。
- `HARNESSX_PRICE_IN=1.0`、`HARNESSX_PRICE_OUT=2.0`：每百万输入、输出 token 的估算单价。

费用默认值只是占位估算，请按所用服务设置。预算在任务循环中检查，正在执行的请求或工具可能使最终用量超过阈值，因此不能将其视为服务端硬性配额。

## 工具与技能

内置工具：`read_file`、`write_file`、`list_dir`、`edit_file`、`run_python`、`run_shell`、`submit`、`list_skills`、`load_skill`。

`edit_file` 按原始文本精确替换：

```json
{
  "path": "app.py",
  "edits": [
    {"old_text": "TIMEOUT = 30", "new_text": "TIMEOUT = 60"}
  ]
}
```

每项 `old_text` 必须在原文件中恰好出现一次；缺失、重复或编辑范围重叠时拒绝写入。全部校验通过后执行原子替换。

在工作区创建 `skills/<name>/SKILL.md` 可添加领域知识：

```markdown
---
name: project-guide
description: 项目的目录约定与交付要求。
---

# 项目约定

在此编写需要 Agent 遵循的具体说明。
```

启动时只将名称与描述加入提示词，正文由 `load_skill` 按需读取。工作区技能优先于源码仓库下的同名技能。本仓库不附带实验用技能。

## 项目结构

```text
src/harnessx/
├── cli.py           # 命令行入口与组件组装
├── config.py        # 配置与运行参数
├── agent.py         # 任务循环、预算与停止条件
├── model.py         # 模型协议与 HTTP 客户端
├── context.py       # 上下文估算与摘要压缩
├── events.py        # JSONL 事件日志与轨迹格式化
├── session.py       # 会话恢复与中断修复
├── prompts.py       # 系统提示词
└── tools/           # 工具协议、注册与内置实现
.env.example         # 不含密钥的配置模板
pyproject.toml       # 包元数据与 CLI 安装配置
LICENSE              # Apache-2.0 许可证
```

发布仓库仅包含主框架与使用文档；课程材料、实验结果、测试目录、验证脚本、参考代码和运行日志不纳入发布。

## 使用边界

文件工具限制路径位于工作区内，但 Python 与 Shell 工具以当前用户权限运行，**不构成安全沙箱**。它们能够访问用户可访问的文件与网络；执行不可信任务时，应自行提供容器或其他隔离环境。

上下文 token 数为启发式估算。规则摘要不保留完整工具输出，可能丢失早期事实；模型摘要会产生额外调用与费用，也不能保证无信息损失。会话日志可能包含任务内容和文件内容，应按业务数据管理。`.env`、会话目录和默认工作区已加入 Git 忽略规则。

## 参考与致谢

设计参考了 `SWE-agent/mini-swe-agent` 的执行限制与进程管理思路，以及 `badlogic/pi-mono` 的精确编辑和上下文压缩思路。本项目使用 Python 独立实现，代码曾在 AI 助手协助下编写与迭代。

## 许可证

沿用仓库原有的 [Apache License 2.0](LICENSE)。
