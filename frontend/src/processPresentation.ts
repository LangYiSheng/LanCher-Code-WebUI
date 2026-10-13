import type {Dict} from './types.ts';

export function processState(process:Dict){
  const active=['starting','running','stopping'].includes(process.status);
  const running=process.status==='running';
  const failed=process.status==='failed'||(typeof process.exit_code==='number'&&process.exit_code!==0);
  const label=({starting:'启动中',running:'运行中',stopping:'停止中',completed:'已退出',exited:'已退出',failed:'失败',cancelled:'已停止',interrupted:'已中断'} as Record<string,string>)[process.status]||process.status||'未知';
  return {active,running,failed,label,tone:failed?'danger':running?'success':active?'working':'muted',canStop:process.status==='starting'||running,canWrite:running,canBackground:running&&process.lifetime!=='session'};
}
export function groupProcesses(processes:Dict[]){
  const active=processes.filter(item=>processState(item).active),finished=processes.filter(item=>!processState(item).active);
  // 活动进程稳定排列；历史按最后更新时间展示，未知时间保留原顺序。
  finished.sort((a,b)=>(Date.parse(b.updated_at||b.started_at)||0)-(Date.parse(a.updated_at||a.started_at)||0));
  return {active,finished};
}
export type ProcessPage={output:string;cursor:number;input:string;loaded:boolean;more:boolean;trimmed:boolean};
export const emptyProcessPage=():ProcessPage=>({output:'',cursor:0,input:'',loaded:false,more:false,trimmed:false});
export function appendProcessOutput(page:ProcessPage,result:Dict):ProcessPage{
  const received=result.output||result.page||result;
  const text=typeof received.text==='string'?received.text:(received.stdout||'')+(received.stderr||'');
  const output=page.output+text;
  return {...page,output:output.slice(-200000),cursor:received.next_cursor??received.cursor??page.cursor,loaded:true,more:received.truncated===true,trimmed:page.trimmed||output.length>200000};
}
