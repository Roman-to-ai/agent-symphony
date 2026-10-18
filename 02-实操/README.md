# 02 · 实操 · Herdr 多 Agent 编排

> 这里是**能直接拿去用**的部分。理论部分在 `../01-理论/`。
> 两份 skill **不是两份拷贝** —— 是**一份协议 + 一层 Claude 覆盖**，避免两边漂移。

---

## 1. 两份 skill 的分工

| | `skill-通用/` | `skill-claude/` |
|---|---|---|
| **是什么** | 完整编排协议（角色、分级、命名、herdr 用法、模板） | Claude Code 的**覆盖层**：只写 Claude 特有的差异 |
| **给谁用** | Claude Code / Codex / OpenCode **都能用** | **只给 Claude Code** |
| **多大** | ~150 KB（SKILL.md + 3 份 reference + 3 个工具） | 单个 SKILL.md |
| **改了谁先动** | **协议改了先改这里**，再检查 Claude 版有没有失效 | 只改 Claude 的事实（模型槽位 / MCP / skill 发现） |

**为什么不做成两份完整拷贝**
> 两份完整文档必然漂移：改了一边忘另一边，最后没人知道哪份是对的。
> 所以通用版是**唯一真源**，Claude 版是**薄薄一层差异说明**，并显式指回通用版的章节号。

---

## 2. 目录

```
02-实操/
├─ README.md              ← 本文
├─ skill-通用/
│   ├─ SKILL.md                       ← 协议主体（角色 / T0-T2 / 命名 / 工作流）
│   ├─ reference/
│   │   ├─ agent-profiles.md          ← 各 agent 的模型槽位、MCP、派活矩阵
│   │   ├─ herdr-cookbook.md          ← herdr 命令手册、报错码、踩过的坑
│   │   └─ templates.md               ← 委托 / 任务书 / 验证报告模板
│   └─ tools/
│       ├─ herdr-layout.py            ← 算窗格网格（herdr 没有 tile）
│       ├─ herdr-status.py            ← 打印工作区编排状态表
│       └─ herdr-audit.py             ← 审计命名 / 尺寸 / 容量 / 模型档位
└─ skill-claude/
    └─ SKILL.md                       ← Claude Code 覆盖层
```

---

## 3. 怎么装

### 3.1 通用版（所有 agent 共用一份实体）

放到 **Agent Skills 标准位置**：项目级 `.agents/skills/<name>/`，或用户级 `~/.agents/skills/`。

```bash
mkdir -p .agents/skills
cp -r skill-通用 .agents/skills/herdr-orchestration
```

### 3.2 Claude Code（需要额外一步）

Claude Code **不扫** `.agents/skills/`，要用 junction（或拷贝）把它挂到 `.claude/skills/`：

```bash
# Windows：junction 不需要管理员权限
powershell -NoProfile -Command "New-Item -ItemType Junction `
  -Path '.claude\skills\herdr-orchestration' `
  -Target '.agents\skills\herdr-orchestration'"
```

⚠️ **git 会跟随 junction 当成第二份文件** —— 记得在 `.gitignore` 里加：

```
.claude/skills/herdr-orchestration
```

Claude 覆盖层则直接放到 `.claude/skills/herdr-orchestration-claude/`。

### 3.3 验证装好了没

- 通用版：让 agent 读一下 `.agents/skills/herdr-orchestration/SKILL.md` 是否存在
- Claude 版：`ls .claude/skills/` 应能看到两个目录

---

## 4. 怎么用

编排只在一个前提下成立：

```bash
test "${HERDR_ENV:-}" = 1 || echo "不在 Herdr 里 —— 不要执行 herdr 命令"
```

然后按顺序：

1. **判档** —— T0（派 1 个 worker）/ T1（Claude Code 统筹）/ T2（Codex 统筹）
   - 例外：**一眼活**（一条命令出结果）自己做完并说明
2. **派活** —— 起 agent 带免审批参数，起完**验模型**
3. **委托** —— 用 `reference/templates.md` 的模板，四件事写全：
   目标 / 验收标准 / 边界 / 回报要求
4. **验证** —— 验证者必须与作者**不同 kind**
5. **收尾** —— **默认保留 agent 和工作区**，别关（用户可能追问）

---

## 5. 三个工具

| 工具 | 什么时候用 |
|---|---|
| `herdr-layout.py` | 要在 tab 里切规整网格（herdr 没有 balance / tile / auto-scale） |
| `herdr-status.py` | 想看当前工作区的页面 / pane / agent / 状态 / 尺寸 / 模型 |
| `herdr-audit.py` | 想检查命名、窗格尺寸、容量、统筹者模型是否符合协议 |

都支持 `--selftest`（`layout` 除外），纯标准库，可 `python -I` 直接跑。

---

## 6. 本包的局限（用之前先知道）

- **强绑定 herdr**。协议本身（角色 / 分级 / 分派 / 验证）是通用的，
  但所有命令、窗格、命名前缀都围绕 herdr 的实现。换编排器要重写 §5 全章。
- **强绑定本机模型配置**。`reference/agent-profiles.md` 里的槽位映射
  （`fable` → `deepseek-v4-pro` 等）是**某一台机器某一时刻**的实测值。
  换机器必须重跑文末的复验命令。
- **可派活的 agent 只有三个**：`claude` / `codex` / `opencode`。
  别照着旧版本的档案把 `pi` / `omp` / `qodercli` 加回来。
- **工具脚本里的解析器是按各家 TUI 状态行写的**，各家改版就可能失效，
  失效表现是「模型列显示未知」而不是报错 —— 别把它当强校验。

---

## 7. 和理论文档的对应

| 实操里的规则 | 理论依据（待作者补充） |
|---|---|
| main 只派活不干活 | 见 `../01-理论/` 第 3 章 3.1 |
| T0/T1/T2 分级 | 第 5–6 章 |
| 按档位分派 | 第四部分（第 7–8 章） |
| 验证者与作者不同源 | 第 9 章 9.2 |
| 收尾保留 agent | 第 13 章 |
| 免审批 + 边界写死 | 第 17 章 |
