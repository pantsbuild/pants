#!/usr/bin/env python3
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A script to rename targets in BUILD files to their new names.

Run `./rename_targets_pants28.py --help`.
"""

import argparse
import tokenize
from difflib import unified_diff
from io import BytesIO
from pathlib import Path
from token import NAME, OP

RENAMES = {
    "python_requirement_library": "python_requirement",
    "python_library": "python_sources",
    "protobuf_library": "protobuf_sources",
    "shell_library": "shell_sources",
}


def main() -> None:
    args = create_parser().parse_args()
    build_files = set(
        fp
        for folder in args.folders
        for fp in [*folder.rglob("BUILD"), *folder.rglob("BUILD.*")]
        # Check that it really is a BUILD file
        if fp.is_file() and fp.stem == "BUILD"
    )

    updates = {}
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
    parser = argparse.ArgumentParser(description="Rename deprecated target names in BUILD files.")
    parser.add_argument(
        "folders", type=Path, nargs="+", help="Folders to recursively search for `BUILD` files"
    )
    parser.add_argument(
        "-p",
        "--preview",
        action="store_true",
        help="Output to stdout rather than overwriting BUILD files.",
    )
    return parser


def maybe_rewrite_build(build_file: Path) -> list[str] | None:
    original_text = build_file.read_text()
    original_text_lines = original_text.splitlines()
    try:
        all_tokens = list(tokenize.tokenize((BytesIO(original_text.encode()).readline)))
    except tokenize.TokenError:
        return None

    def should_be_renamed(token: tokenize.TokenInfo) -> bool:
        no_indentation = token.start[1] == 0
        if not (token.type is NAME and token.string in RENAMES and no_indentation):
            return False
        # Ensure that the next token is `(`
        try:
            next_token = all_tokens[all_tokens.index(token) + 1]
        except IndexError:
            return False
        return next_token.type is OP and next_token.string == "("

    updated_text_lines = original_text_lines.copy()
    for token in all_tokens:
        if not should_be_renamed(token):
            continue
        line_index = token.start[0] - 1
        line = original_text_lines[line_index]
        suffix = line[token.end[1] :]
        new_symbol = RENAMES[token.string]
        updated_text_lines[line_index] = f"{new_symbol}{suffix}"

    return updated_text_lines if updated_text_lines != original_text_lines else None


def generate_diff(build_file: Path, new_content: list[str]) -> str:
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
