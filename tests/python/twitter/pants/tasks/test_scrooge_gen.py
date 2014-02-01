# ==================================================================================================
# Copyright 2014 Twitter, Inc.
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

import pytest

from textwrap import dedent

from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.scrooge_gen import ScroogeGen


class ScroogeGenTest(BaseBuildRootTest):

  def test_validate(self):
    self.create_target('test_validate', dedent('''
      java_thrift_library(name='one',
        sources=None,
        dependencies=None,
      )
    '''))

    self.create_target('test_validate', dedent('''
      java_thrift_library(name='two',
        sources=None,
        dependencies=[pants(':one')],
      )
    '''))

    self.create_target('test_validate', dedent('''
      java_thrift_library(name='three',
        sources=None,
        dependencies=[pants(':one')],
        rpc_style='finagle',
      )
    '''))

    ScroogeGen._validate([self.target('test_validate:one')])
    ScroogeGen._validate([self.target('test_validate:two')])

    with pytest.raises(TaskError):
      ScroogeGen._validate([self.target('test_validate:three')])
