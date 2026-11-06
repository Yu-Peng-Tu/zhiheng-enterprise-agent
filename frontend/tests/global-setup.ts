import { spawn, type ChildProcess } from 'node:child_process';
import { rmSync } from 'node:fs';
import path from 'node:path';

function stop(server: ChildProcess) {
  if (server.exitCode !== null || server.signalCode) return;
  try { if (process.platform !== 'win32') process.kill(-server.pid!, 'SIGTERM'); else server.kill('SIGTERM'); } catch { /* already stopped */ }
}

export default async function globalSetup() {
  const root = path.resolve(process.cwd(), '..');
  rmSync(path.join(root, 'backend', 'data', 'e2e.db'), { force: true });
  const options = { detached: process.platform !== 'win32', stdio: 'inherit' as const };
  const backend = spawn(path.join(root, '.venv', 'bin', 'uvicorn'), ['app.main:app', '--host', '127.0.0.1', '--port', '8011'], {
    ...options, cwd: path.join(root, 'backend'),
    env: { ...process.env, PYTHONPATH: path.join(root, 'backend'), DATABASE_URL: 'sqlite:///data/e2e.db' },
  });
  const frontend = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '7111'], {
    ...options, cwd: path.join(root, 'frontend'), env: { ...process.env, VITE_API_TARGET: 'http://127.0.0.1:8011' },
  });
  const cleanup = async () => {
    stop(backend); stop(frontend);
    await new Promise(resolve => setTimeout(resolve, 500));
  };
  let lastError: unknown;
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const response = await fetch('http://127.0.0.1:8011/api/health');
      if (response.ok) return cleanup;
    } catch (error) { lastError = error; }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  await cleanup();
  throw new Error(`验收服务未能启动：${String(lastError)}`);
}
