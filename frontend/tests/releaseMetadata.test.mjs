import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {parseReleaseMetadata,readReleaseMetadata} from '../releaseMetadata.mjs';

const source='[project]\nname = "webui"\nversion = "0.2.0"\ndependencies = ["lancher-code==0.1.0"]\n\n[tool.example]\nversion = "99.0.0"\n';
const snapshot={wheel:'vendor/wheels/current/lancher_code-0.1.0-py3-none-any.whl',commit:'f3329bc9bcc8b2ef7afd08cc80d3c9f85bcfd61b'};

test('发布元数据读取真实项目与固定快照，前端清单版本保持一致',()=>{
  const metadata=readReleaseMetadata(fileURLToPath(new URL('../../',import.meta.url)));
  const manifest=JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8'));
  const lock=JSON.parse(readFileSync(new URL('../package-lock.json',import.meta.url),'utf8'));
  assert.equal(metadata.webuiVersion,manifest.version);
  assert.equal(metadata.webuiVersion,lock.version);
  assert.equal(metadata.webuiVersion,lock.packages[''].version);
  assert.equal(metadata.sdkVersion,'0.1.0');
  assert.match(metadata.sdkCommit,/^[a-f0-9]{40}$/);
});
test('关于版本只取 project 段，不误取工具版本或运行中的 Git 状态',()=>{
  assert.deepEqual(parseReleaseMetadata(source,snapshot),{webuiVersion:'0.2.0',sdkVersion:'0.1.0',sdkCommit:snapshot.commit});
});
test('来源缺失、依赖与 wheel 不一致或缩写提交时拒绝生成版本',()=>{
  assert.throws(()=>parseReleaseMetadata('[tool.example]\nversion="0.2.0"',snapshot),/project/);
  assert.throws(()=>parseReleaseMetadata(source,{...snapshot,wheel:'lancher_code-0.2.0-py3-none-any.whl'}),/不一致/);
  assert.throws(()=>parseReleaseMetadata(source,{...snapshot,commit:'f3329bc'}),/完整提交/);
});
