"""策略基类 + 注册表（对标 vnpy Template / freqtrade Strategy）"""

from __future__ import annotations

import inspect

from .object import Signal


class Strategy:
    name = "base"
    params: dict = {}

    def __init__(self, data_service=None, **kwargs):
        self.ds = data_service
        self.engine = None
        # 实例级参数合并（寻优时 kwargs 覆盖类默认 params）
        self.params = {**dict(getattr(self.__class__, "params", {})), **kwargs}
        for k, v in kwargs.items():
            setattr(self, k, v)

    def on_init(self):
        """初始化：加载策略所需数据"""

    def on_bar(self, symbol: str, bar) -> Signal | None:
        """每根 Bar 回调；返回 None 或 Signal"""
        return None

    def emit(self, weights: dict, reason: str = ""):
        if self.engine:
            self.engine.emit_signal(Signal(weights=weights, reason=reason))


REGISTRY: dict[str, type[Strategy]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: str, **kwargs) -> Strategy:
    if not REGISTRY:
        # 动态加载策略包（注册装饰器在导入时执行）
        import strategies  # noqa: F401
    if name not in REGISTRY:
        raise KeyError(f"未注册策略: {name}，可用 {list(REGISTRY)}")
    cls = REGISTRY[name]
    sig = inspect.signature(cls.__init__)
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values())
    params = kwargs if has_varkw else {k: v for k, v in kwargs.items() if k in sig.parameters}
    return cls(**params)
