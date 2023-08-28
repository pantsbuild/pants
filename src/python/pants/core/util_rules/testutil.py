# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Sequence, TypeVar

from pants.util.contextutil import temporary_dir

_T = TypeVar("_T")


def materialize_indices(sequence: Sequence[_T], indices: Iterable[int]) -> tuple[_T, ...]:
    return tuple(sequence[i] for i in indices)


@contextmanager
def fake_asdf_root(
    fake_versions: list[str],
    fake_home_versions: list[int],
    fake_local_versions: list[int],
    *,
    tool_name: str,
):
    with temporary_dir() as home_dir, temporary_dir() as asdf_dir:
        fake_dirs: list[Path] = []
        fake_version_dirs: list[str] = []

        fake_home_dir = Path(home_dir)
        fake_tool_versions = fake_home_dir / ".tool-versions"
        fake_home_versions_str = " ".join(materialize_indices(fake_versions, fake_home_versions))
        fake_tool_versions.write_text(f"nodejs lts\njava 8\n{tool_name} {fake_home_versions_str}\n")

        fake_asdf_dir = Path(asdf_dir)
        fake_asdf_plugin_dir = fake_asdf_dir / "plugins" / tool_name
        fake_asdf_installs_dir = fake_asdf_dir / "installs" / tool_name

        fake_dirs.extend(
            [fake_home_dir, fake_asdf_dir, fake_asdf_plugin_dir, fake_asdf_installs_dir]
        )

        for version in fake_versions:
            fake_version_path = fake_asdf_installs_dir / version / "bin"
            fake_version_dirs.append(f"{fake_version_path}")
            fake_dirs.append(fake_version_path)

        for fake_dir in fake_dirs:
            fake_dir.mkdir(parents=True, exist_ok=True)

        yield (
            home_dir,
            asdf_dir,
            fake_version_dirs,
            # fake_home_version_dirs
            materialize_indices(fake_version_dirs, fake_home_versions),
            # fake_local_version_dirs
            materialize_indices(fake_version_dirs, fake_local_versions),
        )
