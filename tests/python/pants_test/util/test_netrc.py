# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
import unittest
from builtins import str
from contextlib import contextmanager

from future.utils import PY3
from mock import MagicMock, mock_open, patch

from pants.util.netrc import Netrc


@patch('os.path')
class TestNetrcUtil(unittest.TestCase):

  class MockOsPath(MagicMock):
    def __init__(self):
      super(TestNetrcUtil.MockOsPath, self).__init__()
      self.expanduser.return_value = '~/.netrc'
      self.exists.return_value = True

  def test_netrc_success(self, MockOsPath):
    with patch('pants.util.netrc.NetrcDb') as mock_netrc:
      instance = mock_netrc.return_value
      instance.hosts = {'host': ('user', 'user', 'passw0rd')}
      instance.authenticators.return_value = ('user', 'user', 'passw0rd')
      netrc = Netrc()
      netrc._ensure_loaded()

  def test_netrc_file_missing_error(self, MockOsPath):
    MockOsPath.exists.return_value = False
    netrc = Netrc()
    with self.assertRaises(netrc.NetrcError) as exc:
      netrc._ensure_loaded()
    assert str(exc.exception) == 'A ~/.netrc file is required to authenticate'

  def test_netrc_parse_error(self, MockOsPath):
    with self.netrc('machine test') as netrc:
      with self.assertRaises(netrc.NetrcError) as exc:
        netrc._ensure_loaded()
      assert re.search(r'Problem parsing', str(exc.exception))

  def test_netrc_no_usable_blocks(self, MockOsPath):
    with self.netrc('') as netrc:
      with self.assertRaises(netrc.NetrcError) as exc:
        netrc._ensure_loaded()
      assert str(exc.exception) == 'Found no usable authentication blocks in ~/.netrc'

  @contextmanager
  def netrc(self, netrc_contents):
    m = mock_open(read_data=netrc_contents)
    open_builtin_name = 'builtins.open' if PY3 else '__builtin__.open'
    with patch(open_builtin_name, m):
      netrc = Netrc()
      yield netrc
