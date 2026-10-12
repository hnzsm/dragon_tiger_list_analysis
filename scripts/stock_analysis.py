# -*- coding: utf-8 -*-
"""单只股票龙虎榜分析 · 主编排。

    python scripts/run_stock.py --code 300821
    python scripts/run_stock.py --code 600127 --date 2026-10-12
    python scripts/run_stock.py --name 东岳硅材

流程：
1. 解析股票（代码 / 名称）→ 取该股**最近一次上榜日**（或 --date 指定）
2. 还原当日**榜单**：同一交易日多个上榜原因按「榜单金额签名」分组，
   「日换手率20%」与「日涨幅偏离7%」这类数据逐分相同的原因是**同一份榜单**，必须合并；
   「连续三个交易日累计」是另一份独立榜单
3. 回填每个榜单的**买入前五 / 卖出前五**席位（RPT_BILLBOARD_DAILYDETAILSBUY/SELL）
4. 对榜单上的**每个席位**：知识库先验 + 该席位历史统计画像 + 近 N 日风格二次分析
5. 该股**历史上榜后表现**统计（用它自己的历史龙虎榜后验涨跌幅）
6. 渲染单股 HTML 报告 + 全量 JSON

口径唯一来源：seat_profile.py（统计画像）、recent_activity.py（近期漂移）+ references/indicators.md。
本文件只做编排与榜单还原。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import recent_activity as RA    # noqa: E402
import report_stock as RS       # noqa: E402
import seat_profile as SP       # noqa: E402
from lhb_api import LhbApi      # noqa: E402
from seats_kb import kb_summary  # noqa: E402

TOP_SEATS_PER_BOARD = 5
CUMULATIVE_HINT = ("连续三个交易日", "累计")
# 匿名/通道席位：OPERATEDEPT_CODE 不可用于历史查询（机构专用 code=0 查不到）
CHANNEL_CODES = {"0", "", None}
CHANNEL_NAME_HINT = ("机构专用",)


def _amt(v) -> float:
    return float(v or 0)


# ------------------------------------------------------------------ 榜单还原
def _top_n_by_reason(rows: list[dict], side: str, n: int = TOP_SEATS_PER_BOARD) -> dict:
    """买入/卖出前五报表行 → {上榜原因: [前 N 席位行]}。

    同一原因内先按 (席位, 金额) 去重（EM 会重复出行），再截前 N。
    行已由接口按金额倒序返回。
    """
    col = "BUY" if side == "buy" else "SELL"
    by_reason: dict[str, list[dict]] = {}
    for r in rows:
        by_reason.setdefault(r.get("EXPLANATION") or "", []).append(r)
    out: dict[str, list[dict]] = {}
    for reason, lst in by_reason.items():
        seen, uniq = set(), []
        # 显式按金额降序再截前 N（不依赖接口排序，防接口改了排序口径静默取错「前五」）
        for r in sorted(lst, key=lambda x: -_amt(x.get(col))):
            key = (r.get("OPERATEDEPT_CODE") or "", round(_amt(r.get(col)), 2))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        out[reason] = uniq[:n]
    return out


def _board_meta(row: dict) -> dict:
    """股票级明细行 → 榜单元信息。"""
    return {
        "buy_amt": round(_amt(row.get("BILLBOARD_BUY_AMT")), 2),
        "sell_amt": round(_amt(row.get("BILLBOARD_SELL_AMT")), 2),
        "net_amt": round(_amt(row.get("BILLBOARD_NET_AMT")), 2),
        "deal_amt": round(_amt(row.get("BILLBOARD_DEAL_AMT")), 2),
        "deal_ratio": row.get("DEAL_AMOUNT_RATIO"),
        "change_rate": row.get("CHANGE_RATE"),
        "turnover": row.get("TURNOVERRATE"),
        "close": row.get("CLOSE_PRICE"),
        "explain": row.get("EXPLAIN"),
        "free_cap": row.get("FREE_MARKET_CAP"),
        "fwd": {k: row.get(f"D{k}_CLOSE_ADJCHRATE") for k in (1, 2, 3, 5, 10, 20, 30)},
    }


def group_boards(detail_rows: list[dict], buy_rows: list[dict],
                 sell_rows: list[dict]) -> list[dict]:
    """把「股票×日×上榜原因」行按**榜单金额签名**分组，回填买卖前五席位。

    为什么必须分组：同一交易日多个上榜原因往往指向**同一份榜单数据**
    （实测 000892：日换手率20% 与 日涨幅偏离7% 的买五名单、金额逐分相同；
    600127 的价格振幅15% 与 换手率20% 也是同一批席位），
    而「连续三个交易日累计达到X%」是**另一份独立榜单**（金额、席位都不同）。
    不分组就会把同一批席位算两遍。

    签名 = (BILLBOARD_BUY_AMT, BILLBOARD_SELL_AMT)；金额相同 ⇒ 同一份榜单。
    """
    # 1) 每个上榜原因 → 榜单签名 + 元信息
    reason_meta: dict[str, dict] = {}
    for r in detail_rows:
        reason = r.get("EXPLANATION") or ""
        sig = (round(_amt(r.get("BILLBOARD_BUY_AMT")), 2),
               round(_amt(r.get("BILLBOARD_SELL_AMT")), 2))
        slot = reason_meta.get(reason)
        if slot is None:
            reason_meta[reason] = {"sig": sig, "row": r}
        else:  # 同原因多行：把缺失的后验/解读补齐
            for k, v in r.items():
                if slot["row"].get(k) is None and v is not None:
                    slot["row"][k] = v

    # 2) 按签名合并成榜单
    sig2board: dict[tuple, dict] = {}
    boards: list[dict] = []
    for reason, slot in reason_meta.items():
        b = sig2board.get(slot["sig"])
        if b is None:
            b = sig2board[slot["sig"]] = {
                "reasons": [], **_board_meta(slot["row"]),
                "buy_seats": [], "sell_seats": [],
            }
            boards.append(b)
        b["reasons"].append(reason)

    # 3) 席位报表里出现、但股票级明细没有的原因 → 独立成榜（金额未知）
    seat_reasons = {r.get("EXPLANATION") or "" for r in buy_rows} | \
                   {r.get("EXPLANATION") or "" for r in sell_rows}
    for reason in sorted(seat_reasons - set(reason_meta)):
        b = {"reasons": [reason], **_board_meta({}), "amounts_unknown": True,
             "buy_seats": [], "sell_seats": []}
        boards.append(b)

    # 4) 排序（成交额大的在前）+ 编号
    boards.sort(key=lambda b: b["deal_amt"], reverse=True)
    for i, b in enumerate(boards):
        b["id"] = f"B{i + 1}"
        b["is_cumulative"] = any(h in rs for rs in b["reasons"] for h in CUMULATIVE_HINT)
    reason2board = {rs: b for b in boards for rs in b["reasons"]}

    # 5) 回填买五/卖五
    for side, rows in (("buy", buy_rows), ("sell", sell_rows)):
        col = "BUY" if side == "buy" else "SELL"
        tgt_key = "buy_seats" if side == "buy" else "sell_seats"
        for reason, lst in _top_n_by_reason(rows, side).items():
            b = reason2board.get(reason)
            if b is None:
                continue
            tgt = b[tgt_key]
            seen = {(s["seat_code"], s["amt"]) for s in tgt}
            for r in lst:
                code = r.get("OPERATEDEPT_CODE") or ""
                amt = round(_amt(r.get(col)), 2)
                if (code, amt) in seen:
                    continue
                seen.add((code, amt))
                name = r.get("OPERATEDEPT_NAME") or ""
                tgt.append({
                    "seat_code": code,
                    "seat_name": name,
                    "amt": amt,
                    "em_net": r.get("NET"),   # ⚠ 东财自带的 NET 口径不稳定，禁止用它，见下方注释
                    "official_3d": {
                        "rise_prob": r.get("RISE_PROBABILITY_3DAY"),
                        "n": r.get("TOTAL_BUYER_SALESTIMES_3DAY"),
                    },
                    "kb": kb_summary(name),
                })
    # ⚠ 东财「买入前五/卖出前五」报表里的 NET 字段**口径不一致**（实测 600127 沪股通：
    # 买榜 NET=买入全额、卖榜 NET=−卖出全额，两处矛盾；而 300821 深股通两处又都是真实净额）。
    # 因此本 skill **不使用该字段**：席位净额一律 = 该榜单买榜金额 − 卖榜金额（按 code+名称聚合）。
    return boards


def collect_seats(boards: list[dict]) -> list[dict]:
    """榜单席位 → 去重后的席位列表（同名机构专用按 code 合并为一行）。

    ⚠ **跨榜单金额不可直接相加**：「3 日累计榜」与「单日榜」的统计区间重叠，
    同一笔成交会在两份榜单里各出现一次。所以这里按榜单分别归集
    （`by_board`），并给出 `overlap` 标记；展示层只在单一榜单时给合计。
    """
    seats: dict[str, dict] = {}
    for b in boards:
        for side in ("buy", "sell"):
            for s in b[f"{side}_seats"]:
                key = s["seat_code"] or f"name:{s['seat_name']}"
                e = seats.get(key)
                if e is None:
                    e = seats[key] = {
                        "seat_code": s["seat_code"], "seat_name": s["seat_name"],
                        "kb": s["kb"], "by_board": {}, "buy_amt": 0.0, "sell_amt": 0.0,
                        "is_channel": s["seat_code"] in CHANNEL_CODES
                        or any(h in s["seat_name"] for h in CHANNEL_NAME_HINT),
                    }
                d = e["by_board"].setdefault(b["id"], {"buy": 0.0, "sell": 0.0})
                d[side] += s["amt"]
                e["buy_amt" if side == "buy" else "sell_amt"] += s["amt"]
    out = list(seats.values())
    for e in out:
        e["buy_amt"] = round(e["buy_amt"], 2)
        e["sell_amt"] = round(e["sell_amt"], 2)
        e["net_amt"] = round(e["buy_amt"] - e["sell_amt"], 2)
        e["roles"] = []
        for k, v in sorted(e["by_board"].items()):
            buy, sell = round(v["buy"], 2), round(v["sell"], 2)
            e["roles"].append({"board": k, "buy": buy, "sell": sell,
                               "net": round(buy - sell, 2),
                               "both_sides": buy > 0 and sell > 0})
        # 只在**该席位确实横跨多份榜单**时才需要防重复加总（如既在 3 日累计榜又在单日榜）
        e["n_boards"] = len(e["by_board"])
        e["overlap"] = e["n_boards"] > 1
    # KB 命中的排前，其次按买入额
    out.sort(key=lambda x: (0 if x.get("kb") else 1, -x["buy_amt"]))
    return out


# ------------------------------------------------------------------ 该股上榜历史
def stock_history_stats(rows: list[dict], recent_n: int = 12) -> dict:
    """该股历史龙虎榜记录 → 每次上榜摘要 + 上榜后表现统计。

    同一日期可能有多行（多上榜原因）→ 每个日期只取一行：优先**单日榜**
    （非「连续三个交易日累计」），因为后验 D1 是相对当日计算的。
    """
    by_date: dict[str, dict] = {}
    for r in rows:
        d = (r.get("TRADE_DATE") or "")[:10]
        if not d:
            continue
        reason = r.get("EXPLANATION") or ""
        is_cum = any(h in reason for h in CUMULATIVE_HINT)
        cur = by_date.get(d)
        if cur is None or (cur["_is_cum"] and not is_cum) or \
                (cur["_is_cum"] == is_cum and _amt(r.get("BILLBOARD_DEAL_AMT")) > cur["_deal"]):
            by_date[d] = {"date": d, "reason": reason, "_is_cum": is_cum,
                          "_deal": _amt(r.get("BILLBOARD_DEAL_AMT")),
                          "chg": r.get("CHANGE_RATE"),
                          "turnover": r.get("TURNOVERRATE"),
                          "net_amt": r.get("BILLBOARD_NET_AMT"),
                          "deal_amt": r.get("BILLBOARD_DEAL_AMT"),
                          "fwd": {k: r.get(f"D{k}_CLOSE_ADJCHRATE") for k in (1, 2, 3, 5, 10, 20, 30)}}
    dates = sorted(by_date.values(), key=lambda x: x["date"], reverse=True)
    for x in dates:
        x.pop("_is_cum", None)
        x.pop("_deal", None)

    def _agg(k: int):
        vals = [x["fwd"].get(k) for x in dates if x["fwd"].get(k) is not None]
        if not vals:
            return None
        return {"n": len(vals),
                "avg": round(sum(vals) / len(vals), 2),
                "win": round(sum(1 for v in vals if v > 0) / len(vals), 3),
                "best": round(max(vals), 1), "worst": round(min(vals), 1)}

    return {
        "n_boards": len(dates),
        "first_date": dates[-1]["date"] if dates else None,
        "last_date": dates[0]["date"] if dates else None,
        "fwd": {k: _agg(k) for k in (1, 2, 3, 5, 10)},
        "recent": dates[:recent_n],
    }


# ------------------------------------------------------------------ 综合结论
def _amt_cn(v) -> str:
    """元 → 人读金额（≥1 亿走「亿」）。"""
    v = float(v or 0)
    return f"{v / 1e8:,.2f}亿" if abs(v) >= 1e8 else f"{v / 1e4:,.0f}万"


def _wan_cn(v) -> str:
    """万元 → 人读金额（≥1 亿走「亿」）。"""
    if v is None:
        return "—"
    v = float(v)
    return f"{v / 1e4:,.2f}亿" if abs(v) >= 1e4 else f"{v:+,.0f}万"


def verdict(payload: dict) -> list[str]:
    """规则式综合结论（口径：榜单净额 + 席位性质 + 该股上榜后表现）。"""
    out: list[str] = []
    boards = payload.get("boards") or []
    if not boards:
        return ["未还原出榜单数据。"]
    out.append("榜单资金：" + "；".join(
        f"{b['id']}（{'/'.join(b['reasons'])[:16]}）净{'买' if (b.get('net_amt') or 0) > 0 else '卖'}"
        f"{_amt_cn(abs(b.get('net_amt')))}"
        for b in boards) + "。")

    seats = payload.get("seats") or []
    # 席位性质归类：按知识库标签映射到类别（一个席位只归一类，按优先级）
    cat_rules = [
        ("游资", ("顶级游资", "一线游资", "知名游资")),
        ("机构", ("机构",)),
        ("北向/外资", ("北向", "外资")),
        ("量化", ("量化",)),
        ("散户集中营", ("散户集中营",)),
        ("通道/总部", ("混合通道",)),
    ]
    kinds: dict[str, list[str]] = {}
    named: list[str] = []
    for s in seats:
        kb = s.get("kb") or {}
        tags = kb.get("tags") or []
        label = kb.get("alias") or s["seat_name"]
        cat = None
        if "机构专用" in s["seat_name"]:
            cat = "机构"
        elif "股通专用" in s["seat_name"]:
            cat = "北向/外资"
        else:
            for name, keys in cat_rules:
                if set(tags) & set(keys):
                    cat = name
                    break
        if cat:
            kinds.setdefault(cat, []).append(label)
            # 「知名/机构席位」只算有明确资金属性的；量化/通道方向性弱，不进这句
            if cat in ("游资", "机构", "北向/外资", "散户集中营"):
                named.append(label)
    if kinds:
        out.append("席位构成：" + "；".join(
            f"{k} {len(set(v))} 个（{'、'.join(sorted(set(v))[:4])}）"
            for k, v in sorted(kinds.items(), key=lambda kv: -len(kv[1]))) + "。")

    st = (payload.get("stock_history") or {}).get("fwd") or {}
    if st.get(1):
        a = st[1]
        out.append(f"该股历史 {payload['stock_history']['n_boards']} 次上榜后："
                   f"次日平均 {a['avg']:+.2f}%（胜率 {a['win']:.0%}，{a['n']} 次样本）；"
                   + (f"5 日平均 {st[5]['avg']:+.2f}%（胜率 {st[5]['win']:.0%}）。" if st.get(5) else ""))

    if named:
        out.append("知名/机构席位参与：" + "、".join(dict.fromkeys(named)) + "。")
    return out


# ------------------------------------------------------------------ 主流程
def run(query: str, date: str | None = None, lookback: int = 120, recent_days: int = 5,
        outdir: str = "out", cache_dir: str = "cache") -> dict:
    api = LhbApi(cache_dir=cache_dir)
    os.makedirs(outdir, exist_ok=True)

    # 1) 解析股票
    info = api.resolve_stock(query)
    if not info:
        print(f"[err] 找不到「{query}」的龙虎榜记录（只分析上过龙虎榜的票）")
        return {"empty": True, "query": query}
    if info.get("ambiguous"):
        print(f"[err] 「{query}」匹配到多只票，请用 6 位代码指定：")
        for h in info["ambiguous"]:
            print(f"    {h['code']} {h['name']}")
        return {"empty": True, "query": query, "ambiguous": info["ambiguous"]}
    code, name = info["code"], info.get("name") or ""
    history = api.stock_board_history(code)
    if not history:
        print(f"[err] {code} {name} 无龙虎榜历史记录")
        return {"empty": True, "query": query}

    dates = sorted({(r.get("TRADE_DATE") or "")[:10] for r in history if r.get("TRADE_DATE")},
                   reverse=True)
    if date:
        if date not in dates:
            print(f"[warn] {code} {name} 在 {date} 未上榜；已上榜日期：{dates[:8]}")
            return {"empty": True, "query": query, "code": code, "dates": dates}
        board_date = date
    else:
        board_date = dates[0]
    print(f"[info] {code} {name} · 上榜日 {board_date}"
          f"（历史 {len(dates)} 次上榜，最近：{'、'.join(dates[:6])}）")

    # 2) 榜单还原
    detail_rows = [r for r in history if (r.get("TRADE_DATE") or "")[:10] == board_date]
    buy_rows = api.board_seats(board_date, code, "buy")
    sell_rows = api.board_seats(board_date, code, "sell")
    boards = group_boards(detail_rows, buy_rows, sell_rows)
    print(f"[info] 还原 {len(boards)} 个榜单：")
    for b in boards:
        print(f"    {b['id']} {'/'.join(b['reasons'])[:34]} "
              f"买 {b['buy_amt'] / 1e4:,.0f}万 卖 {b['sell_amt'] / 1e4:,.0f}万 "
              f"净 {b['net_amt'] / 1e4:+,.0f}万 | 买五 {len(b['buy_seats'])} 卖五 {len(b['sell_seats'])}")

    seats = collect_seats(boards)
    print(f"[info] 榜单席位 {len(seats)} 个：")
    for s in seats:
        kb = s.get("kb") or {}
        tag = f" [{kb.get('alias')}]" if kb else ""
        amt_txt = "；".join(
            f"{r['board']} 买{r['buy'] / 1e4:,.0f}/卖{r['sell'] / 1e4:,.0f}万" for r in s["roles"])
        print(f"    {s['seat_name'][:26]:<28}{tag} {amt_txt}")

    # 3) 席位画像 + 近期二次分析
    t_days = api.trading_days(board_date, n=lookback + 10)
    win_start = t_days[0] if t_days else board_date
    profiles, recent_an = {}, {}
    for s in seats:
        key = s["seat_code"] or f"name:{s['seat_name']}"
        if s["is_channel"]:      # 机构专用等匿名席位无个股历史可查
            profiles[key] = {"seat_code": s["seat_code"], "seat_name": s["seat_name"],
                             "kb": s["kb"], "stats": {"empty": True,
                                                      "note": "匿名/通道席位，无个股历史可统计"}}
            recent_an[key] = {"empty": True}
            continue
        try:
            trades = api.seat_trades(s["seat_code"], win_start, board_date)
        except Exception as e:
            print(f"[warn] 席位 {s['seat_name']} 流水拉取失败: {e}")
            profiles[key] = {"seat_code": s["seat_code"], "seat_name": s["seat_name"],
                             "kb": s["kb"], "stats": {"empty": True, "note": f"流水拉取失败：{e}"}}
            recent_an[key] = {"empty": True}
            continue
        agg = SP.aggregate_seat_trades(trades)
        try:
            bp = api.seat_back_profile(s["seat_code"])
        except Exception:
            bp = []
        profiles[key] = SP.full_profile(s["seat_code"], s["seat_name"], agg, t_days,
                                        bp, win_start, board_date)
        recent_an[key] = RA.analyze_seat_recent(agg, t_days, board_date, recent_days)
        p = profiles[key]["stats"]
        if not p.get("empty"):
            hold = p.get("median_hold_days")
            print(f"    画像 {s['seat_name'][:22]:<24} {p['n_days']}日/{p['n_stocks']}股 "
                  f"净 {_wan_cn(p['net_amt'])} 次日胜率 {p.get('win_1d')}（{p.get('n_1d')}次） "
                  f"持股中位 {hold if hold is not None else '—'}日 "
                  f"一日游 {p.get('quick_flip_rate')}")

    # 4) 该股历史
    hist = stock_history_stats(history)

    payload = {
        "mode": "single_stock",
        "query": query,
        "code": code, "name": name,
        "date": board_date,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window": [win_start, board_date],
        "params": {"lookback": lookback, "recent_days": recent_days},
        "boards": boards,
        "seats": seats,
        "seat_profiles": profiles,
        "seat_recent": recent_an,
        "stock_history": hist,
        "api_stats": api.stats,
    }
    payload["conclusions"] = verdict(payload)

    tag = f"{code}_{board_date}"
    jp = os.path.join(outdir, f"stock_{tag}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    hp = os.path.join(outdir, f"stock_{tag}.html")
    with open(hp, "w", encoding="utf-8") as f:
        f.write(RS.render_html(payload))
    print()
    for c in payload["conclusions"]:
        print(f"  · {c}")
    print()
    print(f"[done] JSON : {jp}")
    print(f"[done] HTML : {hp}")
    return payload


def main():
    ap = argparse.ArgumentParser(description="单只股票龙虎榜分析")
    ap.add_argument("--code", default=None, help="股票代码（6 位或带后缀）")
    ap.add_argument("--name", default=None, help="股票名称")
    ap.add_argument("--date", default=None, help="上榜日 YYYY-MM-DD，默认该股最近一次上榜日")
    ap.add_argument("--lookback", type=int, default=120, help="席位历史回看日历天数")
    ap.add_argument("--recent-days", type=int, default=5, help="近期风格二次分析的交易日数")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--cache-dir", default="cache")
    args = ap.parse_args()

    query = args.code or args.name
    if not query:
        ap.error("必须给 --code 或 --name（例：--code 300821）")
    run(query, args.date, args.lookback, args.recent_days, args.outdir, args.cache_dir)


if __name__ == "__main__":
    main()
