# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base import ParseContext
from pants.targets.exclude import Exclude
from pants.targets.jar_dependency import JarDependency
from pants.targets.jar_library import JarLibrary
from pants.targets.pants_target import Pants


class JarLibraryWithOverrides(unittest.TestCase):

  def test_jar_dependency(self):
    with ParseContext.temp():
      org, name = "org", "name"
      # thing to override
      nay = JarDependency(org, name, "0.0.1")
      yea = JarDependency(org, name, "0.0.8")
      # define targets depend on different 'org:c's
      JarLibrary("c", [nay])
      JarLibrary("b", [yea])
      # then depend on those targets transitively, and override to the correct version
      l = JarLibrary(
        "a",
        dependencies=[Pants(":c")],
        overrides=[":b"])

      # confirm that resolving includes the correct version
      resolved = set(l.resolve())
      self.assertTrue(yea in resolved)
      # and attaches an exclude directly to the JarDependency
      self.assertTrue(Exclude(org, name) in nay.excludes)
