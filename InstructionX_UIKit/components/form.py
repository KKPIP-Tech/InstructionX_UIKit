# -*- coding: utf-8 -*-
"""表单布局组件（SPEC §5.1）。

``FormLayout`` 在 QFormLayout 基础上增强：必填星号（红色，随主题切换）、
错误提示行（字段下方小字）；``FormItem`` 为单项校验辅助，
负责取值、必填检查、自定义校验器与错误状态展示。
"""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_font

__all__ = ["FormLayout", "FormItem"]

#: 字段容器内「控件 ↔ 错误提示行」的间距：取 2px 半档（space.05）
_FIELD_GAP = int(T("space.05"))
#: 错误提示与字段控件的左缘对齐（契约 §3：标签类元素左缘必须严格一致）。
#:
#: 注意这里**不能**用 ``layout.inset.pad_x``：输入控件的文字起点是
#: 「控件左缘 + 1px 边框 + ``space.3``(12px) 内边距」= 13px，
#: 而 ``layout.inset.pad_x`` 是 8px —— 两者从来不是同一个令牌，
#: 按它补会让错误文案恒定偏左 5~6px（实测差 −6px）。
#: 下面取 ``space.3 + space.05`` = 14px，补齐边框并让两行文字共线。
_ERROR_PAD_X = int(T("space.3")) + int(T("space.05"))


def extract_value(widget):
    """从常见输入控件取值（文本 / 数值 / 勾选 / 当前选项）。"""
    if isinstance(widget, QLineEdit):
        return widget.text()
    if isinstance(widget, QTextEdit):
        return widget.toPlainText()
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, QAbstractButton):
        return widget.isChecked()
    if hasattr(widget, "text"):
        return widget.text()
    if hasattr(widget, "value"):
        return widget.value()
    return None


def _is_empty(value) -> bool:
    """判断取值是否为空（用于必填校验）。"""
    if value is None:
        return True
    if isinstance(value, bool):
        # 复选框未勾选（False）视为空，required=True 时校验失败
        return not value
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


class FormItem(QObject):
    """表单项校验辅助。

    用途:
        绑定「字段控件 + 校验规则 + 错误提示行」，
        由 ``FormLayout.add_row`` 创建，一般无需直接实例化。

    参数:
        label_text: 字段标签文案。
        widget: 字段控件。
        required: 是否必填。
        validator: 自定义校验器，签名为 ``callable(value)``，
            返回 ``True`` / ``None`` 表示通过；返回 ``False`` 或
            错误文案字符串表示失败。
        parent: 父对象。

    示例::

        item = form.add_row("用户名", edit, required=True,
                            validator=lambda v: len(v) >= 3 or "至少 3 个字符")
        ok = item.validate()
        item.set_error("自定义错误")
    """

    #: 校验完成信号（参数为是否通过）
    validated = Signal(bool)

    def __init__(self, label_text: str, widget: QWidget, required: bool,
                 validator, parent: QObject = None):
        super().__init__(parent)
        self.label_text = label_text
        self.widget = widget
        self.required = bool(required)
        self.validator = validator
        self._error_label = None  # 由 FormLayout 注入
        self._label_widget = None
        self._error_msg = ""

    # ------------------------------------------------------------------
    # 取值与校验
    # ------------------------------------------------------------------

    def value(self):
        """字段当前取值。"""
        return extract_value(self.widget)

    def validate(self) -> bool:
        """执行校验：必填 + 自定义校验器；通过返回 True。"""
        value = self.value()
        if self.required and _is_empty(value):
            return self._fail(f"{self.label_text}不能为空")
        if not _is_empty(value) and self.validator is not None:
            result = self.validator(value)
            if result is True or result is None:
                pass
            elif result is False:
                return self._fail(f"{self.label_text}不合法")
            else:
                return self._fail(str(result))
        self.clear_error()
        self.validated.emit(True)
        return True

    def _fail(self, message: str) -> bool:
        self.set_error(message)
        self.validated.emit(False)
        return False

    # ------------------------------------------------------------------
    # 错误状态
    # ------------------------------------------------------------------

    def set_error(self, message: str) -> None:
        """显示错误提示行。"""
        self._error_msg = str(message)
        if self._error_label is not None:
            self._error_label.setText(self._error_msg)
            self._error_label.setVisible(True)

    def clear_error(self) -> None:
        """隐藏错误提示行。"""
        self._error_msg = ""
        if self._error_label is not None:
            self._error_label.clear()
            self._error_label.setVisible(False)

    def error(self) -> str:
        """当前错误文案（无错误返回空串）。"""
        return self._error_msg


class FormLayout(QFormLayout):
    """增强表单布局。

    用途:
        以行（标签 + 字段）组织表单；必填项标签带红色星号，
        校验失败在字段下方显示错误提示行。

    参数:
        parent: 父控件。

    示例::

        form = FormLayout()
        item = form.add_row("用户名", LineEdit(), required=True)
        form.add_row("简介", TextArea())
        if form.validate_all():
            print("全部通过")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._labels = []  # (QLabel, base_text, FormItem)
        self._error_labels = []
        # 版面度量全部走 layout.* 令牌（契约 §2）：QFormLayout 默认用风格
        # 里的间距，既不是令牌值，也无法与其他表单对齐。
        self.setHorizontalSpacing(int(T("layout.field.gap")))   # 标签 ↔ 控件
        self.setVerticalSpacing(int(T("space.2")))              # 行 ↔ 行
        # 同一行控件垂直居中（契约 §3），且标签左缘严格一致
        self.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.setRowWrapPolicy(QFormLayout.DontWrapRows)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 行管理
    # ------------------------------------------------------------------

    def add_row(self, label_text: str, widget: QWidget, required: bool = False,
                validator=None) -> FormItem:
        """添加一行：标签（必填带星号）+ 字段 + 错误提示行。

        返回:
            可用于 ``validate()`` / ``set_error()`` 的 ``FormItem``。
        """
        label = QLabel(self._label_markup(label_text, required))
        label.setTextFormat(Qt.RichText)
        error_label = QLabel("")
        error_label.setVisible(False)
        error_label.setWordWrap(False)  # 错误文案是短句，禁换行避免撑高行
        self._style_error_label(error_label)
        field = QWidget()
        v = QVBoxLayout(field)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(_FIELD_GAP)
        v.addWidget(widget)
        v.addWidget(error_label)
        item = FormItem(label_text, widget, required, validator, parent=self)
        item._error_label = error_label
        item._label_widget = label
        self._items.append(item)
        self._labels.append((label, label_text, item))
        self._error_labels.append(error_label)
        self.addRow(label, field)
        return item

    def items(self) -> list:
        """全部 FormItem。"""
        return list(self._items)

    def validate_all(self) -> bool:
        """逐项校验，全部通过返回 True。"""
        ok = True
        for item in self._items:
            if not item.validate():
                ok = False
        return ok

    def clear_errors(self) -> None:
        """清除全部错误提示。"""
        for item in self._items:
            item.clear_error()

    def set_required(self, item: FormItem, required: bool) -> None:
        """运行时切换某项的必填状态（刷新星号）。"""
        item.required = bool(required)
        self._refresh_label(item)

    # ------------------------------------------------------------------
    # 主题感知
    # ------------------------------------------------------------------

    def _label_markup(self, text: str, required: bool) -> str:
        if required:
            return (f'<span style="color:{T("color.danger")};">* </span>'
                    f'{text}')
        return text

    def _error_style(self) -> str:
        return (f"color: {T('color.danger')}; "
                f"font-size: {T('font.xs')}px; "
                f"padding-left: {_ERROR_PAD_X}px;")

    def _style_error_label(self, label: QLabel) -> None:
        """错误提示行样式（颜色 + 字阶 + 左内边距，均取令牌）。

        不能直接用 ``theme.set_font``：它内部是 ``setStyleSheet``，会
        覆盖掉这里同一次调用里写的颜色与左内边距。故在一处把三个令牌
        拼成一条实例级 QSS——生效机制与 ``set_font`` 完全一致（都是
        实例级样式表压过全局 ``QWidget { font-size }`` 基座规则）。
        """
        label.setStyleSheet(self._error_style())

    def _refresh_label(self, item: FormItem) -> None:
        for label, base, it in self._labels:
            if it is item:
                label.setText(self._label_markup(base, item.required))

    def _on_theme_changed(self, *_args) -> None:
        for label, base, item in self._labels:
            label.setText(self._label_markup(base, item.required))
        for error_label in self._error_labels:
            self._style_error_label(error_label)
