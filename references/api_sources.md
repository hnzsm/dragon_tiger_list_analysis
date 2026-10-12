# 数据接口实测档案（龙虎榜）

> 2026-10-12 首测，均为真机验证。接口全免登录，宿主 `datacenter-web.eastmoney.com`。
> 代理环境下 **push2his / push2 会被间歇性封掉**（ProxyError），交易日历已做降级（见 §5）。

## 1. RPT_DAILYBILLBOARD_DETAILSNEW —— 个股每日龙虎榜（股票×日）

```
GET https://datacenter-web.eastmoney.com/api/data/v1/get
    ?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL&source=WEB&client=WEB
    &filter=(TRADE_DATE='2026-10-12')
    &sortColumns=TRADE_DATE,SECURITY_CODE&sortTypes=-1,-1
    &pageSize=500&pageNumber=1
```

| 字段 | 含义 |
|---|---|
| TRADE_DATE | 交易日 |
| SECURITY_CODE / SECURITY_NAME_ABBR / SECUCODE | 代码 / 名称 / 带市场后缀代码 |
| CHANGE_RATE / CLOSE_PRICE / TURNOVERRATE | 当日涨跌幅% / 收盘价 / 换手率% |
| BILLBOARD_BUY/SELL/DEAL/NET_AMT | 龙虎榜买入/卖出/成交/净买额（元） |
| DEAL_AMOUNT_RATIO / DEAL_NET_RATIO | 龙虎榜成交占市场比% / 净买占市场比% |
| **D1/D2/D5/D10/D20/D30_CLOSE_ADJCHRATE** | **上榜后 N 日涨跌幅%（东财直接给后验，不用自己拉 K 线）** |
| EXPLANATION | 上榜原因（换手率达20%、涨幅偏离7%…） |
| EXPLAIN | 东财解读（如「1家机构卖出，成功率31.52%」） |
| BUY_SEAT / SELL_SEAT | 买卖席位编码串（如 "31111"），**别解析，用 §2/§3** |

注意：**同一股票同一天会因多个上榜原因出现多行，且这些原因不一定代表多份独立榜单**
（「日换手率20%」与「日涨幅偏离7%」的榜单金额逐分相同 = 同一份榜单）。
分组口径见 §6，别只按代码去重就把行业名列成两份。

## 2. RPT_OPERATEDEPT_ACTIVE —— 席位×日汇总

```
?reportName=RPT_OPERATEDEPT_ACTIVE&columns=ALL
 &filter=(ONLIST_DATE='2026-10-12')      # 不过滤=全历史（136万行，别这么干）
 &sortColumns=ONLIST_DATE,TOTAL_BUYAMT&sortTypes=-1,1
```

| 字段 | 含义 |
|---|---|
| OPERATEDEPT_CODE / OPERATEDEPT_NAME | 席位代码 / 营业部全称 |
| ORG_NAME_ABBR | 券商简称 |
| ONLIST_DATE | 上榜日期 |
| BUY_STOCK | 当日涉及股票代码，**逗号分隔的一串** |
| TOTAL_BUYAMT / TOTAL_SELLAMT / TOTAL_NETAMT | 当日买入/卖出/净买总额（元） |
| BUYER_APPEAR_NUM / SELLER_APPEAR_NUM | 当日买入/卖出上榜股票家数 |

当日全市场约 220 行。**这是新面孔检测和当日速览的数据源。**

## 3. RPT_OPERATEDEPT_TRADE_DETAILSNEW —— 席位×股票×日成交流水

```
?reportName=RPT_OPERATEDEPT_TRADE_DETAILSNEW&columns=ALL
 &filter=(OPERATEDEPT_CODE="10046745")(TRADE_DATE>='2026-06-04')(TRADE_DATE<='2026-10-12')
 &sortColumns=TRADE_DATE,SECURITY_CODE&sortTypes=-1,1
```

| 字段 | 含义 |
|---|---|
| ACT_BUY / ACT_SELL / NET_AMT | 该席位当日买/卖该股金额（元） |
| CHANGE_RATE | 该股当日涨跌幅% |
| D1~D30_CLOSE_ADJCHRATE | 上榜后 N 日涨跌幅%（**席位画像的胜率基础**） |
| EXPLANATION | 触发本次上榜的原因 |

**⚠ 最大的坑：同一 (席位,股票,日) 会按多个上榜原因重复出行，金额完全相同。**
2026-10-12 用开源证券西安西大街实证：按 `(日期,代码,买入,卖出)` 四元组去重后，
与 §2 的 `TOTAL_BUYAMT/TOTAL_SELLAMT` **逐分吻合**；直接 SUM 会虚高 1~3 倍。
聚合逻辑在 `scripts/seat_profile.py::aggregate_seat_trades`，改前先看那个函数。

## 4. RPT_TRADE_BACK_PROFILE —— 席位官方回测画像

```
?reportName=RPT_TRADE_BACK_PROFILE&columns=ALL
 &filter=(OPERATEDEPT_CODE="10046745")   # 无 sortColumns（会报"排序列不存在"）
```

每席位 4 行（近一月/近三月/近六月/近一年）：
`RISE_PROBABILITY_1/2/3/5/10DAY`（上涨概率%）、`AVERAGE_INCREASE_*DAY`（平均涨幅%）、
`TOTAL_BUYER_SALESTIMES_*DAY`（买入次数）。**这是东财自己的回测，与我们的统计互为交叉验证。**

## 5. 交易日历（上证指数日线 + 降级）

```
GET https://push2his.eastmoney.com/api/qt/stock/kline/get
    ?secid=1.000001&fields1=f1,f2,f3&fields2=f51,f52,f53&klt=101&fqt=1&lmt=100
```

⚠ 该 host 在代理环境下会 ProxyError（datacenter 不受影响）。
降级路径（`lhb_api.py::trading_days` 已实现）：用 §1 的报表按日期区间翻页，
收集 distinct `TRADE_DATE` ≈ 交易日历（A 股基本每天都有龙虎榜，极平静日可能缺一天）。

## 6. 买卖前五席位明细（单股分析的核心）

```
?reportName=RPT_BILLBOARD_DAILYDETAILSBUY     # 买入前五
?reportName=RPT_BILLBOARD_DAILYDETAILSSELL    # 卖出前五
 &columns=ALL&source=WEB&client=WEB
 &filter=(TRADE_DATE='2026-10-12')(SECURITY_CODE="300821")
 &sortColumns=BUY&sortTypes=-1                 # 买榜按 BUY、卖榜按 SELL
 &pageSize=100&pageNumber=1
```

| 字段 | 含义 |
|---|---|
| OPERATEDEPT_CODE / OPERATEDEPT_NAME | 席位代码 / 营业部全称（**机构专用 = 代码 `0`，多家机构同名**） |
| BUY / SELL | 该席位在本榜单的买入额 / 卖出额（各报表只填自己那一侧） |
| NET | ⚠ **口径不稳定，禁止使用**（见下） |
| RISE_PROBABILITY_3DAY / TOTAL_BUYER_SALESTIMES_3DAY | 东财给的该席位 3 日上涨概率% / 样本次数 |
| EXPLANATION | 该行所属的上榜原因 |

### 6.1 榜单分组（不分组就算重）

同一交易日多个上榜原因 **不都是独立榜单**：

| 情形 | 实测证据（2026-10-12） | 处理 |
|---|---|---|
| 日换手率20% + 日涨幅偏离7% | 000892 两原因的买五名单与金额**逐分相同**；600127 的价格振幅15% 与 换手率20% 也是同一批席位 | **同一份榜单**，合并 |
| 连续三个交易日累计达X% | 000892 的三日榜买 3.17 亿 / 日榜买 1.85 亿，席位名单不同 | **独立榜单**，单列 |

分组签名 = `(BILLBOARD_BUY_AMT, BILLBOARD_SELL_AMT)`（§1 的股票级字段），金额相同即同一份榜单。
实现：`scripts/stock_analysis.py::group_boards`。

**自洽校验（已逐分验证）**：买入前五 5 行金额合计 = 榜单 `BILLBOARD_BUY_AMT`；
卖出前五 5 行金额合计 = 榜单 `BILLBOARD_SELL_AMT`。
例：300821 三日累计榜 → 买 872,130,972.19 与 5 行买五合计完全一致；卖 826,703,715.25 同理。

### 6.2 ⚠ NET 字段不可用

同一只票的同一席位，买榜与卖榜给出的 `NET` **互相矛盾**：

| 案例 | 买榜 | 卖榜 | 真实净额 |
|---|---|---|---|
| 600127 沪股通 | BUY=355,402,651.91，NET=**355,402,651.91**（=买入全额） | SELL=124,417,536.91，NET=**−124,417,536.91**（=−卖出全额） | +230,985,115.00 |
| 300821 深股通 | BUY=428,981,226.21，NET=**47,075,573.87** | SELL=381,905,652.34，NET=**47,075,573.87** | +47,075,573.87（真实） |

→ 结论：**席位净额一律自己算 = 买榜金额 − 卖榜金额**（按 seat_code+名称聚合）。

### 6.3 排序陷阱

`sortColumns` 写单列（`BUY`/`SELL`）时 sortTypes 为 `-1`（降序）；
写成 `TRADE_DATE,BUY` 时 `_fetch_all` 固定发 `-1,1`，第二列会变成**升序**，
拿到的就不是「前五」。代码里已显式按金额降序排序兜底（自测 [8] 钉住）。

### 6.4 跨榜单不可加总

「三日累计榜」与「单日榜」的统计区间**重叠**，同一笔成交会在两份榜单里各出现一次。
席位卡片按榜单分别列示买/卖/净；横跨多榜单的席位会标 `overlap`，不做合计解读。

## 7. 抓取礼仪

* datacenter 请求间隔 ≥ 0.4s（`--delay`，别调 0）；
* 5xx/429 按 2/4/6/8s 退避重试 4 次（实测撞过瞬时 500）；
* 全部响应落本地 JSON 缓存（`cache/`），重跑零请求；
* 龙虎榜数据一般当日 **18:00 后**才出全，盘中/傍晚早跑可能只有部分股票；
* **名称反查不支持 like**：`(SECURITY_NAME_ABBR like "%xx%")` 返回「不支持like查询」，
  只能精确名匹配，模糊名靠回扫最近交易日榜单做子串匹配（`lhb_api.resolve_stock`）。
