# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
python_sources()
python_distribution(
    name="dummy-plugin-dist",
    provides=python_artifact(
        name="dummy-plugin",
        version="0.0.0",
    ),
    entry_points={
        "pantsbuild.plugin": {
            "dummy-plugin": "plugin.dist",
        },
    },
)
