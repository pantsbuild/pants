# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
from yamlpath import Processor  # pants: no-infer-dep
from yamlpath.common import Parsers  # pants: no-infer-dep
from yamlpath.exceptions import YAMLPathException  # pants: no-infer-dep
from yamlpath.wrappers import ConsolePrinter  # pants: no-infer-dep

_SOURCE_FILENAME_PREFIX = "# Source: "


def build_template_map(input_file: str) -> dict[str, list[str]]:
    result = defaultdict(list)
    template_files = []
    with open(input_file, "r", encoding="utf-8") as f:
        template_files = f.read().split("---")

    for template in template_files:
        lines = [line for line in template.splitlines() if line and len(line) > 0]
        if not lines:
            continue

        template_name = lines[0][len(_SOURCE_FILENAME_PREFIX) :]
        result[template_name].append("\n".join(lines[1:]))

    return result


def dump_yaml_data(yaml: YAML, data: Any) -> str:
    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def output_templates(templates: dict[str, list[str]]) -> None:
    if not templates:
        return

    for filename, documents in templates.items():
        for content in documents:
            print("---")
            print(f"{_SOURCE_FILENAME_PREFIX}{filename}")
            print(content)


def main(args: list[str]) -> None:
    cfg_file = args[0]
    templates_file = args[1]

    logging_args = SimpleNamespace(quiet=True, verbose=False, debug=False)
    log = ConsolePrinter(logging_args)

    yaml = Parsers.get_yaml_editor(explicit_start=False, preserve_quotes=False)

    input_template_map = build_template_map(templates_file)
    output_template_map: dict[str, list[str]] = defaultdict(list)

    (cfg_yaml, doc_loaded) = Parsers.get_yaml_data(yaml, log, cfg_file)
    if not doc_loaded:
        exit(1)

    # Go through the items in the configuration file and apply the replacements requested
    for filename, doc_changes_list in cfg_yaml.items():
        file_contents = input_template_map.get(filename)
        if not file_contents:
            continue

        for document, doc_change_spec in zip(file_contents, doc_changes_list):
            doc_change_paths = doc_change_spec["paths"]
            if not doc_change_paths:
                output_template_map[filename].append(document)
                continue

            (document_yaml, doc_loaded) = Parsers.get_yaml_data(yaml, log, document, literal=True)
            if not doc_loaded:
                continue

            processor = Processor(log, document_yaml)
            for path_spec, replacement in doc_change_paths.items():
                try:
                    processor.set_value(path_spec, replacement)
                except YAMLPathException as ex:
                    log.critical(ex, 119)

            output_template_map[filename].append(dump_yaml_data(yaml, document_yaml))

    output_templates(output_template_map)


if __name__ == "__main__":
    main(sys.argv[1:])
