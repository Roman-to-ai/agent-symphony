#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按人数把一个 tab 的窗格切成规整网格。

herdr **没有** tile / balance / auto-scale —— `pane split` 只会在现有空间里
继续切，切几刀必碎。所以「按区域自动划分」得自己算比例。

这个脚本就干一件事：给一个 tab 的根 pane 和人数 N，切出 N 个等分窗格，
**并校验每个窗格都 ≥60 列 × 15 行**（低于这个 agent 状态行会被截断，
连模型都验不了）。

用法
----
    python -I herdr-layout.py --pane <root_pane_id> --count N [--mode grid|secretary]

    --mode grid  （默认）2 列均衡排布 —— 部门页用
    --mode secretary  secretary 占左半边，其余在右半边竖排 —— 秘书页用

输出：每行一个 pane_id（按位置从上到下、从左到右），调用方直接拿去 agent start。

示例
----
    # 部门页：一共 5 格（根 pane 算第 1 格）
    IDS=$(python -I herdr-layout.py --pane <root> --count 5 --mode grid)
    # → 打印 4 个新 pane_id；加上 <root> 一共 5 格

    # 秘书页：secretary + 3 个策划者 = 4 格
    # ⚠️ --pane 必须是 **secretary 自己那个 pane**（$HERDR_PANE_ID）。
    #    不要新开 tab 拿它的 root 当占位 —— 那是虚构的 secretary，用户看不到对话窗口。
    IDS=$(python -I herdr-layout.py --pane "$HERDR_PANE_ID" --count 4 --mode secretary)
    # → 打印 3 个 pane_id（右半边）；左半边就是你（secretary）

⚠️ `--count` 是**总格数，含 `--pane` 指的那个根窗格**。
   grid 模式返回 count-1 个；secretary 模式返回 count-1 个（左半边留给 secretary）。
"""
import argparse
import json
import subprocess
import sys

# Windows 控制台默认是 GBK，中文与 ✓✗ 会乱码 —— 本工作区的脚本都这么做
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

MIN_W = 60
MIN_H = 15


def herdr(*args):
    """跑一条 herdr 命令，返回 result。失败直接抛，别静默。"""
    p = subprocess.run(["herdr", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit("herdr 失败（退出码 %d）：%s\n%s"
                         % (p.returncode, " ".join(args), p.stderr.strip()))
    try:
        return json.loads(p.stdout)["result"]
    except (json.JSONDecodeError, KeyError) as e:
        raise SystemExit("herdr 返回解析失败：%s\n%s" % (e, p.stdout[:400]))


def split(pane, direction, ratio):
    """切一刀，返回新窗格 id。"""
    return herdr("pane", "split", "--pane", pane, "--direction", direction,
                 "--ratio", str(ratio), "--no-focus")["pane"]["pane_id"]


def split_rows(pane, k):
    """把一个窗格竖向切成 k 个等高行，返回 k 个 pane_id（上到下）。"""
    panes = [pane]
    remaining = k
    while remaining > 1:
        target = panes[-1]
        # ratio = 目标保留的比例；切出后新窗格拿剩下的
        new = split(target, "down", 1.0 / remaining)
        panes = panes[:-1] + [target, new]
        remaining -= 1
    return panes


def layout_grid(root, n):
    """2 列均衡网格，返回 n 个新 pane_id。root 本身也算一格。"""
    if n <= 1:
        return []
    if n == 2:
        return [split(root, "right", 0.5)]
    left_n = (n + 1) // 2          # 左列多分一个
    right_n = n - left_n
    right_root = split(root, "right", 0.5)
    left_rows = split_rows(root, left_n)          # 含 root
    right_rows = split_rows(right_root, right_n)  # 含 right_root
    # 返回除 root 以外的，按"左列自上而下、右列自上而下"
    return left_rows[1:] + right_rows


def layout_secretary(root, n):
    """secretary 占左半边；右半边竖排 n 个。返回 n 个 pane_id。"""
    right_root = split(root, "right", 0.5)
    return split_rows(right_root, n)


def check_sizes(pane_ids):
    """读布局，报告每个窗格尺寸；有任何一格低于标准就警告。"""
    if not pane_ids:
        return True
    r = herdr("pane", "layout", "--pane", pane_ids[0])
    area = r["layout"]["area"]
    bad = []
    print("# 区域 %d×%d" % (area["width"], area["height"]), file=sys.stderr)
    for p in r["layout"]["panes"]:
        w, h = p["rect"]["width"], p["rect"]["height"]
        ok = w >= MIN_W and h >= MIN_H
        print("#   %s %-7s %3d×%-3d %s"
              % ("✓" if ok else "✗", p["pane_id"], w, h, "" if ok else "← 低于 60×15"),
              file=sys.stderr)
        if not ok:
            bad.append(p["pane_id"])
    return not bad


def main():
    ap = argparse.ArgumentParser(description="把 tab 切成规整网格（herdr 没有 tile）")
    ap.add_argument("--pane", required=True, help="该 tab 的根 pane id")
    ap.add_argument("--count", type=int, required=True,
                    help="总格数（含 --pane 指的根窗格）")
    ap.add_argument("--mode", choices=["grid", "secretary"], default="grid")
    a = ap.parse_args()

    if a.count < 1:
        raise SystemExit("--count 至少是 1")

    if a.mode == "grid":
        ids = layout_grid(a.pane, a.count)          # 返回 count-1 个新窗格
    else:                                           # 根窗格留给 secretary
        ids = layout_secretary(a.pane, a.count - 1) if a.count > 1 else []

    ok = check_sizes(ids)
    for i in ids:
        print(i)
    if not ok:
        print("# ⚠️ 有窗格低于 %d×%d —— agent 状态行会被截断，连模型都验不了。"
              % (MIN_W, MIN_H), file=sys.stderr)
        print("#    要么减少人数，要么另开一个 tab。", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
