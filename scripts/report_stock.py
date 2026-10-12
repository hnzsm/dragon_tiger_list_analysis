# -*- coding: utf-8 -*-
"""单只股票龙虎榜分析 · 单文件 HTML 报告渲染。

版式与配色**沿用 report.py**（深色、A 股口径：涨/正面=红，跌/负面=绿），
只把内容组织从「全市场日报」换成「单票深度分析」。
指标口径不在本文件定义 —— 唯一来源：seat_profile.py / recent_activity.py /
stock_analysis.py（榜单还原+该股历史）+ references/indicators.md。
"""
from __future__ import annotations

from report import ACCENT, DISCLAIMER, _CSS, _cls, _fmt_ratio, _kpi, _pct, esc


def _tag(text: str, cls: str = "") -> str:
    return f'<span class="tag {cls}">{esc(text)}</span>'


def _amt_cn(v, unit: bool = True) -> str:
    """元 → 人读金额（≥1 亿走「亿」，否则「万」）。"""
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.2f}亿" if unit else f"{v / 1e8:,.2f}"
    return f"{v / 1e4:,.0f}万" if unit else f"{v / 1e4:,.0f}"


def _wan_cn(v) -> str:
    """万元 → 人读金额（≥1 亿走「亿」）。"""
    if v is None:
        return "—"
    v = float(v)
    return f"{v / 1e4:,.2f}亿" if abs(v) >= 1e4 else f"{v:+,.0f}万"


def _conf_cn(c: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低（以统计为准）"}.get(c or "", "?")


def _side_txt(buy, sell) -> str:
    """只列非零方向，避免「卖 0万」这种噪声。"""
    parts = []
    if buy:
        parts.append(f"买 <b class='{_cls(buy)}'>{_amt_cn(buy)}</b>")
    if sell:
        parts.append(f"卖 <b class='{_cls(-sell)}'>{_amt_cn(sell)}</b>")
    return " / ".join(parts) or "—"


# ------------------------------------------------------------------ 榜单
def _seat_rows(seats: list[dict], side: str, profiles: dict, keymap: dict,
               both: set | None = None) -> str:
    rows = []
    both = both or set()
    for i, s in enumerate(seats):
        key = keymap.get((s["seat_code"] or "", s["seat_name"]))
        prof = (profiles.get(key) or {}).get("stats") or {}
        kb = s.get("kb") or {}
        name = esc(s["seat_name"])
        if (s["seat_code"] or "", s["seat_name"]) in both:
            name += _tag("同榜双向", "hot")
        if kb.get("alias"):
            name += f' {_tag(kb["alias"], "fam")}'
        for t in (kb.get("tags") or [])[:2]:
            name += _tag(t)
        off = s.get("official_3d") or {}
        off_txt = "—" if off.get("rise_prob") is None else f"{off['rise_prob']:.1f}%"
        summary = []
        if prof.get("win_1d") is not None:
            txt = f"次日胜率 {_fmt_ratio(prof['win_1d'])}"
            n1 = prof.get("n_1d") or 0
            if 0 < n1 < 10:                      # 小样本胜率必须标出来，别让 0%/100% 骗人
                txt += f"（样本仅 {n1}）"
            summary.append(txt)
        if prof.get("median_hold_days") is not None:
            summary.append(f"持股中位 {prof['median_hold_days']}日")
        if prof.get("quick_flip_rate") is not None:
            txt = f"一日游 {_fmt_ratio(prof['quick_flip_rate'])}"
            nb = prof.get("n_buy_days") or 0
            if 0 < nb < 10:
                txt += f"（样本仅 {nb}）"
            summary.append(txt)
        if not summary:
            summary.append(prof.get("note") or "无历史统计")
        rows.append(
            f"<tr><td>{i + 1}</td><td>{name}</td>"
            f"<td class='{_cls(s['amt'] if side == 'buy' else -s['amt'])}'>"
            f"{_amt_cn(s['amt'])}</td>"
            f"<td>{off_txt}</td>"
            f"<td class='small'>{esc('；'.join(summary))}</td></tr>")
    return "".join(rows)


def _board_card(b: dict, profiles: dict, keymap: dict, fwd_days=(1, 3, 5)) -> str:
    net = b.get("net_amt") or 0
    kinds = "、".join("3日累计榜" if ("累计" in r or "连续三个交易日" in r) else "单日榜"
                     for r in b["reasons"][:1])
    head_tags = _tag(b["id"]) + _tag(kinds)
    if b.get("deal_ratio") is not None:
        head_tags += _tag(f"占成交额 {float(b['deal_ratio']):.1f}%")

    fwd = b.get("fwd") or {}
    kpis = "".join([
        _kpi(_pct(b.get("change_rate")), "当日涨跌", _cls(b.get("change_rate"))),
        _kpi(f"{b['turnover']:.1f}%" if b.get("turnover") is not None else "—", "换手率"),
        _kpi(_amt_cn(b["buy_amt"]), "榜单买入"),
        _kpi(_amt_cn(b["sell_amt"]), "榜单卖出"),
        _kpi(_amt_cn(net), "榜单净额", _cls(net)),
        _kpi(_amt_cn(b.get("deal_amt")), "龙虎榜成交"),
    ] + [
        _kpi(_pct(fwd.get(k)), f"上榜后 {k} 日", _cls(fwd.get(k))) for k in fwd_days
    ])

    explain = ""
    if b.get("explain"):
        explain = f"<div class='verdict'>东财解读：{esc(b['explain'])}</div>"

    reason = "；".join(esc(r) for r in b["reasons"])
    both = {(s["seat_code"] or "", s["seat_name"]) for s in b["buy_seats"]} & \
           {(s["seat_code"] or "", s["seat_name"]) for s in b["sell_seats"]}
    buy_rows = _seat_rows(b["buy_seats"], "buy", profiles, keymap, both) or \
        "<tr><td colspan='5' class='small'>无买入席位明细</td></tr>"
    sell_rows = _seat_rows(b["sell_seats"], "sell", profiles, keymap, both) or \
        "<tr><td colspan='5' class='small'>无卖出席位明细</td></tr>"
    return (f"<div class='card'><div class='seat-head'><h3>榜单 {esc(b['id'])}：{reason}</h3>"
            f"<span class='amt'>净 <b class='{_cls(net)}'>{_amt_cn(net)}</b></span></div>"
            f"<div style='margin-bottom:8px'>{head_tags}</div>"
            f"<div class='grid3'>{kpis}</div>{explain}"
            f"<div class='grid2' style='margin-top:12px'>"
            f"<div><h3 style='font-size:13.5px;margin-bottom:8px'>买入前五</h3>"
            f"<div class='scroll'><table>"
            f"<tr><th>#</th><th>席位</th><th>买入额</th><th>官方3日胜率</th><th>该席位历史画像</th></tr>"
            f"{buy_rows}</table></div></div>"
            f"<div><h3 style='font-size:13.5px;margin-bottom:8px'>卖出前五</h3>"
            f"<div class='scroll'><table>"
            f"<tr><th>#</th><th>席位</th><th>卖出额</th><th>官方3日胜率</th><th>该席位历史画像</th></tr>"
            f"{sell_rows}</table></div></div></div>"
            f"<div class='small' style='margin-top:8px'>说明：买入/卖出各自取前五，两侧合计分别与榜单买卖总额自洽；"
            f"席位在榜单内的净额见下方「席位画像」卡片（不由东财 NET 字段给出 —— 该字段口径不稳定）。</div></div>")


# ------------------------------------------------------------------ 席位画像卡
def _seat_card_stock(seat: dict, prof: dict, recent: dict) -> str:
    st = prof.get("stats") or {}
    kb = prof.get("kb") or {}
    tags = ""
    for t in (kb.get("tags") or []):
        cls = "fam" if t in ("顶级游资", "一线游资", "知名游资", "机构", "北向", "外资") else ""
        tags += _tag(t, cls)
    for t in (st.get("style_tags") or []):
        tags += _tag(t, "hot")

    roles = "；".join(
        f"{r['board']} {_side_txt(r['buy'], r['sell'])}（净 {_amt_cn(r['net'])}）"
        for r in seat.get("roles") or [])
    if seat.get("overlap"):
        head_amt = "出现在多个榜单（榜单统计区间重叠，金额不做加总）"
    else:
        head_amt = "本次 " + _side_txt(seat.get("buy_amt"), seat.get("sell_amt"))

    if st.get("empty"):
        kpis = f"<div class='small'>{esc(st.get('note') or '无历史统计')}</div>"
    else:
        off = st.get("official_backtest") or {}
        n1 = st.get("n_1d")
        kpis = "".join([
            _kpi(f"{st.get('n_days', 0)}日/{st.get('n_stocks', 0)}股",
                 f"近窗口上榜（{(st.get('window') or ['', ''])[0][5:]} 起）"),
            _kpi(_wan_cn(st.get("net_amt")), "区间净买入", _cls(st.get("net_amt"))),
            _kpi(_fmt_ratio(st.get("win_1d")),
                 f"次日上涨概率（{n1} 次）" if n1 else "次日上涨概率",
                 _cls((st.get("win_1d") or 0.5) - 0.5)),
            _kpi(f"{st.get('avg_1d')}%" if st.get("avg_1d") is not None else "—",
                 "次日平均涨幅", _cls(st.get("avg_1d"))),
            _kpi(f"{st.get('median_hold_days')}日" if st.get("median_hold_days") is not None else "—",
                 "持股周期中位"),
            _kpi(_fmt_ratio(st.get("quick_flip_rate")), "一日游比例",
                 _cls(-(st.get("quick_flip_rate") or 0))),
            _kpi(f"{st.get('avg_chg_on_day')}%" if st.get("avg_chg_on_day") is not None else "—",
                 "上榜股平均涨幅"),
            _kpi(f"{off['rise_prob_1d']:.1f}%" if off.get("rise_prob_1d") is not None else "—",
                 f"官方次日胜率（{off.get('cycle', '')}）" if off else "官方回测"),
        ])

    if kb:
        lis = "".join(f"<li>{esc(d)}</li>" for d in (kb.get("detail") or [])[:4])
        kb_html = (f"<div class='kb'><b>{esc(kb.get('alias'))}</b>"
                   f"（先验置信度：{_conf_cn(kb.get('confidence'))}）：{esc(kb.get('style'))}"
                   f"<ul>{lis}</ul></div>")
    else:
        kb_html = ("<div class='kb'>知识库未收录该席位（新面孔/普通营业部），"
                   "以下结论纯统计。</div>")

    drift = ""
    if recent and not recent.get("empty"):
        dtags = "".join(_tag(t, "hot") for t in (recent.get("drift") or []))
        stocks = "、".join((recent.get("recent_stocks") or [])[:6])
        drift = (f"<div class='verdict'><b>近期二次分析（{len(recent.get('recent_dates') or [])} 个交易日）：</b>"
                 f"{esc(recent.get('verdict'))}"
                 + (f"<div style='margin-top:4px'>{dtags}</div>" if dtags else "")
                 + (f"<div class='small' style='margin-top:4px'>近期涉及：{esc(stocks)}</div>"
                    if stocks else "")
                 + "</div>")

    return (f"<div class='card'><div class='seat-head'><h3>{esc(prof.get('seat_name'))}</h3>"
            f"<span class='amt'>{head_amt}</span></div>"
            f"<div style='margin-bottom:8px'>{tags}</div>"
            f"<div class='small' style='margin-bottom:8px'>榜单明细：{esc(roles or '—')}</div>"
            f"<div class='grid4'>{kpis}</div>{kb_html}{drift}</div>")


# ------------------------------------------------------------------ 该股历史
def _history_section(hist: dict) -> str:
    fwd = hist.get("fwd") or {}
    kpis = "".join([
        _kpi(str(hist.get("n_boards", 0)), "历史上榜次数"),
        _kpi(esc(hist.get("first_date") or "—"), "最早上榜"),
    ] + [
        _kpi(f"{fwd[k]['avg']:+.2f}% / {fwd[k]['win']:.0%}" if fwd.get(k) else "—",
             f"上榜后 {k} 日 均值/胜率")
        for k in (1, 2, 3, 5, 10)
    ])
    rows = []
    for r in hist.get("recent") or []:
        f = r.get("fwd") or {}
        turnover = f"{r['turnover']:.1f}%" if r.get("turnover") is not None else "—"
        rows.append(
            f"<tr><td>{esc(r['date'])}</td>"
            f"<td class='{_cls(r.get('chg'))}'>{_pct(r.get('chg'))}</td>"
            f"<td>{turnover}</td>"
            f"<td class='{_cls(r.get('net_amt'))}'>{_amt_cn(r.get('net_amt'))}</td>"
            f"<td>{_amt_cn(r.get('deal_amt'))}</td>"
            f"<td class='{_cls(f.get(1))}'>{_pct(f.get(1))}</td>"
            f"<td class='{_cls(f.get(5))}'>{_pct(f.get(5))}</td>"
            f"<td class='{_cls(f.get(10))}'>{_pct(f.get(10))}</td>"
            f"<td class='small'>{esc((r.get('reason') or '')[:24])}</td></tr>")

    note = ("上榜后涨跌幅用的是东方财富 D1~D10_CLOSE_ADJCHRATE（复权后验涨跌幅），"
            "同一日期多个上榜原因只取一行（优先单日榜）。")
    return (f"<div class='card'><div class='grid4'>{kpis}</div>"
            f"<div class='scroll'><table style='margin-top:12px'>"
            f"<tr><th>上榜日</th><th>当日涨跌</th><th>换手</th>"
            f"<th>龙虎榜净买</th><th>龙虎榜成交</th><th>后1日</th><th>后5日</th><th>后10日</th>"
            f"<th>上榜原因</th></tr>{''.join(rows)}</table></div>"
            f"<div class='small' style='margin-top:8px'>{esc(note)}</div></div>")


# ------------------------------------------------------------------ 主渲染
def render_html(payload: dict) -> str:
    code = payload.get("code") or ""
    name = payload.get("name") or ""
    date = payload.get("date") or ""
    boards = payload.get("boards") or []
    seats = payload.get("seats") or []
    profiles = payload.get("seat_profiles") or {}
    recent = payload.get("seat_recent") or {}
    hist = payload.get("stock_history") or {}
    stats = payload.get("api_stats") or {}
    win = payload.get("window") or ["", ""]

    keymap = {(s["seat_code"] or "", s["seat_name"]): (s["seat_code"] or f"name:{s['seat_name']}")
              for s in seats}

    board_cards = "".join(_board_card(b, profiles, keymap) for b in boards)
    cards = []
    for s in seats:
        key = s["seat_code"] or f"name:{s['seat_name']}"
        cards.append(_seat_card_stock(s, profiles.get(key) or {}, recent.get(key) or {}))
    concl = "".join(f"<li>{esc(c)}</li>" for c in (payload.get("conclusions") or []))

    main = boards[0] if boards else {}

    chips = []
    if boards:
        nb = main.get("net_amt")
        chips.append(f'<span class="tag {_cls(nb)}">榜首净额 {_amt_cn(nb)}</span>')
    named = [s for s in seats if s.get("kb")]
    if named:
        chips.append(f'<span class="tag fam">知名/机构席位 {len(named)}</span>')
    chips.append(f'<span class="tag">榜单 {len(boards)} · 席位 {len(seats)}</span>')

    turnover = f"{float(main['turnover']):.2f}%" if main.get("turnover") is not None else "—"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>龙虎榜个股分析 · {esc(name)}{esc(code)} · {esc(date)}</title>
<style>{_CSS}</style></head><body><div class="topbar"></div><div class="wrap">

<div class="hero">
  <div class="eyebrow">A 股龙虎榜 · 个股深度分析</div>
  <h1>{esc(name)} <span class="code">{esc(code)}</span></h1>
  <div class="meta">上榜日 {esc(date)} &nbsp;·&nbsp; 当日 <b class="{_cls(main.get('change_rate'))}">{_pct(main.get('change_rate'))}</b>
   &nbsp;·&nbsp; 换手 {turnover} &nbsp;·&nbsp; 席位历史窗口 {esc(win[0])} ~ {esc(win[1])}
   <br>生成于 {esc(payload.get('generated_at'))} &nbsp;·&nbsp; 接口请求 {stats.get('requests', 0)} 次 / 缓存命中 {stats.get('cache_hits', 0)} 次</div>
  <div class="chips">{''.join(chips)}</div>
</div>

<div class="card"><h3>综合结论</h3><ul class="concl">{concl or '<li>—</li>'}</ul></div>

<div class="section"><span class="idx">1</span><span class="t">当日龙虎榜榜单还原</span>
  <span class="cnt">{len(boards)} 个榜单</span></div>
<p class="small" style="margin-bottom:12px">同一交易日多个上榜原因按<b>榜单金额签名</b>分组：
「日换手率20%」「日涨幅偏离7%」这类数据逐分相同的原因是<b>同一份榜单</b>（席位与金额相同），
已合并；「连续三个交易日累计」是独立榜单。买入/卖出前五合计与榜单买卖总额自洽。</p>
{board_cards or "<div class='card'>未还原出榜单。</div>"}

<div class="section"><span class="idx">2</span><span class="t">上榜席位画像</span>
  <span class="cnt">{len(seats)} 个席位</span></div>
<p class="small" style="margin-bottom:12px">画像 = 该席位近窗口历史统计 + 知识库先验；
「近期二次分析」= 近 {payload.get('params', {}).get('recent_days')} 个交易日实际打法 vs 更长基线。
匿名/通道席位（机构专用等）无个股历史可统计，只给先验。</p>
{''.join(cards) or "<div class='card'>无席位。</div>"}

<div class="section"><span class="idx">3</span><span class="t">该股历史上榜后表现</span></div>
{_history_section(hist)}

<div class="foot">{esc(DISCLAIMER)}<br>
数据源：东方财富数据中心（个股龙虎榜明细 / 买入前五 / 卖出前五 / 席位成交流水 / 官方回测）。<br>
席位知识库：references/seats_knowledge.md（先验，席位会漂移，与统计矛盾时以统计为准）。</div>
</div></body></html>"""
