# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

from hikaru import load_full_yaml  # pants: no-infer-dep
from hikaru.crd import register_crd_class  # pants: no-infer-dep


def _import_crd_source():
    """Dynamically import the CRD source module."""
    try:
        import importlib

        crd_module = importlib.import_module("__crd_source")
        return getattr(crd_module, "CRD", None)
    except ImportError as e:
        print(f"Error: Failed to import CRD module: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to register CRD: {e}", file=sys.stderr)
        sys.exit(1)


def main(args: list[str]):
    crd = args[1] if len(args) > 1 else None
    if crd != "":
        crd_class = _import_crd_source()
        if crd_class is None:
            print("Error: CRD class not found in __crd_source.", file=sys.stderr)
            sys.exit(1)
        register_crd_class(crd_class, "crd", is_namespaced=False)

    input_filename = args[0]

    found_image_refs: dict[tuple[int, str], str] = {}

    with open(input_filename) as file:
        try:
            parsed_docs = load_full_yaml(stream=file)
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
