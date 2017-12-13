# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Example of writing a test that depends on a python_dist target.

# hello_package is a python module within the superhello python_distribution
from hello_package import hello


def test_superhello():
	assert hello.hello() == "Super hello"
