#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""herdr-audit.py — 只读审计指定 Herdr 工作区是否符合编排规范。

只读：仅调用 `herdr api snapshot`（一次）与 `herdr pane read --source visible`
（仅对「名含 plan」的策划逐个读一次），不 prompt / send-keys / resize / zoom /
rename / close / move，不动任何 pane / tab / workspace。

审计四项（对应验收标准）：
  a 命名：agent 名须匹配 [a-z][a-z0-9_-]{0,31} 且为 <dept>-<name>-<kind>，
         dept ∈ {qa,dev,ops,data,pm,fin,buy,wh,mfg,cus}，
         kind ∈ {claude,codex,opencode}（pi/omp/qodercli 已停用，2026-10-18）；
         协议例外：名字为 secretary 不检查；未命名 agent（无 name 字段）不检查；
         shell pane（无 agent）不检查。
  b 尺寸：每个 pane 的 layout.rect（含边框）须 ≥ 60 列 × 15 行。
  c 容量：秘书 tab（标签含「秘书」）≤4 个 pane（1 secretary + 3 策划），其它 tab ≤6 个 pane
         （与 SKILL.md §5.2.1 的「1 + 3」一致。）
  d 模型：名含「plan」的策划须为 codex 或 claude Fable；名含「group」的组长须为
         claude Fable 或 opencode DeepSeek V4 Pro；Opus/Sonnet/Haiku/DeepSeek-Flash 违规。

模型只从 pane「当前状态栏」提取（按各 kind 的固定格式锚定），聊天历史里出现的
模型示例一律不认；读不到 / 不认识 → 对策划即违规（不假通过）。

尺寸/容量依赖 layout.rect：每个 pane 必须存在于某 layout 且 width/height 为完整整数，
否则按采集错误报出（exit 1），不静默跳过、不假通过。

退出码：0 全通过；1 有违规或采集错误；2 参数错误。
纯标准库，可 python -I 直接运行。
"""

import argparse
import json
import math
import re
import subprocess
import sys

HERDR_BIN = "herdr"
DEFAULT_TIMEOUT = 10.0
MIN_COLS = 60
MIN_ROWS = 15

# 部门短码（唯一真源：SKILL.md §3.3）
DEPTS = {"qa", "dev", "ops", "data", "pm", "fin", "buy", "wh", "mfg", "cus"}
# 可派活的 kind（协议固定：SKILL.md §3.4）。pi/omp/qodercli 已于 2026-10-18 停用
# —— 起它们也算违规，故不在此集合内。解析器仍保留（见 extract_model），只影响展示不影响判定。
KINDS = {"claude", "codex", "opencode"}
# 策划允许的 kind（验收标准 d）
PLANNER_KINDS = {"codex", "claude"}
# 组长允许的 kind（验收标准 d，DS 档）
GROUP_KINDS = {"claude", "opencode"}

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

NAME_RULE = "agent 名须匹配 [a-z][a-z0-9_-]{0,31} 且为 <dept>-<name>-<kind>（dept∈10 部门短码，kind∈claude/codex/opencode；secretary 例外）"
SIZE_RULE = "每个 pane 的 layout.rect 须 ≥ {} 列 × {} 行".format(MIN_COLS, MIN_ROWS)
CAPACITY_RULE = "秘书 tab（标签含「秘书」）≤4 个 pane（1 secretary + 3 策划），其它 tab ≤6 个 pane"
MODEL_RULE = "策划（名含 plan）须为 codex 或 claude Fable；组长（名含 group）须为 claude Fable 或 opencode DeepSeek V4 Pro；Opus/Sonnet/Haiku/DeepSeek-Flash 违规"
COLLECT_RULE = "每个 pane 必须有完整整数尺寸（layout.rect.width/height 为整数，且 pane 必须存在于某个 layout 中）"

CATEGORY_ORDER = ["采集错误", "命名", "尺寸", "容量", "模型"]


# --------------------------------------------------------------------------
# 控制台编码：Windows 下默认 stdout 可能是 cp936，直接 print 中文/emoji 会抛
# UnicodeEncodeError。统一重配成 utf-8（丢失字符用 � 兜底，不炸）。
# --------------------------------------------------------------------------
def _setup_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _positive_float(s):
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError("必须是数字")
    if not (math.isfinite(v) and v > 0):
        raise argparse.ArgumentTypeError("必须是有限正数（>0，非 NaN/Inf/0/负数）")
    return v


# --------------------------------------------------------------------------
# 子进程封装：超时 + 编码 + 错误统一处理。
# --------------------------------------------------------------------------
def run_herdr(args, timeout=DEFAULT_TIMEOUT, herdr_bin=HERDR_BIN):
    try:
        proc = subprocess.run([herdr_bin] + args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise SystemExit("找不到 herdr 二进制（PATH 里没有 herdr）")
    except subprocess.TimeoutExpired:
        raise SystemExit("herdr 子进程超时（>{:g}s）：herdr {}".format(timeout, " ".join(args)))
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    return out, err, proc.returncode


def _brief(obj, n=200):
    s = str(obj)
    return s if len(s) <= n else s[:n] + "…"


def _validate_snapshot(data):
    """校验 api snapshot 的 JSON 结构；不合法抛 SystemExit（采集错误 → exit 1）。"""
    if not isinstance(data, dict):
        raise SystemExit("herdr api snapshot 顶层不是对象：{}".format(_brief(data)))
    result = data.get("result")
    if not isinstance(result, dict):
        raise SystemExit("herdr api snapshot 缺少 result 对象（或为 null）")
    snapshot = result.get("snapshot")
    if not isinstance(snapshot, dict):
        raise SystemExit("herdr api snapshot 的 snapshot 缺失或不是对象（可能为 null/[]）")
    for key in ("workspaces", "tabs", "panes", "agents", "layouts"):
        val = snapshot.get(key)
        if not isinstance(val, list):
            raise SystemExit("herdr api snapshot 的 snapshot.{} 缺失或不是数组".format(key))
        for elem in val:
            if not isinstance(elem, dict):
                raise SystemExit("herdr api snapshot 的 snapshot.{} 含非对象元素：{}".format(key, _brief(elem)))
    for layout in snapshot["layouts"]:
        panes = layout.get("panes")
        if not isinstance(panes, list):
            raise SystemExit("herdr api snapshot 的 layout.panes 缺失或不是数组")
        for lp in panes:
            if not isinstance(lp, dict):
                raise SystemExit("herdr api snapshot 的 layout.panes 含非对象元素：{}".format(_brief(lp)))
            if not isinstance(lp.get("rect"), dict):
                raise SystemExit("herdr api snapshot 的 pane.rect 缺失或不是对象：{}".format(_brief(lp.get("rect"))))
    return snapshot


def fetch_snapshot(timeout=DEFAULT_TIMEOUT, herdr_bin=HERDR_BIN):
    out, err, code = run_herdr(["api", "snapshot"], timeout, herdr_bin)
    if code != 0:
        raise SystemExit("herdr api snapshot 失败（exit {}）：{}".format(code, err.strip()))
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise SystemExit("herdr api snapshot 返回不是合法 JSON：{}\n原始：{}".format(exc, out[:500]))
    return _validate_snapshot(data)


# --------------------------------------------------------------------------
# 模型提取：只认各客户端「底部状态栏」里的固定格式，不猜聊天历史。
# 先按各家的 UI 结构锚定状态栏位置，只在锚点之后/那一行找模型；
# 聊天里出现的完整模型示例一律不认。无法确认归属 → 「未知」。
# --------------------------------------------------------------------------
def extract_model(kind, text):
    if not kind or not text:
        return "未知"
    lines = text.splitlines()
    fn = {
        "codex": _extract_codex,
        "claude": _extract_claude,
        "qodercli": _extract_qodercli,
        "pi": _extract_pi,
        "omp": _extract_omp,
    }.get(kind)
    return fn(lines) if fn else "未知"


def _last_index(lines, pattern):
    for i in range(len(lines) - 1, -1, -1):
        if re.search(pattern, lines[i]):
            return i
    return None


def _last_separator_index_after(lines, i):
    for j in range(len(lines) - 1, i, -1):
        if re.match(r"^\s*─{3,}", lines[j]):
            return j
    return None


def _extract_codex(lines):
    # 锚定最后一个 `›` 输入框，只在其后找模型行；模型行 = 整行以 GPT 开头、
    # 匹配「模型 + effort + ·」，且上一行是空行（输入框与模型行之间的空行边界）。
    i = _last_index(lines, r"^\s*›")
    if i is None:
        return "未知"
    for j in range(len(lines) - 1, i, -1):
        if lines[j - 1].strip() != "":
            continue
        m = re.match(r"^\s*(GPT-\d[\w.-]*\s+(?:low|medium|high))\s*·", lines[j])
        if m:
            return m.group(1)
    return "未知"


def _extract_claude(lines):
    # 锚定最后一个 `❯` 输入框，再取其下方最后一条 Unicode ─ 分隔线，
    # 模型 `[...]` 只取该分隔线之后、整行以 `[` 开头的那一行。
    i = _last_index(lines, r"^\s*❯")
    if i is None:
        return "未知"
    sep = _last_separator_index_after(lines, i)
    if sep is None:
        return "未知"
    for j in range(sep + 1, len(lines)):
        m = re.match(r"^\s*\[(Fable|Opus|Sonnet|Haiku)(?:\s+(\d+(?:\.\d+)?))?", lines[j])
        if m:
            alias = m.group(1)
            if m.group(2):
                alias += " " + m.group(2)
            return alias
    return "未知"


def _extract_qodercli(lines):
    # 锚定最后一个 `*` 输入框，再取其下方最后一条 Unicode ─ 分隔线，
    # 模型 `DeepSeek-…` 只取该分隔线之后、整行以 DeepSeek 开头的那一行。
    i = _last_index(lines, r"^\s*\*")
    if i is None:
        return "未知"
    sep = _last_separator_index_after(lines, i)
    if sep is None:
        return "未知"
    for j in range(sep + 1, len(lines)):
        m = re.match(r"^\s*(DeepSeek-[A-Za-z]+(?:\s*\([^)]*\))?)", lines[j])
        if m:
            return m.group(1)
    return "未知"


def _extract_pi(lines):
    # 状态行 = 底部含 `↑…↓…` 网络统计的那一行；模型只出现在该行右侧。
    for i in range(len(lines) - 1, -1, -1):
        ln = lines[i]
        if "↑" in ln and "↓" in ln:
            m = re.search(r"deepseek-[A-Za-z0-9_.-]+\s*[•·]\s*[A-Za-z]+", ln)
            return m.group(0) if m else "未知"
    return "未知"


def _extract_omp(lines):
    # 状态行 = 最底部含 `π >` 的那一行；模型只在该行，且后面要跟 `>` 分隔符（证明完整）。
    i = _last_index(lines, r"π\s*>")
    if i is None:
        return "未知"
    m = re.search(r"DeepSeek(?:\s+V?\d+(?:\.\d+)?)?\s+[A-Za-z]+(?=\s*>)", lines[i])
    return m.group(0) if m else "未知"


# --------------------------------------------------------------------------
# 模型读取（真实路径）：读 pane 的 visible 文本再抽模型；读失败返回 None。
# --------------------------------------------------------------------------
def _read_pane_model(pane_id, kind, timeout, herdr_bin):
    out, _err, code = run_herdr(
        ["pane", "read", pane_id, "--source", "visible", "--format", "text"],
        timeout,
        herdr_bin,
    )
    if code != 0:
        return None  # 读取失败
    return extract_model(kind, out)


# --------------------------------------------------------------------------
# 规则判定（纯函数，供内存自测直接调用）。
# --------------------------------------------------------------------------
def check_name(name):
    """返回 None=合规，否则返回违规原因（字符串）。"""
    if not NAME_RE.fullmatch(name):
        return "不符合正则 [a-z][a-z0-9_-]{0,31}（含大写/中文/空格/点/斜杠或超 32 字符）"
    parts = name.split("-")
    if len(parts) < 3:
        return "缺 <dept>-<name>-<kind> 三段（现 {} 段）".format(len(parts))
    if any(p == "" for p in parts):
        return "含空段（连续的 -）"
    if parts[0] not in DEPTS:
        return "部门短码「{}」不在 qa/dev/ops/data/pm/fin/buy/wh/mfg/cus 之一".format(parts[0])
    if parts[-1] not in KINDS:
        return "kind 段「{}」不在 claude/codex/opencode 之一".format(parts[-1])
    return None


def check_planner(kind, name, model):
    """返回 None=合规，否则返回违规原因（字符串）。model 为 None 表示 pane 读取失败。"""
    if kind not in PLANNER_KINDS:
        return "策划 kind 须为 codex 或 claude，实际 kind={}，模型={}".format(
            kind or "未知", "读取失败" if model is None else model
        )
    if kind == "codex":
        if model is None:
            return "codex 策划缺模型状态证据（pane 读取失败）"
        if not str(model).startswith("GPT"):
            return "codex 策划须有模型状态证据（GPT-…），实际 {}".format(model)
        return None
    # kind == "claude"
    if model is None:
        return "claude 策划模型状态行读取失败，无法确认是否为 Fable"
    if str(model).startswith("Fable"):
        return None
    return "claude 策划须为 Fable（deepseek-v4-pro），实际 {}".format(model)


def check_group(kind, name, model):
    """组长（组级）模型校验：claude 须 Fable，opencode 须 DeepSeek V4 Pro。"""
    if kind not in GROUP_KINDS:
        return "组长 kind 须为 claude 或 opencode，实际 kind={}，模型={}".format(
            kind or "未知", "读取失败" if model is None else model
        )
    if kind == "claude":
        if model is None:
            return "claude 组长模型状态行读取失败，无法确认是否为 Fable"
        if str(model).startswith("Fable"):
            return None
        return "claude 组长须为 Fable（deepseek-v4-pro），实际 {}".format(model)
    # kind == "opencode"
    if model is None:
        return "opencode 组长模型状态行读取失败，无法确认是否为 DeepSeek V4 Pro"
    if "DeepSeek V4 Pro" in str(model):
        return None
    return "opencode 组长须为 DeepSeek V4 Pro，实际 {}".format(model)


def _is_planner(name):
    return bool(name) and "plan" in name


def _is_group(name):
    return bool(name) and "group" in name


def _valid_dim(v):
    """尺寸必须是真正的整数（拒绝 bool、None、float、str 等）。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _tab_label(tabs, tab_id):
    t = tabs.get(tab_id, {})
    lab = t.get("label")
    return lab if lab not in (None, "") else "?"


def _finding(category, tab, pane, agent, rule, actual):
    return {
        "category": category,
        "tab": tab,
        "pane": pane,
        "agent": agent,
        "rule": rule,
        "actual": actual,
    }


# --------------------------------------------------------------------------
# 审计主逻辑：返回 finding 列表。model_reader(pane_id, kind) -> 模型字符串或 None。
# --------------------------------------------------------------------------
def audit_workspace(snapshot, workspace_id, model_reader):
    tabs = {t.get("tab_id"): t for t in snapshot.get("tabs", [])}
    agents = snapshot.get("agents", [])
    panes = snapshot.get("panes", [])
    layouts = snapshot.get("layouts", [])

    # 该工作区的所有 pane（含 shell）；agent 记录优先，缺 agent 用 pane 记录兜底。
    agent_by_pane = {
        a.get("pane_id"): a for a in agents
        if a.get("workspace_id") == workspace_id and a.get("pane_id")
    }
    pane_by_pane = {
        p.get("pane_id"): p for p in panes
        if p.get("workspace_id") == workspace_id and p.get("pane_id")
    }
    expected_panes = set(agent_by_pane) | set(pane_by_pane)

    findings = []

    def _agent_name(pid):
        ag = agent_by_pane.get(pid)
        return (ag.get("name") or "（未命名）") if ag else "—"

    def _tab_str(pid):
        tid = pane_to_tab.get(pid)
        if tid is None:
            rec = agent_by_pane.get(pid) or pane_by_pane.get(pid)
            tid = rec.get("tab_id") if rec else None
        return "{}({})".format(_tab_label(tabs, tid), tid or "?")

    # 从 layouts 建立 pane -> tab 与 pane -> rect，构建时做唯一性与身份检查：
    # 缺 pane_id / 同 pane 重复出现（同 layout 或跨 tab）/ 声明 tab 与 layout tab 不一致
    # → 报采集错误，不覆盖、不假通过。
    pane_to_tab = {}
    pane_to_rect = {}
    seen_in_layout = set()
    for lay in layouts:
        if lay.get("workspace_id") != workspace_id:
            continue
        tid = lay.get("tab_id")
        tab_str = "{}({})".format(_tab_label(tabs, tid), tid or "?")
        for lp in lay.get("panes", []):
            pid = lp.get("pane_id")
            if not pid:
                findings.append(_finding(
                    "采集错误", tab_str, "?", "—", COLLECT_RULE,
                    "layout 条目缺 pane_id（tab={}）".format(tid or "?"),
                ))
                continue
            seen_in_layout.add(pid)
            if pid in pane_to_rect:
                findings.append(_finding(
                    "采集错误", tab_str, pid, _agent_name(pid), COLLECT_RULE,
                    "pane 重复出现（同 layout 或跨 tab）：首次在 tab={}，本次在 tab={}".format(
                        pane_to_tab.get(pid), tid or "?"),
                ))
                continue
            rec = agent_by_pane.get(pid) or pane_by_pane.get(pid)
            declared_tab = rec.get("tab_id") if rec else None
            if declared_tab is not None and declared_tab != tid:
                findings.append(_finding(
                    "采集错误", tab_str, pid, _agent_name(pid), COLLECT_RULE,
                    "pane 声明 tab={} 与所在 layout tab={} 不一致".format(declared_tab, tid or "?"),
                ))
                continue
            pane_to_tab[pid] = tid
            r = lp.get("rect") or {}
            pane_to_rect[pid] = (r.get("width"), r.get("height"))

    # a 命名 + d 模型（遍历该工作区的 agent）。
    for a in agent_by_pane.values():
        pid = a.get("pane_id", "?")
        kind = a.get("agent")
        name = a.get("name")
        tab = _tab_str(pid)

        if name and name != "secretary":  # 未命名不检查；secretary 例外
            reason = check_name(name)
            if reason:
                findings.append(_finding("命名", tab, pid, name, NAME_RULE, "{}：{}".format(name, reason)))

        if _is_planner(name):
            model = model_reader(pid, kind)
            reason = check_planner(kind, name, model)
            if reason:
                findings.append(_finding("模型", tab, pid, name, MODEL_RULE, reason))
        elif _is_group(name):
            model = model_reader(pid, kind)
            reason = check_group(kind, name, model)
            if reason:
                findings.append(_finding("模型", tab, pid, name, MODEL_RULE, reason))

    # b 尺寸 + 采集错误：每个 pane（含 shell）都必须存在于某 layout 且有完整整数尺寸。
    for pid in sorted(expected_panes | set(pane_to_rect)):
        tab = _tab_str(pid)
        agent_name = _agent_name(pid)
        if pid not in pane_to_rect:
            if pid not in seen_in_layout:
                findings.append(_finding(
                    "采集错误", tab, pid, agent_name, COLLECT_RULE,
                    "pane 不在任何 layout（缺 rect，尺寸/容量无法核实，不假通过）",
                ))
            # 在 layout 中出现过但被上方唯一性/一致性检查跳过 → 已报过，不重复报
            continue
        w, h = pane_to_rect[pid]
        if not (_valid_dim(w) and _valid_dim(h)):
            findings.append(_finding(
                "采集错误", tab, pid, agent_name, COLLECT_RULE,
                "rect 非完整整数尺寸：width={!r}, height={!r}".format(w, h),
            ))
            continue
        if w < MIN_COLS or h < MIN_ROWS:
            findings.append(_finding("尺寸", tab, pid, agent_name, SIZE_RULE, "{}×{}".format(w, h)))

    # c 容量（每个 layout 对应一个 tab；重复 pane 去重，不把重复计为容量违规）。
    for lay in layouts:
        if lay.get("workspace_id") != workspace_id:
            continue
        tid = lay.get("tab_id", "?")
        label = _tab_label(tabs, tid)
        pane_ids = list(dict.fromkeys(
            lp.get("pane_id") for lp in lay.get("panes", []) if lp.get("pane_id")
        ))
        count = len(pane_ids)
        limit = 4 if "秘书" in label else 6
        if count > limit:
            findings.append(_finding(
                "容量",
                "{}({})".format(label, tid),
                ",".join(pane_ids),
                ",".join(_agent_name(p) for p in pane_ids),
                CAPACITY_RULE,
                "{} 个 pane（上限 {}）".format(count, limit),
            ))

    findings.sort(key=lambda f: (CATEGORY_ORDER.index(f["category"]), f["tab"], f["pane"], f["agent"]))
    return findings


def render_finding(f):
    return "[{}] tab={} · pane={} · agent={} · 规则：{} · 实际：{}".format(
        f["category"], f["tab"], f["pane"], f["agent"], f["rule"], f["actual"]
    )


# --------------------------------------------------------------------------
# 内存自测：不碰 herdr、不建文件。
# --------------------------------------------------------------------------
def selftest():
    fails = 0

    # check_name
    name_cases = [
        ("dev-plan-claude", None),
        ("qa-test01-claude", None),
        ("ops-w1-opencode", None),
        ("fin-x-claude", None),
        ("mfg-check01-claude", None),
        ("dev-plan2-codex", None),
        ("dev-audit-claude", None),
        ("qa-audit-codex", None),
        ("qa-my-worker-claude", None),  # name 段含连字符
        ("planner", "缺"),           # 1 段
        ("rename-validation", "缺"),  # 2 段
        ("rename-java", "kind"),     # kind 段非法
        ("rename-tools", "kind"),
        ("rename-resources", "kind"),
        ("Test01-claude", "正则"),   # 大写
        ("测试部-x-claude", "正则"),  # 中文
        ("qa--claude", "空段"),      # 连续 -
        ("qax-work-claude", "部门"),  # 部门不在表
        ("dev-plan", "缺"),          # 2 段
        ("qa-x-pi", "kind"),         # 已停用的 kind 也算违规
        ("qa-x-omp", "kind"),
        ("qa-x-qodercli", "kind"),
    ]
    for name, expect in name_cases:
        got = check_name(name)
        if (got is None) != (expect is None):
            fails += 1
            print("FAIL check_name({!r}) = {!r}".format(name, got))
        elif expect is not None and expect not in got:
            fails += 1
            print("FAIL check_name({!r}) = {!r} 期望含 {!r}".format(name, got, expect))

    # check_planner
    planner_cases = [
        ("codex", "GPT-6.1-Sol low", None),
        ("codex", "GPT-6.1-Sol high", None),
        ("codex", "未知", "证据"),
        ("codex", None, "证据"),
        ("claude", "Fable 5", None),
        ("claude", "Opus 5", "Fable"),
        ("claude", "Sonnet 5", "Fable"),
        ("claude", "Haiku 4.5", "Fable"),
        ("claude", "未知", "Fable"),
        ("claude", None, "读取失败"),
        ("opencode", "DeepSeek V4 Pro", "codex 或 claude"),
    ]
    for kind, model, expect in planner_cases:
        got = check_planner(kind, "x-plan-x", model)
        if (got is None) != (expect is None):
            fails += 1
            print("FAIL check_planner({!r}, {!r}) = {!r}".format(kind, model, got))
        elif expect is not None and expect not in got:
            fails += 1
            print("FAIL check_planner({!r}, {!r}) = {!r} 期望含 {!r}".format(kind, model, got, expect))

    # check_group
    group_cases = [
        ("claude", "Fable 5", None),
        ("claude", "Opus 5", "Fable"),
        ("claude", "未知", "Fable"),
        ("claude", None, "读取失败"),
        ("opencode", "DeepSeek V4 Pro", None),
        ("opencode", "Nemotron 3.5 Super VL Free", "DeepSeek V4 Pro"),
        ("opencode", None, "读取失败"),
        ("codex", "GPT-6.1-Sol low", "claude 或 opencode"),
    ]
    for kind, model, expect in group_cases:
        got = check_group(kind, "x-group-x", model)
        if (got is None) != (expect is None):
            fails += 1
            print("FAIL check_group({!r}, {!r}) = {!r}".format(kind, model, got))
        elif expect is not None and expect not in got:
            fails += 1
            print("FAIL check_group({!r}, {!r}) = {!r} 期望含 {!r}".format(kind, model, got, expect))

    # extract_model（代表性子集，完整回归在 herdr-status.py）
    model_cases = [
        ("codex", "› Ask Codex to do anything\n\n  GPT-6.1-Sol low · E:\\YX\\yx-e…\n  ← for agents", "GPT-6.1-Sol low"),
        ("codex", "› compare GPT-9.9 high\n\n  GPT-6.1-Sol low · E:\\XY\n  ← for agents", "GPT-6.1-Sol low"),
        ("claude", "──────────────────────\n❯\n──────────────────────\n  [Opus 5 (1M context)] │ yx-erp\n  3 MCPs", "Opus 5"),
        ("claude", "❯ compare [Fable 5]\n───\n [Opus 5 (1M context)]\n 3 MCPs", "Opus 5"),
        ("claude", "❯\n──────\n  [Fable 5] │ XY", "Fable 5"),
        ("qodercli", "──────\n *   Type your message\n──────\n DeepSeek-Flash (DeepSeek) M…", "DeepSeek-Flash (DeepSeek)"),
        ("pi", "E:\\YX ↑131k ↓114k R20M CH99.7% deepseek-flash • medium", "deepseek-flash • medium"),
        ("omp", "π > ◒ DeepSeek V4.1 Flash > 📁 E:\\YX > ⑂ main > $0.00", "DeepSeek V4.1 Flash"),
        ("omp", "π > 📁 …-erp ▶─────44%──┃─1M─", "未知"),  # 窄 pane 截断，模型看不见
        ("pi", "E:\\YX ↑131k ↓114k R20M CH99.7% 22....", "未知"),  # 窄 pane 截断
    ]
    for kind, text, want in model_cases:
        got = extract_model(kind, text)
        if got != want:
            fails += 1
            print("FAIL extract_model({!r}, ...) = {!r} 期望 {!r}".format(kind, got, want))

    # _positive_float
    for bad in ("nan", "inf", "0", "-1"):
        try:
            _positive_float(bad)
            fails += 1
            print("FAIL _positive_float({!r}) 应抛".format(bad))
        except argparse.ArgumentTypeError:
            pass
    if _positive_float("5") != 5.0:
        fails += 1
        print("FAIL _positive_float 正数应放行")

    # audit_workspace 全链路（假 snapshot + 假 model_reader）
    fake = {
        "workspaces": [{"workspace_id": "w9", "label": "测试"}],
        "tabs": [
            {"tab_id": "w9:t1", "label": "秘书 · X", "workspace_id": "w9"},
            {"tab_id": "w9:t2", "label": "测试部", "workspace_id": "w9"},
        ],
        "panes": ([{"pane_id": "w9:p{}".format(i), "workspace_id": "w9"} for i in range(1, 8)]
                  + [{"pane_id": "w9:p9", "workspace_id": "w9"}]),
        "agents": [
            {"pane_id": "w9:p1", "agent": "claude", "workspace_id": "w9", "tab_id": "w9:t1"},  # 未命名 secretary
            {"pane_id": "w9:p2", "agent": "codex", "name": "dev-plan-codex", "workspace_id": "w9", "tab_id": "w9:t1"},
            {"pane_id": "w9:p3", "agent": "claude", "name": "planner", "workspace_id": "w9", "tab_id": "w9:t1"},
            {"pane_id": "w9:p4", "agent": "opencode", "name": "rename-tools", "workspace_id": "w9", "tab_id": "w9:t1"},
            {"pane_id": "w9:p5", "agent": "opencode", "name": "qa-audit-opencode", "workspace_id": "w9", "tab_id": "w9:t2"},
            {"pane_id": "w9:p6", "agent": "claude", "name": "ops-x-claude", "workspace_id": "w9", "tab_id": "w9:t2"},
            {"pane_id": "w9:p7", "agent": "claude", "name": "dev-verify-claude", "workspace_id": "w9", "tab_id": "w9:t2"},
            {"pane_id": "w9:p9", "agent": "codex", "name": "qa-extra-codex", "workspace_id": "w9", "tab_id": "w9:t1"},
        ],
        "layouts": [
            {"workspace_id": "w9", "tab_id": "w9:t1", "panes": [
                {"pane_id": "w9:p1", "rect": {"width": 66, "height": 45}},
                {"pane_id": "w9:p2", "rect": {"width": 66, "height": 45}},
                {"pane_id": "w9:p3", "rect": {"width": 33, "height": 22}},
                {"pane_id": "w9:p4", "rect": {"width": 33, "height": 22}},
                {"pane_id": "w9:p9", "rect": {"width": 66, "height": 45}},
            ]},
            {"workspace_id": "w9", "tab_id": "w9:t2", "panes": [
                {"pane_id": "w9:p5", "rect": {"width": 66, "height": 45}},
                {"pane_id": "w9:p6", "rect": {"width": 66, "height": 45}},
                {"pane_id": "w9:p7", "rect": {"width": 66, "height": 45}},
            ]},
        ],
    }
    fake_models = {"w9:p2": "GPT-6.1-Sol low", "w9:p3": "Opus 5"}
    findings = audit_workspace(fake, "w9", lambda pid, kind: fake_models.get(pid))

    by_cat = {}
    for f in findings:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    want_cat = {"命名": 2, "尺寸": 2, "容量": 1, "模型": 1}
    if by_cat != want_cat:
        fails += 1
        print("FAIL audit_workspace 分类计数 = {} 期望 {}".format(by_cat, want_cat))
    # p2 codex 策划 GPT 合规 → 不应有模型违规
    if any(f["category"] == "模型" and f["agent"] == "dev-plan-codex" for f in findings):
        fails += 1
        print("FAIL p2 dev-plan-codex 不应有模型违规")
    # p3 claude planner Opus → 应有模型违规
    if not any(f["category"] == "模型" and f["agent"] == "planner" for f in findings):
        fails += 1
        print("FAIL p3 planner 应有模型违规")
    # 容量违规应带全部 pane 与 agent
    cap = [f for f in findings if f["category"] == "容量"]
    if not cap or cap[0]["pane"].count(",") != 4 or cap[0]["agent"].count(",") != 4:
        fails += 1
        print("FAIL 容量违规应列出 5 个 pane/agent")

    # _valid_dim：拒绝 bool / None / float / str，接受整数（含 0）
    if not (_valid_dim(60) and _valid_dim(0) and _valid_dim(15)
            and not _valid_dim(True) and not _valid_dim(False)
            and not _valid_dim(None) and not _valid_dim(60.0) and not _valid_dim("60")):
        fails += 1
        print("FAIL _valid_dim 应只接受真正的整数")

    # 采集错误 1：rect 缺 width（合法 JSON，通过 _validate_snapshot）→ 报采集错误，不假通过
    fake_badrect = json.loads(json.dumps(fake))
    fake_badrect["layouts"][0]["panes"][2]["rect"] = {"height": 22}  # w9:p3 缺 width
    fr = audit_workspace(fake_badrect, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and f["pane"] == "w9:p3" for f in fr):
        fails += 1
        print("FAIL rect 缺 width 应报采集错误")

    # 采集错误 2：pane 在 panes 但不在任何 layout → 报采集错误（不能漏计/假通过）
    fake_nolayout = json.loads(json.dumps(fake))
    fake_nolayout["panes"].append({"pane_id": "w9:p8", "workspace_id": "w9"})
    fr2 = audit_workspace(fake_nolayout, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and f["pane"] == "w9:p8" for f in fr2):
        fails += 1
        print("FAIL pane 不在 layout 应报采集错误")

    # 采集错误 3：rect width 为 bool → 拒绝（bool 是 int 子类，须显式排除）
    fake_boolrect = json.loads(json.dumps(fake))
    fake_boolrect["layouts"][0]["panes"][2]["rect"] = {"width": True, "height": 22}
    fr3 = audit_workspace(fake_boolrect, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and f["pane"] == "w9:p3" for f in fr3):
        fails += 1
        print("FAIL rect width 为 bool 应报采集错误")

    # R4-1：同 layout 重复 pane → 采集错误，且不把重复计成 5 个 pane 的容量违规
    fake_dup = json.loads(json.dumps(fake))
    fake_dup["layouts"][0]["panes"].append({"pane_id": "w9:p1", "rect": {"width": 66, "height": 45}})
    fr_dup = audit_workspace(fake_dup, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and f["pane"] == "w9:p1" and "重复" in f["actual"] for f in fr_dup):
        fails += 1
        print("FAIL 同 layout 重复 pane 应报采集错误")
    cap = [f for f in fr_dup if f["category"] == "容量"]
    if cap and "6 个 pane" in cap[0]["actual"]:
        fails += 1
        print("FAIL 重复 pane 不应把容量计成 6")

    # R4-2：跨 tab 重复 pane → 采集错误
    fake_cross = json.loads(json.dumps(fake))
    fake_cross["layouts"][1]["panes"].append({"pane_id": "w9:p1", "rect": {"width": 66, "height": 45}})
    fr_cross = audit_workspace(fake_cross, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and f["pane"] == "w9:p1" and "重复" in f["actual"] for f in fr_cross):
        fails += 1
        print("FAIL 跨 tab 重复 pane 应报采集错误")

    # R4-3：pane 声明 tab 与所在 layout tab 不一致 → 采集错误
    fake_mtab = json.loads(json.dumps(fake))
    fake_mtab["agents"][0]["tab_id"] = "w9:t2"  # w9:p1 声明 t2，但 layout 在 t1
    fr_mtab = audit_workspace(fake_mtab, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and f["pane"] == "w9:p1" and "不一致" in f["actual"] for f in fr_mtab):
        fails += 1
        print("FAIL pane 声明 tab 与 layout 不一致应报采集错误")

    # R4-4：layout 条目缺 pane_id → 采集错误
    fake_noid = json.loads(json.dumps(fake))
    fake_noid["layouts"][0]["panes"].append({"rect": {"width": 66, "height": 45}})
    fr_noid = audit_workspace(fake_noid, "w9", lambda pid, kind: fake_models.get(pid))
    if not any(f["category"] == "采集错误" and "缺 pane_id" in f["actual"] for f in fr_noid):
        fails += 1
        print("FAIL layout 条目缺 pane_id 应报采集错误")

    # R4-5：6 个唯一 pane + 1 个重复（其它 tab，上限 6）→ 只报重复，不报容量违规
    fake_dedup = {
        "workspaces": [{"workspace_id": "w9", "label": "测试"}],
        "tabs": [{"tab_id": "w9:t1", "label": "生产部", "workspace_id": "w9"}],
        "panes": [{"pane_id": "w9:p{}".format(i), "workspace_id": "w9", "tab_id": "w9:t1"} for i in range(1, 7)],
        "agents": [],
        "layouts": [{"workspace_id": "w9", "tab_id": "w9:t1", "panes": [
            {"pane_id": "w9:p{}".format(i), "rect": {"width": 66, "height": 45}} for i in range(1, 7)
        ] + [{"pane_id": "w9:p1", "rect": {"width": 66, "height": 45}}]}],
    }
    fr_dedup = audit_workspace(fake_dedup, "w9", lambda pid, kind: None)
    if not any(f["category"] == "采集错误" and "重复" in f["actual"] for f in fr_dedup):
        fails += 1
        print("FAIL 6+1 重复应报采集错误")
    if any(f["category"] == "容量" for f in fr_dedup):
        fails += 1
        print("FAIL 6 唯一 + 1 重复不应报容量违规")

    if fails:
        print("SELFTEST FAIL（{} 项）".format(fails))
        return 2
    print("SELFTEST PASS（命名 / 策划模型 / 5 种模型提取 / timeout / 全链路四项 / 采集错误三例 / 重复与一致性五例）")
    return 0


def main(argv=None):
    _setup_stdio()
    ap = argparse.ArgumentParser(
        description="只读审计指定 Herdr 工作区是否符合编排规范（命名/尺寸/容量/策划模型）",
    )
    ap.add_argument("--workspace", metavar="ID", help="要审计的工作区（如 w4）")
    ap.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT,
                    help="单次 herdr 子进程超时秒数（默认 %.0f，须为有限正数）" % DEFAULT_TIMEOUT)
    ap.add_argument("--herdr", default=HERDR_BIN, help="herdr 二进制路径（默认 PATH 里的 herdr）")
    ap.add_argument("--selftest", action="store_true", help="内存自测（不碰 herdr、不建文件），完成后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(selftest())

    if not args.workspace:
        print("参数错误：缺少 --workspace（如 --workspace w4）", file=sys.stderr)
        return 2

    snapshot = fetch_snapshot(args.timeout, args.herdr)

    ws_ids = {w.get("workspace_id") for w in snapshot.get("workspaces", [])}
    if args.workspace not in ws_ids:
        print("参数错误：工作区 {} 不存在；现有：{}".format(
            args.workspace, ", ".join(sorted(ws_ids))), file=sys.stderr)
        return 2

    def model_reader(pane_id, kind):
        return _read_pane_model(pane_id, kind, args.timeout, args.herdr)

    findings = audit_workspace(snapshot, args.workspace, model_reader)

    ws_label = next(
        (w.get("label", args.workspace) for w in snapshot.get("workspaces", [])
         if w.get("workspace_id") == args.workspace),
        args.workspace,
    )

    if findings:
        n_viol = sum(1 for f in findings if f["category"] != "采集错误")
        n_err = sum(1 for f in findings if f["category"] == "采集错误")
        parts = []
        if n_viol:
            parts.append("{} 条违规".format(n_viol))
        if n_err:
            parts.append("{} 条采集错误".format(n_err))
        print("审计工作区 {}「{}」—— {}：".format(args.workspace, ws_label, "、".join(parts)))
        for f in findings:
            print("  " + render_finding(f))
        by_cat = {}
        for f in findings:
            by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
        summary = "，".join("{} {}".format(k, by_cat.get(k, 0)) for k in CATEGORY_ORDER if k in by_cat)
        print("小结：{}。".format(summary))
        return 1

    print("通过：工作区 {}「{}」—— 命名/尺寸/容量/策划模型 四项检查无违规。".format(args.workspace, ws_label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
