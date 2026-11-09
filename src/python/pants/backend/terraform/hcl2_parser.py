# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from pathlib import PurePath
from typing import Set

#
# Note: This file is used as a pex entry point in the execution sandbox.
#

# Printed to stderr when the installed python-hcl2 is older than 8.0, so that Pants can warn that
# support for it is deprecated.
LEGACY_HCL2_MARKER = b"__pants_legacy_python_hcl2__"


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
    import hcl2  # type: ignore[import-not-found]  # pants: no-infer-dep

    content = raw_content.decode("utf-8")
    if hasattr(hcl2, "SerializationOptions"):
        # python-hcl2 keeps the quotes around string values (e.g. `"./foo"`) unless asked to strip
        # them.
        parsed_content = hcl2.loads(
            content, serialization_options=hcl2.SerializationOptions(strip_string_quotes=True)
        )
    else:
        # TODO: Remove support for python-hcl2 < 8.0 in Pants 2.35.0.dev0, along with the warning in
        # `main`. Those versions have no `SerializationOptions`, and strip the quotes around string
        # values themselves.
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
    import hcl2  # pants: no-infer-dep

    # TODO: Remove in Pants 2.35.0.dev0, along with the fallback in `extract_module_source_paths`.
    if not hasattr(hcl2, "SerializationOptions"):
        sys.stderr.buffer.write(LEGACY_HCL2_MARKER + b"\n")

    paths = set()
    for filename in args:
        with open(filename, "rb") as f:
            content = f.read()
        paths |= extract_module_source_paths(PurePath(filename).parent, content)

    for path in paths:
        print(path)


if __name__ == "__main__":
    main(sys.argv[1:])
