# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path

LOCKFILE_NAMES = {
    "npm": "package-lock.json",
    "pnpm": "pnpm-lock.yaml",
    "yarn": "yarn.lock",
}


def load_js_test_project(
    project_name: str, *, package_manager: str | None = None
) -> dict[str, str]:
    base_dir = Path(__file__).parent / "test_resources" / project_name
    files = {}

    # Determine which lockfiles to exclude
    exclude_lockfiles = set()
    if package_manager:
        for pm, lockfile in LOCKFILE_NAMES.items():
            if pm != package_manager:
                exclude_lockfiles.add(lockfile)

    for file_path in base_dir.rglob("*"):
        if file_path.is_file():
            # Skip lockfiles not for the selected package manager
            if file_path.name in exclude_lockfiles:
                continue
            relative_path = file_path.relative_to(base_dir)
            files[f"{project_name}/{relative_path}"] = file_path.read_text()

    return files
