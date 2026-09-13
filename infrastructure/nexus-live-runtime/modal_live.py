from __future__ import annotations

import os
import sys
from pathlib import Path

import modal

APP_NAME = "mft-education-nexus-live"
BUILD_ID = "MFT-EDUCATION-NEXUS-CANONICAL-2026-09-04"
SOURCE_ROOT = Path("runtime")
REQ = SOURCE_ROOT / "requirements.lock"

requirements = [
    line.strip()
    for line in REQ.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
requirements += ["psycopg==3.3.4", "boto3==1.43.64"]

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install(
        "ca-certificates",
        "tesseract-ocr",
        "tesseract-ocr-eng",
        "ffmpeg",
        "espeak",
        "libpocketsphinx3",
        "pocketsphinx-en-us",
        "libpq5",
    )
    .pip_install(*requirements)
    .add_local_dir("runtime/mft_education_nexus", remote_path="/opt/nexus/mft_education_nexus", copy=True)
)

runtime_secrets = modal.Secret.from_name(
    "mft-education-nexus-live-secrets",
    required_keys=[
        "MFT_EDU_POSTGRES_DSN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "PAYNOW_INTEGRATION_KEY",
        "MFT_REVENUE_ADMIN_TOKEN",
    ],
)

app = modal.App(APP_NAME, include_source=True)

NON_SECRET_ENV = {
    "MFT_ENVIRONMENT": "staging",
    "MFT_RUNTIME_PROFILE": "pilot",
    "MFT_PRODUCTION_ACTIVATION": "0",
    "MFT_DATA_DIR": "/tmp/mft-education",
    "MFT_TRUSTED_HOSTS": "staging.mftintelligence.com,*.modal.run",
    "MFT_PUBLIC_BASE_URL": "https://staging.mftintelligence.com",
    "MFT_ENABLE_OPERATOR_API": "0",
    "MFT_BOOTSTRAP_MODE": "0",
    "MFT_ENABLE_BROWSER_MEDIA": "0",
    "MFT_EDU_STATE_BACKEND": "postgres",
    "MFT_EDU_SHARED_DATASTORE_ADAPTER": "neon-postgres://quiet-thunder-10380542/br-dry-paper-ay0ie7lf",
    "MFT_EDU_OBJECT_BACKEND": "s3",
    "MFT_EDU_S3_BUCKET": "mft-nexus-app",
    "MFT_EDU_S3_ENDPOINT_REF": "cloudflare-r2://93f395f5121954671f92fffa453d6b61",
    "MFT_EDU_S3_ENDPOINT_URL": "https://93f395f5121954671f92fffa453d6b61.r2.cloudflarestorage.com",
    "MFT_EDU_S3_REGION": "auto",
    "MFT_EDU_S3_SSE": "AES256",
    "MFT_EDU_AUDIT_S3_BUCKET": "mft-nexus-audit",
    "MFT_EDU_AUDIT_S3_ENDPOINT_URL": "https://93f395f5121954671f92fffa453d6b61.r2.cloudflarestorage.com",
    "MFT_EDU_AUDIT_S3_REGION": "auto",
    "MFT_EDU_AUDIT_S3_SSE": "AES256",
    "MFT_EDU_AUDIT_RETENTION_RULE_REF": "mft-staging-audit-retention-90d",
    "MFT_ENABLE_REVENUE_API": "1",
    "MFT_REVENUE_PROVIDER": "paynow",
    "PAYNOW_INTEGRATION_ID": "26343",
    "MFT_ENFORCE_COMMERCIAL_ENTITLEMENTS": "1",
    "MFT_OTEL_ENABLED": "0",
}

@app.function(
    image=image,
    name="nexus_api",
    secrets=[runtime_secrets],
    min_containers=0,
    max_containers=20,
    scaledown_window=300,
    timeout=300,
)
@modal.asgi_app(requires_proxy_auth=True)
def nexus_api():
    for key, value in NON_SECRET_ENV.items():
        os.environ.setdefault(key, value)
    sys.path.insert(0, "/opt/nexus")
    from mft_education_nexus.app import app as fastapi_app
    return fastapi_app

@app.function(image=image, name="runtime_probe", secrets=[runtime_secrets], timeout=120)
def runtime_probe() -> dict[str, object]:
    for key, value in NON_SECRET_ENV.items():
        os.environ.setdefault(key, value)
    sys.path.insert(0, "/opt/nexus")
    from mft_education_nexus.app import app as fastapi_app
    from mft_education_nexus.core.platform_db import db_health
    routes = sorted({getattr(r, "path", "") for r in fastapi_app.routes if getattr(r, "path", "")})
    return {
        "schema": "mft.education_nexus.runtime.modal_live_probe.v1",
        "build": BUILD_ID,
        "routes": routes,
        "db_health": db_health(),
        "state_backend": os.environ.get("MFT_EDU_STATE_BACKEND"),
        "object_backend": os.environ.get("MFT_EDU_OBJECT_BACKEND"),
        "production_activation": False,
        "axiom_dependency": False,
    }
