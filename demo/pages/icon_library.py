# -*- coding: utf-8 -*-
"""Iconoir 图标库浏览器（设计令牌 → 图标库）。

完整加载 Iconoir v7.12.1 的 1,671 个图标（1,383 Regular + 288 Solid），
提供搜索、Regular/Solid 过滤、尺寸/描边预览和单击复制接口示例。
"""

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit import (
    ICONOIR_NAMES,
    ICONOIR_REGULAR_NAMES,
    ICONOIR_SOLID_NAMES,
    ICONOIR_VERSION,
    get_pixmap,
)
from InstructionX_UIKit.components import Button, ComboBox, LineEdit
from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

from .common import Section, flow_row, hint_label, make_page

__all__ = ["create_page"]

_PAGE_SIZE = 32
_PAGE_STROKE = 1.5


class _Swatch(QWidget):
    """单个调色盘色块：自绘圆角方块 + 选中描边。"""

    clicked = Signal(str, QColor)

    def __init__(self, token: str, color: QColor, parent=None):
        super().__init__(parent)
        self._token = token
        self._color = QColor(color)
        self._selected = False
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(token)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)
        if self._selected:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T("color.text.primary")), 2))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        p.end()

    def mousePressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._token, QColor(self._color))
        super().mousePressEvent(event)


class _ColorPalette(QWidget):
    """主题语义色调色盘；点击后实时刷新图标颜色。"""

    color_changed = Signal(str, QColor)

    #: 预置色：主色/成功/警告/危险/正文/次要文本
    TOKENS = (
        "color.primary",
        "color.success",
        "color.warning",
        "color.danger",
        "color.text.primary",
        "color.text.secondary",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T("space.2"))
        self._swatches = []
        self._selected = "color.primary"
        for token in self.TOKENS:
            swatch = _Swatch(token, QColor(T(token)), self)
            swatch.clicked.connect(self._on_swatch)
            lay.addWidget(swatch)
            self._swatches.append(swatch)
        lay.addStretch(1)
        self.select(self._selected)

    def select(self, token: str) -> None:
        self._selected = token
        for swatch in self._swatches:
            swatch.set_selected(swatch._token == token)

    def refresh(self) -> None:
        """主题切换后重取令牌色。"""
        for swatch in self._swatches:
            swatch.set_color(QColor(T(swatch._token)))

    def _on_swatch(self, token: str, color: QColor) -> None:
        self.select(token)
        self.color_changed.emit(token, color)


class _IconGrid(QListWidget):
    """图标网格：一次性建项，搜索/过滤只切 hidden，避免重复生成 QIcon。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(_PAGE_SIZE, _PAGE_SIZE))
        self.setGridSize(QSize(116, 78))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setStyleSheet(
            "QListWidget { background: transparent; border: none;"
            f" color: {T('color.text.secondary')}; }}"
            "QListWidget::item {"
            f" color: {T('color.text.secondary')};"
            " border-radius: 8px; padding: 6px 4px; }"
            "QListWidget::item:selected {"
            f" background: {T('color.primary.subtle')};"
            f" color: {T('color.text.primary')}; }}"
        )
        self._items = {}
        self._color = QColor(T("color.primary"))
        self._size = _PAGE_SIZE
        self._stroke = _PAGE_STROKE

    def _icon(self, name: str) -> QIcon:
        pm = get_pixmap(name, self._size, self._color, self._stroke)
        return QIcon(pm)

    def set_style(self, size: int, stroke: float) -> None:
        self._size = int(size)
        self._stroke = float(stroke)
        self.setIconSize(QSize(self._size, self._size))
        self.rebuild()

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.rebuild()

    def rebuild(self) -> None:
        """按当前尺寸/描边重建全部条目。"""
        current = self.currentItem()
        current_name = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.blockSignals(True)
        self.clear()
        self._items.clear()
        for name in ICONOIR_NAMES:
            item = QListWidgetItem(self._icon(name), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter
                                  | Qt.AlignmentFlag.AlignTop)
            self.addItem(item)
            self._items[name] = item
        self.blockSignals(False)
        if current_name in self._items:
            self.setCurrentItem(self._items[current_name])
        elif self.count():
            self.setCurrentRow(0)

    def apply_filter(self, query: str, solid_filter) -> int:
        """按名称与 Regular/Solid 过滤；返回可见数量。"""
        text = str(query or "").strip().lower()
        visible = 0
        first = None
        for name, item in self._items.items():
            is_solid = name.endswith("-solid")
            ok_solid = (solid_filter is None or
                        (solid_filter is True) == is_solid)
            ok_text = not text or text in name.lower()
            show = ok_solid and ok_text
            item.setHidden(not show)
            if show:
                visible += 1
                if first is None:
                    first = item
        if first is not None:
            self.setCurrentItem(first)
        return visible


class _IconDetail(QFrame):
    """选中图标的预览、名称与最小调用示例。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        set_property(self, "role", "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(96, 96)
        self.preview.setStyleSheet(
            f"background: {T('color.bg.subtle')};"
            f" border: 1px solid {T('color.border')}; border-radius: 10px;")
        lay.addWidget(self.preview)

        self.name_label = QLabel("选择一个图标")
        set_font(self.name_label, "font.md", "semibold")
        self.name_label.setWordWrap(True)
        lay.addWidget(self.name_label)

        self.code_label = QLabel()
        self.code_label.setWordWrap(True)
        self.code_label.setProperty("role", "tertiary")
        set_font(self.code_label, "font.sm")
        lay.addWidget(self.code_label)

        self.copy_btn = Button("复制调用代码", size="sm")
        self.copy_btn.clicked.connect(self._copy)
        lay.addWidget(self.copy_btn)
        lay.addStretch(1)

        self._name = ""
        self._size = _PAGE_SIZE
        self._stroke = _PAGE_STROKE
        self._color = QColor(T("color.primary"))

    def set_icon(self, name: str, size: int, stroke: float,
                 color: QColor) -> None:
        self._name = name
        self._size = int(size)
        self._stroke = float(stroke)
        self._color = QColor(color)
        pm = get_pixmap(name, 64, color, stroke)
        self.preview.setPixmap(pm)
        self.name_label.setText(name)
        self.code_label.setText(
            f'get_icon("{name}", size={size}, '
            f'stroke_width={stroke:g}, color="{color.name()}")')
        self.copy_btn.setEnabled(bool(name))

    def _copy(self) -> None:
        if self._name:
            QApplication.clipboard().setText(
                f'get_icon("{self._name}", size={self._size}, '
                f'stroke_width={self._stroke:g}, '
                f'color="{self._color.name()}")')


class _IconLibraryPage(QWidget):
    """页面状态：搜索/过滤/尺寸/描边/主题。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._size = _PAGE_SIZE
        self._stroke = _PAGE_STROKE
        self._color_token = "color.primary"
        self._color = QColor(T(self._color_token))
        self._solid_filter = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)

        self.search = LineEdit(placeholder="搜索图标名称，例如 arrow、home、solid")
        self.search.setMinimumWidth(260)
        self.solid_combo = ComboBox(["全部", "Regular", "Solid"], size="sm")
        self.size_combo = ComboBox(["16", "24", "32", "48"], size="sm")
        self.size_combo.setCurrentText(str(_PAGE_SIZE))
        self.stroke_combo = ComboBox(["1.0", "1.5", "2.0"], size="sm")
        self.stroke_combo.setCurrentText(f"{_PAGE_STROKE:g}")
        self.count_label = QLabel()
        set_font(self.count_label, "font.sm")
        set_property(self.count_label, "role", "tertiary")
        self.palette = _ColorPalette()
        self.palette.color_changed.connect(self._on_color)

        self.grid = _IconGrid()
        self.grid.setMinimumHeight(500)
        self.grid.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Expanding)
        self.detail = _IconDetail()
        self.detail.setFixedWidth(260)

        self.search.textChanged.connect(self._schedule_filter)
        self.solid_combo.currentTextChanged.connect(self._on_filter)
        self.size_combo.currentTextChanged.connect(self._on_size)
        self.stroke_combo.currentTextChanged.connect(self._on_stroke)
        self.grid.currentItemChanged.connect(self._on_current)
        ThemeManager.instance().theme_changed.connect(self._on_theme)
        self._search_timer.timeout.connect(self._apply_filter)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(T("layout.card.gap"))
        body_lay.addWidget(self.grid, 1)
        body_lay.addWidget(self.detail, 0)
        self._build_ui(body)

    def _build_ui(self, body) -> None:
        section = Section("全部图标", spacing=T("layout.card.gap"))
        section.layout().addWidget(
            flow_row(
                QLabel("搜索"), self.search,
                QLabel("风格"), self.solid_combo,
                QLabel("尺寸"), self.size_combo,
                QLabel("描边"), self.stroke_combo,
                QLabel("颜色"), self.palette,
                self.count_label,
                spacing=6,
            )
        )
        section.layout().addWidget(
            hint_label(
                f"Iconoir v{ICONOIR_VERSION} · {len(ICONOIR_NAMES)} 个图标 "
                f"（Regular {len(ICONOIR_REGULAR_NAMES)} / Solid "
                f"{len(ICONOIR_SOLID_NAMES)}）；点击图标查看调用代码。",
                role="secondary"))
        section.layout().addWidget(body, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(section)

        self.grid.rebuild()
        self._apply_filter()

    def _schedule_filter(self, _text=None) -> None:
        self._search_timer.start()

    def _on_filter(self, text: str) -> None:
        self._solid_filter = {"Regular": False, "Solid": True}.get(text)
        self._apply_filter()

    def _on_size(self, text: str) -> None:
        try:
            self._size = int(text)
        except ValueError:
            return
        self.grid.set_style(self._size, self._stroke)
        self._apply_filter()
        self._on_current(self.grid.currentItem())

    def _on_stroke(self, text: str) -> None:
        try:
            self._stroke = float(text)
        except ValueError:
            return
        self.grid.set_style(self._size, self._stroke)
        self._apply_filter()
        self._on_current(self.grid.currentItem())

    def _on_color(self, token: str, color: QColor) -> None:
        """调色盘点击：实时重建图标颜色并同步详情。"""
        self._color_token = token
        self._color = QColor(color)
        self.grid.set_color(color)
        self._apply_filter()
        self._on_current(self.grid.currentItem())

    def _apply_filter(self) -> None:
        visible = self.grid.apply_filter(self.search.text(),
                                         self._solid_filter)
        self.count_label.setText(f"{visible} / {len(ICONOIR_NAMES)}")

    def _on_current(self, current, _previous=None) -> None:
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        self.detail.set_icon(name, self._size, self._stroke, self._color)

    def _on_theme(self, _mode) -> None:
        """主题切换：按当前选中语义色重取令牌并刷新全部图标。"""
        self.palette.refresh()
        self._color = QColor(T(self._color_token))
        self.grid.set_color(self._color)
        self._apply_filter()
        self._on_current(self.grid.currentItem())


def create_page() -> QWidget:
    """创建 Icon Library 演示页。"""
    return make_page(
        "图标库",
        "完整浏览 Iconoir v7.12.1：搜索、Regular/Solid 过滤、尺寸/描边/颜色"
        "实时预览，并直接查看 get_icon 调用参数。",
        [_IconLibraryPage()],
    )
