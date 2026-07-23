# -*- coding: utf-8 -*-
"""级联选择器组件（SPEC §5.1）。

``Cascader`` = 触发按钮 + 多级 QMenu（全局 QSS 已提供菜单与右箭头样式）。
选项为嵌套字典：``{"value": .., "label": .., "children": [...],
"disabled": bool}``；选中叶子节点后发射 ``pathChanged``。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QWidget

from ..theme import set_property

__all__ = ["Cascader"]

_SIZES = ("sm", "md", "lg")


class Cascader(QWidget):
    """级联选择器。

    用途:
        多级树形数据的路径选择（如省 / 市 / 区），
        点击按钮弹出级联菜单，选中叶子后按钮显示完整路径。

    参数:
        options: 嵌套选项列表，节点为
            ``{"value": 任意值, "label": 显示文案, "children": [...], "disabled": bool}``。
        placeholder: 未选择时的占位文案。
        size: ``sm`` / ``md`` / ``lg``（作用于触发按钮）。
        parent: 父控件。

    示例::

        cas = Cascader([
            {"value": "zj", "label": "浙江", "children": [
                {"value": "hz", "label": "杭州"},
                {"value": "nb", "label": "宁波"},
            ]},
        ])
        cas.pathChanged.connect(lambda path: print("选中路径:", path))
    """

    #: 选中路径变化信号（参数为 value 列表）
    pathChanged = Signal(list)

    def __init__(self, options=(), placeholder: str = "请选择",
                 size: str = "md", parent=None):
        super().__init__(parent)
        self._options = []
        self._placeholder = placeholder
        self._path = []          # value 列表
        self._labels = []        # label 列表
        self._menu = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._button = QPushButton(placeholder, self)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.setMinimumWidth(180)
        self._button.clicked.connect(self._popup)
        layout.addWidget(self._button)
        self.set_size(size)
        if options:
            self.set_options(options)

    # ------------------------------------------------------------------
    # 选项与选中
    # ------------------------------------------------------------------

    def set_options(self, options) -> None:
        """设置级联选项（嵌套字典列表），并清空当前选中。"""
        self._options = list(options)
        self.clear()

    def options(self) -> list:
        """当前选项树。"""
        return list(self._options)

    def set_placeholder(self, text: str) -> None:
        """设置占位文案。"""
        self._placeholder = text
        if not self._path:
            self._button.setText(text)

    def path(self) -> list:
        """当前选中的 value 路径。"""
        return list(self._path)

    def labels(self) -> list:
        """当前选中的 label 路径。"""
        return list(self._labels)

    def set_path(self, values, emit: bool = False) -> bool:
        """按 value 路径选中，返回路径是否完整有效。"""
        labels = []
        nodes = self._options
        for value in values:
            hit = next((n for n in nodes if n.get("value") == value), None)
            if hit is None:
                return False
            labels.append(str(hit.get("label", hit.get("value"))))
            nodes = hit.get("children") or []
        self._path = list(values)
        self._labels = labels
        self._button.setText(" / ".join(labels))
        if emit:
            self.pathChanged.emit(list(self._path))
        return True

    def clear(self) -> None:
        """清空选中，恢复占位文案。"""
        self._path = []
        self._labels = []
        self._button.setText(self._placeholder)

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知级联选择器尺寸: {size!r}")
        set_property(self, "size", size)
        set_property(self._button, "size", size)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    # ------------------------------------------------------------------
    # 弹出与菜单构建
    # ------------------------------------------------------------------

    def _popup(self) -> None:
        if not self._options or not self.isEnabled():
            return
        self._rebuild_menu()
        pos = self._button.mapToGlobal(self._button.rect().bottomLeft())
        self._menu.popup(pos)

    def _rebuild_menu(self) -> None:
        if self._menu is not None:
            self._menu.deleteLater()
        self._menu = QMenu(self)
        for node in self._options:
            self._add_node(self._menu, node, [])

    def _add_node(self, menu: QMenu, node: dict, prefix: list) -> None:
        label = str(node.get("label", node.get("value")))
        value = node.get("value")
        children = node.get("children") or []
        trail = prefix + [(value, label)]
        if children:
            sub = menu.addMenu(label)
            sub.setEnabled(not node.get("disabled", False))
            for child in children:
                self._add_node(sub, child, trail)
        else:
            action = QAction(label, menu)
            if node.get("disabled", False):
                action.setEnabled(False)
            action.triggered.connect(
                lambda _checked=False, t=trail: self._select(t))
            menu.addAction(action)

    def _select(self, trail: list) -> None:
        self._path = [v for v, _l in trail]
        self._labels = [l for _v, l in trail]
        self._button.setText(" / ".join(self._labels))
        self.pathChanged.emit(list(self._path))
