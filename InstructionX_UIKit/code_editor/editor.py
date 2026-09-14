# -*- coding: utf-8 -*-
"""CodeEditor 主控件（CE_SPEC §2）。

架构：``CodeEditor(QWidget)`` 组合

- ``Gutter``：行号槽（行号 / 断点 / 折叠箭头 / 诊断着色条）；
- ``_TextArea(QPlainTextEdit)``：文本区，自绘当前行以外的叠加层
  （缩进参考线 / 括号着色 / 行尾空白），等宽字体，tab_size 按字体度量换算；
- ``MiniMap``：小地图；
- ``FindReplaceBar`` / ``CompletionPopup`` / ``HoverBubble``：浮层。

多光标说明（stretch 项取舍）：``QPlainTextEdit`` 仅支持单一 QTextCursor，
Alt+Click 多光标无法直接渲染多选区，故以 VS Code 核心多选手势
``Ctrl+D``（选中当前词 → 逐个添加下一个匹配为多选区，批量编辑）替代，
见 ``select_next_occurrence()``。
"""

import re

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QTextCursor,
    QTextOption,
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
    """文本区：负责叠加绘制（缩进线 / 括号着色）与按键路由。"""

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
            if ed._bracket_colorization:
                self._paint_brackets(p)
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

    def _paint_brackets(self, p: QPainter) -> None:
        colors = [
            QColor(T("color.primary")),
            QColor(T("color.success")),
            QColor(T("color.warning")),
        ]
        fm = self.fontMetrics()
        x0 = self.contentOffset().x() + self.document().documentMargin()
        p.setFont(self.font())
        depth = 0
        for block, top, height in self._visible_blocks():
            text = block.text()
            baseline = top + fm.ascent() + fm.leading()
            for col, ch in enumerate(text):
                if ch in _BRACKETS_OPEN:
                    p.setPen(QPen(colors[depth % len(colors)]))
                    x = x0 + fm.horizontalAdvance(text[:col])
                    p.drawText(QPoint(int(x), int(baseline)), ch)
                    depth += 1
                elif ch in _BRACKETS_CLOSE:
                    depth = max(0, depth - 1)
                    p.setPen(QPen(colors[depth % len(colors)]))
                    x = x0 + fm.horizontalAdvance(text[:col])
                    p.drawText(QPoint(int(x), int(baseline)), ch)

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
            if ed._find_bar.isVisible():
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
        self._breakpoints = set()
        self._fold_points = {}     # 起始行(1-based) -> 结束行(1-based, 含)
        self._folded = set()
        self._multi = None         # [(start, end)] 多选区
        self._search_matches = []
        self._search_index = -1
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

    def _refresh_text_style(self) -> None:
        """文本区实例级 QSS：主题令牌底色 / 前景 / 选区色（实时取 T()）。

        不依赖全局 QSS 是否已 apply，保证独立使用也主题正确。
        """
        self._text.setStyleSheet(
            "QPlainTextEdit {"
            f"background: {T('color.bg.base')};"
            f"color: {T('color.text.primary')};"
            "border: none;"
            f"selection-background-color: {T('color.primary.subtle')};"
            f"selection-color: {T('color.text.primary')};"
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
        """设置全部文本。"""
        self._text.setPlainText(text)
        self._recompute_folds()
        self._minimap.schedule_refresh()

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
        """设置字号（px）。"""
        self._font_size = max(6, int(px))
        self._apply_font()

    # ------------------------------------------------------------------
    # 视图开关
    # ------------------------------------------------------------------
    def set_word_wrap(self, on: bool) -> None:
        self._text.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)

    def set_minimap_visible(self, on: bool) -> None:
        self._minimap.setVisible(bool(on))
        self._layout_overlays()

    def minimap_visible(self) -> bool:
        return self._minimap.isVisible()

    def set_line_numbers(self, mode: str) -> None:
        """行号模式：``"on"`` / ``"off"`` / ``"relative"``。"""
        if mode not in ("on", "off", "relative"):
            raise ValueError(f"未知行号模式: {mode!r}")
        self._line_number_mode = mode
        self._gutter.refresh()

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
        self._text.viewport().update()

    def set_whitespace_visible(self, on: bool) -> None:
        """行尾空白 / 制表符可见（stretch 项）。"""
        opt = self._text.document().defaultTextOption()
        flags = opt.flags()
        if on:
            flags |= QTextOption.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.ShowTabsAndSpaces
        opt.setFlags(flags)
        self._text.document().setDefaultTextOption(opt)
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

    def _on_cursor_moved(self) -> None:
        line, col = self.cursor_position()
        self._regions.set_current_line(self._text.textCursor().position())
        self._update_bracket_match()
        self.cursor_position_changed.emit(line, col)

    def _on_selection_changed(self) -> None:
        cur = self._text.textCursor()
        text = cur.selectedText().replace(" ", "\n")
        self.selection_changed.emit(text)
        self._update_word_occurrences()

    def _on_contents_changed(self) -> None:
        self.text_edited.emit()
        self._fold_timer.start()
        self._gutter.refresh()
        self._minimap.schedule_refresh()

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
        """切换某行断点（1-based）。"""
        line = int(line)
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
        """基于缩进重算可折叠区域。"""
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
        # 保留仍合法的折叠状态
        self._fold_points = points
        self._folded = {l for l in self._folded if l in points}
        self._gutter.update()

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

    # ------------------------------------------------------------------
    # 缩进选择区（Tab / Shift+Tab）
    # ------------------------------------------------------------------
    def _indent_selection(self, dedent: bool = False) -> None:
        cur = self._text.textCursor()
        doc = self._text.document()
        start = doc.findBlock(cur.selectionStart()).blockNumber()
        end = doc.findBlock(cur.selectionEnd()).blockNumber()
        unit = " " * self._tab_size
        cur.beginEditBlock()
        for bn in range(start, end + 1):
            block = doc.findBlockByNumber(bn)
            c = QTextCursor(block)
            if dedent:
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
            else:
                c.insertText(unit)
        cur.endEditBlock()
        # 恢复选择（近似：选中范围整体偏移已在编辑块内由 Qt 跟踪）

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
        recorded = []
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
                delta, caret = -1, a
            elif text:
                c.insertText(text)
                delta, caret = len(text) - (b - a), a + len(text)
            else:
                c.removeSelectedText()
                delta, caret = -(b - a), a
            # 已记录位置都在更高偏移处，随本次编辑平移
            recorded = [p + delta for p in recorded]
            recorded.append(caret)
        cur.endEditBlock()
        self._multi = [(p, p) for p in sorted(recorded)]
        self._regions.set_multi_selections(self._multi)
        last = self._text.textCursor()
        last.setPosition(self._multi[-1][0])
        self._text.setTextCursor(last)

    # ------------------------------------------------------------------
    # 主题 / 布局
    # ------------------------------------------------------------------
    def _on_theme_changed(self, _mode: str) -> None:
        """主题切换：引擎自动重刷，这里刷新自绘层。"""
        try:
            self._refresh_text_style()
            self._regions.set_current_line(self._text.textCursor().position())
        except RuntimeError:
            return  # 控件已销毁
        self._update_bracket_match()
        self._update_word_occurrences()
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
        if not self._find_bar.isVisible():
            return
        self._find_bar.adjustSize()
        right_pad = 12 + (self._minimap.width() if self._minimap.isVisible() else 0)
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
