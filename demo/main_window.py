# -*- coding: utf-8 -*-
"""Demo 主窗口：顶部条 + 左侧导航树 + 右侧 QStackedWidget。

- 顶部条：标题「InstructionX_UIKit」+ 亮 / 暗主题切换 SegmentedControl + 版本标签（取自包级 __version__）；
- 左侧：QTreeWidget 导航（9 个分类，懒加载子页）；
- 右侧：QStackedWidget 切换演示页；
- 顶部条与版本标签为自绘元素，随 theme_changed 实时换肤，无需重启。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit import __version__
from InstructionX_UIKit.components.segmented import SegmentedControl
from InstructionX_UIKit.theme import T, ThemeManager

from .pages import NAV


class _TopBar(QWidget):
    """顶部条容器：自绘背景与底部分隔线（主题感知）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T("color.bg.elevated")))
        p.setPen(QPen(QColor(T("color.border"))))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class _VersionTag(QWidget):
    """GitHub 式版本标签：圆角胶囊 + 版本号（主题感知自绘）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        # 版本号唯一来源：包级 __version__（当前为 alpha 阶段）
        self._text = text if text is not None else __version__
        fm = QFontMetricsF(QFont())
        self.setFixedSize(int(fm.horizontalAdvance(self._text)) + 24, 24)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(T("color.border.strong"))))
        p.setBrush(QColor(T("color.bg.muted")))
        p.drawRoundedRect(rect, 12, 12)
        p.setPen(QPen(QColor(T("color.text.secondary"))))
        f = QFont()
        f.setPixelSize(T("font.sm"))
        f.setWeight(QFont.Weight(QFont.Medium))
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, self._text)
        p.end()


class MainWindow(QMainWindow):
    """Demo 主窗口（1280x800）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("InstructionX_UIKit · Demo")
        self.resize(1280, 800)
        self._page_cache = {}   # page_key -> QWidget
        self._syncing = False   # 主题切换控件同步防抖

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_nav())
        splitter.addWidget(self._build_stack())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1040])
        splitter.setCollapsible(1, False)
        root.addWidget(splitter, 1)

        # 默认选中第一页
        first = self._first_leaf()
        if first is not None:
            self._tree.setCurrentItem(first)

    # -- 顶部条 -----------------------------------------------------------
    def _build_topbar(self) -> QWidget:
        bar = _TopBar()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(12)

        title = QLabel("InstructionX_UIKit")
        f = QFont()
        f.setPixelSize(T("font.title.md"))
        f.setWeight(QFont.Weight(QFont.Bold))
        title.setFont(f)
        lay.addWidget(title)

        subtitle = QLabel("设计系统 · 组件库 · 布局库 · 动画库")
        subtitle.setProperty("role", "tertiary")
        lay.addWidget(subtitle)
        lay.addStretch(1)

        tm = ThemeManager.instance()
        self._theme_seg = SegmentedControl(["亮色", "暗色"], current=0)
        self._theme_seg.currentChanged.connect(self._on_seg)
        tm.theme_changed.connect(self._on_theme_changed)
        lay.addWidget(self._theme_seg)

        lay.addWidget(_VersionTag())
        return bar

    def _on_seg(self, index: int):
        """分段控件 -> 切换主题。"""
        if self._syncing:
            return
        ThemeManager.instance().set_mode("light" if index == 0 else "dark")

    def _on_theme_changed(self, mode: str):
        """主题 -> 同步分段控件（含程序内其它入口切换时）。"""
        target = 0 if mode == "light" else 1
        if self._theme_seg.current() != target:
            self._syncing = True
            self._theme_seg.set_current(target)
            self._syncing = False

    # -- 左侧导航 ---------------------------------------------------------
    def _build_nav(self) -> QWidget:
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(200)
        self._tree.setMaximumWidth(320)
        self._tree.setIndentation(16)

        cat_font = QFont()
        cat_font.setWeight(QFont.Weight(QFont.Bold))
        for cat_key, cat_title, pages in NAV:
            cat_item = QTreeWidgetItem([cat_title])
            cat_item.setFont(0, cat_font)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsSelectable)
            self._tree.addTopLevelItem(cat_item)
            for page_key, page_title, factory in pages:
                child = QTreeWidgetItem([page_title])
                child.setData(0, Qt.UserRole, (page_key, factory))
                cat_item.addChild(child)
            cat_item.setExpanded(True)

        self._tree.currentItemChanged.connect(self._on_nav)
        return self._tree

    def _first_leaf(self):
        for i in range(self._tree.topLevelItemCount()):
            cat = self._tree.topLevelItem(i)
            if cat.childCount():
                return cat.child(0)
        return None

    # -- 右侧页面堆叠 -----------------------------------------------------
    def _build_stack(self) -> QWidget:
        self._stack = QStackedWidget()
        return self._stack

    def _on_nav(self, current, previous):
        if current is None:
            return
        data = current.data(0, Qt.UserRole)
        if data is None:  # 分类头：跳到其第一个子页
            if current.childCount():
                self._tree.setCurrentItem(current.child(0))
            return
        page_key, factory = data
        self.show_page(page_key, factory)

    def show_page(self, page_key: str, factory):
        """懒加载并切换到指定演示页（公开，供测试遍历调用）。"""
        if page_key not in self._page_cache:
            page = factory()
            self._page_cache[page_key] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(self._page_cache[page_key])

    # -- 供测试使用的导航访问 --------------------------------------------
    def nav_leaves(self):
        """返回 [(page_key, page_title, tree_item)]，覆盖导航树全部叶子页。"""
        leaves = []
        for i in range(self._tree.topLevelItemCount()):
            cat = self._tree.topLevelItem(i)
            for j in range(cat.childCount()):
                child = cat.child(j)
                key, _factory = child.data(0, Qt.UserRole)
                leaves.append((key, child.text(0), child))
        return leaves

    def select_leaf(self, item):
        self._tree.setCurrentItem(item)
