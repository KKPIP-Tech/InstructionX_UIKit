# -*- coding: utf-8 -*-
"""图表大数组的紧凑存储与零拷贝摄入口径（CHART_SPEC §8 大规模数据管线）。

用途：把调用方传入的**大数值数组**按引用持有为紧凑缓冲区，避免
``set_option`` 的 ``copy.deepcopy`` 与 ``update_option`` 的 ``_deep_merge``
对百万级数组逐元素复制——实测 150 万点单次 deepcopy 约 63~95 ms，
每次数据更新都付这个成本时，无论渲染多快都不可能达到实时帧率。

对外可见语义（必须与历史完全一致）：

- ``NumericBuffer`` 是 ``collections.abc.Sequence``，``len()`` / 下标 /
  切片 / ``iter()`` 行为与 ``list`` 一致；``==`` 支持与普通 list 比较
  （绘图与测试都依赖数据可比较）。
- 元素一律为原生 Python ``float``（来自 ``ndarray.tolist()`` 或缓冲区的
  下标取值），不使用 ``numpy`` 标量——后者与 ``int`` 的 ``==`` 虽然成立，
  但 ``repr`` 与类型断言会露出差异，历史测试也直接比较数据列表。
- ``option()`` / ``SeriesRenderer.data()`` 对外仍返回 **list**，调用方
  观察不到缓冲区的存在。

摄入口径（``to_buffer``）：

- ``ndarray`` / 缓冲协议对象：按引用持有（真正零拷贝）；
- 普通序列：转 ``numpy.float64`` 连续数组（O(n) 一次性，且仅在元素数量
  达到 ``_BUFFER_MIN_LEN`` 时才包装）。

依赖说明：numpy 为本项目已批准的依赖（见 AGENTS.md 依赖清单）。为保持对
无 numpy 环境的健壮性，导入失败时降级为 ``array('d')`` 承载，语义一致。
"""

from collections.abc import Sequence

__all__ = [
    "numpy_available",
    "NumericBuffer",
    "to_buffer",
    "is_array_like",
    "unwrap_data",
    "normalize_option_data",
]

try:  # pragma: no cover - 环境相关分支
    import numpy as _np
except Exception:  # noqa: BLE001 - 降级路径，任何导入失败都退回 array
    _np = None

from array import array as _array

#: 小于该长度的数据不做缓冲包装（小数组直接深拷贝更省事，也避免为
#: 演示页的十来点数据平白增加包装对象）。
_BUFFER_MIN_LEN = 256


def numpy_available() -> bool:
    """当前环境是否可用 numpy（向量化降采样与映射的加速前提）。"""
    return _np is not None


class NumericBuffer(Sequence):
    """大数值数组的紧凑容器（numpy ndarray 或 ``array('d')`` 承载）。

    只读语义：不提供原地修改接口，避免调用方与图表共享可变状态时出现
    难以排查的错位。切片返回 ``list``（与 list 切片语义一致），大范围
    切片请直接用 ``to_list()``。
    """

    __slots__ = ("_buf",)

    def __init__(self, buf) -> None:
        self._buf = buf

    # -- Sequence 协议 ---------------------------------------------------
    def __len__(self) -> int:
        return int(len(self._buf))

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.to_list()[index]
        v = self._buf[index]
        return float(v)

    def __iter__(self):
        if _np is not None and isinstance(self._buf, _np.ndarray):
            # tolist() 在 C 层完成 float64 -> Python float 转换，比逐个
            # 下标取值快一个数量级；大数组的迭代是热路径。
            return iter(self._buf.tolist())
        return (float(v) for v in self._buf)

    def __repr__(self) -> str:
        return f"NumericBuffer(len={len(self)})"

    # -- 与 list 的可比较性（绘图与历史测试都直接比较数据） --------------
    def __eq__(self, other) -> bool:
        if isinstance(other, NumericBuffer):
            other = other.to_list()
        if isinstance(other, (list, tuple)):
            if len(other) != len(self):
                return False
            return self.to_list() == list(other)
        return NotImplemented

    def __ne__(self, other) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    __hash__ = None  # 可比较但不可哈希（与 list 一致）

    # -- 显式转换 --------------------------------------------------------
    def to_list(self) -> list:
        """转为原生 Python float 列表（对外 API 与旧代码的兼容出口）。"""
        if _np is not None and isinstance(self._buf, _np.ndarray):
            return self._buf.tolist()
        return [float(v) for v in self._buf]

    #: 供 numpy 向量化路径直接取底层数组（只读使用，不得写入）
    @property
    def raw(self):
        return self._buf


def _is_array_like(obj) -> bool:
    """是否已是可零拷贝持有的数组（numpy 数组或实现了缓冲协议）。"""
    if _np is not None and isinstance(obj, _np.ndarray):
        return True
    if isinstance(obj, _array):
        return True
    return hasattr(obj, "__array_interface__")


def is_array_like(obj) -> bool:
    """是否已是可零拷贝持有的数组（numpy 数组或实现了缓冲协议）。

    供上游判断「这个值能否直接当数值序列用」——``_deep_merge`` 曾只认
    ``list``/``tuple``，于是 numpy 数组既不匹配 list 分支、也不是
    ``NumericBuffer``，落到兜底的 ``dst[k] = v`` 之后被当作「数据缺失」，
    表现为**流式入图后曲线一个点都不画**。
    """
    return _is_array_like(obj)


def to_buffer(data, min_len: int = _BUFFER_MIN_LEN):
    """把数值序列转为 ``NumericBuffer``；不值得包装时返回 ``None``。

    返回 ``None`` 表示调用方应继续走原有的深拷贝路径（小数组、非数值序列、
    字典项列表等）。判断只看**长度与数值性**，不猜测语义。

    仅当序列中每个元素都是 ``int`` / ``float``（且非 ``bool``）或 ``None``
    时才包装——含 dict（如 pie 的 ``{"name","value"}``）或含嵌套列表（如
    candlestick 的 ``[o,c,l,h]``）的数据保持原样，交由既有渲染路径处理。
    """
    if data is None or isinstance(data, NumericBuffer):
        return None
    if _is_array_like(data):
        try:
            n = len(data)
        except TypeError:
            return None
        if n >= min_len:
            return NumericBuffer(data)
        return None
    if not isinstance(data, (list, tuple)):
        return None
    n = len(data)
    if n < min_len:
        return None
    # 抽样判别元素类型：只抽样即可，全量扫描会白白增加 O(n) Python 开销
    step = max(1, n // 64)
    for i in range(0, n, step):
        v = data[i]
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
    try:
        if _np is not None:
            buf = _np.asarray(data, dtype=_np.float64)
        else:
            buf = _array("d", [float(v) if v is not None else float("nan")
                               for v in data])
    except (TypeError, ValueError):
        return None
    return NumericBuffer(buf)


def unwrap_data(value):
    """把缓冲区还原为 list；非缓冲区原样返回（供 ``option()`` 输出用）。"""
    if isinstance(value, NumericBuffer):
        return value.to_list()
    return value


def normalize_option_data(option: dict, min_len: int = _BUFFER_MIN_LEN) -> dict:
    """就地包装 option 中的大数值数组为缓冲区，返回同一 dict。

    处理位置：``series`` 列表中每一项的 ``data``。
    其余顶层键（``xAxis`` 等）的数据直接由各模块从 ``opt.get("data")``
    读取为 list，包装会破坏其语义，故**不处理**。
    """
    if not isinstance(option, dict):
        return option
    series = option.get("series")
    if not isinstance(series, list):
        return option
    for s in series:
        if not isinstance(s, dict):
            continue
        buf = to_buffer(s.get("data"), min_len)
        if buf is not None:
            s["data"] = buf
    return option
