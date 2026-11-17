# -*- coding: utf-8 -*-
"""UI 热路径的私有固定容量性能指标。"""

from collections import deque

__all__ = ["MetricRing"]


class MetricRing:
    """在固定内存上界内记录耗时样本与累计计数。"""

    def __init__(self, capacity=240):
        self._capacity = max(1, int(capacity))
        self._samples = {}
        self._counters = {}

    def add(self, name, seconds):
        values = self._samples.get(name)
        if values is None:
            values = self._samples[name] = deque(maxlen=self._capacity)
        values.append(float(seconds))

    def count(self, name, amount=1):
        self._counters[name] = self._counters.get(name, 0) + int(amount)

    def snapshot(self):
        result = dict(self._counters)
        for name, values in self._samples.items():
            ordered = sorted(values)
            result[name] = {
                "count": len(values),
                "mean": sum(values) / len(values) if values else 0.0,
                "p95": ordered[min(len(ordered) - 1,
                                   int(len(ordered) * 0.95))] if ordered else 0.0,
            }
        return result
