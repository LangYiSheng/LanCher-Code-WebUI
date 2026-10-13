export type WorkbenchLocation={project:string|null;chat:string|null;settings:boolean;section:string};
export type NavigationState={entries:WorkbenchLocation[];index:number};
export const sameLocation=(a:WorkbenchLocation,b:WorkbenchLocation)=>a.project===b.project&&a.chat===b.chat&&a.settings===b.settings&&(!a.settings||a.section===b.section);
export function visitLocation(state:NavigationState,next:WorkbenchLocation):NavigationState{
  if(state.entries[state.index]&&sameLocation(state.entries[state.index],next))return state;
  const entries=[...state.entries.slice(0,state.index+1),{...next}].slice(-100);return {entries,index:entries.length-1};
}
export function moveLocation(state:NavigationState,offset:number):NavigationState{const index=state.index+offset;return index<0||index>=state.entries.length?state:{...state,index};}
