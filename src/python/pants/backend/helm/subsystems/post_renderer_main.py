# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from ruamel.yaml import YAML  # pants: no-infer-dep
from ruamel.yaml.compat import StringIO  # pants: no-infer-dep
from yamlpath import Processor  # pants: no-infer-dep
from yamlpath.common import Parsers  # pants: no-infer-dep
from yamlpath.exceptions import YAMLPathException  # pants: no-infer-dep
from yamlpath.wrappers import ConsolePrinter  # pants: no-infer-dep

_SOURCE_FILENAME_PREFIX = "# Source: "


def build_manifest_map(input_file: str) -> dict[str, list[str]]:
    """Parses the contents that are being received from Helm.

    Helm will send us input that follows the following format:

    ```yaml
    ---
    # Source: filename.yaml
    data:
      key: value
    ```

    Since there are cases in which the same source may produce more than
    one YAML structure, the returned type represents this with a dictionary
    of lists, in which the key is the source filename and each item in the list
    is the content following the `# Source: ...` header.
    """

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


def print_manifests(templates: dict[str, list[str]]) -> None:
    """Outputs to standard out the contents of the different manifests following the same format
    used by Helm when sending them into us."""

    if not templates:
        return

    for filename, documents in templates.items():
        for content in documents:
            print("---")
            print(f"{_SOURCE_FILENAME_PREFIX}{filename}")
            print(content)


def main(args: list[str]) -> None:
    cfg_file = args[0]
    manifests_stdin_file = args[1]

    logging_args = SimpleNamespace(quiet=True, verbose=False, debug=False)
    log = ConsolePrinter(logging_args)

    yaml = Parsers.get_yaml_editor(explicit_start=False, preserve_quotes=False)

    input_manifest_map = build_manifest_map(manifests_stdin_file)
    output_manifest_map: dict[str, list[str]] = defaultdict(list)

    # `cfg_yaml` is the data structure parsed from the YAML index built while preparing this
    # post-renderer instance.
    (cfg_yaml, doc_loaded) = Parsers.get_yaml_data(yaml, log, cfg_file)
    if not doc_loaded:
        exit(1)

    # Go through the items in the configuration file and apply the replacements requested.
    for source_filename, source_changes_list in cfg_yaml.items():
        input_manifests = input_manifest_map.get(source_filename)
        if not input_manifests:
            continue

        for input_manifest, manifest_change_spec in zip(input_manifests, source_changes_list):
            manifest_change_paths = manifest_change_spec["paths"]

            # Manifests that require no changes will have an empty `paths` element in the change spec,
            # so we add to the output map the manifest document unchanged.
            if not manifest_change_paths:
                output_manifest_map[source_filename].append(input_manifest)
                continue

            (manifest_yaml, doc_loaded) = Parsers.get_yaml_data(
                yaml, log, input_manifest, literal=True
            )
            if not doc_loaded:
                continue

            processor = Processor(log, manifest_yaml)
            for path_spec, replacement in manifest_change_paths.items():
                try:
                    processor.set_value(path_spec, replacement)
                except YAMLPathException as ex:
                    log.critical(ex, 119)

            output_manifest_map[source_filename].append(dump_yaml_data(yaml, manifest_yaml))

    # Include in the output the files that didn't require any replacement
    remaining_files = set(input_manifest_map.keys()) - set(output_manifest_map.keys())
    for remaining_file in remaining_files:
        input_file = input_manifest_map.get(remaining_file)
        if input_file:
            output_manifest_map[remaining_file] = input_file

    print_manifests(output_manifest_map)


if __name__ == "__main__":
    main(sys.argv[1:])
