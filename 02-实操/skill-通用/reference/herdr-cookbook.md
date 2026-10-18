# Herdr 命令速查与坑

> 配套 `../SKILL.md`。**本机版本：herdr 0.9.5**。命令语法以本机二进制为准 —— 拿不准先跑
> `herdr --help`，或把命令组**不带子命令**打一次（`herdr agent` / `herdr pane` / `herdr tab`）。
>
> ⚠️ **别裸跑 `herdr`** —— 那会启动/附上 TUI，把当前会话搞乱。

---

## 0. 门禁：先确认自己在 Herdr 里

```bash
test "${HERDR_ENV:-}" = 1 || { echo "不在 Herdr 里，停手"; exit 1; }
```

不通过就**不要**执行任何 herdr 命令（从外部去操作别的会话是很危险的事）。

确认后，`PATH` 里的 `herdr` 就是在跟**当前会话**说话。

---

## 1. 调用者上下文（herdr 注入的环境变量）

```bash
printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID" "$HERDR_PANE_ID"
# 本机实测：w3 / w3:t1 / w3:p1
```

| 变量 | 含义 |
|---|---|
| `HERDR_WORKSPACE_ID` | 工作区，如 `w3` |
| `HERDR_TAB_ID` | 页签，如 `w3:t1` |
| `HERDR_PANE_ID` | 当前 pane，如 `w3:p1` |
| `HERDR_SOCKET_PATH` | 服务端 socket |
| `HERDR_BIN_PATH` | 二进制绝对路径 |

**优先用 `--current`** 而不是 `$HERDR_PANE_ID` 字面量去指自己。

---

## 2. ID 体系

| 对象 | 形态 | 说明 |
|---|---|---|
| workspace | `w1` | |
| tab | `w1:t1` | 带 workspace 前缀 |
| pane | `w1:p1` | 带 workspace 前缀 |

- **已关闭的 tab/pane ID 不会复用。**
- pane 被移到别的 workspace 后会拿到**新的**带前缀 ID —— 移完要用
  `.result.move_result.pane.pane_id` 继续，别再用旧的。
- **ID 与 agent 名都以"服务端"为界**：两台机器可以都有 `w1:p1`。

---

## 3. 发现类命令（只读）

```bash
herdr workspace list                       # 工作区；含 label / pane_count / agent_status
herdr tab list --workspace "$HERDR_WORKSPACE_ID"
herdr pane current --current
herdr pane list --workspace "$HERDR_WORKSPACE_ID"
herdr pane get <pane_id>
herdr pane layout --pane "$HERDR_PANE_ID"  # ★ 切 pane 前先看这个
herdr pane neighbor --direction right --pane "$HERDR_PANE_ID"
herdr agent list                           # ★ 全景：名字 / kind / 状态 / cwd / pane
herdr agent get <target>
herdr agent explain <target>               # 为什么被判成这个状态（诊断用）
```

> 多数控制命令**返回 JSON**。**从返回值里读 ID 和状态，不要自己猜、不要照抄本文示例。**

---

## 4. 开布局

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
```

| 参数 | 说明 |
|---|---|
| `--current` | 以调用者 pane 为基准（不写就是"焦点 pane"，可能是别人的） |
| `--direction right\|down` | **宽 pane 往右，窄/高 pane 往下** |
| `--ratio FLOAT` | 切分比例 |
| `--cwd PATH` | ★ **保持调用者工作目录**，别让 worker 落到别处 |
| `--env KEY=VALUE` | 给新 pane 注入环境变量 |
| `--no-focus` | ★ **默认用这个**（除非用户要求切过去） |

新 pane ID 在返回的 `.result.pane.pane_id`。

其它布局命令：

```bash
herdr tab create [--workspace ID] [--cwd PATH] [--label TEXT] [--no-focus]
herdr tab rename <tab_id> <label>
herdr tab list [--workspace ID]
herdr tab close <tab_id>
herdr workspace list                     # 需要新工作区时才用，且要先问用户
herdr pane resize --direction right --amount 0.1 --current
herdr pane zoom --current --toggle
herdr pane move <pane_id> --new-tab --label TEXT --no-focus
herdr pane close <pane_id>
```

`tab create` 返回 `.result.tab` 与 `.result.root_pane`（实测：`w3:t2` + `w3:p4`）——
**root_pane 可以直接用来 `agent start`**。

### panes 太多会怎样（本机实测）

**herdr 没有自动平铺** —— 没有 `balance` / `tile` / `equalize` / `auto-scale` 命令，
`config.toml` 里也没有布局项。只有 `split --ratio`（切的时候定）和 `resize`（事后逐个调）。
**所以"先切了再说"必然切碎。**

`w4` 是「一个 tab 里切了 6 刀」的形态：

```
区域 132×45
  p1 66×45 | p2 33×23 | p3 33×22 | p4 33×22 | p5 33×12 | p6 33×11
                                     ↑ 11–12 行高、33 列宽
```

33 列宽**会把 agent 状态行截断** → §5.3.4 的验模型直接失效。
所以：**一个 tab ≤3 个 pane，每个 ≥60×15；再多开 tab**（正文 §5.2.1）。

> ⚠️ **`pane split` 能用默认参数直接执行** —— 别用"省略参数"的方式去试探它会不会执行。

---

## 5. 起 agent

```bash
herdr agent start <name> --kind <KIND> --pane <pane-id>
herdr agent start <name> --kind <KIND> --pane <pane-id> -- <原生参数...>
```

- **`agent start` 不会创建/切分/移动布局** —— 必须**先有一个空闲的交互式 shell pane**，
  且该 shell 在提示符上、前台没有别的命令/编辑器/agent。
- 返回时机：herdr **确认目标 agent 已在同一 pane 里起来并可以交互**之后才返回。
  启动期被卡住则立刻返回 `agent_not_ready`，但**名字仍可用**于 `agent read` / `agent send-keys`。
- 启动超时默认 **30 秒**（`--timeout MS` 可调）。

### 本机支持的 kind

```
pi | claude | codex | gemini | cursor | devin | agy | cline | omp | mastracode |
opencode | copilot | kimi | kiro | droid | amp | grok | hermes | kilo | qodercli |
qwen | letta | maki | muse
```

查实况：`herdr agent`（不带子命令）。

> ⚠️ 上面是 **herdr 能起的全部 kind**，不是"本机允许派的"。
> **本机编排协议只派三个：`claude` / `codex` / `opencode`。**
> `pi` / `omp` / `qodercli` 已停用（2026-10-18，见 `agent-profiles.md` §0.1）——
> 技术上起得来，但**不进阵容、不写进任务书**。

### agent 名的硬约束

正则：**`[a-z][a-z0-9_-]{0,31}`**

- 全小写 ASCII；首字符必须是字母
- 只允许 `a-z` `0-9` `_` `-`
- **≤ 32 字符**
- **不支持中文、大写、空格、点、斜杠**
- 同一服务端内**活着的 agent 名必须唯一**

名字**跟着当前 pane 的占用者走**，agent 退出/被释放/被顶替时名字就清了。
agent 名**不等于"它在前台"** —— 投喂前先看 pane。

### 改名 / 聚焦

```bash
herdr agent rename <target> <new-name>
herdr agent rename <target> --clear
herdr agent focus  <target>
herdr agent attach <target> [--takeover]
```

---

## 5.5 免审批参数（免得一直卡确认框）

用户口径：**干活的 agent 不要老弹审批**。以下参数放在 `agent start` 的 `--` 之后。

| kind | 参数 | 来源 / 等价写法 |
|---|---|---|
| `claude` | `--dangerously-skip-permissions` | 或 `--permission-mode bypassPermissions`（可选值：`acceptEdits` / `auto` / `bypassPermissions` / `manual` / `dontAsk` / `plan`） |
| `codex` | `--dangerously-bypass-approvals-and-sandbox` | 等价组合：`-a never -s danger-full-access`（`-s` 可选值：`read-only` / `workspace-write` / `danger-full-access`；`-a` 可选值：`on-request` / `never`） |
| `opencode` | `--auto` | 自动批准未被显式拒绝的权限。⚠️ **交互模式不接受 `--model`**（只有 `opencode run` 认） |

```bash
# worker：<部门短码>-<名称>-<kind>（§3.2）
herdr agent start qa-java01-claude   --kind claude   --pane w4:p4 -- --dangerously-skip-permissions --model fable
herdr agent start qa-tools01-opencode --kind opencode --pane w4:p6 -- --auto

# 统筹者：档位跟着任务难度走（见正文 §2.0.1）
herdr agent start dev-plan-claude --kind claude --pane w4:p2 -- --dangerously-skip-permissions          # T1 中等
herdr agent start dev-plan-codex  --kind codex  --pane w4:p2 -- --dangerously-bypass-approvals-and-sandbox  # T2 大型

# 每个起完都把 pane 标签设成中文（§3.7）—— 中文只能进标签，不能进 agent 名
herdr pane rename w4:p4 "测试部-java01-claude"
```

### ⚠️ 这不是"加能力"，是"关安全阀"

**Claude 的两个近似开关别用错**：

- `--dangerously-skip-permissions` —— **直接启用**跳过。要的是这个。
- `--allow-dangerously-skip-permissions` —— 只是把"跳过"**变成一个可选模式**，**不默认启用**。
  单独用它，审批照旧弹。别以为带了就关掉了。

- 开了之后 agent 拥有**当前操作系统用户**的全部权限：能删目录、能连生产库、能 `git push`。
- **Pi 的语义和别人不一样**：它本来就没有工具审批（官方 `docs/security.md`：
  *"Project trust does not limit what tool calls can access or affect. After Pi starts,
  enabled tools still use the operating-system permissions of the Pi process."*），
  `--approve` 只是跳过项目信任提示。**别指望 Pi 会帮你把关。**
- **安全网只剩任务书里的边界。** 派活时必须写死：不推根仓远程、不碰别人的 pane、
  不删无备份的东西、不确定就停下回报（正文 §5.3.2）。
- **生产操作照样可以带这些参数**（用户要求别打断），但**必须先拿到 main 的 `[PROD-OK]`**
  —— 授权协议见正文 §5.3.3。**免审批 ≠ 免授权**：一个管"要不要点确认"，一个管"允不允许做"。

---

## 6. 发任务与等待

```bash
herdr agent prompt <target> "<文本>" --wait --timeout 600000
herdr agent wait   <target> [--until STATUS]... [--timeout MS]
herdr agent send-keys <target> esc | ctrl+c | ...
```

`agent prompt` 的行为：
- 尊重 pane 的 **bracketed-paste 模式**，把文本 + 编码回车**作为一次有序提交**发出。
- 返回成功**只证明"写进去了"**，**不证明 agent 开了一轮**。
- Codex on Windows：herdr 会在回车前发一个粘贴边界，所以**不依赖 prompt 长度**。
- 目标正卡在审批/提问对话框时，**直接拒发**并报 `agent_blocked`，一个字节都不写。

`--wait` 的语义（**关键**）：
- 等**第一次**落到 `idle` / `done` / `blocked`。
- 从非工作态发起的 prompt，必须观察到 `working` 或 `blocked` 才算过闸，观察窗口 **5 秒**；
  没观察到 → `agent_prompt_stalled`；调用方 `--timeout` 先到 → `timeout`。
- `timeout` **包含提交时间**。
- **不加 `--timeout`，观察到活动后就是无限等。**
- ⚠️ **它跟的是生命周期状态，不是某一轮** —— agent 本来就在 working 的话，"它当前那轮跑完"就能满足这个等待。

`--until` **只用于状态机场景**（例如等一个已经在跑的 agent 来要输入）：

```bash
herdr agent wait reviewer --until blocked --timeout 120000
```

**普通干活别叠 `--until`**，`--wait` 就够。

---

## 7. 读输出

```bash
herdr agent read <target> --source recent-unwrapped --lines 200
herdr pane  read <pane_id> --source recent --lines 200
```

`--source` 怎么选：

| source | 是什么 | 什么时候用 |
|---|---|---|
| `visible` | 当前视口渲染出来的 | 要看"人眼看到的那一屏" |
| `recent` | 近期渲染输出（含软换行） | 一般查看 |
| `recent-unwrapped` | 近期输出、**软换行已接合** | ★ **日志/转录优先用这个** |
| `detection` | 用于 agent 检测的纯文本底部快照 | 排查"为什么状态判错了" |

- 要颜色/样式当证据时才加 `--format ansi`，否则用文本。
- `--lines N` 是向 herdr 要更多行（含 host scrollback）；备用屏的行不进 scrollback。
- **兜底**：读不到完整回复时，让 agent **把结论写成 Markdown 文件**并只回文件路径，
  再在同机器上读那个文件。⚠️ **这是兜底手段，不要在第一次 prompt 里就要求文件输出。**

---

## 8. 在别的 pane 跑普通命令

```bash
PANE=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus | \
       python -c "import sys,json;print(json.load(sys.stdin)['result']['pane']['pane_id'])")
herdr pane run "$PANE" "pytest -q"
herdr pane wait-output "$PANE" --match "passed" --timeout 120000
herdr pane read "$PANE" --source recent-unwrapped --lines 120
```

- `pane run` 把命令文本和回车**一起排队**；返回成功只表示**已受理**，不代表跑完。
- `pane wait-output` **会先搜一次当前快照** —— 已经存在过的输出也能命中。
- `--match` 是字面子串，`--regex` 是 Rust 正则。
- **不写 `--timeout` 就是无限等。**
- macOS 上 `pane run` / `agent start` 会先检查命令是否超出行输入上限，超了就在排队前拒掉。

---

## 9. 安全与协调规矩

- **后台干活一律 `--no-focus`**，除非用户要求切过去。
- **指定目标用 `--current` / 显式 pane ID / 唯一 agent 名**，不要依赖"当前焦点"（那可能是用户的）。
- **ID 从 JSON 返回值里解析**，不要按侧边栏顺序或示例推。
- ⚠️ **不要关闭不是你创建的 workspace / tab / pane / session**，除非用户明确要求。
  CLI/API 的关闭**不会**继承 TUI 的"最后一个 pane"确认。`workspace close --group`
  会连挂着的 worktree workspace 一起关 —— **永远不要为了绕过 `workspace_group_close_required` 而加上它**。
- `--trust-repository` 只在用户**已核实过该仓库**后用；它不是失败后的常规重试。
- 更新后 client 与 server 版本可能不一致，依赖新特性前先 `herdr status`。
  **"方法不存在"不等于"可以停掉或升级 server"。**
- ⚠️ **绝不在活动会话里跑 `herdr server stop`**，除非用户明确要停掉 server 及其 pane 进程。
- ⚠️ **绝不 kill Herdr 主进程。**
- CLI 的 server 错误是 **stderr 上的 JSON + 退出码 1**；语法错误退出码 **2**。

### 远程机器（`--machine`）

```bash
herdr --machine <label-or-id> agent list
herdr --machine <label-or-id> agent prompt <name> "..." --wait --timeout 120000
```

- 全局前缀**必须一以贯之**（发现和后续命令用同一个）。
- 选择符必须是**已启用的已存档案 ID 或唯一的、大小写敏感的 label**，不是任意 SSH 主机名。
- **不能与 `--session` / `--remote` 混用。**
- 本地 ID 和 `--current` **不能**用来指远程 pane。
- 连接失败**不能证明**改动没生效 —— **重试前先看远程状态**。

---

## 10. 错误码与退出码（本机实测）

**退出码**（2026-10-17 在 herdr 0.9.5 上实测确认）：

| 情况 | 退出码 | 输出在哪 |
|---|---|---|
| 成功 | `0` | stdout 上的 JSON |
| **服务端/业务错误** | **`1`** | ⚠️ **stderr 上的 JSON**（stdout 是空的） |
| **语法错误**（缺参数/参数写错） | **`2`** | stderr 上的 usage |

> ⚠️ 别用管道取退出码 —— `herdr ... | head` 拿到的是 `head` 的退出码，不是 herdr 的。
> 要判成败就把输出重定向到文件再看 `$?`。

**常见错误码**：

| `code` | 触发 | 怎么办 |
|---|---|---|
| `invalid_agent_name` | 名字不符 `[a-z][a-z0-9_-]{0,31}` | **中文名、大写、超 32 字符都报这个**。改成 ASCII slug（见 §5） |
| `agent_name_taken` | 重名 | 消息里**会列出占用者的 pane/workspace/cwd/状态** —— 据此判断是复用还是换名 |
| `agent_not_ready` | 启动期被卡住 | 名字**仍可用** → `agent read` 看它在等什么 |
| `agent_blocked` | 目标正卡在审批/提问对话框 | **一个字节都没发**。先 `agent read` 看清是什么，涉及权限/破坏性操作要问用户 |
| `agent_prompt_stalled` | 提交后 5 秒内没观察到 `working`/`blocked` | ⚠️ **不等于没送达** —— 先 `agent get` + `agent read`，**别盲目重发** |
| `timeout` | 调用方 `--timeout` 先到 | 同上。注意 `--timeout` **包含提交时间** |

实测样例：

```bash
$ herdr agent start 中文名 --kind opencode --pane w3:p1
# stderr: {"error":{"code":"invalid_agent_name","message":"agent name must start with a
#   lowercase letter and contain only lowercase letters, digits, '-' or '_' (1-32 characters)"}}
# 退出码 1

$ herdr agent start rename-java --kind opencode --pane w3:p1
# stderr: {"error":{"code":"agent_name_taken","message":"agent name rename-java is already used;
#   candidates: terminal_id=... pane_id=w4:p4 workspace_id=w4 tab_id=w4:t1
#   cwd=E:\YX\yx-erp status=Idle"}}
```

**发现名字被占时**：先 `herdr agent list` 看那个 agent 在干什么 —— 是**同一个任务的上一个 worker 还活着**
（→ 复用或先让它退出），还是**别的任务撞名**（→ 换一个更具体的 `<task>` 前缀）。

---

## 11. 本机实践样本（可照抄的证据）

2026-10-16 本机 `w4` 工作区在跑的一套编排（`cwd=E:\YX\yx-erp`）：

> 📜 **历史快照** —— 当时还没有部门命名规范。表里 `qodercli` / `omp` / `pi`
> **现已停用**（`agent-profiles.md` §0.1），只作命名规律的证据保留，**别照抄阵容**。

| pane | kind | 名字 | 角色 |
|---|---|---|---|
| `w4:p1` | claude | （未命名） | main |
| `w4:p2` | **codex** | **`planner`** | 统筹 |
| `w4:p3` | claude | `rename-validation` | 验证 |
| `w4:p4` | qodercli | `rename-java` | worker |
| `w4:p5` | omp | `rename-resources` | worker |
| `w4:p6` | pi | `rename-tools` | worker |

可读出的命名规律：**`<task>-<scope>` + 固定 `planner` + `-validation`**。
工作区 label（`芯宇` / `元芯`）用中文，agent 名用 ASCII slug —— 两层各司其职。
