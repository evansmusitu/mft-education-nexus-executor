from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ['QUALIFICATION_BASE_URL'].rstrip('/')
PASSWORD = os.environ['MFT_QA_PASSWORD']
ORIGIN_SECRET = os.environ.get('MFT_ORIGIN_SECRET', '')
INSTITUTION = 'qualification-inst-1'


def request(method: str, path: str, *, token: str | None = None, payload=None, expected=None):
    headers = {'accept': 'application/json'}
    if ORIGIN_SECRET:
        headers['x-mft-origin-secret'] = ORIGIN_SECRET
    if token:
        headers['authorization'] = f'Bearer {token}'
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        headers['content-type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            status = response.status
            ctype = response.headers.get('content-type', '')
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        ctype = exc.headers.get('content-type', '')
    if expected is not None and status != expected:
        raise AssertionError(f'{method} {path}: expected {expected}, got {status}: {raw[:500]!r}')
    if 'application/json' in ctype:
        return status, json.loads(raw or b'{}')
    return status, raw.decode('utf-8', 'replace')


def login(username: str) -> str:
    status, body = request('POST', '/v2/auth/login', payload={
        'institution_id': INSTITUTION,
        'username': username,
        'password': PASSWORD,
    }, expected=200)
    token = body.get('session_token')
    if not token:
        raise AssertionError(f'login token missing for {username}')
    return token


def learner_mastery(token: str) -> float:
    _, body = request('GET', '/v2/workspace', token=token, expected=200)
    learner = body.get('learner') or {}
    return float(learner['mastery'])


def phase_pre(state_path: Path, evidence_path: Path) -> None:
    checks = []
    _, html = request('GET', '/', expected=200)
    checks.append(('ui_served', 'Mission Control' in html and 'Tomorrow' in html))
    _, health = request('GET', '/v2/health', expected=200)
    checks.append(('runtime_health', health.get('status') == 'ok'))

    head = login('head')
    head2 = login('head2')
    learner = login('learner')
    _, me = request('GET', '/v2/me', token=head, expected=200)
    checks.append(('server_identity_headmaster', me.get('role') == 'HEADMASTER'))
    _, tomorrow = request('GET', '/v2/tomorrow', token=head, expected=200)
    checks.append(('predicted_not_observed', tomorrow.get('state_kind') == 'PREDICTED'))
    _, simulation = request('POST', '/v2/tomorrow/simulate', token=head, payload={
        'type': 'learning_intervention', 'learner_id': 'L1'
    }, expected=200)
    checks.append(('simulation_is_counterfactual', simulation.get('state_kind') == 'COUNTERFACTUAL_PREDICTION'))

    _, proposal = request('POST', '/v2/decisions/proposals', token=head, payload={
        'risk_level': 'HIGH',
        'action_type': 'entity_patch',
        'payload': {
            'entity_type': 'learner',
            'entity_id': 'L1',
            'data': {
                'mastery': 55,
                'attendance_rate': 0.75,
                'name': 'Qualification Learner',
                'qualification_fixture': True,
            },
        },
        'reversible': True,
    }, expected=200)
    proposal_id = proposal['proposal_id']
    digest = proposal['proposal_digest']

    status, _ = request('POST', f'/v2/decisions/{proposal_id}/approve', token=head,
                        payload={'proposal_digest': digest}, expected=409)
    checks.append(('high_risk_self_approval_blocked', status == 409))
    _, approved = request('POST', f'/v2/decisions/{proposal_id}/approve', token=head2,
                          payload={'proposal_digest': digest}, expected=200)
    checks.append(('independent_approval', approved.get('status') == 'APPROVED'))

    idem = 'remote-qualification-' + uuid.uuid4().hex
    _, executed = request('POST', f'/v2/decisions/{proposal_id}/execute', token=head,
                          payload={'idempotency_key': idem}, expected=200)
    execution_id = executed['execution_id']
    _, duplicate = request('POST', f'/v2/decisions/{proposal_id}/execute', token=head,
                           payload={'idempotency_key': idem}, expected=200)
    checks.append(('idempotent_execution', duplicate.get('execution_id') == execution_id))
    checks.append(('mutation_visible_pre_restart', learner_mastery(learner) == 55.0))

    state = {'execution_id': execution_id, 'proposal_id': proposal_id}
    state_path.write_text(json.dumps(state, sort_keys=True) + '\n')
    evidence = {
        'phase': 'pre_restart', 'base_url': BASE, 'checks': [
            {'name': name, 'pass': bool(ok)} for name, ok in checks
        ], 'passed': sum(bool(ok) for _, ok in checks), 'total': len(checks)
    }
    if not all(ok for _, ok in checks):
        raise AssertionError(evidence)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')


def phase_post(state_path: Path, evidence_path: Path) -> None:
    state = json.loads(state_path.read_text())
    checks = []
    head2 = login('head2')
    learner = login('learner')
    checks.append(('mutation_survives_restart', learner_mastery(learner) == 55.0))
    _, rolled = request('POST', f"/v2/decisions/executions/{state['execution_id']}/rollback",
                        token=head2, payload={}, expected=200)
    checks.append(('rollback_accepted', rolled.get('status') == 'ROLLED_BACK'))
    checks.append(('rollback_restores_prior_state', learner_mastery(learner) == 40.0))
    evidence = {
        'phase': 'post_restart', 'base_url': BASE, 'checks': [
            {'name': name, 'pass': bool(ok)} for name, ok in checks
        ], 'passed': sum(bool(ok) for _, ok in checks), 'total': len(checks)
    }
    if not all(ok for _, ok in checks):
        raise AssertionError(evidence)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {'pre', 'post'}:
        raise SystemExit('usage: remote_probe.py pre|post STATE_JSON EVIDENCE_JSON')
    mode, state, evidence = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if mode == 'pre':
        phase_pre(state, evidence)
    else:
        phase_post(state, evidence)
    print(f'remote_probe_{mode}=PASS')


if __name__ == '__main__':
    main()
