import test from 'node:test';
import assert from 'node:assert/strict';
import {panelBounds,clampPanelWidth,DEFAULT_PANEL_WIDTH,PANEL_CLOSE_THRESHOLD} from '../src/panelResize.ts';
import {restoreDraftChats,draftCreatePayload} from '../src/drafts.ts';
const id='0123456789abcdef0123456789abcdef';
const draft={id,project_id:'project-a',title:'草稿',draft:true,status:'idle',phase:'plan',access:'full',model_ref:'provider/model'};

test('常见桌面宽度始终保留至少420px聊天，所有标签共用520px默认',()=>{
  for(const width of [1006,1166,1420]){
    const bounds=panelBounds(width,false);
    assert.equal(clampPanelWidth(DEFAULT_PANEL_WIDTH,bounds),520);
    assert.ok(width-clampPanelWidth(9999,bounds)>=420);
    assert.equal(clampPanelWidth(200,bounds),280);
  }
});
test('覆盖模式与极窄尺寸不溢出，未知宽度不产生NaN',()=>{
  assert.deepEqual(panelBounds(378,true),{min:280,max:378});
  assert.equal(clampPanelWidth(520,panelBounds(378,true)),378);
  assert.equal(clampPanelWidth(Number.NaN,panelBounds(200,true)),200);
  assert.equal(clampPanelWidth(520,panelBounds(Number.NaN,true)),0);
  assert.equal(PANEL_CLOSE_THRESHOLD,240);
});
test('草稿恢复仅接受有效草稿身份，不恢复正式聊天或损坏项',()=>{
  const restored=restoreDraftChats({one:{...draft,id:id.toUpperCase()},formal:{...draft,id:'a'.repeat(32),draft:false},bad:{...draft,id:'broken'}});
  assert.deepEqual(Object.keys(restored),[id]);
  assert.equal(restored[id].phase,'plan');assert.equal(restored[id].model_ref,'provider/model');
});
test('本地草稿元数据不复制聊天正文、队列或用量',()=>{
  const restored=restoreDraftChats({one:{...draft,messages:[{content:'私有内容'}],queue:[{text:'输入'}],usage:{input_tokens:42}}});
  assert.equal('messages' in restored[id],false);assert.equal('queue' in restored[id],false);assert.equal('usage' in restored[id],false);
});
test('重建保留同Web id与显式控制选项，不提交旧SDK会话ID或未知控制值',()=>{
  assert.deepEqual(draftCreatePayload({...draft,sdk_session_id:'old-sdk'}),{project_id:'project-a',draft_id:id,title:'草稿',model_ref:'provider/model',phase:'plan',access:'full'});
  const payload=draftCreatePayload({...draft,model_ref:'',phase:'unknown',access:'read_only'});
  assert.equal('phase' in payload,false);assert.equal('access' in payload,false);assert.equal('model_ref' in payload,false);
});

test('浏览器恢复不会沿用上次服务事件游标，保留草稿控制字段',()=>{
  const restored=restoreDraftChats({one:{...draft,_event_sequence:9000}});
  assert.equal(restored[id]._event_sequence,undefined);
  assert.equal(restored[id].phase,'plan');assert.equal(restored[id].access,'full');
});
