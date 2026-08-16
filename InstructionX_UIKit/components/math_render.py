# -*- coding: utf-8 -*-
"""LaTeX 数学公式渲染（SPEC §5.2 markdown_view 的内部依赖）。

基于 matplotlib mathtext 引擎渲染 LaTeX 数学公式为透明底 ``QImage``
（SPEC 依赖例外：matplotlib 经用户批准引入，仅用于公式渲染）。

性能设计（面向流式输出场景）：

- **LRU 缓存**：以 ``(公式源码, 颜色, 字号)`` 为键缓存渲染产物（上限 512 条），
  流式追加导致的全文重渲染命中缓存时零耗时，已渲染公式不会重复渲染；
- **异步渲染**：未命中的公式进入单后台 worker 串行渲染（matplotlib 非线程
  安全，串行也避免字体缓存竞态），渲染期间正文照常显示、公式以源码占位，
  完成后经 ``image_ready`` 信号通知视图重排；
- **2x 超采样**：渲染输出 2 倍像素并设置 ``devicePixelRatio=2``，
  QTextDocument 按逻辑尺寸排版，高 DPI 屏幕下保持清晰。
"""

import io
import queue
import threading
from collections import OrderedDict

import matplotlib

matplotlib.use("Agg")  # 必须早于 pyplot / mathtext 相关导入

from matplotlib import mathtext
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

__all__ = ["MathRenderHub"]

#: 超采样倍率（高 DPI 清晰度；QTextDocument 尊重 QImage 的 DPR）
_SS = 2
#: LRU 缓存容量（条）
_CACHE_CAP = 512

#: 渲染失败占位（缓存中区别于 QImage 的哨兵）
_FAILED = object()


def _render_png_bytes(latex: str, color_hex: str, pt: float,
                      display: bool = False) -> bytes:
    """同步渲染一条公式为 PNG 字节流（在后台 worker 线程调用）。

    注意：``math_to_image`` 要求数学部分必须包在 ``$...$`` 中，
    否则整串按普通文本排版；mathtext 不支持 ``\\displaystyle``，
    其 ``\\frac``/``\\sum`` 等本就以展示样式排版，display 仅用于
    调用方的字号放大。``savefig`` 必须 ``transparent=True``，
    否则暗色主题下公式带不透明白底。
    """
    src = f"${latex}$"
    prop = FontProperties(size=pt * _SS)
    parser = mathtext.MathTextParser("path")
    width, height, depth, _, _ = parser.parse(src, dpi=72, prop=prop)
    fig = Figure(figsize=(width / 72.0, height / 72.0))
    fig.text(0, depth / height, src, fontproperties=prop, color=color_hex)
    buf = io.BytesIO()
    fig.savefig(buf, dpi=96 * _SS, format="png", transparent=True)
    return buf.getvalue()


class MathRenderHub(QObject):
    """公式渲染中枢（单例）：LRU 缓存 + 后台串行渲染 worker。

    用法::

        hub = MathRenderHub.instance()
        img = hub.get(key)            # 命中返回 QImage，未命中返回 None
        if img is None:
            hub.request(key, latex, color_hex, pt)   # 后台渲染
        hub.image_ready.connect(...)  # 完成后再次 get 即命中

    全部公开方法须在 GUI 线程调用；worker 线程只产出 PNG 字节流，
    ``QImage`` 的装载在 GUI 线程完成。
    """

    #: 某键渲染完成并写入缓存后发射（参数为缓存键）
    image_ready = Signal(str)

    #: worker → GUI 线程的内部传递信号（键, PNG 字节流 | None）
    _rendered = Signal(str, object)

    _instance = None
    _lock = threading.Lock()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = OrderedDict()      # key -> QImage | _FAILED
        self._pending = set()            # 已入队未完成的 key
        self._queue = queue.Queue()
        self._rendered.connect(self._on_rendered)
        self._worker = threading.Thread(target=self._worker_loop,
                                        name="uik-math-render", daemon=True)
        self._worker.start()

    @classmethod
    def instance(cls) -> "MathRenderHub":
        """返回全局唯一实例（须在 GUI 线程首次调用）。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ 键
    @staticmethod
    def key_for(latex: str, color_hex: str, pt: float) -> str:
        """计算缓存键。"""
        return f"{color_hex}|{pt:.2f}|{latex}"

    # ------------------------------------------------------------------ 查询
    def get(self, key: str):
        """查缓存：命中返回 ``QImage``；渲染失败返回 None 且 ``is_failed`` 可查。"""
        if key in self._cache:
            self._cache.move_to_end(key)
            value = self._cache[key]
            return None if value is _FAILED else value
        return None

    def is_failed(self, key: str) -> bool:
        """该键是否已渲染失败（调用方应回退为源码文本显示）。"""
        return self._cache.get(key) is _FAILED

    # ------------------------------------------------------------------ 请求
    def request(self, key: str, latex: str, color_hex: str, pt: float,
                display: bool = False) -> None:
        """请求后台渲染（已缓存 / 已入队的请求自动去重）。"""
        if key in self._cache or key in self._pending:
            return
        self._pending.add(key)
        self._queue.put((key, latex, color_hex, pt, display))

    # ------------------------------------------------------------------ worker
    def _worker_loop(self) -> None:
        while True:
            key, latex, color_hex, pt, display = self._queue.get()
            try:
                data = _render_png_bytes(latex, color_hex, pt, display)
            except Exception:
                data = None
            self._rendered.emit(key, data)

    def _on_rendered(self, key: str, data) -> None:
        """GUI 线程：装载 QImage 写缓存并广播完成信号。"""
        self._pending.discard(key)
        img = None
        if data:
            img = QImage()
            if img.loadFromData(data, "PNG"):
                img.setDevicePixelRatio(_SS)
            else:
                img = None
        self._cache[key] = img if img is not None else _FAILED
        while len(self._cache) > _CACHE_CAP:
            self._cache.popitem(last=False)
        self.image_ready.emit(key)
