"""兼容性垫片：self_review 已迁入 quantos_engine.self_review（单一真源，W1-②）。

原 paddy src/utils/self_review.py 与本文件逐字相同，现由共享包提供。
透传 review_backtest / format_human / Issue / CHECKS 等，保留 `python -m engine.self_review` 入口。
"""
from quantos_engine.self_review import *  # noqa: F401,F403
from quantos_engine.self_review import main  # noqa: F401

if __name__ == "__main__":
    main()
