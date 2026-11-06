import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const apiPort = process.env.API_PORT || '8017';
const pythonBin = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'uvicorn.exe' : 'uvicorn');
if (!existsSync(pythonBin)) {
  console.error('未找到后端虚拟环境，请先按 README 创建 .venv 并安装依赖。');
  process.exit(1);
}
if (!existsSync(path.join(root, 'frontend', 'node_modules'))) {
  console.error('未找到前端依赖，请先执行 npm install --prefix frontend。');
  process.exit(1);
}
const children = [];
function launch(command, args, cwd) {
  const child = spawn(command, args, { cwd, stdio: 'inherit', env: { ...process.env, PYTHONPATH: path.join(root, 'backend') }, detached: process.platform !== 'win32' });
  children.push(child);
  child.on('exit', code => { if (!stopping && code) { console.error(`服务异常退出（${code}），正在停止其他服务…`); stop(code); } });
  return child;
}
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null || child.signalCode) continue;
    try { if (process.platform !== 'win32') process.kill(-child.pid, 'SIGTERM'); else child.kill('SIGTERM'); } catch { child.kill('SIGTERM'); }
  }
  setTimeout(() => process.exit(code), 400);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
process.env.VITE_API_TARGET = `http://127.0.0.1:${apiPort}`;
launch(pythonBin, ['app.main:app', '--host', '127.0.0.1', '--port', apiPort], path.join(root, 'backend'));
launch(npm, ['run', 'dev', '--', ...process.argv.slice(2)], path.join(root, 'frontend'));
console.log(`知衡正在启动：前端默认 http://localhost:5173，后端 http://127.0.0.1:${apiPort}`);
