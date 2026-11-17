# -*- coding: utf-8 -*-
"""ChartWidget 父子视口重复绘制与最终像素回归。"""

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("UIKIT_REAL"):
    os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "InstructionX_UIKit").is_dir():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QProgressBar, QVBoxLayout, QWidget

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-baseline", action="store_true")
    args = parser.parse_args()
    suffix = "real" if os.environ.get("UIKIT_REAL") else "offscreen"
    host = QWidget()
    layout = QVBoxLayout(host)
    chart = ChartWidget()
    values = np.sin(np.arange(4000) * 0.01)
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": values, "showSymbol": False}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    progress = QProgressBar()
    progress.setRange(0, 100)
    layout.addWidget(chart, 1)
    layout.addWidget(progress)
    host.resize(800, 500)
    host.show()
    pump(180)
    images = {
        "chart": chart.grab().toImage().convertToFormat(QImage.Format_RGBA8888),
        "host": host.grab().toImage().convertToFormat(QImage.Format_RGBA8888),
    }
    for name, image in images.items():
        baseline = ROOT / "temp" / f"{name}_parent_baseline_{suffix}.png"
        if args.capture_baseline:
            if not image.save(str(baseline)):
                raise AssertionError("无法保存父控件绘制基线")
            continue
        expected = QImage(str(baseline)).convertToFormat(QImage.Format_RGBA8888)
        actual_bytes = bytes(image.constBits())
        expected_bytes = bytes(expected.constBits())
        if expected.size() != image.size() or expected_bytes != actual_bytes:
            image.save(str(ROOT / "temp" / f"{name}_parent_after_{suffix}.png"))
        assert expected.size() == image.size() and expected_bytes == actual_bytes, f"{name} 最终图像存在差异"
    calls = []
    original = chart._paint_contents

    def counted(painter):
        calls.append(1)
        return original(painter)

    chart._paint_contents = counted
    chart.paintEvent(None)
    assert not calls, "父控件普通 UpdateRequest 不应重复完整绘制"
    progress.setValue(42)
    host.repaint()
    pump(100)
    assert len(calls) <= 1, f"一次普通更新触发 {len(calls)} 次完整内容绘制"
    host.close()
    host.deleteLater()
    app.processEvents()
    print("  [通过] 普通更新不重复绘制且最终像素一致")


if __name__ == "__main__":
    raise SystemExit(main())
