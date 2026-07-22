# -*- coding: utf-8 -*-
"""基础控件全家福：经全局 QSS 美化后的 Qt 原生控件总览。

覆盖按钮 / 输入 / 数字日期 / 下拉 / 滑块表盘 / 进度数码 / 文本显示 /
容器 / 数据视图 / 窗口部件，以及标准对话框（QMessageBox / QFileDialog /
QColorDialog / QFontDialog / QInputDialog）的触发按钮。亮 / 暗主题自动换肤。
"""

from PySide6.QtCore import Qt, QDate, QTime, QDateTime
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
from PySide6.QtGui import QFont

from InstructionX_UIKit.theme import set_property

from .common import Section, col, hint_label, make_page, row

__all__ = ["create_page"]


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
    box.layout().addWidget(row(
        QSpinBox(value=42), QDoubleSpinBox(value=3.14),
        QKeySequenceEdit()))
    box.layout().addWidget(row(
        QDateEdit(QDate.currentDate()),
        QTimeEdit(QTime.currentTime()),
        QDateTimeEdit(QDateTime.currentDateTime())))
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
    dial = QDial(value=40)
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
    table = QTableWidget(3, 3)
    table.setHorizontalHeaderLabels(["列一", "列二", "列三"])
    for r in range(3):
        for c in range(3):
            table.setItem(r, c, QTableWidgetItem(f"{r + 1},{c + 1}"))
    for w in (lw, tree, table):
        w.setFixedSize(240, 190)
    box.layout().addWidget(row(lw, tree, table))
    return box


def _window_parts_section():
    box = Section("窗口部件（QMenuBar / QToolBar / QStatusBar）")
    win = QMainWindow()
    mb = win.menuBar()
    m_file = mb.addMenu("文件(&F)")
    m_file.addAction("新建")
    m_file.addAction("打开")
    m_edit = mb.addMenu("编辑(&E)")
    m_edit.addAction("撤销")
    tb = QToolBar("主工具栏")
    tb.addAction(QAction("新建", win))
    tb.addAction(QAction("保存", win))
    tb.addSeparator()
    tb.addAction(QAction("帮助", win))
    win.addToolBar(tb)
    win.setCentralWidget(QLabel("中央内容区", alignment=Qt.AlignCenter))
    sb = QStatusBar()
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
