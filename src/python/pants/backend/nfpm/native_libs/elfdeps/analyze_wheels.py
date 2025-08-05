# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import sys
import zipfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

# elfdeps 0.2.0 added analyze_zipfile
from elfdeps import ELFAnalyzeSettings, ELFInfo, SOInfo, analyze_zipfile


@dataclass(frozen=True)
class WheelsELFInfo:
    provides: tuple[SOInfo, ...]
    requires: tuple[SOInfo, ...]

    def to_dict(self) -> dict[str, str | list[str]]:
        # so_info: SOInfo(soname: str, version: str, marker: str)
        # marker is one of "(64bit)" or ""
        # str(so_info) = f"{soname}({version}){marker}"
        return {
            "provides": [str(so_info) for so_info in sorted(self.provides)],
            "requires": [str(so_info) for so_info in sorted(self.requires)],
        }


def analyze_wheel(wheel_path: Path, settings: ELFAnalyzeSettings) -> Generator[ELFInfo]:
    print(".", end="", file=sys.stderr)  # a progress indicator
    with zipfile.ZipFile(wheel_path, mode="r") as wheel:
        yield from analyze_zipfile(wheel, settings=settings)


def analyze_wheels_repo(wheel_repo: Path) -> WheelsELFInfo:
    settings = ELFAnalyzeSettings(unique=True)

    print(f"Analyzing wheels in {wheel_repo}", file=sys.stderr)
    elf_infos: list[ELFInfo] = [
        elf_info for wheel in wheel_repo.iterdir() for elf_info in analyze_wheel(wheel, settings)
    ]
    print(f"Done analyzing wheels in {wheel_repo}.", file=sys.stderr)  # end progress indicators

    provides: set[SOInfo] = set()
    requires: set[SOInfo] = set()
    for elf_info in elf_infos:
        provides.update(elf_info.provides)  # elf_info.provides: list[SOInfo]
        requires.update(elf_info.requires)  # elf_info.requires: list[SOInfo]

    return WheelsELFInfo(tuple(provides), tuple(requires))


def main() -> int:
    if len(sys.argv) != 2:
        raise RuntimeError(f"{sys.argv[0]} expects one positional arg, the wheel_repo path")
    wheel_repo = Path(sys.argv[1])
    if not wheel_repo.resolve().is_dir():
        raise NotADirectoryError(f"{wheel_repo} is not a directory (or a symlink to a directory)!")

    wheels_elf_info = analyze_wheels_repo(wheel_repo=wheel_repo)

    print(json.dumps(wheels_elf_info.to_dict(), indent=None, separators=(",", ":")))

    return 0


if __name__ == "__main__":
    sys.exit(main())
