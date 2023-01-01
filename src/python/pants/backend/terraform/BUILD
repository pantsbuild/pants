# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(sources=["*.py", "!*_test.py", "!dependency_inference.py", "!hcl2_parser.py"])

python_sources(
    name="dependency_inference",
    sources=["dependency_inference.py"],
    dependencies=[":hcl2_parser", ":lockfile"],
)

python_sources(name="hcl2_parser", sources=["hcl2_parser.py"])

resource(name="lockfile", source="hcl2.lock")

python_tests(name="tests", sources=["*_test.py", "!dependency_inference_test.py"])
python_tests(
    name="dependency_inference_test",
    sources=["dependency_inference_test.py"],
    timeout=340,
    # We want to make sure the default lockfile works for both macOS and Linux.
    tags=["platform_specific_behavior"],
)
