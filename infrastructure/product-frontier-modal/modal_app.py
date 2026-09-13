from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

import modal

APP_NAME = 'mft-product-frontier-runtime'
VOLUME_NAME = 'mft-product-frontier-runtime-data'
SECRET_NAME = 'mft-product-frontier-runtime-secrets'
SOURCE_ZIP = Path('/opt/mft-product-frontier/source/recovery_overlay.zip')
EXPECTED_SOURCE_SHA256 = '32e83dabc02b99c5441d91edb4bd6fdc8e86d2c6bb4ab270dac40d55979b1e1a'
RUNTIME_ROOT = Path('/opt/mft-product-frontier/runtime')
DATA_ROOT = Path('/var/lib/mft-product-frontier')
DB_PATH = DATA_ROOT / 'institution.db'

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
secret = modal.Secret.from_name(SECRET_NAME)

HERE = Path(__file__).resolve().parent
LOCAL_SOURCE_ZIP = HERE / 'input' / 'recovery_overlay.zip'

image = (
    modal.Image.debian_slim(python_version='3.12')
    .pip_install(
        'fastapi==0.116.1',
        'pydantic==2.11.7',
        'cryptography==45.0.6',
    )
    .add_local_file(str(LOCAL_SOURCE_ZIP), str(SOURCE_ZIP), copy=True)
)


def verify_and_extract() -> Path:
    actual = hashlib.sha256(SOURCE_ZIP.read_bytes()).hexdigest()
    if actual != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f'overlay_sha256_mismatch:{actual}')
    if not RUNTIME_ROOT.exists():
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(SOURCE_ZIP) as archive:
            archive.testzip() is None or (_ for _ in ()).throw(RuntimeError('overlay_zip_crc_failure'))
            archive.extractall(RUNTIME_ROOT)
    roots = [p for p in RUNTIME_ROOT.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise RuntimeError('overlay_root_not_unique')
    root = roots[0]
    if not (root / 'institution_os' / 'api.py').is_file():
        raise RuntimeError('overlay_api_missing')
    return root


@app.function(
    image=image,
    cpu=4.0,
    memory=8192,
    timeout=3600,
    min_containers=1,
    max_containers=1,
    scaledown_window=1200,
    volumes={str(DATA_ROOT): volume},
    secrets=[secret],
)
@modal.concurrent(max_inputs=64)
@modal.asgi_app(label='runtime')
def runtime():
    root = verify_and_extract()
    sys.path.insert(0, str(root))
    from fastapi import HTTPException, Request
    from institution_os.api import create_app

    identity_key_hex = os.environ.get('MFT_IDENTITY_KEY_HEX', '')
    origin_secret = os.environ.get('MFT_EDGE_ORIGIN_SECRET', '')
    if len(identity_key_hex) != 64 or not origin_secret:
        raise RuntimeError('runtime_secrets_not_configured')
    try:
        identity_key = bytes.fromhex(identity_key_hex)
    except ValueError as exc:
        raise RuntimeError('identity_key_invalid_hex') from exc
    if len(identity_key) != 32:
        raise RuntimeError('identity_key_invalid_length')

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    api = create_app(str(DB_PATH), identity_key=identity_key)

    @api.middleware('http')
    async def edge_boundary(request: Request, call_next):
        if request.headers.get('x-mft-origin-secret', '') != origin_secret:
            raise HTTPException(status_code=403, detail='edge_origin_required')
        response = await call_next(request)
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and response.status_code < 500:
            volume.commit()
        response.headers['x-mft-runtime-overlay-sha256'] = EXPECTED_SOURCE_SHA256
        response.headers['cache-control'] = 'no-store'
        return response

    @api.get('/_mft/runtime/health', include_in_schema=False)
    def runtime_health():
        return {
            'status': 'ok',
            'mode': 'PARITY_CANDIDATE_REMOTE_QUALIFICATION',
            'overlay_sha256': EXPECTED_SOURCE_SHA256,
            'database': 'sqlite-persistent-volume',
            'modal_max_containers': 1,
            'promotion_effect': 'NONE',
        }

    return api
