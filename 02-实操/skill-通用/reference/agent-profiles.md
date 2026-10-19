# Agent 能力档案（派活的依据）

> 配套 `../SKILL.md` §2.1。**以下都是 2026-10-17 在本机实测抄下来的**，不是印象。
> 模型接入与 MCP 配置**会变** —— 文末有复验命令，派活前拿不准就重查一遍。

---

## 0. 一览

| agent | kind | 默认模型 | 可提档到 | MCP 服务器 | 一句话特色 |
|---|---|---|---|---|---|
| **Claude Code** | `claude` | `deepseek-flash`（opus/sonnet 槽） | ★ **`fable` 槽 → `deepseek-v4-pro`** | 3 个 | 工具链最全：skill / plugin / hook / 子 agent / worktree |
| **Codex** | `codex` | ★ **`gpt-6.1-sol`** | —（已是最强） | 7 个 | 最强推理 + 自带 `review` 子命令 + 三档沙箱 |
| **OpenCode** | `opencode` | ✅ `deepseek/deepseek-v4-pro`（已固定；不配则落到免费模型） | **只能改配置**（交互模式不收 `--model`） | 有（管理命令） | 自带 `serve`/`api`（可当 HTTP API） |

> **本机的模型只有三档**：`gpt-6.1-sol`（只在 codex）、`deepseek-v4-pro`（只在 claude 的 fable 槽）、
> `deepseek-flash`（其余）。**"DS 档"不等于都一样** —— v4-pro 和 flash 差一个层级。

---

## 0.1 ⛔ 已停用：Pi / OMP / qodercli（2026-10-18）

**软件还装在本机，但不再参与 herdr 编排。** 不进阵容、不派活、不写进任务书。

| agent | 原定位（仅存档，别再据此派活） | 替代 |
|---|---|---|
| **Pi**（`pi`） | 极简 read/bash/edit/write、无工具审批，原用于批量机械改 | **Claude Code** |
| **OMP**（`omp`） | 自带子 agent + `omp find` 语义搜索 + `--plan`/`--slow` 提档 | **Claude Code `--model fable`** |
| **qodercli**（`qodercli`） | 1M 上下文 + `security` 安全扫描 | **Claude Code `--model fable`**（同为 1M 槽） |

- **为什么剔掉**：用户决定精简可派活名单，只留 `claude` / `codex` / `opencode` 三个。
- **效果**：`herdr-audit.py` 的 `KINDS` 已同步收窄 → 用它们起的 agent，
  agent 名里的 `<kind>` 段会被判违规（exit 1）。
- **别因为旧文档又加回来。** 要恢复就先问用户，并把本节、`SKILL.md` §2.1、
  `AGENTS.md` / `CLAUDE.md` 的能力表一起改回去。
- `tools/herdr-status.py` / `herdr-audit.py` 里**保留了它们的状态行解析器**
  —— 只是让"万一真起了"还能读，**不代表允许起**。

---

## 1. 逐个档案

### 1.1 Claude Code（`claude`）

**模型路由（实测）**：走本地代理 `127.0.0.1:15721`，按槽位映射：

| 槽位（`--model`） | 实际模型 |
|---|---|
| `fable` | ★ **`deepseek-v4-pro`**（本机能拿到的 DS 最强） |
| `opus` / `sonnet` / `haiku` | `deepseek-flash` |

> ⚠️ **默认槽不是 fable** —— 想让它聪明，起的时候必须显式 `--model fable`。

#### 1.1.1 怎么查「Claude 槽位 → 实际 DS 模型」（**用户关心的这条**）

本机 Claude Code **不是直连 Anthropic** —— 它走 **cc-switch**（`cc-switch.exe`，
监听 `127.0.0.1:15721`）做供应商路由。三层证据，从静到动：

| 层 | 看什么 | 怎么看 |
|---|---|---|
| **静态配置** | 槽位 → 真实模型名 | `~/.claude/settings.json` 的 `ANTHROPIC_DEFAULT_*_MODEL_NAME` |
| **代理状态** | 当前接的是谁 | `curl -s http://127.0.0.1:15721/status` → `"current_provider":"DeepSeek"` |
| **实际调用** | 每个槽位真跑成了什么 | `~/.cc-switch/cc-switch.db` 的 `proxy_request_logs`（`request_model → model`） |

**第三层最硬**——它是真实发生过的调用记录，不是配置期望值。查法：

```bash
python - <<'EOF'
import os, sqlite3
db = os.path.expanduser('~/.cc-switch/cc-switch.db').replace('\\', '/')
con = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
for req, mdl, n in con.execute(
    "select request_model, model, count(*) n from proxy_request_logs "
    "where request_model is not null and model is not null "
    "group by request_model, model order by n desc limit 20"):
    print("%-32s → %-24s %6d 次" % (req, mdl, n))
EOF
```

实测输出（2026-10-17，累计次数）：

```
claude-opus-4-8      → deepseek-flash          21647 次
claude-opus-5        → deepseek-flash           5673 次
claude-sonnet-4-6    → deepseek-flash           2209 次
claude-opus-4-8      → deepseek-v4-pro           716 次
claude-sonnet-5      → deepseek-flash            227 次
claude-haiku-4-5     → deepseek-flash            189 次
claude-fable-5       → deepseek-v4-pro           121 次
gpt-6.1-sol          → gpt-6.1-sol               708 次   ← codex 是直通
```

**结论与 UI 显示的对应关系：**

| Claude 界面显示 | 实际后端 |
|---|---|
| `[Fable 5]` | ★ **`deepseek-v4-pro`** |
| `[Opus 5]` / `[Sonnet 5]` / `[Haiku]` | `deepseek-flash` |

> ⚠️ **cc-switch 还管着 codex / opencode / gemini / grokbuild** ——
> 换供应商是**应用级**的动作，改之前先想清楚会影响哪些 agent。
> `providers` 表里每个 app 都有各自的 `settings_config`，存着具体的槽位映射。

**MCP**：`playwright` · `ms-office-mcp` · `remoteshell`（3 个）

**结构能力强项**
- skill / plugin / hook / 自定义子 agent（`--agents` JSON）
- git worktree、云端会话、Chrome 集成、`/` 斜杠命令
- 非交互模式 `-p/--print`，可接 `--output-format stream-json`

**适合**
- **T1 策划**（拆解清楚、主要靠工具链把活串起来）
- **组级组长**（单域内拆给 worker、收口）
- 需要 MCP 的活：浏览器自动化、Office 文档、远程机器
- 需要再往下派子 agent 的活
- 探索性、要来回试的工作

**不适合**
- 需要强推理定方案的（那是 codex）
- 纯批量机械替换（它要派也得走 herdr，不如直接给它一个边界清楚的任务书）

**起法**
```bash
herdr agent start dev-plan-claude --kind claude --pane <id> -- \
  --dangerously-skip-permissions --model fable
```

---

### 1.2 Codex（`codex`）

**模型**：`gpt-6.1-sol`，`model_reasoning_effort = low`（配置里可调高）

**MCP**（7 个）：`mcp-video` · `mcp_server_mysql` · `ms-office-mcp` · `playwright` · `remoteshell` · `cua_repl`

**特色子命令**
- `codex exec` —— 非交互执行（脚本化）
- ★ `codex review` —— **专门的非交互代码评审**，这是别家没有的
- `codex agents` —— 浏览本机所有会话
- `codex mcp` / `plugin` / `app-server` / `remote-control`

**沙箱三档**：`read-only` · `workspace-write` · `danger-full-access`
**审批两档**：`on-request` · `never`

**适合**
- **T2 策划**（要拿主意、要裁决）
- **任何需要"判断这算不算做对了"的活** —— 验证裁决
- 代码评审：直接用 `codex review`，比自己写 prompt 让别的 agent 看更稳
- 跨模块权衡、方案对比

**不适合**
- 重工具链编排（claude 更强）
- 批量机械活（贵且慢）

---

### 1.3 OpenCode（`opencode`）

**版本**：v2.0.32（`opencode --version`）

**模型**（`opencode models` 实测）：
- `deepseek/deepseek-flash`
- ★ **`deepseek/deepseek-v4-pro`**
- 一批 `opencode/*` 免费模型（`beam-free` / `big-pickle` / `nemotron-*` / `glm-*` …）

> ✅ **2026-10-17 已把默认模型固定为 `deepseek/deepseek-v4-pro`**（改的是
> `~/.config/opencode/opencode.json` 的 `model` 字段）。实测状态行
> `Build auto · DeepSeek V4 Pro DeepSeek`，一句话任务 **1.9 秒**回完（$0.01）。
>
> ⚠️ **不配 `model` 时它会落到内置的免费模型**（实测 `Nemotron 3.5 Super VL Free`，
> 慢到 4 分钟跑不完一句「只回复收到」）。换机器/重装后要重新配。

**免审批**：`--auto`（"Auto-approve permissions that are not explicitly denied"）

**⚠️ 最大的限制：交互模式不接受 `--model`**

```bash
opencode --auto --model deepseek/deepseek-flash      # ✗ Unrecognized flag: --model
opencode run --model deepseek/deepseek-flash "..."   # ✓ 只有 run 子命令认
```

所以 **herdr 起它时无法指定模型**。换模型的唯一办法：改
`~/.config/opencode/opencode.json` 的 `model` 字段（格式 `provider/model#variant`）。

**herdr 集成（已装，完整）**
- `~/.config/opencode/plugins/herdr-agent-state.js`（`HERDR_INTEGRATION_ID=opencode`，v13）
- 状态上报：`permission.asked` / `question.asked` → `blocked`
- 实测：`agent start` → `idle`；`agent prompt` → `working`；`agent read` / `send-keys` 正常

**配置能力**（`~/.config/opencode/opencode.json`，schema 支持）
`model` · `instructions` · `skills` · `mcp` · `plugins` · `subagent_depth`（默认 1）· `permissions` · `tools` · `agents`

**其它**
- 读 `AGENTS.md`（二进制内含该字符串）
- 非交互：`opencode run [--model p/m] [--format json]`
- 服务化：`serve` / `api` / `service` / `acp`（**可当 HTTP API 用**）

**适合**
- **组级组长**（已固定 v4-pro 档，够用；但不能随任务切档）
- 探索性任务、用免费模型跑量大的低价值活
- 需要「把 agent 当 HTTP API 调」的场合（`serve` / `api`）

**不适合**
- **需要按任务切档位的角色**（策划 / 验证）—— 档位固定在配置里，起不了 `--model`；
  真要换只能改配置再重开。
- 需要图片输入的任务 —— `deepseek-v4-pro` **只支持文本**；要图片得把 `model` 换成
  `deepseek/deepseek-flash`（它是 text + image）。

---

## 2. 派活矩阵（策划者照着挑）

| 任务类型 | 首选 | 为什么 | 备选 |
|---|---|---|---|
| **定方案 / 裁决 / 判断"做对没"** | **codex** | 唯一 gpt-6.1-sol | claude `--model fable` |
| **T1 策划（拆解已清楚，主要是派活收口）** | **claude `--model fable`** | 工具链全 + DS 最强档 | codex |
| **组级组长（单域拆给 worker、收口）** | **claude `--model fable`** | 工具链全 + DS 档 | opencode（已固定 v4-pro） |
| **代码评审** | **codex**（`codex review`） | 有专用非交互评审子命令 | claude `--model fable` |
| **批量机械改（一批文件同一规则）** | **claude** | 工具链全，把「只改这些文件」写死即可 | opencode |
| **边界明确的局部改动** | **claude** | 上下文够用、工具面全 | opencode |
| **全仓/超长上下文理解** | **claude `--model fable`** | fable 槽是 **1M 上下文** | opencode |
| **需要浏览器 / Office / 远程机器** | **claude** | 这 3 个 MCP 都在它这儿 | codex（也有） |
| **需要数据库 / 视频 / CUA** | **codex** | 这些 MCP 只在 codex | — |
| **语义检索定位代码** | **claude** | grep + 子 agent 足够 | — |
| **安全扫描** | **codex**（`codex review`） | 无专用扫描子命令了 | claude |
| **需要再往下派子 agent** | **claude** | 内置子 agent | — |
| **验证（与作者不同源）** | **与作者不同 kind 的 DS agent** | 见下（**不用 codex**） | — |
| **需要把 agent 当 HTTP API 调 / 免费模型跑量** | **opencode** | 自带 `serve`/`api` + 免费模型 | — |
| **需要按任务切模型档位** | ⚠️ **别用 opencode** | 档位固定在配置里，交互模式不收 `--model` | claude / codex |

**验证者的选择（重要）：⚠️ codex 不跑测试。**

codex 额度有限，它的高价值活是**定规则、拿主意、裁决** —— 不是照着标准逐条执行。

| 环节 | 谁做 |
|---|---|
| **写验收标准** | **planner（codex）** 在任务书里写清楚 |
| **执行验证** | **DS agent**，且**与作者不同 kind**（作者 `claude` → 验证者 `opencode`；作者 `opencode` → 验证者 `claude`） |
| 验证结果有争议 / 高风险裁决 | planner（codex） |

理由：**换 kind 就已经换了实现与工具链**，能覆盖相当一部分盲点；
codex 留给定标准和最终裁决。只有**判断错了代价极大**（数据迁移、生产改动、不可逆操作）
时，才让 codex 亲自复核。

---

## 3. 模型提档速查

| 想要 | 怎么拿 |
|---|---|
| **本机最强推理** | `codex`（默认就是 `gpt-6.1-sol`） |
| **DS 最强** | `claude --model fable` |
| **快 / 便宜 / 批量** | `claude` 默认槽（flash）· `opencode`（已固定 v4-pro） |
| **超长上下文（1M）** | `claude` 的 fable 槽 |

> ⚠️ **别默认 claude 就是"DS 档"** —— 它有 v4-pro 的槽，但**要显式 `--model fable`** 才拿得到。

---

## 4. 启动后怎么确认模型（**实测**）

**带了参数不等于生效。** 起完 agent、发任务之前，先读状态行：

```bash
herdr agent read <name> --source visible --lines 6
```

2026-10-17 在本机逐个起了一轮，真实看到的样子：

| kind | 状态行原文（截取） | 模型在哪 |
|---|---|---|
| `codex` | `GPT-6.1-Sol low · E:\YX\yx-erp` | 行首，模型名 + reasoning effort |
| `claude` | `[Opus 5 (1M context)]` | 行首，但 **是槽位别名** |
| `opencode` | `Build auto · DeepSeek V4 Pro DeepSeek` | 中间：`<模式> · <模型>`（未配 model 时会显示免费模型名） |

### ⚠️ 坑 1：`claude` 显示的不是真实模型

状态行显示的是 **Anthropic 槽位别名**，后端由代理映射：

| 状态行显示 | 实际后端 |
|---|---|
| `[Fable 5 (1M context)]` | ★ **`deepseek-v4-pro`** |
| `[Opus 5 …]` | `deepseek-flash` |
| `[Sonnet 5 …]` | `deepseek-flash` |
| `[Haiku …]` | `deepseek-flash` |

> **看到 `Opus 5` 就说明你起了个 flash 档的 claude** —— 忘了 `--model fable`。
> 现场证据：本机 `w4` 的 `rename-validation`（claude）状态行是 `[Opus 5 (1M context)]`，
> 按上面的映射它就是 `deepseek-flash`。

### ⚠️ 坑 2：窄 pane 会截断状态行

状态行里模型名常在行尾或行中，pane 太窄就被切掉（本机 132 列时就见过截断）。
验的时候开宽，或 `herdr pane zoom --current --on` 看一眼再 `--off`。

### 对不上怎么办

```bash
herdr agent rename <name> --clear     # 先释放名字
herdr pane close <pane-id>            # 再关 pane
# 重新起，带上正确的参数
```

**别带着错模型往下跑** —— 分派全部按档位设计，模型错了整套逻辑就失效了。

---

## 5. 复验命令（配置变了就跑一遍）

```bash
# 模型
grep -E '^model|reasoning_effort' ~/.codex/config.toml
python -c "import json,os;print(json.load(open(os.path.expanduser('~/.claude/settings.json')))['env'])"
python -c "import json,os;print(json.load(open(os.path.expanduser('~/.config/opencode/opencode.json'))).get('model'))"
opencode models      # opencode 可用模型

# MCP
grep -E '^\[mcp_servers\.' ~/.codex/config.toml
python -c "import json,os;print(list(json.load(open(os.path.expanduser('~/.claude.json'))).get('mcpServers',{})))"

# 正在跑什么
herdr agent list

# 各家能力（以本机二进制为准）
codex --help ; claude --help ; opencode --help
```

⚠️ 上面读 `~/.claude/settings.json` 会带出 `ANTHROPIC_AUTH_TOKEN` —— **别把输出贴到任何地方**。
只要模型名的化：`grep -o '"ANTHROPIC_DEFAULT_[A-Z_]*MODEL[_NAME]*": *"[^"]*"' ~/.claude/settings.json`。
