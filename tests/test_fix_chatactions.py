# -*- coding: utf-8 -*-
"""回归自测：流式对话气泡操作条（ChatConversation action bar）。

对应 dev 新功能提交：气泡操作条（token 估算 / 复制 / 删除 / 内联编辑 /
AI 重新生成 / 继续生成信号 / 流式计时 / set_message_stats 覆盖 /
set_actions_always_visible 常显开关）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_chatactions.py

覆盖：
- ``_estimate_tokens`` 启发式：空串 / 纯中文 / 纯英文 / 混合 / CJK 标点；
- 流式计时：多次 ``append_to_message`` 后统计标签含 tokens 与 tok/s，
  未 finish 时用时段随时间滚动；``finish_message`` 后用时冻结；
- ``set_message_stats`` 覆盖显示与非法参数抛错（ValueError / IndexError）；
- 复制：剪贴板写入原文、图标切换为对勾、约 1 秒后复原；
- 删除：``messageDeleted`` 携带删除前索引、消息数减一、后续索引前移、
  行布局 / 气泡 / 统计状态无残留、删空后回占位；
- 编辑：进入编辑态（TextArea 填入原文、操作条隐藏）、确定后内容更新
  且发射 ``messageEdited``、取消不变更；
- 角色差异：AI 气泡有重新生成 / 继续生成按钮且无编辑按钮，用户气泡
  反之；两信号点击后发射正确索引；
- 悬停显现 / 常显开关：``set_actions_always_visible(True)`` 后新追加
  气泡同样常显，关闭后恢复隐藏；
- 常显状态双主题截图非空白（``tests/shots/fix_chatactions_*.png``）。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"

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


from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QPointF  # noqa: E402
from PySide6.QtGui import QEnterEvent, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.components.button import Button  # noqa: E402
from InstructionX_UIKit.layouts.chat_conversation import (  # noqa: E402
    ChatConversation,
    _estimate_tokens,
)

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


def pump(ms):
    """推进事件循环 ms 毫秒（布局 / 定时器 / 延迟信号落定）。"""
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        QCoreApplication.processEvents()


def _make_conv(w=720, h=560):
    """新建一个无输入区的对话布局并展示（气泡显隐断言需要 show）。"""
    conv = ChatConversation(show_input=False)
    conv.resize(w, h)
    conv.show()
    pump(50)
    return conv


def _edit_button(bubble, text):
    """编辑操作条中按文案取按钮（确定 / 取消）。"""
    for btn in bubble._edit_bar.findChildren(Button):
        if btn.text() == text:
            return btn
    raise AssertionError(f"编辑操作条缺少按钮: {text}")


# ---------------------------------------------------------------------------
# 1. token 估算启发式
# ---------------------------------------------------------------------------

@check("token 估算：空串 / 纯中文 / 纯英文 / 混合 / CJK 标点")
def _():
    assert_eq(_estimate_tokens(""), 0, "空串")
    assert_eq(_estimate_tokens("你好世界"), 4, "纯中文每字 1 token")
    assert_eq(_estimate_tokens("hello world  foo"), 3, "英文按非空白片段计")
    assert_eq(_estimate_tokens("你好 world"), 3, "中英混合")
    # CJK 标点（，。）属 CJK 区块，同样每字 1 token
    assert_eq(_estimate_tokens("你好，世界。"), 6, "CJK 标点计入")
    assert_eq(_estimate_tokens("  \n\t "), 0, "纯空白")


# ---------------------------------------------------------------------------
# 2. 静态消息统计：仅 tokens 段，无速度 / 用时
# ---------------------------------------------------------------------------

@check("静态 AI 消息统计仅显示 tokens 段（无速度 / 用时）")
def _():
    conv = _make_conv()
    try:
        i_ai = conv.add_message("assistant", "")
        i_user = conv.add_message("user", "请介绍一下这个组件库")
        pump(50)
        assert_eq(conv._bubbles[i_ai]._stats_label.text(), "约 0 tokens",
                  "空 AI 气泡统计")
        ai_text = conv._bubbles[i_ai]._stats_label.text()
        assert_true("tok/s" not in ai_text and "用时" not in ai_text,
                    f"静态 AI 消息不应显示速度 / 用时: {ai_text!r}")
        user_text = conv._bubbles[i_user]._stats_label.text()
        assert_true(user_text.startswith("约 ") and "tokens" in user_text,
                    f"用户气泡统计格式异常: {user_text!r}")
        assert_true("tok/s" not in user_text and "用时" not in user_text,
                    f"用户气泡不应显示速度 / 用时: {user_text!r}")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 3. 流式计时：append 后含速度 / 用时，未 finish 时随时间滚动
# ---------------------------------------------------------------------------

@check("流式计时：多次 append 后含 tokens / tok/s / 用时，未 finish 持续滚动")
def _():
    conv = _make_conv()
    try:
        i_ai = conv.add_message("assistant", "")
        for chunk in ("好的，", "这是一段", "流式回复文本", "，用于验证计时。"):
            conv.append_to_message(i_ai, chunk)
            pump(60)
        label = conv._bubbles[i_ai]._stats_label
        text = label.text()
        assert_true("tokens" in text, f"统计缺少 tokens 段: {text!r}")
        assert_true("tok/s" in text, f"流式中应显示速度段: {text!r}")
        assert_true("用时" in text, f"流式中应显示用时段: {text!r}")
        # 未 finish：用时段随时间滚动（0.1s 分辨率，300ms 必然越界变化）
        before = label.text()
        pump(300)
        conv.set_message_stats(i_ai)  # 无参调用强制重算
        assert_true(label.text() != before,
                    f"未 finish 时用时段应随时间滚动: {before!r}")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 4. finish_message 冻结用时
# ---------------------------------------------------------------------------

@check("finish_message 后用时冻结（等待后重算文本不变）")
def _():
    conv = _make_conv()
    try:
        i_ai = conv.add_message("assistant", "")
        for chunk in ("第一段。", "第二段。"):
            conv.append_to_message(i_ai, chunk)
            pump(60)
        conv.finish_message(i_ai)
        assert_true(conv._stats[i_ai]["finished"] is not None,
                    "finish 后 finished 时间戳应已记录")
        frozen = conv._bubbles[i_ai]._stats_label.text()
        assert_true("用时" in frozen, f"finish 后应有用时段: {frozen!r}")
        pump(400)
        conv.set_message_stats(i_ai)  # 触发重算，elapsed 应取自 finished 而非 now
        assert_eq(conv._bubbles[i_ai]._stats_label.text(), frozen,
                  "finish 后用时未冻结")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 5. set_message_stats 覆盖显示 + 非法参数抛错
# ---------------------------------------------------------------------------

@check("set_message_stats 覆盖 tokens / 用时 / 速度显示，非法参数抛错")
def _():
    conv = _make_conv()
    try:
        i_ai = conv.add_message("assistant", "覆盖测试内容")
        pump(30)
        conv.set_message_stats(i_ai, tokens=999, elapsed=3.2, speed=88.5)
        text = conv._bubbles[i_ai]._stats_label.text()
        assert_true("约 999 tokens" in text, f"tokens 覆盖未生效: {text!r}")
        assert_true("用时 3.2s" in text, f"用时覆盖未生效: {text!r}")
        assert_true("88.5 tok/s" in text, f"速度覆盖未生效: {text!r}")
        # 非法参数：负数一律 ValueError，越界索引一律 IndexError
        for kwargs in ({"tokens": -1}, {"elapsed": -0.5}, {"speed": -1.0}):
            try:
                conv.set_message_stats(i_ai, **kwargs)
                raise AssertionError(f"非法参数未抛错: {kwargs}")
            except ValueError:
                pass
        for call in (lambda: conv.set_message_stats(99, tokens=1),
                     lambda: conv.finish_message(99),
                     lambda: conv.append_to_message(99, "x"),
                     lambda: conv.update_message(99, "x")):
            try:
                call()
                raise AssertionError("越界索引未抛 IndexError")
            except IndexError:
                pass
        # 抛错后原覆盖值不被污染
        assert_eq(conv._stats[i_ai]["tokens"], 999, "抛错后 tokens 被污染")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 6. update_message 整体替换并重置计时 / 统计
# ---------------------------------------------------------------------------

@check("update_message 替换内容并重置统计（速度段消失、覆盖值清空）")
def _():
    conv = _make_conv()
    try:
        i_ai = conv.add_message("assistant", "")
        conv.append_to_message(i_ai, "旧内容")
        pump(60)
        conv.append_to_message(i_ai, "继续")
        conv.set_message_stats(i_ai, tokens=999)
        pump(30)
        conv.update_message(i_ai, "重新生成后的内容")
        pump(30)
        assert_eq(conv.messages()[i_ai]["content"], "重新生成后的内容",
                  "update_message 未替换内容")
        st = conv._stats[i_ai]
        assert_true(st["tokens"] is None and st["chunks"] == 0
                    and st["first"] is None and st["finished"] is None,
                    f"update_message 未重置统计状态: {st}")
        text = conv._bubbles[i_ai]._stats_label.text()
        assert_true("999" not in text and "tok/s" not in text,
                    f"update_message 后统计未重置: {text!r}")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 7. 复制：剪贴板原文 + 图标切换 / 复原
# ---------------------------------------------------------------------------

@check("复制：剪贴板写入原文，图标切换为对勾约 1 秒后复原")
def _():
    conv = _make_conv()
    try:
        content = "复制我：**加粗内容** 与 `code`"
        i_ai = conv.add_message("assistant", content)
        pump(30)
        copy_btn = conv._bubbles[i_ai]._action_buttons["copy"]
        before_img = copy_btn.icon().pixmap(14, 14).toImage()
        copy_btn.click()
        pump(30)
        assert_eq(QGuiApplication.clipboard().text(), content,
                  "剪贴板内容与消息原文不一致")
        assert_true(copy_btn.icon().pixmap(14, 14).toImage() != before_img,
                    "复制后图标未切换为对勾")
        pump(1300)
        assert_true(copy_btn.icon().pixmap(14, 14).toImage() == before_img,
                    "约 1 秒后图标未复原")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 8. 角色差异：按钮集合 + 重新生成 / 继续生成信号索引
# ---------------------------------------------------------------------------

@check("角色差异：AI 有重新生成 / 继续无编辑，用户反之；信号携带索引")
def _():
    conv = _make_conv()
    try:
        i_user = conv.add_message("user", "用户消息")
        i_ai = conv.add_message("assistant", "AI 回复")
        pump(30)
        ai_btns = conv._bubbles[i_ai]._action_buttons
        user_btns = conv._bubbles[i_user]._action_buttons
        assert_true("regenerate" in ai_btns and "continue" in ai_btns,
                    f"AI 气泡缺少重新生成 / 继续按钮: {sorted(ai_btns)}")
        assert_true("edit" not in ai_btns, "AI 气泡不应有编辑按钮")
        assert_true("copy" in ai_btns and "delete" in ai_btns,
                    "AI 气泡缺少共有按钮")
        assert_true("edit" in user_btns, "用户气泡缺少编辑按钮")
        assert_true("regenerate" not in user_btns
                    and "continue" not in user_btns,
                    "用户气泡不应有重新生成 / 继续按钮")
        assert_true("copy" in user_btns and "delete" in user_btns,
                    "用户气泡缺少共有按钮")
        got = {"regen": None, "cont": None}
        conv.regenerateRequested.connect(lambda i: got.__setitem__("regen", i))
        conv.continueRequested.connect(lambda i: got.__setitem__("cont", i))
        ai_btns["regenerate"].click()
        ai_btns["continue"].click()
        pump(30)
        assert_eq(got["regen"], i_ai, "regenerateRequested 索引错误")
        assert_eq(got["cont"], i_ai, "continueRequested 索引错误")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 9. 内联编辑全流程：进入 / 确定 / 取消
# ---------------------------------------------------------------------------

@check("编辑：进入编辑态填入原文，确定更新并发射 messageEdited，取消不变更")
def _():
    conv = _make_conv()
    try:
        i_user = conv.add_message("user", "请介绍一下这个组件库")
        pump(30)
        bubble = conv._bubbles[i_user]
        got = {"edited": None}
        conv.messageEdited.connect(lambda i, t: got.__setitem__("edited", (i, t)))

        # -- 进入编辑态
        bubble._action_buttons["edit"].click()
        pump(30)
        assert_true(bubble._editing, "未进入编辑态")
        assert_true(bubble._editor.isVisibleTo(bubble), "TextArea 未显示")
        assert_true(not bubble.view.isVisibleTo(bubble), "内容视图未隐藏")
        assert_eq(bubble.edit_text(), "请介绍一下这个组件库",
                  "编辑器未填入原文")
        assert_true(bubble._stats_label.isHidden(),
                    "编辑态操作条应隐藏")
        assert_true(all(b.isHidden() for b in bubble._action_buttons.values()),
                    "编辑态操作按钮应全部隐藏")

        # -- 取消：内容不变更、不发射信号
        bubble._editor.setPlainText("这段不应生效")
        _edit_button(bubble, "取消").click()
        pump(30)
        assert_true(not bubble._editing, "取消后未退出编辑态")
        assert_eq(conv.messages()[i_user]["content"], "请介绍一下这个组件库",
                  "取消编辑后内容被变更")
        assert_true(got["edited"] is None, "取消编辑不应发射 messageEdited")
        assert_true(bubble.view.isVisibleTo(bubble), "取消后内容视图未恢复")

        # -- 确定：内容更新并发射信号
        bubble._action_buttons["edit"].click()
        pump(30)
        assert_true(bubble._editing, "再次进入编辑态失败")
        bubble._editor.setPlainText("改成：介绍一下图标系统")
        _edit_button(bubble, "确定").click()
        pump(30)
        assert_eq(got["edited"], (i_user, "改成：介绍一下图标系统"),
                  "messageEdited 信号参数错误")
        assert_eq(conv.messages()[i_user]["content"], "改成：介绍一下图标系统",
                  "确定后消息内容未更新")
        assert_true(not bubble._editing and bubble.view.isVisibleTo(bubble),
                    "确定后未退出编辑态")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 10. 删除：信号索引 / 数量 / 索引前移 / 无残留 / 删空回占位
# ---------------------------------------------------------------------------

@check("删除：信号携带删除前索引、数量减一、索引前移、行布局无残留、删空回占位")
def _():
    conv = _make_conv()
    try:
        conv.add_message("user", "第一条")
        i_mid = conv.add_message("assistant", "第二条（待删除）")
        conv.add_message("user", "第三条")
        pump(30)
        n_rows = len(conv._rows)
        n_msgs = len(conv.messages())
        got = {"deleted": None}
        conv.messageDeleted.connect(lambda i: got.__setitem__("deleted", i))
        conv._bubbles[i_mid]._action_buttons["delete"].click()
        pump(50)
        assert_eq(got["deleted"], i_mid, "messageDeleted 未携带删除前索引")
        assert_eq(len(conv.messages()), n_msgs - 1, "删除后消息数未减一")
        assert_eq(conv.messages()[i_mid]["content"], "第三条",
                  "后续消息索引未前移")
        assert_eq(len(conv._rows), n_rows - 1, "行布局有残留")
        assert_eq(len(conv._bubbles), n_msgs - 1, "气泡列表有残留")
        assert_eq(len(conv._stats), n_msgs - 1, "统计状态有残留")

        # 删空后回到空占位
        while conv.messages():
            conv._bubbles[0]._action_buttons["delete"].click()
            pump(30)
        assert_true(conv._placeholder is not None, "删空后未显示空占位")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 11. 悬停显现 / 常显开关
# ---------------------------------------------------------------------------

@check("悬停显现与常显开关：默认隐藏、悬停显现、常显后新气泡继承、关闭恢复")
def _():
    conv = _make_conv()
    try:
        conv.add_message("assistant", "悬停测试消息")
        pump(30)
        b = conv._bubbles[0]
        assert_true(not conv.actions_always_visible(), "默认应为非常显")
        assert_true(b._stats_label.isHidden(), "默认操作条应隐藏")
        # 悬停显现
        QApplication.sendEvent(b, QEnterEvent(QPointF(2, 2), QPointF(2, 2),
                                              QPointF(100, 100)))
        pump(20)
        assert_true(b._stats_label.isVisibleTo(b), "悬停未显现操作条")
        assert_true(all(btn.isVisibleTo(b)
                        for btn in b._action_buttons.values()),
                    "悬停未显现操作按钮")
        QApplication.sendEvent(b, QEvent(QEvent.Leave))
        pump(20)
        assert_true(b._stats_label.isHidden(), "离开后操作条未隐藏")
        # 常显开关
        conv.set_actions_always_visible(True)
        pump(20)
        assert_true(conv.actions_always_visible(), "常显开关未生效")
        assert_true(b._stats_label.isVisibleTo(b), "常显后操作条仍隐藏")
        idx2 = conv.add_message("assistant", "新增气泡")
        pump(20)
        b2 = conv._bubbles[idx2]
        assert_true(b2._stats_label.isVisibleTo(b2),
                    "新追加气泡未继承常显")
        assert_true(all(btn.isVisibleTo(b2)
                        for btn in b2._action_buttons.values()),
                    "新追加气泡按钮未继承常显")
        # 关闭恢复
        conv.set_actions_always_visible(False)
        pump(20)
        assert_true(not conv.actions_always_visible(), "常显开关未关闭")
        assert_true(b._stats_label.isHidden()
                    and b2._stats_label.isHidden(),
                    "关闭常显后操作条未恢复隐藏")
    finally:
        conv.deleteLater()


# ---------------------------------------------------------------------------
# 12. 操作条常显状态双主题截图（非空白断言 + 输出 tests/shots/）
# ---------------------------------------------------------------------------

def _assert_shot(pm, name):
    """截图非空白断言（密集采样 >= 2 种颜色、非全黑），与 test_gallery 一致。"""
    if pm.isNull() or pm.width() < 50:
        raise AssertionError(f"{name} grab() 返回空图像")
    img = pm.toImage()
    w, h = img.width(), img.height()
    colors = set()
    sx, sy = max(1, w // 150), max(1, h // 150)
    for x in range(0, w, sx):
        for y in range(0, h, sy):
            colors.add(img.pixelColor(x, y).rgb())
            if len(colors) >= 2:
                break
        if len(colors) >= 2:
            break
    if len(colors) < 2:
        raise AssertionError(f"{name} 密集采样仅 {len(colors)} 种颜色，疑似空白")
    if colors == {0xFF000000}:
        raise AssertionError(f"{name} 截图全黑")


@check("操作条常显双主题截图非空白（tests/shots/fix_chatactions_*.png）")
def _():
    tm = ThemeManager.instance()
    conv = _make_conv(760, 600)
    try:
        conv.add_message("user", "请介绍一下这个组件库的图表能力")
        i_ai = conv.add_message("assistant", "")
        for chunk in ("好的，", "这是一个支持", "**流式输出** 的对话布局，",
                      "操作条常显截图验证。"):
            conv.append_to_message(i_ai, chunk)
            pump(40)
        conv.finish_message(i_ai)
        conv.set_actions_always_visible(True)
        pump(200)
        SHOTS.mkdir(parents=True, exist_ok=True)
        for mode in ("light", "dark"):
            tm.set_mode(mode)
            tm.apply(app)
            pump(200)
            pm = conv.grab()
            _assert_shot(pm, f"fix_chatactions_{mode}")
            path = SHOTS / f"fix_chatactions_{mode}.png"
            if not pm.save(str(path)):
                raise AssertionError(f"截图保存失败: {path}")
            if path.stat().st_size < 2048:
                raise AssertionError(f"截图文件过小: {path}")
    finally:
        tm.set_mode("light")
        tm.apply(app)
        pump(100)
        conv.deleteLater()


print("\n==== test_fix_chatactions ====")

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
