# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.codegen.targets.java_ragel_library import JavaRagelLibrary
from pants.backend.codegen.tasks.ragel_gen import RagelGen, calculate_genfile
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdtemp
from pants_test.tasks.task_test_base import TaskTestBase


ragel_file_contents = dedent("""
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
""")


class RagelGenTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return RagelGen

  def test_ragel_gen(self):
    self.create_file(relpath='test_ragel_gen/atoi.rl', contents=ragel_file_contents)
    target = self.make_target(spec='test_ragel_gen:atoi',
                              target_type=JavaRagelLibrary,
                              sources=['atoi.rl'])
    task = self.create_task(self.context(target_roots=[target]))

    target_workdir = safe_mkdtemp(dir=self.test_workdir)
    task.execute_codegen(target, target_workdir)

    generated_files = []
    for root, _, files in os.walk(target_workdir):
      generated_files.extend(os.path.relpath(os.path.join(root, f), target_workdir) for f in files)

    self.assertEqual(['com/example/atoi/Parser.java'], generated_files)

  def test_smoke(self):
    with temporary_file() as fp:
      fp.write(ragel_file_contents)
      fp.flush()
      self.assertEquals(calculate_genfile(fp.name), 'com/example/atoi/Parser.java')
