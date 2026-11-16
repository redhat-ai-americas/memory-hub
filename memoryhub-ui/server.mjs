import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, resolve, sep } from 'node:path';

const root = resolve('dist');
const port = Number(process.env.PORT || 8080);
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.json': 'application/json; charset=utf-8' };
const security = {
  'Content-Security-Policy': "default-src 'self' data:; connect-src 'none'; img-src 'self' data:; font-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'",
  'X-Content-Type-Options': 'nosniff',
};

createServer(async (req, res) => {
  if (req.url === '/healthz') { res.writeHead(200, { ...security, 'Content-Type': 'text/plain' }); res.end('ok'); return; }
  if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405, security); res.end(); return; }
  let pathname;
  try { pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname); } catch { res.writeHead(400, security); res.end(); return; }
  const candidate = resolve(join(root, pathname.replace(/^\/+/, '')));
  if (candidate !== root && !candidate.startsWith(root + sep)) { res.writeHead(403, security); res.end(); return; }
  let file = candidate;
  try { if (!(await stat(file)).isFile()) file = join(root, 'index.html'); } catch { file = join(root, 'index.html'); }
  try {
    const content = await readFile(file);
    res.writeHead(200, { ...security, 'Content-Type': mime[extname(file)] || 'application/octet-stream', 'Cache-Control': file.endsWith('index.html') ? 'no-cache' : 'public, max-age=31536000, immutable' });
    res.end(req.method === 'HEAD' ? undefined : content);
  } catch { res.writeHead(404, security); res.end(); }
}).listen(port, '0.0.0.0');
