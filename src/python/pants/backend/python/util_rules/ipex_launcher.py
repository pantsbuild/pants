# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Entrypoint script for a dehydrated ipex file.

The script builds a hydrated PEX next to itself on first execution, then execs that PEX.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile

APP_CODE_PREFIX = "user_files/"


def _strip_app_code_prefix(path: str) -> str:
    if not path.startswith(APP_CODE_PREFIX):
        raise ValueError(f"Path {path} in IPEX-INFO did not begin with {APP_CODE_PREFIX}.")
    return path[len(APP_CODE_PREFIX) :]


def _log(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def _requirement_from_wheel_filename(filename: str) -> str | None:
    if not filename.endswith(".whl"):
        return None
    parts = filename.split("-")
    if len(parts) < 2:
        return None
    return f"{parts[0].replace('_', '-')}=={parts[1]}"


def _requirements_from_pex_info(pex_info: dict) -> tuple[str, ...]:
    requirements = []
    distributions = pex_info.get("distributions") or {}
    for distribution_path in distributions:
        requirement = _requirement_from_wheel_filename(os.path.basename(distribution_path))
        if requirement is not None:
            requirements.append(requirement)
    if requirements:
        return tuple(sorted(set(requirements)))
    return tuple(pex_info.get("requirements") or ())


def _hydrate_pex_file(ipex_file: str, hydrated_pex_file: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        source_dir = os.path.join(td, "sources")
        os.makedirs(source_dir)
        requirements_path = os.path.join(td, "requirements.txt")

        with zipfile.ZipFile(ipex_file) as zf:
            bootstrap_info = json.loads(zf.read("BOOTSTRAP-PEX-INFO").decode())
            ipex_info = json.loads(zf.read("IPEX-INFO").decode())

            for path in ipex_info["code"]:
                output_path = os.path.join(source_dir, _strip_app_code_prefix(path))
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with zf.open(path) as src, open(output_path, "wb") as dst:
                    dst.write(src.read())

        with open(requirements_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(_requirements_from_pex_info(bootstrap_info)))
            fp.write("\n")

        resolver_settings = ipex_info["resolver_settings"]
        argv = [
            sys.executable,
            "-m",
            "pex",
            "--output-file",
            hydrated_pex_file,
            "--sources-directory",
            source_dir,
            "--requirement",
            requirements_path,
            *ipex_info["pex_args"],
            "--no-pypi",
            *(f"--index={index}" for index in resolver_settings["indexes"]),
            *(f"--find-links={find_link}" for find_link in resolver_settings["find_links"]),
        ]
        if bootstrap_info.get("distributions"):
            argv.append("--no-transitive")

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        subprocess.run(argv, env=env, check=True)


def main() -> None:
    ipex_file = sys.argv[0]
    filename_base, ext = os.path.splitext(ipex_file)
    hydrated_pex_file = f"{filename_base}.ipex.pex" if ext == ".pex" else f"{filename_base}.pex"

    if not os.path.exists(hydrated_pex_file):
        _log(f"Hydrating {ipex_file} to {hydrated_pex_file}...")
        _hydrate_pex_file(ipex_file, hydrated_pex_file)

    os.execv(sys.executable, [sys.executable, hydrated_pex_file, *sys.argv[1:]])


if __name__ == "__main__":
    main()
