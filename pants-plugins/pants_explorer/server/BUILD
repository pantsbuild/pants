# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_requirements(
    name="requirements",
    source="requirements.txt",
)

python_tests(
    name="tests",
    dependencies=[":server"],
)
