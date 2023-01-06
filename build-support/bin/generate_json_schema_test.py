# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from unittest.mock import Mock, patch

from generate_json_schema import GENERATED_JSON_SCHEMA_FILENAME, main


def test_main():
    """Test generating a JSON schema using a simplified output of the `./pants help-all` command."""
    cliargs = Mock()
    cliargs.all_help_file = "build-support/bin/json_schema_testdata/all_help_sample_output.json"
    with patch("generate_json_schema.get_args", lambda *args, **kwargs: cliargs):
        main()

    with open(GENERATED_JSON_SCHEMA_FILENAME) as fh:
        schema = json.load(fh)

    assert all((schema["$schema"], schema["description"]))
    collected_properties = schema["properties"]["GLOBAL"]["properties"].keys()
    assert all(
        [
            key in collected_properties
            for key in ["log_show_rust_3rdparty", "ignore_warnings", "level"]
        ]
    )
    assert "process_cleanup" not in collected_properties  # deprecated fields shouldn't be included
