# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.rules.inject_init import InitInjectedDigest, inject_init
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, EMPTY_SNAPSHOT
from pants.util.collections import assert_single_element
from pants_test.test_base import TestBase


class TestInjectInit(TestBase):

  @classmethod
  def rules(cls):
    return super(TestInjectInit, cls).rules() + [inject_init]

  def test_noops_when_empty_snapshot(self):
    injected_digest = assert_single_element(
      self.scheduler.product_request(InitInjectedDigest, [EMPTY_SNAPSHOT])
    )
    self.assertEqual(injected_digest.directory_digest, EMPTY_DIRECTORY_DIGEST)

  def test_noops_when_init_already_present(self):
    snapshot = self.make_snapshot({
      "test/foo.py": "",
      "test/__init__.py": ""
    })
    injected_digest = assert_single_element(
      self.scheduler.product_request(InitInjectedDigest, [snapshot])
    )
    self.assertEqual(injected_digest.directory_digest, snapshot.directory_digest)

  def test_adds_when_init_missing(self):
    snapshot = self.make_snapshot({"test/foo.py": ""})
    injected_digest = assert_single_element(
      self.scheduler.product_request(InitInjectedDigest, [snapshot])
    )
    expected_digest = self.make_snapshot({
      "test/foo.py": "",
      "test/__init__.py": ""
    }).directory_digest
    self.assertEqual(injected_digest.directory_digest, expected_digest)
