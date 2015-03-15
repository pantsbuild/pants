# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.ivy_utils import IvyModuleRef, IvyUtils
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.deprecated import deprecated
from pants.util.contextutil import open_zip64
from pants.util.dirutil import safe_mkdir


# XXX(pl): This task is very broken and has been for a long time.
# Remove it after confirming it has no users.
class Provides(Task):
  @classmethod
  def register_options(cls, register):
    register('--transitive', default=False, action='store_true',
             help='Shows the symbols provided not just by the specified targets but by all their '
                  'transitive dependencies.')
    register('--also-write-to-stdout', default=False, action='store_true',
             help='Also write the provides information to stdout.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('jars')
    round_manager.require_data('ivy_jar_products')

  def __init__(self, *args, **kwargs):
    super(Provides, self).__init__(*args, **kwargs)
    self.confs = self.context.config.getlist('ivy', 'confs', default=['default'])
    self.target_roots = self.context.target_roots
    self.transitive = self.get_options().transitive
    self.also_write_to_stdout = self.get_options().also_write_to_stdout
    # Create a fake target, in case we were run directly on a JarLibrary containing nothing but JarDependencies.
    # TODO(benjy): Get rid of this special-casing of jar dependencies.
    # TODO(pl): Is this necessary?  Now JarLibrary only contains a payload of JarDependency
    # self.context.add_new_target(self.workdir,
    #   JvmBinary,
    #   name='provides',
    #   dependencies=self.target_roots,
    #   configurations=self.confs)
    # self.context.products.require('jars')

  @deprecated('0.0.31', 
              'There is no replacement planned for this task. Contact pants-devel@ if you need it.')
  def execute(self):
    safe_mkdir(self.workdir)
    targets = self.context.targets()
    for conf in self.confs:
      outpath = os.path.join(self.workdir,
                             '{0}.{1}.provides'.format(IvyUtils.identify(targets)[1], conf))
      if self.transitive:
        outpath += '.transitive'
      ivy_jar_products = self.context.products.get_data('ivy_jar_products') or {}
      # This product is a list for historical reasons (exclusives groups) but in practice should
      # have either 0 or 1 entries.
      ivy_info_list = ivy_jar_products.get(conf)
      if ivy_info_list:
        assert len(ivy_info_list) == 1, (
          'The values in ivy_jar_products should always be length 1,'
          ' since we no longer have exclusives groups.'
        )
        ivy_info = ivy_info_list[0]
      else:
        ivy_info = None
      jar_paths = OrderedSet()
      for root in self.target_roots:
        jar_paths.update(self.get_jar_paths(ivy_info, root, conf))

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
      self.context.log.info('Wrote provides information to %s' % outpath)

  def get_jar_paths(self, ivy_info, target, conf):
    jar_paths = OrderedSet()
    if isinstance(target, JarLibrary):
      # Jar library proxies jar dependencies or jvm targets, so the jars are just those of the
      # dependencies.
      for paths in [self.get_jar_paths(ivy_info, dep, conf) for dep in target.dependencies]:
        jar_paths.update(paths)
    elif isinstance(target, JarDependency):
      ref = IvyModuleRef(target.org, target.name, target.rev, conf)
      jar_paths.update(self.get_jar_paths_for_ivy_module(ivy_info, ref))
    elif target.is_jvm:
      for basedir, jars in self.context.products.get('jars').get(target).items():
        jar_paths.update([os.path.join(basedir, jar) for jar in jars])
    if self.transitive:
      for dep in target.dependencies:
        jar_paths.update(self.get_jar_paths(ivy_info, dep, conf))

    return jar_paths

  def get_jar_paths_for_ivy_module(self, ivy_info, ref):
    def create_collection(current_ref):
      module = ivy_info.modules_by_ref[current_ref]
      return OrderedSet([a.path for a in module.artifacts])

    if self.transitive:
      return ivy_info.traverse_dependency_graph(ref, create_collection)
    else:
      return create_collection(ref)

  def list_jar(self, path):
    with open_zip64(path, 'r') as jar:
      return jar.namelist()
