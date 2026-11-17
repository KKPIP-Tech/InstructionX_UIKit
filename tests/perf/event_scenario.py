# -*- coding: utf-8 -*-
"""让真实 GUI 验收步骤始终运行在 QApplication 事件循环内。"""

import traceback

from PySide6.QtCore import QTimer


def run_event_scenario(app, scenario):
    """执行一个 yield 毫秒数的生成器，返回值即 app.exec 的退出码。"""
    iterator = iter(scenario)

    def advance():
        try:
            delay = next(iterator)
        except StopIteration:
            app.exit(0)
        except Exception:
            traceback.print_exc()
            app.exit(1)
        else:
            QTimer.singleShot(max(0, int(delay)), advance)

    QTimer.singleShot(0, advance)
    return app.exec()
