const {app, BrowserWindow, Menu, dialog, shell, session} = require('electron');
const {randomBytes} = require('node:crypto');
const path = require('node:path');
const {mkdirSync} = require('node:fs');
const {startBackend, isAppUrl} = require('./backend.cjs');

let backend, window, quitting = false, origin;
const smoke = process.argv.includes('--smoke-test');
app.setName('Notes');
if (process.env.NOTES_DATA_DIR) {
  mkdirSync(process.env.NOTES_DATA_DIR, {recursive: true});
  app.setPath('userData', process.env.NOTES_DATA_DIR);
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => {if (window) {if (window.isMinimized()) window.restore(); window.show(); window.focus();}});
  app.on('before-quit', event => {
    if (quitting || !backend) return;
    event.preventDefault(); quitting = true;
    backend.stop().finally(() => app.quit());
  });
  app.on('window-all-closed', () => app.quit());
  app.whenReady().then(async () => {
    const dataDir = process.env.NOTES_DATA_DIR || app.getPath('userData');
    const token = randomBytes(32).toString('hex');
    backend = startBackend({packaged: app.isPackaged, resourcesPath: process.resourcesPath,
      projectRoot: path.resolve(__dirname, '..'), dataDir, token, nodePath: process.execPath,
      onExit: () => {if (!quitting) {dialog.showErrorBox('Notes', '처리 엔진이 종료되었습니다. 앱을 다시 실행해 주세요.'); app.quit();}}});
    origin = await backend.started;
    session.defaultSession.webRequest.onBeforeSendHeaders({urls: [`${origin}/*`]}, (details, callback) => {
      details.requestHeaders['X-Notes-Token'] = token;
      callback({requestHeaders: details.requestHeaders});
    });
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    window = new BrowserWindow({width: 1400, height: 940, minWidth: 760, minHeight: 560, show: !smoke,
      title: 'Notes', backgroundColor: '#f8fafc', webPreferences: {contextIsolation: true, nodeIntegration: false, sandbox: true}});
    window.webContents.setWindowOpenHandler(({url}) => {
      if (/^https?:\/\//.test(url) && !isAppUrl(url, origin)) shell.openExternal(url);
      return {action: 'deny'};
    });
    window.webContents.on('will-navigate', (event, url) => {
      if (!isAppUrl(url, origin)) {event.preventDefault(); if (/^https?:\/\//.test(url)) shell.openExternal(url);}
    });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      ...(process.platform === 'darwin' ? [{label: 'Notes', submenu: [{role: 'about'}, {type: 'separator'}, {role: 'quit'}]}] : []),
      {label: '파일', submenu: [
        {label: 'AI 설정', accelerator: 'CmdOrCtrl+,', click: () => window.webContents.executeJavaScript('document.querySelector("#open-ai-settings")?.click()')},
        {label: '데이터 폴더 열기', click: () => shell.openPath(path.join(dataDir, 'workspace'))},
        ...(process.platform === 'win32' ? [{role: 'quit'}] : [])]},
      {label: '편집', submenu: [{role: 'undo'}, {role: 'redo'}, {type: 'separator'}, {role: 'cut'}, {role: 'copy'}, {role: 'paste'}, {role: 'selectAll'}]},
      {label: '보기', submenu: [{role: 'reload'}, {role: 'togglefullscreen'}]},
      {label: '도움말', submenu: [
        {label: '사용 안내', click: () => shell.openExternal('https://github.com/Sleepingoff/Notes#readme')},
        {label: '최신 릴리즈', click: () => shell.openExternal('https://github.com/Sleepingoff/Notes/releases')}]}]));
    await window.loadURL(origin);
    if (smoke) {
      const result = await window.webContents.executeJavaScript(`(async () => {
        const limit=Date.now()+10000;
        while(!document.querySelector('#open-ai-settings') && Date.now()<limit) await new Promise(r=>setTimeout(r,50));
        const response=await fetch('/api/settings/ai');
        return {settings:response.ok,sidebar:!!document.querySelector('#open-ai-settings'),title:document.title};
      })()`);
      if (!result.settings || !result.sidebar || result.title !== 'Notes') throw new Error(`화면 검사 실패: ${JSON.stringify(result)}`);
      console.log('NOTES_DESKTOP_SMOKE_OK');
      app.quit();
    }
  }).catch(async error => {
    console.error(error.message);
    if (!smoke) dialog.showErrorBox('Notes를 시작하지 못했습니다', error.message);
    await backend?.stop();
    quitting = true; app.exit(1);
  });
}
