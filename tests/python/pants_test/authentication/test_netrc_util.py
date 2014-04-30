# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest
import re
import sys
import unittest

from mock import mock_open, patch
from netrc import netrc as NetrcDb

from pants.authentication.netrc_util import Netrc
from pants.authentication.netrc_util import NetrcError

class NetrcUtilTest(unittest.TestCase):

  def setUp(self):
    self._netrc = Netrc()

  def test_netrc_file_missing_error(self):
    with patch('os.path') as os_path:
      os_path.expanduser.return_value = '~/.netrc'
      os_path.exists.return_value = False
      with patch.dict('os.environ', {'USER': 'user'}):
        netrc = Netrc()
        with pytest.raises(NetrcError) as exc:
          netrc._ensure_loaded()
        assert exc.value.message == 'A ~/.netrc file is required to authenticate'

  def test_netrc_parse_error(self):
    netrc_contents = 'machine white \n'
    m = mock_open(read_data=netrc_contents)
    with patch('os.path') as os_path:
      os_path.exists.return_value = True
      with patch.dict('os.environ', {'USER': 'user'}):
        with patch('__builtin__.open', m):
          netrc = Netrc()
          with pytest.raises(NetrcError) as exc:
            netrc._ensure_loaded()
          assert re.search(r'Problem parsing', exc.value.message)

  def test_netrc_no_usable_blocks(self):
    netrc_contents = ''
    m = mock_open(read_data=netrc_contents)
    with patch('os.path.exists') as os_path:
      os_path.exists.return_value = True
      with patch.dict('os.environ', {'USER': 'user'}):
        with patch('__builtin__.open', m):
          netrc = Netrc()
          with pytest.raises(NetrcError) as exc:
            netrc._ensure_loaded()
          assert exc.value.message == 'Found no usable authentication blocks in ~/.netrc'