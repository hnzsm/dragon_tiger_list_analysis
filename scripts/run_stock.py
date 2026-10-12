# -*- coding: utf-8 -*-
"""单只股票龙虎榜分析 · 入口（薄壳，逻辑在 stock_analysis.py）。

    python scripts/run_stock.py --code 300821
    python scripts/run_stock.py --name 东岳硅材 --date 2026-10-12

用户给一只票 → 输出该票的龙虎榜榜单、上榜席位画像（历史风格 + 近期二次分析）、
该股历史上榜后表现。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_analysis import main  # noqa: E402

if __name__ == "__main__":
    main()
