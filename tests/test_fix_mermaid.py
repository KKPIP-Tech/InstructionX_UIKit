# -*- coding: utf-8 -*-
"""回归自测：Mermaid 降级渲染器解析 + 查看器降级画布交互 + 渲染中枢缓存自洽。

对应 dev 修复提交：
- ``fix(mermaid): 修复降级渲染器解析缺陷与查看器交互一致性``

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_mermaid.py

覆盖：
- ``render.py`` 降级解析：首行分号语句（``flowchart TD; A --> B``）正常
  渲染；非法首行抛 ``ValueError``（不再 ``AttributeError``）；引号标签
  含分号不误切分；边标签引号内含箭头正常解析；
- ``view.py`` 降级画布 ``_FallbackCanvas``：工具条缩放（zoom_in）置
  ``_interacted``，宿主 resize 不再冲掉用户缩放；fit_width 复位后恢复
  随宿主宽度自适应；
- ``hub.py`` 缓存自洽：``_finish_job`` 成功后 ``is_failed`` 为 False 且
  ``last_error`` 为空；失败键记录错误；重试成功清除旧失败记录。
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


from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 文本度量依赖 QFont，须先创建 QApplication
app = QApplication.instance() or QApplication(sys.argv)

from InstructionX_UIKit.mermaid import render as fb  # noqa: E402
from InstructionX_UIKit.mermaid.hub import MermaidRenderHub  # noqa: E402
from InstructionX_UIKit.mermaid.view import _FallbackCanvas  # noqa: E402

#: 样式字典（键集合与 _STYLE_KEYS 一致）
STYLE = {
    "text": "#1f2329", "line": "#8f959e", "node_fill": "#f2f3f5",
    "node_border": "#8f959e", "label_bg": "#ffffff",
    "font_family": '"Segoe UI", "Microsoft YaHei", sans-serif',
}


def ink_stats(img):
    """非透明采样像素数 + 颜色桶数（验证真实出图而非空白）。"""
    colors = set()
    opaque = 0
    w, h = img.width(), img.height()
    for y in range(0, h, max(1, h // 60)):
        for x in range(0, w, max(1, w // 60)):
            c = img.pixelColor(x, y)
            if c.alpha() > 8:
                opaque += 1
                colors.add((c.red() // 32, c.green() // 32, c.blue() // 32))
    return opaque, len(colors)


def assert_renders(name, code):
    """正常渲染：不抛异常且产物有墨迹。"""
    img = fb.render_diagram(code, STYLE, 10.5)
    assert_true(isinstance(img, QImage) and not img.isNull(),
                f"{name} 产物为空图")
    op, ncol = ink_stats(img)
    assert_true(op > 10 and ncol >= 2,
                f"{name} 图像疑似空白（墨迹 {op} 颜色 {ncol}）")
    return img


# ---------------------------------------------------------------------------
# 1. render.py 降级解析
# ---------------------------------------------------------------------------

@check("首行分号语句：flowchart TD; A --> B 正常渲染")
def _():
    assert_renders("首行分号", "flowchart TD; A --> B")


@check("非法首行：抛 ValueError（不再 AttributeError）")
def _():
    bad_cases = [
        "flowchart TD A --> B",   # 首行缺分号/换行，正则匹配失败
        "graph LRX\nA --> B",     # 未知方向
    ]
    for code in bad_cases:
        try:
            fb.render_diagram(code, STYLE, 10.5)
        except ValueError:
            continue
        except AttributeError as exc:
            raise AssertionError(
                f"{code!r} 抛出 AttributeError 而非 ValueError: {exc}")
        raise AssertionError(f"{code!r} 未抛 ValueError")


@check("引号标签含分号：A[\"x;y\"] --> B 正常渲染")
def _():
    assert_renders("引号标签含分号", 'flowchart LR\nA["x;y"] --> B')


@check("边标签引号内含箭头：A -- \"t-->x\" --> B 正常渲染")
def _():
    assert_renders("边标签含箭头", 'flowchart LR\nA -- "t-->x" --> B')


# ---------------------------------------------------------------------------
# 2. view.py 降级画布 _FallbackCanvas 交互一致性
# ---------------------------------------------------------------------------

def _make_canvas(w=400, h=300):
    canvas = _FallbackCanvas(None)
    canvas.resize(w, h)
    img = QImage(800, 600, QImage.Format.Format_ARGB32)
    img.fill(0xFF336699)
    canvas.set_image(img)
    return canvas


@check("降级画布 zoom_in 置 _interacted")
def _():
    canvas = _make_canvas()
    assert_true(not canvas._interacted, "set_image/fit_width 后应为未交互状态")
    s_fit = canvas._scale
    canvas.zoom_in()
    assert_true(canvas._interacted, "zoom_in 后 _interacted 应为 True")
    assert_true(canvas._scale > s_fit,
                f"zoom_in 未放大 scale={canvas._scale} fit={s_fit}")
    canvas.deleteLater()


@check("降级画布：用户缩放后宿主 resize 不冲掉缩放")
def _():
    canvas = _make_canvas()
    canvas.zoom_in()
    s_zoom = canvas._scale
    # 模拟宿主 resize（resizeEvent → on_host_resize）
    canvas.resize(600, 300)
    canvas.on_host_resize()
    assert_true(abs(canvas._scale - s_zoom) < 1e-9,
                f"用户缩放被 resize 冲掉 zoom={s_zoom} 现={canvas._scale}")
    # fit_width 复位后恢复随宿主宽度自适应
    canvas.fit_width()
    assert_true(not canvas._interacted, "fit_width 后 _interacted 应复位")
    s_fit600 = canvas._scale
    canvas.resize(800, 300)
    canvas.on_host_resize()
    assert_true(abs(canvas._scale - s_fit600) > 1e-6,
                f"fit_width 复位后 resize 未重适配 scale={canvas._scale}")
    canvas.deleteLater()


# ---------------------------------------------------------------------------
# 3. hub.py 缓存自洽（隔离实例，纯逻辑断言，不触 WebEngine/worker）
# ---------------------------------------------------------------------------

def _isolated_hub():
    """构造不启动 worker / WebEngine 的隔离实例（仅初始化 _finish_job 依赖）。"""
    import queue
    from collections import OrderedDict, deque

    from PySide6.QtCore import QObject

    hub = MermaidRenderHub.__new__(MermaidRenderHub)
    QObject.__init__(hub)  # image_ready 信号发射需要 QObject 初始化
    hub._cache = OrderedDict()
    hub._failed_ts = {}
    hub._errors = {}
    hub._logged_failures = set()
    hub._pending = set()
    hub._jobs = deque()
    hub._busy = False
    hub._current = None
    hub._page = None
    hub._web_ready = False
    hub._web_failed = True  # 视为降级（不触发 WebEngine 路径）
    hub._fb_queue = queue.Queue()
    hub._fb_worker = None
    return hub


@check("hub._finish_job：成功渲染后 is_failed 为 False 且 last_error 为空")
def _():
    hub = _isolated_hub()
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(1)
    hub._finish_job("k-ok", img, "")
    assert_true(not hub.is_failed("k-ok"), "成功键被误标为失败")
    assert_eq(hub.last_error("k-ok"), "", "成功键残留错误消息")
    assert_true(isinstance(hub.get("k-ok"), QImage), "成功键 get 未命中")
    assert_true("k-ok" not in hub._pending, "完成键未从 pending 摘除")


@check("hub._finish_job：失败记录错误，重试成功后清除旧失败记录")
def _():
    hub = _isolated_hub()
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(1)
    # 失败路径
    hub._finish_job("k-bad", None, "语法错误演示")
    assert_true(hub.is_failed("k-bad"), "失败键未标记 _FAILED")
    assert_true(bool(hub.last_error("k-bad")), "失败键缺少错误消息")
    assert_true(hub.get("k-bad") is None, "失败键 get 应返回 None")
    # 重试成功后旧失败记录必须清除（is_failed / last_error 复位）
    hub._finish_job("k-bad", img, "")
    assert_true(not hub.is_failed("k-bad"), "重试成功后仍标记失败")
    assert_eq(hub.last_error("k-bad"), "", "重试成功后残留旧错误消息")
    assert_true(isinstance(hub.get("k-bad"), QImage), "重试成功后 get 未命中")
    # 空图（isNull）同样按失败处理
    null_img = QImage()
    hub._finish_job("k-null", null_img, "空图")
    assert_true(hub.is_failed("k-null"), "空图未按失败处理")
    assert_eq(hub.last_error("k-null"), "空图", "空图错误消息未记录")


print("\n==== test_fix_mermaid ====")

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
