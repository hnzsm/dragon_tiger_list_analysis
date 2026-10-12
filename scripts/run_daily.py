# -*- coding: utf-8 -*-
"""每日龙虎榜分析 · 主编排。

    python scripts/run_daily.py                          # 今天
    python scripts/run_daily.py --date 2026-10-09        # 指定日期
    python scripts/run_daily.py --top-seats 25 --lookback 120

流程（详见 SKILL.md）：
1. 拉当日龙虎榜：个股明细 + 席位×日汇总（lhb_api）
2. 选重点席位：KB 知名席位 + 当日净买入 TOP + 当日买入额 TOP（去重，上限 --top-seats）
3. 重点席位逐个拉近 lookback 日历天的席位流水 → 聚合 → 画像（统计+KB）→ 近期二次分析
4. 市场级汇总：净买/净卖 TOP、知名席位动向、新面孔
5. 渲染单文件 HTML 报告 + 全量 JSON + 终端摘要
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import recent_activity as RA   # noqa: E402
import report as RP             # noqa: E402
import seat_profile as SP      # noqa: E402
from lhb_api import LhbApi     # noqa: E402
from seats_kb import kb_summary  # noqa: E402


def pick_key_seats(today_seats: list[dict], top_seats: int) -> list[dict]:
    """重点席位 = KB 命中 ∪ 当日净买入 TOP ∪ 当日买入额 TOP，按买入额排序截断。"""
    chosen: dict[str, dict] = {}

    def add(r):
        chosen.setdefault(r["OPERATEDEPT_CODE"], r)

    for r in today_seats:
        if kb_summary(r.get("OPERATEDEPT_NAME") or ""):
            add(r)
    for r in sorted(today_seats, key=lambda x: float(x.get("TOTAL_NETAMT") or 0), reverse=True)[:top_seats]:
        add(r)
    for r in sorted(today_seats, key=lambda x: float(x.get("TOTAL_BUYAMT") or 0), reverse=True)[:top_seats]:
        add(r)
    out = list(chosen.values())
    out.sort(key=lambda x: float(x.get("TOTAL_BUYAMT") or 0), reverse=True)
    return out[: max(top_seats * 2, top_seats)]


def run(date: str, top_seats: int, lookback: int, recent_days: int,
        outdir: str, cache_dir: str, delay: float = 0.4) -> dict:
    api = LhbApi(cache_dir=cache_dir, delay=delay)
    os.makedirs(outdir, exist_ok=True)

    # 1) 当日数据
    stock_rows = api.daily_stock_detail(date)
    seat_rows = api.seat_daily(date)
    if not stock_rows or not seat_rows:
        print(f"[warn] {date} 龙虎榜数据为空（非交易日 / 盘后未更新 / 未来日期）")
        return {"date": date, "empty": True}
    t_days = api.trading_days(date, n=lookback + 10)
    win_start = t_days[0] if t_days else date
    print(f"[info] {date}: 个股 {len(stock_rows)} 行，席位 {len(seat_rows)} 行，"
          f"窗口 {win_start}~{date}（{len(t_days)} 个交易日）")

    # 2) 重点席位
    key_seats = pick_key_seats(seat_rows, top_seats)
    print(f"[info] 重点席位 {len(key_seats)} 个：")
    for r in key_seats[:12]:
        kb = kb_summary(r.get("OPERATEDEPT_NAME") or "")
        tag = f" [{kb['alias']}]" if kb else ""
        print(f"    {r['OPERATEDEPT_NAME'][:24]}{tag} "
              f"买{float(r.get('TOTAL_BUYAMT') or 0)/1e4:.0f}万 "
              f"净{float(r.get('TOTAL_NETAMT') or 0)/1e4:+.0f}万")
    if len(key_seats) > 12:
        print(f"    ...等 {len(key_seats)} 个")

    # 3) 逐个席位：流水 → 画像 → 近期分析
    profiles, recent_an = {}, {}
    for r in key_seats:
        code = r["OPERATEDEPT_CODE"]
        name = r["OPERATEDEPT_NAME"]
        try:
            trades = api.seat_trades(code, win_start, date)
        except Exception as e:
            print(f"[warn] 席位 {name} 流水拉取失败: {e}")
            continue
        agg = SP.aggregate_seat_trades(trades)
        bp = []
        try:
            bp = api.seat_back_profile(code)
        except Exception as e:
            print(f"[warn] 席位 {name} 官方回测拉取失败: {e}")
        profiles[code] = SP.full_profile(code, name, agg, t_days, bp, win_start, date)
        recent_an[code] = RA.analyze_seat_recent(agg, t_days, date, recent_days)
        p = profiles[code]["stats"]
        if not p.get("empty"):
            print(f"    {name[:20]:<22} 基线 {p['n_days']}日/{p['n_stocks']}股 "
                  f"净买 {p['net_amt']:+.0f}万 次日胜率 {p.get('win_1d')} "
                  f"持股中位 {p.get('median_hold_days')}日 一日游 {p.get('quick_flip_rate')}")

    # 4) 市场汇总
    summary = RA.market_summary(seat_rows, profiles, recent_an, date)

    # 5) 输出
    payload = {
        "date": date,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window": [win_start, date],
        "params": {"top_seats": top_seats, "lookback": lookback,
                   "recent_days": recent_days},
        "stock_detail": stock_rows,
        "seat_daily": seat_rows,
        "seat_profiles": profiles,
        "seat_recent": recent_an,
        "market_summary": summary,
        "api_stats": api.stats,
    }
    jp = os.path.join(outdir, f"lhb_analysis_{date}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    hp = os.path.join(outdir, f"lhb_report_{date}.html")
    with open(hp, "w", encoding="utf-8") as f:
        f.write(RP.render_html(payload))
    print()
    print(f"[done] JSON  : {jp}")
    print(f"[done] HTML  : {hp}")
    return payload


def main():
    ap = argparse.ArgumentParser(description="每日龙虎榜分析")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--top-seats", type=int, default=15)
    ap.add_argument("--lookback", type=int, default=120, help="席位流水回看日历天数")
    ap.add_argument("--recent-days", type=int, default=5)
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--cache-dir", default="cache")
    args = ap.parse_args()
    run(args.date, args.top_seats, args.lookback, args.recent_days,
        args.outdir, args.cache_dir, args.delay)


if __name__ == "__main__":
    main()
