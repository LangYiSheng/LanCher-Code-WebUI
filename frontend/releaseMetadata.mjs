import {readFileSync} from 'node:fs';
import {join} from 'node:path';

// 构建元数据只来自版本文件与固定 SDK 快照，读取失败时拒绝生成误导版本。
export function parseReleaseMetadata(pyproject,snapshot){
  const marker=/^\[project\][ \t]*\r?$/m.exec(pyproject);
  if(!marker)throw new Error('缺少 pyproject.toml 的 project 段。');
  const project=pyproject.slice(marker.index+marker[0].length).split(/^\[/m,1)[0];
  const webuiVersion=/^version[ \t]*=[ \t]*["']([^"']+)["'][ \t]*\r?$/m.exec(project)?.[1];
  const sdkVersion=/lancher_code-([^-]+)-[^/]+\.whl$/.exec(snapshot.wheel||'')?.[1];
  const sdkDependency=/["']lancher-code==([^"']+)["']/.exec(project)?.[1];
  const validVersion=value=>typeof value==='string'&&/^\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)$/.test(value);
  if(!validVersion(webuiVersion))throw new Error('WebUI 发布版本无效。');
  if(!validVersion(sdkVersion)||sdkDependency!==sdkVersion)throw new Error('固定 SDK wheel 与项目依赖版本不一致。');
  if(typeof snapshot.commit!=='string'||!/^[a-f0-9]{40}$/i.test(snapshot.commit))throw new Error('固定 SDK commit 必须是完整提交值。');
  return Object.freeze({webuiVersion,sdkVersion,sdkCommit:snapshot.commit.toLowerCase()});
}

export function readReleaseMetadata(projectRoot){
  return parseReleaseMetadata(readFileSync(join(projectRoot,'pyproject.toml'),'utf8'),JSON.parse(readFileSync(join(projectRoot,'vendor','snapshot.json'),'utf8')));
}
