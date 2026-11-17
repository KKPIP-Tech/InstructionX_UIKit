# -*- coding: utf-8 -*-
"""真实窗口回归：巨量数据实时流与离线后台生成的状态隔离。"""

import os
import sys
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 巨量数据实时流原生回归仅在真实桌面运行")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.pages.charts import MassiveDataDemo  # noqa: E402
from tests.perf.native_input import activate_window  # noqa: E402
from tests.perf.native_screen import grab_native_window  # noqa: E402

app = QApplication(sys.argv)
ThemeManager.instance().apply(app)
demo = MassiveDataDemo()
demo.resize(1200, 700)
demo.show()
errors = []
apply_calls = []


def start():
    demo.form.controls["live"].setChecked(True)
    QTimer.singleShot(250, poll)


def poll():
    sess = demo._sess
    if sess is not None and sess.ring.total_written >= 300:
        exercise(sess)
        return
    QTimer.singleShot(100, poll)


def exercise(sess):
    original_apply = demo._apply
    demo._apply = lambda *args, **kwargs: (
        apply_calls.append(args) or original_apply(*args, **kwargs))
    demo.form.controls["threaded"].setChecked(True)
    QTest.qWait(150)
    demo.form.controls["threaded"].setChecked(False)
    QTest.qWait(150)
    demo._on_data_ready([0.0] * 1000, 0)
    QTest.qWait(500)
    option = demo.chart._option
    title = option.get("title", {}).get("text", "")
    axis_type = option.get("xAxis", {}).get("type")
    print(f"[诊断] 标题={title!r} xAxis={axis_type!r} "
          f"静态重建次数={len(apply_calls)}", flush=True)
    if demo._sess is not sess:
        errors.append("实时会话被替换")
    if not title.startswith("实时滚动") or axis_type != "category":
        errors.append("实时图的标题或坐标轴被静态重建覆盖")
    if apply_calls:
        errors.append("实时期间仍执行了静态 _apply")
    if sess.ring.total_written <= 300:
        errors.append("实时生产停止")
    if errors:
        finish()
        return
    demo.form.controls["live"].setChecked(False)
    QTest.qWait(200)
    title = demo.chart._option.get("title", {}).get("text", "")
    if demo._sess is not None or not title.startswith("巨量数据"):
        errors.append("关闭实时流后未恢复静态图")
        finish()
        return
    demo.form.controls["threaded"].setChecked(True)
    demo._offline_polls = 0
    QTimer.singleShot(100, poll_offline)


def poll_offline():
    demo._offline_polls += 1
    worker = demo._worker
    if (worker is not None and not worker.isRunning()
            and getattr(demo, "_threaded_used", False)):
        print("[验收] 离线后台线程生成正常完成", flush=True)
        demo.form.controls["threaded"].setChecked(False)
        QTest.qWait(150)
        demo.form.controls["live"].setChecked(True)
        QTimer.singleShot(600, verify_live_again)
        return
    if demo._offline_polls >= 60:
        errors.append("离线后台线程未在期限内完成")
        finish()
        return
    QTimer.singleShot(100, poll_offline)


def verify_live_again():
    sess = demo._sess
    title = demo.chart._option.get("title", {}).get("text", "")
    if sess is None or sess.ring.total_written <= 0 or not title.startswith("实时滚动"):
        errors.append("离线后台生成后无法重新开启实时流")
    finish()


def finish():
    if not activate_window(demo):
        errors.append("测试窗口未能置前")
    QTest.qWait(250)
    grab_native_window(demo).save(str(
        ROOT / "tests" / "shots" / "massive_live_threading.png"))
    demo.stop()
    demo.close()
    app.exit(1 if errors else 0)


QTimer.singleShot(500, start)
sys.exit(app.exec())
