# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
from yamlpath import Processor  # pants: no-infer-dep
from yamlpath.common import Parsers  # pants: no-infer-dep
from yamlpath.exceptions import YAMLPathException  # pants: no-infer-dep
from yamlpath.wrappers import ConsolePrinter  # pants: no-infer-dep

_SOURCE_FILENAME_PREFIX = "# Source: "


def build_template_map(input_file: str) -> dict[str, str]:
    result = {}
    template_files = []
    with open(input_file, "r", encoding="utf-8") as f:
        template_files = f.read().split("---")

    for template in template_files:
        lines = [line for line in template.splitlines() if line and len(line) > 0]
        if not lines:
            continue

        template_name = lines[0][len(_SOURCE_FILENAME_PREFIX) :]
        # We need to strip out the header of the YAML file so we can render it properly later
        if len(lines) > 1:
            result[template_name] = "\n".join(lines[1:])
        else:
            result[template_name] = "\n"

    return result


def dump_yaml_data(yaml: YAML, data: Any) -> str:
    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def output_templates(templates: dict[str, str]) -> None:
    if not templates:
        return

    for filename, content in templates.items():
        print("---")
        print(f"{_SOURCE_FILENAME_PREFIX}{filename}")
        print(content)


def main(args: list[str]) -> None:
    cfg_file = args[0]
    templates_file = args[1]

    logging_args = SimpleNamespace(quiet=True, verbose=False, debug=False)
    log = ConsolePrinter(logging_args)

    yaml = Parsers.get_yaml_editor(explicit_start=False, preserve_quotes=False)

    template_map = build_template_map(templates_file)

    (cfg_data, doc_loaded) = Parsers.get_yaml_data(yaml, log, cfg_file)
    if not doc_loaded:
        exit(1)

    # Go through the items in the configuration file and apply the replacements requested
    for filename, changes in cfg_data.items():
        file_contents = template_map.get(filename)
        if not file_contents:
            continue

        (template_data, doc_loaded) = Parsers.get_yaml_data(yaml, log, file_contents, literal=True)
        if not doc_loaded:
            continue

        processor = Processor(log, template_data)
        for path_spec, replacement in changes.items():
            try:
                processor.set_value(path_spec, replacement)
            except YAMLPathException as ex:
                log.critical(ex, 119)

        template_map[filename] = dump_yaml_data(yaml, template_data)

    output_templates(template_map)


if __name__ == "__main__":
    main(sys.argv[1:])
