# OpenHands × DeepSeek 集成技术文档

> 范围：本项目（TeleGen / Fullstack-WebGen）中 OpenHands 的使用方式，以及它如何与 DeepSeek API 配合。
> 本文为只读分析，未修改任何代码、配置、依赖或 Git 状态。

---

## 1. 一句话总结

本项目以 **OpenHands CLI（headless 模式，v1.16.0）** 作为代码生成与修复的 Agent 运行时，通过 **环境变量 + `--override-with-envs`** 把 DeepSeek（`deepseek-v4-flash` / `deepseek-v4-pro`）注入为 Agent 的 LLM；同时另有一条**直连 DeepSeek 的 OpenAI 兼容 API**（不经 OpenHands），用于遥测日志注入和 brief 压缩。

---

## 2. 全局架构

```
launch_multi_docker.py            ← 多 Docker 容器并行启动入口
    └── run_project_worker.sh     ← 容器内 worker 入口
        └── run_full_pipeline_llm_injection.sh   ← 主编排
            ├── Phase 1: run_batch.py
            │   ├── 1a. OpenHands 代码生成 (DeepSeek-V4)        ← OpenHands CLI
            │   ├── 1b. LLM 遥测注入 (DeepSeek API 直连)         ← httpx/requests
            │   └── 1c. WebVoyager v1 测试 + 日志收集
            ├── Phase 2: optimize_batch_results.py
            │   ├── 2a. 遥测 brief 压缩 (LLM, DeepSeek API 直连) ← requests
            │   ├── 2b. OpenHands 可观测修复 (DeepSeek-V4)        ← OpenHands CLI
            │   └── 2c. WebVoyager v2 测试 + 质量门
            └── Phase 3: WebVoyager 自动评估 (Qwen3.5-Plus)
```

**关键分工（双模型路由）：**

| 角色 | 模型 | 协议 | 是否经过 OpenHands |
|---|---|---|---|
| 代码生成（Phase 1a） | DeepSeek-V4 Flash/Pro | OpenAI 兼容（LiteLLM `deepseek/`） | ✅ 是（CLI） |
| 可观测修复（Phase 2b） | DeepSeek-V4 Flash/Pro | OpenAI 兼容（LiteLLM `deepseek/`） | ✅ 是（CLI） |
| 遥测日志注入（Phase 1b） | DeepSeek-V4 | OpenAI 兼容（直连） | ❌ 否（httpx） |
| brief 压缩（Phase 2a） | DeepSeek-V4 | OpenAI 兼容（直连） | ❌ 否（requests） |
| WebVoyager 浏览/评估 | Qwen3.5-Plus | OpenAI 兼容（dashscope） | ❌ 否 |

模型路由与名字归一化集中在 [model_config.py](openhands_integration/model_config.py)。

---

## 3. OpenHands 的使用方式

### 3.1 版本与安装

- **安装方式**：pip 安装，在 [docker/pipeline.Dockerfile](docker/pipeline.Dockerfile) 中通过构建参数固定版本：
  ```dockerfile
  ARG OPENHANDS_PIP_SPEC=openhands==1.16.0
  RUN python3 -m pip install -c /tmp/openhands-constraints.txt "$OPENHANDS_PIP_SPEC" ...
  ```
- **OpenHands 版本**：`1.16.0`
- **约束文件** [docker/openhands-constraints.txt](docker/openhands-constraints.txt)：仅 pin OpenTelemetry 系列（用于运行时插桩遥测），并不锁定 LiteLLM/Pydantic 版本（跟随 openhands 1.16.0 的依赖）。
- **启动入口**：[launch_multi_docker.py](openhands_integration/launch_multi_docker.py) 的 `--openhands-pip-spec` 可覆盖该版本（[launch_multi_docker.py:225](openhands_integration/launch_multi_docker.py#L225)）。

### 3.2 调用形态：CLI headless（非 SDK / 非 agent-server）

本项目用的是 **完整 OpenHands CLI**，不是 Software Agent SDK、不是 `RemoteConversation`、也不是独立 agent-server。Agent 为 CLI 默认的 **CodeActAgent**（不在代码里显式 import/构造 Agent 类，而是由 `openhands` 命令在内部加载）。

**生成阶段**（[run_batch.py:1210-1216](openhands_integration/run_batch.py#L1210)）：

```python
cmd = [
    "openhands",
    "--headless",
    "--always-approve",
    "--override-with-envs",
    "-f", str(task_file.resolve()),
]
```

**修复阶段**（[dynamic_repair_pipeline.py:948-955](openhands_integration/dynamic_repair_pipeline.py#L948)）：

```python
cmd = [
    "openhands",
    "--headless",
    "--always-approve",
    "--override-with-envs",
    "-f", str(paths.openhands_task_file.resolve()),
]
```

参数含义：

| 标志 | 作用 |
|---|---|
| `--headless` | 无 UI、非交互的批处理模式 |
| `--always-approve` | 自动批准所有 action（不等待人工确认），保证容器内可无人值守运行 |
| `--override-with-envs` | **用环境变量覆盖 OpenHands 的 config.toml 配置**（这是 DeepSeek 接入的关键开关） |
| `-f <task.txt>` | 把任务 prompt 作为初始用户消息喂给 Agent |

> 项目仓库内 **没有 `config.toml`**（已全局搜索确认），所有 OpenHands 配置完全通过环境变量在运行时注入。

### 3.3 子进程执行与超时

- **生成**：`subprocess.run(..., timeout=1800)`，30 分钟超时（[run_batch.py:1256-1263](openhands_integration/run_batch.py#L1256)）；超时后仍会扫描历史 workspace 挽救已产出代码。
- **修复**：`_run_stream()` 流式子进程（[dynamic_repair_pipeline.py:266](openhands_integration/dynamic_repair_pipeline.py#L266)），实时把 stdout/stderr 转写到日志，同时捕获全文；超时用 `killpg(SIGKILL)` 杀整个进程组，避免管道死锁。默认 `DEFAULT_MAX_ITERATIONS = 24`（[dynamic_repair_pipeline.py:33](openhands_integration/dynamic_repair_pipeline.py#L33)），可由 `optimize_batch_results.py --max-iterations` 覆盖（默认 24，[optimize_batch_results.py:123](openhands_integration/optimize_batch_results.py#L123)）。
- 修复阶段额外设置 `WORKSPACE_BASE`、`OPENHANDS_MAX_ITERATIONS`、`MAX_ITERATIONS`、`TTY_INTERACTIVE=1`（[dynamic_repair_pipeline.py:958-961](openhands_integration/dynamic_repair_pipeline.py#L958)）。

### 3.4 完成判定与会话指标采集

OpenHands 退出后，本项目**不是**依赖 SDK 的事件流判定完成，而是：

1. 从 stdout 用正则提取 **Conversation ID**（[run_batch.py:856-869](openhands_integration/run_batch.py#L856)）：
   ```
   Conversation ID\s*:\s*([0-9a-fA-F-]{32,36})
   ```
2. 映射到本地持久化目录 `~/.openhends/conversations/<uuid>/`（[run_batch.py:872-890](openhands_integration/run_batch.py#L872)，同时兼容连字符/紧凑两种 UUID 形式）。
3. 读取 `base_state.json` 与 `events/*.json`，解析其中的 `stats.usage_to_metrics.*.accumulated_token_usage`，得到 `prompt_tokens / completion_tokens / cache_read / cache_write / reasoning_tokens / accumulated_cost / token_usages(len=llm_call_count) / max_iterations`（[run_batch.py:911-974](openhands_integration/run_batch.py#L911)）。
4. **完成判定逻辑**（[dynamic_repair_pipeline.py:972-983](openhands_integration/dynamic_repair_pipeline.py#L972)）：
   - `returncode != 0` → `failed`
   - `llm_call_count == 0` 且 stdout 含 `AuthenticationError`/`login fail` → `auth_error`
   - `llm_call_count == 0`（其他）→ `no_llm_calls`
   - 否则 → `success`

   > 即"做了 0 次 LLM 调用就退出"会被识别为异常（鉴权或无动作），这是关键的健康检查点。

### 3.5 实际运行时输出样貌

样例日志 [batch_runs/.../gen_000001/openhands_stdout.log](batch_runs/gemini3flash_full_101/project_000001/gen_000001/openhands_stdout.log) 显示 CLI 的标准输出序列：

```
Initializing agent...
✓ Agent initialized with model: <provider>/<model>
Agent is working
Agent finished
───── CONVERSATION SUMMARY ─────
Number of agent messages: 21
Last message sent by the agent: ...
```

（注：该样例批次实际加载的是 `gemini/gemini-3-flash-preview`，由 `.env.gemini3flash` 切换而来；默认配置走 DeepSeek。）

### 3.6 一次完整执行链路（生成路径）

```
task prompt(项目需求 + UI 任务) 
  → 写入 task.txt
  → 构造 env(LLM_MODEL/PROVIDER/BASE_URL/API_KEY/EXTRA_BODY)
  → openhands --headless --always-approve --override-with-envs -f task.txt
  → CodeActAgent 初始化(LiteLLM 读 env 路由到 DeepSeek)
  → Agent 内部: LLM 请求 → 工具/action 解析 → Terminal/FileEditor 执行 → 工作区写入
  → Agent finished / CONVERSATION SUMMARY
  → 从 ~/.openhands/conversations/<id>/ 读取 usage 指标
  → 扫描 workspace 把生成的 backend/frontend 拷出
```

---

## 4. DeepSeek 如何接入 OpenHands（Agent 的 LLM）

### 4.1 注入的环境变量（核心）

由 `_build_openhands_llm_env()` / run_batch 内联逻辑统一构造。DeepSeek 分支（[dynamic_repair_pipeline.py:138-163](openhands_integration/dynamic_repair_pipeline.py#L138)、[run_batch.py:1220-1242](openhands_integration/run_batch.py#L1220)）：

| 环境变量 | 取值 | 说明 |
|---|---|---|
| `LLM_API_KEY` | `$DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | DeepSeek 官方 OpenAI 兼容端点（可由 `DEEPSEEK_API_BASE_URL` 覆盖） |
| `LLM_MODEL` | `deepseek/deepseek-v4-flash` | **provider 前缀 + 模型名**，由 `to_deepseek_model()` 拼接（[model_config.py:23-29](openhands_integration/model_config.py#L23)） |
| `LLM_PROVIDER` | `deepseek` | LiteLLM provider |
| `LLM_EXTRA_BODY` | `{"enable_thinking": false}` | **关闭 DeepSeek 的 thinking/推理模式** |
| `TTY_INTERACTIVE` | `1` | 让 Rich/CLI 在非交互终端下也能正常输出 |

### 4.2 模型名归一化（[model_config.py](openhands_integration/model_config.py)）

| 函数 | 作用 | 示例 |
|---|---|---|
| `to_openhands_model()` | 给 OpenHands 用，缺省加 `openai/` 前缀 | `qwen3.5-plus` → `openai/qwen3.5-plus` |
| `to_deepseek_model()` | 给 OpenHands 用，缺省加 `deepseek/` 前缀 | `deepseek-v4-flash` → `deepseek/deepseek-v4-flash` |
| `to_direct_api_model()` | 给直连 API 用，**剥离** provider 前缀 | `deepseek/deepseek-v4-flash` → `deepseek-v4-flash` |
| `apply_unified_model()` | 用一个原始模型名统一回填 `PIPELINE_MODEL/DEEPSEEK_MODEL/LLM_MODEL/LLM_PROVIDER` 等 | — |

### 4.3 provider 前缀 / 协议 / base URL 形态

- **provider 前缀**：`deepseek/`（LiteLLM 内置的 deepseek provider）。
- **协议**：OpenAI 兼容（`/chat/completions`），**非** Anthropic 兼容。
- **base URL**：`https://api.deepseek.com`（不带 `/v1`，DeepSeek 官方端点本身兼容 OpenAI 路径）。
- **thinking 模式**：通过 `LLM_EXTRA_BODY={"enable_thinking": false}` 关闭。
- **temperature / stream / top_p / tool_choice**：**未显式设置**，沿用 OpenHands 1.16.0 / LiteLLM 对 deepseek provider 的默认值（CLI headless 默认流式，CodeActAgent 默认启用 native tool calling）。
- **模型**：默认 `deepseek-v4-flash`（Flash）；pro 批次用 `deepseek-v4-pro`（见 README 实验数据表）。

### 4.4 多 provider 优先级回退

`_build_openhands_llm_env()` 的优先级（[dynamic_repair_pipeline.py:133-205](openhands_integration/dynamic_repair_pipeline.py#L133)）：

1. **DeepSeek**（项目默认，文本生成/修复）→ `deepseek/<model>`
2. 已存在的 `LLM_API_KEY` + `LLM_MODEL`
3. **Qwen**（dashscope，OpenAI 兼容）→ `openai/<model>`
4. **WebVoyager** 凭据回退
5. **OpenAI** 凭据回退 → `openai/gpt-4o`

> 生成阶段 [run_batch.py:1220-1251](openhands_integration/run_batch.py#L1220) 还额外支持 **Gemini** 分支：若模型名含 `gemini`，有 `TRANSIT_API_BASE_URL` 则走 `openai/` 中转站，否则走 LiteLLM 原生 `gemini/` provider。

---

## 5. DeepSeek 直连 API（不经 OpenHands）

除了作为 Agent 的 LLM，DeepSeek 还被**直接以 HTTP 调用**用于两个轻量文本任务，绕开 OpenHands 的 Agent 开销。

### 5.1 遥测注入：[llm_log_injector.py](openhands_integration/llm_log_injector.py)

`LLMClient` 类（[llm_log_injector.py:102](openhands_integration/llm_log_injector.py#L102)）：

- 模型名经 `to_direct_api_model()` 剥前缀（[llm_log_injector.py:108](openhands_integration/llm_log_injector.py#L108)），即 `deepseek-v4-flash`。
- 端点：`POST {base_url}/chat/completions`（[llm_log_injector.py:152](openhands_integration/llm_log_injector.py#L152)）。
- 请求体：`model / messages / max_tokens=8000 / temperature=0.1`（[llm_log_injector.py:142-147](openhands_integration/llm_log_injector.py#L142)）。
- 头：`Authorization: Bearer <key>`。
- 客户端：`httpx.Client(timeout=180s)`，429 指数退避、5xx 重试（[llm_log_injector.py:155-208](openhands_integration/llm_log_injector.py#L155)）。
- **去 think 块**：`re.sub(r"<think>[\s\S]*?</think>", "", content)`（[llm_log_injector.py:174](openhands_integration/llm_log_injector.py#L174)）。
- 常量 `DISABLE_THINKING_EXTRA_BODY = {"enable_thinking": False}`（[llm_log_injector.py:44](openhands_integration/llm_log_injector.py#L44)）。
- 设计要点：不让模型重写整文件，而是返回结构化 patch operations（`replace` 精确匹配），本地应用 + 语法检查。

### 5.2 brief 压缩：[llm_telemetry_extractor.py](openhands_integration/llm_telemetry_extractor.py)

`_chat_completion_once()`（[llm_telemetry_extractor.py:521](openhands_integration/llm_telemetry_extractor.py#L521)）：

- 请求体：`model / messages / temperature=0.0 / top_p=0.9 / stream=False`（[llm_telemetry_extractor.py:535-540](openhands_integration/llm_telemetry_extractor.py#L535)）。
- 客户端：`requests.post`，多 key 候选回退（`_api_key_candidates`），带超时自适应 `_compute_timeout()`。
- 同样走 `/chat/completions`、Bearer 鉴权、剥前缀模型名。

---

## 6. 配置来源

| 文件 | 作用 |
|---|---|
| [.env](.env)（git-ignored） | 实际密钥与模型；默认 DeepSeek 做生成/修复，Qwen 做 WebVoyager |
| [.env.example](.env.example) | 模板：`DEEPSEEK_API_KEY / DEEPSEEK_MODEL=deepseek-v4-flash / DEEPSEEK_API_BASE_URL=https://api.deepseek.com`、Qwen、`CONTAINER_CLI` |
| `.env.gemini3flash` | 切到 Gemini 的实验配置（生成对应 `gemini3flash_full_101` 批次） |
| [docker/pipeline.Dockerfile](docker/pipeline.Dockerfile) | 容器构建，`openhands==1.16.0`，装 chromium/docker.io/node 等 |
| [docker/openhands-constraints.txt](docker/openhands-constraints.txt) | 仅 pin OpenTelemetry（运行时插桩） |

`.env` 暴露的变量名（**仅变量名，不含值**）：`DEEPSEEK_API_KEY / DEEPSEEK_API_BASE_URL / DEEPSEEK_MODEL / QWEN_* / WEBVOYAGER_* / GEMINI_API_KEY / TRANSIT_API_KEY / LLM_API_KEY / LLM_MODEL / LLM_PROVIDER / LLM_BASE_URL / LLM_EXTRA_BODY`。

> `.env` 中 `LLM_*` 一组默认留空，注释明确："除非有意覆盖上面的拆分路由，否则保持为空"。即 DeepSeek/Qwen 路由由代码按优先级动态拼装，不靠静态 `LLM_*`。

---

## 7. 关键设计要点（给读者/审稿人）

1. **OpenHands 作为黑盒 CLI**：项目不直接用 Agent SDK，而是把 OpenHands 当作一个"输入任务文本 → 输出工作区改动"的命令行工具，通过 stdout 正则 + 本地 conversation 持久化来回收指标。这样做的好处是与 OpenHands 内部解耦，升级/替换 Agent 只需改 pip spec 与命令行参数。
2. **`--override-with-envs` 是 DeepSeek 接入的核心**：无需 config.toml，全部 LLM 配置由环境变量在每次 subprocess 调用时注入，便于在同一容器内对不同项目/批次切换 provider。
3. **DeepSeek 用 OpenAI 兼容协议**，provider 前缀 `deepseek/`（LiteLLM 原生支持），base URL `https://api.deepseek.com`，并显式 `enable_thinking=false` 关闭推理模式（Agent 场景追求确定性动作输出）。
4. **双通道用 DeepSeek**：Agent 通道（经 OpenHands/LiteLLM）负责代码生成与修复；直连通道（httpx/requests）负责轻量结构化文本任务（日志 patch、brief），各自独立调参（temperature 0.1 vs 0.0）。
5. **完成判定有防呆**：`llm_call_count == 0` 会被标为 `auth_error` / `no_llm_calls`，能立即暴露"Agent 启动但没真正调用模型"的故障（例如鉴权失败、provider 路由错误）。

---

## 8. 速查：OpenHands CLI 接入 DeepSeek 的最小配方

```bash
# 1) 安装
pip install openhands==1.16.0

# 2) 准备 task.txt（任务 prompt）

# 3) 注入 DeepSeek 环境变量
export LLM_API_KEY=$DEEPSEEK_API_KEY
export LLM_BASE_URL=https://api.deepseek.com
export LLM_MODEL=deepseek/deepseek-v4-flash        # provider 前缀不可少
export LLM_PROVIDER=deepseek
export LLM_EXTRA_BODY='{"enable_thinking": false}' # 关闭 thinking
export TTY_INTERACTIVE=1

# 4) 运行
openhands --headless --always-approve --override-with-envs -f task.txt

# 5) 指标回收：stdout 里的 Conversation ID → ~/.openhands/conversations/<id>/
```

---

## 附：相关文件索引

| 关注点 | 文件:行 |
|---|---|
| OpenHands 生成调用 | [run_batch.py:1210-1263](openhands_integration/run_batch.py#L1210) |
| 生成阶段 DeepSeek env 构造 | [run_batch.py:1220-1252](openhands_integration/run_batch.py#L1220) |
| OpenHands 修复调用 | [dynamic_repair_pipeline.py:948-963](openhands_integration/dynamic_repair_pipeline.py#L948) |
| 多 provider env 优先级 | [dynamic_repair_pipeline.py:133-205](openhands_integration/dynamic_repair_pipeline.py#L133) |
| 流式子进程 `_run_stream` | [dynamic_repair_pipeline.py:266](openhands_integration/dynamic_repair_pipeline.py#L266) |
| 完成判定 | [dynamic_repair_pipeline.py:972-983](openhands_integration/dynamic_repair_pipeline.py#L972) |
| Conversation ID 提取 | [run_batch.py:856-869](openhands_integration/run_batch.py#L856) |
| 会话指标解析 | [run_batch.py:911-974](openhands_integration/run_batch.py#L911) |
| 模型名归一化 | [model_config.py](openhands_integration/model_config.py) |
| DeepSeek 直连（注入） | [llm_log_injector.py:102-217](openhands_integration/llm_log_injector.py#L102) |
| DeepSeek 直连（压缩） | [llm_telemetry_extractor.py:521-585](openhands_integration/llm_telemetry_extractor.py#L521) |
| Phase2 编排入口 | [optimize_batch_results.py:331-340](openhands_integration/optimize_batch_results.py#L331) |
| Docker / 版本 | [docker/pipeline.Dockerfile](docker/pipeline.Dockerfile) |
| Prompt 模板 | [openhands_integration/prompts/](openhands_integration/prompts/) |
