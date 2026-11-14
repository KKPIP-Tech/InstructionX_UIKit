# -*- coding: utf-8 -*-
"""区域高亮管理（CE_SPEC §2 / §3）。

以 ``QTextEdit.ExtraSelection`` 实现所有非语法层的高亮，按优先级合并：
选区 > 诊断 > 搜索当前命中 > 搜索命中 > 选中词 > 括号匹配 > 自定义层 > 当前行
（语法着色由 ``highlight.HighlightEngine`` 负责，不在此列）。

Qt 的 extraSelections 按列表顺序叠加绘制，因此本模块把低优先级层放在
列表前、高优先级层放在列表后，保证高优先级视觉上不被遮盖。

对外契约：

- ``RegionManager``：CodeEditor 内部持有一个实例，同时作为公共扩展点
  （``CodeEditor.set_region_highlight`` 委托到这里）。
- ``SEVERITY_COLORS``：诊断 severity -> 令牌键映射。
"""

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QTextEdit

from ..theme import T

__all__ = ["RegionManager", "SEVERITY_COLORS", "DIAGNOSTIC_SEVERITIES"]

#: 合法诊断级别
DIAGNOSTIC_SEVERITIES = ("error", "warning", "info")

#: 诊断级别 -> 令牌键
SEVERITY_COLORS = {
    "error": "color.danger",
    "warning": "color.warning",
    "info": "color.primary",
}

#: 内置层按优先级从低到高排列（合并为 extraSelections 的顺序）
_BUILTIN_ORDER = [
    "current_line",
    "bracket",
    "word",
    "multi",
    "search",
    "search_current",
    "diagnostic",
    # 选区必须最后绘制：diff 行底色 / 搜索底色 / 诊断等都可能是
    # ExtraSelection，若选区在它们之前会被整行底色盖住，表现为
    # 「鼠标拖选没反应」。这里用高对比前景/背景保证选区始终可见。
    "selection",
]


def _with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


class RegionManager:
    """区域高亮管理器。

    参数:
        text_area: 目标 ``QPlainTextEdit``（CodeEditor 的文本区）。

    范围一律使用文档字符偏移 ``(start, end)``（``end`` 开区间）。
    """

    def __init__(self, text_area):
        self._ta = text_area
        self._builtin = {name: [] for name in _BUILTIN_ORDER}
        self._custom = {}          # layer -> (selections, color)
        self._diagnostics = []     # 原始诊断项（供 gutter / minimap 查询）
        self._diag_by_line = {}    # line(1-based) -> 最重 severity
        # 最近一次设置的范围，供主题切换时按当前令牌重建
        self._current_pos = 0
        self._bracket_ranges = []
        self._word_ranges = []
        self._multi_ranges = []
        self._search_ranges = []
        self._search_current = None
        self._selection = (0, 0)

    # ------------------------------------------------------------------
    # 底层
    # ------------------------------------------------------------------
    def _make_selection(self, start: int, end: int, fmt: QTextCharFormat):
        doc = self._ta.document()
        start = max(0, min(start, doc.characterCount() - 1))
        end = max(start, min(end, doc.characterCount() - 1))
        sel = QTextEdit.ExtraSelection()
        cur = QTextCursor(doc)
        cur.setPosition(start)
        if end > start:
            cur.setPosition(end, QTextCursor.KeepAnchor)
        sel.cursor = cur
        sel.format = fmt
        return sel

    def rebuild(self) -> None:
        """合并所有层并刷新到文本区。"""
        sels = []
        sels.extend(self._builtin["current_line"])
        for layer, (items, _color) in self._custom.items():
            sels.extend(items)
        for name in _BUILTIN_ORDER[1:]:
            sels.extend(self._builtin[name])
        self._ta.setExtraSelections(sels)

    # ------------------------------------------------------------------
    # 当前行
    # ------------------------------------------------------------------
    def set_current_line(self, position: int) -> None:
        """高亮光标所在行（整行宽）。"""
        self._current_pos = int(position)
        fmt = QTextCharFormat()
        fmt.setBackground(_with_alpha(QColor(T("color.primary")), 18))
        fmt.setProperty(QTextFormat.FullWidthSelection, True)
        sel = self._make_selection(position, position, fmt)
        self._builtin["current_line"] = [sel]
        self.rebuild()

    # ------------------------------------------------------------------
    # 选区
    # ------------------------------------------------------------------
    def set_selection(self, start: int, end: int) -> None:
        """高亮原生选区（最后一个内置层，优先级最高）。"""
        self._selection = (int(start), int(end))
        if end <= start:
            self._builtin["selection"] = []
            self.rebuild()
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(T("color.primary")))
        fmt.setForeground(QColor(T("color.on.primary")))
        self._builtin["selection"] = [
            self._make_selection(start, end, fmt)
        ]
        self.rebuild()

    # ------------------------------------------------------------------
    # 括号匹配
    # ------------------------------------------------------------------
    def set_bracket_pair(self, ranges) -> None:
        """高亮匹配的括号对，``ranges`` 为 ``[(pos, pos+1), ...]``。"""
        self._bracket_ranges = list(ranges or [])
        fmt = QTextCharFormat()
        fmt.setBackground(_with_alpha(QColor(T("color.primary")), 60))
        fmt.setForeground(QColor(T("color.text.primary")))
        self._builtin["bracket"] = [
            self._make_selection(a, b, QTextCharFormat(fmt))
            for a, b in self._bracket_ranges
        ]
        self.rebuild()

    # ------------------------------------------------------------------
    # 选中词同词高亮
    # ------------------------------------------------------------------
    def set_word_occurrences(self, ranges) -> None:
        """高亮选中词的全部出现位置。"""
        self._word_ranges = list(ranges or [])
        fmt = QTextCharFormat()
        fmt.setBackground(_with_alpha(QColor(T("color.primary")), 45))
        self._builtin["word"] = [
            self._make_selection(a, b, QTextCharFormat(fmt))
            for a, b in self._word_ranges
        ]
        self.rebuild()

    # ------------------------------------------------------------------
    # 多光标（Ctrl+D）附加选区
    # ------------------------------------------------------------------
    def set_multi_selections(self, ranges) -> None:
        """Ctrl+D 多选区可视化（类选中底色；优先级介于 word 与 search 之间）。"""
        self._multi_ranges = list(ranges or [])
        fmt = QTextCharFormat()
        fmt.setBackground(_with_alpha(QColor(T("color.primary")), 90))
        self._builtin["multi"] = [
            self._make_selection(a, b, QTextCharFormat(fmt))
            for a, b in self._multi_ranges
        ]
        self.rebuild()

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def set_search_matches(self, ranges, current=None) -> None:
        """搜索命中高亮；``current`` 为当前命中 ``(start, end)`` 或 None。"""
        self._search_ranges = list(ranges or [])
        self._search_current = current
        fmt = QTextCharFormat()
        fmt.setBackground(_with_alpha(QColor(T("color.warning")), 70))
        self._builtin["search"] = [
            self._make_selection(a, b, QTextCharFormat(fmt))
            for a, b in self._search_ranges
        ]
        cur_sels = []
        if current is not None:
            cfmt = QTextCharFormat()
            cfmt.setBackground(_with_alpha(QColor(T("color.warning")), 170))
            cfmt.setForeground(QColor(T("color.text.primary")))
            cur_sels = [self._make_selection(current[0], current[1], cfmt)]
        self._builtin["search_current"] = cur_sels
        self.rebuild()

    # ------------------------------------------------------------------
    # 诊断（波浪线）
    # ------------------------------------------------------------------
    def set_diagnostics(self, items) -> None:
        """设置诊断列表。

        每项: ``{"line", "column", "length", "severity", "message"}``；
        line / column 为 1-based。以 ``WaveUnderline`` 波浪线呈现
        （QSS 无法做到波浪下划线，必须用 QTextCharFormat）。
        """
        self._diagnostics = list(items or [])
        self._diag_by_line = {}
        sels = []
        doc = self._ta.document()
        for item in self._diagnostics:
            line = int(item.get("line", 1))
            col = int(item.get("column", 1))
            length = max(1, int(item.get("length", 1)))
            severity = str(item.get("severity", "error"))
            if severity not in SEVERITY_COLORS:
                severity = "info"
            # 只有真实存在的行才进入 gutter / 诊断映射，避免公开 API 传入
            # 超行号后留下永远画不出来的幽灵诊断。
            block = doc.findBlockByNumber(max(0, line - 1))
            if not block.isValid():
                continue
            order = {"error": 3, "warning": 2, "info": 1}
            prev = self._diag_by_line.get(line)
            if prev is None or order[severity] > order[prev]:
                self._diag_by_line[line] = severity
            max_col = max(0, block.length() - 1)
            start = block.position() + min(max(0, col - 1), max_col)
            end = min(start + length, block.position() + block.length() - 1)
            if end <= start:
                end = min(start + 1,
                          block.position() + block.length() - 1)
                if end <= start:
                    continue
            color = QColor(T(SEVERITY_COLORS[severity]))
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            fmt.setUnderlineColor(color)
            fmt.setToolTip(str(item.get("message", "")))
            sels.append(self._make_selection(start, end, fmt))
        self._builtin["diagnostic"] = sels
        self.rebuild()

    def diagnostics(self) -> list:
        """当前诊断项列表（原始 dict 副本）。"""
        return list(self._diagnostics)

    def diagnostic_lines(self) -> dict:
        """``{line(1-based): severity}``，供 gutter / minimap 着色。"""
        return dict(self._diag_by_line)

    @staticmethod
    def severity_color(severity: str) -> QColor:
        """诊断级别对应颜色（实时取令牌）。"""
        return QColor(T(SEVERITY_COLORS.get(severity, "color.primary")))

    # ------------------------------------------------------------------
    # 自定义层（公共扩展点）
    # ------------------------------------------------------------------
    def clear_all(self) -> None:
        """清空全部内置层、自定义层与诊断状态（文档整体替换时调用）。"""
        for name in self._builtin:
            self._builtin[name] = []
        self._custom.clear()
        self._diagnostics = []
        self._diag_by_line = {}
        self._current_pos = 0
        self._bracket_ranges = []
        self._word_ranges = []
        self._multi_ranges = []
        self._search_ranges = []
        self._search_current = None
        self._selection = (0, 0)
        self.rebuild()

    def refresh_theme(self) -> None:
        """按当前主题令牌重建全部内置层（语法层由高亮引擎自理）。"""
        self.set_current_line(self._current_pos)
        self.set_bracket_pair(self._bracket_ranges)
        self.set_word_occurrences(self._word_ranges)
        self.set_multi_selections(self._multi_ranges)
        self.set_search_matches(self._search_ranges, self._search_current)
        self.set_diagnostics(self._diagnostics)
        self.set_selection(*self._selection)

    def set_region_highlight(self, layer: str, ranges, color: str) -> None:
        """设置任意自定义高亮层。

        参数:
            layer: 层名（同名覆盖）。
            ranges: ``[(start, end), ...]`` 文档字符偏移区间。
            color: 颜色（hex / 颜色名），以半透明底色呈现。
        """
        if not ranges:
            self._custom.pop(layer, None)
            self.rebuild()
            return
        fmt = QTextCharFormat()
        fmt.setBackground(_with_alpha(QColor(color), 70))
        sels = [
            self._make_selection(a, b, QTextCharFormat(fmt)) for a, b in ranges
        ]
        self._custom[layer] = (sels, color)
        self.rebuild()

    def clear_layer(self, layer: str) -> None:
        """清除某自定义层。"""
        if layer in self._custom:
            del self._custom[layer]
            self.rebuild()

    def set_region_formats(self, layer: str, items) -> None:
        """完全自定义格式的区域层（同名覆盖）。

        与 :meth:`set_region_highlight`（统一半透明底色）不同，这里每项
        自带 :class:`QTextCharFormat`，可表达字符级 diff 高亮盒
        （加深底 + ``TextOutlineProperty`` 细边框）等复杂格式。

        参数:
            layer: 层名（同名覆盖；空列表清除该层）。
            items: ``[(start, end, QTextCharFormat), ...]`` 文档字符偏移
                区间（``end`` 开区间）+ 各自格式。
        """
        if not items:
            self._custom.pop(layer, None)
            self.rebuild()
            return
        sels = [
            self._make_selection(a, b, QTextCharFormat(f)) for a, b, f in items
        ]
        self._custom[layer] = (sels, "")
        self.rebuild()

    def total_selections(self) -> int:
        """当前 extraSelections 总数（测试 / 调试）。"""
        return len(self._ta.extraSelections())
