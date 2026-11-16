# -*- coding: utf-8 -*-
"""图表演示页回归：现行 RHI 语义、UIKit 控件与巨量数据交互（离屏）。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from InstructionX_UIKit.components import Button  # noqa: E402
from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.pages.charts import MassiveDataDemo, create_page  # noqa: E402
from demo.pages.playground import PlaygroundPanel  # noqa: E402


def main():
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    page = create_page()
    page.resize(1440, 900)
    app.processEvents()
    demo = page.findChild(MassiveDataDemo)
    assert demo is not None
    assert "gpuDirect" not in demo.form.controls, "失效 GL 开关不得重新出现"

    buttons = [w for w in page.findChildren(QPushButton) if type(w) is QPushButton]
    assert not buttons, f"仍有 {len(buttons)} 个独立原生 QPushButton"
    panels = page.findChildren(PlaygroundPanel)
    assert len(panels) >= 2
    assert all(isinstance(panel.reset_button, Button) for panel in panels)
    assert not any("OpenGL" in label.text() for label in page.findChildren(QLabel))

    demo._refresh_benchmark()
    assert "平台后端" in demo.readout.text()
    assert "GL 后端" not in demo.readout.text()

    demo.form.controls["live"].setChecked(True)
    QTest.qWait(800)
    assert demo._sess is not None and demo._sess.ring.total_written > 0
    demo.panel.reset_button.click()
    app.processEvents()
    assert demo._sess is None and not demo.form.controls["live"].isChecked()

    demo.stop()
    page.close()
    app.processEvents()
    print("[通过] 图表页无失效 GL 残留，UIKit 按钮与巨量数据交互正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
