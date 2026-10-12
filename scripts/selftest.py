# -*- coding: utf-8 -*-
"""离线自测：不碰网络，用合成数据把关键口径钉死。

    python scripts/selftest.py            # 全离线，秒级完成

覆盖：
1. seats_kb 匹配（知名席位 / 拉萨山南系 / 未收录）
2. aggregate_seat_trades 去重口径（同一席位×股票×多上榜原因的重复行）
3. compute_profile 统计口径（胜率/持股周期/一日游）
4. infer_style 规则
5. report 渲染（合成 payload 不炸）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import report as RP              # noqa: E402
import recent_activity as RA     # noqa: E402
import report_stock as RS        # noqa: E402
import seat_profile as SP        # noqa: E402
import stock_analysis as SA      # noqa: E402
from seats_kb import kb_summary  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def t_kb():
    print("[1] 知识库匹配")
    kb = kb_summary("国泰海通证券股份有限公司南京太平南路证券营业部")
    check("作手新一命中", kb is not None and "作手新一" in kb["alias"])
    kb2 = kb_summary("东方财富证券股份有限公司山南香曲东路证券营业部")
    check("山南系归入拉萨军团", kb2 is not None and "拉萨军团" in kb2["alias"])
    kb3 = kb_summary("机构专用")
    check("机构专用命中", kb3 is not None and kb3["tags"] == ["机构"])
    check("未收录返回 None", kb_summary("某某证券某某路证券营业部") is None)


def t_aggregate():
    print("[2] 席位流水聚合去重")
    rows = [
        # 同一席位×股票×日，三个上榜原因，两行金额完全相同（重复行）
        {"TRADE_DATE": "2026-10-12 00:00:00", "SECURITY_CODE": "000892",
         "SECURITY_NAME_ABBR": "欢瑞世纪", "ACT_BUY": 1000.0, "ACT_SELL": 5000.0,
         "CHANGE_RATE": 10.0, "D1_CLOSE_ADJCHRATE": 3.0, "EXPLANATION": "涨幅偏离7%"},
        {"TRADE_DATE": "2026-10-12 00:00:00", "SECURITY_CODE": "000892",
         "SECURITY_NAME_ABBR": "欢瑞世纪", "ACT_BUY": 1000.0, "ACT_SELL": 5000.0,
         "CHANGE_RATE": 10.0, "D1_CLOSE_ADJCHRATE": 3.0, "EXPLANATION": "换手率达20%"},
        # 金额不同 = 不同榜单真实成交，要保留
        {"TRADE_DATE": "2026-10-12 00:00:00", "SECURITY_CODE": "000892",
         "SECURITY_NAME_ABBR": "欢瑞世纪", "ACT_BUY": 7000.0, "ACT_SELL": 2000.0,
         "CHANGE_RATE": 10.0, "D1_CLOSE_ADJCHRATE": 3.0, "EXPLANATION": "三日累计20%"},
        {"TRADE_DATE": "2026-10-09 00:00:00", "SECURITY_CODE": "000892",
         "SECURITY_NAME_ABBR": "欢瑞世纪", "ACT_BUY": 200.0, "ACT_SELL": 0.0,
         "CHANGE_RATE": 5.0, "D1_CLOSE_ADJCHRATE": -1.0, "EXPLANATION": "涨幅偏离7%"},
    ]
    agg = SP.aggregate_seat_trades(rows)
    check("聚合后 3 条记录（重复行折叠、异额行保留、跨日分开）", len(agg) == 3, f"got {len(agg)}")
    d12 = [t for t in agg if t["date"] == "2026-10-12"]
    check("10-12 买入合计 8000（1000 去重 + 7000）",
          abs(sum(t["buy"] for t in d12) - 8000.0) < 1e-6, f"{sum(t['buy'] for t in d12)}")
    check("10-12 卖出合计 7000", abs(sum(t["sell"] for t in d12) - 7000.0) < 1e-6)
    check("D1 非空保留", d12[0].get("d1") == 3.0)


def t_profile():
    print("[3] 统计画像")
    days = ["2026-10-08", "2026-10-09", "2026-10-12"]
    trades = [
        # 10-08 买入（涨停日），10-09 卖出 → 一日游
        {"date": "2026-10-08", "code": "A", "name": "票A", "buy": 5000.0, "sell": 0.0,
         "net": 5000.0, "chg": 10.0, "d1": 2.0, "d5": 4.0},
        {"date": "2026-10-09", "code": "A", "name": "票A", "buy": 0.0, "sell": 5000.0,
         "net": -5000.0, "chg": 2.0, "d1": None, "d5": None},
        # 10-08 买入后持有到 10-12（隔 2 个交易日）卖出
        {"date": "2026-10-08", "code": "B", "name": "票B", "buy": 3000.0, "sell": 0.0,
         "net": 3000.0, "chg": 0.0, "d1": -1.0, "d5": 1.0},
        {"date": "2026-10-12", "code": "B", "name": "票B", "buy": 0.0, "sell": 3000.0,
         "net": -3000.0, "chg": -1.0, "d1": None, "d5": None},
    ]
    p = SP.compute_profile(trades, days, window_start="2026-10-08", window_end="2026-10-12")
    check("上榜 3 天 / 2 股", p["n_days"] == 3 and p["n_stocks"] == 2, f"{p['n_days']}/{p['n_stocks']}")
    check("买卖相抵净买 0", abs(p["net_amt"]) < 1e-6, f"{p['net_amt']}")
    check("次日胜率 50%（A:+2%, B:-1%）", abs(p["win_1d"] - 0.5) < 1e-6, f"{p['win_1d']}")
    check("打板率 25%（4 条记录里 1 条 ≥9.5%）", abs(p["board_rate"] - 0.25) < 1e-6, f"{p['board_rate']}")
    check("一日游 50%（A 次日卖，B 隔 2 日）", abs(p["quick_flip_rate"] - 0.5) < 1e-6, f"{p['quick_flip_rate']}")
    check("持股中位 1.5 日（A=1, B=2）", p["median_hold_days"] == 1.5, f"{p['median_hold_days']}")
    tags = SP.infer_style(p)
    check("标签=双向对倒+半路/接力+一日游",
          tags == ["双向对倒", "半路/接力", "一日游"], str(tags))


def t_recent():
    print("[4] 近期二次分析")
    days = ["2026-10-08", "2026-10-09", "2026-10-12"]
    trades = [
        # 基线（10-08 之前没有 → 基线为空，10-09/10-12 是近期）
        {"date": "2026-10-09", "code": "A", "name": "票A", "buy": 9000.0, "sell": 0.0,
         "net": 9000.0, "chg": 9.9, "d1": 5.0, "d5": None},
        {"date": "2026-10-12", "code": "B", "name": "票B", "buy": 1000.0, "sell": 0.0,
         "net": 1000.0, "chg": -3.0, "d1": None, "d5": None},
    ]
    ra = RA.analyze_seat_recent(trades, days, "2026-10-12", recent_days=2)
    check("近期 2 天", not ra["empty"] and len(ra["recent_dates"]) == 2)
    check("基线为空 → is_new_face", ra["is_new_face"] is True)
    check("近期净买 1 万元（9000+1000 元）", abs(ra["recent_net_amt"] - 1.0) < 1e-6,
          f"{ra['recent_net_amt']}")


def t_report():
    print("[6] 报告渲染")
    payload = {
        "date": "2026-10-12", "generated_at": "2026-10-12 21:00:00",
        "window": ["2026-10-08", "2026-10-12"], "params": {"recent_days": 5},
        "stock_detail": [{"SECURITY_CODE": "000892", "SECURITY_NAME_ABBR": "欢瑞世纪",
                          "CHANGE_RATE": 10.03, "TURNOVERRATE": 12.3,
                          "BILLBOARD_NET_AMT": 5e7, "BILLBOARD_DEAL_AMT": 2e8,
                          "EXPLANATION": "日涨幅偏离值达到7%"}],
        "seat_daily": [{"OPERATEDEPT_CODE": "C1", "OPERATEDEPT_NAME": "测试席",
                        "TOTAL_BUYAMT": 1e8, "TOTAL_NETAMT": 5e7, "BUY_STOCK": "000892.SZ"}],
        "seat_profiles": {"C1": {"seat_code": "C1", "seat_name": "测试席", "kb": None,
                                 "stats": {"empty": False, "n_days": 5, "n_stocks": 6,
                                           "net_amt": 5000.0, "win_1d": 0.55,
                                           "avg_1d": 1.2, "board_rate": 0.4,
                                           "quick_flip_rate": 0.2, "median_hold_days": 2,
                                           "avg_chg_on_day": 6.0, "net_bias": 0.35,
                                           "official_backtest": None,
                                           "style_tags": ["打板倾向"]}}},
        "seat_recent": {"C1": {"empty": False, "recent_dates": ["2026-10-09", "2026-10-12"],
                               "verdict": "日均净买 +100.0 万 vs 基线", "drift": [],
                               "recent_stocks": ["票A"]}},
        "market_summary": {"date": "2026-10-12", "n_seats": 1,
                           "net_buy_top": [{"seat_name": "测试席", "buy_amt": 10000.0,
                                            "net_amt": 5000.0, "stocks": ["000892.SZ"]}],
                           "net_sell_top": [], "famous_moves": [], "new_faces": []},
        "api_stats": {"requests": 1, "cache_hits": 0},
    }
    html = RP.render_html(payload)
    check("生成 HTML 且含三个章节",
          all(s in html for s in ["当日龙虎榜个股 TOP", "市场资金面", "重点席位画像"]))
    check("CSS 无未替换占位符", "$" not in html.split("<style>")[1].split("</style>")[0])
    check("深色底 + 涨红跌绿", RP.BG in html and RP.POS in html and RP.NEG in html)


def t_board_group():
    print("[7] 榜单还原（多上榜原因 -> 榜单分组 + 买卖前五）")
    # 同一交易日 3 个上榜原因：R1 是 3 日累计榜；R2/R3 榜单金额逐分相同 = 同一份榜单
    detail = [
        {"TRADE_DATE": "2026-10-12 00:00:00", "EXPLANATION": "连续三个交易日内，涨幅偏离值累计达到20%的证券",
         "BILLBOARD_BUY_AMT": 300.0, "BILLBOARD_SELL_AMT": 200.0, "BILLBOARD_NET_AMT": 100.0,
         "BILLBOARD_DEAL_AMT": 500.0, "CHANGE_RATE": 10.0, "TURNOVERRATE": 25.0,
         "D1_CLOSE_ADJCHRATE": -2.0, "D5_CLOSE_ADJCHRATE": 3.0, "EXPLAIN": "三日累计"},
        {"TRADE_DATE": "2026-10-12 00:00:00", "EXPLANATION": "日换手率达到20%的前5只证券",
         "BILLBOARD_BUY_AMT": 100.0, "BILLBOARD_SELL_AMT": 80.0, "BILLBOARD_NET_AMT": 20.0,
         "BILLBOARD_DEAL_AMT": 180.0, "CHANGE_RATE": 10.0, "TURNOVERRATE": 25.0,
         "D1_CLOSE_ADJCHRATE": -2.0, "D5_CLOSE_ADJCHRATE": 3.0},
        {"TRADE_DATE": "2026-10-12 00:00:00", "EXPLANATION": "日涨幅偏离值达到7%的前5只证券",
         "BILLBOARD_BUY_AMT": 100.0, "BILLBOARD_SELL_AMT": 80.0, "BILLBOARD_NET_AMT": 20.0,
         "BILLBOARD_DEAL_AMT": 180.0, "CHANGE_RATE": 10.0, "TURNOVERRATE": 25.0,
         "D1_CLOSE_ADJCHRATE": -2.0, "D5_CLOSE_ADJCHRATE": 3.0},
    ]

    def _brow(code, name, amt, reason):
        return {"OPERATEDEPT_CODE": code, "OPERATEDEPT_NAME": name, "BUY": amt, "SELL": None,
                "NET": amt, "RISE_PROBABILITY_3DAY": 40.0, "EXPLANATION": reason}

    def _srow(code, name, amt, reason):
        return {"OPERATEDEPT_CODE": code, "OPERATEDEPT_NAME": name, "BUY": None, "SELL": amt,
                "NET": -amt, "RISE_PROBABILITY_3DAY": 40.0, "EXPLANATION": reason}

    R1 = "连续三个交易日内，涨幅偏离值累计达到20%的证券"
    R2 = "日换手率达到20%的前5只证券"
    R3 = "日涨幅偏离值达到7%的前5只证券"
    buy = [
        _brow("A", "甲营业部", 90.0, R1),          # 故意乱序：应被按金额降序整理
        _brow("B", "乙营业部", 150.0, R1),
        _brow("B", "乙营业部", 150.0, R1),          # 同原因重复行，应去重
        _brow("A", "甲营业部", 60.0, R2),
        _brow("C", "丙营业部", 30.0, R2),
        _brow("A", "甲营业部", 60.0, R3),           # R3 与 R2 数据相同，应合并
        _brow("C", "丙营业部", 30.0, R3),
    ]
    sell = [_srow("B", "乙营业部", 200.0, R1), _srow("C", "丙营业部", 50.0, R2),
            _srow("C", "丙营业部", 50.0, R3)]
    boards = SA.group_boards(detail, buy, sell)
    check("3 个上榜原因归并成 2 份榜单", len(boards) == 2, f"got {len(boards)}")
    check("榜单按成交额降序（B1=三日累计）",
          boards[0]["deal_amt"] == 500.0 and boards[0]["is_cumulative"] is True)
    check("数据相同的原因合并进同一榜单（含 2 个原因）", len(boards[1]["reasons"]) == 2,
          str(boards[1]["reasons"]))
    check("买五按金额降序且重复行已去重",
          [s["seat_name"] for s in boards[0]["buy_seats"]] == ["乙营业部", "甲营业部"],
          str([s["seat_name"] for s in boards[0]["buy_seats"]]))
    check("R2/R3 重复不会把席位算两遍（B2 买 2 席 / 卖 1 席）",
          len(boards[1]["buy_seats"]) == 2 and len(boards[1]["sell_seats"]) == 1,
          f"{len(boards[1]['buy_seats'])}/{len(boards[1]['sell_seats'])}")
    check("榜单净额 = 买总额 - 卖总额", boards[0]["net_amt"] == 100.0)

    seats = SA.collect_seats(boards)
    smap = {s["seat_name"]: s for s in seats}
    check("席位去重后 3 个", len(seats) == 3, str(sorted(smap)))
    check("乙营业部同榜双向（买 150 / 卖 200 / 净 -50）",
          smap["乙营业部"]["roles"][0]["buy"] == 150.0
          and smap["乙营业部"]["roles"][0]["sell"] == 200.0
          and smap["乙营业部"]["roles"][0]["net"] == -50.0,
          str(smap["乙营业部"]["roles"]))
    check("跨榜单席位打 overlap 标记（不做加总解读）",
          smap["甲营业部"]["overlap"] is True and smap["甲营业部"]["n_boards"] == 2)
    check("单榜单席位无 overlap 标记", smap["乙营业部"]["overlap"] is False)


def t_top5():
    print("[8] 前五截断（同一原因超过 5 行）")
    rows = [{"OPERATEDEPT_CODE": f"C{i}", "OPERATEDEPT_NAME": f"席{i}", "BUY": float(i),
             "EXPLANATION": "日涨幅偏离值达到7%的前5只证券"} for i in range(1, 8)]
    out = SA._top_n_by_reason(rows, "buy")
    top = out["日涨幅偏离值达到7%的前5只证券"]
    check("只取前 5", len(top) == 5, str(len(top)))
    check("取的是金额最大的 5 个", [r["BUY"] for r in top] == [7.0, 6.0, 5.0, 4.0, 3.0],
          str([r["BUY"] for r in top]))


def t_stock_history():
    print("[9] 该股历史上榜统计（同日期多原因只取一行）")
    rows = [
        {"TRADE_DATE": "2026-10-12 00:00:00", "EXPLANATION": "连续三个交易日内，涨幅偏离值累计达到20%的证券",
         "CHANGE_RATE": 10.0, "TURNOVERRATE": 20.0, "BILLBOARD_NET_AMT": 1e7,
         "BILLBOARD_DEAL_AMT": 5e7, "D1_CLOSE_ADJCHRATE": -2.0, "D5_CLOSE_ADJCHRATE": 3.0},
        {"TRADE_DATE": "2026-10-12 00:00:00", "EXPLANATION": "日涨幅偏离值达到7%的前5只证券",
         "CHANGE_RATE": 10.0, "TURNOVERRATE": 20.0, "BILLBOARD_NET_AMT": 2e7,
         "BILLBOARD_DEAL_AMT": 2e7, "D1_CLOSE_ADJCHRATE": -2.0, "D5_CLOSE_ADJCHRATE": 3.0},
        {"TRADE_DATE": "2026-10-09 00:00:00", "EXPLANATION": "日涨幅偏离值达到7%的前5只证券",
         "CHANGE_RATE": -5.0, "TURNOVERRATE": 8.0, "BILLBOARD_NET_AMT": -1e7,
         "BILLBOARD_DEAL_AMT": 1e7, "D1_CLOSE_ADJCHRATE": 4.0, "D5_CLOSE_ADJCHRATE": None},
    ]
    h = SA.stock_history_stats(rows)
    check("上榜 2 次（10-12 的两行合一）", h["n_boards"] == 2, str(h["n_boards"]))
    check("优先取单日榜（净额 2e7 而非 1e7）", h["recent"][0]["net_amt"] == 2e7,
          str(h["recent"][0]["net_amt"]))
    check("次日平均 +1.0%（-2 与 +4）", h["fwd"][1]["avg"] == 1.0, str(h["fwd"][1]))
    check("次日胜率 50%", h["fwd"][1]["win"] == 0.5)
    check("5 日样本只有 1 条（另一条为空）", h["fwd"][5]["n"] == 1)


def t_stock_report():
    print("[10] 单股报告渲染")
    payload = {
        "mode": "single_stock", "code": "000892", "name": "欢瑞世纪", "date": "2026-10-12",
        "generated_at": "2026-10-12 23:00:00", "window": ["2026-06-01", "2026-10-12"],
        "params": {"recent_days": 5},
        "boards": [{"id": "B1", "reasons": ["日涨幅偏离值达到7%的前5只证券"],
                    "buy_amt": 1e8, "sell_amt": 8e7, "net_amt": 2e7, "deal_amt": 1.8e8,
                    "deal_ratio": 20.5, "change_rate": 10.0, "turnover": 12.0, "close": 10.0,
                    "explain": "游资接力", "is_cumulative": False,
                    "fwd": {1: 2.0, 3: None, 5: -1.0, 10: None},
                    "buy_seats": [{"seat_code": "C1", "seat_name": "甲营业部", "amt": 6e7,
                                   "em_net": 6e7, "official_3d": {"rise_prob": 40.0, "n": 10},
                                   "kb": None}],
                    "sell_seats": [{"seat_code": "C2", "seat_name": "机构专用", "amt": 5e7,
                                    "em_net": -5e7, "official_3d": {"rise_prob": 41.0, "n": 9},
                                    "kb": kb_summary("机构专用")}]}],
        "seats": [{"seat_code": "C1", "seat_name": "甲营业部", "kb": None, "is_channel": False,
                   "buy_amt": 6e7, "sell_amt": 0.0, "net_amt": 6e7, "overlap": False,
                   "roles": [{"board": "B1", "buy": 6e7, "sell": 0.0, "net": 6e7,
                              "both_sides": False}]}],
        "seat_profiles": {"C1": {"seat_code": "C1", "seat_name": "甲营业部", "kb": None,
                                 "stats": {"empty": False, "n_days": 5, "n_stocks": 6,
                                           "net_amt": 5000.0, "win_1d": 0.55, "avg_1d": 1.2,
                                           "quick_flip_rate": 0.2, "median_hold_days": 2,
                                           "avg_chg_on_day": 6.0,
                                           "style_tags": ["打板倾向"]}}},
        "seat_recent": {"C1": {"empty": False, "recent_dates": ["2026-10-09", "2026-10-12"],
                               "verdict": "日均净买 +100.0 万 vs 基线", "drift": ["转打板"],
                               "recent_stocks": ["票A"]}},
        "stock_history": {"n_boards": 2, "first_date": "2026-10-09", "last_date": "2026-10-12",
                          "fwd": {1: {"n": 2, "avg": 1.0, "win": 0.5, "best": 4.0, "worst": -2.0},
                                  2: None, 3: None, 5: {"n": 1, "avg": 3.0, "win": 1.0,
                                                        "best": 3.0, "worst": 3.0}, 10: None},
                          "recent": [{"date": "2026-10-12", "reason": "日涨幅偏离值达到7%的前5只证券",
                                      "chg": 10.0, "turnover": 20.0, "net_amt": 2e7,
                                      "deal_amt": 2e7, "fwd": {1: -2.0, 5: 3.0, 10: None}}]},
        "conclusions": ["榜单资金：B1 净买2,000万。"],
        "api_stats": {"requests": 3, "cache_hits": 1},
    }
    html = RS.render_html(payload)
    for sec in ["当日龙虎榜榜单还原", "上榜席位画像", "该股历史上榜后表现"]:
        check(f"含章节「{sec}」", sec in html)
    check("深色底 + 涨红跌绿", RP.BG in html and RP.POS in html and RP.NEG in html)
    check("无 None/nan 文本", "None" not in html and "nan" not in html)
    check("金额人读化（亿/万）", "亿" in html and "万" in html)


def main():
    t_kb()
    t_aggregate()
    t_profile()
    t_recent()
    t_report()
    t_board_group()
    t_top5()
    t_stock_history()
    t_stock_report()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {FAILS}")
        sys.exit(1)
    print("ALL PASS ✓")


if __name__ == "__main__":
    main()
