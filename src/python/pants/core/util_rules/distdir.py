# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import Path

from pants.base.build_root import BuildRoot
from pants.engine.rules import collect_rules, rule
from pants.option.global_options import GlobalOptions
from pants.util.strutil import softwrap


def is_child_of(path: Path, directory: Path) -> bool:
    abs_path = path if path.is_absolute() else directory.joinpath(path).resolve()
    return directory == abs_path or directory in abs_path.parents


# for backward compatibility -- to prevent extensive patching across the codebase
# we we preserve the old relpath attribute, but note that the Path held inside
# is always absolute now; see normalize_distdir()
@dataclass(frozen=True)
class DistDir:
    """The directory to which we write distributable files."""

    relpath: Path


@rule
async def get_distdir(global_options: GlobalOptions, buildroot: BuildRoot) -> DistDir:
    return normalize_distdir(Path(global_options.pants_distdir), buildroot.pathlib_path)


def normalize_distdir(distdir: Path, buildroot: Path) -> DistDir:
    if distdir.is_absolute():
        path = distdir
    else:
        path = buildroot / distdir
    return DistDir(relpath=path)


def rules():
    return collect_rules()
