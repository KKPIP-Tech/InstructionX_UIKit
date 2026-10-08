# -*- coding: utf-8 -*-
"""基础控件全家福：经全局 QSS 美化后的 Qt 原生控件总览。

覆盖按钮 / 输入 / 数字日期 / 下拉 / 滑块表盘 / 进度数码 / 文本显示 /
容器 / 数据视图 / 窗口部件，以及标准对话框（QMessageBox / QFileDialog /
QColorDialog / QFontDialog / QInputDialog）的触发按钮。亮 / 暗主题自动换肤。
"""

import math

from PySide6.QtCore import Qt, QDate, QTime, QDateTime, QLocale, QRectF
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCalendarWidget,
    QColorDialog,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDial,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFontDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QKeySequenceEdit,
    QLCDNumber,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QTimeEdit,
    QToolBar,
    QToolBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFont, QPainter, QPen

from InstructionX_UIKit.charts._utils import draw_arc
from InstructionX_UIKit.theme import T, set_property

from .common import Section, col, hint_label, make_page, row

__all__ = ["create_page"]


class _FlatDial(QDial):
    """扁平表盘。

    QSS 够不着 QDial：Qt 没有给它暴露任何可样式的子控件（无 ``::indicator``
    之类），裸 QDial 会退回 Fusion 原生绘制 —— 3D 径向渐变、硬黑描边、
    底部投影、纯灰指示点，和整套扁平令牌体系完全无关。

    这里自绘，把语言对齐到 Slider：中性凹面 + 灰色轨道 + 主色进度弧 +
    主色环指示点 + 居中数值。

    **必须连鼠标处理一起接管。** 只覆写 ``paintEvent`` 是不够的：QDial
    自带的「角度 → 数值」映射和这里画的弧带根本不是一套 —— 实测原生
    QDial 的最小值落在 ~112°、最大值落在 ~75°，跨度约 323°；而本组件用
    的是 225° 起顺时针 270°。两套映射各走各的，拖动时数值按 Qt 的规则跳、
    圆环按本组件的规则画，圆环完全跟不住光标（实测 13 个采样角度全部
    错位，最大偏差 161.9°）。所以 ``mousePress/Move/Release`` 一并覆写，
    让取值和绘制共用同一套角度换算，从根子上杜绝两者跑偏。
    """

    #: 弧带宽度，与 Slider 的 lg 槽宽一致
    _TRACK = 6
    #: 指示点直径，与 Slider 的 lg 手柄一致
    _KNOB = 10
    #: 指示点描边宽度
    _KNOB_RING = 2
    #: 弧带起点。Qt 画弧约定下角度自 3 点钟起、逆时针为正、Y 轴向下，
    #: 因此**角度递增 = 屏幕上顺时针**。135° 落在屏幕 7:30（左下），
    #: 正是常规表盘的最小值位；扫 270° 后落在 4:30（右下），
    #: 缺口自然留在正下方。早先取 225° 起点，缺口跑到了正上方。
    _START = 135.0
    #: 弧带跨度，底部留 90° 缺口
    _SPAN = 270.0
    #: 凹面到控件边缘的留白
    _INSET = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        # 本组件的弧带有缺口，不做首尾相接，交给自己的角度换算
        self.setWrapping(False)
        self.setNotchesVisible(False)
        self.setRange(0, 100)

    # -- 角度换算：绘制与取值共用这一对互逆函数 ----------------------------
    # 画和动必须同源。QDial 自带的「角度 → 数值」映射与这里画的弧带不是
    # 一套（实测原生最小值在 ~112°、最大值在 ~75°，跨度约 323°），
    # 所以下面三个鼠标回调全部接管，不让 Qt 的映射掺进来。

    def _angle_for(self, frac: float) -> float:
        """进度 0~1 → Qt 画弧角度。"""
        return self._START + self._SPAN * frac

    def _frac_for(self, angle: float) -> float:
        """Qt 画弧角度 → 进度 0~1。缺口区按就近端点吸附。"""
        off = (angle - self._START) % 360.0
        if off > self._SPAN:
            gap = 360.0 - self._SPAN
            return 0.0 if off - self._SPAN <= gap / 2 else 1.0
        return off / self._SPAN

    def _angle_at(self, pos) -> float:
        """控件坐标 → Qt 画弧约定的角度。"""
        c = self.rect().center()
        return math.degrees(
            math.atan2(pos.y() - c.y(), pos.x() - c.x())) % 360.0

    def _value_at(self, pos) -> int:
        """控件坐标 → 数值，按 singleStep 对齐。"""
        rng = max(1, self.maximum() - self.minimum())
        step = self.singleStep() or 1
        raw = self.minimum() + self._frac_for(self._angle_at(pos)) * rng
        val = self.minimum() + round((raw - self.minimum()) / step) * step
        return max(self.minimum(), min(self.maximum(), val))

    # -- 接管鼠标：与 paintEvent 共用 _START / _SPAN ------------------------

    def mousePressEvent(self, event):  # noqa: N802 - Qt 回调
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.setValue(self._value_at(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt 回调
        if self._dragging:
            self.setValue(self._value_at(event.position().toPoint()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt 回调
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802 - Qt 回调
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height())
        m = self._INSET
        box = QRectF(m, m, side - 2 * m, side - 2 * m)
        # 描边以路径为中心向两侧各扩 _TRACK/2，所以弧带的中心线
        # 落在 inner 上，而不是 box 上 —— 指示点必须用这个半径。
        inner = box.adjusted(self._TRACK / 2, self._TRACK / 2,
                             -self._TRACK / 2, -self._TRACK / 2)
        r_band = inner.width() / 2

        # 凹面
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.bg.muted")))
        p.drawEllipse(box)

        # 未填充轨道。这里不能用 bg.elevated：亮色下它与卡片底色 bg.base
        # 同为 #FFFFFF，暗色下又比凹面 bg.muted 更暗，两个主题方向相反，
        # 回拨时轨道既不与凹面区分也不与背景区分。border.strong 在两个
        # 主题里都是中灰，与凹面、卡片底色都拉得开。
        draw_arc(p, inner, self._START, self._SPAN,
                 QPen(QColor(T("color.border.strong")), self._TRACK,
                      Qt.SolidLine, Qt.FlatCap))

        # 进度弧
        rng = max(1, self.maximum() - self.minimum())
        frac = min(1.0, max(0.0, (self.value() - self.minimum()) / rng))
        if frac > 0:
            draw_arc(p, inner, self._START, self._SPAN * frac,
                     QPen(QColor(T("color.primary")), self._TRACK,
                          Qt.SolidLine, Qt.FlatCap))

        # 居中数值
        p.setPen(QColor(T("color.text.primary")))
        p.drawText(box, Qt.AlignCenter, str(self.value()))

        # 指示点。角度一律来自 _angle_for()，不自己另算一套。
        ang = math.radians(self._angle_for(frac))
        c = box.center()
        kx = c.x() + math.cos(ang) * r_band
        ky = c.y() + math.sin(ang) * r_band
        # 圆环填主色、描边用凹面色：圆环坐在**亮蓝弧**末端，不是滑块那种灰槽上。
        # 试过「白/近黑填充 + 主色描边」——亮色好看，但暗色下 on.primary 近黑、
        # bg.elevated 深灰，压在亮蓝弧上读起来像弧被挖了个洞。
        # 反过来「主色填充 + 凹面描边」在两个主题下都读作弧上的一个节点。
        p.setPen(QPen(QColor(T("color.bg.muted")), self._KNOB_RING))
        p.setBrush(QColor(T("color.primary")))
        p.drawEllipse(QRectF(kx - self._KNOB / 2, ky - self._KNOB / 2,
                             self._KNOB, self._KNOB))
        p.end()


def _buttons_section():
    box = Section("按钮（QPushButton / QToolButton）")
    box.layout().addWidget(row(
        QPushButton("默认按钮"),
        _v("主要按钮", "primary"),
        _v("危险按钮", "danger"),
        _v("禁用按钮", None, False)))
    tb1 = QToolButton(); tb1.setText("工具按钮")
    tb2 = QToolButton(); tb2.setText("带菜单")
    tb2.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    # 默认 QToolButton 是无边框工具型（仅 hover 显形）；演示页给 default 变体，
    # 让它与上方 QPushButton 行形成可比的按钮外观。
    set_property(tb1, "variant", "default")
    set_property(tb2, "variant", "default")
    # 显式挂 md 档：QToolButton 走内容自适应高度（实测 32px），
    # 与同区块 QPushButton 的 28px 不齐；统一档位后两行按钮同高。
    set_property(tb1, "size", "md")
    set_property(tb2, "size", "md")
    # 菜单按钮占 20px，按钮太窄时文字会被压到下拉箭头下面
    tb2.setMinimumWidth(112)
    box.layout().addWidget(row(tb1, tb2))
    return box


def _v(text, variant, enabled=True):
    b = QPushButton(text)
    if variant:
        set_property(b, "variant", variant)
    b.setEnabled(enabled)
    return b


def _text_inputs_section():
    box = Section("文本输入（QLineEdit / QTextEdit / QPlainTextEdit）")
    le = QLineEdit("单行输入框")
    le.setMinimumWidth(200)
    box.layout().addWidget(row(le, QLineEdit("placeholder 占位")))
    te = QTextEdit("QTextEdit 富文本编辑：支持 <b>加粗</b> 与 <i>斜体</i>。")
    te.setFixedHeight(90)
    pe = QPlainTextEdit("QPlainTextEdit 纯文本编辑：\n第二行内容。")
    pe.setFixedHeight(90)
    box.layout().addWidget(row(te, pe))
    return box


def _number_date_section():
    box = Section("数字 / 日期时间（QSpinBox / QDoubleSpinBox / QDate* / QKeySequenceEdit）")
    kse = QKeySequenceEdit()
    # QKeySequenceEdit 既没有 setPlaceholderText() 也没有 lineEdit()，
    # 占位符只能落到它内部的 QLineEdit 上（对象名 qt_keysequenceedit_lineedit）。
    # 不这么设的话 Qt 会画自己的英文 "Press shortcut"，和整页中文排版不一致。
    _kse_edit = kse.findChild(QLineEdit)
    if _kse_edit is not None:
        _kse_edit.setPlaceholderText("按快捷键…")
    box.layout().addWidget(row(
        QSpinBox(value=42), QDoubleSpinBox(value=3.14), kse))
    # 原生控件默认走 Qt 的 M/d/yy 格式，中文界面里显示成 "6 10 2026"，
    # 与页面上其它日期文案完全不是一个语言，显式指定为 ISO 顺序。
    d_e = QDateEdit(QDate.currentDate())
    d_e.setDisplayFormat("yyyy-MM-dd")
    t_e = QTimeEdit(QTime.currentTime())
    t_e.setDisplayFormat("HH:mm")
    dt_e = QDateTimeEdit(QDateTime.currentDateTime())
    dt_e.setDisplayFormat("yyyy-MM-dd HH:mm")
    box.layout().addWidget(row(d_e, t_e, dt_e))
    return box


def _combo_section():
    box = Section("下拉选择（QComboBox / QFontComboBox）")
    cb = QComboBox()
    cb.addItems(["选项一", "选项二", "选项三"])
    fcb = QFontComboBox()
    fcb.setMinimumWidth(200)
    box.layout().addWidget(row(cb, fcb))
    return box


def _slider_dial_section():
    box = Section("滑块 / 表盘 / 进度 / 数码（QSlider / QDial / QProgressBar / QLCDNumber）")
    sl = QSlider(Qt.Horizontal, value=55)
    sl.setMinimumWidth(240)
    dial = _FlatDial()
    dial.setValue(40)
    box.layout().addWidget(row(sl, dial))
    pb = QProgressBar(value=65)
    pb.setMinimumWidth(240)
    pb.setFormat("%p%")
    lcd = QLCDNumber()
    lcd.display("1234")
    lcd.setFixedHeight(60)
    box.layout().addWidget(row(pb, lcd))
    return box


def _display_section():
    box = Section("文本显示 / 日历（QTextBrowser / QCalendarWidget）")
    tb = QTextBrowser()
    tb.setHtml("<h4>QTextBrowser</h4><p>只读富文本浏览器，支持链接与锚点。</p>"
               "<ul><li>项目一</li><li>项目二</li></ul>")
    tb.setFixedHeight(180)
    tb.setMinimumWidth(300)
    cal = QCalendarWidget()
    # 日历默认走 Qt 的系统区域设置，月份与星期会渲染成 "October" / "Mon"。
    # 整页是中文排版，这里显式指定中文区域，避免语言混杂。
    cal.setLocale(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    cal.setFixedSize(360, 260)
    box.layout().addWidget(row(tb, cal))
    return box


def _container_section():
    box = Section("容器（QGroupBox / QTabWidget / QToolBox）")
    gb = QGroupBox("分组框")
    gl = QVBoxLayout(gb)
    gl.addWidget(QLabel("QGroupBox 内的内容"))
    gl.addWidget(QPushButton("按钮"))
    tabs = QTabWidget()
    for name in ("标签一", "标签二", "标签三"):
        tabs.addTab(QLabel(f"{name} 内容", alignment=Qt.AlignCenter), name)
    tabs.setFixedHeight(150)
    toolbox = QToolBox()
    toolbox.addItem(QLabel("抽屉一内容", alignment=Qt.AlignCenter), "抽屉一")
    toolbox.addItem(QLabel("抽屉二内容", alignment=Qt.AlignCenter), "抽屉二")
    toolbox.setFixedHeight(150)
    # 竖排 QToolBox 的工具按钮列右缘是 Qt 原生斜切（QSS 改不掉）。
    # 给足宽度让斜边落在边框位置，看起来像刻意的收口而不是渲染破口。
    toolbox.setFixedWidth(208)
    box.layout().addWidget(row(gb, tabs, toolbox))
    return box


def _views_section():
    box = Section("数据视图（QListWidget / QTreeWidget / QTableWidget）")
    lw = QListWidget()
    lw.addItems(["列表项 一", "列表项 二", "列表项 三", "列表项 四"])
    lw.setCurrentRow(1)
    tree = QTreeWidget()
    tree.setHeaderLabels(["名称", "值"])
    for i in range(3):
        it = QTreeWidgetItem([f"节点 {i + 1}", str(i)])
        it.addChild(QTreeWidgetItem([f"子节点 {i + 1}.1", "x"]))
        tree.addTopLevelItem(it)
    tree.expandAll()
    # 首列默认按内容均分，"子节点 1.1" 被挤成 "子…"。给首列明确宽度。
    tree.setColumnWidth(0, 132)
    table = QTableWidget(3, 3)
    table.setHorizontalHeaderLabels(["列一", "列二", "列三"])
    for r in range(3):
        for c in range(3):
            table.setItem(r, c, QTableWidgetItem(f"{r + 1},{c + 1}"))
    # 行号表头会挤走一列宽度，3 列内容放不下时还会冒出横竖滚动条
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    # 树的首列必须用显式宽度：Stretch 会把它均分给两列，
    # "子节点 1.1" 仍会被挤成 "子节…"
    tree.header().setSectionResizeMode(QHeaderView.Interactive)
    tree.setColumnWidth(0, 132)
    for w in (lw, tree, table):
        w.setFixedSize(240, 190)
    # 树有 3 组父子共 6 行 + 表头，190px 装不下，最后一行会被切掉并冒出滚动条
    tree.setFixedHeight(232)
    box.layout().addWidget(row(lw, tree, table))
    return box


def _window_parts_section():
    box = Section("窗口部件（QMenuBar / QToolBar / QStatusBar）")
    win = QMainWindow()
    mb = win.menuBar()
    m_file = mb.addMenu("文件")
    m_file.addAction("新建")
    m_file.addAction("打开")
    m_edit = mb.addMenu("编辑")
    m_edit.addAction("撤销")
    tb = QToolBar("主工具栏")
    tb.addAction(QAction("新建", win))
    tb.addAction(QAction("保存", win))
    tb.addSeparator()
    tb.addAction(QAction("帮助", win))
    win.addToolBar(tb)
    win.setCentralWidget(QLabel("中央内容区", alignment=Qt.AlignCenter))
    sb = QStatusBar()
    # 右下角点状抓手由 QStatusBar 自己绘制，QSS 压不住，直接用 API 关掉
    sb.setSizeGripEnabled(False)
    sb.showMessage("就绪")
    win.setStatusBar(sb)
    win.setFixedHeight(240)
    box.layout().addWidget(win)
    return box


def _dialogs_section(page):
    box = Section("标准对话框（点击触发）")

    def _msg():
        QMessageBox.information(page, "QMessageBox", "这是 QMessageBox 信息对话框。")

    def _file():
        QFileDialog.getOpenFileName(page, "QFileDialog 选择文件")

    def _color():
        QColorDialog.getColor(QColor("#3F5E8C"), page, "QColorDialog 选择颜色")

    def _font():
        QFontDialog.getFont(page, "QFontDialog 选择字体")

    def _input():
        QInputDialog.getText(page, "QInputDialog", "请输入文本：")

    btns = []
    for text, fn in (("QMessageBox", _msg), ("QFileDialog", _file),
                     ("QColorDialog", _color), ("QFontDialog", _font),
                     ("QInputDialog", _input)):
        b = QPushButton(text)
        b.clicked.connect(fn)
        btns.append(b)
    box.layout().addWidget(row(*btns))
    box.layout().addWidget(hint_label("点击按钮弹出对应的标准对话框。", role="tertiary"))
    return box


def create_page() -> QWidget:
    page_placeholder = QWidget()  # 仅用于对话框 parent 占位（运行时为窗口）
    sections = [
        _buttons_section(),
        _text_inputs_section(),
        _number_date_section(),
        _combo_section(),
        _slider_dial_section(),
        _display_section(),
        _container_section(),
        _views_section(),
        _window_parts_section(),
    ]
    page = make_page(
        "基础控件",
        "Qt 原生控件在全局 QSS 美化下的全家福：按钮、输入、数字日期、下拉、滑块表盘、"
        "进度数码、文本显示、容器、数据视图与窗口部件，以及标准对话框触发。",
        sections)
    # 对话框 section 需要页面作为 parent，最后追加
    content = page.widget()
    content.layout().insertWidget(
        content.layout().count() - 1, _dialogs_section(content))
    page_placeholder.deleteLater()
    return page
