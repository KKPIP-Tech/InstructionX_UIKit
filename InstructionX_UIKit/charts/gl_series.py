# -*- coding: utf-8 -*-
"""GPU 原生系列渲染（CHART_SPEC §7.2 GPU 顶点路径）。

**定位**：把折线/散点的顶点直接提交显卡（VBO + GLSL），绕过 ``QPainter``
的路径构造与光栅化。这是本项目唯一真正「GPU 原生」的绘制路径。

**关键约束（务必先读，避免误期待）**

1. **它只在 GL 视口内可用**：软件回退（offscreen / 无 GL）下完全不走本模块，
   既有 ``paint(p, anim_t)`` 语义与像素结果不变。
2. **它不改变公共 API**：系列渲染器仍实现原有协议；本模块由 GL 视口在
   ``paintGL`` 中按需调用，属于**可选加速**。
3. **顶点上传成本与数据量成正比**：百万点每帧重传约 16 MB（顶点+索引），
   在 90 fps 下约 1.4 GB/s——这对静态数据毫无必要（只需一次上传、之后仅改
   变换矩阵），对**每帧都在变**的数据则是纯负担。
   因此本模块对「数据版本变化」的系列只在**静态期**缓存 VBO；
   流式更新场景应继续走采样 + QPainter 路径。

**收益的正确预期**：单图稳态帧耗时主要来自布局与采样（实测 150 万点约
5 ms / 198 fps，已在 90 fps 预算内），顶点绘制只占其中一小部分。本模块的
价值在于**去掉 QPainter 的路径构造开销**，对「同屏多图」这类固定成本敏感的
场景更有意义；它**不能**让每帧重算布局与采样的成本消失。
"""

try:  # pragma: no cover - 环境相关分支（无 numpy 时不提供 GL 路径）
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None

__all__ = ["GLSeriesPipeline", "gl_series_available"]

#: 顶点着色器：把「数据坐标」经仿射变换映射到 NDC，不做任何 CPU 侧坐标换算。
#: 用 GLSL 1.50（OpenGL 3.2 core）以兼容性优先——实测本机为 4.6 兼容档，
#: 3.2 core 语法在兼容档与核心档下均可编译。
_VERT_SRC = """
#version 150 core
in vec2 a_pos;
uniform mat4 u_mvp;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 0.0, 1.0);
}
"""

_FRAG_SRC = """
#version 150 core
uniform vec4 u_color;
out vec4 fragColor;
void main() {
    fragColor = u_color;
}
"""


def gl_series_available(context=None) -> bool:
    """当前上下文是否可用 GL 原生系列渲染。"""
    if _np is None:
        return False
    try:
        from PySide6.QtOpenGL import (  # noqa: F401
            QOpenGLBuffer,
            QOpenGLShader,
            QOpenGLShaderProgram,
            QOpenGLVertexArrayObject,
        )
    except Exception:  # noqa: BLE001
        return False
    if context is not None:
        try:
            if context is None or not context.isValid():
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


class GLSeriesPipeline:
    """折线/散点的 GL 绘制管线（VBO + GLSL，数据坐标变换在着色器内完成）。

    用法（GL 视口的 ``paintGL`` 内）::

        pipe = GLSeriesPipeline()
        pipe.ensure(context)                      # 编译着色器、创建缓冲
        pipe.set_vertices(points2d)               # [n,2] float32 数据坐标
        pipe.draw(context, mvp, color, mode="line_strip", width=2.0)

    线程约束：**只能在拥有该 GL 上下文的线程（GUI 线程）内使用**。
    """

    #: 缓存容量上限（顶点数）。超过则不建 VBO——百万点每帧重传不值得。
    MAX_CACHED_VERTICES = 262_144

    def __init__(self) -> None:
        self._prog = None
        self._vbo = None
        self._vao = None
        self._count = 0
        self._version = None
        self._ready = False
        self.last_error = None

    # -- 生命周期 ---------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def vertex_count(self) -> int:
        return self._count

    def ensure(self, context) -> bool:
        """编译着色器并创建缓冲（幂等）；失败返回 ``False`` 且后续调用直接跳过。"""
        if self._ready:
            return True
        if not gl_series_available(context):
            return False
        try:
            from PySide6.QtOpenGL import (
                QOpenGLBuffer,
                QOpenGLShader,
                QOpenGLShaderProgram,
                QOpenGLVertexArrayObject,
            )
            prog = QOpenGLShaderProgram()
            if not prog.addShaderFromSourceCode(QOpenGLShader.Vertex, _VERT_SRC):
                return False
            if not prog.addShaderFromSourceCode(QOpenGLShader.Fragment,
                                               _FRAG_SRC):
                return False
            if not prog.link():
                return False
            vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            if not vbo.create():
                return False
            vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
            vao = QOpenGLVertexArrayObject()
            if not vao.create():
                vbo.destroy()
                return False
            self._prog = prog
            self._vbo = vbo
            self._vao = vao
            self._ready = True
            return True
        except Exception:  # noqa: BLE001 - 任何失败都退化为不可用
            self._prog = None
            self._vbo = None
            self._vao = None
            self._ready = False
            return False

    def release(self) -> None:
        """释放 GL 资源（上下文销毁前必须调用，否则泄漏 GL 对象）。"""
        try:
            if self._vbo is not None:
                self._vbo.destroy()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._vao is not None:
                self._vao.destroy()
        except Exception:  # noqa: BLE001
            pass
        self._prog = None
        self._vbo = None
        self._vao = None
        self._count = 0
        self._ready = False
        self._version = None

    # -- 数据 -------------------------------------------------------------
    def set_vertices(self, points, version=None) -> bool:
        """上传顶点（``[n,2]`` 数据坐标）。``version`` 不变时跳过重传。

        返回是否**实际发生了上传**（False 表示命中缓存或未就绪）。
        """
        if not self._ready:
            return False
        arr = self._as_vertices(points)
        if arr is None:
            return False
        if version is not None and version == self._version \
                and arr.shape[0] == self._count:
            return False
        if arr.shape[0] > self.MAX_CACHED_VERTICES:
            # 超过上限：不缓存（每帧重传百万点得不偿失），由调用方走 QPainter
            return False
        try:
            self._vbo.bind()
            # PySide6 的 QOpenGLFunctions 未暴露 glBufferData；allocate 等价
            self._vbo.allocate(arr.tobytes(), arr.nbytes)
            self._vbo.release()
        except Exception:  # noqa: BLE001
            return False
        self._count = int(arr.shape[0])
        self._version = version
        return True

    @staticmethod
    def _as_vertices(points):
        """规范为 ``float32 [n,2]`` 连续数组；不合格返回 ``None``。"""
        if _np is None or points is None:
            return None
        try:
            arr = _np.asarray(points, dtype=_np.float32)
        except (TypeError, ValueError):
            return None
        if arr.ndim != 2 or arr.shape[1] != 2 or arr.shape[0] < 2:
            return None
        return _np.ascontiguousarray(arr)

    # -- 绘制 -------------------------------------------------------------
    #: 上一次 draw 失败的原因（便于诊断；成功时清空）
    last_error = None

    def draw(self, context, mvp, color, mode: str = "line_strip",
             width: float = 2.0) -> bool:
        """绘制已上传的顶点。

        参数:
            mvp: 4x4 变换矩阵（``build_mvp`` 的返回值），把数据坐标映射到 NDC。
            color: ``(r, g, b, a)``，各分量 0..1（也接受 ``QColor``）。
            mode: ``"line_strip"`` / ``"lines"`` / ``"points"`` / ``"line_loop"``。
        """
        if not self._ready or self._count < 2:
            self.last_error = "未就绪或顶点不足"
            return False
        try:
            f = context.functions()
            self._prog.bind()
            self._prog.setUniformValue("u_mvp", mvp)
            self._prog.setUniformValue("u_color", *_as_color(color))
            self._vao.bind()
            self._vbo.bind()
            # 用 QOpenGLShaderProgram.setAttributeBuffer 而不是
            # QOpenGLFunctions.glVertexAttribPointer：后者的 ptr 形参是 C 侧
            # void*，PySide6 绑定层无法表达（传 None 与传 0 都会被拒绝：
            # TypeError / ValueError）。setAttributeBuffer 内部完成同一件事，
            # 且是 Qt 的惯用写法。
            f.glEnableVertexAttribArray(0)
            self._prog.setAttributeBuffer(0, 0x1406, 0, 2, 0)   # GL_FLOAT
            try:
                f.glLineWidth(float(width))
            except Exception:  # noqa: BLE001 - 部分驱动不支持线宽
                pass
            f.glDrawArrays(_GL_MODES.get(mode, 0x0003), 0, self._count)
            f.glDisableVertexAttribArray(0)
            self._vbo.release()
            self._vao.release()
            self._prog.release()
            self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - 失败即退化为 QPainter 路径
            self.last_error = repr(exc)
            return False


_GL_MODES = {
    "points": 0x0000,       # GL_POINTS
    "lines": 0x0001,        # GL_LINES
    "line_strip": 0x0003,   # GL_LINE_STRIP
    "line_loop": 0x0002,    # GL_LINE_LOOP
}


def _as_matrix(mvp):
    """矩阵直传（``build_mvp`` 已返回 ``QMatrix4x4``）。"""
    return mvp


def _as_color(color):
    """把颜色规范为 0..1 的四个浮点分量。"""
    try:
        if hasattr(color, "redF"):          # QColor
            return (color.redF(), color.greenF(), color.blueF(), color.alphaF())
    except Exception:  # noqa: BLE001
        pass
    seq = list(color) if not isinstance(color, (int, float)) else [color] * 4
    while len(seq) < 4:
        seq.append(1.0)
    out = []
    for c in seq[:4]:
        v = float(c)
        out.append(v / 255.0 if v > 1.0 else v)
    return tuple(out)


def build_mvp(x0, x1, y0, y1):
    """构造「数据坐标 → NDC」的 4x4 矩阵（``QMatrix4x4``）。

    用 ``QMatrix4x4`` 而不是裸 numpy 数组：``QOpenGLShaderProgram`` 对前者有
    明确的 ``setUniformValue`` 重载，对后者的支持取决于版本，风险高。

    变换顺序：先把数据坐标平移到以 (x0,y0) 为原点，再缩放到 NDC 尺寸，然后
    y 轴翻转（屏幕 y 向下、NDC y 向上），最后映射到 [-1,1]。
    """
    try:
        from PySide6.QtGui import QMatrix4x4
    except Exception:  # noqa: BLE001
        return None
    if x1 == x0 or y1 == y0:
        return None
    m = QMatrix4x4()
    # 顺序要紧：QMatrix4x4 的 translate/scale 是**后乘**（作用于当前矩阵右侧），
    # 因此必须先缩放再平移——反过来会把平移量也缩放掉（实测 (0,0) 映射成
    # (-5,-5) 而非 (-1,1)）。
    m.scale(2.0 / (x1 - x0), -2.0 / (y1 - y0), 1.0)
    m.translate(-(x0 + x1) / 2.0, -(y0 + y1) / 2.0, 0.0)
    return m
