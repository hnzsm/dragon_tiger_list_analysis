# -*- coding: utf-8 -*-
"""单文件 HTML 报告渲染（内联 CSS/SVG，无 CDN 依赖，离线可看）。

配色口径（A 股惯例，别在别处另起一套）：
* 深色版式；A 股口径：**涨=红 / 跌=绿**。
* 指标数值口径不在本文件定义 —— 唯一来源是 seat_profile.py / recent_activity.py /
  references/indicators.md。
"""
from __future__ import annotations

import html
from datetime import datetime

BG = "#080b13"
PANEL = "#111726"
PANEL_2 = "#151d2e"
BORDER = "rgba(255,255,255,.075)"
TEXT = "#e9eef7"
SUB = "#8d97ab"
POS = "#ff5f55"   # 涨/正面=红
NEG = "#1ec78d"   # 跌/负面=绿
NEU = "#78839a"
ACCENT = "#5b8cff"
GLOW1 = "rgba(91,140,255,.17)"
GLOW2 = "rgba(34,211,238,.12)"
GLOW3 = "rgba(255,95,85,.055)"
FONT = ('"HarmonyOS Sans SC","PingFang SC","Microsoft YaHei UI","Microsoft YaHei",'
        'system-ui,-apple-system,"Segoe UI",sans-serif')

DISCLAIMER = ("席位画像 = 东方财富历史统计 + 知名席位知识库先验；"
              "口径见 references/indicators.md。仅供个人研究，不构成投资建议。")


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _pct(v, nd=1):
    if v is None:
        return "—"
    return f"{v:+.{nd}f}%"


def _cls(v):
    if v is None:
        return "neu"
    return "pos" if v > 0.001 else ("neg" if v < -0.001 else "neu")


def _wan(v):
    """元 -> 万元字符串。"""
    if v is None:
        return "—"
    return f"{float(v) / 1e4:,.0f}万"


def _fmt_ratio(v, nd=1):
    return "—" if v is None else f"{v * 100:.{nd}f}%"


# CSS 用占位符 + replace 组装（比 f-string 里把每个花括号都写两遍更不容易出错）
_CSS_TMPL = """
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:$BG;color:$TEXT;font:14px/1.72 $FONT;padding:0 20px 76px;
     position:relative;overflow-x:hidden;font-variant-numeric:tabular-nums;
     -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(920px 400px at 10% -8%,$GLOW1,transparent 62%),
             radial-gradient(780px 380px at 90% -4%,$GLOW2,transparent 60%),
             radial-gradient(820px 520px at 50% 112%,$GLOW3,transparent 62%)}
.wrap{max-width:1200px;margin:0 auto;position:relative;z-index:1;animation:fade .45s ease both}
@keyframes fade{from{opacity:0}to{opacity:1}}
.topbar{position:fixed;left:0;right:0;top:0;height:2px;z-index:9;opacity:.92;
  background:linear-gradient(90deg,#5b8cff,#22d3ee 46%,#ff5f55)}

/* ---------- 页头 ---------- */
.hero{position:relative;margin:30px 0 8px;padding:26px 28px 24px;border-radius:18px;
  background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.018));
  border:1px solid $BORDER;overflow:hidden;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 26px 64px -36px rgba(0,0,0,.95)}
.hero::after{content:"";position:absolute;left:0;right:0;top:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(91,140,255,.8),rgba(34,211,238,.7),transparent)}
.hero::before{content:"";position:absolute;right:-70px;top:-100px;width:300px;height:300px;
  border-radius:50%;pointer-events:none;
  background:radial-gradient(circle,rgba(91,140,255,.22),transparent 68%)}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.24em;text-transform:uppercase;color:$ACCENT}
h1{font-size:29px;line-height:1.25;font-weight:700;letter-spacing:-.012em;margin:9px 0 0}
h1 .code{color:$ACCENT;font-weight:650}
.meta{color:$SUB;font-size:12.5px;margin-top:11px;line-height:1.9}
.meta b{font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:2px;margin-top:14px}

/* ---------- 标题层级 ---------- */
.section{display:flex;align-items:center;gap:11px;margin:38px 0 15px}
.section .idx{flex:none;width:27px;height:27px;border-radius:9px;display:grid;place-items:center;
  font-size:12.5px;font-weight:700;color:#fff;
  background:linear-gradient(135deg,#5b8cff,#22d3ee);
  box-shadow:0 8px 22px -10px rgba(91,140,255,.95)}
.section .t{font-size:18.5px;font-weight:650;letter-spacing:-.008em}
.section .cnt{color:$SUB;font-size:13px;font-weight:400}
.section::after{content:"";flex:1;min-width:24px;height:1px;
  background:linear-gradient(90deg,rgba(255,255,255,.1),transparent)}
h2{font-size:17px;margin:30px 0 13px;padding-left:11px;border-left:3px solid $ACCENT}
h3{font-size:14.5px;font-weight:600;letter-spacing:.005em}

/* ---------- 卡片 ---------- */
.card{position:relative;margin-bottom:14px;padding:16px 18px;border-radius:15px;
  background:linear-gradient(180deg,rgba(255,255,255,.042),rgba(255,255,255,.014));
  border:1px solid $BORDER;box-shadow:0 20px 48px -36px rgba(0,0,0,.95);
  transition:border-color .18s ease,transform .18s ease}
.card:hover{border-color:rgba(91,140,255,.3);transform:translateY(-1px)}
.card>h3{margin-bottom:11px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.grid2>.card,.grid3>.card,.grid4>.card{margin-bottom:0}
@media(max-width:960px){.grid2,.grid3,.grid4{grid-template-columns:1fr 1fr}}
@media(max-width:640px){.grid2,.grid3,.grid4{grid-template-columns:1fr}}

/* ---------- 表格 ---------- */
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:$SUB;font-weight:500;text-align:left;padding:9px 11px;white-space:nowrap;
  font-size:11.5px;letter-spacing:.055em;background:rgba(255,255,255,.026);
  border-bottom:1px solid $BORDER}
td{padding:9px 11px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(255,255,255,.022)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* ---------- 语义色 ---------- */
.pos{color:$POS} .neg{color:$NEG} .neu{color:$NEU}
.kpi .v.pos{text-shadow:0 0 30px rgba(255,95,85,.35)}
.kpi .v.neg{text-shadow:0 0 30px rgba(30,199,141,.35)}

/* ---------- 标签 ---------- */
.tag{display:inline-flex;align-items:center;background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.085);border-radius:999px;padding:2.5px 9px;line-height:1.45;
  font-size:11.5px;color:$SUB;margin:0 5px 5px 0}
.tag.fam{color:#93bbff;border-color:rgba(91,140,255,.4);background:rgba(91,140,255,.11)}
.tag.hot{color:#ff9089;border-color:rgba(255,95,85,.4);background:rgba(255,95,85,.11)}
.tag.pos{color:$POS;border-color:rgba(255,95,85,.42);background:rgba(255,95,85,.11)}
.tag.neg{color:$NEG;border-color:rgba(30,199,141,.42);background:rgba(30,199,141,.11)}

/* ---------- 指标块 ---------- */
.kpi{position:relative;background:rgba(255,255,255,.032);border:1px solid rgba(255,255,255,.055);
  border-radius:12px;padding:12px 13px}
.kpi::before{content:"";position:absolute;left:0;top:12px;bottom:12px;width:2px;border-radius:2px;
  background:linear-gradient(180deg,rgba(91,140,255,.55),rgba(34,211,238,.35));opacity:.5}
.kpi .k{color:$SUB;font-size:11.5px;letter-spacing:.02em;margin:0 0 6px 8px}
.kpi .v{font-size:20px;font-weight:650;letter-spacing:-.012em;line-height:1.2;margin-left:8px}

/* ---------- 结论 ---------- */
.verdict{background:rgba(91,140,255,.08);border:1px solid rgba(91,140,255,.22);
  border-radius:12px;padding:11px 14px;margin-top:11px;font-size:13px;color:#dde6f6;line-height:1.72}
.verdict b{color:#fff}
.concl{margin:0;padding:0;list-style:none}
.concl li{position:relative;padding-left:20px;margin-top:8px;font-size:13.5px;color:#dbe4f4}
.concl li:first-child{margin-top:0}
.concl li::before{content:"";position:absolute;left:2px;top:9px;width:6px;height:6px;border-radius:50%;
  background:linear-gradient(135deg,#5b8cff,#22d3ee);box-shadow:0 0 10px rgba(91,140,255,.8)}

/* ---------- 杂项 ---------- */
.kb{color:$SUB;font-size:12.5px;margin-top:11px;padding-top:11px;
  border-top:1px dashed rgba(255,255,255,.075)}
.kb b{color:$TEXT}
.kb ul{margin:5px 0 0 18px}
.kb li{margin-top:3px}
.small{font-size:12px;color:$SUB}
.foot{color:$SUB;font-size:12px;line-height:1.9;margin-top:44px;
  border-top:1px solid $BORDER;padding-top:18px}
code{background:rgba(255,255,255,.07);border-radius:5px;padding:1.5px 6px;font-size:12px}
.seat-head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;
  gap:8px;margin-bottom:11px}
.seat-head h3{font-size:15px;font-weight:650}
.seat-head .amt{font-size:12.5px;color:$SUB}
.hr{height:1px;background:$BORDER;margin:16px 0}
"""

_CSS = (_CSS_TMPL
        .replace("$BG", BG).replace("$TEXT", TEXT).replace("$BORDER", BORDER)
        .replace("$SUB", SUB).replace("$POS", POS).replace("$NEG", NEG)
        .replace("$NEU", NEU).replace("$ACCENT", ACCENT).replace("$FONT", FONT)
        .replace("$GLOW1", GLOW1).replace("$GLOW2", GLOW2).replace("$GLOW3", GLOW3))


# ------------------------------------------------------------------ 片段
def _kpi(value: str, key: str, cls: str = "") -> str:
    return f'<div class="kpi"><div class="k">{esc(key)}</div><div class="v {cls}">{esc(value)}</div></div>'


def _stock_table(rows: list[dict], limit: int = 20) -> str:
    body = []
    for r in rows[:limit]:
        chg = r.get("CHANGE_RATE")
        net = r.get("BILLBOARD_NET_AMT")
        body.append(
            f"<tr><td>{esc(r.get('SECURITY_NAME_ABBR'))}<span class='small'> {esc(r.get('SECURITY_CODE'))}</span></td>"
            f"<td class='{_cls(chg)}'>{_pct(chg)}</td>"
            f"<td>{esc(r.get('TURNOVERRATE'))}%</td>"
            f"<td class='{_cls(net)}'>{_wan(net)}</td>"
            f"<td>{_wan(r.get('BILLBOARD_DEAL_AMT'))}</td>"
            f"<td class='small'>{esc((r.get('EXPLANATION') or '')[:26])}</td></tr>")
    return ("<table><tr><th>股票</th><th>当日涨跌</th><th>换手</th><th>龙虎榜净买</th>"
            "<th>龙虎榜成交</th><th>上榜原因</th></tr>" + "".join(body) + "</table>")


def _seat_card(prof: dict, recent: dict, today_row: dict | None) -> str:
    st = prof.get("stats") or {}
    kb = prof.get("kb") or {}
    tags = []
    for t in kb.get("tags") or []:
        cls = "fam" if t in ("顶级游资", "一线游资", "知名游资", "机构", "北向", "外资") else ""
        tags.append(f'<span class="tag {cls}">{esc(t)}</span>')
    for t in st.get("style_tags") or []:
        tags.append(f'<span class="tag hot">{esc(t)}</span>')
    off = st.get("official_backtest") or {}
    off_pct = "—"
    off_key = "官方次日胜率"
    if off:
        if off.get("rise_prob_1d") is not None:
            off_pct = f"{off['rise_prob_1d']:.1f}%"   # EM 给的是百分数，别再 ×100
        off_key = f"官方次日胜率（{off.get('cycle', '')}，{off.get('n_1d', '?')}次）"

    head_amt = ""
    if today_row:
        head_amt = (f"今日买 <b class='{_cls(float(today_row.get('TOTAL_BUYAMT') or 0))}'>"
                    f"{_wan(today_row.get('TOTAL_BUYAMT'))}</b> "
                    f"净 <b class='{_cls(float(today_row.get('TOTAL_NETAMT') or 0))}'>"
                    f"{_wan(today_row.get('TOTAL_NETAMT'))}</b>")

    kpis = "".join([
        _kpi(f"{st.get('n_days', 0)}日/{st.get('n_stocks', 0)}股",
             f"窗口内上榜（{(st.get('window') or ['', ''])[0][5:]} 起）"),
        _kpi(f"{st.get('net_amt', 0):+.0f}万" if st.get("net_amt") is not None else "—", "区间净买入", _cls(st.get("net_amt"))),
        _kpi(_fmt_ratio(st.get("win_1d")), "次日上涨概率", _cls((st.get("win_1d") or 0.5) - 0.5)),
        _kpi(f"{st.get('avg_1d')}%" if st.get("avg_1d") is not None else "—", "次日平均涨幅", _cls(st.get("avg_1d"))),
        _kpi(f"{st.get('median_hold_days')}日" if st.get("median_hold_days") is not None else "—", "持股周期中位"),
        _kpi(_fmt_ratio(st.get("quick_flip_rate")), "一日游比例", _cls(-(st.get("quick_flip_rate") or 0))),
        _kpi(f"{st.get('avg_chg_on_day')}%" if st.get("avg_chg_on_day") is not None else "—", "上榜股平均涨幅"),
        _kpi(off_pct, off_key),
    ])

    kb_html = ""
    if kb:
        lis = "".join(f"<li>{esc(d)}</li>" for d in (kb.get("detail") or [])[:4])
        conf = {"high": "高", "medium": "中", "low": "低（以统计为准）"}.get(kb.get("confidence"), "?")
        kb_html = (f"<div class='kb'><b>{esc(kb.get('alias'))}</b>（先验置信度：{esc(conf)}）："
                   f"{esc(kb.get('style'))}<ul>{lis}</ul></div>")
    else:
        kb_html = "<div class='kb'>KB 未收录该席位（新面孔或普通营业部），以下结论纯统计。</div>"

    drift = ""
    if recent and not recent.get("empty"):
        drift_tags = "".join(f'<span class="tag hot">{esc(t)}</span>' for t in (recent.get("drift") or []))
        stocks = "、".join((recent.get("recent_stocks") or [])[:6])
        drift = (f"<div class='verdict'><b>近期（{len(recent.get('recent_dates') or [])} 个交易日）二次分析：</b>"
                 f"{esc(recent.get('verdict'))}"
                 + (f"<div style='margin-top:4px'>{drift_tags}</div>" if drift_tags else "")
                 + (f"<div class='small' style='margin-top:4px'>涉及：{esc(stocks)}</div>" if stocks else "")
                 + "</div>")

    return (f"<div class='card'><div class='seat-head'>"
            f"<h3>{esc(prof.get('seat_name'))}</h3><span class='amt'>{head_amt}</span></div>"
            f"<div style='margin-bottom:8px'>{''.join(tags)}</div>"
            f"<div class='grid4'>{kpis}</div>{kb_html}{drift}</div>")


def _summary_section(payload: dict) -> str:
    sm = payload.get("market_summary") or {}
    famous = sm.get("famous_moves") or []
    new_faces = sm.get("new_faces") or []

    fam_rows = []
    for f in famous[:10]:
        drift = "、".join(f.get("drift") or [])
        fam_rows.append(
            f"<tr><td>{esc(f.get('alias') or f.get('seat_name'))}</td>"
            f"<td class='{_cls(f.get('net_amt'))}'>{f.get('net_amt'):+.0f}万</td>"
            f"<td class='small'>{esc('、'.join((f.get('stocks') or [])[:5]))}</td>"
            f"<td class='small'>{esc(drift or '—')}</td>"
            f"<td class='small'>{esc((f.get('verdict') or '')[:40])}</td></tr>")
    nf_rows = [f"<tr><td>{esc(f.get('seat_name'))}</td><td>{f.get('buy_amt'):.0f}万</td>"
               f"<td class='small'>{esc('、'.join((f.get('stocks') or [])[:5]))}</td></tr>"
               for f in new_faces[:6]]
    return (f"<div class='grid2'><div class='card'><h3>知名席位动向（{len(famous)}）</h3>"
            f"<table><tr><th>席位</th><th>今日净买</th><th>涉及</th><th>风格漂移</th><th>近期结论</th></tr>"
            + "".join(fam_rows) + "</table></div>"
            f"<div class='card'><h3>新面孔（{len(new_faces)}）</h3>"
            + ("<table><tr><th>席位</th><th>今日买入</th><th>涉及</th></tr>" + "".join(nf_rows) + "</table>"
               if nf_rows else "<p class='small'>无明显新面孔。</p>") + "</div></div>")


def _rank_section(sm: dict) -> str:
    def rows(key):
        out = []
        for r in (sm.get(key) or [])[:8]:
            out.append(
                f"<tr><td>{esc(r.get('alias') or r.get('seat_name'))}</td>"
                f"<td>{r.get('buy_amt'):,.0f}万</td>"
                f"<td class='{_cls(r.get('net_amt'))}'>{r.get('net_amt'):+,.0f}万</td>"
                f"<td class='small'>{esc('、'.join((r.get('stocks') or [])[:4]))}</td></tr>")
        return ("<table><tr><th>席位</th><th>买入</th><th>净买</th><th>涉及</th></tr>"
                + "".join(out) + "</table>")
    return (f"<div class='grid2'><div class='card'><h3>当日净买入 TOP</h3>{rows('net_buy_top')}</div>"
            f"<div class='card'><h3>当日净卖出 TOP</h3>{rows('net_sell_top')}</div></div>")


# ------------------------------------------------------------------ 主渲染
def render_html(payload: dict) -> str:
    date = payload.get("date", "")
    win = payload.get("window") or ["", ""]
    famous = (payload.get("market_summary") or {}).get("famous_moves") or []

    # 头部结论
    concl = []
    if famous:
        buy_fam = [f for f in famous if (f.get("net_amt") or 0) > 0]
        sell_fam = [f for f in famous if (f.get("net_amt") or 0) < 0]
        seen_alias: list[str] = []

        def _alias_list(items):
            out = []
            for f in items:
                a = f.get("alias") or (f.get("seat_name") or "")[:10]
                if a not in out:
                    out.append(a)
            return out

        if buy_fam:
            concl.append(f"{len(buy_fam)} 个知名席位净买入（"
                         + "、".join(esc(a) for a in _alias_list(buy_fam)[:6]) + "）")
        if sell_fam:
            concl.append(f"{len(sell_fam)} 个知名席位净卖出（"
                         + "、".join(esc(a) for a in _alias_list(sell_fam)[:6]) + "）")

    # 当日个股 TOP（按成交额）
    stocks = sorted(payload.get("stock_detail") or [],
                    key=lambda r: float(r.get("BILLBOARD_DEAL_AMT") or 0), reverse=True)
    seen, top_stocks = set(), []
    for r in stocks:
        c = r.get("SECURITY_CODE")
        if c in seen:
            continue
        seen.add(c)
        top_stocks.append(r)

    # 席位卡片：KB 命中的排前，其余按买入额
    seat_daily = {r.get("OPERATEDEPT_CODE"): r for r in (payload.get("seat_daily") or [])}
    profs = list((payload.get("seat_profiles") or {}).values())
    profs.sort(key=lambda p: (0 if p.get("kb") else 1,
                              -float(seat_daily.get(p["seat_code"], {}).get("TOTAL_BUYAMT") or 0)))
    seat_cards = "".join(
        _seat_card(p, (payload.get("seat_recent") or {}).get(p["seat_code"]) or {},
                   seat_daily.get(p["seat_code"]))
        for p in profs[:20])

    stats = payload.get("api_stats") or {}
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日龙虎榜分析 · {esc(date)}</title>
<style>{_CSS}</style></head><body><div class="topbar"></div><div class="wrap">
<div class="hero">
  <div class="eyebrow">A 股龙虎榜 · 全市场日报</div>
  <h1>每日龙虎榜分析<span class="code"> · {esc(date)}</span></h1>
  <div class="meta">观察窗口 {esc(win[0])} ~ {esc(win[1])} &nbsp;·&nbsp;
近期对比 {payload.get('params', {}).get('recent_days')} 个交易日 &nbsp;·&nbsp;
生成于 {esc(payload.get('generated_at'))} &nbsp;·&nbsp;
接口请求 {stats.get('requests', 0)} 次 / 缓存命中 {stats.get('cache_hits', 0)} 次</div>
</div>

<div class="card"><h3>今日速览</h3>
<ul class="concl">{''.join(f'<li>{esc(c)}</li>' for c in concl) or '<li>无明显信号。</li>'}</ul></div>

<div class="section"><span class="idx">1</span><span class="t">当日龙虎榜个股 TOP{min(len(top_stocks), 20)}</span></div>
<div class="card">{_stock_table(top_stocks)}</div>

<div class="section"><span class="idx">2</span><span class="t">市场资金面</span></div>
{_rank_section(payload.get('market_summary') or {})}
{_summary_section(payload)}

<div class="section"><span class="idx">3</span><span class="t">重点席位画像</span>
  <span class="cnt">{min(len(profs), 20)} 个</span></div>
<p class="small" style="margin-bottom:12px">画像 = 窗口内历史统计 + 知识库先验；「近期二次分析」= 近
{payload.get('params', {}).get('recent_days')} 个交易日实际打法 vs 更长基线。</p>
{seat_cards}

<div class="foot">{esc(DISCLAIMER)}<br>
数据源：东方财富数据中心（龙虎榜四张报表）。
席位知识库：references/seats_knowledge.md（先验，可能随席位漂移过期，以统计为准）。</div>
</div></body></html>"""
