# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants_test import base_test
from pants_test.subsystem.subsystem_util import subsystem_instance

from pants.contrib.go.subsystems.fetcher_factory import FetcherFactory


class FetchersTest(base_test.BaseTest):
  @contextmanager
  def fetcher(self, import_path):
    with subsystem_instance(FetcherFactory) as fetcher_factory:
      yield fetcher_factory.get_fetcher(import_path)

  def check_default(self, import_path, expected_root):
    with self.fetcher(import_path) as fetcher:
      self.assertEqual(expected_root, fetcher.root())

  def test_default_bitbucket(self):
    self.check_default('bitbucket.org/rj/sqlite3-go',
                       expected_root='bitbucket.org/rj/sqlite3-go')
    self.check_default('bitbucket.org/neuronicnobody/go-opencv/opencv',
                       expected_root='bitbucket.org/neuronicnobody/go-opencv')

  def test_default_github(self):
    self.check_default('github.com/bitly/go-simplejson',
                       expected_root='github.com/bitly/go-simplejson')
    self.check_default('github.com/docker/docker/daemon/events',
                       expected_root='github.com/docker/docker')

  def test_default_golang(self):
    self.check_default('golang.org/x/oauth2',
                       expected_root='golang.org/x/oauth2')
    self.check_default('golang.org/x/net/context',
                       expected_root='golang.org/x/net')

  def test_default_gopkg(self):
    self.check_default('gopkg.in/check.v1', expected_root='gopkg.in/check.v1')
