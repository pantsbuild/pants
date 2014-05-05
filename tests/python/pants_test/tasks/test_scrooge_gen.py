# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

import pytest

from pants.targets.java_thrift_library import JavaThriftLibrary
from pants.tasks.task import TaskError
from pants.tasks.scrooge_gen import ScroogeGen
from pants_test.base_test import BaseTest


class ScroogeGenTest(BaseTest):

  def test_validate(self):
    defaults = JavaThriftLibrary.Defaults()

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='one',
        sources=[],
        dependencies=[],
      )
    '''))

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='two',
        sources=[],
        dependencies=[pants(':one')],
      )
    '''))

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='three',
        sources=[],
        dependencies=[pants(':one')],
        rpc_style='finagle',
      )
    '''))

    ScroogeGen._validate(defaults, [self.target('test_validate:one')])
    ScroogeGen._validate(defaults, [self.target('test_validate:two')])

    with pytest.raises(TaskError):
      ScroogeGen._validate(defaults, [self.target('test_validate:three')])
