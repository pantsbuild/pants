# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
from typing import Any, Iterable

from packaging.version import Version

from pants.version import VERSION

GENERATED_JSON_SCHEMA_FILENAME = f"pantsbuild-{VERSION}.json"
DOCS_URL = "https://www.pantsbuild.org"
VERSION_MAJOR_MINOR = f"{Version(VERSION).major}.{Version(VERSION).minor}"

PYTHON_TO_JSON_TYPE_MAPPING = {
    "str": "string",
    "bool": "boolean",
    "list": "array",
    "int": "number",
    "float": "number",
    "dict": "object",
}

# Certain default values will be expanded using local runtime environment which is undesirable.
# This list may need to be extended as more options with environment specific default values are added.
ENV_SPECIFIC_OPTION_DEFAULTS = {
    "pants_config_files": ["<buildroot>/pants.toml"],
    "pants_subprocessdir": "<buildroot>/.pids",
    "pants_distdir": "<buildroot>/dist",
    "pants_workdir": "<buildroot>/.pants.d",
    "local_store_dir": "$XDG_CACHE_HOME/lmdb_store",
    "named_caches_dir": "$XDG_CACHE_HOME/named_caches",
}


def simplify_option_description(description: str) -> str:
    """Take only a first sentence out of a multi-sentence description without a final full stop.

    There is an assumption that there are no newlines.
    """
    return re.split(r"(?<=[^A-Z].[.?]) +(?=[A-Z])", description)[0].rstrip(".")


def get_description(option: dict, section: str) -> str:
    """Get a shortened description with a URL to the online docs of the given option."""
    option_help: str = option["help"].lstrip("\n").split("\n")[0]
    option_name: str = option["config_key"]
    simplified_option_help = simplify_option_description(option_help)
    url = f"{DOCS_URL}/v{VERSION_MAJOR_MINOR}/docs/reference-{section.lower()}#{option_name}"
    return f"{simplified_option_help}\n{url}"


def get_default(option: dict) -> Any:
    """Get default value for an option.

    Ensure options that depend on any machine specific environment are properly handled. E.g.
    `"default": "<buildroot>/.pants.d"` will be expanded to the
    `"default": "/home/your-user.name/code/pants/.pants.d"`
    which is not what one want to have in a schema.
    """
    return ENV_SPECIFIC_OPTION_DEFAULTS.get(option["config_key"], option["default"])


def build_scope_properties(ruleset: dict, options: Iterable[dict], scope: str) -> dict:
    """Build properties object for a single scope.

    There are custom types (e.g. `file_option` or `LogLevel`) for which one cannot safely infer a
    type, so no type is added to the ruleset. If there are choices, there is no need to provide
    "type" for the schema (assuming all choices share the same type). If an option value can be
    loaded from a file, a union of `string` and option's `typ` is used. Otherwise, a provided `typ`
    field is used.
    """
    for option in options:
        properties = ruleset[scope]["properties"]

        properties[option["config_key"]] = {
            "description": get_description(option, scope),
            "default": get_default(option),
        }
        if option["choices"]:
            # TODO(alte): find a safe way to sort choices
            properties[option["config_key"]]["enum"] = option["choices"]
        else:
            typ = PYTHON_TO_JSON_TYPE_MAPPING.get(option["typ"])
            # TODO(alte): do we want to maintain a mapping between special options?
            #  `process_total_child_memory_usage` ("typ": "memory_size") -> "int"
            #  `engine_visualize_to` ("typ": "dir_option") -> "str"
            if typ:
                # options may allow providing value inline or loading from a filepath string
                if option.get("fromfile"):
                    properties[option["config_key"]]["oneOf"] = [{"type": typ}, {"type": "string"}]
                else:
                    properties[option["config_key"]]["type"] = typ

                # TODO(alte): see if one safely codify in the schema the fact that we support `.add` and `.remove`
                #  semantics on arrays; e.g. `extra_requirements.add` can either be an array or an object
                #  {add|remove: array}
    return ruleset
