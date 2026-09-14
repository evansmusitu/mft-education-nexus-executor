#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_MANIFEST_SHA256 = "420a024390a4a9a94acaa4ff4ee169f6e800d13e03633215cd0db0e03035ca0c"
EXPECTED = {
    "App.tsx": "c72491f0a2ce44b59c6a6cf13f52dfd58a54d045e660647fe5fcd382688daaca",
    "README.md": "e3987a4480e9339bc770f234daa96afc668d2375250360c639b2f672ef351322",
    "app.json": "aef8b29acafb2d3a4f9e739973c076ba7e6b3805299d198fca56b10a96dd00f1",
    "eas.json": "7894e906f4cb57e254d0a6fc21299b1b8fb9aa50282fe5353fd37f626ad8dc95",
    "package.json": "c1dfc94e2d317cd21d99a2c3653821aab0508115bebdd08af3d7a34f08f3d5a7",
    "src/api.ts": "2d8f0517832b3c0b8dded1132088dfc3dca0e1cfe1f68a356e652e816d2151bd",
    "src/offlineIntents.ts": "3e2c9e91531d347233f1a27aa061b95d77924fc1e63dd248b12b7f9d3b27d13b",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: materialize_v4.py ANDROID_SOURCE_DIR")
    root = Path(sys.argv[1])

    p = root / "package.json"
    d = json.loads(p.read_text())
    d["name"] = "musitu-sovereign-institution-android-frontier"
    d["version"] = "0.1.1"
    d["devDependencies"]["typescript"] = "~6.0.3"
    p.write_text(json.dumps(d, indent=2) + "\n")

    p = root / "app.json"
    d = json.loads(p.read_text())
    d["expo"]["name"] = "MUSITU Sovereign Institution Intelligence"
    d["expo"]["slug"] = "musitu-sovereign-institution"
    d["expo"]["version"] = "0.1.1"
    d["expo"]["android"]["versionCode"] = 2
    p.write_text(json.dumps(d, indent=2) + "\n")

    p = root / "App.tsx"
    s = p.read_text()
    old = "const API_URL = process.env.EXPO_PUBLIC_MFT_API_URL || 'https://institution.example.invalid';"
    new = "const API_URL = process.env.EXPO_PUBLIC_MUSITU_API_URL || process.env.EXPO_PUBLIC_MFT_API_URL || 'https://institution.example.invalid';"
    if old not in s:
        raise SystemExit("V4 materialization failed: expected V2 API_URL line absent")
    s = s.replace(old, new, 1)
    old_brand = "fontWeight:'800',marginVertical:12}}>MFT</Text>"
    new_brand = "fontWeight:'800',marginVertical:12}}>MUSITU</Text>"
    if old_brand not in s:
        raise SystemExit("V4 materialization failed: expected V2 brand absent")
    p.write_text(s.replace(old_brand, new_brand, 1))

    p = root / "README.md"
    s = p.read_text()
    old_title = "# MFT Android Frontier client"
    if not s.startswith(old_title):
        raise SystemExit("V4 materialization failed: expected V2 README title absent")
    s = s.replace(old_title, "# MUSITU Android Frontier client", 1)
    old_note = "This runtime does not contain an Android SDK or installed Expo dependency tree, so no APK/AAB build is claimed by this reconstruction."
    new_note = "This sealed source package contains no prebuilt APK/AAB. Build and API-36 device qualification are performed externally and must remain hash-bound to the qualified source and artifacts."
    if old_note not in s:
        raise SystemExit("V4 materialization failed: expected V2 README note absent")
    p.write_text(s.replace(old_note, new_note, 1))

    manifest = "\n".join(f"{digest}  {name}" for name, digest in EXPECTED.items()) + "\n"
    (root / "SHA256SUMS.txt").write_text(manifest)

    if sha256(root / "SHA256SUMS.txt") != EXPECTED_MANIFEST_SHA256:
        raise SystemExit("V4 manifest digest mismatch")
    for name, expected in EXPECTED.items():
        actual = sha256(root / name)
        if actual != expected:
            raise SystemExit(f"V4 payload mismatch {name}: {actual} != {expected}")

    if ">MFT</Text>" in (root / "App.tsx").read_text():
        raise SystemExit("legacy MFT brand remains user-visible")
    if ">MUSITU</Text>" not in (root / "App.tsx").read_text():
        raise SystemExit("MUSITU brand missing from user-visible client")

    print("V4_MATERIALIZATION_PASS")
    print(f"manifest_sha256={EXPECTED_MANIFEST_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
