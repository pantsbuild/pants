# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.parse_context import ParseContext
from pants.targets.artifact import Artifact
from pants.targets.repository import Repository


class ArtifactTest(unittest.TestCase):

  def test_validation(self):
    with ParseContext.temp():
      repo = Repository(name="myRepo", url="myUrl", push_db="myPushDb")
      Artifact(org="testOrg", name="testName", repo=repo, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org=1, name="testName", repo=repo, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org="testOrg", name=1, repo=repo, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org="testOrg", name="testName", repo=1, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org="testOrg", name="testName", repo=repo, description=1)
