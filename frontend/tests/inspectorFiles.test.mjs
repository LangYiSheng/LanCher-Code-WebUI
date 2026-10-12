import test from 'node:test';
import assert from 'node:assert/strict';
import {fileScopeKey,fileListUrl,filePreviewUrl,fileEntries,fileTree,parentDirectories,restoreInspectorView} from '../src/inspectorFiles.ts';

test('项目文件浏览使用项目作用域，不混入任何对话基线',()=>{
  const list=new URL(fileListUrl('files','project-a','chat-a','目录/文件'), 'http://local');
  assert.equal(list.pathname,'/api/projects/project-a/files');
  assert.equal(list.searchParams.get('scope'),'files');
  assert.equal(list.searchParams.get('q'),'目录/文件');
  assert.equal(list.searchParams.has('chat_id'),false);
  assert.equal(filePreviewUrl('files','project-a','chat-a','dir/a.txt'),'/api/projects/project-a/file?path=dir%2Fa.txt');
  assert.equal(filePreviewUrl('files','project-a',undefined,'dir/a.txt'),'/api/projects/project-a/file?path=dir%2Fa.txt');
});
test('对话变更明确请求净变更，未选择对话不能误用项目源码接口',()=>{
  const list=new URL(fileListUrl('changes','project-a','chat-b',''), 'http://local');
  assert.equal(list.searchParams.get('scope'),'changes');
  assert.equal(list.searchParams.get('chat_id'),'chat-b');
  assert.equal(filePreviewUrl('changes','project-a','chat-b','deleted.txt'),'/api/chats/chat-b/file?path=deleted.txt');
  assert.equal(fileListUrl('changes','project-a',undefined,''),'');
  assert.equal(filePreviewUrl('changes','project-a',undefined,'a.txt'),'');
});
test('修改后恢复原样的文件不出现在变更列表，已删除文件仍可选取差异',()=>{
  const rows=[{path:'added.txt',status:'added'},{path:'modified.txt',status:'modified'},
    {path:'removed.txt',status:'deleted'},{path:'restored.txt',status:'unchanged'},{path:'untouched.txt'}];
  assert.deepEqual(fileEntries('changes',rows).map(row=>row.path),['added.txt','modified.txt','removed.txt']);
  assert.deepEqual(fileEntries('files',rows).map(row=>row.path),['added.txt','modified.txt','restored.txt','untouched.txt']);
});
test('两个标签和不同项目对话有独立选择键，同项目源码可沿用',()=>{
  assert.notEqual(fileScopeKey('changes','project-a','chat-a'),fileScopeKey('changes','project-a','chat-b'));
  assert.notEqual(fileScopeKey('changes','project-a','chat-a'),fileScopeKey('files','project-a','chat-a'));
  assert.notEqual(fileScopeKey('files','project-a'),fileScopeKey('files','project-b'));
  assert.equal(fileScopeKey('files','project-a','chat-a'),fileScopeKey('files','project-a','chat-b'));
});
test('目录树保留真实文件层级且目录排在文件之前',()=>{
  const tree=fileTree([{path:'z.txt'},{path:'src/nested/b.ts',status:'modified'},{path:'src/a.ts'},{path:'a.txt'}]);
  assert.deepEqual(tree.map(node=>node.name),['src','a.txt','z.txt']);
  assert.deepEqual(tree[0].children.map(node=>node.name),['nested','a.ts']);
  assert.equal(tree[0].children[0].children[0].file.status,'modified');
  assert.deepEqual(parentDirectories('src/nested/b.ts'),['src','src/nested']);
});
test('浏览器标签恢复旧选项，过滤未知类型，保留每chat独立树与选择',()=>{
  assert.deepEqual(restoreInspectorView(null).tabs,[]);
  assert.equal(restoreInspectorView(null).newTab,true);
  const old=restoreInspectorView(null,'changes','src/a.ts');
  assert.deepEqual(old.tabs,['changes']);
  assert.equal(old.active,'changes');
  assert.equal(old.files.path,'src/a.ts');
  const restored=restoreInspectorView({tabs:['files','processes','files','unknown'],active:'processes',
    files:{path:'src/a.ts',query:'src',collapsed:['src',42]},changes:{path:'gone.txt',query:'',collapsed:[]}});
  assert.deepEqual(restored.tabs,['files','processes']);
  assert.equal(restored.active,'processes');
  assert.deepEqual(restored.files.collapsed,['src']);
  assert.equal(restored.changes.path,'gone.txt');
  assert.deepEqual(restoreInspectorView({tabs:[],active:'files'}).tabs,[]);
  assert.equal(restoreInspectorView({tabs:[],active:'files',newTab:false}).newTab,true);
  const previous=restoreInspectorView({tabs:['files','activity'],active:'activity'});
  assert.deepEqual(previous.tabs,['files','activity']);
  assert.equal(previous.newTab,false);
});