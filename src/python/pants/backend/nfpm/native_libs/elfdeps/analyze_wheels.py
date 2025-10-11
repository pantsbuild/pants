# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import sys
import zipfile
from collections import defaultdict
from collections.abc import Generator, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

# elfdeps 0.2.0 added analyze_zipfile
from elfdeps import ELFAnalyzeSettings, ELFInfo, SOInfo, analyze_zipfile


@dataclass(frozen=True)
class WheelsELFInfo:
    provides: tuple[SOInfo, ...]
    requires: tuple[SOInfo, ...]
    soname_runpaths: tuple[tuple[str, tuple[str, ...]], ...]

    def __init__(
        self,
        provides: Iterable[SOInfo],
        requires: Iterable[SOInfo],
        runpaths: Mapping[str, Iterable[str]],
    ):
        object.__setattr__(self, "provides", tuple(sorted(provides)))
        object.__setattr__(self, "requires", tuple(sorted(requires)))
        object.__setattr__(
            self,
            "soname_runpaths",
            tuple(sorted((soname, tuple(rpaths)) for soname, rpaths in runpaths.items())),
        )

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        # so_info: SOInfo(soname: str, version: str, marker: str)
        # marker is one of "(64bit)" or ""
        # str(so_info) = f"{soname}({version}){marker}"

        def so_infos_to_dicts(so_infos: tuple[SOInfo, ...]) -> list[dict[str, str]]:
            return [asdict(so_info) | {"so_info": str(so_info)} for so_info in so_infos]

        return {
            "provides": so_infos_to_dicts(self.provides),
            "requires": so_infos_to_dicts(self.requires),
            "soname_runpaths": dict(
                (soname, list(rpaths)) for soname, rpaths in self.soname_runpaths
            ),
        }

    def to_json(self, indent=None, separators=(",", ":")) -> str:
        return json.dumps(self.to_dict(), indent=indent, separators=separators)


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
    runpaths: defaultdict[str, list[str]] = defaultdict(list)
    for elf_info in elf_infos:
        provides.update(elf_info.provides)  # elf_info.provides: list[SOInfo]
        requires.update(elf_info.requires)  # elf_info.requires: list[SOInfo]
        if elf_info.runpath:
            rpaths = runpaths[elf_info.soname]  # elf_info.runpath: list[str]
            rpaths.extend(rpath for rpath in elf_info.runpath if rpath not in rpaths)

    return WheelsELFInfo(provides, requires, runpaths)


def main(args: list[str]) -> int:
    if len(args) != 2:
        raise RuntimeError(f"{args[0]} expects one positional arg, the wheel_repo path")
    wheel_repo = Path(args[1])
    if not wheel_repo.resolve().is_dir():
        raise NotADirectoryError(f"{wheel_repo} is not a directory (or a symlink to a directory)!")

    wheels_elf_info = analyze_wheels_repo(wheel_repo=wheel_repo)

    print(wheels_elf_info.to_json())

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
