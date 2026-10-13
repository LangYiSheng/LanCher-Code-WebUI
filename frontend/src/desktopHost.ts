export type WindowState={maximized:boolean};
export type DesktopApi={minimize:()=>Promise<void>;toggle_maximize:()=>Promise<WindowState>;window_state:()=>Promise<WindowState>;drag:()=>Promise<void>;resize:(edge:string)=>Promise<void>;close_status:()=>Promise<{tasks:number;processes:number}>;quit:()=>Promise<void>;hide:()=>Promise<void>;import_config:()=>Promise<{imported:boolean}>};
declare global {interface Window {__LANCHER_DESKTOP__?:boolean;__LANCHER_UI_STATE__?:Record<string,unknown>;pywebview?:{api:DesktopApi}}}
export const isDesktop=()=>window.__LANCHER_DESKTOP__===true;
export async function desktopApi():Promise<DesktopApi>{
  if(!isDesktop())throw new Error('当前页面运行在浏览器中。');
  if(window.pywebview?.api)return window.pywebview.api;
  return new Promise((resolve,reject)=>{const ready=()=>{cleanup();if(window.pywebview?.api)resolve(window.pywebview.api);else reject(new Error('桌面窗口连接失败。'));};const timer=setTimeout(()=>{cleanup();reject(new Error('桌面窗口尚未就绪，请稍后重试。'));},5000);const cleanup=()=>{clearTimeout(timer);window.removeEventListener('pywebviewready',ready);};window.addEventListener('pywebviewready',ready,{once:true});});
}
