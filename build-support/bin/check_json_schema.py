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

    # there should be some options
    assert json_data["properties"]["GLOBAL"]["properties"]["pants_version"]

    # certain options' default values may be a result of variable expansion
    username = getpass.getuser()
    if username in raw_data:
        raise ValueError(f"{username} is in the schema file.")

    for section_name, section_data in json_data["properties"].items():
        for option_name, option_data in section_data["properties"].items():
            # every property description should contain some text before the URL
            if option_data["description"].startswith("\nhttp"):
                raise ValueError(f"{option_name} has an incomplete description.")

            # every option's description should contain a URL
            if "https://www.pantsbuild.org/v" not in option_data["description"]:
                raise ValueError(f"{option_name} should have a URL in description.")


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
