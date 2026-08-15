// Safe bridge: expose only the backend base URL to the renderer.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ece", {
  backendPort: () => ipcRenderer.invoke("backend-port"),
  baseUrl: async () => `http://127.0.0.1:${await ipcRenderer.invoke("backend-port")}`,
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
});
