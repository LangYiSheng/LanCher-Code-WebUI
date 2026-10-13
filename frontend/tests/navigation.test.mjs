import test from 'node:test';
import assert from 'node:assert/strict';
import {visitLocation,moveLocation} from '../src/navigation.ts';
const page=(project,chat=null,settings=false,section='appearance')=>({project,chat,settings,section});
test('后退再访问新页面会丢弃前进分支且不修改原历史',()=>{const a=visitLocation({entries:[],index:-1},page('a'));const b=visitLocation(a,page('b'));const back=moveLocation(b,-1);const c=visitLocation(back,page('c'));assert.deepEqual(c.entries.map(x=>x.project),['a','c']);assert.deepEqual(b.entries.map(x=>x.project),['a','b']);});
test('相同工作台位置不会重复登记，聊天与设置可来回导航',()=>{let state=visitLocation({entries:[],index:-1},page('p','chat'));assert.equal(visitLocation(state,page('p','chat')),state);state=visitLocation(state,page('p','chat',true,'about'));assert.equal(moveLocation(state,-1).entries[0].chat,'chat');assert.equal(moveLocation(state,1),state);});
test('导航保留完整身份与设置入口，并限制历史长度',()=>{let state={entries:[],index:-1};for(let i=0;i<110;i++)state=visitLocation(state,page('p',String(i),true,'storage'));assert.equal(state.entries.length,100);assert.equal(state.entries[0].chat,'10');assert.equal(state.entries[99].section,'storage');assert.equal(moveLocation(state,-100),state);});
