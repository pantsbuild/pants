# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Generates a JSON schema file to be uploaded to the JSON schema store
(https://www.schemastore.org/json/). The schema file is used by IDEs (PyCharm, VSCode, etc) to
provide intellisense when editing Pants configuration files in TOML format. It can also be used to
validate your pants.toml configuration file programmatically.

Live run:

    $ ./pants help-all > all-help.json
    $ ./pants run build-support/bin/generate_json_schema.py -- --all-help-file=all-help.json
"""
import argparse
import itertools
import json
from typing import Any, Dict, Iterable

from pants.version import VERSION

GENERATED_JSON_SCHEMA_FILENAME = f"pantsbuild-{VERSION}.json"

PYTHON_TO_JSON_TYPE_MAPPING = {
    "str": "string",
    "bool": "boolean",
    "list": "array",
    "int": "number",
    "float": "number",
    "dict": "object",
}


def build_scope_properties(ruleset: dict, options: Iterable[dict], scope: str) -> dict:
    """Build properties object for a single scope.

    There are custom types (e.g. `file_option` or `LogLevel`) for which one cannot safely infer a
    type, so no type is added to the ruleset. If there are choices, there is no need to provide
    "type" for the schema (assuming all choices share the same type). Otherwise, a provided `typ`
    field is used.
    """
    for option in options:
        properties = ruleset[scope]["properties"]

        properties[option["config_key"]] = {
            "description": option["help"],
            "default": option["default"],
        }
        if option["choices"]:
            properties[option["config_key"]]["enum"] = option["choices"]
        else:
            typ = PYTHON_TO_JSON_TYPE_MAPPING.get(option["typ"])
            if typ:
                properties[option["config_key"]]["type"] = typ

    return ruleset


def main() -> None:
    args = get_args()
    with open(args.all_help_file) as fh:
        all_help = json.load(fh)["scope_to_help_info"]

    # set GLOBAL scope that is declared under an empty string
    all_help["GLOBAL"] = all_help[""]
    del all_help[""]

    # build ruleset for all scopes (where "scope" is a [section]
    # in the pants.toml configuration file such as "pytest" or "mypy")
    ruleset = {}
    for scope, options in all_help.items():
        ruleset[scope] = {
            "description": all_help[scope]["description"],
            "type": "object",
            "properties": {},
        }
        ruleset = build_scope_properties(
            ruleset=ruleset,
            options=itertools.chain(options["basic"], options["advanced"]),
            scope=scope,
        )

    schema: Dict[str, Any] = dict()
    schema["$schema"] = "http://json-schema.org/draft-04/schema#"
    schema["description"] = "https://www.pantsbuild.org/"
    schema["properties"] = ruleset

    with open(GENERATED_JSON_SCHEMA_FILENAME, "w") as fh:
        fh.write(json.dumps(schema, indent=4))


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generates JSON schema file to be used in IDEs for Pants configuration files in TOML format."
    )
    parser.add_argument(
        "--all-help-file",
        help="Input file with the contents produced by the `./pants help-all` command.",
        required=True,
    )
    return parser


def get_args():
    return create_parser().parse_args()


if __name__ == "__main__":
    main()
