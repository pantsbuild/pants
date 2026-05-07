# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(sources=["*.py", "!*_test.py", "!dockerfile_parser.py"])

# TODO: Does this need to be separate?
python_sources(
    name="dockerfile_parser",
    sources=["dockerfile_parser.py"],
)

python_tests(name="tests", timeout=120)
