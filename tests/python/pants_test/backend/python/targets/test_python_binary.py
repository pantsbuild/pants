# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.testutil.test_base import TestBase


class PythonBinaryTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"python_binary": PythonBinary})

    subsystems = PythonBinary.subsystems()

    def test_python_binary(self):
        # Set up and run
        self.create_file("some/path/to/python/path/to/py.py")
        self.add_to_build_file(
            "some/path/to/python", 'python_binary(name = "binary", sources = ["path/to/py.py"])\n',
        )
        target = self.target("some/path/to/python:binary")
        # Verify
        self.assertTrue(isinstance(target, PythonBinary))
