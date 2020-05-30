#!/usr/bin/env python3
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import datetime
import re
from pathlib import Path
from textwrap import dedent
from typing import List, Sequence

from common import die

EXPECTED_HEADER = dedent(
    """\
    # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
    # Licensed under the Apache License, Version 2.0 (see LICENSE).

    """
)

EXPECTED_NUM_LINES = 3

CURRENT_YEAR = str(datetime.datetime.now().year)
CURRENT_CENTURY_REGEX = re.compile(r"20\d\d")

PY2_DIRECTORIES = {
    Path("src/python/pants/backend/python/tasks/coverage"),
    Path("src/python/pants/backend/python/tasks/pytest"),
}


class HeaderCheckFailure(Exception):
    """This is only used for control flow and to propagate the `.message` field."""


def main() -> None:
    args = create_parser().parse_args()
    header_parse_failures = []
    for directory in args.dirs:
        directory_failures = check_dir(directory=directory, newly_created_files=args.files_added)
        header_parse_failures.extend(directory_failures)
    if header_parse_failures:
        failures = "\n  ".join(str(failure) for failure in header_parse_failures)
        die(
            f"""\
ERROR: All .py files other than __init__.py should start with the header:
{EXPECTED_HEADER}

---

The following {len(header_parse_failures)} file(s) do not conform:
{failures}"""
        )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that all .py files start with the appropriate header.",
    )
    parser.add_argument(
        "dirs",
        nargs="+",
        type=Path,
        help="The directories to check. Will recursively check subdirectories.",
    )
    parser.add_argument(
        "-a",
        "--files-added",
        nargs="*",
        default=[],
        type=Path,
        help="Any passed files will be checked for a current copyright year.",
    )
    return parser


def check_dir(*, directory: Path, newly_created_files: Sequence[Path]) -> List[HeaderCheckFailure]:
    header_parse_failures: List[HeaderCheckFailure] = []
    for fp in directory.rglob("*.py"):
        if fp.name == "__init__.py" or fp.parent in PY2_DIRECTORIES:
            continue
        try:
            check_header(fp, is_newly_created=fp in newly_created_files)
        except HeaderCheckFailure as e:
            header_parse_failures.append(e)
    return header_parse_failures


def check_header(file_path: Path, *, is_newly_created: bool = False) -> None:
    """Raises `HeaderCheckFailure` if the header doesn't match."""
    lines = get_header_lines(file_path)
    check_header_present(file_path, lines)
    check_copyright_year(file_path, copyright_line=lines[0], is_newly_created=is_newly_created)
    check_matches_header(file_path, lines)


def get_header_lines(file_path: Path) -> List[str]:
    try:
        with file_path.open() as f:
            # We grab an extra line in case there is a shebang.
            lines = [f.readline() for _ in range(0, EXPECTED_NUM_LINES + 1)]
    except OSError as e:
        raise HeaderCheckFailure(f"{file_path}: error while reading input ({e!r})")
    # If a shebang line is included, remove it. Otherwise, we will have conservatively grabbed
    # one extra line at the end for the shebang case that is no longer necessary.
    lines.pop(0 if lines[0].startswith("#!") else -1)
    return lines


def check_header_present(file_path: Path, lines: List[str]) -> None:
    num_nonempty_lines = len([line for line in lines if line])
    if num_nonempty_lines < EXPECTED_NUM_LINES:
        raise HeaderCheckFailure(f"{file_path}: missing the expected header")


def check_copyright_year(file_path: Path, *, copyright_line: str, is_newly_created: bool) -> None:
    """Check that copyright is current year if for a new file, else that it's within the current
    century."""
    year = copyright_line[12:16]
    if is_newly_created and year != CURRENT_YEAR:
        raise HeaderCheckFailure(f"{file_path}: copyright year must be {CURRENT_YEAR} (was {year})")
    elif not CURRENT_CENTURY_REGEX.match(year):
        raise HeaderCheckFailure(
            f"{file_path}: copyright year must match '{CURRENT_CENTURY_REGEX.pattern}' (was {year}): "
            + f"current year is {CURRENT_YEAR}"
        )


def check_matches_header(file_path: Path, lines: List[str]) -> None:
    copyright_line = lines[0]
    sanitized_lines = lines.copy()
    sanitized_lines[0] = "# Copyright YYYY" + copyright_line[16:]
    if "".join(sanitized_lines) != EXPECTED_HEADER:
        raise HeaderCheckFailure(f"{file_path}: header does not match the expected header")


if __name__ == "__main__":
    main()
