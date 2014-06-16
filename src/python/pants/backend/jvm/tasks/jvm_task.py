# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.build_environment import get_buildroot
from pants.backend.core.tasks.task import Task


class JvmTask(Task):
  def get_base_classpath_for_target(self, target):
    """Note: to use this method, the exclusives_groups data product must be available. This should
    have been set by the prerequisite java/scala compile."""
    egroups = self.context.products.get_data('exclusives_groups')
    group_key = egroups.get_group_key_for_target(target)
    return egroups.get_classpath_for_group(group_key)

  def classpath(self, cp=None, confs=None, exclusives_classpath=None):
    classpath = list(cp) if cp else []
    exclusives_classpath = exclusives_classpath or []

    classpath.extend(path for conf, path in exclusives_classpath if not confs or conf in confs)

    def add_resource_paths(predicate):
      bases = set()
      for target in self.context.targets():
        if predicate(target):
          if target.target_base not in bases:
            sibling_resources_base = os.path.join(os.path.dirname(target.target_base), 'resources')
            classpath.append(os.path.join(get_buildroot(), sibling_resources_base))
            bases.add(target.target_base)

    if self.context.config.getbool('jvm', 'parallel_src_paths', default=False):
      add_resource_paths(lambda t: t.is_jvm and not t.is_test)

    if self.context.config.getbool('jvm', 'parallel_test_paths', default=False):
      add_resource_paths(lambda t: t.is_jvm and not t.is_test)

    return classpath
