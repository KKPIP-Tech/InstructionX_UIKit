# -*- coding: utf-8 -*-
"""折线动画与静态绘制回归（直接运行，不使用 pytest）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


def check(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
    return decorate


def make_chart():
    chart = ChartWidget()
    chart.resize(480, 320)
    chart.set_option({
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": [1, 2, None, 4]}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart._layout_all(force=True)
    return chart


@check("动画停止时复用当前点列")
def _():
    chart = make_chart()
    renderer = chart.series_renderers[0]
    current = renderer._points
    renderer.prev_data = [1, 3, None, 5]
    assert renderer._animated_points(0.5) is current
    chart.close()


@check("动画完成时不再读取旧数据")
def _():
    chart = make_chart()
    renderer = chart.series_renderers[0]

    class InvalidPrevious:
        def __len__(self):
            raise AssertionError("完成态不应读取旧数据")

    renderer.prev_data = InvalidPrevious()
    assert renderer._animated_points(1.0) is renderer._points
    chart.close()


@check("真实等长更新仍插值并保留 None 断点")
def _():
    chart = make_chart()
    renderer = chart.series_renderers[0]
    renderer.prev_data = [1, 3, None, 5]
    chart.anim.start()
    result = renderer._animated_points(0.5)
    assert result is not renderer._points
    coord = chart.coord_for(renderer.opt)
    first = coord.map_point(1, 3)
    second = coord.map_point(1, 2)
    assert abs(result[1].x() - (first.x() + second.x()) / 2) < 1e-9
    assert abs(result[1].y() - (first.y() + second.y()) / 2) < 1e-9
    assert result[2] is None
    chart.anim.stop()
    chart.resize(520, 340)
    assert renderer._animated_points(1.0) is renderer._points
    chart.close()


@check("旧数据长度不一致时不构造插值点列")
def _():
    chart = make_chart()
    renderer = chart.series_renderers[0]
    renderer.prev_data = [1]
    chart.anim.start()
    assert renderer._animated_points(0.5) is renderer._points
    chart.anim.stop()
    chart.close()


@check("稳定完成态像素基线")
def _():
    chart = make_chart()
    chart.show()
    QTest.qWait(160)
    app.processEvents()
    image = chart.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    dpr = chart.devicePixelRatioF()
    reference = QImage(round(chart.width() * dpr), round(chart.height() * dpr),
                       QImage.Format_RGBA8888)
    reference.setDevicePixelRatio(dpr)
    reference.fill(0)
    painter = QPainter(reference)
    chart._paint_contents(painter)
    painter.end()
    assert image == reference, "完成态图像与同 DPR 的 QPainter 参考不一致"
    path = ROOT / "tests" / "shots" / "perf" / "line_stable_before.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        baseline = QImage(str(path))
        if baseline.devicePixelRatioF() == dpr:
            assert image == baseline.convertToFormat(QImage.Format_RGBA8888), (
                "完成态图像与优化前不一致")
    else:
        assert image.save(str(path)), "无法保存优化前像素基线"
    chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
