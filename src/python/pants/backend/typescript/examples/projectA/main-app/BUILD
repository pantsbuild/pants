# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
package_json(
    scripts=[
        node_build_script(entry_point="build", output_directories=["dist"]),
        node_test_script(entry_point="test"),
    ],
    dependencies=[":tsconfig"],
)

file(name="tsconfig", source="tsconfig.json")
