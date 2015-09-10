# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty
from textwrap import dedent

from pants.base.address_lookup_error import AddressLookupError
from pants.base.source_root import SourceRoot
from pants.util.meta import AbstractClass
from pants_test.base_test import BaseTest

from pants.contrib.go.register import build_file_aliases


class GoLocalSourceTestBase(AbstractClass):
  # NB: We assume we're mixed into a BaseTest - we can't extend that directly or else unittest tries
  # to run our test methods in the subclass (OK), and against us (not OK).
  # NB: We use  aliases and BUILD files to test proper registration of anonymous targets and macros.

  @classmethod
  def setUpClass(cls):
    if not issubclass(cls, BaseTest):
      raise TypeError('Subclasses must mix in BaseTest')
    super(GoLocalSourceTestBase, cls).setUpClass()

  @abstractproperty
  def target_type(self):
    """Subclasses should return a GoLocalSource target subclass."""

  @property
  def alias_groups(self):
    return build_file_aliases()

  def test_default_name_and_sources(self):
    SourceRoot.register('src/go', self.target_type)
    self.create_file('src/go/src/foo/jake.go')
    self.create_file('src/go/src/foo/sub/jane.go')
    self.add_to_build_file('src/go/src/foo', dedent("""
        {target_alias}()
      """.format(target_alias=self.target_type.alias())))

    go_local_source_target = self.target('src/go/src/foo')
    self.assertIsNotNone(go_local_source_target)
    self.assertEqual('src/foo', go_local_source_target.import_path)
    self.assertEqual(['src/foo/jake.go'],
                     list(go_local_source_target.sources_relative_to_source_root()))

  def test_cannot_name(self):
    SourceRoot.register('src/go', self.target_type)
    self.add_to_build_file('src/go/src/foo', dedent("""
        {target_alias}(name='bob')
      """.format(target_alias=self.target_type.alias())))

    with self.assertRaises(AddressLookupError):
      self.target('src/go/src/foo')

  def test_cannot_sources(self):
    SourceRoot.register('src/go', self.target_type)
    self.create_file('src/go/src/foo/sub/jane.go')
    self.add_to_build_file('src/go/src/foo', dedent("""
        {target_alias}(sources=['sub/jane.go'])
      """.format(target_alias=self.target_type.alias())))

    with self.assertRaises(AddressLookupError):
      self.target('src/go/src/foo')
