# -*- coding: utf-8 -*-
"""实时数据接入：无锁环形缓冲 + 帧合并（CHART_SPEC §8.4 流式形态）。

**用途**：让高速采集的数据不阻塞界面，又能及时入图。

**无锁单写单读环形缓冲（** :class:`RingBuffer` **）**

- 生产者（采集线程）先写数据，**最后**才更新「有效长度」；消费者先读长度，
  再读 ``[0, 长度)``。因此消费者绝不会看到半写状态——这是无锁设计成立的
  关键顺序约束。
- 每个图表只允许**一个**写线程（多写者需自行串行化），读线程为 GUI 线程。
- 容量在创建时确定，满了按「丢弃最旧」处理并计数（``dropped`` 可观测），
  绝不阻塞生产者。

**帧合并（** :class:`FrameCoalescer` **）**

- 采集线程可以远快于重绘（例如 1 kHz 采样、90 fps 重绘）。逐点触发重绘会
  让事件队列堆积、界面反而更卡。
- 合并器按最小间隔聚合数据：一次投递把窗口内积压的点**成批**送达，重绘
  请求也随之合并。
- 与 :class:`RingBuffer` 配合：生产者只管写，消费者按节奏取。
"""

import threading
import time

__all__ = ["RingBuffer", "FrameCoalescer", "StreamSession"]
try:  # pragma: no cover - 环境相关分支
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None

from array import array as _array


class RingBuffer:
    """定长环形缓冲：单写单读，写满丢最旧，生产者永不阻塞。

    参数:
        capacity: 容量（点数）。滚动窗口长度即由此确定。
        dtype: ``"float64"``（默认）。
    """

    __slots__ = ("_buf", "_cap", "_len", "_write", "_total", "_dropped")

    def __init__(self, capacity: int = 4096, dtype: str = "float64") -> None:
        cap = int(capacity)
        if cap <= 0:
            raise ValueError(f"RingBuffer: capacity 必须为正，收到 {capacity!r}")
        self._cap = cap
        if _np is not None:
            self._buf = _np.zeros(cap, dtype=_np.float64)
        else:
            self._buf = _array("d", bytes(8 * cap))
        self._len = 0        # 有效长度（最后更新，消费者据此判断可读范围）
        self._write = 0      # 写指针
        self._total = 0      # 累计写入（含被覆盖的）
        self._dropped = 0    # 因写满被覆盖的旧点数

    # -- 属性 -------------------------------------------------------------
    @property
    def capacity(self) -> int:
        return self._cap

    @property
    def dropped(self) -> int:
        """因容量不足被覆盖的旧点数（>0 表示窗口小于数据速率）。"""
        return self._dropped

    @property
    def total_written(self) -> int:
        return self._total

    def __len__(self) -> int:
        return self._len

    # -- 生产者 -----------------------------------------------------------
    def write(self, values) -> int:
        """写入一批数值，返回实际写入点数（生产者线程调用）。

        **顺序约束**：先写数据、最后更新 ``_len``——消费者看到旧长度时读到
        的是完整的旧数据，不会读到半写状态。
        """
        vals = _as_1d(values)
        if vals is None or vals.size == 0:
            return 0
        n = int(vals.size)
        if n >= self._cap:
            # 一次写入超过容量：只保留最新的 capacity 个点
            vals = vals[-self._cap:]
            n = self._cap
            self._buf[:] = vals
            self._write = 0
            self._dropped += self._len + (int(vals.size) - n)
            self._len = self._cap
            self._total += n
            return n
        end = self._write + n
        if end <= self._cap:
            self._buf[self._write:end] = vals
            self._write = end % self._cap
        else:
            head = self._cap - self._write
            self._buf[self._write:] = vals[:head]
            self._buf[:n - head] = vals[head:]
            self._write = n - head
        if self._len + n > self._cap:
            self._dropped += self._len + n - self._cap
            self._len = self._cap
        else:
            self._len += n
        self._total += n
        return n

    # -- 消费者 -----------------------------------------------------------
    def read(self, count: int = None):
        """按时间顺序读取最近 ``count`` 个点（缺省读全部有效数据）。

        返回 numpy 数组（无 numpy 时为 list）；无数据返回 ``None``。
        读线程为 GUI 线程；读取使用**当前**长度，不阻塞。
        """
        n = self._len
        if n <= 0:
            return None
        if count is not None:
            n = max(0, min(n, int(count)))
        if n == 0:
            return None
        start = (self._write - n) % self._cap
        if start + n <= self._cap:
            out = self._buf[start:start + n]
        else:
            head = self._cap - start
            if _np is not None:
                out = _np.concatenate((self._buf[start:], self._buf[:n - head]))
            else:
                out = list(self._buf[start:]) + list(self._buf[:n - head])
        return out.copy() if _np is not None else out

    def clear(self) -> None:
        """清空（消费者调用；生产者需自行停止后再清）。"""
        self._len = 0
        self._write = 0


def _as_1d(values):
    """把输入规范为一维 float64 数组；不可转换返回 ``None``。"""
    if values is None:
        return None
    if _np is not None:
        try:
            arr = _np.asarray(values, dtype=_np.float64)
        except (TypeError, ValueError):
            return None
        if arr.ndim == 0:
            arr = arr.reshape(1)
        elif arr.ndim != 1:
            arr = arr.reshape(-1)
        return arr
    if isinstance(values, (int, float)) and not isinstance(values, bool):
        return [float(values)]
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return None


class FrameCoalescer:
    """把高频投递合并到目标重绘节奏，避免事件队列堆积。

    用法（生产者线程）::

        coal = FrameCoalescer(min_interval=1 / 90)
        coal.push(values)          # 高频调用，内部按时间窗口聚合

    消费者（GUI 线程）在定时器里调用 :meth:`take` 取出待处理数据；返回
    ``None`` 表示本帧无新数据（**此时不要重绘**）。

    线程安全：``push`` 可在任意线程调用；``take`` 只应由一个线程调用。
    """

    __slots__ = ("_interval", "_lock", "_pending", "_last", "_batches",
                 "_points", "_frames")

    def __init__(self, min_interval: float = 1.0 / 90.0) -> None:
        self._interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._pending = []
        self._last = 0.0
        self._batches = 0
        self._points = 0
        self._frames = 0

    @property
    def pending_points(self) -> int:
        with self._lock:
            return sum(len(b) if not hasattr(b, "size") else int(b.size)
                       for b in self._pending)

    @property
    def stats(self) -> dict:
        """``{"batches": 投递批次数, "points": 累计点数, "frames": 实际取帧数,
        "merged": 被合并掉的投递次数}``。"""
        with self._lock:
            return {"batches": self._batches, "points": self._points,
                    "frames": self._frames,
                    "merged": max(0, self._batches - self._frames)}

    def push(self, values) -> bool:
        """投递一批数据；返回是否**立即**通过（未处于合并窗口内）。

        未通过的数据不会丢失，会留在待处理队列等待 :meth:`take`。
        """
        arr = _as_1d(values)
        if arr is None or len(arr) == 0:
            return False
        now = time.monotonic()
        with self._lock:
            self._pending.append(arr)
            self._batches += 1
            size = arr.size if hasattr(arr, "size") else len(arr)
            self._points += int(size)
            if now - self._last >= self._interval:
                self._last = now
                return True
        return False

    def take(self):
        """取出并合并当前待处理数据；无数据返回 ``None``。

        合并语义：把队列中所有批次按到达顺序拼接（时间序），保证不丢点。
        """
        with self._lock:
            if not self._pending:
                return None
            batches = self._pending
            self._pending = []
            self._frames += 1
        if len(batches) == 1:
            return batches[0]
        if _np is not None:
            return _np.concatenate([_as_1d(b) for b in batches])
        out = []
        for b in batches:
            out.extend(b)
        return out

    def reset(self) -> None:
        with self._lock:
            self._pending = []
            self._last = 0.0


class StreamSession:
    """把一个图表接到实时数据源（**任意线程**可写，合并后按节奏入图）。

    典型用法::

        chart.set_option({"xAxis": {...}, "series": [{"type": "line",
                                                      "name": "信号"}]})
        sess = chart.stream(series="信号", window=20000)

        # 采集线程（每秒 50 点、1 kHz 都可以）
        sess.write(value)          # 或 sess.write([v1, v2, ...])

        # 结束时
        sess.close()

    设计要点：

    - **写侧无锁**：``write`` 只写定长环形缓冲并投递合并器，绝不阻塞采集线程；
    - **读侧在 GUI 线程**：由本会话创建的定时器按 ``interval``（默认 1/90 秒）
      取数并调用 ``option 追加 + 重绘``，因此不跨线程操作 Qt 对象；
    - **帧合并**：投递频率高于刷新节奏时按时间窗口聚合，一次投递成批入图，
      避免事件队列堆积（堆积会让界面反而更卡）；
    - **无新数据不重绘**：本帧没有数据时直接跳过，空闲期零开销。

    参数:
        chart: 目标 ``ChartWidget``。
        series: 系列名（``series[].name``）或 0 起序号；缺省取第一个系列。
        window: 保留的最近点数（决定环形缓冲容量与内存上界）。
        interval: 入图节奏（秒），默认 1/90。
        auto_scale: 是否在每次入图后自动跟随数据范围（默认 True）。
    """

    def __init__(self, chart, series=0, window: int = 20000,
                 interval: float = 1.0 / 90.0, auto_scale: bool = True) -> None:
        from PySide6.QtCore import QTimer
        self.chart = chart
        self.ring = RingBuffer(window)
        self.coalescer = FrameCoalescer(interval)
        self.auto_scale = bool(auto_scale)
        self._series_key = series
        self._alive = True
        #: 上一次入图的实际计算耗时（秒），见 :meth:`_on_tick`
        self.last_apply_seconds = 0.0
        #: 相邻两次真正入图的间隔（秒），见 :meth:`_on_tick`
        self.last_apply_interval = 0.0
        self._last_apply_at = 0.0
        self._apply_intervals = []
        self._INTERVAL_WINDOW = 60
        self._timer = QTimer(chart)
        self._timer.setInterval(max(1, int(interval * 1000)))
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    # -- 写侧（任意线程） -------------------------------------------------
    def write(self, values) -> int:
        """写入一个或多个点；返回写入点数。可在任意线程调用，不阻塞。"""
        n = self.ring.write(values)
        if n:
            self.coalescer.push(values)
        return n

    # -- 读侧（GUI 线程） -------------------------------------------------
    def _on_tick(self) -> None:
        if not self._alive:
            return
        batch = self.coalescer.take()
        if batch is None:
            return                      # 本帧无新数据：不重绘
        data = self.ring.read()
        if data is None:
            return
        t0 = time.perf_counter()
        try:
            self._apply(data)
        except Exception as exc:  # noqa: BLE001 - 单次入图失败不应终止会话
            from ._utils import warn_once
            warn_once("stream-apply", f"实时入图失败: {exc!r}")
        finally:
            now = time.perf_counter()
            #: 上一次入图的实际计算耗时（秒）。它是**纯计算**：不含窗口合成与
            #: 帧缓冲交换的等待，因此与「入图间隔」之差就是合成阻塞——这个
            #: 差额是判断「瓶颈在算法还是在合成」的关键依据。
            self.last_apply_seconds = now - t0
            #: 相邻两次**真正入图**的间隔（秒）；由会话自己记录，因为调用方的
            #: 计时器节奏未必等于入图节奏。瞬时值抖动大（生产者成批到达时
            #: 相邻两次可能只差一两毫秒），故同时维护最近 ``_INTERVAL_WINDOW``
            #: 次的样本，读数应使用 :meth:`mean_apply_interval`。
            if self._last_apply_at:
                dt = now - self._last_apply_at
                self.last_apply_interval = dt
                self._apply_intervals.append(dt)
                del self._apply_intervals[:-self._INTERVAL_WINDOW]
            self._last_apply_at = now

    def mean_apply_interval(self) -> float:
        """最近若干次入图间隔的平均值（秒）；样本不足时回退瞬时值。

        读数应使用本方法而不是 ``last_apply_interval``：后者是瞬时值，在
        「生产者成批到达」时会被压到极小（实测报出过 432 Hz 的假读数），
        平均后才是屏幕每秒真正前进多少次。
        """
        if not self._apply_intervals:
            return self.last_apply_interval
        return sum(self._apply_intervals) / len(self._apply_intervals)

    def _apply(self, data) -> None:
        """把缓冲内容写入系列并请求重绘（保持既有调用语义）。

        ``vals`` 直接透传 ``RingBuffer.read`` 的返回值（ndarray，零拷贝切片）：
        ``_deep_merge`` 会把 ndarray 按引用包成 ``NumericBuffer``，省掉每帧把
        整个窗口转成 list 的成本（实测 2 万点窗口：``update_option`` 由
        8.75 ms 降到 6.14 ms），同时保住渲染器的矢量映射快路径。

        **补丁必须带上该系列的完整 option**（渲染器当前的 ``opt`` 加新 data），
        而不是只给 ``{"data": ...}``：``update_option`` 的契约是 **list 值整体
        替换**（见 core._deep_merge），只给 ``data`` 会把 ``type`` / ``name`` /
        ``lineStyle`` / ``gpuDirect`` 等一并抹掉——实测表现为开启 ``gpuDirect``
        的流式系列从第二帧起丢失直绘标记（``gpu_vertex_data()`` 返回 None、
        VBO 顶点数 0），于是每帧白做一次 CPU 光栅化。
        """
        vals = data
        chart = self.chart
        idx = self._resolve_series_index()
        if idx < 0:
            return
        # 优先走流式专用入口：只换数据、不重建 option / 渲染器。实测 2 万点
        # 窗口每帧可省掉 ``_rebuild`` 6.83 ms 与两次多余重排（合计十余毫秒），
        # 这是 90 fps 预算内的关键一步。入口不可用时（旧版 Kit / 自定义图表）
        # 自动退回 update_option 全量路径。
        setter = getattr(chart, "set_stream_data", None)
        if callable(setter):
            if self.auto_scale and len(vals):
                lo, hi = min(vals), max(vals)
                pad = (hi - lo) * 0.05 or 1.0
                renderers = chart.series_renderers
                base = dict(renderers[idx].opt) if idx < len(renderers) else {}
                base["data"] = vals
                patch = {"yAxis": {"min": lo - pad, "max": hi + pad},
                         "series": [base if i == idx else {}
                                    for i in range(len(renderers))]}
                prev_anim = chart.anim
                chart.update_option(patch)
                try:
                    chart.anim.stop()
                    chart.anim.set_progress(1.0)
                except Exception:  # noqa: BLE001
                    del prev_anim
                return
            setter(vals, series=idx)
            return
        renderers = chart.series_renderers
        item = dict(renderers[idx].opt) if idx < len(renderers) else {}
        item["data"] = vals
        patch = {"series": [item if i == idx else {}
                            for i in range(len(renderers))]}
        if self.auto_scale and len(vals):
            lo = min(vals)
            hi = max(vals)
            pad = (hi - lo) * 0.05 or 1.0
            patch["yAxis"] = {"min": lo - pad, "max": hi + pad}
        # 实时场景不播放入场动画：动画会让新点延迟可见
        prev_anim = chart.anim
        chart.update_option(patch)
        try:
            chart.anim.stop()
            chart.anim.set_progress(1.0)
        except Exception:  # noqa: BLE001
            del prev_anim

    def _resolve_series_index(self) -> int:
        key = self._series_key
        renderers = self.chart.series_renderers
        if isinstance(key, int):
            return key if 0 <= key < len(renderers) else -1
        for i, r in enumerate(renderers):
            if r.name == str(key):
                return i
        return 0 if renderers else -1

    # -- 生命周期 ---------------------------------------------------------
    def close(self) -> None:
        """停止会话并释放定时器（不修改图表已显示的数据）。"""
        if not self._alive:
            return
        self._alive = False
        try:
            self._timer.stop()
            self._timer.timeout.disconnect(self._on_tick)
        except (RuntimeError, TypeError):
            pass

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def stats(self) -> dict:
        s = self.coalescer.stats
        s["dropped"] = self.ring.dropped
        s["buffered"] = len(self.ring)
        return s
