"""保留 Windows 窗口能力，同时由共享前端绘制完整客户区。"""
from __future__ import annotations
import ctypes
from ctypes import wintypes

LRESULT=ctypes.c_ssize_t
UINT_PTR=ctypes.c_size_t
SUBCLASSPROC=ctypes.WINFUNCTYPE(LRESULT,wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,UINT_PTR,UINT_PTR)

class MonitorInfo(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]

class Margins(ctypes.Structure):
    _fields_=[('left',ctypes.c_int),('right',ctypes.c_int),('top',ctypes.c_int),('bottom',ctypes.c_int)]

class NativeFrame:
    def __init__(self,handle):
        self.handle=handle
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.controls=ctypes.WinDLL('comctl32',use_last_error=True)
        self.user.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int];self.user.GetWindowLongW.restype=wintypes.LONG
        self.user.SetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.LONG]
        self.user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        self.user.IsZoomed.argtypes=[wintypes.HWND];self.user.IsZoomed.restype=wintypes.BOOL
        self.user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];self.user.MonitorFromWindow.restype=wintypes.HANDLE
        self.user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
        self.controls.SetWindowSubclass.argtypes=[wintypes.HWND,SUBCLASSPROC,UINT_PTR,UINT_PTR];self.controls.SetWindowSubclass.restype=wintypes.BOOL
        self.controls.DefSubclassProc.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];self.controls.DefSubclassProc.restype=LRESULT
        self.controls.RemoveWindowSubclass.argtypes=[wintypes.HWND,SUBCLASSPROC,UINT_PTR]
        # 必须随窗口保留回调，禁止被 Python 垃圾回收。
        self.callback=SUBCLASSPROC(self._procedure)

    def install(self):
        if not self.controls.SetWindowSubclass(self.handle,self.callback,1,0):raise ctypes.WinError(ctypes.get_last_error())
        style=self.user.GetWindowLongW(self.handle,-16)
        self.user.SetWindowLongW(self.handle,-16,style|0x00040000|0x00020000|0x00010000)
        dwm=ctypes.WinDLL('dwmapi')
        dwm.DwmExtendFrameIntoClientArea.argtypes=[wintypes.HWND,ctypes.POINTER(Margins)]
        dwm.DwmExtendFrameIntoClientArea(self.handle,ctypes.byref(Margins(0,0,0,0)))
        # Windows 11 的外边线不再以白色压在自绘标题栏上；旧系统忽略不支持项。
        dwm.DwmSetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        rounding=wintypes.DWORD(2)
        dwm.DwmSetWindowAttribute(self.handle,33,ctypes.byref(rounding),ctypes.sizeof(rounding))
        no_border=wintypes.DWORD(0xfffffffe)
        dwm.DwmSetWindowAttribute(self.handle,34,ctypes.byref(no_border),ctypes.sizeof(no_border))
        self.user.SetWindowPos(self.handle,None,0,0,0,0,0x0037)

    def _procedure(self,handle,message,wparam,lparam,identity,data):
        if message==0x0083 and wparam:  # WM_NCCALCSIZE：完整窗口作为客户区。
            if self.user.IsZoomed(handle):
                info=MonitorInfo();info.size=ctypes.sizeof(info)
                monitor=self.user.MonitorFromWindow(handle,2)
                if self.user.GetMonitorInfoW(monitor,ctypes.byref(info)):
                    rectangle=ctypes.cast(lparam,ctypes.POINTER(wintypes.RECT)).contents
                    rectangle.left=info.work.left;rectangle.top=info.work.top
                    rectangle.right=info.work.right;rectangle.bottom=info.work.bottom
            return 0
        if message==0x0082:self.controls.RemoveWindowSubclass(handle,self.callback,identity)
        return self.controls.DefSubclassProc(handle,message,wparam,lparam)
