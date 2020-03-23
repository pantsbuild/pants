# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


def prepare_dependencies(self):
    self.add_to_build_file("a", 'java_library(name="a")')
    self.add_to_build_file("b", 'java_library(name="b", dependencies=["a:a"])')
    self.add_to_build_file("c", 'java_library(name="c", dependencies=["a:a"])')
    self.add_to_build_file("d", 'java_library(name="d", dependencies=["a:a", "b"])')

    targets = {"a": self.make_target("a")}
    targets["b"] = self.make_target("b", dependencies=[targets["a"]])
    targets["c"] = self.make_target("c", dependencies=[targets["a"], targets["b"]])
    targets["d"] = self.make_target("d", dependencies=[targets["a"], targets["b"]])

    return targets
