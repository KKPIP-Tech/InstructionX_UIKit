# -*- coding: utf-8 -*-
"""DiffEditor 差异对比控件（CE_SPEC §4，E3）。

组合两个 / 一个 :class:`CodeEditor`（复用 E1，只读 + 语法高亮）实现
行级 diff 的三种视图：

- **并排**（``"side-by-side"``）：左右两栏（旧 / 新），删除行左侧
  danger 半透明底、插入行右侧 success 半透明底、replace 行两侧
  warning 半透明底；两侧用等效空行占位保证 equal 块垂直对齐，
  垂直滚动同步；每栏顶部显示标题与统计徽标。
- **内联**（``"inline"``）：单编辑器，删除行（danger 底 + 行首自绘
  ``-``）与插入行（success 底 + ``+``）按 diff 序穿插，等宽前缀列
  由视口左缘的自绘叠加层绘制（不污染文档文本，语法高亮不受影响）。
- **自动**（``"auto"``）：容器宽度小于 ``auto_breakpoint``（缺省
  900px）时内联，否则并排；``resizeEvent`` 中平滑切换并保持当前
  hunk 定位。

diff 模型：``difflib.SequenceMatcher`` opcodes → hunk（equal 之外的
delete / insert / replace；相邻非 equal 操作之间间隔不超过
``_MERGE_GAP`` 行的 equal 小块会被吸收进同一个 hunk）。

行底色通过 ``QTextBlockFormat`` 背景实现（与 CodeEditor 的
ExtraSelections 区域层互不干扰），主题切换时实时取 ``T()`` 重刷。
"""

import difflib
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QPainter,
    QPen,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..components.button import Button
from ..components.segmented import SegmentedControl
from ..icons import get_icon
from ..theme import T, ThemeManager
from .editor import CodeEditor

__all__ = ["DiffEditor", "DiffHunk"]

#: 相邻变更之间不超过该行数的 equal 间隔被合并进同一 hunk
_MERGE_GAP = 1

#: 行底色透明度
_BG_ALPHA = 70

#: 占位区斜线阴影（hatch）：对角斜线纹理，方向 /，瓦片边长（px）。
#: 45° 斜线水平/垂直周期 = 瓦片边长，垂直间距 ≈ 边长/√2（9 → 6.4px）
_HATCH_TILE = 9
#: hatch 线条透明度（≈40%）
_HATCH_ALPHA = 102

#: 字符级 diff 高亮盒背景透明度（行底色之上再加深一档）
_CHAR_BG_ALPHA = 110

#: 中央槽宽（并排模式回滚箭头列）
_SLOT_W = 28

#: 右缘 overview ruler 宽
_RULER_W = 14

_VIEW_SIDE = "side-by-side"
_VIEW_INLINE = "inline"

#: QTextFormat 文本描边属性：Qt5 名 TextOutlineProperty，Qt6 改名
#: OutlinePen（QTextFormat.Property 作用域枚举），按可用性取值
_TEXT_OUTLINE = (
    getattr(QTextFormat, "TextOutlineProperty", None)
    or getattr(QTextFormat.Property, "TextOutlineProperty", None)
    or QTextFormat.Property.OutlinePen
)


@dataclass
class DiffHunk:
    """一个差异块（原始文档行区间，0-based，end 开区间）。

    ``kind`` 为 ``"delete"`` / ``"insert"`` / ``"replace"``；
    ``side_line`` / ``inline_line`` 为渲染后该 hunk 在对应视图中的
    起始视图行（0-based，由 DiffEditor 填充）。
    """

    kind: str
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    side_line: int = 0
    inline_line: int = 0
    #: 组内原始 opcodes（供渲染保留内部 equal 间隔）
    ops: list = field(default_factory=list)

    @property
    def old_count(self) -> int:
        return self.old_end - self.old_start

    @property
    def new_count(self) -> int:
        return self.new_end - self.new_start


def build_hunks(old_lines, new_lines, merge_gap=_MERGE_GAP):
    """由两段文本的行列表构建 hunk 列表（equal 不产生 hunk）。

    相邻变更间不超过 ``merge_gap`` 行的 equal 间隔会被吸收；
    吸收后组内同时含删除与插入行时归类为 ``replace``。
    """
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    ops = sm.get_opcodes()
    hunks = []
    i = 0
    n = len(ops)
    while i < n:
        tag, a0, a1, b0, b1 = ops[i]
        if tag == "equal":
            i += 1
            continue
        members = [ops[i]]
        ga1, gb1 = a1, b1
        j = i + 1
        while j < n:
            t2, a20, a21, b20, b21 = ops[j]
            if t2 == "equal":
                # 小间隔且后面仍接变更 → 吸收进本 hunk
                if (a21 - a20) <= merge_gap and j + 1 < n \
                        and ops[j + 1][0] != "equal":
                    members.append(ops[j])
                    ga1, gb1 = a21, b21
                    j += 1
                    continue
                break
            members.append(ops[j])
            ga1, gb1 = a21, b21
            j += 1
        has_old = any(t in ("delete", "replace") for t, *_ in members)
        has_new = any(t in ("insert", "replace") for t, *_ in members)
        if has_old and has_new:
            kind = "replace"
        elif has_old:
            kind = "delete"
        else:
            kind = "insert"
        hunks.append(DiffHunk(
            kind=kind,
            old_start=members[0][1], old_end=ga1,
            new_start=members[0][3], new_end=gb1,
            ops=list(members),
        ))
        i = j
    return hunks


def diff_stats(old_lines, new_lines):
    """``(新增行数, 删除行数)``：replace 同时计旧行删除与新行新增。"""
    adds = dels = 0
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "insert":
            adds += b1 - b0
        elif tag == "delete":
            dels += a1 - a0
        elif tag == "replace":
            dels += a1 - a0
            adds += b1 - b0
    return adds, dels


def _char_segments(old_line: str, new_line: str):
    """replace 行对的字符级比较（difflib）。

    返回 ``(old_segments, new_segments)``：各自行内变更字符的列区间
    ``[(col_start, col_end), ...]``（0-based，end 开区间）。
    """
    sm = difflib.SequenceMatcher(None, old_line, new_line, autojunk=False)
    olds, news = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1 and tag in ("replace", "delete"):
            olds.append((i1, i2))
        if j2 > j1 and tag in ("replace", "insert"):
            news.append((j1, j2))
    return olds, news


class _InlinePrefixOverlay(QWidget):
    """内联视图的等宽前缀列自绘叠加层。

    父控件为内联编辑器的文本区（``QPlainTextEdit``），绘制在
    ``setViewportMargins`` 让出的左侧条带内：删除行 ``-``、插入行
    ``+``，并对变更行补齐与行底同色的条带底色。不接收鼠标事件。
    """

    def __init__(self, text_area, owner: "DiffEditor"):
        super().__init__(text_area)
        self._ta = text_area
        self._owner = owner
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_area.installEventFilter(self)
        text_area.verticalScrollBar().valueChanged.connect(self.update)
        self._sync_geometry()

    # ------------------------------------------------------------------
    def prefix_width(self) -> int:
        fm = QFontMetrics(self._ta.font())
        return fm.horizontalAdvance(" ") * 2 + 10

    def _sync_geometry(self) -> None:
        self.setGeometry(0, 0, self.prefix_width(), self._ta.height())

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        from PySide6.QtCore import QEvent

        if obj is self._ta and event.type() in (QEvent.Resize, QEvent.Show):
            self._sync_geometry()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        kinds = self._owner._inline_kinds
        if not kinds:
            return
        ta = self._ta
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        fm = ta.fontMetrics()
        base_y = ta.viewport().geometry().top()
        offset = ta.contentOffset()
        block = ta.firstVisibleBlock()
        vh = ta.viewport().height()
        while block.isValid():
            geo = ta.blockBoundingGeometry(block).translated(offset)
            top = geo.top()
            if top > vh:
                break
            bn = block.blockNumber()
            if block.isVisible() and 0 <= bn < len(kinds):
                kind = kinds[bn]
                if kind in ("delete", "insert"):
                    color = self._owner._kind_color(kind)
                    if color is not None:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QBrush(color))
                        p.drawRect(0, int(base_y + top),
                                   self.width(), int(geo.height() + 1))
                    ch = "-" if kind == "delete" else "+"
                    p.setPen(QColor(T("color.text.secondary")))
                    p.drawText(
                        0, int(base_y + top), self.width(),
                        int(geo.height()),
                        Qt.AlignCenter, ch)
            block = block.next()
        p.end()


class _RevertSlot(QWidget):
    """并排模式两编辑器之间的中央槽（VS Code 回滚箭头列）。

    每个 hunk 在对应垂直位置（以左编辑器块几何定位）绘制一个
    回滚箭头按钮（``arrow_left`` 图标）；点击后由 DiffEditor 执行
    ``revert_hunk``（右侧新文档该 hunk 恢复为左侧旧内容）。
    背景透明自绘，滚动时经 ``update()`` 同步重绘。
    """

    def __init__(self, owner: "DiffEditor"):
        super().__init__(owner._side_page)
        self._owner = owner
        self._hover = -1
        self._btn_rects = {}          # hunk index -> QRect（本次绘制）
        self.setFixedWidth(_SLOT_W)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        for ed in (owner._ed_left, owner._ed_right):
            ed.text_area().verticalScrollBar().valueChanged.connect(
                self.update)

    # ------------------------------------------------------------------
    def _hunk_button_rect(self, hunk):
        """hunk 对应的按钮矩形（槽坐标系）；不可见返回 None。"""
        ta = self._owner._ed_left.text_area()
        block = ta.document().findBlockByNumber(hunk.side_line)
        if not block.isValid():
            return None
        geo = ta.blockBoundingGeometry(block).translated(ta.contentOffset())
        vp_top = self.mapFromGlobal(
            ta.viewport().mapToGlobal(QPoint(0, 0))).y()
        y = vp_top + geo.top()
        line_h = max(18, geo.height())
        if y + line_h < vp_top or y > vp_top + ta.viewport().height():
            return None
        side = min(20, int(line_h) - 2)
        return QRect((_SLOT_W - side) // 2, int(y) + 1, side, side)

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 两侧细分隔线
        p.setPen(QColor(T("color.border")))
        p.drawLine(0, 0, 0, self.height())
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        self._btn_rects = {}
        if not self._owner._revert_enabled:
            p.end()
            return
        icon = get_icon("arrow_left", 12,
                        QColor(T("color.text.secondary")))
        for i, hunk in enumerate(self._owner._hunks):
            r = self._hunk_button_rect(hunk)
            if r is None:
                continue
            self._btn_rects[i] = r
            p.setPen(QPen(QColor(T("color.border.strong"))))
            bg = QColor(T("color.bg.elevated" if i != self._hover
                          else "color.bg.subtle"))
            p.setBrush(QBrush(bg))
            p.drawRoundedRect(r, 4, 4)
            icon.paint(p, r.adjusted(4, 4, -4, -4))
        p.end()

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            for i, r in self._btn_rects.items():
                if r.contains(pos):
                    self._owner.revert_hunk(i)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt 命名
        pos = event.position().toPoint()
        hover = -1
        for i, r in self._btn_rects.items():
            if r.contains(pos):
                hover = i
                break
        if hover != self._hover:
            self._hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt 命名
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(event)


class _OverviewRuler(QWidget):
    """右缘 overview ruler：按 hunk 在新文档中的位置绘制变更刻度。

    插入 → success、删除 → danger、replace → warning（主题令牌色），
    透明自绘，随主题 / 文档 / 视图切换重绘。
    """

    def __init__(self, owner: "DiffEditor"):
        super().__init__(owner)
        self._owner = owner
        self.setFixedWidth(_RULER_W)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        owner = self._owner
        total = max(1, len(owner._new_lines))
        h = self.height()
        if h <= 0 or not owner._hunks:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        token = {"insert": "color.success", "delete": "color.danger",
                 "replace": "color.warning"}
        for hunk in owner._hunks:
            y0 = hunk.new_start / total * h
            lines = max(hunk.new_count, 1)
            rh = max(3.0, lines / total * h)
            c = QColor(T(token.get(hunk.kind, "color.warning")))
            p.setBrush(QBrush(c))
            p.drawRect(2, int(y0), self.width() - 4, int(rh))
        p.end()


class DiffEditor(QWidget):
    """行级 diff 对比控件（并排 / 内联 / 自动，CE_SPEC §4）。"""

    #: 当前 hunk 变化信号 ``(index, total)``，index 为 0-based
    hunk_changed = Signal(int, int)
    #: 某 hunk 经中央槽回滚箭头（或 ``revert_hunk``）回滚 ``(index)``
    hunk_reverted = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DiffEditor")
        self._mode = _VIEW_SIDE
        self._effective = _VIEW_SIDE
        self._auto_breakpoint = 900
        self._old_lines = []
        self._new_lines = []
        self._language = "plain"
        self._old_title = "原始"
        self._new_title = "修改后"
        self._hunks = []
        self._current = -1
        self._adds = 0
        self._dels = 0
        self._syncing_scroll = False
        self._bg_lines = {}          # editor -> 已着底色的块号（供清除）
        self._side_left_kinds = []   # 并排左栏每视图行类型
        self._side_right_kinds = []
        self._inline_kinds = []
        # 每视图行的真实文件行号（1-based；占位行为 None）——供 gutter
        # 行号 provider 显示与 VS Code 一致的原始行号
        self._side_left_labels = []
        self._side_right_labels = []
        self._inline_labels = []
        # 内联视图双列行号：(左=旧文件, 右=新文件, marker)；VS Code 样式
        self._inline_dual = []
        # 字符级 diff：editor -> {块号: [(col_start, col_end, family)]}
        self._char_ranges = {}
        self._char_diff_enabled = True
        self._revert_enabled = True
        self._hatch_brush = None     # hatch 纹理画刷（按主题缓存）

        # -- 工具行 ------------------------------------------------------
        self._btn_prev = Button("↑ 上一个", size="sm")
        self._btn_next = Button("下一个 ↓", size="sm")
        self._btn_prev.clicked.connect(self.prev_hunk)
        self._btn_next.clicked.connect(self.next_hunk)
        self._hunk_label = QLabel("0/0")
        self._stats_label = QLabel("+0 −0")
        self._seg = SegmentedControl(["并排", "内联", "自动"], current=0,
                                     size="sm")
        self._seg.currentChanged.connect(self._on_seg_changed)

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(8)
        bar.addWidget(self._btn_prev)
        bar.addWidget(self._btn_next)
        bar.addWidget(self._hunk_label)
        bar.addWidget(self._stats_label)
        bar.addStretch(1)
        bar.addWidget(self._seg)

        # -- 并排页 ------------------------------------------------------
        self._ed_left = self._make_editor()
        self._ed_right = self._make_editor()
        self._title_left = QLabel()
        self._title_right = QLabel()
        self._badge_left = QLabel()
        self._badge_right = QLabel()
        self._side_page = QWidget()
        side_lay = QHBoxLayout(self._side_page)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(1)
        side_lay.addLayout(self._make_column(
            self._title_left, self._badge_left, self._ed_left), 1)
        # 中央槽（回滚箭头列，VS Code 并排 diff 样式）
        self._slot = _RevertSlot(self)
        side_lay.addWidget(self._slot)
        side_lay.addLayout(self._make_column(
            self._title_right, self._badge_right, self._ed_right), 1)

        # 占位区斜线阴影（hatch）：文本区视口叠加绘制钩子，与文本
        # 同一 paint pass 执行，滚动严格同步、无额外控件开销
        self._ed_left.set_paint_hook(
            lambda p, ta: self._paint_hatch(p, ta, self._side_left_kinds))
        self._ed_right.set_paint_hook(
            lambda p, ta: self._paint_hatch(p, ta, self._side_right_kinds))

        # 滚动同步
        self._ed_left.text_area().verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self._ed_left, self._ed_right, v))
        self._ed_right.text_area().verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self._ed_right, self._ed_left, v))

        # -- 内联页 ------------------------------------------------------
        self._ed_inline = self._make_editor()
        ta = self._ed_inline.text_area()
        self._prefix_overlay = _InlinePrefixOverlay(ta, self)
        ta.setViewportMargins(self._prefix_overlay.prefix_width(), 0, 0, 0)
        self._inline_page = QWidget()
        inline_lay = QVBoxLayout(self._inline_page)
        inline_lay.setContentsMargins(0, 0, 0, 0)
        inline_lay.setSpacing(0)
        inline_lay.addWidget(self._ed_inline, 1)

        # -- 总布局 ------------------------------------------------------
        self._stack = QStackedLayout()
        self._stack.addWidget(self._side_page)
        self._stack.addWidget(self._inline_page)

        # 右缘 overview ruler（变更刻度条）
        self._ruler = _OverviewRuler(self)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addLayout(self._stack, 1)
        row.addWidget(self._ruler)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(bar)
        root.addLayout(row, 1)

        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._refresh_style()

    # ------------------------------------------------------------------
    # 构建辅助
    # ------------------------------------------------------------------
    def _make_editor(self) -> CodeEditor:
        ed = CodeEditor()
        ed.set_readonly(True)
        ed.set_minimap_visible(False)
        return ed

    def _make_column(self, title: QLabel, badge: QLabel,
                     editor: CodeEditor) -> QVBoxLayout:
        title.setObjectName("DiffColumnTitle")
        badge.setObjectName("DiffColumnBadge")
        head = QHBoxLayout()
        head.setContentsMargins(10, 4, 10, 4)
        head.setSpacing(8)
        head.addWidget(title)
        head.addWidget(badge)
        head.addStretch(1)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addLayout(head)
        col.addWidget(editor, 1)
        return col

    # ------------------------------------------------------------------
    # 公共 API（CE_SPEC §4 契约）
    # ------------------------------------------------------------------
    def set_documents(self, old_text: str, new_text: str,
                      language: str = "plain",
                      old_title: str = "原始",
                      new_title: str = "修改后") -> None:
        """设置对比文档并重建 diff 视图（并排与内联两页均渲染）。"""
        self._old_lines = old_text.split("\n")
        self._new_lines = new_text.split("\n")
        self._language = language or "plain"
        self._old_title = old_title
        self._new_title = new_title
        self._rebuild()

    def old_text(self) -> str:
        """当前旧（左）文档文本。"""
        return "\n".join(self._old_lines)

    def new_text(self) -> str:
        """当前新（右）文档文本（回滚后会更新）。"""
        return "\n".join(self._new_lines)

    def _rebuild(self) -> None:
        """按当前 ``_old_lines`` / ``_new_lines`` 重建 diff 两视图。"""
        self._hunks = build_hunks(self._old_lines, self._new_lines)
        self._adds, self._dels = diff_stats(self._old_lines, self._new_lines)

        self._title_left.setText(self._old_title)
        self._title_right.setText(self._new_title)
        self._badge_left.setText(f"−{self._dels}")
        self._badge_right.setText(f"+{self._adds}")
        self._stats_label.setText(f"+{self._adds} −{self._dels}")

        self._render_side()
        self._render_inline()

        self._current = 0 if self._hunks else -1
        self._update_hunk_label()
        self._apply_effective_mode(scroll=False)
        if self._hunks:
            self._scroll_to_hunk(self._current)
        self._slot.update()
        self._ruler.update()

    # ------------------------------------------------------------------
    # hunk 回滚（VS Code 中央槽箭头）
    # ------------------------------------------------------------------
    def set_revert_enabled(self, on: bool) -> None:
        """是否启用中央槽回滚箭头（默认 True；仅并排模式有中央槽）。"""
        self._revert_enabled = bool(on)
        self._slot.setVisible(self._revert_enabled)
        self._slot.update()

    def revert_enabled(self) -> bool:
        return self._revert_enabled

    def revert_hunk(self, index: int) -> bool:
        """将右侧（新）文档第 ``index`` 个 hunk 恢复为左侧（旧）内容。

        重建 diff 视图并发射 ``hunk_reverted(index)``；index 越界返回
        ``False`` 且不发射信号。
        """
        if not (0 <= index < len(self._hunks)):
            return False
        hunk = self._hunks[index]
        new_lines = list(self._new_lines)
        new_lines[hunk.new_start:hunk.new_end] = \
            self._old_lines[hunk.old_start:hunk.old_end]
        self._new_lines = new_lines
        self._rebuild()
        self.hunk_reverted.emit(index)
        return True

    def set_view_mode(self, mode: str) -> None:
        """设置视图模式：``"side-by-side"`` / ``"inline"`` / ``"auto"``。"""
        if mode not in (_VIEW_SIDE, _VIEW_INLINE, "auto"):
            raise ValueError(f"未知视图模式: {mode!r}")
        if mode == self._mode:
            return
        self._mode = mode
        seg_index = {_VIEW_SIDE: 0, _VIEW_INLINE: 1, "auto": 2}[mode]
        if self._seg.current() != seg_index:
            self._seg.set_current(seg_index, animate=False)
        self._apply_effective_mode(scroll=True)

    def view_mode(self) -> str:
        """实际生效的视图模式（auto 下按当前宽度求值）。"""
        if self._mode == "auto":
            return (_VIEW_INLINE if self.width() < self._auto_breakpoint
                    else _VIEW_SIDE)
        return self._mode

    def set_auto_breakpoint(self, px: int) -> None:
        """auto 模式宽度断点（px）：容器宽小于该值时切换为内联。"""
        self._auto_breakpoint = max(1, int(px))
        if self._mode == "auto":
            self._apply_effective_mode(scroll=True)

    def auto_breakpoint(self) -> int:
        return self._auto_breakpoint

    def hunk_count(self) -> int:
        return len(self._hunks)

    def current_hunk(self) -> int:
        """当前 hunk 下标（0-based；无 hunk 时 -1）。"""
        return self._current

    def next_hunk(self) -> None:
        """跳到下一个 hunk（循环回绕）。"""
        if self._hunks:
            self._scroll_to_hunk((self._current + 1) % len(self._hunks),
                                 emit=True)

    def prev_hunk(self) -> None:
        """跳到上一个 hunk（循环回绕）。"""
        if self._hunks:
            self._scroll_to_hunk((self._current - 1) % len(self._hunks),
                                 emit=True)

    # ------------------------------------------------------------------
    # 测试 / 调试辅助
    # ------------------------------------------------------------------
    def side_editors(self):
        """并排模式左右 ``(旧, 新)`` 两个 CodeEditor。"""
        return self._ed_left, self._ed_right

    def inline_editor(self) -> CodeEditor:
        return self._ed_inline

    def side_line_kinds(self):
        """并排两侧每视图行类型：equal/delete/insert/replace/placeholder。"""
        return list(self._side_left_kinds), list(self._side_right_kinds)

    def inline_line_kinds(self) -> list:
        """内联视图每行类型：equal/delete/insert。"""
        return list(self._inline_kinds)

    def inline_prefixes(self) -> list:
        """内联视图每行前缀字符（``"-"`` / ``"+"`` / ``" "``）。"""
        return [{"delete": "-", "insert": "+"}.get(k, " ")
                for k in self._inline_kinds]

    def side_line_labels(self):
        """并排两侧每视图行真实文件行号（1-based；占位行为 None）。"""
        return list(self._side_left_labels), list(self._side_right_labels)

    def inline_line_labels(self) -> list:
        """内联视图每行行号：删除 / equal 行=旧文件行号，插入行=新文件行号。"""
        return list(self._inline_labels)

    def inline_dual_labels(self) -> list:
        """内联视图双列行号：每行 ``(left, right, marker)``。

        equal 行 ``("旧号", "新号", None)``；删除行 ``("旧号−", None, "−")``；
        插入行 ``(None, "新号+", "+")``（VS Code 内联 diff 双列样式）。
        """
        return list(self._inline_dual)

    def set_char_diff_enabled(self, on: bool) -> None:
        """字符级 diff 高亮盒（replace 行对内变更字符段）开关，默认 True。"""
        self._char_diff_enabled = bool(on)
        self._apply_char_highlights()

    def char_diff_enabled(self) -> bool:
        return self._char_diff_enabled

    def set_overview_ruler_visible(self, on: bool) -> None:
        """右缘 overview ruler（变更刻度条）开关，默认 True。"""
        self._ruler.setVisible(bool(on))
        self._ruler.update()

    def overview_ruler_visible(self) -> bool:
        return self._ruler.isVisibleTo(self)

    def revert_slot(self) -> QWidget:
        """并排模式中央槽控件（回滚箭头列；测试 / 调试用）。"""
        return self._slot

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    @staticmethod
    def _labels_provider(labels):
        """由标签表构造行号 provider（越界返回 None，即不绘制）。"""
        def provider(display_line):
            if 1 <= display_line <= len(labels):
                return labels[display_line - 1]
            return None
        return provider

    @staticmethod
    def _marker_provider(kinds, mark_kinds, marker):
        """由行类型表构造行标记 provider（VS Code 并排符号列）。

        行类型属于 ``mark_kinds`` 时返回 ``marker``，否则 None。
        """
        kinds = list(kinds)

        def provider(display_line):
            if 1 <= display_line <= len(kinds) \
                    and kinds[display_line - 1] in mark_kinds:
                return marker
            return None
        return provider

    @staticmethod
    def _dual_provider(dual):
        """由双列标签表构造 gutter 双列 provider（越界返回 None）。"""
        dual = list(dual)

        def provider(display_line):
            if 1 <= display_line <= len(dual):
                return dual[display_line - 1]
            return None
        return provider

    # ------------------------------------------------------------------
    # 占位区斜线阴影（hatch）
    # ------------------------------------------------------------------
    def _hatch_texture(self) -> QBrush:
        """hatch 纹理画刷：方向 / 的对角斜线，主题令牌色 ≈40% alpha。

        按主题缓存（theme_changed 时置 None 重建）。
        """
        if self._hatch_brush is None:
            s = _HATCH_TILE
            pm = QPixmap(s, s)
            pm.fill(Qt.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.Antialiasing, False)
            c = QColor(T("color.border.strong"))
            c.setAlpha(_HATCH_ALPHA)
            pp.setPen(QPen(c, 1))
            pp.drawLine(0, s - 1, s - 1, 0)   # "/" 方向
            pp.end()
            self._hatch_brush = QBrush(pm)
        return self._hatch_brush

    def _paint_hatch(self, p: QPainter, ta, kinds) -> None:
        """文本区视口叠加绘制：连续 placeholder 行合并为一块 hatch。

        在文本区同一 paint pass 内执行；画刷纹理锚定在文档坐标系
        （painter 平移 contentOffset），滚动时斜线与文本严格同步。
        占位行本身无文本、无行号（label provider 返回 None）。
        """
        if "placeholder" not in kinds:
            return
        offset = ta.contentOffset()
        vh = ta.viewport().height()
        width = ta.viewport().width() - offset.x()
        p.save()
        p.translate(offset.x(), offset.y())
        p.setPen(Qt.NoPen)
        p.setBrush(self._hatch_texture())
        block = ta.firstVisibleBlock()
        run_top = None
        run_bottom = 0.0
        while block.isValid():
            geo = ta.blockBoundingGeometry(block)  # 文档坐标
            top, height = geo.top(), geo.height()
            if top + offset.y() > vh:
                break
            bn = block.blockNumber()
            is_ph = block.isVisible() and 0 <= bn < len(kinds) \
                and kinds[bn] == "placeholder"
            if is_ph:
                if run_top is not None and abs(top - run_bottom) <= 1.0:
                    run_bottom = top + height
                else:
                    if run_top is not None:
                        p.drawRect(QRect(0, int(run_top), width,
                                         int(run_bottom - run_top)))
                    run_top, run_bottom = top, top + height
            elif run_top is not None:
                p.drawRect(QRect(0, int(run_top), width,
                                 int(run_bottom - run_top)))
                run_top = None
            block = block.next()
        if run_top is not None:
            p.drawRect(QRect(0, int(run_top), width,
                             int(run_bottom - run_top)))
        p.restore()

    # ------------------------------------------------------------------
    # 字符级 diff 高亮盒（加深底 + TextOutlineProperty 细边框）
    # ------------------------------------------------------------------
    @staticmethod
    def _char_format(family: str) -> QTextCharFormat:
        """变更字符段格式：背景比行底色加深一档 + 1px 细边框。

        颜色随行类型：删除侧 danger 系、插入侧 success 系。
        """
        token = "color.danger" if family == "delete" else "color.success"
        base = QColor(T(token))
        bg = QColor(base)
        bg.setAlpha(_CHAR_BG_ALPHA)
        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(bg))
        fmt.setProperty(_TEXT_OUTLINE, QPen(base, 1))
        return fmt

    def _apply_char_highlights(self) -> None:
        """把缓存的字符级变更段写为 ``diff_char`` 自定义格式层。

        主题切换 / set_documents / 回滚后重刷；关闭开关时清空各层。
        """
        for editor, per_block in list(self._char_ranges.items()):
            try:
                rm = editor.region_manager()
            except RuntimeError:
                continue
            if not self._char_diff_enabled or not per_block:
                rm.set_region_formats("diff_char", [])
                continue
            doc = editor.text_area().document()
            items = []
            fmt_cache = {}
            for bn, segs in per_block.items():
                block = doc.findBlockByNumber(bn)
                if not block.isValid():
                    continue
                for c1, c2, family in segs:
                    if c2 <= c1:
                        continue
                    fmt = fmt_cache.get(family)
                    if fmt is None:
                        fmt = fmt_cache[family] = self._char_format(family)
                    items.append((block.position() + c1,
                                  block.position() + c2, fmt))
            rm.set_region_formats("diff_char", items)

    def _render_side(self) -> None:
        """构建并排两侧文本（含占位空行）并填充行类型表 / 行号表。

        行号对齐 VS Code：左栏显示旧文件真实行号、右栏显示新文件
        真实行号，占位空行无行号。
        """
        left_lines, right_lines = [], []
        left_kinds, right_kinds = [], []
        left_labels, right_labels = [], []
        char_left, char_right = {}, {}   # bn -> [(c1, c2)] 字符级变更段
        old, new = self._old_lines, self._new_lines
        prev_old = prev_new = 0

        def emit_equal(a0, a1, b0):
            for k in range(a1 - a0):
                left_lines.append(old[a0 + k])
                right_lines.append(new[b0 + k])
                left_kinds.append("equal")
                right_kinds.append("equal")
                left_labels.append(a0 + k + 1)
                right_labels.append(b0 + k + 1)

        for hunk in self._hunks:
            emit_equal(prev_old, hunk.old_start, prev_new)
            hunk.side_line = len(left_lines)
            for tag, a0, a1, b0, b1 in hunk.ops:
                if tag == "equal":  # 被合并吸收的小间隔
                    emit_equal(a0, a1, b0)
                elif tag == "delete":
                    for k in range(a1 - a0):
                        left_lines.append(old[a0 + k])
                        right_lines.append("")
                        left_kinds.append("delete")
                        right_kinds.append("placeholder")
                        left_labels.append(a0 + k + 1)
                        right_labels.append(None)
                elif tag == "insert":
                    for k in range(b1 - b0):
                        left_lines.append("")
                        right_lines.append(new[b0 + k])
                        left_kinds.append("placeholder")
                        right_kinds.append("insert")
                        left_labels.append(None)
                        right_labels.append(b0 + k + 1)
                else:  # replace：逐行配对，余量补占位
                    old_n, new_n = a1 - a0, b1 - b0
                    for k in range(max(old_n, new_n)):
                        bn = len(left_lines)
                        if k < old_n:
                            left_lines.append(old[a0 + k])
                            left_kinds.append(
                                "replace" if k < new_n else "delete")
                            left_labels.append(a0 + k + 1)
                        else:
                            left_lines.append("")
                            left_kinds.append("placeholder")
                            left_labels.append(None)
                        if k < new_n:
                            right_lines.append(new[b0 + k])
                            right_kinds.append(
                                "replace" if k < old_n else "insert")
                            right_labels.append(b0 + k + 1)
                        else:
                            right_lines.append("")
                            right_kinds.append("placeholder")
                            right_labels.append(None)
                        # 字符级 diff：配对行做 difflib 字符比较
                        if k < old_n and k < new_n:
                            segs_old, segs_new = _char_segments(
                                old[a0 + k], new[b0 + k])
                            if segs_old:
                                char_left[bn] = segs_old
                            if segs_new:
                                char_right[bn] = segs_new
            prev_old, prev_new = hunk.old_end, hunk.new_end
        emit_equal(prev_old, len(old), prev_new)

        self._side_left_kinds = left_kinds
        self._side_right_kinds = right_kinds
        self._side_left_labels = left_labels
        self._side_right_labels = right_labels
        self._ed_left.set_language(self._language)
        self._ed_right.set_language(self._language)
        self._ed_left.set_line_label_provider(
            self._labels_provider(left_labels))
        self._ed_right.set_line_label_provider(
            self._labels_provider(right_labels))
        # 行号旁变更符号：左栏删除/替换行 "−"（danger），
        # 右栏插入/替换行 "+"（success），equal / 占位行无符号
        self._ed_left.set_line_marker_provider(
            self._marker_provider(left_kinds, ("delete", "replace"), "−"))
        self._ed_right.set_line_marker_provider(
            self._marker_provider(right_kinds, ("insert", "replace"), "+"))
        self._ed_left.set_text("\n".join(left_lines))
        self._ed_right.set_text("\n".join(right_lines))
        # VS Code：左栏 replace 行 danger 系、右栏 success 系
        self._set_line_backgrounds(self._ed_left, left_kinds, "danger")
        self._set_line_backgrounds(self._ed_right, right_kinds, "success")
        self._char_ranges[self._ed_left] = {
            bn: [(a, b, "delete") for a, b in segs]
            for bn, segs in char_left.items()
        }
        self._char_ranges[self._ed_right] = {
            bn: [(a, b, "insert") for a, b in segs]
            for bn, segs in char_right.items()
        }
        self._apply_char_highlights()

    def _render_inline(self) -> None:
        """构建内联视图文本（删除 / 插入按 diff 序穿插）与行类型表。

        行号对齐 VS Code 内联 diff：**双列行号**——左列 = 原始文件行号、
        右列 = 修改文件行号；插入行 = 左列空 + 右列 ``"N+"``（success 绿），
        删除行 = 左列 ``"N−"``（danger 红）+ 右列空，equal 行两列数字。
        ``_inline_labels``（单列，删除 / equal 取旧号、插入取新号）保留
        作兼容 API 与双列被清除时的回退。
        """
        lines, kinds, labels, dual = [], [], [], []
        char_inline = {}                 # bn -> [(c1, c2, family)]
        old, new = self._old_lines, self._new_lines
        prev_old = prev_new = 0

        def emit_equal(a0, a1, b0):
            for k in range(a1 - a0):
                lines.append(old[a0 + k])
                kinds.append("equal")
                labels.append(a0 + k + 1)
                dual.append((str(a0 + k + 1), str(b0 + k + 1), None))

        for hunk in self._hunks:
            emit_equal(prev_old, hunk.old_start, prev_new)
            hunk.inline_line = len(lines)
            for tag, a0, a1, b0, b1 in hunk.ops:
                if tag == "equal":
                    emit_equal(a0, a1, b0)
                elif tag in ("delete", "replace"):
                    del_bn = len(lines)
                    for k in range(a0, a1):
                        lines.append(old[k])
                        kinds.append("delete")
                        labels.append(k + 1)  # 旧文件行号
                        dual.append((f"{k + 1}−", None, "−"))
                    if tag == "replace":
                        ins_bn = len(lines)
                        for k in range(b0, b1):
                            lines.append(new[k])
                            kinds.append("insert")
                            labels.append(k + 1)  # 新文件行号
                            dual.append((None, f"{k + 1}+", "+"))
                        # 字符级 diff：配对行做 difflib 字符比较
                        for k in range(min(a1 - a0, b1 - b0)):
                            segs_old, segs_new = _char_segments(
                                old[a0 + k], new[b0 + k])
                            for a, b in segs_old:
                                char_inline.setdefault(del_bn + k, []) \
                                    .append((a, b, "delete"))
                            for a, b in segs_new:
                                char_inline.setdefault(ins_bn + k, []) \
                                    .append((a, b, "insert"))
                else:  # insert
                    for k in range(b0, b1):
                        lines.append(new[k])
                        kinds.append("insert")
                        labels.append(k + 1)  # 新文件行号
                        dual.append((None, f"{k + 1}+", "+"))
            prev_old, prev_new = hunk.old_end, hunk.new_end
        emit_equal(prev_old, len(old), prev_new)

        self._inline_kinds = kinds
        self._inline_labels = labels
        self._inline_dual = dual
        self._ed_inline.set_language(self._language)
        self._ed_inline.set_line_label_provider(
            self._labels_provider(labels))
        self._ed_inline.set_dual_line_labels(
            self._dual_provider(dual))
        self._ed_inline.set_text("\n".join(lines))
        self._set_line_backgrounds(self._ed_inline, kinds)
        self._char_ranges[self._ed_inline] = char_inline
        self._apply_char_highlights()
        self._prefix_overlay.update()

    # ------------------------------------------------------------------
    # 行底色（QTextBlockFormat 背景，与 ExtraSelections 层互不干扰）
    # ------------------------------------------------------------------
    def _kind_color(self, kind: str):
        token = {
            "delete": "color.danger",
            "insert": "color.success",
            "replace": "color.warning",
        }.get(kind)
        if token is None:
            return None
        c = QColor(T(token))
        c.setAlpha(_BG_ALPHA)
        return c

    def _set_line_backgrounds(self, editor: CodeEditor, kinds,
                              replace_family: str = None) -> None:
        """按行类型表着行底色。

        ``replace_family``：并排模式 replace 配对行的用色家族——VS Code
        中左栏（旧）用 danger 系、右栏（新）用 success 系；缺省
        ``None`` 保持 warning（内联视图不产生 replace 行，不受影响）。
        """
        doc = editor.text_area().document()
        for bn in self._bg_lines.get(editor, []):
            block = doc.findBlockByNumber(bn)
            if block.isValid():
                fmt = QTextBlockFormat(block.blockFormat())
                fmt.clearBackground()
                QTextCursor(block).setBlockFormat(fmt)
        colored = []
        for bn, kind in enumerate(kinds):
            if kind == "replace" and replace_family:
                c = QColor(T(f"color.{replace_family}"))
                c.setAlpha(_BG_ALPHA)
                color = c
            else:
                color = self._kind_color(kind)
            if color is None:
                continue
            block = doc.findBlockByNumber(bn)
            if not block.isValid():
                continue
            fmt = QTextBlockFormat(block.blockFormat())
            fmt.setBackground(QBrush(color))
            QTextCursor(block).setBlockFormat(fmt)
            colored.append(bn)
        self._bg_lines[editor] = colored

    # ------------------------------------------------------------------
    # 滚动同步 / hunk 导航
    # ------------------------------------------------------------------
    def _sync_scroll(self, src: CodeEditor, dst: CodeEditor,
                     value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            dst.text_area().verticalScrollBar().setValue(value)
        finally:
            self._syncing_scroll = False

    def _scroll_editor_to_line(self, editor: CodeEditor, line0: int) -> None:
        ta = editor.text_area()
        block = ta.document().findBlockByNumber(max(0, line0))
        if not block.isValid():
            return
        cur = ta.textCursor()
        cur.setPosition(block.position())
        ta.setTextCursor(cur)
        ta.centerCursor()

    def _scroll_to_hunk(self, index: int, emit: bool = False) -> None:
        if not (0 <= index < len(self._hunks)):
            return
        self._current = index
        hunk = self._hunks[index]
        if self._effective == _VIEW_SIDE:
            self._scroll_editor_to_line(self._ed_left, hunk.side_line)
            self._scroll_editor_to_line(self._ed_right, hunk.side_line)
        else:
            self._scroll_editor_to_line(self._ed_inline, hunk.inline_line)
        self._update_hunk_label()
        if emit:
            self.hunk_changed.emit(index, len(self._hunks))

    def _update_hunk_label(self) -> None:
        total = len(self._hunks)
        self._hunk_label.setText(
            f"{self._current + 1}/{total}" if total else "0/0")

    # ------------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------------
    def _on_seg_changed(self, index: int) -> None:
        inv = {0: _VIEW_SIDE, 1: _VIEW_INLINE, 2: "auto"}
        self.set_view_mode(inv.get(index, _VIEW_SIDE))

    def _apply_effective_mode(self, scroll: bool) -> None:
        eff = self.view_mode()
        changed = eff != self._effective
        self._effective = eff
        self._stack.setCurrentWidget(
            self._side_page if eff == _VIEW_SIDE else self._inline_page)
        if scroll and self._hunks and self._current >= 0:
            # 平滑切换：保持当前 hunk 定位
            self._scroll_to_hunk(self._current)
        elif changed and self._hunks and self._current >= 0:
            self._scroll_to_hunk(self._current)

    def resizeEvent(self, event):  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        if self._mode == "auto":
            self._apply_effective_mode(scroll=True)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _on_theme_changed(self, _mode: str) -> None:
        try:
            self._refresh_style()
        except RuntimeError:
            return  # 控件已销毁
        # 行底色按新令牌重刷
        self._set_line_backgrounds(self._ed_left, self._side_left_kinds,
                                   "danger")
        self._set_line_backgrounds(self._ed_right, self._side_right_kinds,
                                   "success")
        self._set_line_backgrounds(self._ed_inline, self._inline_kinds)
        # hatch 纹理 / 字符级高亮盒 / 中央槽 / ruler 按新令牌重绘
        self._hatch_brush = None
        self._apply_char_highlights()
        self._prefix_overlay.update()
        self._slot.update()
        self._ruler.update()
        for ed in (self._ed_left, self._ed_right, self._ed_inline):
            ed.text_area().viewport().update()
            ed.gutter().update()

    def _refresh_style(self) -> None:
        self.setStyleSheet(
            "#DiffEditor {"
            f"background: {T('color.bg.elevated')};"
            "}"
            "#DiffColumnTitle {"
            f"color: {T('color.text.primary')};"
            "font-weight: 600;"
            "background: transparent;"
            "}"
            "#DiffColumnBadge {"
            f"color: {T('color.text.secondary')};"
            "background: transparent;"
            "}"
        )
        self._badge_left.setStyleSheet(
            f"color: {T('color.danger')}; background: transparent;")
        self._badge_right.setStyleSheet(
            f"color: {T('color.success')}; background: transparent;")
        self._hunk_label.setStyleSheet(
            f"color: {T('color.text.primary')}; background: transparent;")
        self._stats_label.setStyleSheet(
            f"color: {T('color.text.secondary')}; background: transparent;")
