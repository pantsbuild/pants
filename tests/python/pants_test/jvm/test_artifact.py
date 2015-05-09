# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.artifact import Artifact, PublicationMetadata
from pants.backend.jvm.repository import Repository
from pants_test.base_test import BaseTest


class ArtifactTest(BaseTest):

  def test_validation(self):
    repo = Repository(name="myRepo",
                      url="myUrl",
                      push_db_basedir="myPushDb")

    class TestPublicationMetadata(PublicationMetadata):
      def _compute_fingerprint(self):
        return None
    metadata = TestPublicationMetadata()

    Artifact(org="testOrg", name="testName", repo=repo, publication_metadata=metadata)

    with self.assertRaises(ValueError):
      Artifact(org=1, name="testName", repo=repo, publication_metadata=metadata)

    with self.assertRaises(ValueError):
      Artifact(org="testOrg", name=1, repo=repo, publication_metadata=metadata)

    with self.assertRaises(ValueError):
      Artifact(org="testOrg", name="testName", repo=1, publication_metadata=metadata)

    with self.assertRaises(ValueError):
      Artifact(org="testOrg", name="testName", repo=repo, publication_metadata=1)
