const { contextBridge, ipcRenderer } = require('electron')

// 具名 + 白名单：只暴露完成通知这一个能力（原泛型 send/on 无白名单是安全松散点）
contextBridge.exposeInMainWorld('electronAPI', {
  showCompletionNotification: (payload) => ipcRenderer.send('show-notification', payload)
})
