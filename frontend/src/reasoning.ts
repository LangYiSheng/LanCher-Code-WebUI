import type {ChatSummary} from './types.ts';
export const EFFORT_LABELS:Record<string,string>={auto:'自动',minimal:'极低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最高',ultra:'极高'};
export const API_MODES=[['auto','自动'],['chat_completions','标准聊天'],['chat_completions_legacy','兼容聊天'],['responses','Responses']] as const;
// 只呈现核心为当前连接返回的档位；没有加载能力时仅提供 auto。
export function effortOptions(chat:Pick<ChatSummary,'effort_levels'>|undefined){
  return [...new Set(['auto',...(Array.isArray(chat?.effort_levels)?chat.effort_levels:[])])].filter((level):level is string=>typeof level==='string'&&!!level.trim()&&!['off','none','disabled'].includes(level.toLowerCase()));
}
export function capabilityList(value:unknown,empty:string){return Array.isArray(value)?value.length?value.join(' / '):empty:'未声明';}
