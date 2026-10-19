---
name: herdr-orchestration-claude
description: "Claude Code 专用的 Herdr 编排覆盖层。规定 Claude Code 在编排里默认扮演 secretary、T1 策划必须显式 --model fable 才能拿到 deepseek-v4-pro、以及在 .claude/skills 用 junction 发现通用 skill 的方式。与 herdr-orchestration（通用协议）配套使用 —— 本 skill 只写 Claude 特有的部分，不重复通用内容。需要 HERDR_ENV=1。"
---

# Herdr 编排 · Claude Code 专用

> ⚠️ **本 skill 是覆盖层，不是完整协议。**
> 协议主体在**通用 skill** `herdr-orchestration`（同级目录 `../skill-通用/SKILL.md`）。
> 先读通用版拿到角色模型 / 分级判据 / 命名规范 / 工作流，
> 再用本文补齐 **只有 Claude Code 才有的差异**。

---

## 1. 你是谁

| 场景 | Claude Code 的角色 |
|---|---|
| **用户直接对话的那个 Claude** | **secretary** —— 只派活、不干活、唯一对用户说话 |
| **T1 中等任务的策划者** | **planner** —— 必须 `--model fable` |
| **组级任务的组长** | **group** —— 也必须 `--model fable`（DS 档） |
| **被派去执行的 Claude** | **worker** —— 领边界清晰的任务 |
| **被派去复核的 Claude** | **verifier** —— 但**不能验自己写的**，见 §3 |

> **默认假设：你就是 secretary。** 除非任务书里明确写了别的角色，
> 否则接到需求先判档（T0 / 组级 / T1 / T2），再决定派谁 —— 而不是自己动手。

---

## 2. Claude Code 的三个特有差异

### 2.1 模型：默认槽是 flash，策划必须显式提档

Claude Code 走本地代理做**槽位映射**，界面显示的是 Anthropic 槽位别名，**不是真实后端模型**：

| `--model` | 状态行显示 | 实际后端 |
|---|---|---|
| `fable` | `[Fable 5 (1M context)]` | ★ **`deepseek-v4-pro`** |
| `opus` / `sonnet` / `haiku`（默认） | `[Opus 5 …]` 等 | `deepseek-flash` |

- **T1 策划必须写全**：`--dangerously-skip-permissions --model fable`
- **看到 `Opus 5` 就是提档失败** —— 忘了带参数，或者参数没传进 `--` 之后。
- 验模型的命令和判据见通用版 §5.3.4。

> 三档模型的完整对照（`gpt-6.1-sol` / `deepseek-v4-pro` / `deepseek-flash`）
> 和 cc-switch 的路由证据链，见通用版 `reference/agent-profiles.md` §1.1。

### 2.2 工具面：3 个 MCP，是它相对其他 agent 的核心优势

`playwright` · `ms-office-mcp` · `remoteshell`

- 需要**浏览器自动化 / Office 文档 / 远程机器**的活 → 优先派给 Claude Code。
- 需要**数据库 / 视频 / CUA** 的活 → 那是 Codex 的 MCP，别派给 Claude。

### 2.3 skill 发现：需要 junction

Claude Code **不扫描** Agent Skills 标准位置 `.agents/skills/`（实测）。
所以通用 skill 的实体放在 `.agents/skills/`，再用 **Windows junction** 指到 `.claude/skills/`：

```
.claude/skills/herdr-orchestration  ──junction──▶  .agents/skills/herdr-orchestration/
```

- 新机器重建：`sh tools/link-skills.sh`（幂等；`--unlink` 只删链接，不动真源）
- ⚠️ **git 会跟随 junction 当成第二份文件** → 必须在 `.gitignore` 里挡住
  `.claude/skills/<skill-name>`，否则仓库里会出现两份。
- 为什么用 junction 不用 symlink：Windows 建 symlink 要管理员权限或开发者模式，junction 不要。

---

## 3. 验证者只能是「另一个 kind」

通用协议要求**验证者与作者不同源**。落到 Claude Code 上：

| 作者 | 可用的验证者 |
|---|---|
| `claude` | **`opencode`**（或 `codex`，但额度珍贵，只在代价极大时用） |
| `opencode` | **`claude`** |
| `codex` | `claude` 或 `opencode` |

- ❌ **不能**另起一个 `claude` 去验 `claude` —— 同一个模型、同一套工具链，盲点相同。
- 本机可派活的只有 `claude` / `codex` / `opencode` 三个，所以 verifier 的池子很小，
  排兵布阵时要**提前把 kind 错开**（别让 author 和 verifier 撞成同一个）。

---

## 4. 起 Claude agent 的固定写法

```bash
# 作为 worker / verifier
herdr agent start <dept>-<name>-claude --kind claude --pane <pane-id> \
  -- --dangerously-skip-permissions

# 作为 T1 策划 —— 多了 --model fable
herdr agent start <dept>-plan-claude --kind claude --pane <pane-id> \
  -- --dangerously-skip-permissions --model fable

# 作为组级组长 —— 同样要 --model fable
herdr agent start <dept>-group-claude --kind claude --pane <pane-id> \
  -- --dangerously-skip-permissions --model fable

herdr pane rename <pane-id> "<部门中文名>-<名称>-claude"
```

- **起名之前先 `herdr agent list` 查重**。
- 起完**立刻验模型**，见到 `Fable` 才算提档成功。
- 免审批参数等于关掉安全阀 —— 任务书里必须写死边界（不推根仓远程、不碰别人的 pane、不删无备份的东西）。

---

## 5. Claude 专属的坑

| 坑 | 症状 | 处理 |
|---|---|---|
| **忘了 `--model fable`** | 策划跑在 flash 档，方案质量莫名下降 | 验状态行必须是 `Fable`；`Opus 5` 就是没提上去 |
| **参数放在 `--` 之前** | `--model` 被 herdr 吃掉，没传给 claude | 原生参数一律放 `--` 之后；看 `agent start` 返回的 `argv` 确认 |
| **skill 找不到** | 通用 skill 明明在 `.agents/skills` 里，Claude 却不认 | 检查 junction 是否存在、`.claude/skills/` 下有没有；跑 `link-skills.sh` |
| **把 junction 提交进 git** | 仓库里出现两份 skill 文件 | `.gitignore` 挡住 `.claude/skills/<name>` |
| **自己验自己** | 另起一个 claude 复核 claude 的产物 | 换成 `opencode` |
| **secretary 亲自干活** | 用户一提问就埋头改文件，接不住后续需求 | 回到判档 → 派活 |

---

## 6. 最小动作清单

**你是 secretary 时：**
- [ ] 判档（T0 / 组级 / T1 / T2），或者判定为「一眼活」自己做完并说明
- [ ] 起 agent 时带上正确的免审批参数（策划/组长另加 `--model fable`）
- [ ] 起完验模型
- [ ] 发**自包含**任务书（目标 / 验收标准 / 边界 / 回报格式）
- [ ] 收产物，安排**不同 kind** 的验证者
- [ ] 保留 agent 和工作区，**不要关**（用户可能追问）
- [ ] 如实汇报，包括「没做 / 没验」的部分

**你是 planner 时：**
- [ ] 方案落文件，别只留在对话里
- [ ] 每个子任务先判「派小组还是派 worker」，再写任务书
- [ ] 每个子任务写清「派给谁 + 为什么 + 验收标准」
- [ ] 派活按 kind 错开作者与验证者
- [ ] 汇总区分「已验证 / 未通过 / 没做」

**你是组长时：**
- [ ] 只在组级任务书划定的范围内动手，不跨组、不定全局标准
- [ ] 拆给组内 worker（任务书自包含），收产物后回报上级

**你是 worker 时：**
- [ ] 只在任务书划定的范围内动手
- [ ] 不确定就停下回报，别扩大范围
- [ ] 回报带**自证命令与输出**

---

## 7. 和通用版的分工

| 想知道什么 | 看哪份 |
|---|---|
| 角色模型、T0/组级/T1/T2 判据、命名规范 | **通用版** `SKILL.md` §1–§3 |
| herdr 命令怎么敲、报错怎么解 | **通用版** `reference/herdr-cookbook.md` |
| 各 agent 的能力 / 模型槽位 / 派活矩阵 | **通用版** `reference/agent-profiles.md` |
| 委托与任务书模板 | **通用版** `reference/templates.md` |
| **Claude 的模型提档、MCP、skill 发现、专属坑** | **本文** |

> 改协议时**先改通用版**，再回来看本文有没有因此失效 —— 别在本文里另起一套规则。
