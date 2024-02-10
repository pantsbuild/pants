#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""A script to automatically convert an INI Pants config file to TOML. There will still likely be
some issues remaining which require manual fixes, but this script will automate most of the tedium.

Run `python3 migrate_to_toml_config.py --help`.
"""

import argparse
import logging
import re
from pathlib import Path
from typing import Dict, List


def main() -> None:
    args = create_parser().parse_args()
    updates: Dict[Path, List[str]] = {}
    for config in args.files:
        if config.suffix not in [".ini", ".cfg"]:
            logging.warning(f"This script may only be run on INI files. Skipping {config}.")
            continue
        new_path = Path(config.parent, f"{config.stem}.toml")
        if new_path.exists():
            logging.warning(f"{new_path} already exists. Skipping conversion of {config}.")
            continue
        new_config_content = generate_new_config(config)
        updates[new_path] = new_config_content
    for new_path, new_content in updates.items():
        joined_new_content = "\n".join(new_content) + "\n"
        if args.preview:
            print(f"Would create {new_path} with the following content:\n\n{joined_new_content}")
        else:
            logging.info(
                f"Created {new_path}. There are likely some remaining issues that need manual "
                "attention. Please copy the file into https://www.toml-lint.com or open with your editor "
                "to fix any remaining issues."
            )
            new_path.write_text(joined_new_content)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert INI config files to TOML config files.")
    parser.add_argument("files", type=Path, nargs="*", help="Config files to convert.")
    parser.add_argument(
        "-p",
        "--preview",
        action="store_true",
        help="Output to stdout rather than creating the new TOML config file(s).",
    )
    return parser


def update_primitive_value(original: str) -> str:
    if original in ["true", "True"]:
        return "true"
    if original in ["false", "False"]:
        return "false"

    try:
        return str(int(original))
    except ValueError:
        pass

    try:
        return str(float(original))
    except ValueError:
        pass

    return f'"{original}"'


def generate_new_config(config: Path) -> List[str]:
    original_text = config.read_text()
    original_text_lines = original_text.splitlines()
    updated_text_lines = original_text_lines.copy()

    for i, line in enumerate(original_text_lines):
        option_regex = r"(?P<option>[a-zA-Z0-9_]+)"
        before_value_regex = rf"\s*{option_regex}\s*[:=]\s*"
        valid_value_characters = r"a-zA-Z0-9_.@!:%\*\=\>\<\-\(\)\/"
        value_regex = rf"(?P<value>[{valid_value_characters}]+)"
        parsed_line = re.match(rf"{before_value_regex}{value_regex}\s*$", line)

        if parsed_line:
            option, value = parsed_line.groups()
            updated_text_lines[i] = f"{option} = {update_primitive_value(value)}"
            continue

        # Check if it's a one-line list value
        list_value_regex = rf"(?P<list>[\+\-]?\[[{valid_value_characters},\s\'\"]*\])"
        parsed_list_line = re.match(rf"{before_value_regex}{list_value_regex}\s*$", line)
        if parsed_list_line:
            option, value = parsed_list_line.groups()
            if value.startswith("+"):
                updated_line = f"{option}.add = {value[1:]}"
            elif value.startswith("-"):
                updated_line = f"{option}.remove = {value[1:]}"
            else:
                updated_line = f"{option} = {value}"
            updated_text_lines[i] = updated_line
            continue

        # Check if it's a one-line dict value
        dict_value_regex = rf"(?P<dict>{{[{valid_value_characters},:\s\'\"]*}})"
        parsed_dict_line = re.match(rf"{before_value_regex}{dict_value_regex}\s*$", line)
        if parsed_dict_line:
            option, value = parsed_dict_line.groups()
            updated_text_lines[i] = f'{option} = """{value}"""'
            continue

    return updated_text_lines


if __name__ == "__main__":
    logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)
    try:
        main()
    except KeyboardInterrupt:
        pass
