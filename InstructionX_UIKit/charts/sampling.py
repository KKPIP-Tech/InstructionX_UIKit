# -*- coding: utf-8 -*-
"""大规模数据的运行时降采样与保真承诺（CHART_SPEC §8.2 采样）。

**保真承诺（首要条款）**：当某系列在当前视口内的可见点数不超过视口像素
宽度时，**不进行任何降采样**——全部点按原始分辨率参与绘制。采样阈值是
运行时按视口宽度实时计算的，因此调用方无需预先知道轴范围或图表尺寸。

超过阈值时采用**逐桶保留极值**（min/max 包络，等价于 ECharts 的
``sampling: 'minmax'``）：

- 把数据按 x 顺序切成 ``threshold`` 个桶，每桶输出该桶 y 的最小值与最大值
  所在的原始点，并**按 x 顺序还原**，从而完整保留尖峰与毛刺；
- 丢掉的只是「同一像素列内部的中间起伏顺序」——那部分在屏幕上不可分辨；
- 因此降采样后的**逐像素列 y 极值与全量直绘一致**，这正是可验证的判据
  （见 temp/verify_sampling.py 与将来的 tests/test_chart_large.py）。

**只对数值型数据生效**：折线/面积/柱状/散点的原始数值序列可直接采样；
candlestick / boxplot / pie / sankey 等**结构型数据**（列表项为 ``[o,c,l,h]``
或字典）一律原样返回，由各渲染器自行处理（它们的点数通常很小）。
"""

import math
import numbers

from .data import NumericBuffer

__all__ = [
    "SamplingOptions",
    "sampling_options",
    "visible_threshold",
    "bucket_count",
    "bucket_sample",
    "sample_entries",
]

try:  # pragma: no cover - 环境相关分支
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None

#: 采样方式（当前实现 minmax；lttb/average 保留选项名以便后续扩展）
_METHODS = ("minmax", "lttb", "average")

#: 每个显示像素允许承载的最大点数（阈值 = 视口像素宽 × 该系数）
_DEFAULT_SAFETY = 2.0

#: 低于该点数不做任何采样判断（小数据的开销不值得引入分支）
_MIN_CANDIDATES = 512


class SamplingOptions:
    """一次性解析出的采样参数（避免逐帧反复解析 option）。"""

    __slots__ = ("method", "safety")

    def __init__(self, method="minmax", safety=_DEFAULT_SAFETY) -> None:
        self.method = method
        self.safety = float(safety)

    @property
    def enabled(self) -> bool:
        return self.method is not None

    def __repr__(self) -> str:
        return f"SamplingOptions(method={self.method!r}, safety={self.safety})"


def sampling_options(series_opt: dict) -> SamplingOptions:
    """解析系列 option 的采样配置。

    - ``sampling``: ``"minmax"``（默认）/ ``"lttb"`` / ``"average"`` /
      ``None``（显式关闭，帧率不作保证）/ 缺省（自动）；
    - ``samplingSafety``: 阈值系数，默认 2.0。

    未知取值回退为默认，不抛异常（与 charts 包既有的容灾风格一致）。
    """
    opt = series_opt if isinstance(series_opt, dict) else {}
    raw = opt.get("sampling", "minmax")
    if raw is None or raw is False:
        method = None
    else:
        name = str(raw).strip().lower()
        method = name if name in _METHODS else "minmax"
    safety = opt.get("samplingSafety", _DEFAULT_SAFETY)
    try:
        safety = float(safety)
    except (TypeError, ValueError):
        safety = _DEFAULT_SAFETY
    if not math.isfinite(safety) or safety <= 0:
        safety = _DEFAULT_SAFETY
    return SamplingOptions(method, safety)


def visible_threshold(viewport_px, safety: float = _DEFAULT_SAFETY) -> int:
    """由视口像素宽推导采样**判定阈值**（可见点数超过它才降采样）。"""
    try:
        px = float(viewport_px)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(px) or px <= 0:
        return 0
    return max(2, int(px * max(0.1, float(safety))))


def bucket_count(viewport_px) -> int:
    """由视口像素宽推导**产出桶数**（= 视口像素宽）。

    为什么桶数必须等于视口像素宽而不是阈值：桶是「一个像素列的样本」，
    只有桶边界与像素列边界对齐，抽样结果的**逐像素列极值才与全量直绘严格
    一致**。若桶数取阈值（= 2×像素宽），每列会跨两个桶，桶内极值可能落在
    列边界外侧，该列的极值随即丢失（实测 300 列中有 8 列出现此偏差）。
    """
    try:
        px = float(viewport_px)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(px) or px <= 0:
        return 0
    return max(2, int(px))


def _bucket_bounds(n: int, threshold: int):
    """把 ``n`` 个点切成 ``threshold`` 个桶，返回 (start, end) 对。

    **桶区间即像素列区间**，由列边界正向推导，二者恒等：

    - 像素列 c 覆盖 ``[ceil(c·n/m), ceil((c+1)·n/m))``（m = 像素列数）；
    - 故 ``lo = ceil(c·n/m)``，``hi = ceil((c+1)·n/m)``（末桶取 n）。

    这一步**必须**如此推导，先前三种朴素写法均被实测证伪：
    ``int(b·(n/m))`` 有 1/300 列丢极值；``int(b·n/m)`` 有 200/300 桶错位；
    ``floor((c+1)·n/m)`` 作上界时每桶比列区间少一个元素（首桶 [0,666) 而列区间
    为 [0,667)），导致约 1/3 的下标落在所有桶之外、其极值从输出中消失。
    """
    if threshold >= n or threshold < 2:
        return None
    ceil_div = lambda a, b: -((-a) // b)   # noqa: E731 - 局部小工具
    out = []
    for c in range(threshold):
        lo = ceil_div(c * n, threshold)
        hi = n if c == threshold - 1 else ceil_div((c + 1) * n, threshold)
        if hi <= lo:
            lo = min(c, n - 1)
            hi = min(lo + 1, n)
        out.append((lo, hi))
    return out


def bucket_sample(values, threshold: int, x_values=None):
    """逐桶保留极值（min/max 包络）。

    参数:
        values: 数值序列（``NumericBuffer`` / list / ndarray）。
        threshold: 目标桶数（约等于目标输出点数）。
        x_values: 可选，与 ``values`` 等长的 x 序列；传入时输出
                  ``[(x, y), ...]``，否则输出 ``[(index, y), ...]``。

    返回 ``(sampled, sampled_count)``；未发生采样时 ``sampled`` 为 ``None``
    （调用方应继续使用原始数据）。输出的 x 顺序与输入一致（极值按原位置
    还原），保证折线形状保真且单调。
    """
    try:
        n = len(values)
    except TypeError:
        return None, 0
    bounds = _bucket_bounds(n, threshold)
    if bounds is None:
        return None, 0

    use_np = _np is not None
    if use_np:
        v = values.raw if isinstance(values, NumericBuffer) else values
        x = None
        if x_values is not None:
            x = x_values.raw if isinstance(x_values, NumericBuffer) else x_values
        try:
            v = _np.asarray(v, dtype=_np.float64)
            if x is not None:
                x = _np.asarray(x, dtype=_np.float64)
        except (TypeError, ValueError):
            # 判别与转换不一致时安全放弃采样（绝不因数据形态误判而中断绘制）
            return None, 0
    else:
        v = values
        x = x_values

    out = []
    ap = out.append
    for s, e in bounds:
        if use_np:
            seg = v[s:e]
            imin = s + int(_np.argmin(seg))
            imax = s + int(_np.argmax(seg))
        else:
            imin = s
            imax = s
            lo = hi = v[s]
            for j in range(s + 1, e):
                val = v[j]
                if val < lo:
                    lo, imin = val, j
                if val > hi:
                    hi, imax = val, j
        if imin == imax:
            idxs = (imin,)
        elif imin < imax:
            idxs = (imin, imax)
        else:
            idxs = (imax, imin)
        for j in idxs:
            if x is None:
                ap((j, float(v[j])))
            else:
                ap((float(x[j]), float(v[j])))
    return out, len(out)


def _sample_kind(obj) -> str:
    """抽样判别数据承载形态：``scalar`` 可采样，其余不采样。

    抽样**必须覆盖首尾**：只按固定步长从前向后抽样时，形如
    ``[数值×300] + [None×300] + [字典×300]`` 的混合数据会被误判为纯数值
    （抽样点全落在前段），随后在 ``asarray`` 处抛异常。前后各抽一段并覆盖
    尾部即可识别这类结构。
    """
    if isinstance(obj, NumericBuffer) or (_np is not None
                                          and isinstance(obj, _np.ndarray)):
        return "scalar"
    if not isinstance(obj, (list, tuple)):
        return "other"
    n = len(obj)
    if n == 0:
        return "other"
    # 抽样下标：前 24 个 + 等距 16 个 + 后 24 个，保证尾部结构可见
    idxs = set(range(min(24, n)))
    step = max(1, n // 16)
    idxs.update(range(0, n, step))
    idxs.update(range(max(0, n - 24), n))
    seen_scalar = False
    for i in sorted(idxs):
        v = obj[i]
        if v is None:
            continue
        if isinstance(v, bool):
            return "other"
        # 用 numbers.Real 而非 (int, float)：numpy 标量（np.float64 等）
        # 不是 Python float 的子类，只认原生类型会把数值数据误判为不可采样，
        # 表现为「明明是大数组却完全不降采样」。
        if isinstance(v, numbers.Real):
            seen_scalar = True
            continue
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return "pair"
        return "other"
    # 注意：必须在这里显式判定，不能依赖循环自然结束后的 return——
    # 那样会落到函数末尾的 "other"，使数值序列永远判不出 scalar、
    # 采样形同未接入（此缺陷曾实际发生并被本节测试捕获）。
    return "scalar" if seen_scalar else "other"


def sample_entries(data, threshold: int, buckets: int = None,
                   x_of_index=None):
    """按数据承载形态选择采样路径。

    参数:
        data: 系列数据。
        threshold: **判定阈值**——点数不超过它时一律不采样（保真承诺）。
        buckets: **产出桶数**，默认与 ``threshold`` 相同；调用方应传入
                 ``bucket_count(视口像素宽)`` 以保证逐像素列极值严格一致。
        x_of_index: 可调用对象，把下标映射为 x（缺省用下标本身）。

    返回 ``(entries, sampled)``：``entries`` 为 ``[(x, y), ...]`` 或 ``None``
    （``None`` 表示未采样，调用方应走原始逐点路径）；``sampled`` 为是否发生
    了降采样。

    仅 ``scalar``（数值序列）与 ``pair``（``[x, y]`` 数值对序列）会采样；
    ``other``（字典项、含 None 混合、缺 y 等）一律不采样。
    """
    kind = _sample_kind(data)
    if kind == "other":
        return None, False
    n = len(data)
    if n <= threshold or threshold < 2:
        return None, False
    if buckets is None:
        buckets = threshold

    if kind == "scalar":
        if x_of_index is None:
            entries, _ = bucket_sample(data, buckets)
        else:
            xs = [x_of_index(i) for i in range(n)]
            entries, _ = bucket_sample(data, buckets, xs)
        return entries, entries is not None

    # pair：[x, y] 序列
    if _np is not None:
        try:
            arr = _np.asarray(data, dtype=_np.float64)
        except (TypeError, ValueError):
            return None, False
        if arr.ndim != 2 or arr.shape[1] < 2:
            return None, False
        entries, _ = bucket_sample(arr[:, 1], buckets, arr[:, 0])
        return entries, entries is not None
    try:
        ys = [float(item[1]) for item in data]
        xs = [item[0] for item in data]
    except (TypeError, ValueError, IndexError):
        return None, False
    entries, _ = bucket_sample(ys, buckets, xs)
    return entries, entries is not None
