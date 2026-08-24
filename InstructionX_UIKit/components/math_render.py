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
  QTextDocument 按逻辑尺寸排版，高 DPI 屏幕下保持清晰；
- **失败可见**：渲染异常经 sys.stderr 记录一次（按键去重），失败条目带
  时间戳，超过重试间隔后允许重新请求，也可经 ``clear_cache`` 立即清除。

线程与退出：worker 以 daemon 线程运行，``shutdown`` 以哨兵退出并 join
（实例创建时自动连接 ``aboutToQuit``）；退出期 emit 失败会被兜底捕获。
"""

import io
import queue
import sys
import threading
import time
from collections import OrderedDict

import matplotlib

from matplotlib import mathtext
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtGui import QImage

__all__ = ["MathRenderHub"]

#: 超采样倍率（高 DPI 清晰度；QTextDocument 尊重 QImage 的 DPR）
_SS = 2
#: LRU 缓存容量（条）
_CACHE_CAP = 512
#: 渲染失败后的重试间隔（秒）
_FAIL_RETRY_TTL = 10.0
#: 失败日志去重集合容量上限
_FAIL_LOG_CAP = 256

#: 渲染失败占位（缓存中区别于 QImage 的哨兵）
_FAILED = object()

#: 后端惰性设置状态（线程安全，仅设置一次）
_backend_state = {"ready": False}
_backend_lock = threading.Lock()


def _ensure_agg_backend() -> None:
    """惰性设置 Agg 后端：首次渲染前、且宿主未导入 pyplot 时。

    模块导入期不再全局调用 ``matplotlib.use("Agg")``，避免污染宿主：
    若宿主在首次公式渲染前已导入 pyplot（交互绘图），跳过设置以免
    破坏其交互后端；此时 ``Figure.savefig`` 在多数后端下仍可工作。
    """
    if _backend_state["ready"]:
        return
    with _backend_lock:
        if _backend_state["ready"]:
            return
        _backend_state["ready"] = True
        if "matplotlib.pyplot" in sys.modules:
            return  # 宿主已导入 pyplot：跳过设置
        matplotlib.use("Agg")


def _render_png_bytes(latex: str, color_hex: str, pt: float) -> bytes:
    """同步渲染一条公式为 PNG 字节流（在后台 worker 线程调用）。

    注意：``math_to_image`` 要求数学部分必须包在 ``$...$`` 中，
    否则整串按普通文本排版；mathtext 不支持 ``\\displaystyle``，
    其 ``\\frac``/``\\sum`` 等本就以展示样式排版，调用方的 display
    仅用于字号放大。``savefig`` 必须 ``transparent=True``，
    否则暗色主题下公式带不透明白底。

    字号按逻辑 pt 传入（不加超采样倍率），清晰度由 savefig 的
    2x dpi 与 QImage 的 devicePixelRatio 承担，避免双重计入
    导致公式显示为预期的 2 倍大小。
    """
    _ensure_agg_backend()
    src = f"${latex}$"
    prop = FontProperties(size=pt)
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
        self._failed_ts = {}             # 失败键 -> 时间戳（供有限重试）
        self._logged_failures = set()    # 已记录异常的键（去重、有界）
        self._pending = set()            # 已入队未完成的 key
        self._queue = queue.Queue()
        self._rendered.connect(self._on_rendered)
        self._worker = threading.Thread(target=self._worker_loop,
                                        name="uik-math-render", daemon=True)
        self._worker.start()
        app = QCoreApplication.instance()
        if app is not None:
            # 应用退出时停止 worker，避免退出期 emit 踩已销毁对象
            app.aboutToQuit.connect(self.shutdown)

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

    def clear_cache(self) -> None:
        """清空全部缓存（含失败条目与失败日志去重集合）。

        清空后失败过的公式可立即重新请求渲染（无需等待重试间隔）。
        """
        self._cache.clear()
        self._failed_ts.clear()
        self._logged_failures.clear()

    # ------------------------------------------------------------------ 请求
    def request(self, key: str, latex: str, color_hex: str, pt: float,
                display: bool = False) -> None:
        """请求后台渲染（已缓存 / 已入队的请求自动去重）。

        失败条目超过重试间隔后允许重新入队（有限重试）。
        """
        if key in self._cache:
            if self._cache.get(key) is not _FAILED:
                return
            if time.time() - self._failed_ts.get(key, 0.0) < _FAIL_RETRY_TTL:
                return
        if key in self._pending:
            return
        self._pending.add(key)
        self._queue.put((key, latex, color_hex, pt, display))

    def shutdown(self, timeout: float = 2.0) -> None:
        """停止后台 worker：哨兵退出 + join 超时（退出前经 aboutToQuit 调用）。"""
        if not self._worker.is_alive():
            return
        self._queue.put(None)
        self._worker.join(timeout)

    # ------------------------------------------------------------------ worker
    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:  # 退出哨兵
                break
            key, latex, color_hex, pt, _display = item
            try:
                data = _render_png_bytes(latex, color_hex, pt)
            except Exception as exc:
                data = None
                self._log_failure(key, exc)
            try:
                self._rendered.emit(key, data)
            except RuntimeError:
                return  # 应用退出期：接收端（GUI 对象）已销毁

    def _log_failure(self, key: str, exc: Exception) -> None:
        """渲染异常记录一次（按键去重，sys.stderr）。"""
        if key in self._logged_failures:
            return
        self._logged_failures.add(key)
        while len(self._logged_failures) > _FAIL_LOG_CAP:
            self._logged_failures.pop()
        print(f"[MathRenderHub] 公式渲染失败（回退为源码占位）: "
              f"key={key!r} error={exc!r}", file=sys.stderr)

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
        if img is None:
            self._failed_ts[key] = time.time()
        while len(self._cache) > _CACHE_CAP:
            self._cache.popitem(last=False)
        self.image_ready.emit(key)
