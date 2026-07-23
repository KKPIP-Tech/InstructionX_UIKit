# -*- coding: utf-8 -*-
"""统一对话框 Dialog（SPEC §5.3 dialog.py）。

原生窗口标题栏 + 内容区 + 按钮区。``confirm()`` / ``info()`` 静态便捷
方法以非阻塞方式弹出（show），结果通过回调或 finished 信号返回，
便于 offscreen 测试与异步交互。
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property

__all__ = ["Dialog"]

#: 跟踪非阻塞弹出的对话框，避免被 GC
_OPEN_DIALOGS = []


def _close_icon() -> QIcon:
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.tertiary")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(3.0, 3.0), QPointF(9.0, 9.0))
    painter.drawLine(QPointF(9.0, 3.0), QPointF(3.0, 9.0))
    painter.end()
    return QIcon(pm)


class Dialog(QDialog):
    """统一对话框：原生标题栏、内容区、按钮区。

    标题通过 ``setWindowTitle`` 交给系统原生窗口标题栏展示（含原生
    关闭按钮），不再自绘标题栏与关闭按钮，避免出现双重标题栏。

    参数:
        parent: 父控件。
        title: 标题文本。
        ok_text: 确认按钮文本。
        cancel_text: 取消按钮文本。
        show_cancel: 是否显示取消按钮。

    示例::

        dlg = Dialog(self, title="删除文件")
        dlg.set_text("确定删除该文件吗？")
        dlg.accepted.connect(lambda: print("已确认"))
    """

    def __init__(self, parent: QWidget = None, title: str = "",
                 ok_text: str = "确定", cancel_text: str = "取消",
                 show_cancel: bool = True):
        super().__init__(parent)
        self._title_text = title
        self.setWindowTitle(title or "对话框")
        self.setMinimumWidth(400)
        self.setWindowModality(Qt.WindowModal if parent is not None
                               else Qt.ApplicationModal)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget(self)
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(20, 16, 20, 16)
        self._body_layout.setSpacing(8)
        root.addWidget(body, 1)

        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 0, 20, 16)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)
        self._cancel = QPushButton(cancel_text, self)
        set_property(self._cancel, "variant", "default")
        self._cancel.clicked.connect(self.reject)
        self._ok = QPushButton(ok_text, self)
        set_property(self._ok, "variant", "primary")
        self._ok.setDefault(True)
        self._ok.clicked.connect(self.accept)
        footer_layout.addWidget(self._cancel)
        footer_layout.addWidget(self._ok)
        self._cancel.setVisible(show_cancel)
        root.addWidget(footer)

    # -- 公开 API ---------------------------------------------------------
    def set_title(self, text: str) -> None:
        """设置标题（显示在原生窗口标题栏）。"""
        self._title_text = text
        self.setWindowTitle(text or "对话框")

    def title(self) -> str:
        return self._title_text

    def set_text(self, text: str) -> None:
        """以一段文本填充内容区。"""
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setMinimumWidth(320)
        policy = label.sizePolicy()
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
        set_property(label, "role", "secondary")
        self.set_content(label)

    def set_content(self, widget: QWidget) -> None:
        """设置内容区控件（替换原有内容）。"""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._body_layout.addWidget(widget)

    def ok_button(self) -> QPushButton:
        return self._ok

    def cancel_button(self) -> QPushButton:
        return self._cancel

    # -- 静态便捷方法（非阻塞） ------------------------------------------
    @staticmethod
    def confirm(parent: QWidget, title: str, text: str, on_result=None,
                ok_text: str = "确定", cancel_text: str = "取消") -> "Dialog":
        """弹出确认对话框（非阻塞）。

        参数 ``on_result`` 为回调，签名为 ``on_result(ok: bool)``；
        返回 Dialog 实例，可继续连接 accepted / rejected 信号。
        """
        dlg = Dialog(parent, title, ok_text, cancel_text, show_cancel=True)
        dlg.set_text(text)
        if callable(on_result):
            dlg.finished.connect(
                lambda res: on_result(res == QDialog.DialogCode.Accepted))
        _track(dlg)
        dlg.show()
        return dlg

    @staticmethod
    def info(parent: QWidget, title: str, text: str, on_close=None,
             ok_text: str = "知道了") -> "Dialog":
        """弹出信息提示对话框（非阻塞，仅确认按钮）。"""
        dlg = Dialog(parent, title, ok_text, show_cancel=False)
        dlg.set_text(text)
        if callable(on_close):
            dlg.finished.connect(lambda _res: on_close())
        _track(dlg)
        dlg.show()
        return dlg


def _track(dlg: Dialog) -> None:
    """持有非阻塞对话框引用，finished 后释放。"""
    _OPEN_DIALOGS.append(dlg)

    def _release(*_):
        if dlg in _OPEN_DIALOGS:
            _OPEN_DIALOGS.remove(dlg)

    dlg.finished.connect(_release)
