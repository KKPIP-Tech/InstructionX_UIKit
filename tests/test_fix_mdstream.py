# -*- coding: utf-8 -*-
"""回归自测：MarkdownView 流式增量渲染一致性 + 流式对话滚动跟随状态机。

对应 dev 修复提交：
- ``fix(components): 修复 MarkdownView 流式增量渲染多项缺陷``
- ``fix(layouts): 修复流式对话滚动跟随状态机两处误判``

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_mdstream.py

覆盖：
- 含空行的闭合围栏按单 chunk / 按行 / 逐字符流式追加后，与一次性
  ``set_markdown`` 的文档纯文本逐字符一致、块数一致；
- 未闭合块级公式（``$$`` 含空行）分片流式追加，降级显示与一次性渲染
  纯文本一致（空行不被吞）；
- 段落→列表流式后不残留空块（块数与一次性一致）；
- 增量渲染字族：流式渲染的正文 fragment 字体与一次性渲染一致；
- theme_changed 生命周期：视图 deleteLater 销毁后切换主题不抛
  RuntimeError；
- ChatConversation：clear_messages 后 _follow 复位，清空重填自动跟随到底；
- 滚动钳制不误判：用户上翻后主题切换（文档瞬态收缩）保持 _follow=False，
  追加消息不强拉到底。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FAILURES = []


def check(name):
    """装饰器：登记一项检查，异常即记为失败。"""

    def deco(fn):
        try:
            fn()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()

    return deco


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.components.markdown_view import MarkdownView  # noqa: E402
from InstructionX_UIKit.layouts.chat_conversation import ChatConversation  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


def pump(ms):
    """推进事件循环 ms 毫秒（布局 / 延迟信号落定）。"""
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        QCoreApplication.processEvents()


# ---------------------------------------------------------------------------
# MarkdownView 流式一致性辅助
# ---------------------------------------------------------------------------

def render_oneshot(src):
    """一次性 set_markdown，返回 (纯文本, 块数, 视图)。"""
    v = MarkdownView()
    v.set_markdown(src)
    return v.document().toPlainText(), v.document().blockCount(), v


def render_streamed(src, chunks):
    """按给定分片流式追加，返回 (纯文本, 块数, 视图)。"""
    v = MarkdownView()
    for c in chunks:
        v.append_markdown(c)
    return v.document().toPlainText(), v.document().blockCount(), v


def assert_stream_consistent(name, src, chunkings):
    """每种分片方案的流式结果与一次性渲染逐字符一致、块数一致。"""
    text0, blocks0, v0 = render_oneshot(src)
    for label, chunks in chunkings:
        assert_eq("".join(chunks), src, f"{name}/{label} 分片拼接≠原文")
        text1, blocks1, v1 = render_streamed(src, chunks)
        assert_eq(text1, text0, f"{name}/{label} 流式纯文本与一次性不一致")
        assert_eq(blocks1, blocks0, f"{name}/{label} 流式块数与一次性不一致")
        v1.deleteLater()
    v0.deleteLater()


# ---------------------------------------------------------------------------
# 1. 含空行的闭合围栏：单 chunk / 按行 / 逐字符
# ---------------------------------------------------------------------------

FENCE_SRC = "```py\na=1\n\nb=2\n```\n\ntail"


@check("围栏含空行：单 chunk / 按行 / 逐字符流式与一次性一致")
def _():
    assert_stream_consistent("围栏含空行", FENCE_SRC, [
        ("单chunk", [FENCE_SRC]),
        ("按行", FENCE_SRC.splitlines(keepends=True)),
        ("逐字符", list(FENCE_SRC)),
    ])


# ---------------------------------------------------------------------------
# 2. 未闭合块级公式（$$ 含空行）：降级显示不吞空行
# ---------------------------------------------------------------------------

MATH_SRC = "$$\nx=1\n\ny=2"


@check("未闭合块级公式含空行：分片流式与一次性纯文本一致")
def _():
    assert_stream_consistent("未闭合$$", MATH_SRC, [
        ("单chunk", [MATH_SRC]),
        ("空行随前文", ["$$\nx=1\n\n", "y=2"]),
        ("空行独立chunk", ["$$\nx=1", "\n\n", "y=2"]),
        ("开启行独立", ["$$", "\nx=1\n\ny=2"]),
        ("逐字符", list(MATH_SRC)),
    ])
    # 空行不被吞：Qt Markdown 语义下空行是段落分隔符（toPlainText 块间为
    # 单个 \n），x=1 与 y=2 必须分属不同块，而非折叠进同一行
    text0, blocks0, v = render_oneshot(MATH_SRC)
    assert_true("x=1\ny=2" in text0,
                f"一次性渲染空行未分段（被吞或折叠）: {text0!r}")
    assert_true(blocks0 >= 2, f"一次性渲染块数异常: {blocks0}")
    v.deleteLater()


# ---------------------------------------------------------------------------
# 3. 段落→列表：流式后不残留空块
# ---------------------------------------------------------------------------

LIST_SRC = "# 标题\n\n正文 **加粗** 与 `代码`\n\n- 列表一\n- 列表二\n"


@check("段落→列表：流式块数与一次性一致（无残留空块）")
def _():
    assert_stream_consistent("段落→列表", LIST_SRC, [
        ("单chunk", [LIST_SRC]),
        ("按行", LIST_SRC.splitlines(keepends=True)),
        ("逐字符", list(LIST_SRC)),
    ])


# ---------------------------------------------------------------------------
# 4. 增量渲染字族：流式 fragment 字体与一次性一致
# ---------------------------------------------------------------------------

def _fragment_families(doc):
    """文档全部非空 fragment 的 (文本, 字体族元组) 列表。"""
    out = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.text().strip():
                out.append((frag.text(),
                            tuple(frag.charFormat().font().families())))
            it += 1
        block = block.next()
    return out


#: CSS generic 字族（一次性渲染经 CSS 声明保留 generic 兜底名，增量路径
#: 经 QFont.setFamilies 按 _families() 约定剔除——归一化后两者可比）
_GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "cursive", "fantasy"}


def _norm_families(fams):
    """字体族元组剔除 generic 族（两条渲染管线的固有表示差异）。"""
    return tuple(f for f in fams if f.lower() not in _GENERIC_FAMILIES)


@check("增量渲染字族：流式 fragment 字体与一次性渲染一致")
def _():
    text0, _, v0 = render_oneshot(LIST_SRC)
    text1, _, v1 = render_streamed(LIST_SRC, list(LIST_SRC))
    fams0 = [(t, _norm_families(f)) for t, f in _fragment_families(v0.document())]
    fams1 = [(t, _norm_families(f)) for t, f in _fragment_families(v1.document())]
    set0 = {f for _, f in fams0}
    set1 = {f for _, f in fams1}
    assert_eq(set1, set0, "流式与一次性的字体族集合（归一化后）不一致")
    # 正文 fragment 逐字对比（「正文」起首的段落 fragment），且族非空
    # （非空证明走令牌字族而非 Qt 默认字体）
    body0 = [f for t, f in fams0 if t.startswith("正文")]
    body1 = [f for t, f in fams1 if t.startswith("正文")]
    assert_true(bool(body0) and bool(body1),
                f"未找到正文 fragment: 一次性={body0} 流式={body1}")
    assert_eq(body1, body0, "正文 fragment 字体族不一致")
    assert_true(all(body1), f"流式正文 fragment 字体族为空: {body1}")
    v0.deleteLater()
    v1.deleteLater()


# ---------------------------------------------------------------------------
# 5. theme_changed 生命周期：视图销毁后切换主题不抛 RuntimeError
# ---------------------------------------------------------------------------

@check("theme_changed 生命周期：deleteLater 销毁后切换主题无 RuntimeError")
def _():
    tm = ThemeManager.instance()
    views = [MarkdownView(LIST_SRC) for _ in range(3)]
    survivor = MarkdownView(FENCE_SRC)
    pump(50)
    for v in views:
        v.deleteLater()
    # 冲刷 DeferredDelete，确保 C++ 侧对象真正销毁后再发射 theme_changed
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    pump(50)
    try:
        tm.set_mode("dark")
        pump(100)
        tm.set_mode("light")
        pump(100)
    except RuntimeError:
        raise AssertionError("视图销毁后切换主题抛出 RuntimeError")
    # 幸存视图在两次主题切换后渲染内容不变
    assert_eq(survivor.document().toPlainText(),
              render_oneshot(FENCE_SRC)[0], "幸存视图主题切换后纯文本变化")
    survivor.deleteLater()


# ---------------------------------------------------------------------------
# 6. ChatConversation：clear_messages 后 _follow 复位
# ---------------------------------------------------------------------------

LONG_MSG = "# 长消息\n\n" + "这是一段用于撑高文档的中文内容。\n\n" * 60


@check("clear_messages 后 _follow 复位：清空重填自动跟随到底")
def _():
    conv = ChatConversation(
        messages=[{"role": "assistant", "content": LONG_MSG}],
        show_input=False)
    conv.resize(500, 300)
    conv.show()
    pump(400)
    bar = conv._scroll.verticalScrollBar()
    assert_true(bar.maximum() > 0, f"内容未撑出滚动范围 max={bar.maximum()}")
    # 用户上翻到顶部
    bar.setValue(0)
    pump(50)
    assert_true(not conv._follow, "上翻后 _follow 应为 False")
    # 清空 → _follow 复位
    conv.clear_messages()
    pump(200)
    assert_true(conv._follow, "clear_messages 后 _follow 应复位为 True")
    assert_eq(len(conv._rows), 0, "clear 后行布局未全部摘除")
    # 重新填充 → 自动跟随到底
    for i in range(3):
        conv.add_message("assistant", f"清空后的第 {i + 1} 条消息。" + "行\n\n" * 20)
        pump(100)
    pump(300)
    assert_true(bar.value() >= bar.maximum() - 4,
                f"清空重填后未跟随到底 value={bar.value()} max={bar.maximum()}")
    conv.deleteLater()


# ---------------------------------------------------------------------------
# 7. ChatConversation：滚动钳制不误判（主题切换瞬态收缩）
# ---------------------------------------------------------------------------

@check("滚动钳制不误判：上翻后主题切换保持 _follow=False，追加不强拉")
def _():
    tm = ThemeManager.instance()
    conv = ChatConversation(
        messages=[{"role": "assistant", "content": LONG_MSG}],
        show_input=False)
    conv.resize(500, 300)
    conv.show()
    pump(400)
    bar = conv._scroll.verticalScrollBar()
    assert_true(bar.maximum() > 0, f"内容未撑出滚动范围 max={bar.maximum()}")
    # 用户翻到中部阅读
    mid = bar.maximum() // 2
    bar.setValue(mid)
    pump(50)
    assert_true(not conv._follow, "翻页后 _follow 应为 False")
    try:
        # 主题切换 → MarkdownView 全量重渲染，占位期文档瞬态收缩，
        # Qt 会把 value 钳到新 maximum——这是布局变化而非用户回到底部
        tm.set_mode("dark")
        pump(600)
        assert_true(not conv._follow,
                    f"主题切换后 _follow 被误判为 True"
                    f"（value={bar.value()} max={bar.maximum()}）")
        # 追加消息不应强拉到底
        conv.add_message("assistant", "主题切换后的追加消息。" + "行\n\n" * 30)
        pump(400)
        assert_true(not conv._follow, "追加消息后 _follow 应保持 False")
        assert_true(bar.value() < bar.maximum() - 4,
                    f"追加消息后阅读位置被强拉到底"
                    f"（value={bar.value()} max={bar.maximum()}）")
    finally:
        tm.set_mode("light")
        pump(100)
        conv.deleteLater()


print("\n==== test_fix_mdstream ====")

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
