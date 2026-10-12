/// <reference types="vite/client" />

// Vite 从 pyproject.toml 与 vendor/snapshot.json 注入本次前端发布信息。
declare const __LANCHER_RELEASE__:Readonly<{webuiVersion:string;sdkVersion:string;sdkCommit:string}>;
