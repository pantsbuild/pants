# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from future.utils import text_type

from pants.backend.python.rules.inject_init import InitInjectedDigest
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, EMPTY_SNAPSHOT, PathGlobs, PathGlobsAndRoot
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump
from pants_test.test_base import TestBase


class TestInjectInit(TestBase):

  def test_noops_when_empty_snapshot(self):
    injected_digest = assert_single_element(
      self.scheduler.product_request(InitInjectedDigest, [EMPTY_SNAPSHOT])
    )
    self.assertEqual(injected_digest.directory_digest, EMPTY_DIRECTORY_DIGEST)

  def test_noops_when_init_already_present(self):
    with temporary_dir() as temp_dir:
      safe_file_dump(os.path.join(temp_dir, "test", "foo.py"), makedirs=True)
      safe_file_dump(os.path.join(temp_dir, "test", "__init__.py"), makedirs=True)
      globs = PathGlobs(("*",), ())
      snapshot = self.scheduler.capture_snapshots((PathGlobsAndRoot(globs, text_type(temp_dir)),))[0]
      injected_digest = assert_single_element(
        self.scheduler.product_request(InitInjectedDigest, [snapshot])
      )
    self.assertEqual(injected_digest.directory_digest, snapshot.directory_digest)

  def test_adds_when_init_missing(self):
    with temporary_dir() as temp_dir:
      safe_file_dump(os.path.join(temp_dir, "test", "foo.py"), makedirs=True)
      globs = PathGlobs(("*",), ())
      snapshot = self.scheduler.capture_snapshots((PathGlobsAndRoot(globs, text_type(temp_dir)),))[0]
      injected_digest = assert_single_element(
        self.scheduler.product_request(InitInjectedDigest, [snapshot])
      )
    # TODO: how to make expected digest
    self.assertEqual(injected_digest, EMPTY_DIRECTORY_DIGEST)
