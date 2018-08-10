# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.binaries.binary_tool import BinaryToolBase
from pants.binaries.binary_util import (BinaryToolFetcher, BinaryToolUrlGenerator, BinaryUtil,
                                        HostPlatform)
from pants.option.scope import GLOBAL_SCOPE
from pants_test.base_test import BaseTest


class DefaultVersion(BinaryToolBase):
  options_scope = 'default-version-test'
  name = 'default_version_test_tool'
  default_version = 'XXX'


class AnotherTool(BinaryToolBase):
  options_scope = 'another-tool'
  name = 'another_tool'
  default_version = '0.0.1'


class ReplacingLegacyOptionsTool(BinaryToolBase):
  # TODO: check scope?
  options_scope = 'replacing-legacy-options-tool'
  name = 'replacing_legacy_options_tool'
  default_version = 'a2f4ab23a4c'

  replaces_scope = 'old_tool_scope'
  replaces_name = 'old_tool_version'


class BinaryUtilFakeUname(BinaryUtil):

  def _host_platform(self):
    return HostPlatform('xxx', 'yyy')


class CustomUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://custom-url.example.org/files/custom_urls_tool-{version}-{system_id}'

  _SYSTEM_ID = {
    'xxx': 'zzz',
  }

  def generate_urls(self, version, host_platform):
    base = self._DIST_URL_FMT.format(
      version=version,
      system_id=self._SYSTEM_ID[host_platform.os_name])
    return [
      base,
      '{}-alternate'.format(base),
    ]


class CustomUrls(BinaryToolBase):
  options_scope = 'custom-urls'
  name = 'custom_urls_tool'
  default_version = 'v2.1'

  def get_external_url_generator(self):
    return CustomUrlGenerator()

  def _select_for_version(self, version):
    binary_request = self._make_binary_request(version)
    return BinaryUtilFakeUname.Factory._create_for_cls(BinaryUtilFakeUname).select(binary_request)


# TODO(cosmicexplorer): these should have integration tests which use BinaryTool subclasses
# overriding archive_type
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
    self.assertIsNone(default_version_tool.get_external_url_generator())

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      default_version_tool.select()
    err_msg = str(cm.exception)
    self.assertIn(BinaryToolFetcher.BinaryNotFound.__name__, err_msg)
    self.assertIn(
      "Failed to fetch default_version_test_tool binary from any source:",
      err_msg)
    self.assertIn(
      "Failed to fetch binary from https://binaries.example.org/bin/default_version_test_tool/XXX/default_version_test_tool:",
      err_msg)

    custom_urls_tool = CustomUrls.global_instance()
    self.assertEqual(custom_urls_tool.version(), 'v2.3')

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      custom_urls_tool.select()
    err_msg = str(cm.exception)
    self.assertIn(BinaryToolFetcher.BinaryNotFound.__name__, err_msg)
    self.assertIn(
      "Failed to fetch custom_urls_tool binary from any source:",
      err_msg)
    self.assertIn(
      "Failed to fetch binary from https://custom-url.example.org/files/custom_urls_tool-v2.3-zzz:",
      err_msg)
    self.assertIn(
      "Failed to fetch binary from https://custom-url.example.org/files/custom_urls_tool-v2.3-zzz-alternate:",
      err_msg)
