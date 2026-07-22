# -*- coding: utf-8 -*-
"""Demo 交互参数面板（Playground）基础设施。

提供三个可复用构件：

- ``ParamForm``：紧凑参数表单（标签 + 控件网格），支持
  int（滑块 + 数值）/ float / 下拉 / 开关 / 颜色 / 文本，变化即回调；
- ``PlaygroundPanel``：右侧固定宽（默认 280px）参数面板 = 标题 +
  ``ParamForm`` + 「重置」按钮；
- ``ParamCard``：带动画「播放」与底部参数区的演示卡片（动画页使用）。

全部控件使用 InstructionX_UIKit 组件（``sm`` 尺寸），颜色 / 边框 / 文字均命中全局
QSS 或令牌，亮 / 暗主题切换无需重启即可正确换肤。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.components.checkbox import CheckBox
from InstructionX_UIKit.components.color_picker import ColorPicker
from InstructionX_UIKit.components.combo_box import ComboBox
from InstructionX_UIKit.components.line_edit import LineEdit
from InstructionX_UIKit.components.slider import Slider
from InstructionX_UIKit.components.spin_box import DoubleSpinBox, SpinBox
from InstructionX_UIKit.theme import T, set_property

__all__ = [
    "ParamForm",
    "PlaygroundPanel",
    "ParamCard",
    "with_playground",
    "swap_widget",
    "add_specs",
]


def _small_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    set_property(btn, "size", "sm")
    return btn


def add_specs(form: "ParamForm", opts: dict, specs) -> None:
    """按规格元组批量向 ``form`` 添加参数控件，并以默认值初始化 ``opts``。

    规格（元组首元素为类型）::

        ("int",    key, 标签, 默认, 最小, 最大[, 额外 kwargs dict])
        ("float",  key, 标签, 默认, 最小, 最大[, 额外 kwargs dict])
        ("choice", key, 标签, 默认, options)
        ("easing", key, 标签, 默认)        # 缓动下拉（InstructionX_UIKit EASING 键名）
        ("bool",   key, 标签, 默认)
        ("text",   key, 标签, 默认)
    """
    easings = ["standard", "entrance", "spring", "emphasis", "linear"]
    for spec in specs:
        kind = spec[0]
        if kind == "int":
            _, key, label, default, lo, hi = spec[:6]
            extra = spec[6] if len(spec) > 6 else {}
            opts[key] = default
            form.add_int(label, default, lo, hi,
                         lambda v, k=key: opts.__setitem__(k, v),
                         key=key, **extra)
        elif kind == "float":
            _, key, label, default, lo, hi = spec[:6]
            extra = spec[6] if len(spec) > 6 else {}
            opts[key] = default
            form.add_float(label, default, lo, hi,
                           lambda v, k=key: opts.__setitem__(k, v),
                           key=key, **extra)
        elif kind == "choice":
            _, key, label, default, options = spec
            opts[key] = default
            form.add_choice(label, options, default,
                            lambda v, k=key: opts.__setitem__(k, v), key=key)
        elif kind == "easing":
            _, key, label, default = spec
            opts[key] = default
            form.add_choice(label, list(easings), default,
                            lambda v, k=key: opts.__setitem__(k, v), key=key)
        elif kind == "bool":
            _, key, label, default = spec
            opts[key] = default
            form.add_bool(label, default,
                          lambda v, k=key: opts.__setitem__(k, v), key=key)
        elif kind == "text":
            _, key, label, default = spec
            opts[key] = default
            form.add_text(label, default,
                          lambda v, k=key: opts.__setitem__(k, v), key=key)
        else:  # pragma: no cover - 规格错误
            raise ValueError(f"未知参数规格: {spec!r}")


class ParamForm(QWidget):
    """紧凑参数表单：每行 = 标签 + 参数控件，任何变化立即回调。

    每个 ``add_*`` 方法返回主控件（同时登记进 ``controls[key]``），
    回调签名统一为 ``callback(value)``：

    - ``add_int``：值 int（滑块与数值框联动）；
    - ``add_float``：值 float；
    - ``add_choice``：值为选项数据（``options`` 项为 ``(文本, 数据)`` 时取数据，
      否则取选项文本）；
    - ``add_bool``：值 bool；
    - ``add_color``：值 ``QColor``；
    - ``add_text``：值 str。

    参数:
        parent: 父控件。
    """

    #: 任何参数变化时发射：(key, value)
    changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)
        self._entries = []   # [{key, kind, default, control, set_default}]
        self.controls = {}   # key -> 主控件

    # ------------------------------------------------------------------ 登记
    def _label(self, text: str) -> QLabel:
        lab = QLabel(text)
        set_property(lab, "role", "secondary")
        return lab

    def _register(self, key, label, kind, default, control, set_default):
        row = self._grid.rowCount()
        self._grid.addWidget(self._label(label), row, 0,
                             Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(control, row, 1)
        self._entries.append({
            "key": key, "kind": kind, "default": default,
            "control": control, "set_default": set_default,
        })
        self.controls[key] = control
        return control

    def _fire(self, key, callback, value):
        callback(value)
        self.changed.emit(key, value)

    # ------------------------------------------------------------------ 控件
    def add_int(self, label, value, minimum, maximum, callback,
                key=None, step=1, special=None):
        """整数参数：滑块 + 数值框联动。

        参数:
            special: 最小值的特殊文本（如 ``"无限"`` 用于 -1）。
        返回:
            ``SpinBox``（滑块可通过宿主控件的 ``.slider`` 访问）。
        """
        key = key or label
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        slider = Slider(minimum=minimum, maximum=maximum, value=value)
        slider.set_tip_enabled(False)
        spin = SpinBox(minimum=minimum, maximum=maximum, value=value,
                       step=step, size="sm")
        if special:
            spin.setSpecialValueText(special)
        h.addWidget(slider, 1)
        h.addWidget(spin, 0)

        def _from_slider(v):
            spin.setValue(v)  # spin 的 valueChanged 完成回调

        def _from_spin(v):
            slider.blockSignals(True)
            slider.setValue(v)
            slider.blockSignals(False)
            self._fire(key, callback, int(v))

        slider.valueChanged.connect(_from_slider)
        spin.valueChanged.connect(_from_spin)
        host.slider = slider  # 便于测试 / 外部访问
        host.spin = spin
        self._register(key, label, "int", value, host,
                       lambda: spin.setValue(value))
        self.controls[key] = spin  # 主控件登记为数值框
        return spin

    def add_float(self, label, value, minimum, maximum, callback,
                  key=None, step=0.1, decimals=2, suffix=""):
        """浮点参数：小数调节框。"""
        key = key or label
        spin = DoubleSpinBox(minimum=minimum, maximum=maximum, value=value,
                             step=step, decimals=decimals, suffix=suffix,
                             size="sm")
        spin.valueChanged.connect(
            lambda v: self._fire(key, callback, float(v)))
        self._register(key, label, "float", value, spin,
                       lambda: spin.setValue(value))
        return spin

    def add_choice(self, label, options, value, callback, key=None):
        """下拉参数。

        参数:
            options: 选项列表；项为 ``str`` 或 ``(显示文本, 数据)``。
            value: 当前值（与数据或文本匹配）。
        """
        key = key or label
        combo = ComboBox(size="sm")
        for opt in options:
            if isinstance(opt, (tuple, list)) and len(opt) == 2:
                combo.addItem(str(opt[0]), opt[1])
            else:
                combo.addItem(str(opt), opt)
        index = 0
        for i in range(combo.count()):
            if combo.itemData(i) == value or combo.itemText(i) == str(value):
                index = i
                break
        combo.setCurrentIndex(index)

        def _changed(i):
            if i >= 0:
                self._fire(key, callback, combo.itemData(i))

        combo.currentIndexChanged.connect(_changed)
        self._register(key, label, "choice", value, combo,
                       lambda: combo.setCurrentIndex(index))
        return combo

    def add_bool(self, label, value, callback, key=None):
        """开关参数：复选框。"""
        key = key or label
        box = CheckBox("", checked=bool(value))
        box.toggled.connect(lambda on: self._fire(key, callback, bool(on)))
        self._register(key, label, "bool", bool(value), box,
                       lambda: box.setChecked(bool(value)))
        return box

    def add_color(self, label, value, callback, key=None, show_text=True):
        """颜色参数：InstructionX_UIKit ColorPicker（QColor 或 ``#RRGGBB``）。"""
        key = key or label
        picker = ColorPicker(value if isinstance(value, QColor) else str(value),
                             size="sm", show_text=show_text)
        picker.colorChanged.connect(
            lambda c: self._fire(key, callback, QColor(c)))
        self._register(key, label, "color", QColor(value), picker,
                       lambda: picker.set_color(QColor(value)))
        return picker

    def add_text(self, label, value, callback, key=None, placeholder=""):
        """文本参数：单行输入（输入即回调）。"""
        key = key or label
        edit = LineEdit(text=str(value), placeholder=placeholder, size="sm")
        edit.textChanged.connect(lambda s: self._fire(key, callback, str(s)))
        self._register(key, label, "text", str(value), edit,
                       lambda: edit.setText(str(value)))
        return edit

    # ------------------------------------------------------------------ 维护
    def reset(self):
        """全部参数恢复默认值（逆序设置，变化项会触发回调）。"""
        for entry in reversed(self._entries):
            entry["set_default"]()

    def values(self):
        """当前各参数值快照：``{key: value}``。"""
        out = {}
        for entry in self._entries:
            kind, c = entry["kind"], entry["control"]
            if kind == "int":
                out[entry["key"]] = c.spin.value()
            elif kind == "float":
                out[entry["key"]] = c.value()
            elif kind == "choice":
                out[entry["key"]] = c.currentData()
            elif kind == "bool":
                out[entry["key"]] = c.isChecked()
            elif kind == "color":
                out[entry["key"]] = c.color()
            elif kind == "text":
                out[entry["key"]] = c.text()
        return out


class PlaygroundPanel(QFrame):
    """右侧固定宽参数面板：标题 + ``ParamForm`` + 「重置」按钮。

    ``add_*`` 方法与 ``ParamForm`` 相同（委托给内部表单）；
    ``controls`` 字典暴露各参数主控件，便于测试与外部访问。

    参数:
        title: 面板标题。
        width: 固定宽度，默认 280。
        parent: 父控件。
    """

    def __init__(self, title: str = "参数调节", width: int = 280, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)  # 命中 QSS 卡片边框
        self.setFixedWidth(int(width))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head = QLabel(title)
        font = QFont()
        font.setWeight(QFont.Weight(T("font.weight.semibold")))
        head.setFont(font)
        lay.addWidget(head)

        self.form = ParamForm(self)
        lay.addWidget(self.form)
        lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.reset_button = _small_button("重置")
        self.reset_button.clicked.connect(self.form.reset)
        btn_row.addWidget(self.reset_button)
        lay.addLayout(btn_row)

        self.controls = self.form.controls
        self.changed = self.form.changed  # Signal(str, object)

    # -- 委托 add_* ------------------------------------------------------
    def add_int(self, *args, **kwargs):
        return self.form.add_int(*args, **kwargs)

    def add_float(self, *args, **kwargs):
        return self.form.add_float(*args, **kwargs)

    def add_choice(self, *args, **kwargs):
        return self.form.add_choice(*args, **kwargs)

    def add_bool(self, *args, **kwargs):
        return self.form.add_bool(*args, **kwargs)

    def add_color(self, *args, **kwargs):
        return self.form.add_color(*args, **kwargs)

    def add_text(self, *args, **kwargs):
        return self.form.add_text(*args, **kwargs)

    def reset(self):
        self.form.reset()

    def values(self):
        return self.form.values()


def with_playground(demo: QWidget, panel: PlaygroundPanel,
                    spacing: int = 12) -> QWidget:
    """演示区 + 右侧参数面板 的水平容器（演示区拉伸，面板固定宽）。"""
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    lay.addWidget(demo, 1)
    lay.addWidget(panel, 0)
    return host


def swap_widget(container: QWidget, widget: QWidget,
                alignment=Qt.AlignmentFlag.AlignCenter):
    """替换容器内唯一子控件（旧控件 deleteLater），用于重建式参数应用。"""
    lay = container.layout()
    if lay is None:
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
    while lay.count():
        item = lay.takeAt(0)
        old = item.widget()
        if old is not None:
            old.setParent(None)
            old.deleteLater()
    lay.addWidget(widget, 0, alignment)
    widget.show()
    return widget


def _stop_handle(handle):
    """安全停止动画句柄（无 stop 方法的句柄忽略）。"""
    if handle is None:
        return
    try:
        handle.stop()
    except Exception:  # noqa: BLE001
        pass


class ParamCard(QFrame):
    """带参数区的动画演示卡片：标题 + 演示区 + 参数表单 + 「播放」。

    参数:
        title: 卡片标题。
        demo: 初始演示控件（可后续 ``set_demo`` 替换）。
        play: 「播放」回调，``play() -> 句柄 | None``。
        hint: 简短说明。
        demo_height: 演示区最小高度。
        continuous: True 时任何参数变化都会自动重放（连续型动画）。
        on_stop: 重放前对旧句柄的自定义清理（默认调用 ``stop()``）。
        parent: 父控件。
    """

    def __init__(self, title: str, demo: QWidget = None, play=None,
                 hint: str = "", demo_height: int = 130,
                 continuous: bool = False, on_stop=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)  # 命中 QSS 卡片边框

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QLabel(title)
        head_font = QFont()
        head_font.setWeight(QFont.Weight(T("font.weight.semibold")))
        head.setFont(head_font)
        lay.addWidget(head)

        if hint:
            hint_lab = QLabel(hint)
            hint_lab.setWordWrap(True)
            set_property(hint_lab, "role", "tertiary")
            lay.addWidget(hint_lab)

        self._demo_host = QWidget()
        demo_lay = QVBoxLayout(self._demo_host)
        demo_lay.setContentsMargins(0, 2, 0, 2)
        self._demo_host.setMinimumHeight(demo_height)
        lay.addWidget(self._demo_host, 1)
        self.demo = None
        if demo is not None:
            self.set_demo(demo)

        self.form = ParamForm(self)
        lay.addWidget(self.form)
        self.controls = self.form.controls
        self.changed = self.form.changed

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.play_button = _small_button("播放")
        self.play_button.clicked.connect(self.replay)
        btn_row.addWidget(self.play_button)
        lay.addLayout(btn_row)

        self._play = play
        self._on_stop = on_stop
        self.continuous = bool(continuous)
        self.handle = None
        self.form.changed.connect(self._on_param_changed)

    # ------------------------------------------------------------------
    def set_demo(self, widget: QWidget) -> QWidget:
        """替换演示控件（旧控件销毁），用于按新参数重建演示对象。"""
        self.demo = swap_widget(self._demo_host, widget)
        return self.demo

    def set_play(self, play) -> None:
        self._play = play

    def replay(self):
        """停止旧句柄并按当前参数重放。"""
        if self._on_stop is not None:
            try:
                self._on_stop(self.handle)
            except Exception:  # noqa: BLE001
                pass
        else:
            _stop_handle(self.handle)
        self.handle = None
        if self._play is None:
            return None
        try:
            self.handle = self._play()
        except Exception:  # noqa: BLE001
            self.handle = None
        return self.handle

    def _on_param_changed(self, *_):
        if self.continuous:
            self.replay()
