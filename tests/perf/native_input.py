# -*- coding: utf-8 -*-
"""Windows 原生指针与监视器坐标；仅用于真实窗口验收，不属于 UIKit 运行时。"""

import ctypes
from ctypes import wintypes
import time

_USER32 = ctypes.WinDLL("user32", use_last_error=True)


class _Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _Rect),
                ("rcWork", _Rect), ("dwFlags", wintypes.DWORD)]


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]


_USER32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_USER32.GetCursorPos.restype = wintypes.BOOL
_USER32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_USER32.SetCursorPos.restype = wintypes.BOOL
_USER32.GetSystemMetrics.argtypes = [ctypes.c_int]
_USER32.GetSystemMetrics.restype = ctypes.c_int
_USER32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
_USER32.SendInput.restype = wintypes.UINT
_USER32.GetForegroundWindow.restype = wintypes.HWND
_USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
_USER32.SetForegroundWindow.restype = wintypes.BOOL
_USER32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_USER32.MonitorFromWindow.restype = wintypes.HMONITOR
_USER32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_USER32.MonitorFromPoint.restype = wintypes.HMONITOR
_USER32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
_USER32.GetMonitorInfoW.restype = wintypes.BOOL
_USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
_USER32.GetWindowRect.restype = wintypes.BOOL


def cursor_pos():
    point = wintypes.POINT()
    if not _USER32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return point.x, point.y


def _send(flags, x=None, y=None):
    event = _Input()
    event.type = 0
    event.union.mi.dwFlags = flags
    if x is not None:
        left = _USER32.GetSystemMetrics(76)
        top = _USER32.GetSystemMetrics(77)
        width = _USER32.GetSystemMetrics(78)
        height = _USER32.GetSystemMetrics(79)
        event.union.mi.dx = round((x - left) * 65535 / max(1, width - 1))
        event.union.mi.dy = round((y - top) * 65535 / max(1, height - 1))
    if _USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def move_to(x, y):
    target = round(x), round(y)
    direct = _USER32.SetCursorPos(*target)
    deadline = time.perf_counter() + 0.05
    actual = cursor_pos()
    while direct and actual != target and time.perf_counter() < deadline:
        time.sleep(0.001)
        actual = cursor_pos()
    if actual == target:
        return actual
    _send(0x0001 | 0x8000 | 0x4000, *target)
    deadline = time.perf_counter() + 0.05
    actual = cursor_pos()
    while actual != target and time.perf_counter() < deadline:
        time.sleep(0.001)
        actual = cursor_pos()
    if actual != target:
        raise AssertionError(f"原生光标位置不一致: 预期 {target}，实际 {actual}")
    return actual


def left_button(down):
    _send(0x0002 if down else 0x0004)


def client_to_physical(widget, point):
    global_point = widget.mapToGlobal(point)
    screen = widget.screen()
    origin = screen.geometry().topLeft()
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    monitor = _USER32.MonitorFromWindow(widget.window().winId(), 2)
    if not monitor or not _USER32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    dpr = screen.devicePixelRatio()
    return (round(info.rcMonitor.left + (global_point.x() - origin.x()) * dpr),
            round(info.rcMonitor.top + (global_point.y() - origin.y()) * dpr))


def global_to_physical(screen, point):
    origin = screen.geometry().topLeft()
    dpr = screen.devicePixelRatio()
    candidate = wintypes.POINT(
        round(origin.x() + (point.x() - origin.x()) * dpr),
        round(origin.y() + (point.y() - origin.y()) * dpr))
    monitor = _USER32.MonitorFromPoint(candidate, 2)
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not _USER32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    expected_width = round(screen.geometry().width() * dpr)
    expected_height = round(screen.geometry().height() * dpr)
    if abs(info.rcMonitor.right - info.rcMonitor.left - expected_width) > 2 \
            or abs(info.rcMonitor.bottom - info.rcMonitor.top - expected_height) > 2:
        raise RuntimeError(f"目标屏幕与原生显示器不一致: {screen.name()}")
    return (round(info.rcMonitor.left + (point.x() - origin.x()) * dpr),
            round(info.rcMonitor.top + (point.y() - origin.y()) * dpr))


def is_foreground(widget):
    return _USER32.GetForegroundWindow() == int(widget.window().winId())


def activate_window(widget):
    from PySide6.QtCore import QCoreApplication

    window = widget.window()
    window.raise_()
    window.activateWindow()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        _USER32.SetForegroundWindow(int(window.winId()))
        QCoreApplication.processEvents()
        if is_foreground(widget):
            return True
        time.sleep(0.02)
    return False


def window_rect(widget):
    rect = _Rect()
    if not _USER32.GetWindowRect(widget.window().winId(), ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    return [rect.left, rect.top, rect.right, rect.bottom]
