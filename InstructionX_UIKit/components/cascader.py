# -*- coding: utf-8 -*-
"""级联选择器组件（SPEC §5.1）。

``Cascader`` = 触发按钮 + 多级 QMenu（全局 QSS 已提供菜单与右箭头样式）。
选项为嵌套字典：``{"value": .., "label": .., "children": [...],
"disabled": bool}``；选中叶子节点后发射 ``pathChanged``。

本轮修复（轨道 2）：

- **触发按钮文字左对齐**：``QPushButton`` 默认居中显示文案，作为「选择类」
  控件与 ``ComboBox`` / ``LineEdit`` 的左对齐文字对不齐。组件用一条**只含
  ``text-align``** 的实例级 QSS 覆盖（不含颜色 / 尺寸，其余样式仍由全局
  QSS 负责），与下拉框左缘口径一致（契约 §3）。
- **缺省宽度由内容决定**：原写死 ``setMinimumWidth(180)``（裸数字，既不在
  令牌集合也不随字号档缩放）。改为按「最宽的一级文案 + 左右内边距」计算，
  换字号 / 换数据都会跟着变。
- 菜单实例复用（``clear()`` 重建而非每次 ``deleteLater``），避免反复弹开
  累积 QMenu 与其 action。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QWidget

from ..theme import T, set_property, _INPUT_HEIGHTS
from ._mixin import SizeMixin

__all__ = ["Cascader"]


class Cascader(SizeMixin, QWidget):
    """级联选择器。

    用途:
        多级树形数据的路径选择（如省 / 市 / 区），
        点击按钮弹出级联菜单，选中叶子后按钮显示完整路径。

    参数:
        options: 嵌套选项列表，节点为
            ``{"value": 任意值, "label": 显示文案, "children": [...], "disabled": bool}``。
        placeholder: 未选择时的占位文案。
        size: ``sm`` / ``md`` / ``lg``（作用于触发按钮，高度 22 / 28 / 34）。
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

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "级联选择器"

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
        self._apply_trigger_style()
        self._button.clicked.connect(self._popup)
        layout.addWidget(self._button)
        self.set_size(size)
        if options:
            self.set_options(options)
        else:
            self._update_min_width()

    # ------------------------------------------------------------------
    # 选项与选中
    # ------------------------------------------------------------------

    def set_options(self, options) -> None:
        """设置级联选项（嵌套字典列表），并清空当前选中。"""
        self._options = list(options)
        self.clear()
        self._update_min_width()

    def options(self) -> list:
        """当前选项树。"""
        return list(self._options)

    def set_placeholder(self, text: str) -> None:
        """设置占位文案。"""
        self._placeholder = text
        if not self._path:
            self._button.setText(text)
        self._update_min_width()

    def path(self) -> list:
        """当前选中的 value 路径。"""
        return list(self._path)

    def labels(self) -> list:
        """当前选中的 label 路径。"""
        return list(self._labels)

    def set_path(self, values, emit: bool = False) -> bool:
        """按 value 路径选中，返回路径是否完整有效。

        ``values`` 支持任意可迭代对象（含生成器），入参立即物化。
        """
        values = list(values)  # 生成器一次性迭代：先物化避免被 for 耗尽
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

    def _apply_trigger_style(self) -> None:
        """触发按钮的实例级 QSS：左对齐 + 与下拉框一致的左内边距。

        只覆盖两件事，其余（高度 / 圆角 / 颜色 / 右内边距 / 字阶）仍由
        全局 QSS 负责：

        - ``text-align: left``：``QPushButton`` 默认居中，作为「选择类」
          控件与 ``ComboBox`` / ``LineEdit`` 的左对齐文字对不齐（契约 §3）。
        - ``padding-left: space.3``：全局按钮按档位给 8 / 16 / 20px 左内边距，
          三档各不相同；这里统一成与 ``ComboBox`` 相同的一档，使三种选择类
          控件的文字左缘在三档下都落在同一条竖线上。
        """
        self._button.setStyleSheet(
            f"QPushButton {{ text-align: left;"
            f" padding-left: {int(T('space.3'))}px; }}")

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：触发按钮同步尺寸档。

        根控件是按钮的透明外壳，min / max height 一并锁到该档高度：
        否则外层布局一拉伸，外壳就变成 60px 高的空壳，而声明的
        ``uiksize`` 仍写着 md（契约 §1）。
        """
        set_property(self._button, "size", size)
        self.setMinimumHeight(_INPUT_HEIGHTS[size])
        self.setMaximumHeight(_INPUT_HEIGHTS[size])
        self._update_min_width()

    def _update_min_width(self) -> None:
        """按「最宽一级文案 + 左右内边距」给触发按钮一个缺省宽度。

        宽度随字号档与数据自动伸缩，取代原先写死的 180px 裸数字。
        """
        fm = self._button.fontMetrics()
        texts = [self._placeholder]
        for node in self._options:
            texts.append(str(node.get("label", node.get("value"))))
        text_w = max((fm.horizontalAdvance(t) for t in texts), default=0)
        pad = 2 * int(T("layout.inset.pad_x")) + int(T("space.4"))
        self._button.setMinimumWidth(text_w + pad)

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
        """复用同一个 QMenu 实例重建菜单（避免每次弹开累积菜单与 action）。"""
        if self._menu is None:
            self._menu = QMenu(self)
        else:
            self._menu.clear()
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
