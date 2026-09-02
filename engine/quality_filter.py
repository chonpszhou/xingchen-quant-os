"""兼容性垫片：quality_filter 已迁入 quantos_engine.quality_filter（单一真源，W1-②）。

原 paddy src/engine/quality_filter.py 与本文件逐字相同，现由共享包提供。
透传 Fundamentals / QualityFilter / QualityReport，供 optimizer.py（live 路径）
与 research_views.py 零改动使用。
"""
from quantos_engine.quality_filter import *  # noqa: F401,F403
from quantos_engine.quality_filter import Fundamentals, QualityFilter, QualityReport  # noqa: F401
