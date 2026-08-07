#!/usr/bin/env python3
from __future__ import annotations

import ast
import configparser
import json
import math
import re
import struct
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "cartomize_qgis"
META = PLUGIN / "metadata.txt"
MAX_BYTES = 25 * 1024 * 1024
FORBIDDEN_SUFFIXES = {".dll", ".exe", ".so", ".dylib", ".pyd", ".pyc", ".class", ".jar"}
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519"}
PLACEHOLDER_TOKENS = {"__AUTHOR_EMAIL__", "__REPOSITORY_URL__", "REPLACE_ME", "YOUR_ACCOUNT", "YOUR_REAL_EMAIL"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key|password|access[_-]?token)\s*=\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"),
]
DANGEROUS_CODE = [
    ("eval", re.compile(r"\beval\s*\(")),
    ("exec", re.compile(r"\bexec\s*\(")),
    ("shell=True", re.compile(r"shell\s*=\s*True")),
    ("os.system", re.compile(r"\bos\.system\s*\(")),
]


def ok_url(value: str) -> bool:
    try:
        u = urlparse(value)
    except Exception:
        return False
    return u.scheme == "https" and bool(u.netloc) and u.hostname not in {"localhost", "127.0.0.1"}


def png_size(path: Path):
    data = path.read_bytes()[:24]
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for required in (META, PLUGIN / "__init__.py", PLUGIN / "LICENSE", PLUGIN / "README.md"):
        if not required.is_file():
            errors.append(f"Missing required file: {required.relative_to(ROOT)}")

    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(META, encoding="utf-8")
    if "general" not in cfg:
        errors.append("metadata.txt has no [general] section")
    else:
        g = cfg["general"]
        required_fields = ["name", "qgisMinimumVersion", "description", "about", "version", "author", "email", "repository"]
        for key in required_fields:
            if not g.get(key, "").strip():
                errors.append(f"Missing metadata field: {key}")
        blob = META.read_text("utf-8")
        for token in PLACEHOLDER_TOKENS:
            if token in blob:
                errors.append(f"Submission placeholder still present: {token}")
        for key in ("repository", "homepage", "tracker"):
            if not ok_url(g.get(key, "")):
                errors.append(f"Metadata {key} must be a valid public HTTPS URL")
        email = g.get("email", "")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or "example." in email.lower():
            errors.append("Metadata email must be a real maintainer email")
        if g.get("experimental", "").lower() not in {"true", "false"}:
            errors.append("experimental must be True or False")
        if g.get("hasProcessingProvider", "").lower() not in {"true", "false"}:
            errors.append("hasProcessingProvider must be True or False")
        if g.get("server", "").lower() not in {"true", "false"}:
            errors.append("server must be True or False")
        if g.get("qgisMaximumVersion", "3.99").startswith("4"):
            warnings.append("QGIS 4 support is declared; make sure Qt6/QGIS4 testing has been completed")

    total = 0
    python_files = []
    for path in PLUGIN.rglob("*"):
        if path.is_symlink():
            errors.append(f"Symlink is not allowed in submission package: {path.relative_to(PLUGIN)}")
            continue
        if not path.is_file():
            continue
        total += path.stat().st_size
        rel = path.relative_to(PLUGIN)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Forbidden binary/compiled file: {rel}")
        if path.name in FORBIDDEN_NAMES or "__pycache__" in path.parts:
            errors.append(f"Forbidden private/generated file: {rel}")
        if path.suffix == ".py":
            python_files.append(path)
            text = path.read_text("utf-8")
            try:
                compile(text, str(path), "exec")
                ast.parse(text)
            except Exception as exc:
                errors.append(f"Python syntax error in {rel}: {exc}")
            for label, pattern in DANGEROUS_CODE:
                if pattern.search(text):
                    errors.append(f"Potentially unsafe code ({label}) in {rel}")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"Potential embedded secret in {rel}")
        elif path.suffix.lower() in {".txt", ".md", ".json", ".yml", ".yaml", ".ini", ".cfg"}:
            try:
                text = path.read_text("utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"Potential embedded secret in {rel}")

    if total > MAX_BYTES:
        errors.append(f"Plugin directory exceeds 25 MiB: {total / 1024 / 1024:.2f} MiB")

    init_text = (PLUGIN / "__init__.py").read_text("utf-8") if (PLUGIN / "__init__.py").exists() else ""
    try:
        tree = ast.parse(init_text)
        funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        if "classFactory" not in funcs:
            errors.append("__init__.py must define classFactory(iface)")
    except Exception:
        pass

    for template in (PLUGIN / "templates_library").rglob("*.json"):
        try:
            json.loads(template.read_text("utf-8"))
        except Exception as exc:
            errors.append(f"Invalid JSON template {template.relative_to(PLUGIN)}: {exc}")

    icon_name = cfg.get("general", "icon", fallback="icon.png")
    icon = PLUGIN / icon_name
    if not icon.is_file():
        errors.append(f"Metadata icon does not exist: {icon_name}")
    elif icon.suffix.lower() == ".png":
        size = png_size(icon)
        if not size:
            warnings.append(f"Could not read PNG dimensions: {icon_name}")
        elif min(size) < 64:
            warnings.append(f"Plugin icon is small: {size[0]}x{size[1]}")

    print("Cartomize QGIS submission preflight")
    print(f"Plugin files: {sum(1 for p in PLUGIN.rglob('*') if p.is_file())}")
    print(f"Python files: {len(python_files)}")
    print(f"Size: {total / 1024 / 1024:.2f} MiB")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print("OK: package is structurally ready for QGIS submission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
