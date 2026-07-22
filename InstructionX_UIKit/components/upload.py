# -*- coding: utf-8 -*-
"""文件上传组件（SPEC §5.1）。

``UploadWidget`` = 拖拽区（自绘虚线框，支持拖入文件与点击选择）+
文件列表（文件名 + 移除按钮）。任何增删都会发射 ``filesChanged``。
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from .button import Button

__all__ = ["UploadWidget"]


class _DropArea(QFrame):
    """内部：拖拽热区，自绘虚线边框与 hover / 拖入高亮。"""

    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(104)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._drag = False
        ThemeManager.instance().theme_changed.connect(self.update)

    # -- 视觉状态 ------------------------------------------------------
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    # -- 拖拽 ----------------------------------------------------------
    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if any(u.isLocalFile() for u in urls):
            event.acceptProposedAction()
            self._drag = True
            self.update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drag = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drag = False
        self.update()
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # -- 绘制 ----------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        active = self._drag or self._hover
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.primary.subtle")) if self._drag
                   else QColor(T("color.bg.subtle")))
        p.drawRoundedRect(rect, 8.0, 8.0)
        pen = QPen(QColor(T("color.primary")) if active
                   else QColor(T("color.border.strong")))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 8.0, 8.0)
        p.end()


class UploadWidget(QWidget):
    """文件上传选择器。

    用途:
        通过拖拽或按钮选择本地文件，列表展示已选文件并支持逐个移除。
        本组件只收集文件路径，不执行实际上传。

    参数:
        hint: 拖拽区提示文案。
        button_text: 选择按钮文案。
        parent: 父控件。

    示例::

        up = UploadWidget()
        up.filesChanged.connect(lambda files: print("文件:", files))
        up.add_files(["/tmp/a.txt"])
    """

    #: 文件集合变化信号（参数为路径列表）
    filesChanged = Signal(list)

    def __init__(self, hint: str = "拖拽文件到此处，或点击选择文件",
                 button_text: str = "选择文件", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._drop = _DropArea(self)
        drop_layout = QVBoxLayout(self._drop)
        drop_layout.setContentsMargins(12, 12, 12, 12)
        drop_layout.setSpacing(8)
        self._hint = QLabel(hint, self._drop)
        set_property(self._hint, "role", "hint")
        self._hint.setAlignment(Qt.AlignCenter)
        self._pick = Button(button_text, variant="default", size="sm",
                            parent=self._drop)
        self._pick.clicked.connect(self._open_dialog)
        drop_layout.addStretch(1)
        drop_layout.addWidget(self._hint)
        drop_layout.addWidget(self._pick, 0, Qt.AlignCenter)
        drop_layout.addStretch(1)
        self._drop.files_dropped.connect(self.add_files)
        self._drop.clicked.connect(self._open_dialog)
        layout.addWidget(self._drop)

        self._list = QListWidget(self)
        layout.addWidget(self._list)
        self._sync_list_visibility()

    # ------------------------------------------------------------------
    # 文件集合
    # ------------------------------------------------------------------

    def files(self) -> list:
        """当前已选文件路径列表。"""
        return [self._list.item(i).data(Qt.UserRole)
                for i in range(self._list.count())]

    def add_files(self, paths) -> None:
        """添加文件路径（自动去重），发射 ``filesChanged``。"""
        existing = set(self.files())
        added = False
        for path in paths:
            path = str(path)
            if not path or path in existing:
                continue
            existing.add(path)
            self._append_row(path)
            added = True
        if added:
            self._sync_list_visibility()
            self.filesChanged.emit(self.files())

    def remove_file(self, path: str) -> None:
        """按路径移除文件。"""
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == path:
                self._list.takeItem(i)
                break
        self._sync_list_visibility()
        self.filesChanged.emit(self.files())

    def clear(self) -> None:
        """清空文件列表。"""
        if self._list.count():
            self._list.clear()
            self._sync_list_visibility()
            self.filesChanged.emit([])

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _append_row(self, path: str) -> None:
        item = QListWidgetItem(self._list)
        item.setData(Qt.UserRole, path)
        row = QWidget(self._list)
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 2, 8, 2)
        h.setSpacing(8)
        name = QLabel(Path(path).name, row)
        name.setToolTip(path)
        h.addWidget(name, 1)
        btn = QToolButton(row)
        btn.setText("移除")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, p=path: self.remove_file(p))
        h.addWidget(btn, 0)
        item.setSizeHint(row.sizeHint())
        self._list.setItemWidget(item, row)

    def _sync_list_visibility(self) -> None:
        count = self._list.count()
        self._list.setVisible(count > 0)
        if count:
            row_h = self._list.sizeHintForRow(0) or 30
            shown = min(count, 5)  # 超过 5 行出现滚动条
            h = shown * row_h + self._list.frameWidth() * 2 + 6
            self._list.setFixedHeight(h)

    def _open_dialog(self) -> None:
        paths, _flt = QFileDialog.getOpenFileNames(self, "选择文件")
        if paths:
            self.add_files(paths)
