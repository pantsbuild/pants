# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import sys

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.core.tasks.task import Task
from pants.backend.jvm.ivy_utils import IvyModuleRef, IvyUtils
from pants.util.contextutil import open_zip as open_jar


class Provides(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('transitive'), default=False,
      action='store_true', dest='provides_transitive',
      help='Shows the symbols provided not just by the specified targets but by all their transitive dependencies.')
    option_group.add_option(mkflag('also-write-to-stdout'), default=False,
      action='store_true', dest='provides_also_write_to_stdout',
      help='If set, also outputs the provides information to stdout.')

  def __init__(self, *args, **kwargs):
    super(Provides, self).__init__(*args, **kwargs)
    self.ivy_utils = IvyUtils(config=self.context.config,
                              options=self.context.options,
                              log=self.context.log)
    self.confs = self.context.config.getlist('ivy', 'confs', default=['default'])
    self.target_roots = self.context.target_roots
    self.transitive = self.context.options.provides_transitive
    self.also_write_to_stdout = self.context.options.provides_also_write_to_stdout or False
    # Create a fake target, in case we were run directly on a JarLibrary containing nothing but JarDependencies.
    # TODO(benjy): Get rid of this special-casing of jar dependencies.
    # TODO(pl): Is this necessary?  Now JarLibrary only contains a payload of JarDependency
    # self.context.add_new_target(self.workdir,
    #   JvmBinary,
    #   name='provides',
    #   dependencies=self.target_roots,
    #   configurations=self.confs)
    # self.context.products.require('jars')

  def execute(self):
    targets = self.context.targets()
    for conf in self.confs:
      outpath = os.path.join(self.workdir, '%s.%s.provides' %
                             (self.ivy_utils.identify(targets)[1], conf))
      if self.transitive:
        outpath += '.transitive'
      ivyinfo = self.ivy_utils.parse_xml_report(self.context.target_roots, conf)
      jar_paths = OrderedSet()
      for root in self.target_roots:
        jar_paths.update(self.get_jar_paths(ivyinfo, root, conf))

      with open(outpath, 'w') as outfile:
        def do_write(s):
          outfile.write(s)
          if self.also_write_to_stdout:
            sys.stdout.write(s)
        for jar in jar_paths:
          do_write('# from jar %s\n' % jar)
          for line in self.list_jar(jar):
            if line.endswith('.class'):
              class_name = line[:-6].replace('/', '.')
              do_write(class_name)
              do_write('\n')
      print('Wrote provides information to %s' % outpath)

  def get_jar_paths(self, ivyinfo, target, conf):
    jar_paths = OrderedSet()
    if target.is_jar_library:
      # Jar library proxies jar dependencies or jvm targets, so the jars are just those of the
      # dependencies.
      for paths in [self.get_jar_paths(ivyinfo, dep, conf) for dep in target.dependencies]:
        jar_paths.update(paths)
    elif isinstance(target, JarDependency):
      ref = IvyModuleRef(target.org, target.name, target.rev, conf)
      jar_paths.update(self.get_jar_paths_for_ivy_module(ivyinfo, ref))
    elif target.is_jvm:
      for basedir, jars in self.context.products.get('jars').get(target).items():
        jar_paths.update([os.path.join(basedir, jar) for jar in jars])
      if self.transitive:
        for dep in target.dependencies:
          jar_paths.update(self.get_jar_paths(ivyinfo, dep, conf))

    return jar_paths

  def get_jar_paths_for_ivy_module(self, ivyinfo, ref):
    jar_paths = OrderedSet()
    module = ivyinfo.modules_by_ref[ref]
    jar_paths.update([a.path for a in module.artifacts])
    if self.transitive:
      for dep in ivyinfo.deps_by_caller.get(ref, []):
        jar_paths.update(self.get_jar_paths_for_ivy_module(ivyinfo, dep))
    return jar_paths

  def list_jar(self, path):
    with open_jar(path, 'r') as jar:
      return jar.namelist()
