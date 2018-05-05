# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import BinaryToolBase
from pants.binaries.binary_util import BinaryUtilPrivate
from pants.option.scope import GLOBAL_SCOPE
from pants.util.osutil import OsId
from pants_test.base_test import BaseTest


class BinaryToolTestBase(BinaryToolBase):

  @classmethod
  def _os_id(cls):
    return OsId('xxx', 'yyy')


class DefaultVersion(BinaryToolTestBase):
  options_scope = 'default-version-test'
  name = 'default_version_test_tool'
  default_version = 'XXX'


class AnotherTool(BinaryToolTestBase):
  options_scope = 'another-tool'
  name = 'another_tool'
  default_version = '0.0.1'


class ReplacingLegacyOptionsTool(BinaryToolTestBase):
  # TODO: check scope?
  options_scope = 'replacing-legacy-options-tool'
  name = 'replacing_legacy_options_tool'
  default_version = 'a2f4ab23a4c'

  replaces_scope = 'old_tool_scope'
  replaces_name = 'old_tool_version'


class CustomUrls(BinaryToolTestBase):
  options_scope = 'custom-urls'
  name = 'custom_urls_tool'
  default_version = 'v2.1'

  dist_url_versions = ['v2.1', 'v2.3']

  _DIST_URL_FMT = 'https://custom-url.example.org/files/custom_urls_tool-{version}-{system_id}'

  _SYSTEM_ID = {
    'xxx': 'zzz',
    'darwin': 'x86_64-apple-darwin',
    'linux': 'x86_64-linux-gnu',
  }

  @classmethod
  def make_dist_urls(cls, version, os_name):
    base = cls._DIST_URL_FMT.format(version=version, system_id=cls._SYSTEM_ID[os_name])
    return [
      base,
      '{}-alternate'.format(base),
    ]


class BinaryToolBaseTest(BaseTest):

  def setUp(self):
    super(BinaryToolBaseTest, self).setUp()
    self._context = self.context(
      for_subsystems=[DefaultVersion, AnotherTool, ReplacingLegacyOptionsTool, CustomUrls],
      options={
        GLOBAL_SCOPE: {
          'binaries_baseurls': ['https://binaries.example.org'],
        },
        'another-tool': {
          'version': '0.0.2',
        },
        'default-version-test.another-tool': {
          'version': 'YYY',
        },
        'custom-urls': {
          'version': 'v2.3',
        },
        'old_tool_scope': {
          'old_tool_version': '3',
        },
      })

  def test_base_options(self):
    # TODO: using extra_version_option_kwargs!
    default_version_tool = DefaultVersion.global_instance()
    self.assertEqual(default_version_tool.version(), 'XXX')

    another_tool = AnotherTool.global_instance()
    self.assertEqual(another_tool.version(), '0.0.2')

    another_default_version_tool = DefaultVersion.scoped_instance(AnotherTool)
    self.assertEqual(another_default_version_tool.version(), 'YYY')

  def test_replacing_legacy_options(self):
    replacing_legacy_options_tool = ReplacingLegacyOptionsTool.global_instance()
    self.assertEqual(replacing_legacy_options_tool.version(), 'a2f4ab23a4c')
    self.assertEqual(replacing_legacy_options_tool.version(self._context), '3')

  def test_urls(self):
    default_version_tool = DefaultVersion.global_instance()
    self.assertEqual(default_version_tool.get_options().urls, {})

    with self.assertRaises(BinaryUtilPrivate.BinaryNotFound) as cm:
      default_version_tool.select()
    err_msg = str(cm.exception)
    self.assertIn(
      "Failed to fetch binary bin/default_version_test_tool/XXX/default_version_test_tool from any source",
      err_msg)
    self.assertIn(
      "Failed to fetch binary from https://binaries.example.org/bin/default_version_test_tool/XXX/default_version_test_tool",
      err_msg)

    custom_urls_tool = CustomUrls.global_instance()
    self.assertEqual(custom_urls_tool.version(), 'v2.3')
    custom_urls_urls = custom_urls_tool.get_options().urls
    self.assertEqual(custom_urls_urls, {
      'v2.1': [
        'https://custom-url.example.org/files/custom_urls_tool-v2.1-zzz',
        'https://custom-url.example.org/files/custom_urls_tool-v2.1-zzz-alternate',
      ],
      'v2.3': [
        'https://custom-url.example.org/files/custom_urls_tool-v2.3-zzz',
        'https://custom-url.example.org/files/custom_urls_tool-v2.3-zzz-alternate',
      ],
    })

    with self.assertRaises(BinaryUtilPrivate.BinaryNotFound) as cm:
      custom_urls_tool.select()
    err_msg = str(cm.exception)
    self.assertIn(
      "Failed to fetch binary bin/custom_urls_tool/v2.3/custom_urls_tool from any source",
      err_msg)
    self.assertIn(
      "Failed to fetch binary from https://custom-url.example.org/files/custom_urls_tool-v2.3-zzz",
      err_msg)
    self.assertIn(
      "Failed to fetch binary from https://custom-url.example.org/files/custom_urls_tool-v2.3-zzz-alternate",
      err_msg)
