import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Dev-server configuration, driven by `frontend/.env` (see .env.example).
 *
 * loadEnv's third argument is the prefix filter. It is deliberately '' rather
 * than the default 'VITE_': these values configure the dev server in Node, they
 * are NOT injected into client code, so they must not carry the VITE_ prefix —
 * that prefix is what marks a variable as safe to ship to the browser.
 *
 * Every value falls back to what was previously hardcoded here, so an absent
 * .env leaves behaviour unchanged.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  const backendUrl = env.PIXOVO_BACKEND_URL || 'http://localhost:8000';
  const devPort = Number(env.PIXOVO_DEV_PORT) || 5173;

  // Comma-separated, so a rotating tunnel hostname is a .env edit rather than
  // a code change. The ngrok wildcards stay in the defaults because a free
  // ngrok subdomain changes on every restart.
  const splitList = (value, fallback) => {
    const items = (value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    return items.length ? items : fallback;
  };

  const allowedHosts = splitList(env.PIXOVO_DEV_ALLOWED_HOSTS, [
    'doorpost-smashing-regime.ngrok-free.dev',
    '.ngrok-free.dev',
    '.ngrok.io',
    'localhost',
  ]);

  // Hosts `vite preview` will answer to in production. Preview applies the same
  // Host-header check as the dev server, so without the deployed domain here it
  // rejects every proxied request with "Blocked request".
  const previewHosts = splitList(env.PIXOVO_PREVIEW_ALLOWED_HOSTS, [
    'storymode.pixovo.com',
    'localhost',
    '127.0.0.1',
  ]);

  const corsOrigins = splitList(env.PIXOVO_DEV_CORS_ORIGINS, [
    'https://doorpost-smashing-regime.ngrok-free.dev',
    `http://localhost:${devPort}`,
    `http://127.0.0.1:${devPort}`,
  ]);

  // The app itself calls the API with RELATIVE paths ('/api/...'), which this
  // proxy resolves in development. A production build has no proxy, so the
  // built assets must be served from the same origin as the API (or behind a
  // reverse proxy that maps /api, /uploads and /exports to the backend).
  const proxyTarget = { target: backendUrl, changeOrigin: true };

  return {
    plugins: [react()],
    server: {
      port: devPort,
      host: true,
      allowedHosts,
      cors: {
        origin: corsOrigins,
        credentials: true,
      },
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
        'Access-Control-Allow-Headers':
          'X-Requested-With, content-type, Authorization, ngrok-skip-browser-warning',
      },
      proxy: {
        '/api': proxyTarget,
        '/uploads': proxyTarget,
        '/exports': proxyTarget,
      },
    },
    // `vite preview` serves the built dist/ in production. It deliberately has
    // no proxy block: the reverse proxy in front owns the routing of /api,
    // /uploads and /exports, so preview only ever serves static assets. Bound
    // to loopback because nothing should reach it except that proxy.
    preview: {
      port: Number(env.PIXOVO_PREVIEW_PORT) || 4173,
      host: env.PIXOVO_PREVIEW_HOST || '127.0.0.1',
      allowedHosts: previewHosts,
    },
  };
});
