from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath

import modal

APP_NAME = 'mft-product-frontier-runtime'
VOLUME_NAME = 'mft-product-frontier-runtime-data'
SECRET_NAME = 'mft-product-frontier-runtime-secrets'
SOURCE_ZIP = Path('/opt/mft-product-frontier/source/runtime_source.zip')
EXPECTED_SOURCE_SHA256 = '29d149a7789375003e0e86499a4ee0f4f3995d16678176a2735f2f1c208e1c53'
PARENT_OVERLAY_SHA256 = '32e83dabc02b99c5441d91edb4bd6fdc8e86d2c6bb4ab270dac40d55979b1e1a'
RUNTIME_ROOT = Path('/opt/mft-product-frontier/runtime')
DATA_ROOT = Path('/var/lib/mft-product-frontier')
DB_PATH = DATA_ROOT / 'institution.db'

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
secret = modal.Secret.from_name(SECRET_NAME)

HERE = Path(__file__).resolve().parent
LOCAL_SOURCE_ZIP = HERE / 'input' / 'runtime_source.zip'

image = (
    modal.Image.debian_slim(python_version='3.12')
    .pip_install(
        'fastapi==0.128.2',
        'pydantic==2.13.4',
        'cryptography==46.0.4',
    )
    .add_local_file(str(LOCAL_SOURCE_ZIP), str(SOURCE_ZIP), copy=True)
)


def verify_and_extract() -> Path:
    actual = hashlib.sha256(SOURCE_ZIP.read_bytes()).hexdigest()
    if actual != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f'runtime_source_sha256_mismatch:{actual}')

    with zipfile.ZipFile(SOURCE_ZIP) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f'runtime_source_zip_crc_failure:{bad}')
        manifest = json.loads(archive.read('RUNTIME_SOURCE_MANIFEST.json'))
        if manifest.get('parent_overlay_sha256') != PARENT_OVERLAY_SHA256:
            raise RuntimeError('parent_overlay_sha256_mismatch')
        expected = {row['path']: row for row in manifest.get('files', [])}
        if not expected:
            raise RuntimeError('runtime_source_manifest_empty')
        for name, row in expected.items():
            pure = PurePosixPath(name)
            if pure.is_absolute() or '..' in pure.parts:
                raise RuntimeError(f'unsafe_runtime_path:{name}')
            data = archive.read(name)
            if len(data) != int(row['bytes']):
                raise RuntimeError(f'runtime_source_size_mismatch:{name}')
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise RuntimeError(f'runtime_source_file_hash_mismatch:{name}')
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        archive.extractall(RUNTIME_ROOT)

    if not (RUNTIME_ROOT / 'institution_os' / 'api.py').is_file():
        raise RuntimeError('runtime_api_missing')
    if not (RUNTIME_ROOT / 'institution_ui' / 'index.html').is_file():
        raise RuntimeError('runtime_ui_missing')
    return RUNTIME_ROOT


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
    from fastapi import Request
    from fastapi.responses import JSONResponse
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
        supplied = request.headers.get('x-mft-origin-secret', '')
        if not hmac.compare_digest(supplied, origin_secret):
            return JSONResponse({'detail': 'edge_origin_required'}, status_code=403)
        response = await call_next(request)
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and response.status_code < 500:
            volume.commit()
        response.headers['x-mft-runtime-source-sha256'] = EXPECTED_SOURCE_SHA256
        response.headers['x-mft-parent-overlay-sha256'] = PARENT_OVERLAY_SHA256
        response.headers['cache-control'] = 'no-store'
        return response

    @api.get('/_mft/runtime/health', include_in_schema=False)
    def runtime_health():
        return {
            'status': 'ok',
            'mode': 'PARITY_CANDIDATE_REMOTE_QUALIFICATION',
            'runtime_source_sha256': EXPECTED_SOURCE_SHA256,
            'parent_overlay_sha256': PARENT_OVERLAY_SHA256,
            'database': 'sqlite-persistent-modal-volume',
            'modal_max_containers': 1,
            'promotion_effect': 'NONE',
        }

    return api
