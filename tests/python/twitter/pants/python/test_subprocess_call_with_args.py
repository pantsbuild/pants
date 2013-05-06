# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import errno
import os
import unittest

import pytest

from twitter.pants.binary_util import _subprocess_call, _subprocess_call_with_args


def _call(cmd_with_args, **kwargs):
  if len(cmd_with_args) > 4:
    raise OSError(errno.E2BIG, os.strerror(errno.E2BIG))
  return 0

class SubprocessCallWithArgs(unittest.TestCase):

  def test_subprocess_call_with_args(self):
    cmd = ["no-such-cmd"]
    args = [ "one", "two", "three", "four", "five" ]
    cmd_with_args = cmd[:]
    cmd_with_args.extend(args) # len = 6

    with pytest.raises(OSError) as err:
      _subprocess_call(cmd_with_args, call=_call)
    self.assertEqual(err.value.errno, errno.E2BIG)

    self.assertEqual(0, _subprocess_call_with_args(cmd, args, call=_call))
