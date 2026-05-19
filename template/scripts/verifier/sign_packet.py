#!/usr/bin/env python3
"""sign_packet.py — utility for signing/verifying promotion_packet.json.

A small standalone helper for cases where ``verify_request.py`` produced an
unsigned packet (e.g., signing key was added after verification) or where a
downstream consumer wants to re-verify a packet's signature without re-running
the full verifier.

Usage
-----
    # Sign an existing unsigned packet:
    OPEN_AUTORESEARCH_VERIFIER_KEY=<secret> python sign_packet.py \\
        --packet autoresearch/reports/<id>-promotion-packet.json sign

    # Verify a signed packet's signature:
    OPEN_AUTORESEARCH_VERIFIER_KEY=<secret> python sign_packet.py \\
        --packet autoresearch/reports/<id>-promotion-packet.json verify

Exit codes
----------
    0  — sign succeeded / verify confirmed the signature
    1  — verify rejected the signature
    2  — configuration error
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any


def get_signing_key() -> bytes:
    key_str = os.environ.get("OPEN_AUTORESEARCH_VERIFIER_KEY", "")
    if not key_str:
        raise SystemExit("CONFIG ERROR: OPEN_AUTORESEARCH_VERIFIER_KEY is not set.")
    if len(key_str) < 32:
        raise SystemExit(
            "CONFIG ERROR: signing key is shorter than 32 bytes; use a long "
            "random key."
        )
    return key_str.encode("utf-8")


def compute_signature(packet: dict[str, Any], key: bytes) -> str:
    """Replicates verify_request.py's signature scheme.

    Signature is computed over the packet fields EXCLUDING `verifier`, plus a
    `verifier_partial` block containing only (type, identity, signed_at).
    """
    verifier = packet.get("verifier", {})
    fields = {k: v for k, v in packet.items() if k != "verifier"}
    fields["verifier_partial"] = {
        k: verifier.get(k) for k in ("type", "identity", "signed_at")
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def cmd_sign(packet_path: Path, key: bytes) -> int:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    existing = packet.get("verifier", {}).get("signature")
    if existing and existing != "unsigned":
        raise SystemExit(
            f"CONFIG ERROR: packet already signed (signature={existing[:16]}...). "
            f"Refusing to overwrite — re-run the verifier for a fresh packet."
        )
    if "verifier" not in packet:
        raise SystemExit("CONFIG ERROR: packet has no 'verifier' block")
    new_sig = compute_signature(packet, key)
    packet["verifier"]["signature"] = new_sig
    packet_path.write_text(
        json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8"
    )
    sys.stdout.write(f"Signed {packet_path}\n")
    return 0


def cmd_verify(packet_path: Path, key: bytes) -> int:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    claimed = packet.get("verifier", {}).get("signature", "")
    if not claimed or claimed == "unsigned":
        sys.stderr.write(f"FAIL: packet {packet_path} is unsigned; cannot verify.\n")
        return 1
    expected = compute_signature(packet, key)
    if hmac.compare_digest(claimed, expected):
        sys.stdout.write(f"OK: signature on {packet_path} is valid.\n")
        return 0
    sys.stderr.write(
        f"FAIL: signature on {packet_path} does NOT match. "
        f"claimed={claimed[:16]}... expected={expected[:16]}...\n"
    )
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Sign or verify a §10.5 promotion packet's HMAC."
    )
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("action", choices=["sign", "verify"])
    args = parser.parse_args(argv)
    if not args.packet.exists():
        sys.stderr.write(f"CONFIG ERROR: {args.packet} does not exist\n")
        return 2
    key = get_signing_key()
    if args.action == "sign":
        return cmd_sign(args.packet, key)
    return cmd_verify(args.packet, key)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
