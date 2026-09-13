const MODAL_HEADER_KEY = 'Modal-Key';
const MODAL_HEADER_SECRET = 'Modal-Secret';

function fail(body, status = 503) {
  return Response.json(body, { status, headers: { 'cache-control': 'no-store' } });
}

export default {
  async fetch(request, env) {
    if (!env.MODAL_BASE_URL || !env.MODAL_PROXY_KEY || !env.MODAL_PROXY_SECRET) {
      return fail({ ok: false, error: 'NEXUS_MODAL_ADAPTER_NOT_CONFIGURED' });
    }
    const incoming = new URL(request.url);
    const base = new URL(env.MODAL_BASE_URL);
    const target = new URL(incoming.pathname + incoming.search, base);
    const headers = new Headers(request.headers);
    for (const name of ['host', 'content-length', 'transfer-encoding', 'connection', 'modal-key', 'modal-secret']) headers.delete(name);
    headers.set(MODAL_HEADER_KEY, env.MODAL_PROXY_KEY);
    headers.set(MODAL_HEADER_SECRET, env.MODAL_PROXY_SECRET);
    headers.set('x-forwarded-host', incoming.host);
    headers.set('x-forwarded-proto', 'https');
    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      const body = await request.arrayBuffer();
      if (body.byteLength) init.body = body;
    }
    try {
      const response = await fetch(target.toString(), init);
      const out = new Response(response.body, response);
      out.headers.set('x-mft-runtime', 'cloudflare-modal-neon');
      return out;
    } catch (_) {
      return fail({ ok: false, error: 'NEXUS_MODAL_UPSTREAM_UNREACHABLE' }, 502);
    }
  },
};
