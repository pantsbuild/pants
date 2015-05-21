# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from contextlib import contextmanager

import pytest
from mock import MagicMock, mock_open, patch

from pants.backend.authentication.netrc_util import Netrc


@patch('os.path')
class TestNetrcUtil(object):

  class MockOsPath(MagicMock):
    def __init__(self):
      self.expanduser.return_value = '~/.netrc'
      self.exists.return_value = True

  def test_netrc_success(self, MockOsPath):
    with patch('pants.backend.authentication.netrc_util.NetrcDb') as mock_netrc:
      instance = mock_netrc.return_value
      instance.hosts = {'host': ('user', 'user', 'passw0rd')}
      instance.authenticators.return_value = ('user', 'user', 'passw0rd')
      netrc = Netrc()
      netrc._ensure_loaded()

  def test_netrc_file_missing_error(self, MockOsPath):
    MockOsPath.exists.return_value = False
    netrc = Netrc()
    with pytest.raises(netrc.NetrcError) as exc:
      netrc._ensure_loaded()
    assert str(exc.value) == 'A ~/.netrc file is required to authenticate'

  def test_netrc_parse_error(self, MockOsPath):
    with self.netrc('machine test') as netrc:
      with pytest.raises(netrc.NetrcError) as exc:
        netrc._ensure_loaded()
      assert re.search(r'Problem parsing', exc.value.message)

  def test_netrc_no_usable_blocks(self, MockOsPath):
    with self.netrc('') as netrc:
      with pytest.raises(netrc.NetrcError) as exc:
        netrc._ensure_loaded()
      assert str(exc.value) == 'Found no usable authentication blocks in ~/.netrc'

  @contextmanager
  def netrc(self, netrc_contents):
    m = mock_open(read_data=netrc_contents)
    with patch('__builtin__.open', m):
      netrc = Netrc()
      yield netrc
