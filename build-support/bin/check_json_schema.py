# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Check a generated a JSON schema file before uploading it to the JSON schema store
(https://www.schemastore.org/json/).

Live run:

    $ ./pants run build-support/bin/generate_json_schema.py -- --all-help-file=all-help.json
    $ ./pants run build-support/bin/check_json_schema.py -- --schema="pantsbuild-$(./pants version).json"
"""
import argparse
import getpass
import json


def main() -> None:
    args = get_args()
    with open(args.schema) as fh:
        raw_data = fh.read()

    with open(args.schema) as fh:
        json_data = json.load(fh)

    # certain options' default values may be a result of variable expansion
    assert getpass.getuser() not in raw_data

    # there should be some options
    assert json_data["properties"]["GLOBAL"]["properties"]["pants_version"]


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Checks JSON schema file.")
    parser.add_argument(
        "--schema",
        help="Input schema file with the contents produced by the schema generation script.",
        required=True,
    )
    return parser


def get_args():
    return create_parser().parse_args()


if __name__ == "__main__":
    main()
