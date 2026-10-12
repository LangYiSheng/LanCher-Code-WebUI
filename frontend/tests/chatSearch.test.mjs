import test from 'node:test';
import assert from 'node:assert/strict';
import {searchChats,visibleChats} from '../src/chatSearch.ts';

const projects=[
  {id:'p-a',name:'项目甲',path:String.raw`D:\Dev\TodoLab`,available:true},
  {id:'p-b',name:'项目乙',path:String.raw`D:\Dev\BackendLab`,available:true},
];
const chat=(id,overrides={})=>({id,project_id:'p-a',title:'待办 API 后端',status:'completed',phase:'execute',access:'project',model_ref:'provider/deepseek',...overrides});
const ids=rows=>rows.map(row=>row.id);

test('聊天搜索排除归档、草稿和未登记项目，侧栏可见规则不混入项目查找',()=>{
  const rows=[chat('formal'),chat('archived',{archived:true}),chat('draft',{draft:true}),chat('orphan',{project_id:'removed'})];
  assert.deepEqual(ids(searchChats(rows,projects,'待办')),['formal']);
  assert.deepEqual(ids(searchChats(rows,projects,'   ')),['formal']);
  assert.deepEqual(ids(visibleChats(rows)),['formal','orphan']);
  assert.deepEqual(searchChats(rows,[],'待办'),[]);
});

test('中文与全角搜索按规范化、大小写和多类空白匹配真实标题',()=>{
  const rows=[chat('todo'),chat('other',{title:'用户 API 登录'})];
  assert.deepEqual(ids(searchChats(rows,projects,'\t待办　ＡＰＩ\n')),['todo']);
  assert.deepEqual(ids(searchChats(rows,projects,'api 后端')),['todo']);
  assert.deepEqual(ids(searchChats(rows,projects,'待办 登录')),[]);
});

test('多词可跨项目、标题与模型字段匹配，但每个词都必须命中',()=>{
  const rows=[chat('a'),chat('b',{project_id:'p-b',title:'登录后端',model_ref:'provider/claude'})];
  assert.deepEqual(ids(searchChats(rows,projects,'项目乙 CLAUDE 登录')),['b']);
  assert.deepEqual(ids(searchChats(rows,projects,'登录 项目乙')),['b']);
  assert.deepEqual(ids(searchChats(rows,projects,'项目甲 claude')),[]);
  assert.deepEqual(ids(searchChats(rows,projects,'项目乙 待办')),[]);
});

test('路径、Web身份和原生SDK身份均可定位对应聊天而不借用其他聊天字段',()=>{
  const rows=[chat('web-alpha',{sdk_session_id:'native-uuid-one'}),chat('web-beta',{project_id:'p-b',sdk_session_id:'native-uuid-two'})];
  for(const query of ['todolab','WEB-ALPHA','native-uuid-one'])assert.deepEqual(ids(searchChats(rows,projects,query)),['web-alpha']);
  assert.deepEqual(ids(searchChats(rows,projects,'backendlab native-uuid-two')),['web-beta']);
  assert.deepEqual(ids(searchChats(rows,projects,'web-alpha native-uuid-two')),[]);
});

test('置顶、更新时间和平局身份排序确定，搜索与侧栏都不修改输入',()=>{
  const rows=[
    chat('z',{updated_at:'2026-10-12T08:00:00Z'}),
    chat('pin-old',{pinned:true,updated_at:'2026-10-11T08:00:00Z'}),
    chat('a',{updated_at:'2026-10-12T08:00:00Z'}),
    chat('pin-new',{pinned:true,updated_at:'2026-10-12T08:00:00Z'}),
    chat('no-time'),
  ];
  const before=structuredClone(rows);const projectBefore=structuredClone(projects);
  rows.forEach(Object.freeze);Object.freeze(rows);
  const frozenProjects=Object.freeze(projects.map(item=>Object.freeze({...item})));
  const expected=['pin-new','pin-old','a','z','no-time'];
  assert.deepEqual(ids(searchChats(rows,frozenProjects,'')),expected);
  assert.deepEqual(ids(searchChats([...rows].reverse(),frozenProjects,'API')),expected);
  assert.deepEqual(ids(visibleChats(rows)),expected);
  assert.deepEqual(rows,before);assert.deepEqual(projects,projectBefore);
});
