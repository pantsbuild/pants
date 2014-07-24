# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
from textwrap import dedent
import xml.etree.ElementTree as ET

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.util.contextutil import temporary_file_path
from pants_test.base_test import BaseTest
from pants_test.base.context_utils import create_config


class IvyUtilsTestBase(BaseTest):
  @staticmethod
  def create_options(**kwargs):
    options = dict(ivy_mutable_pattern=None,
                   ivy_resolve_overrides=None)
    options.update(**kwargs)
    return options

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())


class IvyUtilsGenerateIvyTest(IvyUtilsTestBase):

  # TODO(John Sirois): increase coverage.
  # Some examples:
  # + multiple confs - via with_sources and with_docs for example
  # + excludes
  # + classifiers
  # + with_artifact

  def setUp(self):
    super(IvyUtilsGenerateIvyTest, self).setUp()

    self.add_to_build_file('src/java/targets',
        dedent("""
            jar_library(
              name='simple',
              jars=[
                jar('org1', 'name1', 'rev1'),
                jar('org2', 'name2', 'rev2', force=True),
              ]
            )
        """))

    self.simple = self.target('src/java/targets:simple')
    self.ivy_utils = IvyUtils(create_config(), self.create_options(), logging.Logger('test'))

  def test_force_override(self):
    jars = list(self.simple.payload.jars)
    with temporary_file_path() as ivyxml:
      self.ivy_utils._generate_ivy([self.simple], jars=jars, excludes=[], ivyxml=ivyxml,
                                   confs=['default'])

      doc = ET.parse(ivyxml).getroot()

      conf = self.find_single(doc, 'configurations/conf')
      self.assert_attributes(conf, name='default')

      dependencies = list(doc.findall('dependencies/dependency'))
      self.assertEqual(2, len(dependencies))

      dep1 = dependencies[0]
      self.assert_attributes(dep1, org='org1', name='name1', rev='rev1')
      conf = self.find_single(dep1, 'conf')
      self.assert_attributes(conf, name='default', mapped='default')

      dep2 = dependencies[1]
      self.assert_attributes(dep2, org='org2', name='name2', rev='rev2', force='true')
      conf = self.find_single(dep1, 'conf')
      self.assert_attributes(conf, name='default', mapped='default')

      override = self.find_single(doc, 'dependencies/override')
      self.assert_attributes(override, org='org2', module='name2', rev='rev2')

  def find_single(self, elem, xpath):
    results = list(elem.findall(xpath))
    self.assertEqual(1, len(results))
    return results[0]

  def assert_attributes(self, elem, **kwargs):
    self.assertEqual(dict(**kwargs), dict(elem.attrib))
