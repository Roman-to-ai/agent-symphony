---
name: herdr-orchestration
description: "用 Herdr 编排多 agent 协作（main/planner/worker/verifier）。⚠️ **main 只派活、不干活**：简单任务 → 派 1 个 worker；中等任务 → 派 **Claude Code(DS 档) 当 planner**；大型任务 → 派 **Codex(最强 GPT) 当 planner**。含分级判据（T0/T1/T2）、按能力档位分派、agent 命名规范（须为 [a-z][a-z0-9_-]{0,31}）、herdr 调用规范与交接模板，跨 Claude Code / Codex / OpenCode 通用。需要 HERDR_ENV=1。"
---

# Herdr 多 Agent 编排协议

> **这份文件是跨 agent 通用的**（Claude Code / Codex / OpenCode 都照同一套规矩办）。
> 你是这套编排里的**某个角色**——先看 §1 确认自己是哪个，再只看与自己相关的小节。
>
> ⛔ **可派活的 agent 只有三个：`claude` / `codex` / `opencode`。**
> **Pi / OMP / qodercli 已于 2026-10-18 停用** —— 软件还装着，但**不派活、不进任何阵容**。
> 见 `reference/agent-profiles.md` §0.1。

**配套文件**

| 文件 | 什么时候看 |
|---|---|
| `reference/agent-profiles.md` | **派活前** —— 各 agent 的模型槽位 / MCP / 特色命令 / 派活矩阵 |
| `reference/herdr-cookbook.md` | 要敲 herdr 命令、或遇到报错/卡住 |
| `reference/templates.md` | 要写委托 / 任务书 / 验证报告 / 汇总 —— **直接抄** |
| `tools/herdr-layout.py` | 要把 tab 切成规整网格（herdr 没有 tile，得自己算） |
| `tools/herdr-status.py` | 查看某个工作区的编排状态表：页面 / pane / agent / kind / 状态 / 尺寸 / 模型 |

**📦 位置：全 agent 共用一份实体**

唯一真源 = **`.agents/skills/herdr-orchestration/`**（Agent Skills 标准位置）。

| agent | 怎么找到它（2026-10-17 实测） |
|---|---|
| **opencode** | ✅ 原生扫描 —— `opencode run` 能列出 `herdr-orchestration` |
| **Codex** | 二进制含 `.agents/skills` 路径（未实跑） |
| **Claude Code** | ⚠️ 2.1.302 **不扫项目级 `.agents/skills`**（同一个探针放 `.claude/skills` 能被发现、放 `.agents/skills` 不能）→ 用 **junction** 指过去 |

```
.claude/skills/herdr-orchestration  ──junction──▶  .agents/skills/herdr-orchestration/
```

- 新克隆的机器：`sh tools/link-skills.sh`（幂等；`--unlink` 只删链接）
- ⚠️ **git 会跟随 junction 当成第二份文件** → `.gitignore` 已挡住
  `.claude/skills/herdr-orchestration`。**别删那条**。
- 为什么用 junction 不用 symlink：Windows 建 symlink 要管理员权限/开发者模式，junction 不要。

> ⚠️ **关于「Claude Code 从 2.1.277 起兼容 `.agents/skills`」这个说法** ——
> 2026-10-17 在本机（2.1.302）查证：**兼容的是「导入」，不是「原地共享」**。
> `claude import [codex|gemini|cursor]` / `/import` 会把别的 agent 的配置**复制**进
> Claude Code，`.agents/skills` 是这条迁移链路里出现的路径之一。
> 二进制里另有 `synced skills`（79 处），那是**从 claude.ai 账号云端同步**的技能，与 `.agents` 无关。
> 实测：同一份最小探针放 `.claude/skills` 立即被发现，放 `.agents/skills`（项目级/用户级都试过）都不被发现。
> **所以要么用 junction（本方案，一份实体），要么 `claude import`（会多一份拷贝）。**

---

**按角色速跳**

| 你是 | 先读 |
|---|---|
| 还没决定要不要编排 | **§2.0 判档** |
| 决定要编排了，但不确定 T1 还是 T2 | **§2.0.1（claude 统筹 vs codex 统筹）** |
| `main` | §2.0 → §2.0.2（一眼活）→ §2.0.3 → §4 → §8 |
| `planner`（T1=claude / T2=codex） | §2 → §4 阶段②③ → §5.3.1 / §5.3.3 → §6 |
| 起完 agent 要确认模型对没对 | **§5.3.4** |
| `worker` | §6（任务书要求）→ §8 |
| `verifier` | §8 → `reference/templates.md` §3 |

---

## 1. 角色模型

四个角色，各司其职。**同一个人可以顺序扮演多个角色，但不能同时**。

| 角色 | 谁来做 | 干什么 | 不干什么 |
|---|---|---|---|
| **main** | Claude Code | 接需求、**判档（§2.0）**、**派活**、向用户汇报（唯一出口） | **不亲自干活** —— 默认派 worker。唯一例外是"一眼活"（§2.0.2） |
| **统筹**（planner） | **T1：Claude Code `--model fable`（→ deepseek-v4-pro）**<br>**T2：Codex（gpt-6.1-sol）** | 出方案 → 分派 → 收口 → 安排验证 → 裁决 → 汇总 | 不亲自写业务代码（除非任务极小且无人可派） |
| **worker**（执行） | Claude Code / OpenCode | 领到**边界清晰**的任务，干完交回**可验证的产物** | 不扩大范围、不替别人做决定 |
| **verifier**（验证） | **与作者不同 kind 的 DS agent**（`claude`/`opencode`） | 按 planner 写好的验收标准独立复核，给**有证据的**结论 | 不修产物；**也不该是 codex**（见 §2.1） |

### 铁律

0. **先判档（§2.0）。** 判档决定"派谁"，不是"main 干不干"。
1. **main 不亲自干活。** 默认派 worker/planner 去做；**唯一例外是"一眼活"**（§2.0.2）。
   保持 main 空闲，才能随时接新需求、随时向用户汇报。
2. **main 是唯一对用户说话的 agent。** 其它角色**一律不直接找用户**。
3. **同一个任务只能有一个统筹者**：T1 是 Claude Code 的 planner，T2 是 Codex 的 planner。
   worker 不接"你看着办"这类任务——边界不清就退回去问。
4. **verifier 必须与作者不同 kind。** 谁写的谁不验（同实现会重复同一个盲点）。
   **验证者用 DS agent，不是 codex** —— codex 的额度留给定标准与裁决。
5. **能力优先，不等于"用满五个 agent"。** 只派适合的，没人适合就统筹者自己干。

---

## 2. 先分级，再分派

> **核心原则：main 不干活，只派活。** 判档决定的是「派给谁」，不是「main 干不干」。
> 唯一的例外是"一眼活"（§2.0.2）—— 起 agent 比直接做还慢的那种。

### 2.0 三档：按任务规模选统筹者

| 档 | 判据 | 统筹者 | 执行者 |
|---|---|---|---|
| **T0 简单** | ① 一个 worker 一次能做完，**不需要拆**<br>② 改动 ≤ 3 个文件<br>③ 只读 / 查询 / 解释 | **无 —— main 直接派** | **1 个 worker** |
| **T1 中等** | ① 要拆 **2–3** 个子任务<br>② **方案明确**（你能一遍写清每份任务书）<br>③ 子任务互不影响<br>④ 预计 30 分钟 – 2 小时 | **`planner` = Claude Code `--model fable`**（→ deepseek-v4-pro） | 2–3 worker（+ 按需 verifier） |
| **T2 大型** | ① **≥3** 个子任务或依赖复杂<br>② 跨模块且**相互影响**<br>③ 要**拿主意**（方案不止一种）<br>④ 需**裁决**（方案冲突 / worker 结果冲突）<br>⑤ 预计 **> 2 小时** 或 **> 20 步**<br>⑥ 用户说「这个重要 / 别搞坏」 | **`planner` = Codex（最强 GPT 档）** | 2–4 worker + **verifier（必须）** |

**默认从 T0 开始。** 判据没命中就不要升级。

> ⚠️ **T0 也派 worker，不自己干。** 起一个 worker 的固定开销（起 pane + 启动 + 交互）
> 通常只有十几秒，换来的是 main 全程空闲 —— 能随时接新问题、随时汇报进度。
> 唯一例外见 §2.0.2。

#### 2.0.1 为什么 T1 用 Claude Code、T2 用 Codex？

统筹者的档位**跟着任务难度走**，不是"越强越好"：

| | **T1 统筹 = Claude Code `--model fable`（→ deepseek-v4-pro）** | **T2 统筹 = Codex（gpt-6.1-sol）** |
|---|---|---|
| 统筹的性质 | **执行性协调**：拆解已经清楚，主要是派活、盯进度、收口、按模板校验产物 | **决策性统筹**：要在几种走法之间权衡、要裁决冲突、要判断"这算不算做对了" |
| 适合 | 方案明确、子任务互不影响 | 方案有分歧、依赖复杂、风险高 |
| 工具链 | 工具最全（skill / MCP / 子 agent），检查产物、跑验证命令更顺手 | 推理深度优先 |
| **核心判据** | **你能一遍把每份任务书写清楚** | 写的时候**还在犹豫边界 / 依赖 / 先后** |

> **"拆不清楚"是方案问题，不是执行力问题** —— DS 档的 worker 补不上，必须升到 T2。

#### 2.0.2 T0 的唯一例外：一眼活

**如果起 agent 比直接做还慢，就直接做。** 判据：**一条命令就出结果**。

| 算"一眼活"，main 直接做 | 不算，要派 worker |
|---|---|
| `netstat` 查端口、`tasklist` 查进程 | 要改文件 |
| 读一个文件、`git status` / `git log` | 要跑构建 / 测试 |
| 查一条记录（单条 SQL） | 要批量改、要跨多个文件 |
| 回答"这个配置在哪" | 任何要多轮的活 |

做完在汇报里说明「这条我自己查的」—— 让用户知道没走编排。

#### 2.0.3 T0 / T1 的执行要点

**T0（main 直接派 1 个 worker，不设 planner）**

1. 开**部门页** tab（§5.2.1）→ 起 worker（§5.3，**带 §5.3.1 免审批参数**）→ 设中文标签
2. 发自包含任务书（§6，抄 `templates.md` §2）—— **哪怕只有一个 worker，任务书也要自包含**
3. `--wait` 收产物 + `agent read` 读回执 + 自己核一遍
4. 汇报

**T1（main 派 `dev-plan-claude`，由它再派 worker）**

1. **在 main 自己的 tab 里开统筹位**（§5.2.1，`--pane "$HERDR_PANE_ID"`）→
   起 `dev-plan-claude --kind claude -- --dangerously-skip-permissions --model fable` → 设标签
   （⚠️ **必须带 `--model fable`**，默认槽是 flash；**不要新开 tab 放「主控占位」**）
2. 按 `templates.md` §1 给委托（四件事写全），**并注明「这是 T1：你来统筹」**
3. 等 planner 的汇总（§4 阶段⑦ 的格式，`agent wait` + `agent read`）
4. 汇报（抄 `templates.md` §4 的三段式）

> ⚠️ **T1 的 planner 是另一个 Claude Code agent，不是 main 自己。**
> main 不兼任统筹 —— 保持空闲，才接得住用户的新问题。
> 规范一条不省：§3 命名、§6 自包含任务书、§5.3.1 免审批参数。
> §5.3.3 生产授权里，**`[PROD-OK]` 仍由 main 签发**，planner 只负责往下传。

### 2.1 能力档位与派活依据

> 📇 **完整档案：`reference/agent-profiles.md`** —— 每个 agent 的模型槽位、MCP 服务器、
> 特色子命令、适合/不适合、以及一张**派活矩阵**（任务类型 → 首选 → 理由 → 备选）。
> **派活前先看它，别凭印象。**

一句话版：

| agent | 档位 | 一句话 |
|---|---|---|
| **Codex** | ★ **最强 GPT**（`gpt-6.1-sol`） | 定方案、裁决、**代码评审**（专用的 `codex review`） |
| **Claude Code** | DS 档（⚠️ **`--model fable` 才拿到 `deepseek-v4-pro`，默认槽是 flash**） | **T1 统筹**、工具链活（浏览器 / Office / 远程 MCP） |
| **OpenCode** | DS（已固定 `deepseek-v4-pro`；⚠️ **交互模式不收 `--model`**，换档只能改配置） | 当 HTTP API 用（`serve`/`api`）、固定档位的常规活 |

> ⛔ **可派活的只有这三个（`claude` / `codex` / `opencode`）。**
> **Pi / OMP / qodercli 已停用**（2026-10-18）—— 软件还装着，但**不进任何阵容、不写进任务书**。
> 派活时不要再考虑它们；档案见 `reference/agent-profiles.md` §0.1。

**判据**：**档位高的做判断，档位低的做执行；同档再看工具面和上下文。**

> ⚠️ **codex 只做高价值的事，不跑执行。**
> 它的额度有限 —— 用来**拆活、定规则、写验收标准、裁决**；
> **写代码、跑测试、逐条核**一律交给 DS agent。
>
> 具体到验证环节：**验收标准由 planner（codex）写进任务书，执行验证的是另一个 DS agent**
> （与作者不同 kind）。只有"判错了代价极大"时，才让 codex 亲自复核。

> ⚠️ **本机的模型只有三档**：`gpt-6.1-sol`（只在 codex）、`deepseek-v4-pro`（只在 claude 的 fable 槽）、
> `deepseek-flash`（其余）。**"DS 档"不等于都一样。**
>
> ⚠️ 模型与 MCP 配置**会变** —— 派活前用 `reference/agent-profiles.md` §4 的复验命令重查，
> **别照抄本文**。

### 2.2 分派判据（T1 / T2 内的统筹者用）

1. **这活需要"拿主意"吗？** → 需要：planner 自己干 或 派给 Codex 档。
2. **这活是"照方案执行"吗？** → 是：派给 DS 档 worker。
3. **有几个能独立完成、互不依赖的子任务？** → 有几个就开几个 worker。**串行能过就别并行**。
4. **有没有哪个 agent 特别适合？** 例：需要 MCP / skill 能力 / 浏览器 / Office → Claude Code；要当 HTTP API 调 → OpenCode。
5. **没人是明显更优的？** → 别为了"用上"而派。planner 自己干，或派给最闲的那个。

> ⚠️ **并行是有代价的**：多个 worker 改同一个仓库会互相踩。**同一文件/同一模块的任务必须串行或明确划分所有物**。

### 2.3 常见场景 → 档位与阵容

| 场景 | 档 | 统筹者 | 阵容 |
|---|---|---|---|
| 看端口 / 查进程 / 读一个文件 / `git status` | **一眼活** | — | **main 直接做**（§2.0.2） |
| 改一个 bug / 小重构 / 加个字段 | **T0** | — | 1 个 worker |
| 解释代码、查资料（要多轮） | **T0** | — | 1 个 worker |
| 跑测试 / 构建 / 批量重命名 / 全库扫描 | **T0** | — | 1 个 worker |
| 写一份文档 / 整理资料 | **T0** | — | 1 个 worker |
| **2–3 个模块的常规改动**（方案明确、互不影响） | **T1** | **claude** | planner + 2–3 worker |
| **一批文件 / 表按同一规则批量改** | **T1** | **claude** | planner + 2–3 worker |
| **交付物机械生成**（改脚本跑出 xlsx/docx） | **T1** | **claude** | planner + 1–2 worker |
| **小范围数据修补 / 补字段**（路径明确） | **T1** | **claude** | planner + 1–2 worker + verifier |
| **跨模块重构 / 换框架 / 改名迁移** | **T2** | **codex** | planner + 2–3 worker + verifier |
| **数据迁移 / ETL / 对账** | **T2** | **codex** | planner + worker + verifier（**逐条对数，不能只比行数**） |
| **交付物生成但口径有分歧** | **T2** | **codex** | planner + worker + verifier |
| **生产运维 / 发布** | **T2** | **codex** | planner + worker + verifier + **`[PROD-OK]`**（§5.3.3） |
| **技术选型 / 多方案对比** | **T2** | **codex** | planner(codex) 主判 + 2 worker 分头调研 + verifier 交叉核 |

> **拿不准 T1 还是 T2** → 用 §2.0.1 的判据：**你能一遍把每份任务书写清楚吗？**
> 能 → T1（claude 统筹）；写的时候还在犹豫 → T2（codex 统筹）。

### 2.4 升降级信号（干到一半发现判错了）

**往上升：**

- worker 回报"这个得拆成几块，一块做不完" → **T0 → T1**
- 拆的时候发现**子任务互相影响** → **T1 → T2**
- 干着干着发现**要拿主意**（不止一种走法） → **T1 → T2**，让 codex 定方案
- 发现**错了不容易发现**（要人验才知道对不对） → 升一档，并加 verifier
- 用户说"这个比较重要 / 别搞坏" → 直接上 **T2**

**T1 → T2 的具体信号（换更强的统筹者）：**

- 边界说不清（谁改哪块划不开）
- 两个子任务的改动会互相影响
- worker 回报"按你这个描述做不了，得先决定 X" —— 那是**方案问题**，不是执行力问题
- 已经写好的 plan / 任务书**别扔**，直接交给 codex planner 当委托材料，省一轮

**往下减：**

- 拆完发现**只有一个子任务** → 退回 T0，**别起 planner**
- 好几个 worker 都在等同一个文件 → 串行化，减少 agent 数
- 子任务是"跑个命令看看" → 一眼活，main 直接做（§2.0.2）

> ⚠️ **降级不是失败。** 拆完发现不必拆，说明判得准；硬凑出几个 agent 才是浪费。

---

## 3. 命名规范（**硬约束，别自己发明**）

### 3.1 ⚠️ 先说冲突：herdr 的 agent 名**不收中文**

想要的 `测试部-test01-claude` —— **作为 agent 名会直接被拒**（2026-10-17 实测）：

```
{"error":{"code":"invalid_agent_name",
 "message":"agent name must start with a lowercase letter and contain only
            lowercase letters, digits, '-' or '_' (1-32 characters)"}}
```

中文、大写、超过 32 字符，全会被拒。所以**部门名分两处写**：

- **agent 名** → ASCII slug（机器寻址用）
- **pane / tab 标签** → 中文（给人看）

### 3.2 三层命名

| 层 | 格式 | 例子 | 谁看 | 字符限制 |
|---|---|---|---|---|
| **agent 名** | `<dept>-<name>-<kind>` | `qa-test01-claude` | 机器 | `[a-z][a-z0-9_-]{0,31}`，**≤32** |
| **pane 标签** | `<部门中文>-<名称>-<kind>` | `测试部-test01-claude` | 人 | **无限制** |
| **tab 标签** | 部门中文 / `<项目> · 主视角` | `测试部` | 人 | **无限制** |

**长度预算**：`dept(2–4) + '-' + name(2–10) + '-' + kind(2–8)` → 最坏 24 字符，够用。

### 3.3 部门短码表（**唯一真源；新部门加一行**）

| 部门 | slug | 部门 | slug |
|---|---|---|---|
| 测试部 | `qa` | 采购部 | `buy` |
| 开发部 | `dev` | 仓储部 | `wh` |
| 运维部 | `ops` | 生产部 | `mfg` |
| 数据部 | `data` | 关务部 | `cus` |
| 产品部 | `pm` | 财务部 | `fin` |

- 表里没有的部门：**2–4 个 lowercase 字母**，全机唯一，**加进上表**再用。
- ⚠️ **别用拼音全拼** —— `gongyinglianguanlibu` 这种一长就把 32 字符吃光。

### 3.4 `<kind>` 段固定用 herdr 的 kind 名

`claude` / `codex` / `opencode` —— 和 `herdr agent start --kind` 一致。
**只认这三个**；`pi` / `omp` / `qodercli` 已停用（§2.1）。
看名字就知道该按哪套能力去理解它（见 `reference/agent-profiles.md`）。

### 3.5 角色专属名

| 角色 | agent 名 | pane 标签 |
|---|---|---|
| **main** | `main`（或省名，由用户直接开） | `主控` |
| **统筹** | `<dept>-plan-<kind>`，如 `dev-plan-claude` | `<部门>-统筹-<kind>` |
| **worker** | `<dept>-<name>-<kind>`，如 `qa-test01-claude` | `<部门>-<名称>-<kind>` |
| **verifier** | `<dept>-<name>-verify` | `<部门>-<名称>-验证` |

> ⚠️ **多个任务并行时**统筹名会撞。用序号区分：`dev-plan1-claude` / `dev-plan2-claude`，
> pane 标签写清是哪个任务（`开发部-统筹-重命名`）。
>
> ⚠️ 老约定里的固定名 `planner`（本机 `w4` 在用）**已被本规范取代** —— 新起的统一按部门格式。

### 3.6 示例

| 场景 | agent 名 | pane 标签 |
|---|---|---|
| 测试部第 1 个 claude worker | `qa-test01-claude` | `测试部-test01-claude` |
| 测试部第 2 个 opencode worker | `qa-test02-opencode` | `测试部-test02-opencode` |
| 开发部的统筹 | `dev-plan-claude` | `开发部-统筹-claude` |
| 生产部的验证者 | `mfg-check01-verify` | `生产部-check01-验证` |
| main | `main` | `主控` |

### 3.7 起名时一次设两处

```bash
herdr agent start qa-test01-claude --kind claude --pane <pane-id> \
  -- --dangerously-skip-permissions --model fable
herdr pane rename <pane-id> "测试部-test01-claude"
```

- **起名之前先 `herdr agent list` 查重**（重名报 `agent_name_taken`，会告诉你谁占着）。
- 部门页开好后，**tab 标签也设成部门中文**：`herdr tab rename <tab_id> "测试部"`。

---

## 4. 完整工作流

> 📌 **下面这张图是 T1 / T2 的流程** —— 两者的差别**只在 planner 用哪个模型**：
> **T1 = `--kind claude`（DS 档）**，**T2 = `--kind codex`（最强 GPT）**。其余完全一样。
>
> **T0 没有 planner**：main 直接执行 ②③④⑤ 派给 **1 个 worker**，没有①⑦两步。

```
用户
 │  提需求
 ▼
main (Claude Code) ──────────────┐
 │  ① 复述需求 + 委托 + 指定档位  │ ⑥ 最终汇报（唯一出口）
 ▼                               │
planner ◄────────────────────────┘
 │   T1: claude（DS）   T2: codex（最强 GPT）
 │  ② 出方案（写进文件，不只嘴上说）
 │  ③ 按能力分派 → 开 pane、起 worker、发任务
 │  ④ 收 worker 产物（等 done + 读回执）
 │  ⑤ 安排 verifier（与作者不同源）→ 收验证结论
 │     └─ 不通过 → 回 ③ 让原作者或换人修 → 再验
 │  ⑦ 裁决 + 汇总
 ▼
main ──► 用户
```

### 阶段 ① main 委托

main **不拆任务**，只把"要什么"讲清楚。委托必须含四件事：

1. **目标**：要达成什么（可判定的）
2. **验收标准**：怎么算做对了
3. **边界**：不能碰什么（哪些目录/文件/系统）
4. **回报要求**：什么时候、以什么形式回报

然后用 herdr 把 planner 拉起来（见 §5.1），把委托发给它。

### 阶段 ② planner 出方案

**方案要落成文件**，不能只在对话里说 —— worker 是全新进程，看不到你的上下文。

推荐落在项目里的临时目录，例如 `<项目>/.orchestration/<task>-plan.md`。
方案至少写清：**拆成几个子任务 · 各自的验收标准 · 派给谁 · 为什么派给它 · 依赖顺序**。

### 阶段 ③ planner 分派

对每个子任务：
1. **先判是不是生产操作**（判据见 §5.3.3 的表）。是 → **必须有 main 的 `[PROD-OK]`**，否则回问 main，不要派。
2. `herdr pane split` 开一个 pane（见 §5.2）
3. `herdr agent start <task>-<scope> --kind <kind> --pane <id> -- <免审批参数>`（见 §5.3、§5.3.1）
4. `herdr pane rename` 设中文标签
5. `herdr agent prompt <name> "<自包含任务书>" --wait --timeout <ms>`（见 §5.4、§6）。
   生产任务要把 `[PROD-OK]` **原样抄进任务书**。

### 阶段 ④ 收产物

`--wait` 返回不等于活干完了（见 §7 陷阱）。收产物要**三件齐**：

```bash
herdr agent get   <name>                              # 状态/是否 interactive_ready
herdr agent read  <name> --source recent-unwrapped --lines 200   # 它的回执
# 再自己独立核一遍产物（文件/测试/接口），别只信它的自述
```

### 阶段 ⑤ 验证

**验证者是独立 agent，不是 planner 自己，也不是作者。** 派发方式同 ③，命名 `<task>-validation`。

验证任务书要**给出判据**，而不是"看看对不对"：原文照抄**验收标准** + 让 verifier 输出**逐条的通过/不通过 + 证据**（命令、输出、文件路径行号）。

**验证不通过**：planner 决定"回原作者修" 还是 "换人重做"，修完**重新验证**（不能只修不验）。

### 阶段 ⑥⑦ 裁决与回报

planner 汇总时**必须区分三件事**：
- **已验证通过的**（附验证者与证据）
- **未验证/验证不通过的**（说明卡在哪）
- **没做的**（说明为什么没派 —— 比如没有合适的 agent）

然后 `herdr agent prompt main "..."` 把汇总发给 main。**main 再转述给用户，并如实转达 planner 说的"没做/没验"部分**，不许美化。

---

## 5. herdr 命令规范

> 完整命令手册与本机踩过的坑：`.agents/skills/herdr-orchestration/reference/herdr-cookbook.md`

### 5.0 每次都先做的门禁

```bash
test "${HERDR_ENV:-}" = 1 || { echo "不在 Herdr 里，停手"; exit 1; }
herdr --help | head -3          # 确认 CLI 版本（本机 0.9.5）
```

**不在 Herdr 环境里就不要执行任何 herdr 命令。**

### 5.1 拉起 planner

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
# 从返回 JSON 取 .result.pane.pane_id

# T1（中等）→ claude（DS 档）
# ⚠️ 必须带 --model fable —— 默认槽是 deepseek-flash，fable 才是 deepseek-v4-pro
herdr agent start dev-plan-claude --kind claude --pane <pane-id> -- \
  --dangerously-skip-permissions --model fable
# T2（大型）→ codex（最强 GPT，默认就是 gpt-6.1-sol）
herdr agent start dev-plan-codex  --kind codex  --pane <pane-id> -- --dangerously-bypass-approvals-and-sandbox

herdr pane rename <pane-id> "统筹 · <任务名>"
herdr agent prompt dev-plan-claude "<委托书>" --wait --timeout 300000
```

> ⚠️ 委托里**必须写明档位**（"这是 T1 / T2"），planner 才知道自己该按哪套标准收口。

### 5.2 开 pane

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
```

- **宽 pane 往右切，窄/高 pane 往下切**。先看 `herdr pane layout --pane "$HERDR_PANE_ID"` 再决定。
- **别连着同方向切很多刀** —— 会切出没法用的窄条。
- **`--no-focus` 是默认选择**（除非用户明确要求切过去看）。
- **`--cwd "$PWD"`** 保持和调用者同一工作目录，别让 worker 落在别处。

#### 5.2.1 ★ 页面划分：**主视角页 + 部门页**

**herdr 不会自动平铺** —— 没有 `balance` / `tile` / `auto-scale`，`config.toml` 也没有布局项。
只有 `split --ratio`（切的时候定比例）和 `resize`（事后逐个调）。
**"按区域自动划分"必须自己算** → 用助手 `tools/herdr-layout.py`（见 §5.2.2）。

**页面划分（硬规矩）**

| 页面 | 放什么 | 上限 | tab 标签 |
|---|---|---|---|
| **主视角页** | **main 自己所在的 tab** + 各任务的**统筹者** | **1 + 3** | **main 那个 tab，不新建** |
| **部门页**（每部门一个） | 该部门的 agent | **6** | 部门中文名（`测试部`） |

> ⚠️ **主视角页就是 main 自己所在的 tab —— 不要另建。**
>
> **main 不是"另起的占位 pane"**，它就是**发起编排的那个 agent 自己**，
> 也就是 `$HERDR_PANE_ID` 所指的那个 pane（用户正在对话的窗口）。
>
> ❌ **反例（踩过）**：新开一个 workspace → 新 tab → 把一个空 pane 标成「主控（占位）」，
> 再把统筹者开在它旁边。那是**虚构的 main** —— 用户看不到真正的对话窗口，
> 也违背"只有 main 对用户说话"。**main 只有一个，就是调用者。**
>
> 正确做法：**在 main 自己的 pane 上 split**，统筹者开在它旁边。

**主视角页的排法** —— main 占左半边，统筹者在右半边**竖排**：

```
132×45
┌──────────────┬──────────────┐
│              │ 统筹1  66×15 │
│              ├──────────────┤
│  main 66×45  │ 统筹2  66×15 │
│              ├──────────────┤
│              │ 统筹3  66×15 │
└──────────────┴──────────────┘
```

- **统筹者 ≤3** → 同页（3 个时每格刚好 15 行，是下限）
- **统筹者 >3** → **另开一页「统筹者」**，用 grid 模式排；主视角页只留 main

**怎么切（main 自己执行）**：

```bash
# 从 main 自己的 pane 出发 —— 注意是 --pane "$HERDR_PANE_ID"，不是新 tab 的 root
python -I .agents/skills/herdr-orchestration/tools/herdr-layout.py \
  --pane "$HERDR_PANE_ID" --count 4 --mode main
# 打印 3 个统筹位；左半边就是你（main）现在这个 pane
```

**部门页的排法** —— 2 列均衡：

| 部门人数 | 每格尺寸 | 说明 |
|---|---|---|
| 1 | 132×45 | 独占 |
| 2 | 66×45 | 左右 |
| 3 | 66×45 + 66×22 ×2 | 左 1 + 右 2 |
| 4 | 66×22 ×4 | 2×2 |
| 5 | 66×15 ×3 + 66×22 ×2 | 左 3 + 右 2 |
| 6 | 66×15 ×6 | 2×3 |
| **>6** | — | **分页**：`测试部(1)` / `测试部(2)` |

> **为什么部门卡 6**：再多就只能分 3 列 → 44 列宽，**低于 60，状态行会被截断**，
> 连模型都验不了（§5.3.4）。

#### 5.2.2 用助手一次切到位

```bash
S=.agents/skills/herdr-orchestration/tools/herdr-layout.py

# ── 主视角页：**就在 main 自己的 tab 里切，不新建 tab** ──
# main + 3 个统筹者 = 4 格。左半边就是 $HERDR_PANE_ID 本身（你，main），
# 打印出的 3 个是统筹位。
COORD=$(python -I "$S" --pane "$HERDR_PANE_ID" --count 4 --mode main)

# ── 部门页：测试部 5 个 agent（共 5 格）──
JSON=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$PWD" \
        --label "测试部" --no-focus)
T2=$(echo "$JSON" | python -c "import sys,json;print(json.load(sys.stdin)['result']['tab']['tab_id'])")
R2=$(echo "$JSON" | python -c "import sys,json;print(json.load(sys.stdin)['result']['root_pane']['pane_id'])")
# 打印出的 4 个 + R2 = 共 5 格
python -I "$S" --pane "$R2" --count 5 --mode grid
```

- `--count` = **总格数**（含 `--pane` 那个根窗格）。
- 脚本会**逐个校验 ≥60×15**，不达标直接 **退出码 3** 并说明为什么。
- pane_id 按位置先后打印，直接拿去 `agent start`。

**先量再切**（不想用脚本时）：

```bash
herdr pane layout --pane <pane_id>     # 看 area 宽高，自己算
```

> ⚠️ `tab create` / `pane split` 都能用默认参数直接执行 —— **别用"省略参数"去试探**。


### 5.3 起 agent

```bash
herdr agent start <task>-<scope> --kind <claude|codex|opencode> --pane <pane-id> \
  -- <免审批参数...>
```

- 名字规则见 §3，**起名之前先 `herdr agent list` 看有没有重名**。
- 原生参数（含下面 §5.3.1 的免审批参数）**放在 `--` 之后**。
- `agent start` 只在 herdr**确认该 agent 起来了且可交互**后才返回。返回 `agent_not_ready` 说明启动期被卡住 → `agent read` 看看它在等什么。

#### 5.3.1 ★ 起 agent 时**默认开高权限**（否则会一直卡在确认框）

用户的明确要求：**干活的 agent 不要老弹审批**。所以起 **worker / verifier** 时一律带上免审批参数。
（`planner` 是统筹、通常只读方案，但也建议带上，免得它卡在确认框上。）

| kind | 免审批参数（放在 `--` 之后） | 说明 |
|---|---|---|
| `claude` | `--dangerously-skip-permissions` | 等价：`--permission-mode bypassPermissions` |
| `codex` | `--dangerously-bypass-approvals-and-sandbox` | 等价组合：`-a never -s danger-full-access` |
| `opencode` | `--auto` | 自动批准未被显式拒绝的权限。⚠️ **交互模式不接受 `--model`**，见 `agent-profiles.md` §1.3 |

实测命令样例：

```bash
herdr agent start dev-plan-codex  --kind codex    --pane w4:p2 -- --dangerously-bypass-approvals-and-sandbox
herdr agent start dev-plan-claude --kind claude   --pane w4:p3 -- --dangerously-skip-permissions --model fable
herdr agent start qa-test01-opencode --kind opencode --pane w4:p4 -- --auto
```

> ⚠️ **带了参数不等于生效** —— 起完必须按 §5.3.4 验一眼模型，尤其 `claude` 要看到 `Fable` 才算拿到 v4-pro。
>
> ⚠️ **这些参数是"关掉安全阀"，不是"提升能力"。** 开了之后 agent 拥有**当前操作系统用户**的全部权限
> —— 能删仓库、能连生产库、能推送。所以**安全网只剩任务书里的边界**：
> 派活时必须把「不许碰什么」写死（见 §6）。planner 派发前确认一遍。
>
> ⛔ **不要起 `pi` / `omp` / `qodercli`** —— 它们已停用（§2.1），不进阵容、不派活。
> 起了也没有对应角色，只会白占一个 pane。

#### 5.3.2 高权限下必须保留的硬边界

免审批 ≠ 没有规矩。这几条**写进每一份任务书**：

- ⚠️ **生产环境可以动，但必须拿到 main 的显式授权** —— 见 §5.3.3。
  **没有 `[PROD-OK]` 就等于没授权**，worker 不得自行执行，planner 也不得自行批准。
- ❌ **根仓 `E:\XY` 永不推远程**（这是用户定死的，不属于"生产"范畴，**授权也不能推翻**）。
  其它仓的 `git push` 视同生产操作，同样需要 §5.3.3 的授权。
- ❌ **不碰不是这次任务开的 pane / workspace / tab**
- ❌ **不删、不覆盖没有备份的东西**（交付物、`.git`、备份目录）
- ✅ 不确定就停下来回报 —— **比猜错便宜**

#### 5.3.3 ★ 生产操作授权协议

> 用户口径：**生产可以动，但得 main 明确才可以。**
> 目的：既不让 worker 卡在确认框上，也不让某个 worker 自己一拍脑袋改生产。

**唯一有权授权的角色：`main`。** planner 不能自批，worker 不能自批。

**授权必须是一条固定格式的文本**，由 main 发给 planner：

```
[PROD-OK] env=<环境> action=<动作> target=<对象> at=<YYYY-MM-DD HH:MM> by=main
```

例：

```
[PROD-OK] env=元芯ERP生产 action=重启后端Pod target=ns yuanxin-erp-hg deploy/erp-hg-backend at=2026-10-17 10:30 by=main
```

**规则（照做，别变通）**：

1. **没有 `[PROD-OK]` 一行 → 不派、不做。** planner 收到生产类任务时，先检查委托里有没有这一行；
   没有就回问 main，**不要自己判断"这个改动很小应该没事"**。
2. **planner 派发时把这一行原样抄进 worker 的任务书。** worker **只认这一行**，
   不认"planner 说可以"、更不认"看起来很安全"。
3. **一次授权只覆盖一次操作。** `env` / `action` / `target` 任何一项变了都要**重新授权**。
   批量操作要在 `action` 里写清范围（如 `action=批量更新表X的Y列`）。
4. **授权不是常开开关。** 任务完成、失败、或超过 1 小时即失效，再动要重新要。
5. **main 负责判断"用户是不是真的授权了这件事"**：
   - 用户的一般性表态（"可以动生产"）**不等于**对某次具体操作的授权；
   - 除非用户对**这次任务**明确说过"你看着办/不用再问"，否则 main 应**先向用户确认一次**，
     拿到确认后再发 `[PROD-OK]`。

**什么算"生产"（判据，避免扯皮）**：

| 算生产 | 不算生产 |
|---|---|
| 生产库的**写**操作（含 DDL、数据修补） | 本地/测试库的任何操作 |
| 生产 k8s、`deploy:prod`、发布流水线 | 本地构建、本地起服务 |
| 对外可访问的服务配置（frp、nginx、安全组、隧道） | 改文档、改脚本 |
| **覆盖写**真实交付物（xlsx/docx/pdf 成品） | 新增文件、写临时目录 |
| 推送任何远程仓（根仓除外 —— 那是永远禁止） | 本地 git 提交 |
| 删除/覆盖没有备份的数据 | 删自己刚生成的临时文件 |

> ⚠️ **拿不准算不算生产 → 按生产办**，去要授权。多问一句比事后收拾便宜。

#### 5.3.4 ★ 起完 agent，**先确认模型对不对**再发任务

**带了参数 ≠ 生效。** 每次 `herdr agent start` 之后、`agent prompt` 之前，**读一眼状态行**：

```bash
herdr agent read <name> --source visible --lines 6
```

| kind | 状态行长什么样（本机实测） | 看哪里 |
|---|---|---|
| `codex` | `GPT-6.1-Sol low · E:\YX\yx-erp` | 模型名 + reasoning effort |
| `claude` | `[Opus 5 (1M context)]` | ⚠️ **槽位别名，不是真实模型**（见下） |
| `opencode` | `Build auto · DeepSeek V4 Pro DeepSeek` | 中间：`<模式> · <模型>`（未配 `model` 时会显示免费模型名） |

**⚠️ 两个必踩的坑：**

1. **`claude` 显示的是 Anthropic 槽位别名，不是后端真实模型。** 本机代理映射：

   | 状态行显示 | 实际后端 |
   |---|---|
   | `[Fable 5 (1M context)]` | ★ `deepseek-v4-pro` ← **T1 统筹要的** |
   | `[Opus 5 …]` / `[Sonnet 5 …]` / `[Haiku …]` | `deepseek-flash` ← 默认槽，**不是 v4-pro** |

   **看到 `Opus 5` 就说明你起了个 flash 档的统筹者** —— 忘了带 `--model fable`。

   > 想**确认映射本身没变**（而不是只看界面显示），三层证据：
   > `~/.claude/settings.json` 的 `ANTHROPIC_DEFAULT_*_MODEL_NAME`（静态）→
   > `curl -s http://127.0.0.1:15721/status` 的 `current_provider`（代理）→
   > `~/.cc-switch/cc-switch.db` 的 `proxy_request_logs` 里 `request_model → model`（**真实调用记录**）。
   > 详见 `reference/agent-profiles.md` §1.1.1。

2. **窄 pane 会截断状态行。** 模型名常在行尾或行中，pane 一窄就看不见，
   容易误以为"没显示模型"。验的时候开宽一点，或 `herdr pane zoom --current --on` 看一眼再 `--off`。

**对不上怎么办**：`herdr agent rename <name> --clear`（释放名字）→ `herdr pane close <pane-id>` → 重起。
**别带着错模型往下跑** —— 那会让整套按能力分派失去意义。

> 📌 这条同样适用于 **verifier**：验证者如果也掉到 flash 档，"换人验"就成了自己验自己（同档同盲点）。

#### 5.3.5 ★ 新目录首次起 agent：先过「信任此文件夹」

⚠️ **`--dangerously-*` 不管这个。** 本机实测（2026-10-17，目录 `E:\XY`）：

| kind | 提示 | 处理 |
|---|---|---|
| `codex` | `Trust this folder?` / `Trust and continue` | 同上，`send-keys enter` |
| `claude` / `opencode` | 本次未出现 | 出现就用同样的办法 |

```bash
herdr agent send-keys <name> enter
```

也可以预先配置，免得每次都点：
- **codex**：信任决定它自己会保存

> ⚠️ **`herdr agent get` 报 `idle` 不代表真就绪。**
> 实测（qodercli，现已停用；codex 有同类提示）：明明卡在信任对话框上，`agent get` 仍返回 `idle` + `interactive_ready: true`。
> **起完必须 `agent read --source visible --lines 6` 看一眼**，见到选择框就 `send-keys enter`。

#### 5.3.6 批量起多个 agent：逐个确认，别一把梭

本机实测：一个循环里连续起 4 个不同 kind 的 agent，**其中两个静默退回 shell**
（pane 里只剩 `PS E:\XY>`），`agent list` 里也就没有它们。

**做法**：
1. 起完**立刻** `herdr agent list` 对照预期名单，数一遍。
2. 缺了就用**同样的命令重试**（实测重试即可成功）。
3. `agent start` 的返回里有 `argv` 字段 —— **确认参数真的传进去了**（尤其 `--model fable`）。

### 5.4 发任务

```bash
herdr agent prompt <name> "<任务书>" --wait --timeout 600000
```

- `--wait` 等的是**第一次落到 idle/done/blocked**。**它只证明"跑完了一轮"，不证明"干对了"**。
- `--timeout` 要给足（长任务 10 分钟起）；超时**不等于没送达**，别盲目重发（见 §7）。
- **`--wait` 就够了，不要再叠 `--until`**。`--until` 只用于"等一个已经跑着的 agent 来问我要输入"这类状态机场景。

### 5.5 读与判

```bash
herdr agent list                                   # 全景：谁在、什么 kind、什么状态、cwd 在哪
herdr agent get  <name>                            # 单个状态
herdr agent read <name> --source recent-unwrapped --lines 200   # 回执（日志/转录优先用这个 source）
herdr agent wait <name> --until blocked --timeout 120000        # 等它来问你要输入
```

状态含义：`working` 在干 · `idle`/`done` 空闲可投喂（**都不代表任务成功**）· `blocked` 卡在审批/提问对话框 · `unknown` 认不出来。

### 5.6 收尾：**默认保留，不关**

任务收口后，**保留全部 agent 和 pane** —— 不要主动关闭。

**为什么**：agent 活着就还握着**任务上下文**（读过哪些文件、为什么这么改、验证时发现了什么）。
用户看完汇报要追问一句「这行为什么这么写」或「顺手把 X 也改一下」，
**一条 prompt 就够**；一旦关掉，就得重新读文件、重新推导一遍 —— **等于把这轮的成本白花了**。

**默认动作**只有一条：

```bash
herdr agent list     # 只确认谁还在，别关
```

汇报时**告诉用户工作区在哪**，让他能切过去看：

> 工作区 `w8`「T1 · AI工程化」仍开着，agent 都在，可以直接追问。

**什么时候才关**（都要有明确依据，别自作主张）：

| 情形 | 动作 |
|---|---|
| 用户明确说「关掉 / 清理」 | 关，并回报关了哪些 |
| 新一轮任务完全取代旧的、且旧任务不会再被问 | **先问一句**再关 |
| 起错了 / 验证不通过要重来 | 关掉错的那几个再起新的（这是必要的回收） |

> ⚠️ **只关自己开的**。不是这次编排开的 pane / workspace / tab，**不要动**。
>
> ⚠️ **`pane close` 会杀掉里面的 agent 进程 —— 上下文一起没了。**
> 它不是"关个窗口"那么轻。

**真要回收资源时**：先问用户；同意后**按 workspace 整体关**（`herdr workspace close`），
别零散地关 pane —— 零散关会让布局塌掉、剩下的 pane 全部变形。

---

## 6. 任务书要自包含（★ 最容易翻车的地方）

> 📋 **直接抄模板：`reference/templates.md`** —— 委托 / 任务书 / 验证报告 / 汇总回报，四套都有。

**worker 是全新进程：没有你的上下文、没读这份 skill、不知道前面发生过什么。**

派活时任务书**必须自带**下面全部内容，否则就是让 worker 猜：

```
【角色】你是 <task>-<scope>，只负责 <范围>，不碰 <范围外>。
【背景】<为什么做这件事，一两句；涉及的文件/模块路径写全>
【要做的事】<编号的可执行步骤，不要写"优化一下"这种话>
【验收标准】<可判定：跑什么命令、看什么输出、比对什么数字>
【边界】不许改 <路径/表/系统>；不确定就停下来回报，不要自己决定
【产出】<改哪些文件 / 生成什么报告 / 写到哪里>
【回报格式】干完请输出：① 改了什么（文件:行）② 怎么自证的（命令+输出）③ 没做的和原因
```

> ⚠️ **`AGENTS.md` 只在 worker 的 cwd 落在含它的目录时才自动加载。** worker 起在别的项目目录时读不到。
> **所以：任务书自包含是硬要求，不能指望它自己去看 skill。**

---

## 7. 陷阱清单

| # | 陷阱 | 处理 |
|---|---|---|
| 1 | **agent 名带中文/大写/超 32 字符** | 直接报 `invalid_agent_name`。`测试部-test01-claude` **只能当标签**；agent 名用 `qa-test01-claude`（§3.1） |
| 2 | **`--wait` 返回 = 以为干完了** | 它只等"一轮结束"。**必须 `agent read` 读回执 + 自己独立核产物** |
| 3 | **超时/`stalled` 就重发** | ⚠️ **超时不等于没送达**。先 `agent get` + `agent read` 看状态，**盲目重发会造成重复执行** |
| 4 | **不看 `blocked` 就继续等** | `blocked` = 它在等你批准某个操作。`agent read` 看清是什么，**涉及权限/破坏性操作要问用户**，别自己代批 |
| 4.5 | **起 agent 时忘了带免审批参数** | 症状：agent 干两步就 `blocked`，要人一个个点确认。**每个 kind 都要带 §5.3.1 的参数** |
| 4.6 | **worker 自己判断"这个改动很小，不算生产"** | 不准判。**判据统一在 §5.3.3 的表**里；表里算生产就必须有 `[PROD-OK]`，拿不准按生产办 |
| 4.7 | **planner 拿"main 之前同意过"当授权** | 授权**一次一用、限定 `env/action/target`**，换一项就失效。口头的"可以动生产"不是 `[PROD-OK]` |
| 5 | **多个 worker 改同一个文件** | 互相覆盖。**同文件/同模块的任务串行**，或在任务书里划清"你只改 A，他改 B" |
| 6 | **让作者自己验** | 同源偏差，等于没验。**verifier 必须换人** |
| 7 | **循环切 pane 切出窄条** | ⚠️ 会连带毁掉 §5.3.4 的验模型（状态行被截断）。**容量上限：主视角页 ≤4（1 main + 3 统筹）· 部门页 ≤6 · 每个 pane ≥60×15**；再多就分页（§5.2.1） |
| 8 | **乱关 pane** | 只关本次编排自己开的。`--group` 之类会连带关掉别的，**不要为了绕过报错而加** |
| 9 | **以为 worker 知道全局** | 见 §6。任务书不自包含 = 让它猜 |
| 10 | **`herdr` 裸跑** | 会启动/附上 TUI，把当前会话搞乱。**永远带子命令** |
| 11 | **`herdr agent start` 想新建布局** | 它**只接受已有的空闲 shell pane**，不建也不切布局。pane 得自己先 split |
| 12 | **模型档位照抄本文** | 档位是用户配置的，会变。见 §2 的确认命令 |
| 13 | **新目录首次起 agent 卡在「信任此文件夹」** | `--dangerously-*` **不覆盖**它。`send-keys enter`，或预配 `trustDirectories`（§5.3.5） |
| 14 | **`agent get` 报 idle，界面其实卡在对话框** | 实测过。**起完必须 `agent read --source visible` 看一眼**（§5.3.5） |
| 15 | **批量连起多个 agent，个别静默退回 shell** | 起完立刻 `agent list` 数一遍；缺了重试即可（§5.3.6） |
| 16 | **任务一收口就把 agent / 工作区关了** | ⚠️ **默认保留**。agent 活着还握着任务上下文，用户追问一句就能答；
关了要重读文件重推导，等于白跑一轮。只有用户明说「关掉」、或起错了要重来才关（§5.6） |

---

## 8. 给各角色的最小清单

### 如果你是 main
- [ ] **先判档（§2.0）**：T0 / T1 / T2。**例外是"一眼活"**（§2.0.2）—— 一条命令出结果的，
      自己做完、汇报时说明一句
- [ ] **T0**：起 **1 个 worker**（带 §5.3.1 免审批参数）→ **验模型（§5.3.4）** → 发自包含任务书 → 收产物 + **自己核一遍** → 汇报
- [ ] **T1**：起 `dev-plan-claude --kind claude -- --dangerously-skip-permissions --model fable` →
      **验状态行必须是 `Fable`（Opus/Sonnet 都是 flash 档）** → 按 `templates.md` §1 委托 → 等汇总 → 汇报
- [ ] **T2**：起 `dev-plan-codex --kind codex` → 按 `templates.md` §1 委托（**注明这是 T2**）→ 等汇总 → 汇报
- [ ] **你全程不干活**（除了一眼活）—— 保持空闲，才接得住用户的新问题
- [ ] **涉及生产时：判断用户是否真的授权了这次操作，然后签 `[PROD-OK]`**（§5.3.3）；
      拿不准就先问用户
- [ ] 如实转述给用户，**包括"没做/没验"的部分**（模板：`reference/templates.md` §4）

### 如果你是 planner
- [ ] 方案落文件（§2 阶段②），别只在对话里说
- [ ] 每个子任务：**适合谁 + 为什么 + 验收标准**写进任务书
- [ ] **生产类任务：确认委托里有 `[PROD-OK]`；没有就回问 main，不要自己批**（§5.3.3）
- [ ] **起每个 agent 时带上 §5.3.1 的免审批参数**（否则会一直卡确认框）
- [ ] **起完逐个验模型**（§5.3.4）—— 对不上就重起，别带着错档往下跑
- [ ] 任务书自包含（§6），并写死 §5.3.2 的硬边界；生产任务把 `[PROD-OK]` 原样抄进去
- [ ] 收产物要三件齐（§5.5）
- [ ] 派 **别的** agent 验证（作者不验）
- [ ] 汇总里区分"已验证 / 未通过 / 没做"

### 如果你是 worker
- [ ] 只在任务书划定的范围内动手
- [ ] **生产操作：任务书里没有 `[PROD-OK]` 就不做**，回问 planner（§5.3.3）
- [ ] 不确定就停下回报，**别自己扩大范围**
- [ ] 按任务书要求的格式回报，**带上自证命令与输出**

### 如果你是 verifier
- [ ] 拿任务书里的**验收标准**逐条判
- [ ] 输出**逐条通过/不通过 + 证据**（命令、输出、文件:行）
- [ ] **不修产物** —— 发现问题回报给 planner
