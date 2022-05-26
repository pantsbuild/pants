# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":kotlin_resources"])
resources(name="kotlin_resources", sources=["*.kt", "*.lock"])

python_tests(name="tests", timeout=240)
