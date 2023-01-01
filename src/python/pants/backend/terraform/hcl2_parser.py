# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from pathlib import PurePath
from typing import Set

#
# Note: This file is used as an pex entry point in the execution sandbox.
#


# PurePath does not have the Path.resolve method which resolves ".." components, thus we need to
# code our own version for PurePath's.
def resolve_pure_path(base: PurePath, relative_path: PurePath) -> PurePath:
    parts = list(base.parts)
    for component in relative_path.parts:
        if component == ".":
            pass
        elif component == "..":
            if not parts:
                raise ValueError(f"Relative path {relative_path} escapes from path {base}.")
            parts.pop()
        else:
            parts.append(component)

    return PurePath(*parts)


def extract_module_source_paths(path: PurePath, raw_content: bytes) -> Set[str]:
    # Import here so we can still test this file with pytest (since `hcl2` is not present in
    # normal Pants venv.)
    import hcl2  # type: ignore[import]  # pants: no-infer-dep

    content = raw_content.decode("utf-8")
    parsed_content = hcl2.loads(content)

    # Note: The `module` key is a list where each entry is a dict with a single entry where the key is the
    # module name and the values are a dict for that module's actual values.
    paths = set()
    for wrapped_module in parsed_content.get("module", []):
        values = list(wrapped_module.values())[
            0
        ]  # the module is the sole entry in `wrapped_module`
        source = values.get("source", "")

        # Local paths to modules must begin with "." or ".." as per
        # https://www.terraform.io/docs/language/modules/sources.html#local-paths.
        if source.startswith("./") or source.startswith("../"):
            try:
                resolved_path = resolve_pure_path(path, PurePath(source))
                paths.add(str(resolved_path))
            except ValueError:
                pass

    return paths


def main(args):
    paths = set()
    for filename in args:
        with open(filename, "rb") as f:
            content = f.read()
        paths |= extract_module_source_paths(PurePath(filename).parent, content)

    for path in paths:
        print(path)


if __name__ == "__main__":
    main(sys.argv[1:])
