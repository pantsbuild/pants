# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

__author__ = 'John Sirois'

import os
import pytest
import unittest

from twitter.common.contextutil import temporary_dir
from twitter.pants.base import BuildFile, ContextError, ParseContext

def create_buildfile(root_dir, relpath, content=''):
  path = os.path.join(root_dir, relpath)
  os.makedirs(path)
  buildfile = os.path.join(path, 'BUILD')
  with open(buildfile, 'a') as f:
    f.write(content)
  return BuildFile(root_dir, relpath)


class ParseContextTest(unittest.TestCase):
  def test_locate(self):
    with pytest.raises(ContextError):
      ParseContext.locate()

    with temporary_dir() as root_dir:
      a_context = ParseContext(create_buildfile(root_dir, 'a'))
      b_context = ParseContext(create_buildfile(root_dir, 'b'))

      def test_in_a():
        self.assertEquals(a_context, ParseContext.locate())
        return b_context.do_in_context(lambda: ParseContext.locate())

      self.assertEquals(b_context, a_context.do_in_context(test_in_a))

  def test_parse(self):
    with temporary_dir() as root_dir:
      buildfile = create_buildfile(root_dir, 'a', '''
with open('b', 'w') as b:
  b.write('jack spratt')
      '''.strip())
      b_file = os.path.join(root_dir, 'a', 'b')
      self.assertFalse(os.path.exists(b_file))
      ParseContext(buildfile).parse()
      with open(b_file, 'r') as b:
        self.assertEquals('jack spratt', b.read())

  def test_on_context_exit(self):
    with temporary_dir() as root_dir:
      parse_context = ParseContext(create_buildfile(root_dir, 'a'))
      with pytest.raises(ContextError):
        parse_context.on_context_exit(lambda: 37)

    with temporary_dir() as root_dir:
      buildfile = create_buildfile(root_dir, 'a', '''
import os
from twitter.pants.base import ParseContext
def leave_a_trail(file, contents=''):
  with open(file, 'w') as b:
    b.write(contents)
b_file = os.path.join(os.path.dirname(__file__), 'b')
ParseContext.locate().on_context_exit(leave_a_trail, b_file, contents='42')
assert not os.path.exists(b_file), 'Expected context exit action to be delayed.'
      '''.strip())
      b_file = os.path.join(root_dir, 'a', 'b')
      self.assertFalse(os.path.exists(b_file))
      ParseContext(buildfile).parse()
      with open(b_file, 'r') as b:
        self.assertEquals('42', b.read())
