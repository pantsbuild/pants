#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import tokenize
from difflib import unified_diff
from io import BytesIO
from pathlib import Path
from token import NAME, OP
from typing import Dict, List, Optional, Set


def main() -> None:
    args = create_parser().parse_args()
    build_files: Set[Path] = set(
        fp
        for folder in args.folders
        for fp in [*folder.rglob("BUILD"), *folder.rglob("BUILD.*")]
        # Check that it really is a BUILD file
        if fp.is_file() and fp.stem == "BUILD"
    )
    updates: Dict[Path, List[str]] = {}
    for build in build_files:
        possibly_new_build = maybe_rewrite_build(build)
        if possibly_new_build is not None:
            updates[build] = possibly_new_build
    for build, new_content in updates.items():
        if args.preview:
            print(generate_diff(build, new_content))
        else:
            build.write_text("\n".join(new_content) + "\n")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert deprecated `source` fields to `sources`.",
    )
    parser.add_argument(
        "folders", type=Path, nargs="+", help="Folders to recursively search for `BUILD` files",
    )
    parser.add_argument(
        "-p",
        "--preview",
        action="store_true",
        help="Output to stdout rather than overwriting BUILD files.",
    )
    return parser


def maybe_rewrite_line(line: str) -> Optional[str]:
    try:
        tokens = list(tokenize.tokenize(BytesIO(line.encode()).readline))
    except tokenize.TokenError:
        return None
    source_field = next(
        (token for token in tokens if token.type is NAME and token.string == "source"), None
    )
    if not source_field:
        return None
    source_field_index = tokens.index(source_field)

    # Ensure that the next token is `=`
    if (
        tokens[source_field_index + 1].type is not OP
        and tokens[source_field_index + 1].string != "="
    ):
        return None

    source_value = tokens[source_field_index + 2]

    prefix = line[: source_field.start[1]]
    interfix = line[source_field.end[1] : source_value.start[1]]
    suffix = line[source_value.end[1] :]
    return f"{prefix}sources{interfix}[{source_value.string}]{suffix}"


def maybe_rewrite_build(build_file: Path) -> Optional[List[str]]:
    original_text = build_file.read_text()
    original_text_lines = original_text.splitlines()
    updated_text_lines = original_text_lines.copy()
    # import ipdb;
    # ipdb.set_trace()
    for i, line in enumerate(original_text_lines):
        maybe_new_line = maybe_rewrite_line(line)
        if maybe_new_line is not None:
            updated_text_lines[i] = maybe_new_line
    return updated_text_lines if updated_text_lines != original_text_lines else None


def generate_diff(build_file: Path, new_content: List[str]) -> str:
    def green(s: str) -> str:
        return f"\x1b[32m{s}\x1b[0m"

    def red(s: str) -> str:
        return f"\x1b[31m{s}\x1b[0m"

    diff = unified_diff(
        build_file.read_text().splitlines(),
        new_content,
        fromfile=str(build_file),
        tofile=str(build_file),
    )
    msg = ""
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            msg += green(line)
        elif line.startswith("-") and not line.startswith("---"):
            msg += red(line)
        else:
            msg += line
        if not (line.startswith("+++") or line.startswith("---") or line.startswith("@@ ")):
            msg += "\n"
    return msg


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
