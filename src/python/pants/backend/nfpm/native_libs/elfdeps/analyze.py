# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections.abc import Generator, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

# elfdeps 0.2.0 added analyze_zipfile
from elfdeps import ELFAnalyzeSettings, ELFInfo, SOInfo, analyze_zipfile


@dataclass(frozen=True)
class ELFInfoAnalysis:
    provides: tuple[SOInfo, ...]
    requires: tuple[SOInfo, ...]

    def __init__(self, provides: Iterable[SOInfo], requires: Iterable[SOInfo]):
        object.__setattr__(self, "provides", tuple(sorted(provides)))
        object.__setattr__(self, "requires", tuple(sorted(requires)))

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        # so_info: SOInfo(soname: str, version: str, marker: str)
        # marker is one of "(64bit)" or ""
        # str(so_info) = f"{soname}({version}){marker}"

        def so_infos_to_dicts(so_infos: tuple[SOInfo, ...]) -> list[dict[str, str]]:
            return [asdict(so_info) | {"so_info": str(so_info)} for so_info in so_infos]

        return {
            "provides": so_infos_to_dicts(self.provides),
            "requires": so_infos_to_dicts(self.requires),
        }

    def to_json(self, indent=None, separators=(",", ":")) -> str:
        return json.dumps(self.to_dict(), indent=indent, separators=separators)

    @classmethod
    def from_elf_infos(cls, elf_infos: Iterable[ELFInfo]) -> ELFInfoAnalysis:
        provides: set[SOInfo] = set()
        requires: set[SOInfo] = set()
        for elf_info in elf_infos:
            provides.update(elf_info.provides)  # elf_info.provides: list[SOInfo]
            requires.update(elf_info.requires)  # elf_info.requires: list[SOInfo]

        return cls(tuple(provides), tuple(requires))


def analyze_wheel(wheel_path: Path, settings: ELFAnalyzeSettings) -> Generator[ELFInfo]:
    print(".", end="", file=sys.stderr)  # a progress indicator
    with zipfile.ZipFile(wheel_path, mode="r") as wheel:
        yield from analyze_zipfile(wheel, settings=settings)


def analyze_wheels_repo(wheel_repo: Path) -> ELFInfoAnalysis:
    settings = ELFAnalyzeSettings(unique=True)

    print(f"Analyzing wheels in {wheel_repo}", file=sys.stderr)
    elf_infos: list[ELFInfo] = [
        elf_info for wheel in wheel_repo.iterdir() for elf_info in analyze_wheel(wheel, settings)
    ]
    print(f"Done analyzing wheels in {wheel_repo}.", file=sys.stderr)  # end progress indicators

    return ELFInfoAnalysis.from_elf_infos(elf_infos)


def main(args: list[str]) -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--mode", required=True, choices=("wheels",))
    arg_parser.add_argument("directory", nargs=1, type=Path)
    options = arg_parser.parse_args()

    directory = options.directory[0]
    if not directory.resolve().is_dir():
        raise NotADirectoryError(f"{directory} is not a directory (or a symlink to a directory)!")

    if options.mode == "wheels":
        elf_info_analysis = analyze_wheels_repo(wheel_repo=directory)

    print(elf_info_analysis.to_json())

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
