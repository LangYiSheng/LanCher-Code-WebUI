import type {Dict} from './types';
export type UsageScope='answer'|'session'|'project'|'server';
export const USAGE_SCOPES=[['answer','本轮'],['session','会话'],['project','项目'],['server','服务']] as const;
export const TOKEN_FIELDS=['input_tokens','output_tokens','cached_input_tokens','cache_creation_input_tokens','reasoning_output_tokens'] as const;
export type TokenField=typeof TOKEN_FIELDS[number];
export const PARTIAL_LABELS:Record<string,string>={input:'输入',output:'输出',cache:'缓存读取',cache_creation:'缓存创建',reasoning:'推理输出'};
export function reportedNumber(value:unknown):number|null {return typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;}
export function usageSummary(all:Dict|undefined,scope:UsageScope){
  const raw:Dict=all?.[scope]||{};
  // SDK 顶层计数是已知小计；嵌套 usage 的 null 才表示完整总量尚未上报。
  const values:Dict=Object.hasOwn(raw,'usage')?(raw.usage&&typeof raw.usage==='object'?raw.usage:{}):raw;
  const tokens=Object.fromEntries(TOKEN_FIELDS.map(key=>[key,reportedNumber(values[key])])) as Record<TokenField,number|null>;
  const partial=Array.isArray(values.partial_fields)?values.partial_fields.filter((key:unknown)=>typeof key==='string') as string[]:[];
  const requestCount=reportedNumber(raw.request_count);
  const invalid=reportedNumber(raw.invalid_request_count);
  const incomplete=reportedNumber(raw.incomplete_request_count);
  const anyKnown=TOKEN_FIELDS.some(key=>tokens[key]!==null);
  const missing=TOKEN_FIELDS.some(key=>tokens[key]===null);
  const isFinal=values.is_final!==false;
  const state=requestCount===0?'empty':!anyKnown?'unknown':(invalid||0)>0?'invalid':!isFinal||(incomplete||0)>0?'incomplete':partial.length||missing?'partial':'complete';
  const quality={empty:'尚无请求',unknown:'尚无有效上报',invalid:'含无效上报',incomplete:'上报未完成',partial:'部分字段未知',complete:'已完整上报'}[state];
  const total=tokens.input_tokens===null&&tokens.output_tokens===null?null:(tokens.input_tokens??0)+(tokens.output_tokens??0);
  const shortKeys:Record<TokenField,string>={input_tokens:'input',output_tokens:'output',cached_input_tokens:'cache',cache_creation_input_tokens:'cache_creation',reasoning_output_tokens:'reasoning'};
  const isPartial=(key:TokenField)=>partial.includes(shortKeys[key])||!isFinal||(incomplete||0)>0;
  const totalPartial=tokens.input_tokens===null||tokens.output_tokens===null||isPartial('input_tokens')||isPartial('output_tokens');
  const knownSubtotal=(key:TokenField)=>{if(tokens[key]!==null&&isPartial(key))return tokens[key];const count=reportedNumber(raw[key]);return tokens[key]===null&&count!==null&&count>0?count:null;};
  const cacheHitRatio=reportedNumber(raw.cache_hit_ratio);
  const cacheRatioEstimated=cacheHitRatio!==null&&raw.cache_ratio_estimated===true;
  const cacheRatioRequestCount=reportedNumber(raw.cache_ratio_request_count);
  const cacheRatioText=cacheHitRatio===null?'—':(cacheRatioEstimated?'≈':'')+(cacheHitRatio*100).toFixed(1)+'%';
  const cacheRatioNote=cacheRatioEstimated?`按 ${cacheRatioRequestCount??'—'} / ${requestCount??'—'} 次请求的已知输入与缓存量计算；估算，可能不准。`
    :cacheHitRatio===null?requestCount===0?'尚无请求。':(invalid||0)>0?'异常请求已排除，暂无可计算的缓存率样本。':'无可计算样本或样本输入为零。':'';
  return {raw,tokens,partial,requestCount,invalid,incomplete,state,quality,total,totalPartial,isPartial,knownSubtotal,isFinal,cacheHitRatio,cacheRatioEstimated,cacheRatioRequestCount,cacheRatioText,cacheRatioNote};
}
export function contextSummary(context:Dict|undefined){
  const raw=context||{};const tokens=reportedNumber(raw.tokens);const reportedWindow=reportedNumber(raw.window);const window=reportedWindow!==null&&reportedWindow>0?reportedWindow:null;
  const ratio=tokens!==null&&window!==null?tokens/window:null;
  const source=raw.snapshot===true?'会话快照估算':({estimated:'本地估算',usage_calibrated:'提供方校准估算'} as Record<string,string>)[raw.source]||'未知';
  const percent=ratio===null?null:Math.round(ratio*100);
  const label=percent!==null?`当前上下文已用 ${percent}%，${tokens?.toLocaleString('zh-CN')} / ${window?.toLocaleString('zh-CN')} tokens，${source}`:tokens!==null?`上下文 ${tokens.toLocaleString('zh-CN')} tokens，模型容量未知`:'当前上下文占用未知';
  return {tokens,window,ratio,percent,source,label,snapshot:raw.snapshot===true};
}
