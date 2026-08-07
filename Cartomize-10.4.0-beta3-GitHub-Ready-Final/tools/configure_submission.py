#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "cartomize_qgis" / "metadata.txt"


def valid_https(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc) and "REPLACE" not in url and "YOUR_" not in url


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)) and "example." not in value.lower()


def main() -> int:
    ap = argparse.ArgumentParser(description="Configure Cartomize metadata for official QGIS submission.")
    ap.add_argument("--repository", required=True, help="Public HTTPS source repository URL")
    ap.add_argument("--email", required=True, help="Real maintainer email")
    ap.add_argument("--homepage", help="Optional plugin homepage; defaults to repository URL")
    args = ap.parse_args()

    repo = args.repository.rstrip("/")
    homepage = (args.homepage or repo).rstrip("/")
    tracker = repo + "/issues"

    if not valid_https(repo):
        raise SystemExit("Repository must be a real public HTTPS URL.")
    if not valid_https(homepage):
        raise SystemExit("Homepage must be a real HTTPS URL.")
    if not valid_email(args.email):
        raise SystemExit("Please provide a real maintainer email address.")

    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    cfg.read(METADATA, encoding="utf-8")
    general = cfg["general"]
    general["email"] = args.email
    general["homepage"] = homepage
    general["repository"] = repo
    general["tracker"] = tracker

    with METADATA.open("w", encoding="utf-8", newline="\n") as fh:
        cfg.write(fh, space_around_delimiters=False)

    print(f"Configured: {METADATA}")
    print(f"Repository: {repo}")
    print(f"Homepage:   {homepage}")
    print(f"Tracker:    {tracker}")
    print(f"Email:      {args.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
