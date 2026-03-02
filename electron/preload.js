/**
 * Velluma AI - Electron 预加载脚本
 * 提供安全的 IPC 通信桥接
 */

const { contextBridge, ipcRenderer } = require('electron');

// 暴露安全的 API 给渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
  // 平台信息
  platform: process.platform,
  
  // 版本信息
  versions: {
    node: process.versions.node,
    electron: process.versions.electron,
    chrome: process.versions.chrome
  },
  
  // 是否是开发模式
  isDev: !process.env.NODE_ENV || process.env.NODE_ENV === 'development'
});

console.log('[Preload] Electron API 已注入');
