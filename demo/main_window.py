# -*- coding: utf-8 -*-
"""Demo 主窗口：品牌顶栏 + 侧边导航 + 右侧内容区。

- 顶栏：品牌标识 + 名称 + 版本胶囊，右侧为亮 / 暗主题切换与「全屏/窗口」无关的留白；
- 侧栏：搜索框 + 分类导航，叶子项带矢量图标、hover 底色与选中态左侧强调条；
- 内容区：QStackedWidget 懒加载切换演示页；
- 顶栏、导航、版本标签均为自绘 / 角色化 QSS 元素，随 ``theme_changed`` 实时换肤。

导航为自绘控件而非 QTreeWidget：QTreeWidget 的分支线、项目高度与选中态
无法贴合设计令牌，逐项自绘才能保证与 Kit 组件同一套视觉语言。
"""

import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit import __version__
from InstructionX_UIKit.components.segmented import SegmentedControl
from InstructionX_UIKit.icons import get_icon
from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

from .pages import NAV

# ---------------------------------------------------------------------------
# 图标适配层（临时实现，后续替换为专用 Icon 图标库）
# ---------------------------------------------------------------------------
# 这里是全 Demo **唯一**获取图标的地方。后续接入正式图标库时，只需改
# ``_icon()`` 的实现（以及 ``_CATEGORY_ICONS`` 的取值），导航渲染逻辑
# （尺寸 / 对齐 / 主题换色 / 缓存策略）都不需要改动。
#
# 当前用 Kit 自带的 QPainter 矢量图标占位。注意 Kit 的 QIcon 把颜色烤进
# 像素，所以主题切换时必须重新取一次——调用方通过 ``_icon()`` 统一处理。

#: 导航分类 -> 图标语义名。接入正式图标库后，把取值换成图标库的 name 即可。
_CATEGORY_ICONS = {
    "tokens": "chart",
    "layouts": "layout",
    "inputs": "component",
    "display": "layout",
    "feedback": "info",
    "anim_property": "animation",
    "anim_painted": "animation",
    "charts": "chart",
    "basic_widgets": "component",
    "blueprint": "layout",
    "code_editor": "edit",
}

#: 未知图标名的回退
_ICON_FALLBACK = "component"

#: 导航图标统一边长（px）——与文字光学对齐，实测 15px 与 13px 正文最协调
_NAV_ICON_SIZE = 15


def _nav_text_x() -> int:
    """导航项文本左缘 = 左内边距 + 图标边长 + 图标文字间距。

    选中态强调条贴左内边距、图标紧随其后、文本再随之，三者共用这一条基准线，
    保证 hover / 选中 / 默认三种状态下文本不会横向跳动。
    """
    return T("layout.nav.pad_x") + _NAV_ICON_SIZE + T("layout.icon.gap")


def _icon(name: str, color: str) -> QIcon:
    """按语义名 + 颜色取图标（图标库唯一接入口）。

    参数:
        name: ``_CATEGORY_ICONS`` 中的语义名。
        color: 描边色令牌值（调用方决定用 ``primary`` 还是 ``text.tertiary``）。

    返回:
        ``QIcon``；名称未注册时回退到 ``_ICON_FALLBACK``，不抛异常。
    """
    try:
        return get_icon(name or _ICON_FALLBACK, size=_NAV_ICON_SIZE, color=color)
    except Exception:  # noqa: BLE001 - 图标缺失不应影响导航可用性
        return QIcon()


# ---------------------------------------------------------------------------
# 顶栏
# ---------------------------------------------------------------------------

class _BrandMark(QWidget):
    """品牌标识：主色圆角方块 + 白色字形「IX」。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.primary")))
        p.drawRoundedRect(self.rect(), T("radius.md"), T("radius.md"))

        f = QFont()
        f.setPixelSize(11)
        f.setWeight(QFont.Weight(QFont.Black))
        p.setFont(f)
        p.setPen(QPen(QColor(T("color.on.primary"))))
        p.drawText(self.rect(), Qt.AlignCenter, "IX")
        p.end()


class _VersionTag(QWidget):
    """版本胶囊：圆角 + 细边 + 版本号（GitHub release 标签样式）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        self._text = text if text is not None else __version__
        f = QFont()
        f.setPixelSize(T("font.sm"))
        fm = QFontMetricsF(f)
        self.setFixedSize(int(fm.horizontalAdvance(self._text)) + 22, 24)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(QColor(T("color.border"))))
        p.setBrush(QColor(T("color.bg.subtle")))
        p.drawRoundedRect(rect, T("radius.pill"), T("radius.pill"))

        f = QFont()
        f.setPixelSize(T("font.sm"))
        f.setWeight(QFont.Weight(T("font.weight.medium")))
        p.setFont(f)
        p.setPen(QPen(QColor(T("color.text.secondary"))))
        p.drawText(rect, Qt.AlignCenter, self._text)
        p.end()


# ---------------------------------------------------------------------------
# 侧边导航
# ---------------------------------------------------------------------------

class _NavItem(QWidget):
    """单个导航项：图标 + 文本，hover 底色与选中态左侧强调条（自绘）。

    视觉规则与 Kit 令牌对齐：
    - 行高 30px，圆角 ``radius.md``，左右内边距 10px；
    - hover：``bg.muted``；选中：``primary.subtle`` + 3px ``primary`` 左条 + 主色文字；
    - 文本单行省略，窄侧栏下不撑破布局。
    """

    clicked = Signal(object)

    def __init__(self, text: str, icon_name: str, page_key: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._icon_name = icon_name
        self._page_key = page_key
        self._active = False
        self._hover = False
        self._icon = None
        self._reload_icon()
        self.setFixedHeight(T("layout.nav.row_h"))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        ThemeManager.instance().theme_changed.connect(lambda *_: self._reload_icon())

    def _reload_icon(self) -> None:
        """按当前主题重绘图标（QIcon 像素里固化了颜色，需随主题重建）。"""
        color = T("color.primary") if self._active else T("color.text.tertiary")
        self._icon = _icon(self._icon_name, color)
        self.update()

    def set_active(self, active: bool) -> None:
        """切换选中态（同步刷新图标颜色）。"""
        if active == self._active:
            return
        self._active = active
        self._reload_icon()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._page_key)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = T("radius.md")

        if self._active:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T("color.primary.subtle")))
            p.drawRoundedRect(rect, radius, radius)
            # 左侧强调条：与卡片同圆角的短竖条
            bar = QRectF(rect.left() + 1, rect.top() + 6, 3, rect.height() - 12)
            p.setBrush(QColor(T("color.primary")))
            p.drawRoundedRect(bar, 1.5, 1.5)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T("color.bg.muted")))
            p.drawRoundedRect(rect, radius, radius)

        # 图标：统一边长，垂直居中，与文本基线对齐
        if self._icon is not None and not self._icon.isNull():
            s = _NAV_ICON_SIZE
            top = (self.height() - s) // 2
            self._icon.paint(p, T("layout.nav.pad_x"), top, s, s, Qt.AlignmentFlag.AlignCenter)

        # 文本
        f = QFont()
        f.setPixelSize(T("font.md"))
        weight = "semibold" if self._active else "regular"
        f.setWeight(QFont.Weight(T(f"font.weight.{weight}")))
        p.setFont(f)
        p.setPen(QPen(QColor(T("color.primary") if self._active else T("color.text.secondary"))))
        text_rect = self.rect().adjusted(_nav_text_x(), 0, -T("layout.nav.pad_x"), 0)
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(f).elidedText(self._text, Qt.TextElideMode.ElideRight,
                                               text_rect.width()))
        p.end()


class _CategoryLabel(QLabel):
    """分类小标题：三级文字色 + 语义化字重，弱化为分组标签。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        set_font(self, "font.sm", "semibold")
        set_property(self, "role", "tertiary")


#: 侧边栏纯中文标题用到的字的拼音（无外部依赖）。
#: 只收录 demo 导航里真实出现的字；未收录的字会回退到英文 page_key，
#: 所以往 NAV 里加新页面时不会因为缺字而报错，最多退化成按 key 排。
_PINYIN = {
    "顶": "ding", "部": "bu", "导": "dao", "航": "hang", "栏": "lan",
    "圣": "sheng", "杯": "bei", "布": "bu", "局": "ju", "卡": "ka",
    "片": "pian", "网": "wang", "格": "ge", "单": "dan", "列": "lie",
    "堆": "dui", "叠": "die", "侧": "ce", "边": "bian", "表": "biao",
    "详": "xiang", "情": "qing", "分": "fen", "面": "mian", "板": "ban",
    "仪": "yi", "盘": "pan", "英": "ying", "雄": "xiong", "区": "qu",
    "居": "ju", "中": "zhong", "容": "rong", "器": "qi", "瀑": "pu",
    "流": "liu", "图": "tu", "文": "wen", "左": "zuo", "右": "you",
    "式": "shi", "对": "dui", "话": "hua",
}


def _nav_sort_key(page):
    """侧边栏叶子项的排序键：按 A-Z 排，便于查找。

    三级回退，保证任何标题都能排出确定顺序：

    1. 标题以英文开头（``"Button 按钮"``、``"Cascader 级联选择"``）——
       取英文前缀。这段英文正是用户在侧边栏看到的字形，
       所以「看到的顺序」与「排序键」完全一致，不会出现视觉错位。
    2. 标题是纯中文（``"顶部导航栏"``）—— 逐字转拼音后按拼音排，
       这才是中文读者预期的字母序。
    3. 两者都取不到（中文且字不在对照表里）—— 回退到英文 page_key。
    """
    page_key, title = page[0], (page[1] or "")
    lead = re.match(r"[A-Za-z0-9][A-Za-z0-9 ._+-]*", title)
    if lead:
        return (0, lead.group(0).strip().lower(), title)
    if title:
        pinyin = "".join(_PINYIN.get(ch, "") for ch in title
                         if not ch.isspace() and ch not in "-·")
        if pinyin:
            return (1, pinyin, title)
    return (2, (page_key or "").lower(), title)


class _Sidebar(QWidget):
    """侧边导航容器：搜索框 + 分类导航列表（滚动）。"""

    #: 用户选中某个叶子页时发射，参数为 page_key（由 MainWindow 接管切换）
    navigate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        set_property(self, "role", "sidebar")
        self.setFixedWidth(T("layout.sidebar.w"))
        self._items = {}       # page_key -> _NavItem
        self._categories = []  # [(标签控件, [叶子控件])]
        self._ordered = []     # 全部叶子项，按 NAV 顺序
        self._hidden = set()   # 被搜索过滤隐藏的项 id

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_search())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        set_property(content, "role", "plain")
        self._list_layout = QVBoxLayout(content)
        pad = T("layout.nav.pad_x") + T("space.05")
        self._list_layout.setContentsMargins(pad, T("space.1"), pad, T("space.5"))
        self._list_layout.setSpacing(0)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        for cat_key, cat_title, pages in NAV:
            self._add_category(cat_key, cat_title, pages)
        self._list_layout.addStretch(1)

        self._empty = QLabel("没有匹配的页面")
        set_property(self._empty, "role", "tertiary")
        self._empty.setVisible(False)
        self._list_layout.insertWidget(0, self._empty)

    def _build_search(self) -> QWidget:
        """搜索框：带放大镜图标的圆角输入，实时过滤导航项。"""
        host = QWidget()
        set_property(host, "role", "plain")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(T("space.3"), T("space.3"), T("space.3"), T("space.2"))

        edit = QLineEdit()
        edit.setPlaceholderText("搜索组件 / 页面")
        edit.setClearButtonEnabled(True)
        # ClickFocus：避免成为窗口首个可聚焦控件而在启动时自动套上焦点环
        edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        set_property(edit, "size", "sm")
        edit.addAction(_icon("search", T("color.text.tertiary")),
                       QLineEdit.ActionPosition.LeadingPosition)
        edit.textChanged.connect(self._apply_filter)
        lay.addWidget(edit)
        self._search = edit
        ThemeManager.instance().theme_changed.connect(lambda *_: self._refresh_search_icon())
        return host

    def _refresh_search_icon(self) -> None:
        """主题切换后重绘搜索框放大镜（QIcon 固化了颜色）。"""
        self._search.actions()[0].setIcon(_icon("search", T("color.text.tertiary")))

    def _add_category(self, cat_key: str, cat_title: str, pages) -> None:
        """追加一个分类标题 + 其叶子导航项。"""
        cat_lab = _CategoryLabel(cat_title)
        top = 14 if self._categories else 2
        self._list_layout.addSpacing(top)
        self._list_layout.addWidget(cat_lab)
        self._list_layout.addSpacing(6)

        items = []
        for page_key, page_title, _factory in sorted(pages, key=_nav_sort_key):
            item = _NavItem(page_title, _CATEGORY_ICONS.get(cat_key, "component"), page_key)
            item.clicked.connect(self._on_item_clicked)
            self._list_layout.addWidget(item)
            self._items[page_key] = item
            self._ordered.append(item)
            items.append(item)
        self._categories.append((cat_lab, items))

    def _apply_filter(self, text: str) -> None:
        """按关键词过滤：命中叶子项或分类名时显示所属分类，否则隐藏。"""
        kw = text.strip().lower()
        hit_any = False
        hidden = set()
        for cat_lab, items in self._categories:
            cat_text = cat_lab.text().lower()
            cat_hit = bool(kw) and kw in cat_text
            visible_items = [i for i in items
                             if (not kw) or cat_hit or kw in i._text.lower()]
            for it in items:
                it.setVisible(it in visible_items)
                if it not in visible_items:
                    hidden.add(id(it))
            show_cat = bool(visible_items)
            cat_lab.setVisible(show_cat)
            hit_any = hit_any or show_cat
        self._empty.setVisible(bool(kw) and not hit_any)
        # 由过滤结果直接推导隐藏集合，不能用 isVisible() 反推：窗口 show 之前
        # 所有控件的 isVisible() 恒为 False，会把全部项误判为隐藏。
        self._hidden = hidden

    def _on_item_clicked(self, page_key: str) -> None:
        """导航项点击 -> 发信号给主窗口（不向上找父级，避免耦合窗口层级）。"""
        self.navigate_requested.emit(page_key)

    def set_active(self, page_key: str) -> None:
        """高亮指定页面（其余项复位）。"""
        for key, item in self._items.items():
            item.set_active(key == page_key)

    def select_first(self) -> None:
        """选中第一个未被搜索过滤掉的叶子项（构造后初始化用）。

        注意不能用 ``isVisible()`` 判断：构造期窗口尚未 show，所有控件的
        isVisible() 都是 False，会导致启动时一个页都选不中。
        """
        for it in self._ordered:
            if id(it) not in self._hidden:
                self.navigate_requested.emit(it._page_key)
                return


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Demo 主窗口（1440x900）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("InstructionX_UIKit · Demo")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)
        self._page_cache = {}   # page_key -> QWidget
        self._syncing = False   # 主题切换控件同步防抖
        self._current = None    # 当前 page_key

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())

        body = QWidget()
        set_property(body, "role", "plain")
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        self._sidebar = _Sidebar()
        # 必须在 select_first() 之前连接：初始化时侧栏会主动发一次导航请求
        self._sidebar.navigate_requested.connect(self.navigate)
        body_lay.addWidget(self._sidebar)

        self._stack_host = QWidget()
        set_property(self._stack_host, "role", "canvas")
        stack_lay = QVBoxLayout(self._stack_host)
        stack_lay.setContentsMargins(0, 0, 0, 0)
        stack_lay.setSpacing(0)
        self._stack = _Stacked()
        stack_lay.addWidget(self._stack)
        body_lay.addWidget(self._stack_host, 1)
        root.addWidget(body, 1)

        # 预热蓝图页：蓝图 GL 视口基于 QOpenGLWidget，若在顶层窗口可见之后
        # 才加入窗口树，Qt 会重建顶层原生窗口句柄（表现为窗口短暂关闭重开）。
        # 在 show() 之前的构造阶段创建蓝图页即可规避（USAGE.md §8.6）。
        self._prewarm_page("blueprint")
        # 同理预热图表页：图表绘制视口在 GL 可用时也是 QOpenGLWidget
        # （charts/viewport.py），首个图表控件若在窗口可见后才创建同样会
        # 触发句柄重建。全页 27 个 ChartWidget 会一次性建好（惰性页缓存）。
        self._prewarm_page("charts")

        # 默认选中第一页
        self._sidebar.select_first()

    # -- 顶栏 ---------------------------------------------------------------
    def _build_topbar(self) -> QWidget:
        """品牌顶栏：标识 + 名称 + 副标题 …… 主题切换 + 版本胶囊。"""
        bar = QWidget()
        set_property(bar, "role", "topbar")
        bar.setFixedHeight(T("layout.topbar.h"))
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(T("layout.page.pad"), 0, T("space.3"), 0)
        lay.setSpacing(T("space.2"))

        lay.addWidget(_BrandMark())

        name = QLabel("InstructionX UIKit")
        set_font(name, "font.title.md", "bold")
        lay.addWidget(name)

        subtitle = QLabel("设计系统 · 组件库 · 布局库 · 动画库")
        set_property(subtitle, "role", "tertiary")
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

    # -- 页面切换 -----------------------------------------------------------
    def _prewarm_page(self, page_key: str) -> bool:
        """在窗口显示前预创建指定导航页（不改变当前选中页）。"""
        for cat_key, _cat_title, pages in NAV:
            for key, _title, factory in pages:
                if key == page_key:
                    self._load_page(key, factory)
                    return True
        return False

    def navigate(self, page_key: str) -> None:
        """按页面键切换页面（侧栏点击 / 初始化共用）。"""
        for _cat_key, _cat_title, pages in NAV:
            for key, _title, factory in pages:
                if key == page_key:
                    self.show_page(key, factory)
                    return

    def show_page(self, page_key: str, factory):
        """懒加载并切换到指定演示页（公开，供测试遍历调用）。"""
        page = self._load_page(page_key, factory)
        self._stack.setCurrentWidget(page)
        self._current = page_key
        self._sidebar.set_active(page_key)

    def _load_page(self, page_key: str, factory) -> QWidget:
        """首次访问时创建并缓存页面。"""
        if page_key not in self._page_cache:
            page = factory()
            self._page_cache[page_key] = page
            self._stack.addWidget(page)
        return self._page_cache[page_key]

    # -- 供测试使用的导航访问 ----------------------------------------------
    def nav_leaves(self):
        """返回 [(page_key, page_title, item)]，覆盖导航全部叶子页。"""
        leaves = []
        for _cat_key, _cat_title, pages in NAV:
            for key, title, _factory in pages:
                item = self._sidebar._items.get(key)
                if item is not None:
                    leaves.append((key, title, item))
        return leaves

    def select_leaf(self, item):
        """选中指定导航项（测试遍历用，兼容旧版 tree_item 入参）。"""
        self.navigate(item._page_key)


class _Stacked(QWidget):
    """极简页面栈：只做 show/hide，避免 QStackedWidget 默认页的底色残留。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._pages = []
        self._current = None

    def addWidget(self, widget):  # noqa: N802 - 兼容 QStackedWidget 接口
        widget.setParent(self)
        self._lay.addWidget(widget)
        self._pages.append(widget)
        widget.setVisible(widget is self._current)
        return widget

    def setCurrentWidget(self, widget):  # noqa: N802
        for page in self._pages:
            page.setVisible(page is widget)
        self._current = widget
