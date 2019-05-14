# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from unittest import TestCase

from pants.backend.python.rules.inject_init import inject_init
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, EMPTY_SNAPSHOT
from pants_test.engine.util import run_rule


class TestInjectInit(TestCase):

  def test_noops_when_empty_snapshot(self):
    # TODO: why does this arg fail?
    injected_digest = run_rule(inject_init, EMPTY_SNAPSHOT)
    self.assertEqual(injected_digest, EMPTY_DIRECTORY_DIGEST)

  def test_noops_when_init_already_present(self):
    # TODO: how to make test snapshot
    injected_digest = run_rule(inject_init, EMPTY_SNAPSHOT)
    self.assertEqual(injected_digest, EMPTY_DIRECTORY_DIGEST)

  def test_adds_when_init_missing(self):
    # TODO: how to make test snapshot
    injected_digest = run_rule(inject_init, EMPTY_SNAPSHOT)
    # TODO: how to make expected digest
    self.assertEqual(injected_digest, EMPTY_DIRECTORY_DIGEST)
