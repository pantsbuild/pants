# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from unittest.mock import Mock, patch

import pytest
from generate_json_schema import (
    GENERATED_JSON_SCHEMA_FILENAME,
    VERSION_MAJOR_MINOR,
    main,
    simplify_option_description,
)


@pytest.mark.parametrize(
    "description,output",
    [
        (
            "Sentence starts here and ends without a full stop",
            "Sentence starts here and ends without a full stop",
        ),
        ("Sentence starts here and ends here.", "Sentence starts here and ends here"),
        (
            "We run `./pants goal` and stop here, then continue.",
            "We run `./pants goal` and stop here, then continue",
        ),
        (
            "We run `./pants goal` and stop here. After that, we continue.",
            "We run `./pants goal` and stop here",
        ),
        (
            "We run `./pants goal` and then e.g. finish.",
            "We run `./pants goal` and then e.g. finish",
        ),
        (
            "We run `./pants goal` and then stop here.With a missing whitespace after dot, a new sentence starts here.",
            "We run `./pants goal` and then stop here.With a missing whitespace after dot, a new sentence starts here",
        ),
        (
            "Sentence starts here and ends here.\n\nA new sentence goes on in a new paragraph.",
            "Sentence starts here and ends here.\n\nA new sentence goes on in a new paragraph",
        ),
        (
            "Path to a .pypirc config. (https://packaging.python.org/specifications/pypirc/). Set this.",
            "Path to a .pypirc config. (https://packaging.python.org/specifications/pypirc/)",
        ),
        (
            "Use this (4-space indentation). ('AOSP' is the Android Open Source Project.)",
            "Use this (4-space indentation). ('AOSP' is the Android Open Source Project.)",
        ),
    ],
)
def test_simplify_option_description(description: str, output: str) -> None:
    assert simplify_option_description(description) == output


def test_main():
    """Test generating a JSON schema using a simplified output of the `./pants help-all` command."""
    with patch(
        "generate_json_schema.get_args",
        lambda *args, **kwargs: Mock(
            all_help_file="build-support/bin/json_schema_testdata/all_help_sample_output.json"
        ),
    ):
        main()

    with open(GENERATED_JSON_SCHEMA_FILENAME) as fh:
        schema = json.load(fh)

    assert all((schema["$schema"], schema["description"]))
    collected_properties = schema["properties"]["GLOBAL"]["properties"].keys()

    # all options should be included
    assert all(
        key in collected_properties
        for key in ["log_show_rust_3rdparty", "ignore_warnings", "level"]
    )
    # deprecated fields shouldn't be included
    assert "process_cleanup" not in collected_properties

    # an option description should be a single sentence with a URL to the option docs section
    assert schema["properties"]["GLOBAL"]["properties"]["level"]["description"] == (
        f"Set the logging level\nhttps://www.pantsbuild.org/v{VERSION_MAJOR_MINOR}/docs/reference-global#level"
    )

    # options should be part of the enum
    # TODO(alte): ensure enum is sorted once implemented
    assert set(schema["properties"]["GLOBAL"]["properties"]["level"]["enum"]) == {
        "trace",
        "debug",
        "info",
        "warn",
        "error",
    }
