# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from twitter.common.dirutil.fileset import Fileset

from pants.backend.codegen.antlr.python.antlr_py_gen import AntlrPyGen
from pants.backend.codegen.antlr.python.python_antlr_library import PythonAntlrLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class AntlrPyGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return AntlrPyGen

  @property
  def alias_groups(self):
    return super(AntlrPyGenTest, self).alias_groups.merge(BuildFileAliases(
      targets={
        'python_antlr_library': PythonAntlrLibrary,
      },
    ))

  def test_antlr_py_gen(self):
    self.create_file(
      relpath='foo/bar/baz/Baz.g',
      contents=dedent("""
        grammar Baz;

        options {
          language=Python;
          output=template;
        }

        a : ID INT
            -> template(id={$ID.text}, int={$INT.text})
               "id=<id>, int=<int>"
          ;

        ID : 'a'..'z'+;
        INT : '0'..'9'+;
        WS : (' '|'\n') {$channel=HIDDEN;} ;
      """))

    self.add_to_build_file('foo/bar/baz/BUILD', dedent("""
        python_antlr_library(
          name='baz',
          module='foo.bar.baz',
          sources=['Baz.g'],
        )
      """))

    target = self.target('foo/bar/baz')
    context = self.context(target_roots=[target])
    task = self.prepare_execute(context)
    target_workdir = self.test_workdir

    # Generate code, then create a synthetic target.
    task.execute_codegen(target, target_workdir)
    actual_sources = set(s for s in Fileset.rglobs('*.py', root=target_workdir))
    self.assertSetEqual({
      'foo/__init__.py',
      'foo/bar/__init__.py',
      'foo/bar/baz/__init__.py',
      'foo/bar/baz/BazParser.py',
      'foo/bar/baz/BazLexer.py',
    }, actual_sources)
