# -*- coding: utf-8 -*-
"""以相同 12 组用例验证 QCanvasPainterItem 的折线完整形态。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))

from InstructionX_UIKit.charts.canvas_item_viewport import CanvasItemLineChartViewport
import run_canvas_line_features


class ItemLineAdapter(CanvasItemLineChartViewport):
    def __init__(self, renderer, _coord=None):
        super().__init__(renderer.chart)
        self._canvas = None

    def _model(self):
        return self._line_views[0]

    @property
    def _paths(self):
        return self._model()._paths

    @property
    def _points(self):
        return self._model()._points

    @property
    def _areas(self):
        return self._model()._areas

    @property
    def _dashes(self):
        return self._model()._dashes

    @property
    def _color(self):
        return self._model()._color

    @property
    def _last_symbol_count(self):
        return self.symbol_count(0)

    def set_paths(self, points):
        self._model().set_paths(points)
        self._item.set_views(self._line_views)
        self.update()


run_canvas_line_features.CanvasLineViewport = ItemLineAdapter

if __name__ == "__main__":
    raise SystemExit(run_canvas_line_features.main())
