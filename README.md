# 龙虎榜个股分析（A 股）

输入一只上过龙虎榜的票（代码或名称），输出这只票的**全套龙虎榜解读**：

1. **榜单还原** —— 当日买入前五 / 卖出前五席位、榜单买卖净额、龙虎榜成交占比与上榜后涨跌幅；
2. **上榜席位画像** —— 每个席位的知识库先验 + 该席位历史统计（上榜次数 / 净买入 / 次日胜率 / 持股周期 / 一日游率 / 打板低吸倾向）+ 近 5 日操作风格二次分析；
3. **该股历史上榜后表现** —— 它自己上榜 N 次后的后 1/2/3/5/10 日平均涨跌幅与胜率。

产出**单文件 HTML 报告**（深色玻璃拟态、涨红跌绿）+ 全量 JSON。全部本地完成：不调大模型、不依赖 CDN，断网也能打开生成的 HTML。

> 数据源：东方财富数据中心公开报表。仅供个人研究，**不构成投资建议**。

## 快速开始

```bash
pip install requests
# Windows 控制台先执行，否则中文乱码
set PYTHONUTF8=1

# ★ 主入口：分析一只票（默认取它最近一次上榜日）
python scripts/run_stock.py --code 300821

# 按名称
python scripts/run_stock.py --name 东岳硅材

# 指定某一次上榜日 + 调参
python scripts/run_stock.py --code 000892 --date 2026-10-12 --lookback 120 --recent-days 5

# 全市场日报（另一条线）
python scripts/run_daily.py --date 2026-10-12 --top-seats 15

# 回归自测（纯离线，秒级）
python scripts/selftest.py
```

产出落 `--outdir`（默认 `out/`）：`stock_{代码}_{上榜日}.html` / `.json`，日报为 `lhb_report_{date}.html`。

## 目录结构

```
SKILL.md              skill 说明（给 agent 读的入口）
scripts/
  run_stock.py        ★ 单股分析入口（薄壳，逻辑在 stock_analysis.py）
  stock_analysis.py   单股主编排：榜单还原 / 席位归集 / 该股历史 / 综合结论
  report_stock.py     单股 HTML 渲染（复用 report.py 的版式与配色）
  run_daily.py        全市场日报主编排
  lhb_api.py          东财报表封装 + 缓存 + 退避重试 + 交易日历降级
  seats_kb.py         知名席位知识库（机器可读，含匹配规则 / 置信度）
  seat_profile.py     聚合去重 + 统计画像 + 风格标签推断
  recent_activity.py  近期二次分析 + 市场级汇总
  report.py           日报 HTML 渲染（CSS / 工具函数的来源）
  selftest.py         离线回归（45 项断言）
references/
  api_sources.md      接口实测档案（reportName / 字段 / 坑 / 口径实证）
  indicators.md       指标口径唯一来源（报告数字怎么来的）
  seats_knowledge.md  席位知识库人读版
```

## 几个关键口径

* **多上榜原因 ≠ 多份榜单**：同一交易日「日换手率20%」与「日涨幅偏离7%」的买五/卖五名单**逐分相同**，是**同一份榜单**，必须按榜单金额签名分组合并；「连续三日累计」才是独立榜单。
* **席位净额 = 买榜金额 − 卖榜金额**（自算）。东财买卖前五报表自带的 `NET` 字段口径矛盾，一律不用。
* **跨榜单金额不可相加**：3 日累计榜与单日榜统计区间重叠。
* **席位流水按 `(日期, 代码, 买入, 卖出)` 四元组去重**，否则多上榜原因重复出行会让金额虚高 1~3 倍。
* 席位知识库是**先验**，席位会漂移（券商合并改名）；与统计矛盾时**以统计为准**，小样本（<10）标注样本量。

## 作为 WorkBuddy / Claude Code Skill 使用

把本目录放到 `~/.workbuddy/skills/lhb-stock-analysis/` 即可被识别（`SKILL.md` 的 frontmatter 已就绪）。
