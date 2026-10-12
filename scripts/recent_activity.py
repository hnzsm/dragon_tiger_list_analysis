# -*- coding: utf-8 -*-
"""近期操作风格二次分析：当日/近 N 日实际打法 vs 历史基线。

输入：同一席位在观察窗口内的聚合流水（aggregate_seat_trades 的输出）。
切分：近 `recent_days` 个交易日 = 「近期」；窗口内更早部分 = 「基线」。

输出每个席位的 `recent` 结论（口径见 references/indicators.md）：
* `net_shift`   近 N 日日均净买入 − 基线日均净买入（万元/日）
* `chg_shift`   近 N 日上榜股平均涨幅 − 基线（>0 说明打法变激进/更追高）
* `flip_shift`  近 N 日一日游比例 − 基线
* `breadth`     近 N 日覆盖股票数 / 基线日均覆盖数（发散度变化）
* `drift`       风格漂移标签列表（如「由低吸转打板」「由波段转一日游」）
* `verdict`     一句话结论

市场级汇总（market_summary）：
* 当日净买入/净卖出席位 TOP
* 知名席位（KB 命中）当日动向
* 新面孔（基线零记录但当日大额）
"""
from __future__ import annotations

import statistics

from seat_profile import compute_profile, infer_style

NEW_FACE_MIN_BUY = 3000.0   # 新面孔判定：当日买入 ≥ 3000 万


def split_recent(agg_trades: list[dict], trading_days: list[str],
                 today: str, recent_days: int) -> tuple[list[dict], list[dict], list[str]]:
    """按 today 往前 recent_days 个交易日切 (近期, 基线, 近期日期列表)。"""
    if today not in trading_days:
        # 今天不在日历（停市/数据未出）就用窗口最后一天
        recent_set = set(trading_days[-recent_days:]) if trading_days else set()
    else:
        i = trading_days.index(today)
        recent_set = set(trading_days[max(0, i - recent_days + 1): i + 1])
    recent = [t for t in agg_trades if t["date"] in recent_set]
    baseline = [t for t in agg_trades if t["date"] not in recent_set]
    return recent, baseline, sorted(recent_set)


def analyze_seat_recent(agg_trades: list[dict], trading_days: list[str],
                        today: str, recent_days: int = 5) -> dict:
    recent, baseline, recent_dates = split_recent(agg_trades, trading_days, today, recent_days)
    if not recent:
        return {"empty": True, "recent_dates": recent_dates}

    rp = compute_profile(recent, trading_days, window_start=recent_dates[0] if recent_dates else "",
                         window_end=recent_dates[-1] if recent_dates else "")
    bp = compute_profile(baseline, trading_days) if baseline else None

    def _shift(rk, bk, scale=1.0):
        rv = rp.get(rk)
        bv = (bp or {}).get(bk)
        if rv is None or bv is None:
            return None
        return round((rv - bv) * scale, 2)

    out = {
        "empty": False,
        "recent_dates": recent_dates,
        "recent_profile": rp,
        "baseline_profile": bp,
        "net_shift": _shift("avg_buy_per_day", "avg_buy_per_day"),
        "chg_shift": _shift("avg_chg_on_day", "avg_chg_on_day"),
        "flip_shift": _shift("quick_flip_rate", "quick_flip_rate"),
        "bias_shift": _shift("net_bias", "net_bias"),
        "recent_stocks": sorted({t["name"] for t in recent}),
        "recent_net_amt": rp.get("net_amt"),
        "recent_win_1d": rp.get("win_1d"),
        "baseline_win_1d": (bp or {}).get("win_1d"),
        "baseline_n_days": (bp or {}).get("n_days"),
        "is_new_face": (bp is None or bp.get("n_days", 0) == 0),
    }
    out["drift"] = _drift_tags(rp, bp)
    out["verdict"] = _verdict(out)
    return out


def _drift_tags(rp: dict, bp: dict | None) -> list[str]:
    tags: list[str] = []
    if not bp or bp.get("empty"):
        return tags
    r_tags, b_tags = set(infer_style(rp)), set(infer_style(bp))
    if "打板倾向" in r_tags and "打板倾向" not in b_tags:
        tags.append("转打板")
    if "低吸倾向" in r_tags and "低吸倾向" not in b_tags:
        tags.append("转低吸")
    if "一日游" in r_tags and "一日游" not in b_tags:
        tags.append("转一日游")
    if "波段/趋势" in r_tags and "波段/趋势" not in b_tags:
        tags.append("转波段")
    if "净买方" in r_tags and "净卖方" in b_tags:
        tags.append("由卖转买")
    if "净卖方" in r_tags and "净买方" in b_tags:
        tags.append("由买转卖")
    return tags


def _verdict(o: dict) -> str:
    if o["empty"]:
        return "近 N 日无操作记录"
    parts = []
    if o.get("net_shift") is not None:
        parts.append(f"日均净买 {o['net_shift']:+.1f} 万 vs 基线")
    if o.get("chg_shift") is not None and abs(o["chg_shift"]) >= 1.5:
        parts.append(f"上榜股涨幅 {o['chg_shift']:+.1f}pct（更{'追高' if o['chg_shift'] > 0 else '保守'}）")
    if o.get("drift"):
        parts.append("、".join(o["drift"]))
    if o.get("recent_win_1d") is not None and o.get("baseline_win_1d") is not None:
        d = (o["recent_win_1d"] - o["baseline_win_1d"]) * 100
        if abs(d) >= 8:
            parts.append(f"次日胜率 {d:+.0f}pct")
    if not parts:
        parts.append("打法与基线一致，无显著漂移")
    return "；".join(parts)


def market_summary(today_seats: list[dict], profiles: dict,
                   recent_an: dict, today: str) -> dict:
    """today_seats: RPT_OPERATEDEPT_ACTIVE 当日行；profiles/recent_an: seat_code -> 分析结果。"""
    def buy(r):
        return float(r.get("TOTAL_BUYAMT") or 0) / 1e4

    def net(r):
        return float(r.get("TOTAL_NETAMT") or 0) / 1e4

    net_buy_top = sorted(today_seats, key=net, reverse=True)[:8]
    net_sell_top = sorted(today_seats, key=net)[:8]

    famous_moves, new_faces = [], []
    for r in today_seats:
        code = r.get("OPERATEDEPT_CODE")
        prof = profiles.get(code) or {}
        kb = prof.get("kb")
        ra = recent_an.get(code) or {}
        item = {
            "seat_code": code,
            "seat_name": r.get("OPERATEDEPT_NAME"),
            "alias": (kb or {}).get("alias"),
            "tags": (kb or {}).get("tags") or [],
            "buy_amt": round(buy(r), 1),
            "net_amt": round(net(r), 1),
            "stocks": (r.get("BUY_STOCK") or "").split(",")[:8],
            "n_buy_seats": r.get("BUYER_APPEAR_NUM"),
        }
        if kb:
            item["verdict"] = ra.get("verdict")
            item["drift"] = ra.get("drift")
            famous_moves.append(item)
        # 新面孔/稀客：窗口内几乎没出现过（含 0 次）但今日大额买入
        elif (ra.get("is_new_face") or (ra.get("baseline_n_days") or 0) <= 2) \
                and buy(r) >= NEW_FACE_MIN_BUY:
            new_faces.append(item)

    return {
        "date": today,
        "n_seats": len(today_seats),
        "net_buy_top": [{"seat_name": r.get("OPERATEDEPT_NAME"),
                         "alias": (profiles.get(r.get("OPERATEDEPT_CODE"), {}).get("kb") or {}).get("alias"),
                         "buy_amt": round(buy(r), 1), "net_amt": round(net(r), 1),
                         "stocks": (r.get("BUY_STOCK") or "").split(",")[:6]}
                        for r in net_buy_top],
        "net_sell_top": [{"seat_name": r.get("OPERATEDEPT_NAME"),
                          "alias": (profiles.get(r.get("OPERATEDEPT_CODE"), {}).get("kb") or {}).get("alias"),
                          "buy_amt": round(buy(r), 1), "net_amt": round(net(r), 1),
                          "stocks": (r.get("BUY_STOCK") or "").split(",")[:6]}
                         for r in net_sell_top],
        "famous_moves": famous_moves,
        "new_faces": new_faces,
    }
