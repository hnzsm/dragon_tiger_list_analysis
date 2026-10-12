# -*- coding: utf-8 -*-
"""东方财富龙虎榜数据接口封装（datacenter-web.eastmoney.com）。

四个报表（2026-10-12 实测，全部免登录，字段口径见 references/api_sources.md）：

| reportName | 粒度 | 关键字段 |
|---|---|---|
| RPT_DAILYBILLBOARD_DETAILSNEW | 股票×日 | CHANGE_RATE, TURNOVERRATE, D1/D2/D5/D10/D20/D30_CLOSE_ADJCHRATE, EXPLANATION, EXPLAIN(解读) |
| RPT_OPERATEDEPT_ACTIVE | 席位×日 | TOTAL_BUYAMT/TOTAL_SELLAMT/TOTAL_NETAMT, BUY_STOCK(逗号分隔), BUYER_APPEAR_NUM |
| RPT_OPERATEDEPT_TRADE_DETAILSNEW | 席位×股票×日 | ACT_BUY/ACT_SELL/NET_AMT, CHANGE_RATE, D1~D30_CLOSE_ADJCHRATE, EXPLANATION |
| RPT_TRADE_BACK_PROFILE | 席位×统计周期 | RISE_PROBABILITY_1/2/3/5/10DAY, AVERAGE_INCREASE_*（官方回测画像） |

交易日历用上证指数日线（push2his）推导。

工程约束：
* 本地 JSON 缓存（默认 `cache/`），同参数二次运行零请求；
* 5xx/429/网络异常按 2/4/6/8s 退避重试 4 次（实测撞过瞬时 500）；
* 请求间隔 `delay` 默认 0.4s，别调 0。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date as _date, timedelta as _timedelta

import requests

BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

RETRY_WAITS = [0, 2, 4, 6, 8]  # 秒；第 1 次不等待直接重试逻辑由 attempt 控制


class LhbApi:
    def __init__(self, cache_dir: str | None = None, timeout: int = 20, delay: float = 0.4):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.timeout = timeout
        self.delay = delay
        self.cache_dir = cache_dir
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0}

    # ------------------------------------------------------------ 底层：缓存 + 重试
    def _cache_path(self, key: str) -> str | None:
        if not self.cache_dir:
            return None
        os.makedirs(self.cache_dir, exist_ok=True)
        h = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"{h}.json")

    def _read_cache(self, cp: str | None):
        if cp and os.path.exists(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    self.stats["cache_hits"] += 1
                    return json.load(f)
            except Exception:
                return None  # 缓存损坏就重新拉
        return None

    def _write_cache(self, cp: str | None, j: dict) -> None:
        if not cp:
            return
        try:
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False)
        except Exception:
            pass

    def _get_json(self, url: str, params: dict, cache_key: str,
                  require_result: bool = True) -> dict:
        """带缓存 + 退避重试的 GET（datacenter 与 kline 两个 host 共用）。"""
        cp = self._cache_path(cache_key)
        hit = self._read_cache(cp)
        if hit is not None:
            return hit
        last_err = None
        for wait in RETRY_WAITS:
            if wait:
                self.stats["retries"] += 1
                time.sleep(wait)
            try:
                self.stats["requests"] += 1
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code >= 500 or r.status_code == 429:
                    last_err = f"HTTP {r.status_code}"
                    continue
                j = r.json()
                if require_result and j.get("result") is None:
                    raise RuntimeError(f"接口无结果: {j.get('message')}")
                self._write_cache(cp, j)
                return j
            except (requests.RequestException, ValueError) as e:
                last_err = f"{type(e).__name__}: {e}"
        raise RuntimeError(f"重试 {len(RETRY_WAITS)} 次仍失败: {last_err}")

    def _fetch_all(self, report_name: str, filter_: str, sort: str,
                   page_size: int = 500) -> list[dict]:
        """datacenter 报表全量翻页拉取。"""
        out: list[dict] = []
        page = 1
        while True:
            j = self._get_json(BASE, {
                "sortColumns": sort,
                "sortTypes": "-1,1" if "," in sort else "-1",
                "pageSize": page_size, "pageNumber": page,
                "reportName": report_name, "columns": "ALL",
                "source": "WEB", "client": "WEB", "filter": filter_,
            }, cache_key=f"{report_name}|{filter_}|{sort}|p{page}")
            res = j["result"]
            rows = res.get("data") or []
            out.extend(rows)
            if page >= res.get("pages", 1) or not rows:
                break
            page += 1
            time.sleep(self.delay)
        return out

    # ------------------------------------------------------------ 业务接口
    def daily_stock_detail(self, trade_date: str) -> list[dict]:
        """个股每日龙虎榜（股票×日）。trade_date='YYYY-MM-DD'。"""
        return self._fetch_all(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            f"(TRADE_DATE='{trade_date}')",
            "TRADE_DATE,SECURITY_CODE")

    def seat_daily(self, trade_date: str) -> list[dict]:
        """席位×日汇总：当日每个席位买了哪些股票、买卖总额。"""
        return self._fetch_all(
            "RPT_OPERATEDEPT_ACTIVE",
            f"(ONLIST_DATE='{trade_date}')",
            "ONLIST_DATE,TOTAL_BUYAMT")

    def seat_trades(self, seat_code: str, start: str, end: str) -> list[dict]:
        """席位×股票×日成交流水。start/end='YYYY-MM-DD'。

        ⚠ 同一 (席位,股票,日) 可能因多个上榜原因出现多行，下游必须按
        (TRADE_DATE, SECURITY_CODE) 聚合后再用。
        """
        return self._fetch_all(
            "RPT_OPERATEDEPT_TRADE_DETAILSNEW",
            f'(OPERATEDEPT_CODE="{seat_code}")(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{end}\')',
            "TRADE_DATE,SECURITY_CODE")

    def seat_back_profile(self, seat_code: str) -> list[dict]:
        """席位官方回测画像（近一月/三月/六月/一年 4 行）。"""
        return self._fetch_all(
            "RPT_TRADE_BACK_PROFILE",
            f'(OPERATEDEPT_CODE="{seat_code}")',
            "STATISTICSCYCLE")

    # ------------------------------------------------------------ 单股票维度
    def stock_board_history(self, code: str, max_pages: int = 4) -> list[dict]:
        """单只股票的**全部**历史龙虎榜记录（股票×日×上榜原因），按日期倒序。

        字段：TRADE_DATE / CHANGE_RATE / TURNOVERRATE / 榜单买卖净额 /
        EXPLANATION(上榜原因) / EXPLAIN(东财解读) / D1~D30_CLOSE_ADJCHRATE(后验涨跌幅)。

        ⚠ 同一交易日有多个上榜原因时会多行，其中「日换手率达到20%」与
        「日涨幅偏离值达到7%」这类**榜单数据完全相同**（见 stock_analysis.group_boards
        的金额签名分组），别直接按行数统计上榜次数。
        """
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            j = self._get_json(BASE, {
                "sortColumns": "TRADE_DATE", "sortTypes": "-1",
                "pageSize": 500, "pageNumber": page,
                "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
                "columns": "ALL", "source": "WEB", "client": "WEB",
                "filter": f'(SECURITY_CODE="{code}")',
            }, cache_key=f"stockhist|{code}|p{page}")
            res = j.get("result") or {}
            rows = res.get("data") or []
            out.extend(rows)
            if page >= (res.get("pages") or 1) or not rows:
                break
            time.sleep(self.delay)
        return out

    def board_seats(self, trade_date: str, code: str, side: str) -> list[dict]:
        """某股某日的**买入/卖出前五席位明细**。

        side='buy' → RPT_BILLBOARD_DAILYDETAILSBUY（字段 BUY/NET 为买入额/净额）
        side='sell' → RPT_BILLBOARD_DAILYDETAILSSELL（字段 SELL/NET 为卖出额/净额）

        ⚠ 每个上榜原因各有一套买五卖五；同一天「数据相同」的两个原因会重复出行
        （如「日换手率20%」与「日涨幅偏离7%」的名单**逐分相同**）。
        去重与榜单分组统一走 stock_analysis.group_boards，别在别处重写。
        """
        report = ("RPT_BILLBOARD_DAILYDETAILSBUY" if side == "buy"
                  else "RPT_BILLBOARD_DAILYDETAILSSELL")
        col = "BUY" if side == "buy" else "SELL"
        # 只按金额列排序（sortTypes 单列时是 -1 降序）——
        # ⚠ 别写成 "TRADE_DATE,BUY"：_fetch_all 对多列固定给 "-1,1"，
        # 第二列会变成**升序**，取到的就不是「前五」了。
        return self._fetch_all(
            report, f'(TRADE_DATE=\'{trade_date}\')(SECURITY_CODE="{code}")',
            col, page_size=100)

    def resolve_stock(self, query: str, max_scan_days: int = 60) -> dict | None:
        """股票查询串 → {code, name, last_date, n_boards}。支持代码 / 名称 / 带后缀代码。

        代码路径一次请求；名称路径先精确匹配，失败则回扫最近交易日榜单做子串匹配
        （东财 datacenter **不支持 like 查询**，实测返回「不支持like查询」）。
        只认龙虎榜历史里出现过的票 —— 本 skill 的分析全部基于龙虎榜。
        """
        q = (query or "").strip()
        if not q:
            return None
        m = re.search(r"(\d{6})", q)
        if m:
            code = m.group(1)
            j = self._get_json(BASE, {
                "sortColumns": "TRADE_DATE", "sortTypes": "-1",
                "pageSize": 1, "pageNumber": 1,
                "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE",
                "source": "WEB", "client": "WEB",
                "filter": f'(SECURITY_CODE="{code}")',
            }, cache_key=f"resolve|code|{code}", require_result=False)
            res = j.get("result") or {}
            data = res.get("data") or []
            if data:
                return {"code": code, "name": data[0].get("SECURITY_NAME_ABBR") or "",
                        "last_date": (data[0].get("TRADE_DATE") or "")[:10],
                        "n_boards": res.get("count")}
            return {"code": code, "name": "", "last_date": None, "n_boards": 0}

        # 精确名称
        j = self._get_json(BASE, {
            "sortColumns": "TRADE_DATE", "sortTypes": "-1",
            "pageSize": 1, "pageNumber": 1,
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE",
            "source": "WEB", "client": "WEB",
            "filter": f'(SECURITY_NAME_ABBR="{q}")',
        }, cache_key=f"resolve|name|{q}", require_result=False)
        res = j.get("result") or {}
        data = res.get("data") or []
        if data:
            return {"code": data[0].get("SECURITY_CODE"), "name": q,
                    "last_date": (data[0].get("TRADE_DATE") or "")[:10],
                    "n_boards": res.get("count")}

        # 子串兜底：回扫最近交易日榜单
        days = self.trading_days(_date.today().isoformat(), n=max_scan_days)
        hits: dict[str, dict] = {}
        for d in reversed(days):
            for r in self.daily_stock_detail(d):
                nm = r.get("SECURITY_NAME_ABBR") or ""
                if q in nm:
                    hits.setdefault(r["SECURITY_CODE"], {
                        "code": r["SECURITY_CODE"], "name": nm,
                        "last_date": (r.get("TRADE_DATE") or "")[:10], "n_boards": None})
            if hits:
                break
        if len(hits) == 1:
            return next(iter(hits.values()))
        if hits:
            return {"ambiguous": list(hits.values())}
        return None

    def trading_days(self, end: str, n: int = 30) -> list[str]:
        """截止 end 的最近 n 个交易日。

        主路径：上证指数日线（push2his）—— 权威，但实测会被代理间歇性封掉；
        降级路径：datacenter 龙虎榜明细的 distinct TRADE_DATE（≈交易日历，
        理论上「无龙虎榜异动」的极平静交易日会缺，A 股现实中基本每天都有榜）。
        """
        try:
            j = self._get_json(KLINE, {
                "secid": "1.000001",
                "fields1": "f1,f2,f3",
                "fields2": "f51,f52,f53",
                "klt": "101", "fqt": "1", "end": "20500101", "lmt": max(n, 30) + 10,
            }, cache_key=f"kline|000001|{end}|{n}", require_result=False)
            klines = ((j.get("data") or {}).get("klines")) or []
            days = [k.split(",")[0] for k in klines]
            days = [d for d in days if d <= end]
            if days:
                return days[-n:]
        except Exception:
            pass  # 走降级
        start = (_date.fromisoformat(end) - _timedelta(days=n * 2 + 20)).isoformat()
        seen: set[str] = set()
        page = 1
        while page <= 15:
            j = self._get_json(BASE, {
                "sortColumns": "TRADE_DATE", "sortTypes": "-1",
                "pageSize": 500, "pageNumber": page,
                "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
                "columns": "TRADE_DATE", "source": "WEB", "client": "WEB",
                "filter": f"(TRADE_DATE>='{start}')(TRADE_DATE<='{end}')",
            }, cache_key=f"calendar|{start}|{end}|p{page}")
            res = j.get("result") or {}
            for r in res.get("data") or []:
                d = (r.get("TRADE_DATE") or "")[:10]
                if d:
                    seen.add(d)
            if page >= (res.get("pages") or 1) or len(seen) >= n + 5:
                break
            page += 1
            time.sleep(self.delay)
        return sorted(seen)[-n:]
