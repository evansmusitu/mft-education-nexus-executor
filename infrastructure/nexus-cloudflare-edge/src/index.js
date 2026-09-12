const REPO = 'evansmusitu/mft-education-nexus-executor';
const WORKFLOW = 'mft-nexus-modal-runtime-preadmission-v1.yml';
const REF = 'main';

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

async function digest(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
}

async function secretEqual(a, b) {
  if (!a || !b) return false;
  const [da, db] = await Promise.all([digest(a), digest(b)]);
  if (da.length !== db.length) return false;
  let diff = 0;
  for (let i = 0; i < da.length; i++) diff |= da[i] ^ db[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'GET' && url.pathname === '/health') {
      return json({
        schema: 'mft.education_nexus.infrastructure.cloudflare_edge_health.v1',
        service: 'mft-education-nexus-edge',
        scope: 'EDUCATION_NEXUS_ONLY',
        github_repository: REPO,
        github_workflow: WORKFLOW,
        modal_plane: 'mft-education-nexus-build-plane',
        phase1_frontier: '112/114',
        official_phase2_credit: 0,
        phase2_started: false,
        authority_role: false,
        authority_modified: false,
        axiom_dependency: false,
      });
    }

    if (request.method !== 'POST' || url.pathname !== '/v1/preadmission/build') {
      return json({ error: 'not_found' }, 404);
    }

    if (!env.NEXUS_EDGE_SHARED_SECRET || !env.GITHUB_DISPATCH_TOKEN) {
      return json({ error: 'provider_secrets_not_configured', fail_closed: true }, 503);
    }

    const auth = request.headers.get('authorization') || '';
    const expected = `Bearer ${env.NEXUS_EDGE_SHARED_SECRET}`;
    if (!(await secretEqual(auth, expected))) {
      return json({ error: 'unauthorized' }, 401);
    }

    const response = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: 'POST',
        headers: {
          authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
          accept: 'application/vnd.github+json',
          'x-github-api-version': '2022-11-28',
          'user-agent': 'MFT-Education-Nexus-Cloudflare-Edge',
        },
        body: JSON.stringify({ ref: REF }),
      },
    );

    if (response.status !== 204) {
      const detail = (await response.text()).slice(0, 2000);
      return json({ error: 'github_dispatch_failed', status: response.status, detail, fail_closed: true }, 502);
    }

    return json({
      accepted: true,
      mode: 'PRE_ADMISSION_ENGINEERING_ONLY',
      workflow: WORKFLOW,
      ref: REF,
      official_phase2_credit: 0,
      phase2_started: false,
      authority_modified: false,
      axiom_dependency: false,
    }, 202);
  },
};
