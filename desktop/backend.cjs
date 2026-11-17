const {spawn} = require('node:child_process');
const {existsSync, mkdirSync, appendFileSync} = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

function backendCommand({packaged, resourcesPath, projectRoot, platform = process.platform, python = process.env.NOTES_PYTHON}) {
  if (packaged) return [path.join(resourcesPath, 'backend', platform === 'win32' ? 'notes-backend.exe' : 'notes-backend'), 'server', '--port', '0'];
  const local = path.join(projectRoot, '.venv-web', platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  return [python || (existsSync(local) ? local : platform === 'win32' ? 'python' : 'python3'), path.join(projectRoot, 'desktop_backend.py'), 'server', '--port', '0'];
}
function isAppUrl(value, origin) {
  try { const url = new URL(value); return url.origin === origin && url.username === '' && url.password === ''; } catch { return false; }
}
function startBackend(options) {
  const {dataDir, token, nodePath, onExit = () => {}} = options;
  mkdirSync(dataDir, {recursive: true});
  const log = path.join(dataDir, 'backend.log');
  const [command, ...args] = backendCommand(options);
  const child = spawn(command, args, {cwd: dataDir, windowsHide: true, detached: process.platform !== 'win32',
    env: {...process.env, NOTES_DATA_DIR: dataDir, NOTES_DESKTOP: '1', NOTES_AUTH_TOKEN: token,
      NODE_PATH_EXECUTABLE: nodePath, ELECTRON_RUN_AS_NODE: '1', PYTHONUNBUFFERED: '1'}});
  let stopping = false, ready = false, stopPromise;
  const lines = readline.createInterface({input: child.stdout});
  child.stderr.on('data', chunk => appendFileSync(log, chunk));
  const started = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {reject(new Error('처리 엔진 시작 시간이 초과되었습니다.')); stop();}, 45000);
    child.once('error', error => {clearTimeout(timeout); reject(error);});
    child.once('exit', (code, signal) => {
      clearTimeout(timeout);
      if (!ready) reject(new Error(`처리 엔진이 종료되었습니다 (${code ?? signal}). 로그: ${log}`));
      else if (!stopping) onExit(code, signal);
    });
    lines.on('line', line => {
      appendFileSync(log, line + '\n');
      if (!line.startsWith('NOTES_READY=')) return;
      try {
        const {port} = JSON.parse(line.slice('NOTES_READY='.length));
        if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('잘못된 처리 엔진 포트');
        ready = true; clearTimeout(timeout); resolve(`http://127.0.0.1:${port}`);
      } catch (error) {clearTimeout(timeout); reject(error); stop();}
    });
  });
  function stop() {
    if (stopPromise) return stopPromise;
    stopping = true;
    stopPromise = new Promise(resolve => {
      if (!child.pid || child.exitCode !== null || child.signalCode) {resolve(); return;}
      let timeout;
      child.once('exit', () => {clearTimeout(timeout); resolve();});
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {windowsHide: true}).on('error', () => child.kill());
      } else {
        try {process.kill(-child.pid, 'SIGTERM');} catch {resolve(); return;}
      }
      timeout = setTimeout(() => {
        if (process.platform !== 'win32') {try {process.kill(-child.pid, 'SIGKILL');} catch {}}
        resolve();
      }, 3000);
    });
    return stopPromise;
  }
  return {started, stop, child};
}
module.exports = {backendCommand, isAppUrl, startBackend};
