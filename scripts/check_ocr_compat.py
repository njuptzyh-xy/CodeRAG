import argparse
import binascii
import json
import os
import struct
import sys
import zlib

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import setting


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack("!I", len(data))
        + tag
        + data
        + struct.pack("!I", binascii.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_probe_png_base64(width: int = 160, height: int = 60) -> str:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            value = 255
            if 10 < y < 50 and (20 < x < 25 or 40 < x < 45 or 60 < x < 65 or 80 < x < 85):
                value = 0
            row.extend((value, value, value))
        rows.append(b"\x00" + bytes(row))

    raw = b"".join(rows)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(
        b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    )
    idat = _png_chunk(b"IDAT", zlib.compress(raw, 9))
    iend = _png_chunk(b"IEND", b"")
    return base64_encode(signature + ihdr + idat + iend)


def base64_encode(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()


def probe(url: str, payload: dict, timeout: float) -> tuple[bool, str]:
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return False, f"request failed: {exc}"

    try:
        body = response.json()
    except json.JSONDecodeError:
        body = response.text

    has_expected_field = isinstance(body, dict) and (
        "texts" in body or "ocr_result" in body
    )
    ok = response.status_code == 200 and has_expected_field
    return ok, f"status={response.status_code} body={body}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check OCR compatibility for CodeRAG")
    parser.add_argument("--url", default=setting.OCR_URL)
    parser.add_argument("--timeout", type=float, default=setting.OCR_TIMEOUT)
    parser.add_argument(
        "--image-base64",
        default=make_probe_png_base64(),
        help="Base64 image payload used for probing",
    )
    args = parser.parse_args()

    if not args.image_base64:
        print("image base64 payload is empty")
        return 1

    checks = [
        ("paddle-style", {"img_base64": args.image_base64}),
        ("legacy-style", {"base64_str": args.image_base64}),
    ]

    overall_ok = False
    for label, payload in checks:
        ok, message = probe(args.url, payload, args.timeout)
        print(f"{label}: {message}")
        overall_ok = overall_ok or ok

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
