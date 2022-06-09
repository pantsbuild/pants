# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    sources=["*.py", "!*_test.py", "!dockerfile_parser.py", "!dockerfile_wrapper_script.py"]
)

python_sources(
    name="dockerfile_parser",
    sources=["dockerfile_parser.py"],
    dependencies=[":dockerfile_tool", ":lockfile"],
)

resource(name="lockfile", source="dockerfile.lock")

python_sources(name="dockerfile_tool", sources=["dockerfile_wrapper_script.py"])

python_tests(name="tests", timeout=120)
