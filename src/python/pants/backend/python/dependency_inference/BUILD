# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={
        "parse_python_imports.py": {
            # This Python script is loaded as a resource, see parse_python_imports.py for more info.
            "dependencies": ["./scripts:import_parser"]
        }
    }
)

python_tests(
    name="tests",
    overrides={"parse_python_imports_test.py": {"timeout": 120}},
)
