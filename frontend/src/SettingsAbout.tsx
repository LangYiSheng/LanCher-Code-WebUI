import {isDesktop} from './desktopHost';
import {Brand} from './Brand';
import './SettingsAbout.css';

// 内容来自构建所用的项目版本与固定 SDK 快照，不推测运行中的 Git 状态。
export function SettingsAbout(){
  const release=__LANCHER_RELEASE__;
  return <section className="settings-about" aria-label="发布版本与 SDK 来源">
    <div className="settings-about-brand"><Brand size={40}/><div><h2>LanCher Code {isDesktop()?'Desktop':'WebUI'}</h2><p>本机 AI 编程工作台</p></div></div>
    <dl className="settings-about-versions">
      <div><dt>WebUI 版本</dt><dd><strong>{release.webuiVersion}</strong><small>当前前端发布版本</small></dd></div>
      <div><dt>LanCher Code SDK</dt><dd><strong>{release.sdkVersion}</strong><small>固定 SDK 版本</small></dd></div>
      <div><dt>SDK 提交</dt><dd><code>{release.sdkCommit}</code><small>当前固定快照</small></dd></div>
    </dl>
    <p className="settings-about-note">{isDesktop()?'桌面预览：共用 WebUI 前端和 SDK，使用独立数据与用户配置目录。':'本机运行，与 LanCher Code 共用模型配置和项目会话。'}</p>
  </section>;
}
