# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest
from textwrap import dedent

from pants.base.parse_context import ParseContext
from pants.base.target import TargetDefinitionException
from pants.base_build_root_test import BaseBuildRootTest
from pants.targets.artifact import Artifact
from pants.targets.python_artifact import PythonArtifact
from pants.targets.python_target import PythonTarget
from pants.targets.repository import Repository
from pants.targets.sources import SourceRoot


class PythonTargetTest(BaseBuildRootTest):

  @classmethod
  def setUpClass(self):
    super(PythonTargetTest, self).setUpClass()
    SourceRoot.register(os.path.realpath(os.path.join(self.build_root, 'test_python_target')),
                        PythonTarget)

    self.create_target('test_thrift_replacement', dedent('''
      python_thrift_library(name='one',
        sources=['thrift/keyword.thrift'],
        dependencies=None
      )
    '''))

  def test_validation(self):
    with ParseContext.temp('PythonTargetTest/test_validation'):

      # Adding a JVM Artifact as a provides on a PythonTarget doesn't make a lot of sense. This test
      # sets up that very scenario, and verifies that pants throws a TargetDefinitionException.
      self.assertRaises(TargetDefinitionException, PythonTarget, name="one", sources=[],
        provides=Artifact(org='com.twitter', name='one-jar',
        repo=Repository(name='internal', url=None, push_db=None, exclusives=None)))

      name = "test-with-PythonArtifact"
      pa = PythonArtifact(name='foo', version='1.0', description='foo')

      # This test verifies that adding a 'setup_py' provides to a PythonTarget is okay.
      self.assertEquals(PythonTarget(name=name, provides=pa, sources=[]).name, name)
      name = "test-with-none"

      # This test verifies that having no provides is okay.
      self.assertEquals(PythonTarget(name=name, provides=None, sources=[]).name, name)
