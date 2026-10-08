# -*- coding: utf-8 -*-
"""日历组件（SPEC §5.2 calendar）。

中文表头（周一为一周起点）、今日以主色圆角标记、选中态为实心主色；
全部单元格由组件自绘：周一起始的表头带 + 日期网格。

本轮修复（轨道 2）：

- **周末不再刺眼的纯红**：``QCalendarWidget`` 的默认代理把周末的表头与日期
  硬编码为 ``Qt::red``（与整套主题色板冲突，暗色主题下尤其刺眼）。组件安装
  自己的单元格代理：表头带按 ``text.tertiary`` 着色（透明底，避免与导航栏
  的 ``bg.subtle`` 叠成两条灰带）；日期格交回 ``paintCell`` 自绘，周末降为
  ``text.secondary``、跨月降为 ``text.tertiary``（均 ≥ 3:1，契约 §5），
  不再有硬编码色值。
- **网格右缘齐平**：7 列改 ``Stretch`` 均分宽度（原按内容算出的
  46/46/46/46/46/45/45 末两列各窄 1px，控件拉宽后右侧还留一条空白）。
- **减法**：单元格只保留「选中 / 今日」两处底色，其余一律由组件铺 ``bg.base``
  底、不叠边框与装饰层（契约 §4）；``framed=True``（``DatePicker`` 弹层用）
  为浮层补 1px 边框 + ``radius.lg``，让浮层边界可见。
"""

from PySide6.QtCore import QDate, QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHeaderView, QStyledItemDelegate, QTableView, QCalendarWidget,
)

from InstructionX_UIKit.theme import T, ThemeManager
from InstructionX_UIKit.tokens import TokenState

__all__ = ["Calendar"]

#: 表头带 / 日期数字的字阶（令牌键，避免在绘制代码里散落字面量字号）
_FONT_SCALE = {"header": "sm", "day": "md"}

#: 字重令牌（CSS 数值 400/500/600/700）→ Qt 枚举。
#: QSS 可以直接写 ``font-weight: 500``，QFont.setWeight() 只认 Qt 枚举，
#: 自绘路径必须显式换算，否则 Python 侧直接传 int 会抛 TypeError。
_FONT_WEIGHT = {
    "regular": QFont.Weight.Normal,
    "medium": QFont.Weight.Medium,
    "semibold": QFont.Weight.DemiBold,
    "bold": QFont.Weight.Bold,
}


def _token_font(base: QFont, scale: str, weight: str = "regular") -> QFont:
    """按字阶 / 字重令牌派生 QFont（自绘路径不经过 QSS，故直接用令牌）。"""
    font = QFont(base)
    font.setPixelSize(int(T(f"font.{scale}")))
    font.setWeight(_FONT_WEIGHT[weight])
    return font


class _CellDelegate(QStyledItemDelegate):
    """日历单元格代理：接管表头带绘制，日期格转交 ``Calendar.paintCell``。

    网格第 0 行是「周一起始的表头带」（属于视图模型的一部分，不是
    ``QHeaderView``），默认代理按模型里写死的 ``Qt::red`` 画周末，与主题
    色板冲突；这里改为按令牌着色。其余 42 个日期格交回组件的
    ``paintCell``——那里有 ``QDate``，才能精确区分今天 / 选中 / 跨月。
    """

    def __init__(self, calendar: "Calendar", parent=None):
        super().__init__(parent)
        self._calendar = calendar

    def paint(self, painter, option, index) -> None:
        if index.row() == 0:
            self._paint_header_band(painter, option.rect, str(index.data()))
            return
        self._calendar.paintCell(painter, option.rect,
                                 self._calendar.date_at(index.row(),
                                                        index.column()))

    def _paint_header_band(self, painter, rect, text: str) -> None:
        """表头带：透明底 + text.tertiary 文案（周末不再标红）。

        不铺底色：导航栏本身已是 ``bg.subtle`` 底，两条相邻灰带叠在一起
        反而显重（契约 §4 减法优先）；表头文字对 ``bg.base`` 的对比度
        3.41:1 / 4.14:1，达装饰性文字 3:1 下限。
        """
        painter.save()
        painter.setFont(_token_font(painter.font(), _FONT_SCALE["header"]))
        painter.setPen(QColor(T("color.text.tertiary")))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class Calendar(QCalendarWidget):
    """中文日历。

    参数:
        parent: 父控件。
        framed: 是否作为**浮层**渲染（补 1px 边框 + ``radius.lg`` 圆角）。
            页面内嵌用法缺省 False（由所在卡片提供边界），``DatePicker``
            的弹层传 True。

    示例::

        cal = Calendar()
        cal.setSelectedDate(QDate.currentDate())
        cal.clicked.connect(lambda d: print(d.toString("yyyy-MM-dd")))

    备注:
        日期格绘制完全自绘（``paintCell``），颜色 / 圆角 / 字阶全部取令牌：
        选中 = ``primary`` 底 + ``on.primary`` 字；今日 = ``primary.subtle`` 底 +
        ``primary`` 描边与字；周末 = ``text.secondary``；跨月 = ``text.tertiary``。
    """

    def __init__(self, parent=None, framed: bool = False):
        super().__init__(parent)
        self.setLocale(QLocale(QLocale.Chinese, QLocale.China))
        self.setFirstDayOfWeek(Qt.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.setGridVisible(False)
        # 跟踪当前显示页：自绘单元格需要知道「哪一天属于跨月」
        today = QDate.currentDate()
        self._page = (today.year(), today.month())
        self.currentPageChanged.connect(self._on_page_changed)
        if framed:
            # 浮层边界：浮层必须有边框与圆角，否则只是一块白底色块
            self.setStyleSheet(
                f"{type(self).__name__} {{"
                f" border: 1px solid {T('color.border')};"
                f" border-radius: {int(T('radius.lg'))}px; }}")
        self._install_view()
        ThemeManager.instance().theme_changed.connect(self.updateCells)
        # set_token 会话覆盖时重绘（QSS 不感知令牌覆盖，自绘需监听）
        TokenState.instance().token_changed.connect(self.updateCells)

    # ------------------------------------------------------------------
    # 内部视图：行高 / 列宽 / 绘制代理
    # ------------------------------------------------------------------

    def _install_view(self) -> None:
        """接管内部网格：7 列均分宽度 + 表头带 / 日期格自绘。

        列宽改 ``Stretch``：默认是按内容算的固定列宽（实测 46/46/46/46/
        46/45/45），末两列各窄 1px，控件被拉宽时右侧还会留出一条空白，
        右缘对不齐。行高**不**在这里设——``QCalendarView`` 会把行高均摊到
        控件高度上（``setDefaultSectionSize`` 无效，实测两种写法行高完全
        相同），因此只调列宽这一项真正起作用。

        ``qt_calendar_calendarview`` 是 Qt 内部视图的固定 objectName
        （Qt5 / Qt6 一致），取不到时保持默认外观，不抛异常。
        """
        view = self.findChild(QTableView, "qt_calendar_calendarview")
        if view is None:
            return
        view.setItemDelegate(_CellDelegate(self, view))
        view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _on_page_changed(self, year: int, month: int) -> None:
        self._page = (int(year), int(month))

    def date_at(self, row: int, column: int) -> QDate:
        """网格坐标 → ``QDate``（行 0 为表头带，日期从第 1 行开始）。

        QCalendarWidget 的月视图固定为「含当月 1 号的那一周起、每周一起、
        逐日推进」的 6 × 7 布局；跨月判定也依赖该布局，故与视图模型共用
        同一套推导。
        """
        year, month = self._page
        first = QDate(year, month, 1)
        offset = (first.dayOfWeek() - self.firstDayOfWeek().value) % 7
        return first.addDays(-offset + (row - 1) * 7 + column)

    # ------------------------------------------------------------------
    # 单元格绘制
    # ------------------------------------------------------------------

    def paintCell(self, painter, rect, date) -> None:
        """自绘单个日期格：仅「选中 / 今日」铺底色，其余透明（契约 §4 减法）。"""
        today = QDate.currentDate()
        selected = date == self.selectedDate()
        is_today = date == today
        weekend = date.dayOfWeek() in (Qt.Saturday, Qt.Sunday)
        outside = (date.year(), date.month()) != self._page

        inset = int(T("space.05"))
        cell = rect.adjusted(inset, inset, -inset, -inset)
        radius = float(T("radius.sm"))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        # 先铺满底色：QTableView 会为「当前索引格」（键盘光标）额外画一层
        # primary.subtle 高亮（全局 QTableView::item:selected 规则），不铺底
        # 就会在与选中无关的格子上留下一块浅色方块
        painter.fillRect(rect, QColor(T("color.bg.base")))
        if selected:
            bg, fg = T("color.primary"), T("color.on.primary")
        elif is_today:
            bg, fg = T("color.primary.subtle"), T("color.primary")
        else:
            bg = None
            if outside:
                fg = T("color.text.tertiary")
            elif weekend:
                fg = T("color.text.secondary")
            else:
                fg = T("color.text.primary")
        if bg is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(cell, radius, radius)
        if is_today and not selected:
            # 1px 描边：QSS 边框为 1px，绘制时内缩半像素才是真正 1px（光学补偿）
            ring = QRectF(cell).adjusted(0.5, 0.5, -0.5, -0.5)
            pen = QPen(QColor(T("color.primary")))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(ring, radius, radius)
        painter.setFont(_token_font(painter.font(), _FONT_SCALE["day"],
                                    "medium" if (selected or is_today)
                                    else "regular"))
        painter.setPen(QColor(fg))
        painter.drawText(cell, Qt.AlignCenter, str(date.day()))
        painter.restore()
