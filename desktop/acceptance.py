"""真实 WebView2 桌面验收，独立目录，完成后关闭自己的实例。"""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path

once=threading.Event()

async def native_tool_proof(output,home):
    from lancher_code.config.loader import load_config_data
    from lancher_code.sdk import create_agent,PermissionResolution
    from lancher_code.agent.skills import SkillsService
    from lancher_code.permissions.storage import PermissionStorage
    from lancher_code.contracts.messages import ContentBlock,StreamEvent
    from lancher_code.contracts.tools import ToolCallChunk
    from lancher_code.usage.models import MessageUsage
    workspace=output/'tool-project';workspace.mkdir(exist_ok=True)
    steps=[('write_file',{'path':'proof.txt','content':'frozen-native-proof'}),('read_file',{'path':'proof.txt'}),('run_command',{'description':'桌面冻结包原生 Shell 验收','command':"Write-Output 'desktop-frozen-shell-ok'",'yield_ms':5000,'max_runtime_ms':15000})]
    class ProofProvider:
        position=0
        async def stream_chat(self,request):
            blocks=[]
            if self.position<len(steps):
                name,arguments=steps[self.position];self.position+=1
                identity='desktop-proof-'+str(self.position)
                yield StreamEvent(kind='tool_call_delta',tool_call_chunk=ToolCallChunk(call_index=0,provider_call_id=identity,name_delta=name,arguments_delta=json.dumps(arguments)))
                blocks.append(ContentBlock.tool_use_block(call_id=identity,name=name,input=arguments))
            else:
                yield StreamEvent(kind='text_delta',text='独立工程原生工具验收完成。')
                blocks.append(ContentBlock.text_block('独立工程原生工具验收完成。'))
            yield StreamEvent(kind='message_end',response_complete=True,assistant_blocks=blocks,stop_reason='tool_calls' if self.position<=len(steps) and blocks[0].kind=='tool_use' else None,usage=MessageUsage(input_tokens=5,output_tokens=3))
    config=load_config_data({'providers':{'fixture':{'name':'桌面验收','protocol':'openai','base_url':'http://127.0.0.1:1/v1','api_key':'fixture','models':{'one':{'model_name':'fixture'}}}},'default_model':'fixture/one'}).to_agent_config()
    storage=PermissionStorage(project_rules_path=workspace/'.lancher/permissions.yaml',user_rules_path=home/'.lancher/permissions.yaml')
    agent=create_agent(config,cwd=workspace,provider_factory=lambda _:ProofProvider(),skills_service=SkillsService(workspace,user_root=home),permission_storage=storage,enable_mcp=False)
    results=[]
    agent.subscribe(lambda event:results.append(event.tool_result) if event.kind=='tool_result_received' else None)
    try:
        result=await agent.run('仅验收专用目录内的文件和 Shell 工具。',permission_handler=lambda request:PermissionResolution(request.request_id,'allow_once'))
        return {'status':result.status,'error_text':result.error_text,'completed':result.status=='completed','write_read':(workspace/'proof.txt').read_text()=='frozen-native-proof' and any(item.tool_name=='read_file' and 'frozen-native-proof' in item.content for item in results),'shell':any(item.tool_name=='run_command' and not item.is_error and 'desktop-frozen-shell-ok' in item.content for item in results),'tool_results':len(results),'external_model_requests':0}
    finally:await agent.close()

def smoke(window,bridge,server):
    if once.is_set():return
    once.set()
    output=server.storage/'acceptance'
    output.mkdir(parents=True,exist_ok=True)
    report={'port':server.port,'isolated_data':str(server.storage),'checks':{}}
    try:
        def wait(expression):
            for _ in range(100):
                if window.evaluate_js(expression):return
                time.sleep(.1)
            raise AssertionError(expression)
        wait("!!document.querySelector('.desktop-titlebar') && !document.querySelector('.loading-screen')")
        report['checks']['desktop_titlebar']=window.evaluate_js("document.querySelector('.desktop-titlebar').getBoundingClientRect().height === 40")
        report['checks']['no_duplicate_sidebar_toggle']=window.evaluate_js("getComputedStyle(document.querySelector('.desktop-sidebar-toggle')).display === 'none'")
        window.evaluate_js("document.querySelector('.desktop-navigation button').click()")
        wait("document.querySelector('.app-frame').classList.contains('sidebar-collapsed')")
        window.evaluate_js("document.querySelector('.desktop-navigation button').click()")
        wait("!document.querySelector('.app-frame').classList.contains('sidebar-collapsed')")
        report['checks']['sidebar_toggle']=True
        window.evaluate_js("document.querySelector('.desktop-menu button').click()")
        window.evaluate_js("[...document.querySelectorAll('.desktop-menu-items button')].find(x=>x.textContent==='关于').click()")
        wait("!!document.querySelector('.settings-about')")
        report['checks']['about_desktop']=window.evaluate_js("document.querySelector('.settings-about h2').textContent==='LanCher Code Desktop'")
        window.evaluate_js("document.querySelector('[aria-label=上一页]').click()")
        wait("!document.querySelector('.settings-about')")
        window.evaluate_js("document.querySelector('[aria-label=下一页]').click()")
        wait("!!document.querySelector('.settings-about')")
        report['checks']['navigation_back_forward']=True
        bridge.toggle_maximize()
        wait("document.querySelector('[aria-label=还原窗口]') !== null")
        report['checks']['native_maximized']=str(window.native.WindowState)=='Maximized'
        bridge.toggle_maximize()
        wait("document.querySelector('[aria-label=最大化]') !== null")
        report['checks']['native_restored']=str(window.native.WindowState)=='Normal'
        bridge.minimize();time.sleep(.3)
        report['checks']['native_minimized']=str(window.native.WindowState)=='Minimized'
        bridge._show();time.sleep(.4)
        bridge.hide();time.sleep(.3)
        report['checks']['tray_hidden']=not bool(window.native.Visible)
        bridge._show();time.sleep(.3)
        report['checks']['tray_restored']=bool(window.native.Visible)
        import subprocess,sys
        if getattr(sys,'frozen',False):command=[sys.executable]
        else:command=[sys.executable,'-m','desktop','--resources',str(Path(__file__).resolve().parent.parent/'data/desktop-build/resources')]
        second=subprocess.run([*command,'--data-dir',str(server.storage)],timeout=20,capture_output=True)
        report['checks']['single_instance_activation']=second.returncode==0
        from .frame_acceptance import verify_frame_and_picker
        frame=verify_frame_and_picker(window,server.storage)
        report['frame_and_picker']=frame
        report['checks']['no_native_top_gap']=frame['client_top_gap']==0
        report['checks']['real_mouse_drag']=abs(frame['drag_dx'])>=20 and abs(frame['drag_dy'])>=10
        report['checks']['shared_titlebar_background']=frame['shared_background']
        report['checks']['native_folder_picker']=frame['native_picker_selected']
        report['checks']['native_rounding_enabled']=frame['corner_preference']==2

        # WebView2 原生截图接口直接捕获真实桌面内容，非浏览器模拟。
        from System import Action
        from System.IO import FileStream,FileMode,FileAccess
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        image=output/'desktop-about.png'
        stream=FileStream(str(image),FileMode.Create,FileAccess.Write)
        capture=[]
        window.native.Invoke(Action(lambda:capture.append(window.native.browser.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,stream))))
        capture[0].Wait();stream.Close()
        # 额外捕获自己的前台窗口外缘，供检查真实圆角；不抓取整张桌面。
        import ctypes
        from ctypes import wintypes
        from System.Drawing import Bitmap,Graphics
        from System.Drawing.Imaging import ImageFormat
        user=ctypes.WinDLL('user32');user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)];user.GetForegroundWindow.restype=wintypes.HWND
        handle=int(window.native.Handle.ToInt64());bounds=wintypes.RECT();user.GetWindowRect(handle,ctypes.byref(bounds))
        if user.GetForegroundWindow()==handle:
            bitmap=Bitmap(bounds.right-bounds.left,bounds.bottom-bounds.top);graphics=Graphics.FromImage(bitmap)
            graphics.CopyFromScreen(bounds.left,bounds.top,0,0,bitmap.Size)
            full_image=output/'desktop-window.png';bitmap.Save(str(full_image),ImageFormat.Png);graphics.Dispose();bitmap.Dispose()
            report['window_screenshot']=str(full_image)
        report['screenshot']=str(image)
        report['checks']['screenshot_nonempty']=image.stat().st_size>10000
        report['checks']['no_tasks']=server.activity()=={'tasks':0,'processes':0}
        proof=server.call(native_tool_proof(output,server.home),60)
        report['native_tools']=proof
        report['checks']['native_sdk_tools']=proof['completed'] and proof['write_read'] and proof['shell'] and proof['tool_results']==3
        report['passed']=all(report['checks'].values())
    except Exception as error:
        import traceback
        report['page']=window.evaluate_js("({url:location.origin+location.pathname,flag:window.__LANCHER_DESKTOP__,body:document.body.innerText.slice(0,2000),title:document.title})");report['error']=str(error);report['traceback']=traceback.format_exc();report['passed']=False
    finally:
        (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        bridge._quit()
