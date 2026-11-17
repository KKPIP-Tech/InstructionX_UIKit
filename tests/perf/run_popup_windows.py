# -*- coding: utf-8 -*-
"""真实透明弹窗采集及原始／当前源码的同机原生图像比较。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]


def capture(args):
    source = args.source.resolve()
    os.environ.pop("QT_QPA_PLATFORM", None)
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(ROOT / "tests" / "perf"))

    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
    from InstructionX_UIKit.components import (
        BudgetSliderGroup, Dialog, Drawer, Message, Notification, Popconfirm, Popover, Tour,
    )
    from InstructionX_UIKit.theme import ThemeManager
    from event_scenario import run_event_scenario
    from native_input import client_to_physical
    from native_screen import grab_native_window

    def rgba(image):
        image = image.convertToFormat(QImage.Format_RGBA8888)
        image.setDevicePixelRatio(1.0)
        return image

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tm = ThemeManager.instance()
    tm.apply(app)
    host = QWidget()
    host.setObjectName("popupHost")
    host.setStyleSheet("#popupHost { background: #f0f0f0; }")
    host.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    host.resize(900, 650)
    host.move(100, 60)
    anchor = QPushButton("弹窗锚点", host)
    anchor.setGeometry(300, 220, 100, 32)
    host.show()
    host.raise_()
    host.activateWindow()
    source_sha = args.source_sha or subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    output = ROOT / "temp" / "performance" / source_sha / "popups" / args.label
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    current = None

    def close_current():
        nonlocal current
        if current is not None:
            current.close()
            current.deleteLater()
            current = None
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()

    def record(name, actual, expected):
        actual.save(str(output / f"{name}_actual.png"))
        expected.save(str(output / f"{name}_expected.png"))
        same = actual.size() == expected.size() and actual == expected
        checks.append({"name": name, "synthetic_equal": same,
                       "actual_size": [actual.width(), actual.height()],
                       "expected_size": [expected.width(), expected.height()]})
        print(f"  [记录] {name} 合成参考一致={same}", flush=True)

    def capture_popup(name):
        actual = rgba(grab_native_window(current.windowHandle()))
        popup_image = rgba(current.grab().toImage())
        if actual.size() != popup_image.size():
            record(name, actual, popup_image)
            return
        p0 = client_to_physical(current, QPoint(0, 0))
        p1 = client_to_physical(host, QPoint(0, 0))
        x, y = p0[0] - p1[0], p0[1] - p1[1]
        underlay = rgba(host.grab().toImage())
        expected = underlay.copy(x, y, actual.width(), actual.height())
        if expected.size() != actual.size():
            record(name, actual, expected)
            return
        painter = QPainter(expected)
        painter.drawImage(0, 0, popup_image)
        painter.end()
        record(name, actual, expected)

    def capture_host(name):
        actual = rgba(grab_native_window(host.windowHandle()))
        expected = rgba(host.grab().toImage())
        record(name, actual, expected)

    def scenario():
        nonlocal current
        report = {"source_sha": source_sha, "source": str(source),
                  "native_mouse_verified": False, "capture_complete": False}
        try:
            yield 500
            for mode in ("light", "dark"):
                tm.set_mode(mode)
                yield 150
                current = Popover("筛选", "气泡正文")
                current.show_for(anchor, "bottom")
                yield 500
                capture_popup(f"{mode}_popover")
                close_current()

                current = Popconfirm(anchor, "确定删除该文件吗？")
                current.show_popup()
                yield 300
                capture_popup(f"{mode}_popconfirm")
                close_current()

                current = Dialog(host, title="删除文件")
                current.set_text("确定删除该文件吗？")
                current.show()
                yield 500
                capture_popup(f"{mode}_dialog")
                close_current()

                current = Drawer(host, position="right", size=300, title="详情")
                current.set_content(QLabel("抽屉内容"))
                current.open()
                yield 500
                capture_popup(f"{mode}_drawer")
                close_current()

                current = Message.info(anchor, "操作已完成", duration=0)
                yield 500
                capture_popup(f"{mode}_message")
                Message.close_all()
                current = None

                current = Notification.info(anchor, "构建完成", "全部检查已结束", duration=0)
                yield 500
                capture_popup(f"{mode}_notification")
                Notification.close_all()
                current = None

                current = Tour(host)
                current.add_step(anchor, "引导步骤", "这里是需要关注的控件")
                current.start()
                yield 400
                capture_host(f"{mode}_tour")
                current.stop()
                close_current()

                current = BudgetSliderGroup(parent=host)
                current.move(40, 420)
                current.resize(500, 160)
                current.show()
                yield 300
                capture_host(f"{mode}_budget_pill")
                close_current()
            report.update(checks=checks, capture_complete=True,
                          synthetic_reference="QPainter 合成仅供诊断，不作桌面验收基线")
        except Exception as exc:
            traceback.print_exc()
            report.update(checks=checks, exception=repr(exc))
        finally:
            close_current()
            Message.close_all()
            Notification.close_all()
            host.close()
            host.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            (output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            app.exit(0 if report["capture_complete"] else 1)

    return run_event_scenario(app, scenario())


def compare(args):
    import numpy as np
    from PySide6.QtGui import QImage

    before_root = args.before.resolve()
    after_root = args.after.resolve()
    before_report = json.loads((before_root / "report.json").read_text(encoding="utf-8"))
    after_report = json.loads((after_root / "report.json").read_text(encoding="utf-8"))
    if not before_report.get("capture_complete") or not after_report.get("capture_complete"):
        raise AssertionError("两次弹窗采集必须都正常结束")
    names = [item["name"] for item in before_report["checks"]]
    after_names = [item["name"] for item in after_report["checks"]]
    if len(names) != 16 or names != after_names:
        raise AssertionError(f"弹窗状态集合不完整: {names!r} / {after_names!r}")
    results = []
    for name in names:
        before = QImage(str(before_root / f"{name}_actual.png")).convertToFormat(
            QImage.Format_RGBA8888)
        after = QImage(str(after_root / f"{name}_actual.png")).convertToFormat(
            QImage.Format_RGBA8888)
        row = {"name": name}
        if before.size() != after.size():
            row.update(equal=False, reason="尺寸不同")
        else:
            aa = np.frombuffer(after.constBits(), dtype=np.uint8).reshape(
                after.height(), after.width(), 4)
            bb = np.frombuffer(before.constBits(), dtype=np.uint8).reshape(
                before.height(), before.width(), 4)
            delta = aa.astype(np.int16) - bb.astype(np.int16)
            changed = np.any(delta, axis=2)
            row.update(equal=not changed.any(), changed=int(changed.sum()),
                       max_delta=int(np.abs(delta).max()))
        results.append(row)
    mismatches = [row for row in results if not row["equal"]]
    report = {"before": str(before_root), "after": str(after_root),
              "count": len(results), "required_count": 16,
              "comparison": "原始源码与当前源码的真实 Win32 客户区 RGBA 比较",
              "mismatches": mismatches, "pass": not mismatches}
    args.out.resolve().mkdir(parents=True, exist_ok=True)
    (args.out.resolve() / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 1


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    shoot = commands.add_parser("capture")
    shoot.add_argument("--source", type=Path, default=ROOT)
    shoot.add_argument("--source-sha")
    shoot.add_argument("--label", default="candidate")
    shoot.set_defaults(function=capture)
    diff = commands.add_parser("compare")
    diff.add_argument("--before", type=Path, required=True)
    diff.add_argument("--after", type=Path, required=True)
    diff.add_argument("--out", type=Path, required=True)
    diff.set_defaults(function=compare)
    args = parser.parse_args()
    return args.function(args)


if __name__ == "__main__":
    raise SystemExit(main())
