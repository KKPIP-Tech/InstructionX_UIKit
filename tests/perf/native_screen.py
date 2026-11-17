# -*- coding: utf-8 -*-
"""仅供真实窗口验收使用的 Win32 原生屏幕抓取，不属于 UIKit 运行时。"""

import ctypes
from ctypes import wintypes

from PIL import ImageGrab
from PySide6.QtGui import QImage


class _Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def grab_native_window(window):
    """按 Win32 实际客户区矩形抓取桌面，包含原生 Scene Graph 子窗口。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    rect = _Rect()
    origin = wintypes.POINT(0, 0)
    hwnd = int(window.winId())
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise ctypes.WinError(ctypes.get_last_error())
    image = ImageGrab.grab(
        bbox=(origin.x + rect.left, origin.y + rect.top,
              origin.x + rect.right, origin.y + rect.bottom), all_screens=True)
    image = image.convert("RGBA")
    result = QImage(image.tobytes("raw", "RGBA"), image.width, image.height,
                    image.width * 4, QImage.Format_RGBA8888)
    if result.isNull():
        raise AssertionError("原生窗口屏幕抓取为空")
    return result.copy()
