r"""Zero-dependency Cloudinary image uploader for Meta / Instagram Graph API.

Reads CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET
from environment variables or d:\Gemini\.env.

Usage:
  python scripts/cloudinary_upload.py --verify
  python scripts/cloudinary_upload.py --folder meta-auto/sir-dharma-syamim path/to/poster.png
"""

import argparse
import hashlib
import json
import mimetypes
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent


def load_env_file(env_path: pathlib.Path | None = None) -> dict[str, str]:
    path = env_path or (ROOT_DIR / ".env")
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def get_config(key: str, env_path: pathlib.Path | None = None) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        val = load_env_file(env_path).get(key, "").strip()
    if not val:
        print(f"ERROR: {key} tidak ditemui dalam environment atau .env", file=sys.stderr)
        sys.exit(1)
    return val


def sign_params(params: dict[str, str], api_secret: str) -> str:
    pairs = [f"{k}={params[k]}" for k in sorted(params.keys()) if params[k] != ""]
    to_sign = "&".join(pairs) + api_secret
    return hashlib.sha1(to_sign.encode("utf-8")).hexdigest()


def build_multipart(fields: dict[str, str], file_field: str, file_path: pathlib.Path) -> tuple[bytes, str]:
    boundary = f"----GeminiBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(f"{value}\r\n".encode("utf-8"))

    mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode("utf-8")
    )
    chunks.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))

    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_image(
    file_path: pathlib.Path,
    folder: str = "meta-auto",
    env_path: pathlib.Path | None = None,
    resource_type: str = "image",
) -> str:
    if not file_path.exists():
        print(f"ERROR: Fail tidak ditemui: {file_path}", file=sys.stderr)
        sys.exit(1)

    cloud_name = get_config("CLOUDINARY_CLOUD_NAME", env_path=env_path)
    api_key = get_config("CLOUDINARY_API_KEY", env_path=env_path)
    api_secret = get_config("CLOUDINARY_API_SECRET", env_path=env_path)

    if resource_type == "auto":
        ext = file_path.suffix.lower()
        resource_type = "video" if ext in (".mp4", ".mov", ".m4v", ".webm") else "image"

    timestamp = str(int(time.time()))
    params_to_sign = {"folder": folder, "timestamp": timestamp}
    signature = sign_params(params_to_sign, api_secret)

    fields = {
        "api_key": api_key,
        "folder": folder,
        "timestamp": timestamp,
        "signature": signature,
    }
    body, content_type = build_multipart(fields, "file", file_path)
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": content_type,
            "Accept": "application/json",
        },
        method="POST",
    )
    timeout_sec = 300 if resource_type == "video" else 60
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["secure_url"]
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        print(f"Cloudinary Upload Error HTTP {e.code}: {err}", file=sys.stderr)
        sys.exit(1)


def verify_credentials(env_path: pathlib.Path | None = None) -> None:
    import base64

    cloud_name = get_config("CLOUDINARY_CLOUD_NAME", env_path=env_path)
    api_key = get_config("CLOUDINARY_API_KEY", env_path=env_path)
    api_secret = get_config("CLOUDINARY_API_SECRET", env_path=env_path)

    auth = base64.b64encode(f"{api_key}:{api_secret}".encode("utf-8")).decode("ascii")
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/ping"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"Cloudinary OK! Cloud: {cloud_name} | Status: {data.get('status')}")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        print(f"Cloudinary Verify Error HTTP {e.code}: {err}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload poster images to Cloudinary for IG Graph API")
    parser.add_argument("files", nargs="*", type=pathlib.Path, help="Fail gambar PNG/JPG atau video MP4 untuk diupload")
    parser.add_argument("--folder", default="meta-auto/sir-dharma-syamim", help="Folder Cloudinary")
    parser.add_argument("--type", dest="resource_type", default="auto", choices=["auto", "image", "video"], help="Jenis fail (default: auto)")
    parser.add_argument("--env", type=pathlib.Path, default=None, help="Path ke fail .env")
    parser.add_argument("--verify", action="store_true", help="Uji sambungan API Cloudinary sahaja")
    args = parser.parse_args()

    if args.verify:
        verify_credentials(env_path=args.env)
        return

    if not args.files:
        print("Sila nyatakan fail atau guna --verify", file=sys.stderr)
        sys.exit(1)

    urls = []
    for f in args.files:
        url = upload_image(f, folder=args.folder, env_path=args.env, resource_type=args.resource_type)
        urls.append(url)
        print(url)


if __name__ == "__main__":
    main()
