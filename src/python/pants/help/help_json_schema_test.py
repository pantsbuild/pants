# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

import pytest

from pants.help.help_json_schema import VERSION_MAJOR_MINOR, simplify_option_description
from pants.help.help_printer import HelpPrinter


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


def test_get_json_schema():
    sample_all_help_output = {
        "scope_to_help_info": {
            "": {
                "advanced": [
                    {
                        "choices": None,
                        "comma_separated_choices": None,
                        "comma_separated_display_args": "--[no-]log-show-rust-3rdparty",
                        "config_key": "log_show_rust_3rdparty",
                        "default": False,
                        "deprecated_message": None,
                        "deprecation_active": False,
                        "display_args": ["--[no-]log-show-rust-3rdparty"],
                        "env_var": "PANTS_LOG_SHOW_RUST_3RDPARTY",
                        "fromfile": False,
                        "help": "Whether to show/hide logging done by 3rdparty Rust crates used by the Pants engine.",
                        "removal_hint": None,
                        "removal_version": None,
                        "scoped_cmd_line_args": [
                            "--log-show-rust-3rdparty",
                            "--no-log-show-rust-3rdparty",
                        ],
                        "target_field_name": None,
                        "typ": "bool",
                        "unscoped_cmd_line_args": [
                            "--log-show-rust-3rdparty",
                            "--no-log-show-rust-3rdparty",
                        ],
                        "value_history": {
                            "ranked_values": [
                                {"details": None, "rank": "NONE", "value": None},
                                {"details": None, "rank": "HARDCODED", "value": False},
                            ]
                        },
                    },
                    {
                        "choices": None,
                        "comma_separated_choices": None,
                        "comma_separated_display_args": "--ignore-warnings=\"['<str>', '<str>', ...]\"",
                        "config_key": "ignore_warnings",
                        "default": [],
                        "deprecated_message": None,
                        "deprecation_active": False,
                        "display_args": ["--ignore-warnings=\"['<str>', '<str>', ...]\""],
                        "env_var": "PANTS_IGNORE_WARNINGS",
                        "fromfile": False,
                        "help": "Ignore logs and warnings matching these strings.\n\nNormally, Pants will look for literal matches from the start of the log/warning message, but you can prefix the ignore with `$regex$` for Pants to instead treat your string as a regex pattern. For example:\n\n    ignore_warnings = [\n        \"DEPRECATED: option 'config' in scope 'flake8' will be removed\",\n        '$regex$:No files\\s*'\n    ]",
                        "removal_hint": None,
                        "removal_version": None,
                        "scoped_cmd_line_args": ["--ignore-warnings"],
                        "target_field_name": None,
                        "typ": "list",
                        "unscoped_cmd_line_args": ["--ignore-warnings"],
                        "value_history": {
                            "ranked_values": [
                                {"details": "", "rank": "NONE", "value": []},
                                {"details": "", "rank": "HARDCODED", "value": []},
                            ]
                        },
                    },
                ],
                "basic": [
                    {
                        "choices": ["trace", "debug", "info", "warn", "error"],
                        "comma_separated_choices": "trace, debug, info, warn, error",
                        "comma_separated_display_args": "-l=<LogLevel>, --level=<LogLevel>",
                        "config_key": "level",
                        "default": "info",
                        "deprecated_message": None,
                        "deprecation_active": False,
                        "display_args": ["-l=<LogLevel>", "--level=<LogLevel>"],
                        "env_var": "PANTS_LEVEL",
                        "fromfile": False,
                        "help": "Set the logging level.",
                        "removal_hint": None,
                        "removal_version": None,
                        "scoped_cmd_line_args": ["-l", "--level"],
                        "target_field_name": None,
                        "typ": "LogLevel",
                        "unscoped_cmd_line_args": ["-l", "--level"],
                        "value_history": {
                            "ranked_values": [
                                {"details": None, "rank": "NONE", "value": None},
                                {"details": None, "rank": "HARDCODED", "value": "info"},
                            ]
                        },
                    }
                ],
                "deprecated": [
                    {
                        "choices": None,
                        "comma_separated_choices": None,
                        "comma_separated_display_args": "--[no-]process-cleanup",
                        "config_key": "process_cleanup",
                        "default": True,
                        "deprecated_message": "Deprecated, is scheduled to be removed in version: 3.0.0.dev0.",
                        "deprecation_active": True,
                        "display_args": ["--[no-]process-cleanup"],
                        "env_var": "PANTS_PROCESS_CLEANUP",
                        "fromfile": False,
                        "help": "\nIf false, Pants will not clean up local directories used as chroots for running processes. Pants will log their location so that you can inspect the chroot, and run the `__run.sh` script to recreate the process using the same argv and environment variables used by Pants. This option is useful for debugging.",
                        "removal_hint": "Use the `keep_sandboxes` option instead.",
                        "removal_version": "3.0.0.dev0",
                        "scoped_cmd_line_args": ["--process-cleanup", "--no-process-cleanup"],
                        "target_field_name": None,
                        "typ": "bool",
                        "unscoped_cmd_line_args": ["--process-cleanup", "--no-process-cleanup"],
                        "value_history": {
                            "ranked_values": [
                                {"details": None, "rank": "NONE", "value": None},
                                {"details": None, "rank": "HARDCODED", "value": True},
                            ]
                        },
                    }
                ],
                "deprecated_scope": None,
                "description": "Options to control the overall behavior of Pants.",
                "is_goal": False,
                "provider": "pants.core",
                "scope": "",
            }
        }
    }
    schema = HelpPrinter._get_json_schema(json.dumps(sample_all_help_output))
    assert schema["$schema"]
    assert schema["description"]

    # all options should be included
    collected_properties = schema["properties"]["GLOBAL"]["properties"].keys()
    assert all(
        [
            key in collected_properties
            for key in ["log_show_rust_3rdparty", "ignore_warnings", "level"]
        ]
    )

    # deprecated fields shouldn't be included
    assert "process_cleanup" not in collected_properties

    # an option description should be a single sentence with a URL to the option docs section
    assert schema["properties"]["GLOBAL"]["properties"]["level"]["description"] == (
        f"Set the logging level\nhttps://www.pantsbuild.org/v{VERSION_MAJOR_MINOR}/docs/reference-global#level"
    )

    # options should be part of the enum
    # TODO(alte): ensure enum is sorted once implemented
    assert sorted(schema["properties"]["GLOBAL"]["properties"]["level"]["enum"]) == [
        "debug",
        "error",
        "info",
        "trace",
        "warn",
    ]
