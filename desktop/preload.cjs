'use strict';
const {contextBridge, ipcRenderer} = require('electron');
// The demonstration page receives no native API. No generic invoke/send is exposed.
if (location.href.split('#')[0] === 'daf://app/planning.html') {
  contextBridge.exposeInMainWorld('dafPlanning', Object.freeze({
    importPublicPlan: source => ipcRenderer.invoke('planning:import', source),
    listImports: () => ipcRenderer.invoke('planning:list'),
    getImport: id => ipcRenderer.invoke('planning:get', id),
    cancelImport: () => ipcRenderer.invoke('planning:cancel'),
  }));
}
