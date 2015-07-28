# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base import ParseContext


class JarLibraryWithOverrides(unittest.TestCase):

  def test_jar_dependency(self):
    with ParseContext.temp():
      org, name = "org", "name"
      # thing to override
      nay = JarDependency(org, name, "0.0.1")
      yea = JarDependency(org, name, "0.0.8")
      # define targets depend on different 'org:c's
      JarLibrary("c", jars=[nay])
      JarLibrary("b", jars=[yea])
      # then depend on those targets transitively, and override to the correct version
      l = Target(
        "a",
        dependencies=[Pants(":c")],
        overrides=[":b"])

      # confirm that resolving includes the correct version
      resolved = set(l.resolve())
      self.assertTrue(yea in resolved)
      # and attaches an exclude directly to the JarDependency
      self.assertTrue(Exclude(org, name) in nay.excludes)
