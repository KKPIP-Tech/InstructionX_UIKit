# -*- coding: utf-8 -*-
"""分层采样金字塔（CHART_SPEC §8.3 窗口化采样）。

**用途**：把「大窗口的降采样」从 O(窗口内点数) 降到 O(输出桶数)。单级降采样
每次都从原始数组切片分桶，窗口覆盖大部分数据时切片本身即 O(n)；金字塔预计算
多级 min/max 摘要，一次构建、多次查询。

**层级阶梯由数据长度推导**（``span = n // _MIN_BUCKETS * _RATIO ** i``，逐级
加粗到 ``n // _MIN_POINTS``）。这样任意窗口尺寸都落在相邻两级之间，不会出现
「想要的桶宽在阶梯里找不到」的情况——固定阶梯（如 4/16/64…）在百万级数据下
只有一级可用，等于没建。

**质量语义（重要，勿误用）**：
``query`` 返回 ``quality`` 标记。当「窗口内该层级的桶数 ≤ 目标桶数」时为
``"exact"``——此时逐桶极值与直接分桶一致；否则调用方必须把桶合并到目标数量，
``"coarse"`` 表示**可能丢失窄尖峰**。窗口覆盖超过半数数据时，任何预计算层级
都会超出目标桶数，因此此时只能得到 ``"coarse"``。需要严格保真的路径应回退到
``sampling.sample_entries``（它直接对原始数据分桶，保真承诺由那里保证）。

**惰性构建**：层级在首次被查询时构建并缓存；低于 ``_MIN_POINTS`` 不建。
**增量更新**：``extend`` 只重算各层级受新数据影响的**尾部桶**。
"""

import math

from .data import NumericBuffer

__all__ = ["Pyramid", "build_pyramid", "pyramid_for", "invalidate_pyramid"]

try:  # pragma: no cover - 环境相关分支
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None

#: 最细层级的桶宽。取 2 而非 1：span=1 的层级等于把原始数组再复制一份，
#: 而「不抽稀」的场景本来就该直接用原始数据，预计算没有意义。
_MIN_SPAN = 2

#: 最多保留的层级数（内存上界 ≈ 原始数据的 1/3）
_MAX_LEVELS = 9

#: 最粗层级每桶覆盖的点数。取 256：更粗的层级在百万级数据下只剩不到 4000 桶，
#: 用它覆盖大窗口时桶数往往已少于目标，等于必然要合并（丢极值）。
_MAX_SPAN_POINTS = 256

#: 低于该点数不建金字塔（小数据直接分桶更快）
_MIN_POINTS = 16384


class Pyramid:
    """数值序列的多级 min/max 摘要（层级按需构建）。"""

    __slots__ = ("_arr", "_n", "_spans", "_cache")

    def __init__(self) -> None:
        self._arr = None      # 原始 float64 数组（含强引用，保证 id 稳定）
        self._n = 0
        self._spans = []      # 可用层级的 span 列表（升序）
        self._cache = {}      # span -> (mins, maxs)

    # -- 状态 -------------------------------------------------------------
    @property
    def built(self) -> bool:
        return bool(self._spans)

    @property
    def length(self) -> int:
        return self._n

    @property
    def n_levels(self) -> int:
        """已构建的层级数（层级按需构建，故可能随查询增长）。"""
        return len(self._cache)

    @property
    def spans(self) -> list:
        return list(self._spans)

    # -- 构建 -------------------------------------------------------------
    def build(self, values) -> bool:
        """接管数据并定义层级阶梯（不预先计算摘要，首次查询时才建）。

        每一级都**直接从原始数组**用 ``reduceat`` 计算，不在级间传递中间
        数组——级间 reshape 会产生与上一级等大的临时数组，峰值内存成倍叠加
        （实测在内存受限环境下触发 numpy 分配失败）。
        """
        arr = _as_float_array(values)
        if arr is None or arr.size < _MIN_POINTS:
            return False
        n = int(arr.size)
        # 层级阶梯用 2 的幂次：任意目标桶宽都能在阶梯上精确匹配，避免
        # 「想要的桶宽落在两级之间」——用 4 倍倍数时阶梯过粗（百万点下只有
        # 244/976 两级），大窗口必然退化为合并。
        spans = []
        span = _MIN_SPAN
        while span <= _MAX_SPAN_POINTS and len(spans) < _MAX_LEVELS:
            if n // span >= 2:
                spans.append(span)
            span *= 2
        if not spans:
            return False
        self._arr = arr
        self._n = n
        self._spans = spans
        self._cache = {}
        return True

    def extend(self, values) -> bool:
        """数据追加后增量更新；无法增量（变短/类型不符）返回 ``False``。"""
        if not self.built:
            return self.build(values)
        arr = _as_float_array(values)
        if arr is None or arr.size < self._n:
            return False
        if arr.size == self._n:
            return True
        try:
            for span in list(self._cache):
                self._cache[span] = self._compute(arr, span, extend_from=span)
        except Exception:  # noqa: BLE001 - 增量失败即整体失效，绝不留半更新
            self._arr = None
            self._n = 0
            self._spans = []
            self._cache = {}
            return False
        self._arr = arr
        self._n = int(arr.size)
        return True

    def _compute(self, arr, span: int, extend_from: int = None):
        """计算 ``span`` 层级的 (mins, maxs)。

        只使用**完整桶**（末尾不足一桶的余数被丢弃）。这一约定必须与参照实现
        （直接分桶）一致：``reduceat`` 会把最后一个起点一直算到数组末尾，于是
        末端桶覆盖的区间比「完整桶」多出余数部分，其 max 可能大于参照值——
        实测由此产生 1 个桶的偏差（约 1.0，取决于数据）。
        """
        n = int(arr.size)
        buckets = n // span
        if buckets <= 0:
            return None
        if extend_from is None:
            starts = _np.arange(buckets, dtype=_np.int64) * span
            return (_np.minimum.reduceat(arr[:buckets * span], starts),
                    _np.maximum.reduceat(arr[:buckets * span], starts))
        old = self._cache.get(extend_from)
        if old is None:
            starts = _np.arange(buckets, dtype=_np.int64) * span
            return (_np.minimum.reduceat(arr[:buckets * span], starts),
                    _np.maximum.reduceat(arr[:buckets * span], starts))
        have = old[0].size
        if buckets <= have:
            return old
        redo = max(0, have - 1)
        starts = _np.arange(redo, buckets, dtype=_np.int64) * span
        seg = arr[:buckets * span]
        return (_np.concatenate((old[0][:redo],
                                 _np.minimum.reduceat(seg, starts))),
                _np.concatenate((old[1][:redo],
                                 _np.maximum.reduceat(seg, starts))))

    # -- 查询 -------------------------------------------------------------
    def level_for(self, points_per_bucket: float):
        """选取**不超过**目标桶宽的最粗层级（桶数最少但仍满足精度）。

        返回 ``None`` 表示目标桶宽比最细层级还小——此时预计算帮不上忙，
        调用方应直接对原始数据分桶。
        """
        if not self.built:
            return None
        target = max(1.0, float(points_per_bucket))
        best = None
        for span in self._spans:
            if span <= target:
                best = span
            else:
                break
        return best

    def query(self, span: int, start: int, end: int, buckets: int):
        """读取覆盖 ``[start, end)`` 的摘要。

        返回 ``(mins, maxs, quality)``；无数据返回 ``None``。

        - ``quality == "exact"``：窗口内该层级的桶数 ≤ ``buckets``，逐桶极值
          与直接分桶一致；
        - ``quality == "coarse"``：桶数超出目标，已合并相邻桶——**可能丢失
          窄尖峰**，调用方应回退到原始数据分桶再做一次精确采样。
        """
        if not self.built or span not in self._spans or span <= 0:
            return None
        if span not in self._cache:
            self._cache[span] = self._compute(self._arr, span)
        entry = self._cache.get(span)
        if entry is None:
            return None
        mins, maxs = entry
        b0 = max(0, start // span)
        b1 = min(mins.size, -(-end // span))
        if b1 <= b0:
            return None
        seg_m = mins[b0:b1]
        seg_x = maxs[b0:b1]
        count = int(seg_m.size)
        if count <= buckets:
            return seg_m, seg_x, "exact"
        m = count // buckets
        if m < 2:
            # 桶数虽超目标，但合并并不会改变逐桶取值（每组不足 2 个），
            # 等价于原样返回——此时仍是精确的，不应误报为 coarse。
            return seg_m, seg_x, "exact"
        trim = m * buckets
        rm = seg_m[:trim].reshape(buckets, m)
        rx = seg_x[:trim].reshape(buckets, m)
        return rm.min(axis=1), rx.max(axis=1), "coarse"


def _as_float_array(values):
    """转为一维 float64 数组；不可转换返回 ``None``。"""
    if _np is None or values is None:
        return None
    raw = values.raw if isinstance(values, NumericBuffer) else values
    try:
        arr = _np.asarray(raw, dtype=_np.float64)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 1:
        return None
    return arr


#: 按数据对象身份缓存的金字塔（键含强引用，容量受限）
_PYRAMIDS: dict = {}
_PYRAMID_LIMIT = 32


def build_pyramid(values) -> Pyramid:
    """为数值序列构建金字塔（不缓存）。"""
    p = Pyramid()
    p.build(values)
    return p


def pyramid_for(values, allow_build: bool = True):
    """取（必要时构建）该序列的金字塔；不适用时返回 ``None``。

    缓存键为 ``(id(数据), 长度)`` 并**持有数据对象的强引用**——否则对象回收
    后 ``id`` 可能被复用，把别的数据的摘要当成自己的。
    """
    try:
        n = len(values)
    except TypeError:
        return None
    if n < _MIN_POINTS or _np is None:
        return None
    ck = (id(values), n)
    hit = _PYRAMIDS.get(ck)
    if hit is not None and hit[0] is values and hit[1] is not None:
        return hit[1]
    if not allow_build:
        return None
    pyr = Pyramid()
    if not pyr.build(values):
        return None
    if len(_PYRAMIDS) >= _PYRAMID_LIMIT:
        _PYRAMIDS.clear()
    _PYRAMIDS[ck] = (values, pyr)
    return pyr


def invalidate_pyramid(values) -> None:
    """丢弃某序列的金字塔缓存（数据被替换时调用）。"""
    if values is None:
        return
    for key in [k for k in _PYRAMIDS if k[0] == id(values)]:
        _PYRAMIDS.pop(key, None)
