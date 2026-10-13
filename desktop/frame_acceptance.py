"""仅操作验收实例自己的窗口，验证真实鼠标与原生目录选择。"""
import ctypes
from ctypes import wintypes
import os
import time

class Mouse(ctypes.Structure):
    _fields_=[('x',wintypes.LONG),('y',wintypes.LONG),('data',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
class Keyboard(ctypes.Structure):
    _fields_=[('key',wintypes.WORD),('scan',wintypes.WORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
class Hardware(ctypes.Structure):
    _fields_=[('message',wintypes.DWORD),('low',wintypes.WORD),('high',wintypes.WORD)]
class InputData(ctypes.Union):
    _fields_=[('mouse',Mouse),('keyboard',Keyboard),('hardware',Hardware)]
class Input(ctypes.Structure):
    _fields_=[('kind',wintypes.DWORD),('data',InputData)]

def verify_frame_and_picker(window,storage):
    user=ctypes.WinDLL('user32',use_last_error=True)
    hwnd=int(window.native.Handle.ToInt64())
    user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p];user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    previous_dpi=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    from System import Action
    window.native.Invoke(Action(lambda:setattr(window.native,'TopMost',True)))
    window.native.Invoke(Action(lambda:window.native.Activate()))
    time.sleep(.15)
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    user.SendInput.argtypes=[wintypes.UINT,ctypes.POINTER(Input),ctypes.c_int]
    user.GetForegroundWindow.restype=wintypes.HWND
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    def send(items):
        array=(Input*len(items))(*items)
        if user.SendInput(len(items),array,ctypes.sizeof(Input))!=len(items):raise ctypes.WinError(ctypes.get_last_error())
    def move(x,y):
        left=user.GetSystemMetrics(76);top=user.GetSystemMetrics(77)
        width=user.GetSystemMetrics(78);height=user.GetSystemMetrics(79)
        send([Input(0,InputData(mouse=Mouse(round((x-left)*65535/(width-1)),round((y-top)*65535/(height-1)),0,0xC001,0,0)))])
    def button(flag):send([Input(0,InputData(mouse=Mouse(0,0,0,flag,0,0)))])
    def key(value,up=False):send([Input(1,InputData(keyboard=Keyboard(value,0,2 if up else 0,0,0)))])
    def text(value):
        code=value.encode('utf-16-le')
        items=[]
        for index in range(0,len(code),2):
            scan=int.from_bytes(code[index:index+2],'little')
            items.extend([Input(1,InputData(keyboard=Keyboard(0,scan,4,0,0))),Input(1,InputData(keyboard=Keyboard(0,scan,6,0,0)))])
        send(items)
    before=wintypes.RECT();client=wintypes.RECT();origin=wintypes.POINT(0,0)
    user.GetWindowRect(hwnd,ctypes.byref(before));user.GetClientRect(hwnd,ctypes.byref(client));user.ClientToScreen(hwnd,ctypes.byref(origin))
    report={'client_top_gap':origin.y-before.top,'client_left_gap':origin.x-before.left}
    rect=window.evaluate_js("(()=>{const r=document.querySelector('.desktop-drag-area').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:innerWidth};})()")
    scale=client.right/rect['width'];x=origin.x+round(rect['x']*scale);y=origin.y+round(rect['y']*scale)
    cursor=wintypes.POINT();user.GetCursorPos(ctypes.byref(cursor))
    window.evaluate_js("window.__frame_test_pointer=null;document.addEventListener('mousedown',event=>{window.__frame_test_pointer={x:event.clientX,y:event.clientY,target:event.target.className};},{once:true});")
    try:
        user.WindowFromPoint.argtypes=[wintypes.POINT];user.WindowFromPoint.restype=wintypes.HWND
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
        move(x,y);time.sleep(.1)
        if user.GetAncestor(user.WindowFromPoint(wintypes.POINT(x,y)),2)!=hwnd:raise AssertionError('鼠标位置没有命中验收窗口，未点击。')
        if user.GetForegroundWindow()!=hwnd:
            button(2);time.sleep(.15);button(4);time.sleep(user.GetDoubleClickTime()/1000+.15)
        if user.GetForegroundWindow()!=hwnd:raise AssertionError('验收窗口未被激活，未执行拖动。')
        button(2);time.sleep(.4)
        for step in range(1,9):move(x+step*7,y+step*3);time.sleep(.035)
        button(4);time.sleep(.25)
        after=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(after))
        report['drag_dx']=after.left-before.left;report['drag_dy']=after.top-before.top
        report['pointer_event']=window.evaluate_js('window.__frame_test_pointer')
    finally:button(4);move(cursor.x,cursor.y)
    dwm=ctypes.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
    rounding=wintypes.DWORD();dwm.DwmGetWindowAttribute(hwnd,33,ctypes.byref(rounding),ctypes.sizeof(rounding))
    report['corner_preference']=rounding.value
    report['shared_background']=window.evaluate_js("getComputedStyle(document.querySelector('.desktop-titlebar')).backgroundColor === 'rgba(0, 0, 0, 0)'")
    # 从共享项目表单真正点“浏览”，不直接返回假路径。
    window.evaluate_js("document.querySelector('.desktop-menu button').click()")
    window.evaluate_js("[...document.querySelectorAll('.desktop-menu-items button')].find(x=>x.textContent==='打开项目').click()")
    time.sleep(.15)
    window.evaluate_js("document.querySelector('.path-input button').click()")
    thread=user.GetWindowThreadProcessId(hwnd,None)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumThreadWindows.argtypes=[wintypes.DWORD,callback_type,wintypes.LPARAM]
    found=[]
    def collect(handle,data):
        name=ctypes.create_unicode_buffer(80);user.GetClassNameW(handle,name,80)
        if name.value=='#32770':found.append(handle)
        return True
    callback=callback_type(collect)
    for _ in range(80):
        user.EnumThreadWindows(thread,callback,0)
        if found:break
        time.sleep(.1)
    if not found:raise AssertionError('原生文件夹选择器未出现。')
    dialog=found[0]
    pid=wintypes.DWORD();user.GetWindowThreadProcessId(dialog,ctypes.byref(pid))
    if pid.value!=os.getpid():raise AssertionError('目录选择器不属于验收实例。')
    try:
        user.SetForegroundWindow.argtypes=[wintypes.HWND];user.SetForegroundWindow(dialog);time.sleep(.2)
        foreground=user.GetForegroundWindow();foreground_pid=wintypes.DWORD();user.GetWindowThreadProcessId(foreground,ctypes.byref(foreground_pid))
        if foreground_pid.value!=os.getpid():raise AssertionError('验收目录窗口没有获得焦点，未发送按键。')
        key(0x11);key(0x4C);key(0x4C,True);key(0x11,True);time.sleep(.15)
        # 当前目录取服务器提供的独立验收存储，不选择或修改用户工程。
        from pathlib import Path
        selected=Path(storage)
        text(str(selected.resolve()));key(0x0D);key(0x0D,True);time.sleep(.4)
        user.GetDlgItem.argtypes=[wintypes.HWND,ctypes.c_int];user.GetDlgItem.restype=wintypes.HWND
        accept=user.GetDlgItem(dialog,1)
        if not accept:raise AssertionError('找不到原生文件夹选择按钮。')
        user.PostMessageW(accept,0x00F5,0,0)  # BM_CLICK：只点击自己的系统选择器。
        for _ in range(60):
            actual=window.evaluate_js("document.querySelector('.path-input input')?.value")
            if actual and Path(actual).resolve()==selected.resolve():break
            time.sleep(.1)
        report['native_picker_path']=actual
        report['native_picker_selected']=bool(actual) and Path(actual).resolve()==selected.resolve()
        window.evaluate_js("document.querySelector('dialog[open] [aria-label=关闭弹窗]').click()")
    finally:user.PostMessageW(dialog,0x0010,0,0)
    window.native.Invoke(Action(lambda:setattr(window.native,'TopMost',False)))
    user.SetThreadDpiAwarenessContext(previous_dpi)
    return report
