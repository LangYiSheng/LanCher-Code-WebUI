import type {Dict} from './types.ts';
export type DiscoveredModel={id:string;display_name?:string;owned_by?:string;fetched_at?:string;context_window?:number|null;max_output_tokens?:number|null;capabilities?:Dict};
export type DiscoveryResult={discovery_id:string;models:DiscoveredModel[];fetched_at:string;cached:boolean;stale:boolean;notice:string;existing:string[]};
export function discoveryEligible(result:DiscoveryResult){const existing=new Set(result.existing);return result.models.filter(model=>!existing.has(model.id)).map(model=>model.id);}
// 后端返回脱敏目录；只保留本地尚未保存的密钥输入，不覆盖新的能力快照。
export function preserveDiscoverySecrets(original:Dict,merged:Dict):Dict{
  function keep(before:Dict|undefined,after:Dict){if(!before)return after;const next={...after};
    if(Object.hasOwn(before,'api_key'))next.api_key=before.api_key;
    if(Object.hasOwn(before,'api_key_clear'))next.api_key_clear=before.api_key_clear;
    return next;
  }
  const next=keep(original,merged);
  next.models=Object.fromEntries(Object.entries(merged.models||{}).map(([id,model])=>[id,keep(original.models?.[id],model as Dict)]));
  return next;
}
