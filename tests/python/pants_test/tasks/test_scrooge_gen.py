# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

import pytest

from pants.tasks import TaskError
from pants.tasks.scrooge_gen import ScroogeGen
from pants_test.base_build_root_test import BaseBuildRootTest


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
