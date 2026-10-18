#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""herdr-status.py — 读取本机 Herdr 会话的工作区/页面/pane/agent 现状并打印状态表。

只读：仅调用 `herdr api snapshot`（一次）与 `herdr pane read --source visible`（逐 pane），
不 prompt / send-keys / zoom / close / resize，不动任何 pane。

模型口径：
- 只从 pane「当前状态栏」提取：先按各客户端的提示区 / 状态行结构锚定状态栏位置，
  再在锚点内找模型；聊天历史里出现的模型示例一律不认。
- 覆盖的状态行格式：codex / claude（在用的三个 kind 里，opencode 尚未解析 → 显示「未知」）。
  另保留 qodercli / pi / omp 的解析器 —— 这三个 kind 已于 2026-10-18 停用，仅作兼容，不代表允许派活。
- claude 保留槽位别名（Fable / Opus / Sonnet / Haiku），不解析成真实后端模型。
- 提取不到 → 标「未知」；无 agent 的 pane → 模型列标「—」。

尺寸口径：取自 snapshot 的 `layouts[].panes[].rect`（含边框）。
          阈值「<60 列 或 <15 行」按同一 rect 口径判断，超标的在表内标 ⚠。

纯标准库，无第三方依赖，可用 `python -I` 直接运行。
"""

import argparse
import json
import math
import re
import subprocess
import sys
import unicodedata

HERDR_BIN = "herdr"
DEFAULT_TIMEOUT = 10.0
MIN_COLS = 60
MIN_ROWS = 15

COLUMNS = ["页面", "pane", "agent 名", "kind", "状态", "尺寸", "模型"]


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


# --------------------------------------------------------------------------
# 显示宽度（CJK 感知）：东亚全角/宽字符按 2 列算，组合字符按 0 列算。
# 表头「页面/agent 名/状态/尺寸/模型」含中文，不对齐会歪。
# --------------------------------------------------------------------------
def disp_width(text):
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def pad_to(text, width):
    text = str(text)
    cur = disp_width(text)
    if cur >= width:
        return text
    return text + " " * (width - cur)


# --------------------------------------------------------------------------
# 子进程封装：超时 + 编码 + 错误统一处理。
# --------------------------------------------------------------------------
def run_herdr(args, timeout=DEFAULT_TIMEOUT, herdr_bin=HERDR_BIN):
    try:
        proc = subprocess.run(
            [herdr_bin] + args, capture_output=True, timeout=timeout
        )
    except FileNotFoundError:
        raise SystemExit("找不到 herdr 二进制（PATH 里没有 herdr）")
    except subprocess.TimeoutExpired:
        raise SystemExit(
            "herdr 子进程超时（>{:.0f}s）：herdr {}".format(timeout, " ".join(args))
        )
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    return out, err, proc.returncode


def _brief(obj, n=200):
    s = str(obj)
    return s if len(s) <= n else s[:n] + "…"


def _validate_snapshot(data):
    """校验 api snapshot 的 JSON 结构；不合法抛 SystemExit（供内存自测直接调用）。"""
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
# 模型提取：只认「状态行」里的固定格式，不猜聊天历史。
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 模型提取：只认各客户端「底部状态栏」里的固定格式，不猜聊天历史。
# 关键：先按各家的 UI 结构锚定状态栏位置（提示区 / 状态行签名），只在锚点之后
# （codex/claude/qodercli 的提示区下方）或锚点那一行（pi/omp 的状态行）找模型；
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
    """从底部往上找最后一个匹配 pattern 的行号（优先真正最底部）；找不到返回 None。"""
    for i in range(len(lines) - 1, -1, -1):
        if re.search(pattern, lines[i]):
            return i
    return None


def _last_separator_index_after(lines, i):
    """返回 i 之后最后一条「Unicode 横线 ─ 分隔线」（排除 ASCII ---）的行号；找不到返回 None。"""
    for j in range(len(lines) - 1, i, -1):
        if re.match(r"^\s*─{3,}", lines[j]):
            return j
    return None


def _extract_codex(lines):
    # Codex：先锚定最后一个 `›` 输入框，只在其后找模型行。
    # 模型行 = 整行以 GPT 开头（允许空白）、匹配「模型 + effort + `·`」，
    # 且上一行是空行（输入框与模型行之间的空行边界）；否则可能是输入折行，保守判未知。
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
    # Claude：先锚定最后一个 `❯` 输入框，再取其下方最后一条 Unicode ─ 分隔线，
    # 模型 `[...]` 只取该分隔线之后、且整行以 `[` 开头的那一行。
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
    # qodercli：先锚定最后一个 `*` 输入框，再取其下方最后一条 Unicode ─ 分隔线，
    # 模型 `DeepSeek-…` 只取该分隔线之后、且整行以 DeepSeek 开头的那一行。
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
# 组装行：snapshot 的 layouts 提供 pane 顺序与 rect，agents 提供 name/kind/状态。
# --------------------------------------------------------------------------
def _pane_sort_key(pane_id):
    m = re.search(r"(\d+)\s*$", pane_id)
    return (0, int(m.group(1))) if m else (1, pane_id)


def build_rows(snapshot, workspace_id=None):
    tabs = {t.get("tab_id"): t for t in snapshot.get("tabs", [])}
    agents = {a.get("pane_id"): a for a in snapshot.get("agents", [])}
    panes = {p.get("pane_id"): p for p in snapshot.get("panes", [])}

    rows = []
    for layout in snapshot.get("layouts", []):
        wsid = layout.get("workspace_id")
        if workspace_id and wsid != workspace_id:
            continue
        tab = tabs.get(layout.get("tab_id"), {})
        page = tab.get("label") if tab.get("label") is not None else "?"

        lp_panes = sorted(layout.get("panes", []), key=lambda p: _pane_sort_key(p.get("pane_id", "")))
        for lp in lp_panes:
            pid = lp.get("pane_id", "?")
            rect = lp.get("rect", {})
            w, h = rect.get("width"), rect.get("height")
            if isinstance(w, int) and isinstance(h, int):
                size = "{}×{}".format(w, h)
                if w < MIN_COLS or h < MIN_ROWS:
                    size += " ⚠"
            else:
                size = "?"

            pane = panes.get(pid, {})
            ag = agents.get(pid, {})
            kind = ag.get("agent") or pane.get("agent")
            name = ag.get("name")
            status = ag.get("agent_status") or pane.get("agent_status") or "unknown"

            if not kind:
                kind, name, status = "—", "—", "—"

            rows.append({
                "workspace_id": wsid,
                "tab_id": layout.get("tab_id"),
                "page": str(page),
                "pane": pid,
                "name": name if name else "（未命名）",
                "kind": kind,
                "status": status,
                "size": size,
                "rect": (w, h),
                "_kind_for_model": kind if kind not in ("—", None) else None,
            })
    return rows


def read_model_for_row(row, timeout=DEFAULT_TIMEOUT, herdr_bin=HERDR_BIN):
    kind = row["_kind_for_model"]
    if not kind:
        return "—"
    out, _err, code = run_herdr(
        ["pane", "read", row["pane"], "--source", "visible", "--format", "text"],
        timeout,
        herdr_bin,
    )
    if code != 0:
        return "未知"
    return extract_model(kind, out)


# --------------------------------------------------------------------------
# 表格渲染（CJK 对齐）。
# --------------------------------------------------------------------------
def render_table(rows):
    data = [[r["page"], r["pane"], r["name"], r["kind"], r["status"], r["size"], r["model"]] for r in rows]
    widths = [disp_width(h) for h in COLUMNS]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], disp_width(cell))

    lines = []
    lines.append("  ".join(pad_to(h, widths[i]) for i, h in enumerate(COLUMNS)))
    lines.append("  ".join("-" * widths[i] for i in range(len(COLUMNS))))
    for row in data:
        lines.append("  ".join(pad_to(cell, widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 自测：全部在内存里跑，不建测试文件、不碰 herdr。
# --------------------------------------------------------------------------
def selftest():
    cases = [
        # (kind, 状态行文本, 期望)
        # codex：最后一个 `›` 之后、空行边界下方、整行 GPT 开头的模型行
        ("codex", "› Ask Codex to do anything\n\n  GPT-6.1-Sol low · E:\\YX\\yx-e…\n  ← for agents · ? f  ⚠ 7 · f2", "GPT-6.1-Sol low"),
        ("codex", "› Ask Codex to do anything\n\n  GPT-6.1-Sol high · E:\\XY · Context 87% left\n  New activity · enter/esc", "GPT-6.1-Sol high"),
        # codex 回归：输入框文本含 GPT-9.9 high，但真实模型行在空行之下
        ("codex", "› Please compare GPT-9.9 high\n\n  GPT-6.1-Sol low · E:\\YX\n  ← for agents", "GPT-6.1-Sol low"),
        # codex 回归：聊天示例（带 ·）在 `›` 上方 → 取最底部真实模型行
        ("codex", "参考：GPT-9.9 high · E:\\YX\n› Ask Codex to do anything\n\n  GPT-6.1-Sol low · E:\\XY\n  ← for agents", "GPT-6.1-Sol low"),
        # codex 反例 1：Reference 前缀在 `›` 上方 → 未知
        ("codex", "Reference: GPT-9.9 high · E:\\example\n› Ask Codex to do anything\n ← for agents", "未知"),
        # codex 反例 2：无空行边界，可能是输入折行 → 未知
        ("codex", "› Please check this example:\n GPT-9.9 high · E:\\example\n ← for agents", "未知"),
        # claude：最后一个 `❯` 之后、最后一条 Unicode ─ 分隔线之下、整行 `[` 开头
        ("claude", "──────────────────────\n❯\n──────────────────────\n  [Opus 5 (1M context)] │ yx-erp git:(rename/yuanxin-erp)\n  3 MCPs | 1 hooks", "Opus 5"),
        ("claude", "❯ Press up to edit queued messages\n──────\n  [Fable 5] │ XY git:(main*)\n  Context █░░░ 11%", "Fable 5"),
        ("claude", "❯\n──────\n  [Sonnet 5 (200k context)]", "Sonnet 5"),
        ("claude", "❯\n──────\n  [Haiku 4.5]", "Haiku 4.5"),
        # claude 回归：输入框文本里的 [Fable 5] 不算
        ("claude", "❯ Please compare [Fable 5]\n───\n [Opus 5 (1M context)]\n 3 MCPs | 1 hooks", "Opus 5"),
        # claude 反例：聊天里的槽位别名示例在输入框上方 → 不算
        ("claude", "参考状态行 [Opus 5 (1M context)]\n❯\n──────\n  Context █░░░ 36%\n  3 MCPs | 1 hooks", "未知"),
        # claude 反例 3：输入正文含 Markdown --- 与伪模型，只认最后一条 ─── 下的真模型
        ("claude", "❯ Please compare:\n---\n[Fake 5]\nEnd quote\n───\n[Opus 5 (1M context)]", "Opus 5"),
        # qodercli：最后一个 `*` 之后、最后一条 Unicode ─ 分隔线之下、整行 DeepSeek 开头
        ("qodercli", "──────\n *   Type your message or\n   @path/to/file\n──────\n DeepSeek-Flash (DeepSeek) M…", "DeepSeek-Flash (DeepSeek)"),
        # qodercli 回归：输入框文本里的 DeepSeek-Fake (Example) 不算
        ("qodercli", "* Please compare DeepSeek-Fake (Example)\n───\n DeepSeek-Flash (DeepSeek) Model", "DeepSeek-Flash (DeepSeek)"),
        # qodercli 反例：聊天示例在输入框上方 → 不算
        ("qodercli", "参考状态行 DeepSeek-Flash (DeepSeek)\n *   Type your message or @path/to/file\n──────\n 1 MCP server · 24 skills", "未知"),
        # qodercli 反例 3：输入正文含 Markdown --- 与伪模型，只认最后一条 ─── 下的真模型
        ("qodercli", "* Please compare:\n---\nDeepSeek-Fake (Example)\nEnd quote\n───\nDeepSeek-Flash (DeepSeek) M…", "DeepSeek-Flash (DeepSeek)"),
        # pi：状态行 = 含 `↑…↓` 的那一行，模型只在该行右侧
        ("pi", "E:\\YX\\yx-erp (rename/yuanxin-erp) ↑131k ↓114k R20M CH99.7% deepseek-flash • medium", "deepseek-flash • medium"),
        # pi 反例：聊天完整示例 + 真实状态行（无模型）→ 未知
        ("pi", "模型是 deepseek-flash • medium\n本项任务结束，保持 idle。\nE:\\YX\\yx-erp (rename/yuanxin...\n↑131k ↓114k R20M CH99.7% 22....", "未知"),
        # omp：状态行 = 最底部 `π >` 那一行，模型只在该行且后面跟 `>`
        ("omp", "π > ◒ DeepSeek V4.1 Flash > 📁 E:\\YX > ⑂ main > $0.00 …", "DeepSeek V4.1 Flash"),
        # omp 反例：聊天完整示例 + 真实状态行（无模型）→ 未知
        ("omp", "参考：π > ◒ DeepSeek V4.1 Flash > 📁 E:\\YX > ⑂ main\nπ > 📁 …-erp ▶─────44%──┃─1M─\n╰─", "未知"),
        ("omp", "π > ◒ DeepSeek V4.1 …", "未知"),  # 半截模型名不算
        (None, "whatever", "未知"),
    ]
    fails = 0
    for kind, text, want in cases:
        got = extract_model(kind, text)
        if got != want:
            fails += 1
            print("FAIL extract_model({!r}, ...) = {!r} 期望 {!r}".format(kind, got, want))

    # snapshot 结构校验：null / [] / 缺字段都要明确报错，不 traceback
    bad_snaps = [
        None,
        [],
        {"result": None},
        {"result": {"snapshot": None}},
        {"result": {"snapshot": []}},
        {"result": {"snapshot": {"workspaces": None, "tabs": [], "panes": [], "agents": [], "layouts": []}}},
        {"result": {"snapshot": {"workspaces": [], "tabs": [], "panes": [], "agents": [], "layouts": None}}},
        {"result": {"snapshot": {"workspaces": [None], "tabs": [], "panes": [], "agents": [], "layouts": []}}},
        {"result": {"snapshot": {"workspaces": [], "tabs": [], "panes": [], "agents": [], "layouts": [{"panes": None}]}}},
        {"result": {"snapshot": {"workspaces": [], "tabs": [], "panes": [], "agents": [], "layouts": [{"panes": [{"pane_id": "p1", "rect": None}]}]}}},
    ]
    for bad in bad_snaps:
        try:
            _validate_snapshot(bad)
            fails += 1
            print("FAIL _validate_snapshot({!r}) 应抛 SystemExit".format(bad))
        except SystemExit:
            pass
    good = {"result": {"snapshot": {"workspaces": [], "tabs": [], "panes": [], "agents": [], "layouts": [{"panes": [{"pane_id": "p1", "rect": {"width": 66, "height": 45}}]}]}}}
    if _validate_snapshot(good) is not good["result"]["snapshot"]:
        fails += 1
        print("FAIL _validate_snapshot 应返回 snapshot 对象")

    # --timeout 校验：NaN/Inf/0/负数拒绝，正数放行
    for bad in ("nan", "NaN", "inf", "-inf", "0", "-1", "0.0"):
        try:
            _positive_float(bad)
            fails += 1
            print("FAIL _positive_float({!r}) 应抛 ArgumentTypeError".format(bad))
        except argparse.ArgumentTypeError:
            pass
    if _positive_float("5") != 5.0 or _positive_float("0.5") != 0.5:
        fails += 1
        print("FAIL _positive_float 正数应放行")

    # 显示宽度 / 对齐
    if disp_width("模型") != 4:
        fails += 1
        print("FAIL disp_width(模型) = {} 期望 4".format(disp_width("模型")))
    if disp_width("a模型") != 5:
        fails += 1
        print("FAIL disp_width(a模型) = {} 期望 5".format(disp_width("a模型")))
    if disp_width("✓") != 1:
        fails += 1
        print("FAIL disp_width(✓) = {} 期望 1".format(disp_width("✓")))

    # 组装行：未命名 agent 占位、无 agent 标「—」、尺寸超标（含 0 尺寸）标 ⚠、None 尺寸标「?」
    fake_snap = {
        "tabs": [{"tab_id": "w9:t1", "label": "1"}],
        "layouts": [{
            "workspace_id": "w9", "tab_id": "w9:t1",
            "panes": [
                {"pane_id": "w9:p1", "rect": {"width": 66, "height": 45}},
                {"pane_id": "w9:p2", "rect": {"width": 33, "height": 22}},
                {"pane_id": "w9:p3", "rect": {"width": 33, "height": 11}},
                {"pane_id": "w9:p4", "rect": {"width": 0, "height": 20}},
                {"pane_id": "w9:p5", "rect": {"width": None, "height": 20}},
            ],
        }],
        "agents": [
            {"pane_id": "w9:p1", "agent": "claude", "name": None, "agent_status": "idle"},
            {"pane_id": "w9:p2", "agent": "codex", "name": "planner", "agent_status": "working"},
        ],
        "panes": [
            {"pane_id": "w9:p1", "agent": "claude", "agent_status": "idle"},
            {"pane_id": "w9:p2", "agent": "codex", "agent_status": "working"},
            {"pane_id": "w9:p3", "agent": None, "agent_status": "unknown"},
            {"pane_id": "w9:p4", "agent": None, "agent_status": "unknown"},
            {"pane_id": "w9:p5", "agent": None, "agent_status": "unknown"},
        ],
    }
    r = build_rows(fake_snap, "w9")
    got_names = [x["name"] for x in r]
    if got_names != ["（未命名）", "planner", "—", "—", "—"]:
        fails += 1
        print("FAIL 组装行 name = {} 期望 ['（未命名）','planner','—','—','—']".format(got_names))
    got_sizes = [x["size"] for x in r]
    want_sizes = ["66×45", "33×22 ⚠", "33×11 ⚠", "0×20 ⚠", "?"]
    if got_sizes != want_sizes:
        fails += 1
        print("FAIL 组装行 size = {} 期望 {}".format(got_sizes, want_sizes))

    if fails:
        print("SELFTEST FAIL（{} 项）".format(fails))
        return 2
    print("SELFTEST PASS（模型锚定 5 格式 / 输入框与聊天不猜 / snapshot 嵌套校验 / timeout 校验 / CJK 宽度 / 占位与 ⚠）")
    return 0


def _positive_float(s):
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError("必须是数字")
    if not (math.isfinite(v) and v > 0):
        raise argparse.ArgumentTypeError("必须是有限正数（>0，非 NaN/Inf/0/负数）")
    return v


def main(argv=None):
    _setup_stdio()
    ap = argparse.ArgumentParser(
        description="读取 Herdr 工作区状态并打印表格（只读）",
    )
    ap.add_argument("--workspace", metavar="ID", help="只显示该工作区（如 w4）；缺省显示全部")
    ap.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT, help="单次 herdr 子进程超时秒数（默认 %.0f，须为有限正数）" % DEFAULT_TIMEOUT)
    ap.add_argument("--herdr", default=HERDR_BIN, help="herdr 二进制路径（默认 PATH 里的 herdr）")
    ap.add_argument("--selftest", action="store_true", help="内存自测（不碰 herdr、不建文件），完成后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(selftest())

    snapshot = fetch_snapshot(args.timeout, args.herdr)

    # 校验 --workspace 是否真实存在
    ws_ids = {w.get("workspace_id") for w in snapshot.get("workspaces", [])}
    if args.workspace and args.workspace not in ws_ids:
        raise SystemExit("工作区 {} 不存在；现有：{}".format(args.workspace, ", ".join(sorted(ws_ids))))

    rows = build_rows(snapshot, args.workspace)
    if not rows:
        raise SystemExit("没有可显示的 pane（工作区 {} 可能为空）".format(args.workspace or "全部"))

    for row in rows:
        row["model"] = read_model_for_row(row, args.timeout, args.herdr)

    # 标题行（给出来源工作区，页面列仍是 tab 标签）
    shown_ws = sorted({r["workspace_id"] for r in rows})
    ws_labels = []
    for wid in shown_ws:
        lab = next((w.get("label", wid) for w in snapshot.get("workspaces", []) if w.get("workspace_id") == wid), wid)
        ws_labels.append("{}「{}」".format(wid, lab))
    print("工作区 {} · {} 个 pane".format(" + ".join(ws_labels), len(rows)))
    print(render_table(rows))
    print("注：尺寸 = layout.rect（含边框），<{}列或<{}行标 ⚠；模型取自 pane 当前状态行，缺失标「未知」。".format(MIN_COLS, MIN_ROWS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
