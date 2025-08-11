# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
import re

from hikaru import load_full_yaml  # pants: no-infer-dep


def remove_comment_only_manifests(manifests: str) -> str:
    """Remove manifests that only contain comment lines and hence cant be parsed by hikaru."""
    all_manifests = re.split(r'(?m)^---\s*$', manifests)
    non_empty_manifests = []
    for manifest in all_manifests:
        # Keep non-empty lines only
        lines = [l for l in manifest.splitlines() if l.strip()]
        if not all(line.startswith("#") for line in lines):
            non_empty_manifests.append(manifest)
    return '\n---\n'.join(non_empty_manifests)


def main(args: list[str]):
    input_filename = args[0]

    found_image_refs: dict[tuple[int, str], str] = {}

    with open(input_filename) as file:
        manifests = remove_comment_only_manifests(manifests=file.read())
        try:
            parsed_docs = load_full_yaml(yaml=manifests)
        except RuntimeError as e:
            # If we couldn't load any hikaru-model packages
            e_str = str(e)
            if "No release packages found" in e_str or "install a hikaru-module package" in e_str:
                raise

            # Hikaru fails with a `RuntimeError` when it finds a K8S manifest for an
            # API version and kind that doesn't understand.
            #
            # We exit the process early without giving any output.
            sys.exit(0)

    for idx, doc in enumerate(parsed_docs):
        entries = doc.find_by_name("image")
        for entry in entries:
            entry_value = doc.object_at_path(entry.path)
            entry_path = "/".join(map(str, entry.path))
            found_image_refs[(idx, entry_path)] = str(entry_value)

    for (idx, path), value in found_image_refs.items():
        print(f"{idx},/{path},{value}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR: Missing file argument", file=sys.stderr)
        print(f"Syntax: {sys.argv[0]} <file>", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1:])
