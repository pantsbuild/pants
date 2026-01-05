# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

package_json(
    scripts=[
        node_build_script(entry_point="build", output_directories=["dist"]),
        node_test_script(),
    ],
    dependencies=[":tsconfig", ":babel_config"],
)

file(name="tsconfig", source="tsconfig.json")
file(name="babel_config", source="babel.config.json")
