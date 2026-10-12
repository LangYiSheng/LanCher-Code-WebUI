export const DEFAULT_PANEL_WIDTH=520;
export const PANEL_CLOSE_THRESHOLD=240;
export function panelBounds(workspaceWidth:number,overlay:boolean){
  const available=Math.max(0,Math.floor(Number.isFinite(workspaceWidth)?workspaceWidth:0));
  const max=overlay?available:Math.max(0,available-420);
  return {min:Math.min(280,max),max};
}
export function clampPanelWidth(value:number,bounds:{min:number;max:number}){
  const width=Number.isFinite(value)?value:DEFAULT_PANEL_WIDTH;
  return Math.round(Math.min(bounds.max,Math.max(bounds.min,width)));
}
