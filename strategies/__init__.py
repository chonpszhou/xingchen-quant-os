"""策略实现（注册制，供引擎加载）"""

from .dual_momentum import DualMomentumStrategy  # noqa: F401
from .risk_parity import RiskParityStrategy  # noqa: F401
from .cb_double_low import CBDoubleLowStrategy  # noqa: F401
from .sma_cross import SMACrossStrategy  # noqa: F401 (研究驱动扫描/参数寻优单资产策略)
from .momentum import MomentumStrategy  # noqa: F401 (时间序列动量，学习报告高频主题，动态优化新增)
from .cross_sectional_momentum import CrossSectionalMomentumStrategy  # noqa: F401 (M-938 横截面因子)
from .ml_factor import MLFactorStrategy  # noqa: F401 (M-937 横截面 ML 因子)
from .vol_target_momentum import VolTargetMomentumStrategy  # noqa: F401 (M-030 波动目标仓位)
