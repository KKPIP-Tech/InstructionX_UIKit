# -*- coding: utf-8 -*-
"""CodeEditor 主控件（CE_SPEC §2）。

架构：``CodeEditor(QWidget)`` 组合

- ``Gutter``：行号槽（行号 / 断点 / 折叠箭头 / 诊断着色条）；
- ``_TextArea(QPlainTextEdit)``：文本区，自绘缩进参考线与行尾空白叠加层；
  括号层级着色走 ``RegionManager`` 的 ExtraSelections 前景色层（不重绘字形，
  避免抗锯齿重影）；等宽字体，tab_size 按字体度量换算；
- ``MiniMap``：小地图；
- ``FindReplaceBar`` / ``CompletionPopup`` / ``HoverBubble``：浮层。

多光标说明（stretch 项取舍）：``QPlainTextEdit`` 仅支持单一 QTextCursor，
Alt+Click 多光标无法直接渲染多选区，故以 VS Code 核心多选手势
``Ctrl+D``（选中当前词 → 逐个添加下一个匹配为多选区，批量编辑）替代，
见 ``select_next_occurrence()``。
"""

import re

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QPlainTextEdit,
    QWidget,
)

from ..theme import T, ThemeManager
from ..tokens import MONO_FAMILY
from .gutter import Gutter
from .highlight import create_engine
from .minimap import MiniMap
from .panels import CompletionPopup, FindReplaceBar, HoverBubble
from .regions import RegionManager

__all__ = ["CodeEditor"]

_BRACKETS_OPEN = "([{"
_BRACKETS_CLOSE = ")]}"
_BRACKET_PAIR = {")": "(", "]": "[", "}": "{"}
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: 快捷键动作默认值（action -> QKeySequence 字符串）。
#: 该表同时是合法 action 名的唯一权威来源，``set_shortcut`` 依其校验。
_DEFAULT_SHORTCUTS = {
    "find": "Ctrl+F",
    "replace": "Ctrl+H",
    "goto_line": "Ctrl+G",
    "select_next_occurrence": "Ctrl+D",
    "trigger_completion": "Ctrl+Space",
    "redo": "Ctrl+Y",
}


def _mono_font(families, px: int) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setStyleHint(QFont.TypeWriter)
    f.setFixedPitch(True)
    f.setPixelSize(px)
    return f


class _TextArea(QPlainTextEdit):
    """文本区：负责叠加绘制（缩进线 / 行尾空白）与按键路由。

    括号层级着色不在这里重绘字形，而是由 CodeEditor 写入 ExtraSelections
    前景色层——重绘括号会与原字形叠加产生重影。
    """

    def __init__(self, editor: "CodeEditor", parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._hover_pos = QPoint(-1, -1)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(300)
        self._hover_timer.timeout.connect(self._fire_hover)

    # ------------------------------------------------------------------
    # 叠加绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        super().paintEvent(event)
        ed = self._editor
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing, True)
        try:
            if ed._indent_guides:
                self._paint_indent_guides(p)
            if ed._whitespace_visible:
                self._paint_trailing_whitespace(p)
            if ed._paint_hook is not None:
                ed._paint_hook(p, self)
        finally:
            p.end()

    def _visible_blocks(self):
        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        vh = self.viewport().height()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(offset)
            if geo.top() > vh:
                break
            if block.isVisible() and geo.top() + geo.height() >= 0:
                yield block, geo.top(), geo.height()
            block = block.next()

    def _paint_indent_guides(self, p: QPainter) -> None:
        fm = self.fontMetrics()
        tab_w = self._editor._tab_size * fm.horizontalAdvance(" ")
        x0 = self.contentOffset().x() + self.document().documentMargin()
        level_colors = [
            QColor(T("color.border")),
            QColor(T("color.border.strong")),
            QColor(T("color.text.disabled")),
        ]
        for block, top, height in self._visible_blocks():
            text = block.text()
            stripped = text.lstrip(" \t")
            if not stripped:
                continue
            ws = text[: len(text) - len(stripped)]
            cols = sum(
                self._editor._tab_size if ch == "\t" else 1 for ch in ws
            )
            levels = cols // self._editor._tab_size
            for lvl in range(1, levels + 1):
                pen = QPen(level_colors[(lvl - 1) % len(level_colors)])
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                x = x0 + lvl * tab_w
                p.drawLine(int(x), int(top), int(x), int(top + height))

    def _paint_trailing_whitespace(self, p: QPainter) -> None:
        """只绘制行尾的连续空格 / 制表符（而非整篇空白）。"""
        color = QColor(T("color.text.tertiary"))
        x0 = self.contentOffset().x()
        for block, top, height in self._visible_blocks():
            text = block.text()
            stripped = text.rstrip(" \t")
            if len(stripped) == len(text):
                continue
            layout = block.layout()
            p.setPen(QPen(color, 1))
            for col in range(len(stripped), len(text)):
                line = layout.lineForTextPosition(col)
                if not line.isValid():
                    continue
                x = x0 + line.cursorToX(col)[0]
                baseline = top + line.y() + line.ascent()
                if text[col] == "\t":
                    # 制表符用一个小右箭头表示
                    p.drawLine(QPointF(x + 1, baseline - 2),
                               QPointF(x + 7, baseline - 2))
                    p.drawLine(QPointF(x + 4, baseline - 5),
                               QPointF(x + 7, baseline - 2))
                    p.drawLine(QPointF(x + 4, baseline + 1),
                               QPointF(x + 7, baseline - 2))
                else:
                    p.drawPoint(QPointF(x + 2, baseline - 2))

    # ------------------------------------------------------------------
    # 按键路由
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):  # noqa: N802 - Qt 命名
        ed = self._editor
        key = event.key()
        # 补全弹窗优先（延迟创建：None 表示从未弹过，直接跳过）
        if ed._completion is not None and ed._completion.isVisible() \
                and ed._completion.handle_key(key):
            return
        # Esc：退出多选 / 关闭查找栏
        if key == Qt.Key_Escape:
            if ed._multi:
                ed._clear_multi()
                return
            if not ed._find_bar.isHidden():
                ed.close_find_bar()
                return
            super().keyPressEvent(event)
            return
        # Tab / Shift+Tab：缩进 / 反缩进
        if key == Qt.Key_Tab:
            ed._indent_selection(dedent=False)
            return
        if key == Qt.Key_Backtab:
            ed._indent_selection(dedent=True)
            return
        # 多选区批量编辑
        if ed._multi:
            if key == Qt.Key_Backspace:
                ed._apply_multi_edit(backspace=True)
                return
            if key == Qt.Key_Delete:
                ed._apply_multi_edit(delete=True)
                return
            text = event.text()
            if text and text.isprintable():
                ed._apply_multi_edit(text=text)
                return
            if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                # 组合键（如 Ctrl+D 继续加选）交给快捷键处理，不退出多选
                super().keyPressEvent(event)
                return
            ed._clear_multi()  # 其他键（方向键等）退出多选
        super().keyPressEvent(event)
        # 输入触发补全（默认关闭，见 set_completion_auto_trigger；
        # 手动触发走 trigger_completion 快捷键，默认 Ctrl+Space）
        if (
            ed._completion_auto_trigger
            and ed._completion_provider
            and event.text()
            and (event.text().isprintable() or key == Qt.Key_Backspace)
            and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)
        ):
            ed._trigger_completion()
        elif (ed._completion is not None and ed._completion.isVisible()
              and not ed._completion_auto_trigger
              and (event.text().isprintable() or key == Qt.Key_Backspace)):
            # 默认手动补全：继续输入时旧候选已过期，直接收起。
            ed._completion.hide()

    def focusOutEvent(self, event):  # noqa: N802 - Qt 命名
        if self._editor._completion is not None:
            self._editor._completion.hide()
        super().focusOutEvent(event)

    # ------------------------------------------------------------------
    # 悬停
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event):  # noqa: N802 - Qt 命名
        self._hover_pos = event.position().toPoint()
        self._hover_timer.start()
        # 延迟创建：None 表示从未显示过气泡，无需隐藏
        if self._editor._hover_bubble is not None:
            self._editor._hover_bubble.hide()
        super().mouseMoveEvent(event)

    def _fire_hover(self):
        self._editor._show_hover_at(self._hover_pos)

    def leaveEvent(self, event):  # noqa: N802 - Qt 命名
        self._hover_timer.stop()
        if self._editor._hover_bubble is not None:
            self._editor._hover_bubble.hide()
        super().leaveEvent(event)

    def resizeEvent(self, event):  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        # 视口尺寸变化会改变可见 block 集合，括号前景色层只覆盖可见区。
        self._editor._update_bracket_colors()


# ---------------------------------------------------------------------------
# CodeEditor
# ---------------------------------------------------------------------------

class CodeEditor(QWidget):
    """VS Code 对齐的原生代码编辑器（CE_SPEC §2）。"""

    # -- 信号（CE_SPEC §2 契约） -------------------------------------------
    #: 光标位置变化 ``(line, column)``，均为 1-based
    cursor_position_changed = Signal(int, int)
    #: 选中文本变化
    selection_changed = Signal(str)
    #: 内容变化
    text_edited = Signal()
    #: 语言变化
    language_changed = Signal(str)
    #: 断点切换 ``(line, on)``
    breakpoint_toggled = Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 状态
        self._language = "plain"
        self._engine = None
        self._tab_size = 4
        self._line_number_mode = "on"
        self._indent_guides = True
        self._bracket_colorization = True
        self._whitespace_visible = False
        self._breakpoints = set()
        self._fold_points = {}     # 起始行(1-based) -> 结束行(1-based, 含)
        self._folded = set()
        self._multi = None         # [(start, end)] 多选区
        self._search_matches = []
        self._search_index = -1
        #: 括号层级着色的每块起始深度缓存（None 表示需重建）
        self._bracket_depth_cache = None
        self._last_selection = None
        self._completion_provider = None
        self._hover_provider = None
        self._completion_prefix = ""
        self._completion_auto_trigger = False
        self._line_label_provider = None
        self._line_marker_provider = None
        self._dual_line_label_provider = None
        self._paint_hook = None
        self._shortcuts_enabled = True
        self._shortcuts = dict(_DEFAULT_SHORTCUTS)
        self._shortcut_objs = []

        # 子控件
        self._text = _TextArea(self)
        self._gutter = Gutter(self)
        self._minimap = MiniMap(self)
        self._regions = RegionManager(self._text)
        # 可见区域变化时更新括号前景色层（只处理可见 block，滚动开销很小）
        self._text.verticalScrollBar().valueChanged.connect(
            self._update_bracket_colors)
        self._find_bar = FindReplaceBar(self, parent=self)
        self._find_bar.hide()
        # 补全弹窗与悬停气泡**延迟创建**（见 _ensure_completion/
        # _ensure_hover_bubble）。
        # 它们带 ``Qt.ToolTip`` 标志，即使有父级也会各自占一个原生窗口：一行
        # 编辑器 3 个、代码编辑器演示页 10 个。这些窗口在**顶层窗口已可见**时被
        # 创建，Windows 上会被窗口系统闪现一帧——用户看到的就是「突然闪出一个
        # 小面板又关掉」（多屏下尤其明显）。改为首次真正需要时才建，构造期不再
        # 产生任何窗口级控件。
        self._completion = None
        self._hover_bubble = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._gutter)
        lay.addWidget(self._text, 1)
        lay.addWidget(self._minimap)

        # 默认等宽字体
        families = [f.strip().strip('"') for f in MONO_FAMILY.split(",")]
        families = [f for f in families if f != "monospace"] or ["monospace"]
        self._font_families = families
        self._font_size = 13
        self._apply_font()
        self._refresh_text_style()

        # 信号连接
        self._text.cursorPositionChanged.connect(self._on_cursor_moved)
        self._text.selectionChanged.connect(self._on_selection_changed)
        self._text.document().contentsChanged.connect(self._on_contents_changed)
        self._text.verticalScrollBar().valueChanged.connect(
            lambda _v: (self._gutter.update(), self._minimap.update()))
        self._text.horizontalScrollBar().valueChanged.connect(
            lambda _v: self._gutter.update())
        self._gutter.breakpoint_clicked.connect(self.toggle_breakpoint)
        self._gutter.fold_clicked.connect(self._toggle_fold_at)
        self._find_bar.close_requested.connect(self.close_find_bar)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

        # 折叠重算去抖
        self._fold_timer = QTimer(self)
        self._fold_timer.setSingleShot(True)
        self._fold_timer.setInterval(200)
        self._fold_timer.timeout.connect(self._recompute_folds)

        # 编辑时搜索命中去抖刷新（查找栏可见时）
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.find_update)

        # 括号层级着色（ExtraSelections 前景色，避免重绘字形产生重影）
        self._bracket_timer = QTimer(self)
        self._bracket_timer.setSingleShot(True)
        self._bracket_timer.setInterval(120)
        self._bracket_timer.timeout.connect(self._update_bracket_colors)

        # 快捷键（统一由 _shortcuts 映射驱动，见 set_shortcut）
        self._install_shortcuts()

        self._gutter.refresh()
        self._on_cursor_moved()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _shortcut_actions(self) -> dict:
        """action -> 槽函数（每次安装时重建，保证绑定当前实例方法）。"""
        return {
            "find": lambda: self.open_find_bar(False),
            "replace": lambda: self.open_find_bar(True),
            "goto_line": self._goto_line_dialog,
            "select_next_occurrence": self.select_next_occurrence,
            "trigger_completion": self._trigger_completion,
            "redo": self._text.redo,
        }

    def _install_shortcuts(self) -> None:
        """按 ``_shortcuts`` 映射重装全部 QShortcut（改动即时生效）。"""
        for sc in self._shortcut_objs:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcut_objs = []
        if not self._shortcuts_enabled:
            return
        actions = self._shortcut_actions()
        for action, key in self._shortcuts.items():
            if not key:  # 空串 = 禁用该动作
                continue
            slot = actions.get(action)
            if slot is None:
                continue
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._shortcut_objs.append(sc)

    # ------------------------------------------------------------------
    # 快捷键管理
    # ------------------------------------------------------------------
    def set_shortcuts_enabled(self, on: bool) -> None:
        """启用 / 禁用全部自定义快捷键（默认 True，保持现状兼容）。

        关闭后编辑器不安装任何自定义快捷键（查找 / 替换 / 跳行 /
        多选 / 补全 / 重做）；Qt 原生文本编辑键（Ctrl+Z 撤销、
        Ctrl+C/V/X 等）不受影响。
        """
        self._shortcuts_enabled = bool(on)
        self._install_shortcuts()

    def shortcuts_enabled(self) -> bool:
        """自定义快捷键是否启用。"""
        return self._shortcuts_enabled

    def set_shortcut(self, action: str, key_sequence: str) -> None:
        """设置某动作的快捷键并即时生效（重装快捷键）。

        合法 ``action`` 与默认值::

            find                  Ctrl+F      打开查找栏
            replace               Ctrl+H      打开替换栏
            goto_line             Ctrl+G      跳行对话框
            select_next_occurrence Ctrl+D     选中词下一个匹配（多选）
            trigger_completion    Ctrl+Space  手动触发补全
            redo                  Ctrl+Y      重做

        ``key_sequence`` 为 ``QKeySequence`` 字符串（如 ``"Ctrl+J"``）；
        传空串表示禁用该动作。未知 ``action`` 抛 ``ValueError``。
        """
        if action not in _DEFAULT_SHORTCUTS:
            raise ValueError(
                f"未知快捷键动作: {action!r}（合法值: "
                f"{', '.join(sorted(_DEFAULT_SHORTCUTS))}）")
        self._shortcuts[action] = str(key_sequence or "")
        self._install_shortcuts()

    def shortcut(self, action: str) -> str:
        """返回某动作当前快捷键字符串（禁用为空串）。"""
        if action not in _DEFAULT_SHORTCUTS:
            raise ValueError(
                f"未知快捷键动作: {action!r}（合法值: "
                f"{', '.join(sorted(_DEFAULT_SHORTCUTS))}）")
        return self._shortcuts[action]

    def shortcuts(self) -> dict:
        """当前全部快捷键映射的副本 ``{action: key_sequence}``。"""
        return dict(self._shortcuts)

    def _apply_font(self) -> None:
        self._text.setFont(_mono_font(self._font_families, self._font_size))
        self._update_tab_stop()
        self._gutter.refresh()
        self._minimap.update()
        self._update_bracket_colors()

    def _refresh_text_style(self) -> None:
        """文本区实例级 QSS：主题令牌底色 / 前景 / 选区色（实时取 T()）。

        不依赖全局 QSS 是否已 apply，保证独立使用也主题正确。
        """
        self._text.setStyleSheet(
            "QPlainTextEdit {"
            f"background: {T('color.bg.base')};"
            f"color: {T('color.text.primary')};"
            "border: none;"
            f"selection-background-color: {T('color.primary')};"
            f"selection-color: {T('color.on.primary')};"
            "}"
        )

    def _update_tab_stop(self) -> None:
        fm = self._text.fontMetrics()
        self._text.setTabStopDistance(
            self._tab_size * fm.horizontalAdvance(" "))

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------
    def set_text(self, text: str) -> None:
        """设置全部文本（按「新文档」语义重置行级状态）。"""
        # 清理全部与旧文档偏移/行号绑定的状态：断点、诊断、搜索高亮、
        # 多选、折叠。否则错误行号会残留到新文档，甚至出现「folded_lines
        # 声称已折叠、但新文本块可见」的自相矛盾状态。
        self._fold_timer.stop()
        self._search_timer.stop()
        self._bracket_timer.stop()
        self._breakpoints.clear()
        self._multi = None
        self._search_matches = []
        self._search_index = -1
        self._folded.clear()
        self._fold_points = {}
        self._bracket_depth_cache = None
        self._last_selection = None
        self._regions.clear_all()
        self._text.setPlainText(text)
        # setPlainText 会同步触发 contentsChanged，上面已停掉去抖定时器，
        # 这里显式重算一次，避免新文档等待 200ms 才建立折叠点。
        self._fold_timer.stop()
        self._search_timer.stop()
        self._bracket_timer.stop()
        self._recompute_folds()
        self._gutter.refresh()
        self._minimap.schedule_refresh()
        self._regions.set_current_line(self._text.textCursor().position())
        self._update_bracket_match()
        self._update_bracket_colors()
        self._update_selection_highlight()
        if not self._find_bar.isHidden():
            self.find_update()
        else:
            self._regions.set_word_occurrences([])

    def text(self) -> str:
        """全部文本。"""
        return self._text.toPlainText()

    def set_language(self, name: str) -> None:
        """设置语言（经 highlight 注册表创建引擎）。"""
        if name == self._language and self._engine is not None:
            return
        if self._engine is not None:
            self._engine.setDocument(None)
            self._engine.deleteLater()
            self._engine = None
        self._language = name
        self._engine = create_engine(self._text.document(), name)
        self.language_changed.emit(name)
        self._minimap.schedule_refresh()

    def language(self) -> str:
        return self._language

    def set_font_family(self, family: str) -> None:
        """设置字族（支持逗号分隔的回退链）。"""
        self._font_families = [
            f.strip().strip('"') for f in family.split(",") if f.strip()
        ] or ["monospace"]
        self._apply_font()

    def set_font_size(self, px: int) -> None:
        """设置字号（px，范围 8-32，与 CE_SPEC / USAGE 一致）。"""
        self._font_size = max(8, min(32, int(px)))
        self._apply_font()

    # ------------------------------------------------------------------
    # 视图开关
    # ------------------------------------------------------------------
    def set_word_wrap(self, on: bool) -> None:
        self._text.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)
        self._update_bracket_colors()

    def set_minimap_visible(self, on: bool) -> None:
        self._minimap.setVisible(bool(on))
        self._layout_overlays()
        self._update_bracket_colors()

    def minimap_visible(self) -> bool:
        # 不能用 isVisible()：父级隐藏时它恒为 False，逻辑上的「已启用」
        # 会被误报为关闭。isHidden() 只反映控件自身的显隐设置。
        return not self._minimap.isHidden()

    def set_line_numbers(self, mode: str) -> None:
        """行号模式：``"on"`` / ``"off"`` / ``"relative"``。"""
        if mode not in ("on", "off", "relative"):
            raise ValueError(f"未知行号模式: {mode!r}")
        self._line_number_mode = mode
        self._gutter.refresh()
        self._update_bracket_colors()

    def line_number_mode(self) -> str:
        return self._line_number_mode

    def set_tab_size(self, n: int) -> None:
        self._tab_size = max(1, int(n))
        self._update_tab_stop()
        self._text.viewport().update()
        self._recompute_folds()

    def tab_size(self) -> int:
        return self._tab_size

    def set_readonly(self, on: bool) -> None:
        self._text.setReadOnly(bool(on))

    def set_indent_guides(self, on: bool) -> None:
        self._indent_guides = bool(on)
        self._text.viewport().update()

    def set_bracket_colorization(self, on: bool) -> None:
        self._bracket_colorization = bool(on)
        self._update_bracket_colors()
        self._text.viewport().update()

    def set_whitespace_visible(self, on: bool) -> None:
        """行尾空白可见（只标记行末连续空格 / 制表符，不是整篇空白）。"""
        self._whitespace_visible = bool(on)
        self._text.viewport().update()

    # ------------------------------------------------------------------
    # 光标与选择
    # ------------------------------------------------------------------
    def cursor_position(self) -> tuple:
        """当前光标 ``(line, column)``，均为 1-based。"""
        cur = self._text.textCursor()
        return (cur.blockNumber() + 1, cur.positionInBlock() + 1)

    def goto_line(self, line: int, column: int = 1) -> None:
        """跳转到指定行列（1-based），触发 cursor_position_changed。"""
        doc = self._text.document()
        line = max(1, min(int(line), doc.blockCount()))
        block = doc.findBlockByNumber(line - 1)
        col = max(1, min(int(column), block.length()))
        cur = self._text.textCursor()
        cur.setPosition(block.position() + col - 1)
        self._text.setTextCursor(cur)
        self._text.centerCursor()
        self._text.setFocus()

    def _update_selection_highlight(self) -> None:
        """把原生选区复制到最高优先级 ExtraSelection 层。

        diff 行底色、搜索高亮等都是 ExtraSelection，Qt 会把它们叠在
        原生选区之上；只改 QSS 的 selection-background-color 在 diff 页
        仍会被整行底色遮住。这里用独立的 selection 层保证拖选始终可见。
        """
        cur = self._text.textCursor()
        rng = ((cur.selectionStart(), cur.selectionEnd())
               if cur.hasSelection() else (0, 0))
        if rng == self._last_selection:
            return
        self._last_selection = rng
        self._regions.set_selection(*rng)

    def _on_cursor_moved(self) -> None:
        line, col = self.cursor_position()
        self._regions.set_current_line(self._text.textCursor().position())
        self._update_selection_highlight()
        self._update_bracket_match()
        self.cursor_position_changed.emit(line, col)

    def _on_selection_changed(self) -> None:
        cur = self._text.textCursor()
        text = cur.selectedText().replace(" ", "\n")
        self._update_selection_highlight()
        self.selection_changed.emit(text)
        self._update_word_occurrences()

    def _on_contents_changed(self) -> None:
        self.text_edited.emit()
        self._bracket_depth_cache = None
        self._fold_timer.start()
        self._bracket_timer.start()
        self._gutter.refresh()
        self._minimap.schedule_refresh()
        if not self._find_bar.isHidden() and self._find_bar.pattern():
            self._search_timer.start()

    # ------------------------------------------------------------------
    # 选中词同词高亮
    # ------------------------------------------------------------------
    def _update_word_occurrences(self) -> None:
        cur = self._text.textCursor()
        word = cur.selectedText()
        if (
            not word
            or len(word) > 128
            or any(ch.isspace() for ch in word)
        ):
            self._regions.set_word_occurrences([])
            return
        text = self.text()
        ranges = []
        for m in re.finditer(re.escape(word), text):
            ranges.append((m.start(), m.end()))
            if len(ranges) >= 5000:
                break
        self._regions.set_word_occurrences(ranges)

    # ------------------------------------------------------------------
    # 括号匹配
    # ------------------------------------------------------------------
    def _update_bracket_match(self) -> None:
        text = self.text()
        pos = self._text.textCursor().position()
        pair = self._find_bracket_pair(text, pos)
        if pair:
            self._regions.set_bracket_pair(pair)
        else:
            self._regions.set_bracket_pair([])

    def _bracket_start_depths(self) -> list:
        """每个 block 起始处的括号嵌套深度（供视口着色使用缓存）。"""
        doc = self._text.document()
        n = doc.blockCount()
        cache = self._bracket_depth_cache
        if cache is not None and len(cache) == n:
            return cache
        depths = []
        depth = 0
        block = doc.firstBlock()
        while block.isValid():
            depths.append(depth)
            for ch in block.text():
                if ch in _BRACKETS_OPEN:
                    depth += 1
                elif ch in _BRACKETS_CLOSE:
                    depth = max(0, depth - 1)
            block = block.next()
        self._bracket_depth_cache = depths
        return depths

    def _update_bracket_colors(self) -> None:
        """用 ExtraSelections 前景色给可见括号按嵌套深度着色。

        不用 ``paintEvent`` 重绘括号字形：重绘与原字形叠加会出现重影
        （尤其是抗锯齿边缘），而且 x 坐标一偏就会在原文旁多出一个括号。
        ExtraSelection 的 foreground 只改一次字形颜色，没有叠加问题。
        """
        if getattr(self, "_regions", None) is None:
            return
        if not self._bracket_colorization:
            self._regions.clear_layer("bracket_color")
            return
        depths = self._bracket_start_depths()
        colors = [
            QColor(T("color.primary")),
            QColor(T("color.success")),
            QColor(T("color.warning")),
        ]
        fmts = []
        for color in colors:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            fmts.append(fmt)
        items = []
        for block, _top, _height in self._text._visible_blocks():
            bn = block.blockNumber()
            depth = depths[bn] if bn < len(depths) else 0
            text = block.text()
            for col, ch in enumerate(text):
                if ch in _BRACKETS_CLOSE:
                    depth = max(0, depth - 1)
                if ch in _BRACKETS_OPEN or ch in _BRACKETS_CLOSE:
                    items.append((block.position() + col,
                                  block.position() + col + 1,
                                  fmts[depth % len(fmts)]))
                if ch in _BRACKETS_OPEN:
                    depth += 1
        self._regions.set_region_formats("bracket_color", items)

    @staticmethod
    def _find_bracket_pair(text: str, pos: int):
        """在光标前 / 后查找括号并配对其搭档，返回 ``[(a,a+1),(b,b+1)]``。"""
        idx = -1
        ch = ""
        if pos > 0 and text[pos - 1] in _BRACKETS_OPEN + _BRACKETS_CLOSE:
            idx = pos - 1
            ch = text[idx]
        elif pos < len(text) and text[pos] in _BRACKETS_OPEN + _BRACKETS_CLOSE:
            idx = pos
            ch = text[idx]
        if idx < 0:
            return None
        if ch in _BRACKETS_OPEN:
            target = _BRACKETS_CLOSE[_BRACKETS_OPEN.index(ch)]
            depth = 0
            for i in range(idx + 1, len(text)):
                c = text[i]
                if c == ch:
                    depth += 1
                elif c == target:
                    if depth == 0:
                        return [(idx, idx + 1), (i, i + 1)]
                    depth -= 1
        else:
            target = _BRACKET_PAIR[ch]
            depth = 0
            for i in range(idx - 1, -1, -1):
                c = text[i]
                if c == ch:
                    depth += 1
                elif c == target:
                    if depth == 0:
                        return [(i, i + 1), (idx, idx + 1)]
                    depth -= 1
        return None

    # ------------------------------------------------------------------
    # 诊断 / 断点 / 自定义层
    # ------------------------------------------------------------------
    def set_diagnostics(self, items) -> None:
        """设置诊断：``{"line","column","length","severity","message"}``。"""
        self._regions.set_diagnostics(items)
        self._gutter.update()
        self._minimap.update()

    def diagnostics(self) -> list:
        return self._regions.diagnostics()

    def diagnostic_lines(self) -> dict:
        return self._regions.diagnostic_lines()

    def toggle_breakpoint(self, line: int) -> None:
        """切换某行断点（1-based；越界行号直接忽略）。"""
        line = int(line)
        if not 1 <= line <= self._text.document().blockCount():
            return
        if line in self._breakpoints:
            self._breakpoints.discard(line)
            self.breakpoint_toggled.emit(line, False)
        else:
            self._breakpoints.add(line)
            self.breakpoint_toggled.emit(line, True)
        self._gutter.update()
        self._minimap.update()

    def breakpoints(self) -> set:
        return set(self._breakpoints)

    def set_region_highlight(self, layer: str, ranges, color: str) -> None:
        """自定义区域高亮（公共扩展点）。"""
        self._regions.set_region_highlight(layer, ranges, color)

    def region_manager(self) -> RegionManager:
        """区域高亮管理器（高级扩展入口）。"""
        return self._regions

    # ------------------------------------------------------------------
    # Provider 扩展点
    # ------------------------------------------------------------------
    def set_completion_provider(self, fn) -> None:
        """补全 provider：``fn(prefix, line, col) -> list[dict]``。"""
        self._completion_provider = fn

    def set_hover_provider(self, fn) -> None:
        """悬停 provider：``fn(line, col) -> str | None``（富文本）。"""
        self._hover_provider = fn

    def set_completion_auto_trigger(self, on: bool) -> None:
        """输入字符时是否自动弹出补全（默认 False）。

        默认关闭：补全只在 ``trigger_completion`` 快捷键（缺省
        Ctrl+Space，可用 ``set_shortcut`` 改绑）时弹出。开启后
        每次击键同步调用 provider 并刷新弹窗（弹窗不抢焦点，
        不会阻塞输入）。
        """
        self._completion_auto_trigger = bool(on)

    def completion_auto_trigger(self) -> bool:
        """补全自动触发是否开启。"""
        return self._completion_auto_trigger

    def set_line_label_provider(self, fn) -> None:
        """自定义行号提供者（默认 None，行为不变）。

        ``fn(display_line_1based) -> str | None``：返回该显示行的
        行号文本；返回 ``None`` 表示该行不绘制行号（如 diff 并排
        视图的占位空行）。设置后 gutter 绘制优先使用 provider，
        取代 ``"on" / "relative"`` 模式下的内置编号。
        """
        self._line_label_provider = fn
        self._gutter.refresh()

    def line_label_provider(self):
        """当前行号提供者（未设置为 None）。"""
        return self._line_label_provider

    def set_line_marker_provider(self, fn) -> None:
        """行号旁变更符号提供者（默认 None，行为不变）。

        ``fn(display_line_1based) -> str | None``：返回该行行号旁的
        标记文本（如 diff 视图的 ``"+"`` / ``"−"``）；``None`` 表示
        无标记。标记绘制在行号右侧的标记列内，``+`` 取 success 色、
        ``−``/``-`` 取 danger 色，其余取次要文本色。
        """
        self._line_marker_provider = fn
        self._gutter.refresh()

    def line_marker_provider(self):
        """当前行标记提供者（未设置为 None）。"""
        return self._line_marker_provider

    def set_dual_line_labels(self, fn) -> None:
        """双列行号提供者（默认 None，行为不变；VS Code 内联 diff 样式）。

        ``fn(display_line_1based) -> (left, right, marker) | None``：
        left / right 分别为左列（原始文件）/ 右列（修改文件）的行号
        文本（可含 ``+`` / ``−`` 后缀），``None`` 表示该列留空；
        marker 为 ``"+"`` / ``"−"`` / ``None``，决定着色（success /
        danger / 默认）。设置后 gutter 切换为双列布局并加宽，优先于
        ``set_line_label_provider``；传 ``None`` 恢复单列。
        """
        self._dual_line_label_provider = fn
        self._gutter.refresh()

    def dual_line_label_provider(self):
        """当前双列行号提供者（未设置为 None）。"""
        return self._dual_line_label_provider

    def set_paint_hook(self, fn) -> None:
        """文本区视口叠加绘制钩子（默认 None）。

        ``fn(painter, text_area)`` 在文本区 ``paintEvent`` 基础绘制
        之后调用，坐标系为 viewport；因为在同一 paint pass 内执行，
        叠加内容与文本滚动严格同步（diff 占位区斜线阴影块等用途）。
        """
        self._paint_hook = fn
        self._text.viewport().update()

    def paint_hook(self):
        """当前视口叠加绘制钩子（未设置为 None）。"""
        return self._paint_hook

    # ------------------------------------------------------------------
    # 查找替换
    # ------------------------------------------------------------------
    def open_find_bar(self, replace: bool = False) -> None:
        """打开查找替换浮条（顶部右侧）。"""
        self._search_timer.stop()
        cur = self._text.textCursor()
        seed = ""
        if cur.hasSelection():
            sel = cur.selectedText()
            if "\n" not in sel and " " not in sel and len(sel) <= 200:
                seed = sel
        self._find_bar.open(replace, seed)
        self._layout_overlays()

    def close_find_bar(self) -> None:
        """关闭查找替换浮条并清除搜索高亮。"""
        self._search_timer.stop()
        self._find_bar.hide()
        self._search_matches = []
        self._search_index = -1
        self._regions.set_search_matches([], None)
        self._minimap.update()
        self._text.setFocus()

    def _compile_search(self):
        """按浮条选项编译搜索正则；失败返回 None。"""
        pattern = self._find_bar.pattern()
        if not pattern:
            return None
        opts = self._find_bar.options()
        flags = 0 if opts["case"] else re.IGNORECASE
        pat = pattern if opts["regex"] else re.escape(pattern)
        if opts["word"]:
            pat = r"\b(?:" + pat + r")\b"
        try:
            return re.compile(pat, flags)
        except re.error:
            return None

    def find_update(self) -> None:
        """按浮条当前输入重新搜索并高亮全部命中。"""
        self._search_timer.stop()
        rx = self._compile_search()
        matches = []
        if rx is not None:
            text = self.text()
            for m in rx.finditer(text):
                if m.end() > m.start():
                    matches.append((m.start(), m.end()))
                if len(matches) >= 20000:
                    break
        self._search_matches = matches
        if not matches:
            self._search_index = -1
            self._regions.set_search_matches([], None)
            self._find_bar.set_count(0, 0)
        else:
            pos = self._text.textCursor().position()
            idx = 0
            for i, (a, _b) in enumerate(matches):
                if a >= pos:
                    idx = i
                    break
            self._search_index = idx
            self._regions.set_search_matches(matches, matches[idx])
            self._find_bar.set_count(idx + 1, len(matches))
        self._minimap.update()

    def _goto_match(self, idx: int) -> None:
        if not self._search_matches:
            return
        self._search_index = idx % len(self._search_matches)
        a, b = self._search_matches[self._search_index]
        cur = self._text.textCursor()
        cur.setPosition(a)
        cur.setPosition(b, QTextCursor.KeepAnchor)
        self._text.setTextCursor(cur)
        self._text.centerCursor()
        self._regions.set_search_matches(
            self._search_matches, self._search_matches[self._search_index])
        self._find_bar.set_count(
            self._search_index + 1, len(self._search_matches))
        self._minimap.update()

    def find_next(self) -> None:
        """跳到下一个命中（回绕）。"""
        if self._search_matches:
            self._goto_match(self._search_index + 1)

    def find_prev(self) -> None:
        """跳到上一个命中（回绕）。"""
        if self._search_matches:
            self._goto_match(self._search_index - 1)

    def replace_current(self) -> None:
        """替换当前命中并重新搜索。"""
        if not self._search_matches or self._search_index < 0:
            return
        a, b = self._search_matches[self._search_index]
        cur = self._text.textCursor()
        cur.setPosition(a)
        cur.setPosition(b, QTextCursor.KeepAnchor)
        cur.insertText(self._find_bar.replacement())
        self.find_update()

    def replace_all(self) -> None:
        """替换全部命中。"""
        if not self._search_matches:
            return
        doc = self._text.document()
        repl = self._find_bar.replacement()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        for a, b in sorted(self._search_matches, reverse=True):
            c = QTextCursor(doc)
            c.setPosition(a)
            c.setPosition(b, QTextCursor.KeepAnchor)
            c.insertText(repl)
        cur.endEditBlock()
        self.find_update()

    def search_match_lines(self) -> list:
        """搜索命中所在行（1-based，供小地图刻度）。"""
        doc = self._text.document()
        lines = set()
        for a, _b in self._search_matches[:2000]:
            block = doc.findBlock(a)
            if block.isValid():
                lines.add(block.blockNumber() + 1)
        return sorted(lines)

    def find_count(self) -> tuple:
        """``(当前序号 0-based, 总数)``，无匹配时 ``(-1, 0)``。"""
        return (self._search_index, len(self._search_matches))

    # ------------------------------------------------------------------
    # 补全
    # ------------------------------------------------------------------
    def _current_prefix(self) -> tuple:
        """光标前单词前缀与起点偏移：``(prefix, start_pos)``。"""
        cur = self._text.textCursor()
        pos = cur.position()
        text = self._text.document().findBlock(pos).text()
        col = cur.positionInBlock()
        m = None
        for m in _WORD_RE.finditer(text, 0, col):
            if m.end() == col:
                break
        else:
            m = None
        if m is None:
            return ("", pos)
        return (m.group(0), pos - len(m.group(0)))

    def _trigger_completion(self) -> None:
        """触发补全（输入触发或 Ctrl+Space）。"""
        if self._completion_provider is None:
            if self._completion is not None:
                self._completion.hide()
            return
        prefix, _start = self._current_prefix()
        self._completion_prefix = prefix
        line, col = self.cursor_position()
        try:
            items = self._completion_provider(prefix, line, col) or []
        except Exception:
            items = []
        if not items:
            if self._completion is not None:
                self._completion.hide()
            return
        popup = self._ensure_completion()
        popup.set_items(items)
        rect = self._text.cursorRect()
        pos = self._text.viewport().mapToGlobal(rect.bottomLeft())
        popup.popup_at(pos)

    def _apply_completion(self, insert_text: str) -> None:
        """确认补全：替换当前前缀为插入文本。"""
        prefix, start = self._current_prefix()
        cur = self._text.textCursor()
        cur.setPosition(start)
        cur.setPosition(cur.position() + len(prefix), QTextCursor.KeepAnchor)
        cur.insertText(insert_text)
        self._text.setTextCursor(cur)
        if self._completion is not None:
            self._completion.hide()

    # ------------------------------------------------------------------
    # 悬停
    # ------------------------------------------------------------------
    def _show_hover_at(self, pos: QPoint) -> None:
        """在文本区坐标 ``pos`` 处请求悬停气泡（provider 驱动）。"""
        if self._hover_provider is None:
            return
        cur = self._text.cursorForPosition(pos)
        line = cur.blockNumber() + 1
        col = cur.positionInBlock() + 1
        try:
            html = self._hover_provider(line, col)
        except Exception:
            html = None
        if not html:
            return
        global_pos = self._text.viewport().mapToGlobal(
            QPoint(pos.x() + 12, pos.y() + 18))
        self._ensure_hover_bubble().show_at(global_pos, html)

    # ------------------------------------------------------------------
    # 折叠（基于缩进）
    # ------------------------------------------------------------------
    def _line_indents(self) -> list:
        """每行缩进列数；空行记为 None。"""
        lines = self.text().split("\n")
        indents = []
        for line in lines:
            stripped = line.lstrip(" \t")
            if not stripped:
                indents.append(None)
            else:
                ws = line[: len(line) - len(stripped)]
                indents.append(
                    sum(self._tab_size if ch == "\t" else 1 for ch in ws))
        return indents

    def _recompute_folds(self) -> None:
        """基于缩进重算可折叠区域，并恢复失效折叠隐藏的行。"""
        doc = self._text.document()
        # 折叠是本编辑器里唯一使用 block 可见性的功能。重算前先全部恢复
        # 可见，再按仍有效的折叠点重新隐藏：否则编辑让某个折叠点失效后，
        # 旧折叠隐藏的 block 会永远留在不可见状态（unfold_all 也救不回来，
        # 因为 _folded 已经被过滤掉）。
        block = doc.firstBlock()
        while block.isValid():
            if not block.isVisible():
                block.setVisible(True)
            block = block.next()

        indents = self._line_indents()
        points = {}
        n = len(indents)
        for i in range(n):
            if indents[i] is None:
                continue
            j = i + 1
            while j < n and indents[j] is None:
                j += 1
            if j >= n or indents[j] <= indents[i]:
                continue
            end = j
            k = j + 1
            while k < n and (indents[k] is None or indents[k] > indents[i]):
                if indents[k] is not None:
                    end = k
                k += 1
            if end > i:
                points[i + 1] = end + 1
        # 保留仍合法的折叠状态，并按新范围重新隐藏
        self._fold_points = points
        self._folded = {line for line in self._folded if line in points}
        for line in sorted(self._folded):
            end = points[line]
            for ln in range(line + 1, end + 1):
                b = doc.findBlockByNumber(ln - 1)
                if b.isValid():
                    b.setVisible(False)
        self._gutter.update()
        self._update_bracket_colors()

    def fold_points(self) -> dict:
        """可折叠起始行 ``{起始行: 结束行}``（1-based，结束行含）。"""
        return dict(self._fold_points)

    def folded_lines(self) -> set:
        """当前已折叠的起始行集合（1-based）。"""
        return set(self._folded)

    def fold(self, line: int) -> None:
        """折叠以 ``line``（1-based）开始的区域。"""
        line = int(line)
        if line not in self._fold_points or line in self._folded:
            return
        end = self._fold_points[line]
        doc = self._text.document()
        for ln in range(line + 1, end + 1):
            block = doc.findBlockByNumber(ln - 1)
            if block.isValid():
                block.setVisible(False)
        self._folded.add(line)
        self._after_fold_change(line)

    def unfold(self, line: int) -> None:
        """展开 ``line``（1-based）处的折叠。"""
        line = int(line)
        if line not in self._folded:
            return
        end = self._fold_points.get(line, line)
        doc = self._text.document()
        for ln in range(line + 1, end + 1):
            block = doc.findBlockByNumber(ln - 1)
            if block.isValid():
                block.setVisible(True)
        self._folded.discard(line)
        self._after_fold_change(line)

    def fold_all(self) -> None:
        """折叠全部可折叠区域。"""
        for line in sorted(self._fold_points):
            self.fold(line)

    def unfold_all(self) -> None:
        """展开全部折叠。"""
        for line in sorted(self._folded, reverse=True):
            self.unfold(line)

    def _toggle_fold_at(self, line: int) -> None:
        if line in self._folded:
            self.unfold(line)
        else:
            self.fold(line)

    def _after_fold_change(self, line: int) -> None:
        doc = self._text.document()
        block = doc.findBlockByNumber(max(0, line - 1))
        if block.isValid():
            doc.markContentsDirty(block.position(), block.length())
        self._text.viewport().update()
        self._text.updateGeometry()
        self._gutter.update()
        self._minimap.schedule_refresh()
        self._update_bracket_colors()

    # ------------------------------------------------------------------
    # 缩进选择区（Tab / Shift+Tab）
    # ------------------------------------------------------------------
    def _indent_selection(self, dedent: bool = False) -> None:
        """Tab / Shift+Tab：缩进选择区；无选区时在光标处插入缩进。"""
        cur = self._text.textCursor()
        doc = self._text.document()
        unit = " " * self._tab_size

        def dedent_block(block) -> int:
            """删除 block 行首最多一个缩进档，返回删除字符数。"""
            c = QTextCursor(block)
            text = block.text()
            remove = 0
            for ch in text[: self._tab_size]:
                if ch == " ":
                    remove += 1
                elif ch == "\t":
                    remove += 1
                    break
                else:
                    break
            if remove:
                c.movePosition(QTextCursor.NextCharacter,
                               QTextCursor.KeepAnchor, remove)
                c.removeSelectedText()
            return remove

        if cur.hasSelection():
            sel_start = cur.selectionStart()
            sel_end = cur.selectionEnd()
            start_bn = doc.findBlock(sel_start).blockNumber()
            end_bn = doc.findBlock(sel_end).blockNumber()
            # 选区结束在下一行行首时，不应把那一行也缩进（VS Code 语义），
            # 同时避免选中以换行结尾时给末尾空行补缩进。
            if (end_bn > start_bn
                    and sel_end == doc.findBlock(sel_end).position()):
                end_bn -= 1
            start_bn = max(0, min(start_bn, doc.blockCount() - 1))
            end_bn = max(start_bn, min(end_bn, doc.blockCount() - 1))

            edit_cur = QTextCursor(doc)
            edit_cur.beginEditBlock()
            for bn in range(start_bn, end_bn + 1):
                block = doc.findBlockByNumber(bn)
                if not block.isValid():
                    continue
                if dedent:
                    dedent_block(block)
                else:
                    QTextCursor(block).insertText(unit)
            edit_cur.endEditBlock()

            # 恢复为「完整行选择」：包含缩进后的行首空白，下一次 Tab 可
            # 继续对同一组行缩进，不会再出现半行/多一行。
            first = doc.findBlockByNumber(start_bn)
            last = doc.findBlockByNumber(end_bn)
            if first.isValid() and last.isValid():
                c = self._text.textCursor()
                c.setPosition(first.position())
                c.setPosition(last.position() + len(last.text()),
                              QTextCursor.KeepAnchor)
                self._text.setTextCursor(c)
            self._text.setFocus()
            return

        # 无选区：Tab 在光标处插入缩进；Shift+Tab 去掉当前行行首缩进。
        block = doc.findBlock(cur.position())
        if not block.isValid():
            return
        if dedent:
            pos = cur.position()
            removed = dedent_block(block)
            if removed:
                c = self._text.textCursor()
                c.setPosition(max(block.position(), pos - removed))
                self._text.setTextCursor(c)
        else:
            cur.insertText(unit)
            self._text.setTextCursor(cur)
        self._text.setFocus()

    # ------------------------------------------------------------------
    # 多光标（Ctrl+D，Alt+Click 的替代实现，见模块 docstring）
    # ------------------------------------------------------------------
    def select_next_occurrence(self) -> None:
        """Ctrl+D：选中当前词 / 添加下一个同词匹配为多选区。"""
        cur = self._text.textCursor()
        if self._multi is None:
            if not cur.hasSelection():
                cur.select(QTextCursor.WordUnderCursor)
                if not cur.hasSelection():
                    return
                self._text.setTextCursor(cur)
            self._multi = [(cur.selectionStart(), cur.selectionEnd())]
            self._regions.set_multi_selections(self._multi)
            return
        a0, b0 = self._multi[0]
        word = self.text()[a0:b0]
        if not word:
            return
        text = self.text()
        taken = set(self._multi)
        from_pos = self._multi[-1][1]
        idx = text.find(word, from_pos)
        if idx < 0:
            idx = text.find(word, 0, from_pos)
        if idx < 0 or (idx, idx + len(word)) in taken:
            return
        self._multi.append((idx, idx + len(word)))
        self._regions.set_multi_selections(self._multi)
        # 主光标移到最新选区
        cur.setPosition(idx)
        cur.setPosition(idx + len(word), QTextCursor.KeepAnchor)
        self._text.setTextCursor(cur)

    def multi_selections(self) -> list:
        """当前多选区列表（无多选返回空表）。"""
        return list(self._multi or [])

    def _clear_multi(self) -> None:
        self._multi = None
        self._regions.set_multi_selections([])

    def _apply_multi_edit(self, text: str = None, backspace: bool = False,
                          delete: bool = False) -> None:
        """对所有多选区批量应用同一编辑（从后往前保证偏移有效）。"""
        if not self._multi:
            return
        doc = self._text.document()
        recorded = []          # 已处理（更高偏移）选区在新文档中的 (start,end)
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        for a, b in sorted(self._multi, reverse=True):
            c = QTextCursor(doc)
            if backspace and a == b and a > 0:
                a -= 1
            c.setPosition(a)
            c.setPosition(b, QTextCursor.KeepAnchor)
            if delete and a == b:
                c.deleteChar()
                delta = -1
                new_range = (a, a)
            elif text:
                c.insertText(text)
                delta = len(text) - (b - a)
                new_range = (a, a + len(text))
            else:
                c.removeSelectedText()
                delta = -(b - a)
                new_range = (a, a)
            # 已记录的选区都在更高偏移处，随本次（更低位置）编辑整体平移
            recorded = [(s + delta, e + delta) for s, e in recorded]
            recorded.append(new_range)
        cur.endEditBlock()
        self._multi = sorted(recorded)
        self._regions.set_multi_selections(self._multi)
        last = self._text.textCursor()
        last.setPosition(self._multi[-1][1])
        self._text.setTextCursor(last)

    # ------------------------------------------------------------------
    # 主题 / 布局
    # ------------------------------------------------------------------
    def _on_theme_changed(self, _mode: str) -> None:
        """主题切换：引擎自动重刷，这里刷新自绘层。"""
        try:
            self._refresh_text_style()
            self._regions.refresh_theme()
            self._update_bracket_colors()
        except RuntimeError:
            return  # 控件已销毁
        self._gutter.update()
        self._minimap.update()
        self._text.viewport().update()

    def _goto_line_dialog(self) -> None:
        """Ctrl+G：跳行输入框。"""
        total = self._text.document().blockCount()
        line, ok = QInputDialog.getInt(
            self, "跳转到行", f"行号 (1-{total}):",
            self.cursor_position()[0], 1, total)
        if ok:
            self.goto_line(line)

    def _layout_overlays(self) -> None:
        """查找栏定位：编辑器顶部右侧（避开小地图）。"""
        if self._find_bar.isHidden():
            return
        self._find_bar.adjustSize()
        right_pad = 12 + (self._minimap.width()
                          if not self._minimap.isHidden() else 0)
        x = max(self._gutter.width() + 8,
                self.width() - self._find_bar.width() - right_pad)
        self._find_bar.move(x, 8)
        self._find_bar.raise_()

    def resizeEvent(self, event):  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._layout_overlays()

    # ------------------------------------------------------------------
    # 子控件访问（E2/E3/E4 扩展）
    # ------------------------------------------------------------------
    def text_area(self) -> QPlainTextEdit:
        """内部文本区（QPlainTextEdit 子类）。"""
        return self._text

    def gutter(self) -> Gutter:
        return self._gutter

    def minimap(self) -> MiniMap:
        return self._minimap

    def find_bar(self) -> FindReplaceBar:
        return self._find_bar

    def completion_popup(self) -> CompletionPopup:
        return self._ensure_completion()

    def hover_bubble(self) -> HoverBubble:
        return self._ensure_hover_bubble()

    def _ensure_completion(self) -> CompletionPopup:
        """补全弹窗（首次调用时创建，见 __init__ 中的延迟创建说明）。"""
        if self._completion is None:
            self._completion = CompletionPopup(self, parent=self)
            self._completion.item_chosen.connect(self._apply_completion)
            self._completion.hide()
        return self._completion

    def _ensure_hover_bubble(self) -> HoverBubble:
        """悬停气泡（首次调用时创建，见 __init__ 中的延迟创建说明）。"""
        if self._hover_bubble is None:
            self._hover_bubble = HoverBubble(self, parent=self)
            self._hover_bubble.hide()
        return self._hover_bubble

    def highlight_engine(self):
        """当前高亮引擎（plain 语言时为 None）。"""
        return self._engine
