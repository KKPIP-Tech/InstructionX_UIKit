# -*- coding: utf-8 -*-
"""蓝图菜单（BP_SPEC §5/§6）：节点创建菜单与节点右键菜单模板。

- ``NodeCreationMenu``：搜索框置顶 + 分类分组 + 描述 tooltip，
  回车创建第一项；支持按「待连接引脚」过滤（拖到空白松开的 UE5 行为）；
- ``NodeContextMenu``：节点右键菜单模板（重命名 / 复制 / 断开所有连线 /
  删除 / 属性），各动作只发信号，开发者自由挂接实现；
  ``add_custom_action`` 可追加自定义动作。
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
)

from ..theme import T, ThemeManager
from .model import PinDirection, types_compatible
from .node_widget import safe_slot
from .registry import NodeRegistry

__all__ = ["NodeCreationMenu", "NodeContextMenu"]


class NodeCreationMenu(QDialog):
    """节点创建菜单（模态弹出，搜索 + 分类 + 描述）。

    信号:
        type_chosen(str): 用户选定了某节点类型（参数为 ``type_name``）。

    用法::

        menu = NodeCreationMenu(canvas)
        menu.type_chosen.connect(lambda t: canvas.add_node_at(t, scene_pos))
        menu.popup_at(QCursor.pos())

    拖线到空白松开的场景可传 ``compatible`` 过滤：

        # 只列出拥有「Input 且兼容 image」引脚的节点类型
        menu.popup_at(pos, compatible=(PinDirection.Input, "image"))
    """

    #: 选定节点类型信号，参数为 type_name
    type_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMinimumWidth(260)
        self._compatible = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("搜索节点…")
        self.list = QListWidget(self)
        self.list.setMinimumHeight(220)
        self.list.setMaximumHeight(360)
        lay.addWidget(self.search_edit)
        lay.addWidget(self.list)

        self.search_edit.textChanged.connect(lambda _t: self._rebuild())
        self.search_edit.returnPressed.connect(self._choose_first)
        self.list.itemActivated.connect(self._on_item)
        self.list.itemClicked.connect(self._on_item)
        ThemeManager.instance().theme_changed.connect(
            safe_slot(lambda *_: self._retheme()))
        self._retheme()

    def _retheme(self) -> None:
        """主题感知的外框样式（内容控件走全局 QSS）。"""
        self.setStyleSheet(
            f"NodeCreationMenu {{ background-color: {T('color.bg.elevated')};"
            f" border: 1px solid {T('color.border')};"
            f" border-radius: {T('radius.lg')}px; }}")

    # -- 弹出 ------------------------------------------------------------
    def popup_at(self, global_pos: QPoint, compatible=None) -> None:
        """在全局坐标弹出菜单，搜索框聚焦。

        参数:
            global_pos: 弹出位置（全局像素坐标）。
            compatible: 可选 ``(PinDirection, data_type)``——只列出拥有
                该方向且类型兼容引脚的节点类型（拖线建节点时传入）。
        """
        self._compatible = compatible
        self.search_edit.clear()
        self._rebuild()
        self.move(global_pos)
        self.show()
        self.raise_()
        self.search_edit.setFocus()

    # -- 列表 ------------------------------------------------------------
    def _spec_visible(self, spec) -> bool:
        """按 compatible 过滤：spec 至少有一个方向 / 类型兼容的引脚。"""
        if self._compatible is None:
            return True
        direction, data_type = self._compatible
        pins = spec.inputs if direction is PinDirection.Input else spec.outputs
        for pd in pins:
            pd_type = pd.get("data_type", "any")
            if direction is PinDirection.Input:
                if types_compatible(data_type, pd_type):
                    return True
            else:
                if types_compatible(pd_type, data_type):
                    return True
        return False

    def _rebuild(self) -> None:
        """按搜索词 / 兼容过滤重建分类列表（分类头不可选）。"""
        self.list.clear()
        keyword = self.search_edit.text()
        reg = NodeRegistry.instance()
        specs = [s for s in reg.search(keyword) if self._spec_visible(s)]
        first_item = None
        for category in reg.categories():
            cat_specs = [s for s in specs if s.category == category]
            if not cat_specs:
                continue
            header = QListWidgetItem(category)
            header.setFlags(Qt.NoItemFlags)
            from PySide6.QtGui import QColor, QFont
            f = QFont(self.font())
            f.setWeight(QFont.DemiBold)
            header.setFont(f)
            header.setForeground(QColor(str(T("color.text.tertiary"))))
            self.list.addItem(header)
            for spec in cat_specs:
                item = QListWidgetItem(f"  {spec.title}")
                item.setData(Qt.UserRole, spec.type_name)
                if spec.description:
                    item.setToolTip(spec.description)
                self.list.addItem(item)
                if first_item is None:
                    first_item = item
        self._first_item = first_item
        if first_item is not None:
            self.list.setCurrentItem(first_item)

    def matching_types(self) -> list:
        """当前过滤条件下可见的 ``type_name`` 列表（测试 / 调试友好）。"""
        result = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            t = item.data(Qt.UserRole)
            if t:
                result.append(t)
        return result

    def _choose_first(self) -> None:
        """回车：创建当前过滤结果的第一项。"""
        item = self._first_item
        if item is not None:
            self._on_item(item)

    def _on_item(self, item) -> None:
        type_name = item.data(Qt.UserRole)
        if not type_name:
            return
        self.hide()
        self.type_chosen.emit(type_name)


class NodeContextMenu(QMenu):
    """节点右键菜单模板（各动作只发信号，开发者可挂回调）。

    内置动作与信号（参数均为节点 id）：
        ``rename_requested`` 重命名 / ``duplicate_requested`` 复制 /
        ``disconnect_requested`` 断开所有连线 / ``delete_requested`` 删除 /
        ``properties_requested`` 属性。

    画布为「复制 / 断开 / 删除」挂了默认实现；「重命名 / 属性」完全交给
    开发者（例如打开属性面板）。追加自定义动作::

        menu = NodeContextMenu(node.id, canvas)
        menu.add_custom_action("导出子图", lambda nid: print("导出", nid))
        menu.exec(QCursor.pos())
    """

    rename_requested = Signal(str)
    duplicate_requested = Signal(str)
    disconnect_requested = Signal(str)
    delete_requested = Signal(str)
    properties_requested = Signal(str)

    def __init__(self, node_id: str, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self._add("重命名", self.rename_requested)
        self._add("复制", self.duplicate_requested)
        self._add("断开所有连线", self.disconnect_requested)
        self.addSeparator()
        self._add("属性…", self.properties_requested)
        self.addSeparator()
        self._add("删除", self.delete_requested)

    def _add(self, text: str, signal) -> None:
        self.addAction(text, lambda: signal.emit(self.node_id))

    def add_custom_action(self, text: str, callback) -> None:
        """追加自定义动作；``callback`` 接收节点 id 作为唯一参数。"""
        self.addAction(text, lambda: callback(self.node_id))
