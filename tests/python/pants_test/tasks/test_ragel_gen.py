# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from textwrap import dedent

from twitter.common.collections import OrderedSet
from twitter.common.contextutil import temporary_file

from mock import MagicMock, patch
from pants.backend.codegen.targets.java_ragel_library import JavaRagelLibrary
from pants.backend.codegen.tasks.ragel_gen import calculate_genfile, RagelGen
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.goal.context import Context

from pants_test.base_test import BaseTest
from pants_test.tasks.test_base import is_exe, prepare_task

ragel_file_contents = dedent('''
package com.example.atoi;
%%{
  machine parser;

  action minus {
    negative = true;
  }

  action digit {
    val *= 10;
    val += fc - '0';
  }

  main := ( '-'@minus )? ( [0-9] @digit ) + '\0';
}%%

public class Parser {
  %% write data;

  public static int parse(CharSequence input) {
    StringBuilder builder = new StringBuilder(input);
    builder.append('\0');
    char[] data = builder.toString().toCharArray();
    int p = 0;
    int pe = data.length;
    int eof = pe;
    int cs;
    boolean negative = false;
    int val = 0;

    %% write init;
    %% write exec;
    if (negative)
      return -val;
    else
      return val;
  }
}
''')


class RagelGenTest(BaseTest):

  RAGEL = is_exe('ragel')
  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'java_ragel_library': JavaRagelLibrary})

  @pytest.mark.skipif('not RagelGenTest.RAGEL',
                      reason='No ragel binary on the PATH.')
  def test_ragel_gen(self):
    self.create_file(relpath='test_ragel_gen/atoi.rl', contents=ragel_file_contents)
    self.add_to_build_file('test_ragel_gen', dedent('''
      java_ragel_library(name='atoi',
        sources=['atoi.rl'],
        dependencies=[]
      )
    '''))
    task_outdir = os.path.join(self.build_root, '.pants.d')

    task = prepare_task(RagelGen,
                        build_graph=self.build_graph,
                        targets=[self.target('test_ragel_gen:atoi')],
                        build_file_parser=self.build_file_parser)

    task._ragel_binary = 'ragel'
    task.invalidate_for_files = lambda: []
    task._java_out = task_outdir

    sources = [os.path.join(task_outdir, 'com/example/atoi/Parser.java')]

    Context.add_new_target = MagicMock()
    task.execute()
    relative_task_outdir = os.path.relpath(task_outdir, get_buildroot())
    spec = '{spec_path}:{name}'.format(spec_path=relative_task_outdir, name='test_ragel_gen.atoi')
    address = SyntheticAddress.parse(spec=spec)
    Context.add_new_target.assert_called_once_with(address,
                                                   JavaRagelLibrary,
                                                   sources=sources,
                                                   excludes=OrderedSet(),
                                                   dependencies=OrderedSet(),
                                                   provides=None)


  def test_smoke(self):

    with temporary_file() as fp:
      fp.write(ragel_file_contents)
      fp.flush()
      self.assertEquals(calculate_genfile(fp.name), 'com/example/atoi/Parser.java')
