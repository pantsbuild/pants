# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from twitter.common.dirutil.fileset import Fileset

from pants.backend.codegen.tasks.antlr_gen import AntlrGen
from pants.base.address import SyntheticAddress
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class AntlrGenTest(NailgunTaskTestBase):
  def test_antlr4(self):
    parts = {'srcroot': 'src/antlr',
             'dir': 'this/is/a/directory',
             'name': 'smoke',
             'package': 'this.is.a.package',
             'prefix': 'SMOKE'}
    self.create_file(relpath='%(srcroot)s/%(dir)s/%(prefix)s.g4' % parts,
                     contents=dedent('''
      grammar %(prefix)s;
      options { language=Java; }
      ////////////////////
      start  : letter EOF ;
      letter : LETTER ;
      ////////////////////
      fragment LETTER : [a-zA-Z] ;
    ''' % parts))
    self.add_to_build_file('%(srcroot)s/%(dir)s/BUILD' % parts, dedent('''
      java_antlr_library(
        name='%(name)s',
        compiler='antlr4',
        package='%(package)s',
        sources=['%(prefix)s.g4'],
      )
    ''' % parts))

    # generate a context to contain the build graph for the input target, then execute
    context = self.context(target_roots=[self.target('%(srcroot)s/%(dir)s:%(name)s' % parts)])
    task = self.execute(context, AntlrGen)

    # get the synthetic target from the private graph
    task_outdir = os.path.join(task.workdir, 'antlr4', 'gen-java')
    syn_sourceroot = os.path.join(task_outdir, parts['srcroot'])
    syn_target_name = ('%(srcroot)s/%(dir)s.%(name)s' % parts).replace('/', '.')
    syn_address = SyntheticAddress(spec_path=os.path.relpath(syn_sourceroot, self.build_root),
                                   target_name=syn_target_name)
    syn_target = context.build_graph.get_target(syn_address)

    # verify that the synthetic target's list of sources match what are actually created
    def re_relativize(p):
      """Take a path relative to task_outdir, and make it relative to the build_root"""
      # TODO: is there a way to do this directly with rglobs?
      return os.path.relpath(os.path.join(task_outdir, p), self.build_root)
    actual_sources = [re_relativize(s) for s in Fileset.rglobs('*.java', root=task_outdir)]
    self.assertEquals(set(syn_target.sources_relative_to_buildroot()), set(actual_sources))
    # and that the synthetic target has a valid sourceroot
    for source in syn_target.sources_relative_to_source_root():
      self.assertTrue(os.path.isfile(os.path.join(syn_sourceroot, source)),
                      "%s is not the sourceroot for %s" % (syn_sourceroot, source))
