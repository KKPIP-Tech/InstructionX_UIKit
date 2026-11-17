# -*- coding: utf-8 -*-
"""对原始 uniform_style 快照逐项核对公开 API 兼容性。"""

import enum
import importlib
import inspect
import json
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = ROOT / "temp" / "performance" / (
    "949b7288a50b6ed5beed744db3c8bf46a13c00ef" ) / "api-baseline.json"
ALLOWED_NEW = {
    ("InstructionX_UIKit.charts", "ChartWidget", "on_ui_activated"),
    ("InstructionX_UIKit.charts", "ChartWidget", "on_ui_deactivated"),
    ("InstructionX_UIKit.blueprint", "BlueprintCanvas", "on_ui_activated"),
    ("InstructionX_UIKit.blueprint", "BlueprintCanvas", "on_ui_deactivated"),
    ("InstructionX_UIKit.layouts", "ChatConversation", "on_ui_activated"),
    ("InstructionX_UIKit.layouts", "ChatConversation", "on_ui_deactivated"),
}


def qualified(value):
    return f"{value.__module__}.{value.__qualname__}"


def compare_class(module_name, name, expected, actual, differences):
    expected_class = expected["class"]
    if actual.__module__ != expected_class["module"]:
        differences.append(f"{module_name}.{name}: 模块 {actual.__module__} != {expected_class['module']}")
    actual_signature = str(inspect.signature(actual))
    if actual_signature != expected_class["signature"]:
        differences.append(
            f"{module_name}.{name}: 签名 {actual_signature} != {expected_class['signature']}")
    actual_bases = [qualified(base) for base in actual.__bases__]
    if actual_bases != expected_class["bases"]:
        differences.append(f"{module_name}.{name}: 基类 {actual_bases} != {expected_class['bases']}")
    for method, signature in expected_class["methods"].items():
        if not hasattr(actual, method):
            differences.append(f"{module_name}.{name}.{method}: 缺少方法")
            continue
        actual_signature = str(inspect.signature(getattr(actual, method)))
        if actual_signature != signature:
            differences.append(
                f"{module_name}.{name}.{method}: 签名 {actual_signature} != {signature}")
    for property_name in expected_class["properties"]:
        if not isinstance(getattr(actual, property_name, None), property):
            differences.append(f"{module_name}.{name}.{property_name}: 缺少 property")
    from PySide6.QtCore import Signal
    for signal in expected_class["signals"]:
        if not isinstance(getattr(actual, signal, None), Signal):
            differences.append(f"{module_name}.{name}.{signal}: 缺少信号")


def main():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["modules"]
    current = {}
    differences = []
    for module_name, exports in baseline.items():
        module = importlib.import_module(module_name)
        current[module_name] = {}
        for name, expected in exports.items():
            if not hasattr(module, name):
                differences.append(f"{module_name}.{name}: 缺少导出")
                continue
            actual = getattr(module, name)
            kind = expected["kind"]
            if kind in ("type", "ObjectType", "EnumType"):
                if not inspect.isclass(actual):
                    differences.append(f"{module_name}.{name}: 不是类")
                    continue
                if kind == "ObjectType" and not issubclass(actual, __import__(
                        "PySide6.QtCore", fromlist=["QObject"]).QObject):
                    differences.append(f"{module_name}.{name}: 不是 QObject 子类")
                if kind == "EnumType" and not issubclass(actual, enum.Enum):
                    differences.append(f"{module_name}.{name}: 不是 Enum")
                compare_class(module_name, name, expected, actual, differences)
            else:
                if kind == "function" and not callable(actual):
                    differences.append(f"{module_name}.{name}: 不可调用")
                elif kind not in ("function", "tuple") and not isinstance(
                        actual, getattr(__import__("builtins"), kind)):
                    differences.append(f"{module_name}.{name}: 类型不是 {kind}")
            current[module_name][name] = kind
    for module_name, class_name, method in sorted(ALLOWED_NEW):
        module = importlib.import_module(module_name)
        if not hasattr(getattr(module, class_name), method):
            differences.append(f"{module_name}.{class_name}.{method}: 允许的新接口缺失")
    from InstructionX_UIKit.charts.stream import StreamSession
    if not hasattr(StreamSession, "set_active"):
        differences.append("charts.stream.StreamSession.set_active: 允许的新接口缺失")
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    destination = ROOT / "temp" / "performance" / source_sha
    destination.mkdir(parents=True, exist_ok=True)
    report = {"source_sha": source_sha, "baseline": str(BASELINE),
              "exports_checked": sum(len(exports) for exports in baseline.values()),
              "allowed_new": sorted(ALLOWED_NEW),
              "differences": differences}
    (destination / "api-compat.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if differences:
        for difference in differences[:60]:
            print("  [差异]", difference)
        print(f"共 {len(differences)} 项差异，报告：{destination / 'api-compat.json'}")
        return 1
    print(f"  [通过] {report['exports_checked']} 个公开导出及允许的新生命周期接口全部兼容")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
