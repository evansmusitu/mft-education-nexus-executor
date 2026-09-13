function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2) + '\n', {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
    },
  });
}

function configured(env) {
  return Boolean(env.MFT_MODAL_ORIGIN && env.MFT_EDGE_ORIGIN_SECRET);
}

async function originFetch(request, env) {
  const incoming = new URL(request.url);
  const origin = new URL(env.MFT_MODAL_ORIGIN);
  const target = new URL(incoming.pathname + incoming.search, origin);
  const headers = new Headers(request.headers);
  headers.delete('x-mft-origin-secret');
  headers.set('x-mft-origin-secret', env.MFT_EDGE_ORIGIN_SECRET);
  headers.set('x-forwarded-host', incoming.host);
  const init = {
    method: request.method,
    headers,
    redirect: 'manual',
  };
  if (!['GET', 'HEAD'].includes(request.method)) init.body = request.body;
  return fetch(target, init);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!configured(env)) {
      return json({ error: 'origin_not_configured', fail_closed: true }, 503);
    }

    if (request.method === 'GET' && url.pathname === '/_edge/health') {
      const response = await originFetch(new Request(new URL('/_mft/runtime/health', request.url), request), env);
      const detail = await response.text();
      if (!response.ok) {
        return json({ error: 'modal_origin_unhealthy', status: response.status, fail_closed: true }, 502);
      }
      let originHealth;
      try { originHealth = JSON.parse(detail); } catch { return json({ error: 'modal_origin_invalid_health', fail_closed: true }, 502); }
      return json({
        status: 'ok',
        service: 'mft-product-frontier-edge',
        topology: 'github->modal-stateful-runtime->cloudflare-edge',
        origin: originHealth,
        promotion_effect: 'NONE',
      });
    }

    const response = await originFetch(request, env);
    const headers = new Headers(response.headers);
    headers.set('cache-control', 'no-store');
    headers.set('x-content-type-options', 'nosniff');
    headers.set('referrer-policy', 'same-origin');
    headers.delete('server');
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },
};
