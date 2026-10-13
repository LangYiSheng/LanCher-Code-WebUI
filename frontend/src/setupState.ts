import type {Dict} from './types';
import type {ValidationIssue} from './settingsValidation';

export type SetupState='required'|'repair'|'unreadable'|'ready';
export type SetupStatus={state:SetupState;config_path:string;issues:ValidationIssue[]};
export type SetupData={models:Dict;ui:Dict;runtime:Dict;execution:Dict};
export type SetupSnapshot=SetupStatus & {revision:string;data:SetupData|null;config_exists?:boolean};
export type SetupStep='connection'|'models'|'ui'|'runtime'|'execution'|'review';
export const SETUP_LABELS:Record<SetupStep,string>={connection:'连接供应商',models:'添加模型',ui:'修复显示参数',runtime:'修复运行参数',execution:'修复执行参数',review:'确认默认模型'};

export type SetupPage=SetupStep|'welcome'|'story'|'source'|'imported';
export function initialSetupPage(snapshot:SetupSnapshot,introSeen=false):SetupPage{
  // 已有配置缺模型属于补配置；全新安装才展示欢迎和能力介绍。
  return snapshot.config_exists===false&&!introSeen?'welcome':'source';
}

export function setupRequired(status:SetupStatus|undefined,models:Dict[],configError?:string):boolean{
  return !!configError||!models.length||!!status&&status.state!=='ready';
}
export function setupSteps(issues:ValidationIssue[]):SetupStep[]{
  return ['connection','models',...(['ui','runtime','execution'] as const).filter(domain=>issues.some(issue=>issue.domain===domain)),'review'];
}
export function setupModelChoices(models:Dict):{id:string;name:string;provider:string}[]{
  const text=(value:unknown,fallback:string)=>typeof value==='string'&&value?value:fallback;
  return Object.entries(models.providers||{}).flatMap(([providerId,source])=>Object.entries((source as Dict).models||{}).map(([modelId,item])=>({id:providerId+'/'+modelId,name:text((item as Dict).display_name,text((item as Dict).model_name,modelId)),provider:text((source as Dict).name,providerId)})));
}
export function chooseOnlyModel(models:Dict):Dict{
  const choices=setupModelChoices(models);
  return choices.length===1&&models.default_model!==choices[0].id?{...models,default_model:choices[0].id}:models;
}
export function issueStep(issue:ValidationIssue):SetupStep{
  if(['ui','runtime','execution'].includes(issue.domain))return issue.domain as SetupStep;
  if(issue.path[0]==='default_model')return 'review';
  return issue.path[0]==='providers'&&issue.path[2]==='models'?'models':'connection';
}
