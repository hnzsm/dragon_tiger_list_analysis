# -*- coding: utf-8 -*-
"""席位画像引擎：历史统计 + 知识库先验 → 席位风格画像。

口径（**唯一来源在这里**，report / SKILL.md 照抄，别在别处重写公式）：

| 指标 | 定义 |
|---|---|
| `n_days` | 区间内该席位上榜天数 |
| `n_stocks` | 区间内覆盖的股票数 |
| `buy_amt` / `sell_amt` / `net_amt` | 区间买入/卖出/净买总额（万元） |
| `avg_buy_per_day` | 日均净买入（万元） |
| `avg_chg_on_day` | 上榜日个股平均涨跌幅（%）—— 打板 vs 低吸的判别基础 |
| `board_rate` | 上榜日个股「大涨」比例：涨幅 ≥ 板块阈值(默认 9.5%) |
| `win_1d` / `avg_1d` | 买入后次日上涨概率 / 平均涨幅（只用 ACT_BUY>0 的记录，取 D1_CLOSE_ADJCHRATE；当日买入的 D1 为 null，自动排除） |
| `win_5d` / `avg_5d` | 同上，5 日 |
| `quick_flip_rate` | 「一日游」比例：买入日之后的下一交易日，该席位即在同股出现卖出 |
| `median_hold_days` | 持股周期中位数（交易日）：买入日 → 该席位下一次在同股出现的间隔 |
| `net_bias` | 净买 / (买+卖) ∈ [-1,1]，>0.3 偏买方、<-0.3 偏卖方 |
| `style_tags` | 推断风格标签（规则见 indicators.md） |

已知取舍：
* `quick_flip_rate` 用「下一交易日是否卖出」近似，席位对倒/做 T 会高估；
* `median_hold_days` 用全局交易日历算间隔，席位消失超过 30 天记 30（截断）；
* 区间末端的买入，其后验字段（D1/D5）可能还没走完，统计时按非空过滤。
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from seats_kb import kb_summary

BOARD_THR = 9.5          # 「大涨/疑似涨停」阈值（主板 10% 板留 0.5 容差）
HOLD_CAP_DAYS = 30       # 持股周期截断
QUICK_FLIP_MAX = 3       # 只认 3 个交易日内的快速反手，防止把「隔月回来」算成一曰游


def aggregate_seat_trades(rows: list[dict]) -> list[dict]:
    """RPT_OPERATEDEPT_TRADE_DETAILSNEW 原始行 → 按 (TRADE_DATE, SECURITY_CODE) 聚合。

    ⚠ 同一 (席位,股票,日) 会按**多个上榜原因重复出行，且金额完全相同**
    （2026-10-12 用开源西安西大街验证：按 (日期,代码,买入,卖出) 四元组去重后，
    与 RPT_OPERATEDEPT_ACTIVE 当日 TOTAL_BUYAMT/TOTAL_SELLAMT **逐分吻合**）。
    金额不同的行是不同榜单的真实成交（EM 自己也这么加总），保留。
    D1~D30 字段同一股票同一天相同，取任一非空即可。
    """
    bucket: dict[tuple, dict] = {}
    for r in rows:
        buy = float(r.get("ACT_BUY") or 0)
        sell = float(r.get("ACT_SELL") or 0)
        key = (r.get("TRADE_DATE", "")[:10], r.get("SECURITY_CODE") or "",
               round(buy, 2), round(sell, 2))
        if key in bucket:
            continue  # 同一 (席位,股票,日,金额) 的重复行（多个上榜原因），跳过
        b = bucket[key] = {
            "date": key[0], "code": key[1],
            "name": r.get("SECURITY_NAME_ABBR") or "",
            "buy": buy, "sell": sell, "net": buy - sell,
            "chg": None, "explain": r.get("EXPLANATION") or "",
        }
        if r.get("CHANGE_RATE") is not None:
            b["chg"] = float(r["CHANGE_RATE"])
        for f, tag in (("D1_CLOSE_ADJCHRATE", "d1"), ("D2_CLOSE_ADJCHRATE", "d2"),
                       ("D3_CLOSE_ADJCHRATE", "d3"), ("D5_CLOSE_ADJCHRATE", "d5"),
                       ("D10_CLOSE_ADJCHRATE", "d10")):
            v = r.get(f)
            if v is not None and b.get(tag) is None:
                b[tag] = float(v)
    out = list(bucket.values())
    out.sort(key=lambda x: (x["date"], x["code"]))
    return out


def _next_trading_gap(trading_days: list[str], d0: str, d1: str) -> int:
    """d0 -> d1 的交易日间隔；任一日期不在日历里返回 None。"""
    try:
        i0 = trading_days.index(d0)
        i1 = trading_days.index(d1)
    except ValueError:
        return None
    return i1 - i0


def compute_profile(agg_trades: list[dict], trading_days: list[str],
                    back_profile: list[dict] | None = None,
                    window_start: str = "", window_end: str = "") -> dict:
    """聚合后的席位流水 → 统计画像。"""
    if not agg_trades:
        return {"empty": True}

    n_days = len({t["date"] for t in agg_trades})
    n_stocks = len({t["code"] for t in agg_trades})
    buy_amt = sum(t["buy"] for t in agg_trades) / 1e4
    sell_amt = sum(t["sell"] for t in agg_trades) / 1e4
    net_amt = buy_amt - sell_amt

    # ---- 打板/低吸判别 ----
    chgs = [t["chg"] for t in agg_trades if t["chg"] is not None]
    avg_chg_on_day = statistics.fmean(chgs) if chgs else None
    board_rate = (sum(1 for c in chgs if c >= BOARD_THR) / len(chgs)) if chgs else None

    # ---- 后验收益（买入记录）----
    def _fwd(tag: str):
        vals = [t[tag] for t in agg_trades if t["buy"] > 0 and t.get(tag) is not None]
        if not vals:
            return None, None, 0
        return (round(sum(1 for v in vals if v > 0) / len(vals), 4),
                round(statistics.fmean(vals), 3), len(vals))

    win_1d, avg_1d, n_1d = _fwd("d1")
    win_5d, avg_5d, n_5d = _fwd("d5")

    # ---- 持股周期 & 一日游 ----
    by_stock: dict[str, list[dict]] = defaultdict(list)
    for t in agg_trades:
        by_stock[t["code"]].append(t)
    holds: list[int] = []
    flips = 0
    buy_days = 0
    for code, recs in by_stock.items():
        recs.sort(key=lambda x: x["date"])
        for i, r in enumerate(recs):
            if r["buy"] <= 0:
                continue
            buy_days += 1
            # 持股周期：下一次在同股出现的间隔（截断到 HOLD_CAP_DAYS）
            nxt = None
            for r2 in recs[i + 1:]:
                gap = _next_trading_gap(trading_days, r["date"], r2["date"])
                if gap and gap > 0:
                    nxt = r2
                    break
            if nxt is not None:
                gap = _next_trading_gap(trading_days, r["date"], nxt["date"])
                holds.append(min(gap or HOLD_CAP_DAYS, HOLD_CAP_DAYS))
                # 一日游：下一交易日即卖出
                if gap == 1 and nxt["sell"] > 0 and nxt["net"] < 0:
                    flips += 1
    median_hold = statistics.median(holds) if holds else None
    quick_flip_rate = (flips / buy_days) if buy_days else None

    net_bias = (net_amt / (buy_amt + sell_amt)) if (buy_amt + sell_amt) > 0 else None

    # ---- 官方回测画像（东财 RPT_TRADE_BACK_PROFILE，取近三月行）----
    official = None
    if back_profile:
        row = next((r for r in back_profile if r.get("STATISTICSCYCLENAME") == "近三月"), None) \
            or (back_profile[0] if back_profile else None)
        if row:
            official = {
                "cycle": row.get("STATISTICSCYCLENAME"),
                "rise_prob_1d": row.get("RISE_PROBABILITY_1DAY"),
                "avg_inc_1d": row.get("AVERAGE_INCREASE_1DAY"),
                "rise_prob_5d": row.get("RISE_PROBABILITY_5DAY"),
                "avg_inc_5d": row.get("AVERAGE_INCREASE_5DAY"),
                "n_1d": row.get("TOTAL_BUYER_SALESTIMES_1DAY"),
            }

    profile = {
        "empty": False,
        "window": [window_start, window_end],
        "n_days": n_days, "n_stocks": n_stocks,
        "buy_amt": round(buy_amt, 1), "sell_amt": round(sell_amt, 1),
        "net_amt": round(net_amt, 1),
        "avg_buy_per_day": round(net_amt / n_days, 1) if n_days else None,
        "avg_chg_on_day": round(avg_chg_on_day, 2) if avg_chg_on_day is not None else None,
        "board_rate": round(board_rate, 3) if board_rate is not None else None,
        "win_1d": win_1d, "avg_1d": avg_1d, "n_1d": n_1d,
        "win_5d": win_5d, "avg_5d": avg_5d, "n_5d": n_5d,
        "quick_flip_rate": round(quick_flip_rate, 3) if quick_flip_rate is not None else None,
        "n_buy_days": buy_days,        # 一日游比例的分母，样本量提示用
        "median_hold_days": median_hold,
        "net_bias": round(net_bias, 3) if net_bias is not None else None,
        "official_backtest": official,
    }
    profile["style_tags"] = infer_style(profile)
    return profile


def infer_style(p: dict) -> list[str]:
    """统计特征 → 风格标签（规则写死在这里，改规则要同步 indicators.md）。"""
    tags: list[str] = []
    if p.get("net_bias") is not None:
        if p["net_bias"] >= 0.3:
            tags.append("净买方")
        elif p["net_bias"] <= -0.3:
            tags.append("净卖方")
        else:
            tags.append("双向对倒")
    if p.get("avg_chg_on_day") is not None and p.get("board_rate") is not None:
        if p["avg_chg_on_day"] >= 5 and p["board_rate"] >= 0.4:
            tags.append("打板倾向")
        elif p["avg_chg_on_day"] <= 1:
            tags.append("低吸倾向")
        else:
            tags.append("半路/接力")
    if p.get("quick_flip_rate") is not None:
        if p["quick_flip_rate"] >= 0.5:
            tags.append("一日游")
        elif p["quick_flip_rate"] <= 0.15 and (p.get("median_hold_days") or 0) >= 3:
            tags.append("波段/趋势")
    if p.get("win_1d") is not None:
        if p["win_1d"] >= 0.6:
            tags.append("次日溢价强")
        elif p["win_1d"] <= 0.4:
            tags.append("次日溢价弱")
    return tags


def full_profile(seat_code: str, seat_name: str, agg_trades: list[dict],
                 trading_days: list[str], back_profile: list[dict] | None = None,
                 window_start: str = "", window_end: str = "") -> dict:
    """统计画像 + KB 先验合并。"""
    p = compute_profile(agg_trades, trading_days, back_profile, window_start, window_end)
    kb = kb_summary(seat_name)
    return {
        "seat_code": seat_code,
        "seat_name": seat_name,
        "kb": kb,                      # None = KB 未收录（新面孔/普通席位）
        "stats": p,
    }
