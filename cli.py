#!/usr/bin/env python3
"""CLI to manage PII masking service API tokens."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:8090"


def _request(method: str, url: str, master_key: str, body: bytes | None = None) -> dict:
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("X-Master-Key", master_key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Connection error: {exc.reason}", file=sys.stderr)
        sys.exit(1)


def cmd_generate(args: argparse.Namespace) -> None:
    data = _request("POST", f"{args.url}/tokens", args.master_key)
    print(json.dumps(data, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    data = _request("GET", f"{args.url}/tokens", args.master_key)
    print(json.dumps(data, indent=2))


def cmd_revoke(args: argparse.Namespace) -> None:
    data = _request("DELETE", f"{args.url}/tokens/{args.id}", args.master_key)
    print(json.dumps(data, indent=2))


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--url", default=os.environ.get("PII_URL", DEFAULT_URL))
    p.add_argument("--master-key", default=os.environ.get("PII_MASTER_KEY", ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="PII Masking token management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Generate a new API token")
    _add_common(p_gen)
    p_gen.set_defaults(func=cmd_generate)

    p_list = sub.add_parser("list", help="List active tokens")
    _add_common(p_list)
    p_list.set_defaults(func=cmd_list)

    p_rev = sub.add_parser("revoke", help="Revoke a token by id")
    p_rev.add_argument("id", help="Token id (UUID) to revoke")
    _add_common(p_rev)
    p_rev.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    if not args.master_key:
        print(
            "Error: master key required. Pass --master-key or set PII_MASTER_KEY.",
            file=sys.stderr,
        )
        sys.exit(2)
    args.func(args)


if __name__ == "__main__":
    main()
