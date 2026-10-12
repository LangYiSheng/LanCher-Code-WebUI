import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
import {readReleaseMetadata} from './releaseMetadata.mjs';
const release=readReleaseMetadata(fileURLToPath(new URL('../',import.meta.url)));
export default defineConfig({plugins:[react()], define:{__LANCHER_RELEASE__:JSON.stringify(release)}, base:'/', server:{host:'127.0.0.1',port:5173,proxy:{'/api':{target:'http://127.0.0.1:8765',changeOrigin:false}}}, build:{outDir:'dist',emptyOutDir:true}});
