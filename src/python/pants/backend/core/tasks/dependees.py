# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.tasks.target_filter_task_mixin import TargetFilterTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot


class ReverseDepmap(TargetFilterTaskMixin, ConsoleTask):
  """Outputs all targets whose dependencies include at least one of the input targets."""

  @classmethod
  def register_options(cls, register):
    super(ReverseDepmap, cls).register_options(register)
    register('--transitive', default=False, action='store_true',
             help='List transitive dependees.')
    register('--closed', default=False, action='store_true',
             help='Include the input targets in the output along with the dependees.')
    register('--type', default=[], action='append',
             help="Identifies target types to include. Multiple type inclusions "
                  "can be specified at once in a comma separated list or else by "
                  "using multiple instances of this flag.")

  def __init__(self, *args, **kwargs):
    super(ReverseDepmap, self).__init__(*args, **kwargs)

    self._transitive = self.get_options().transitive
    self._closed = self.get_options().closed
    self._dependees_types = self.get_options().type
    self._spec_excludes = self.get_options().spec_excludes

  def console_output(self, _):
    buildfiles = OrderedSet()
    address_mapper = self.context.address_mapper
    if self._dependees_types:
      base_paths = OrderedSet()
      for dependees_type in self._dependees_types:
        target_types = self.target_types_for_alias(dependees_type)
        # Try to find the SourceRoots for the given input type alias
        for target_type in target_types:
          try:
            roots = SourceRoot.roots(target_type)
            base_paths.update(roots)
          except KeyError:
            pass

      # TODO(John Sirois): BUG: This should not cause a failure, it should just force a slower full
      # scan.
      # TODO(John Sirois): BUG: The --type argument only limited the scn bases, it does no limit the
      # types of targets found under those bases, ie: we may have just limited our scan to roots
      # containing java_library, but those same roots likely also contain jvm_binary targets that
      # we do not wish to have in the results.  So the --type filtering needs to apply to the final
      # dependees_by_target map as well below.
      if not base_paths:
        raise TaskError(dedent("""\
                        No SourceRoot set for any of these target types: {}.
                        Please define a source root in BUILD file as:
                          source_root('<src-folder>', {})
                        """.format(' '.join(self._dependees_types),
                                   ', '.join(self._dependees_types))).strip())
      for base_path in base_paths:
        scanned = address_mapper.scan_buildfiles(get_buildroot(),
                                                 os.path.join(get_buildroot(), base_path),
                                                 spec_excludes=self._spec_excludes)
        buildfiles.update(scanned)
    else:
      buildfiles = address_mapper.scan_buildfiles(get_buildroot(),
                                                  spec_excludes=self._spec_excludes)

    build_graph = self.context.build_graph
    build_file_parser = self.context.build_file_parser

    dependees_by_target = defaultdict(set)
    for build_file in buildfiles:
      address_map = build_file_parser.parse_build_file(build_file)
      for address in address_map.keys():
        build_graph.inject_address_closure(address)
      for address in address_map.keys():
        target = build_graph.get_target(address)
        # TODO(John Sirois): tighten up the notion of targets written down in a BUILD by a
        # user vs. targets created by pants at runtime.
        target = self.get_concrete_target(target)
        for dependency in target.dependencies:
          dependency = self.get_concrete_target(dependency)
          dependees_by_target[dependency].add(target)

    roots = set(self.context.target_roots)
    if self._closed:
      for root in roots:
        yield root.address.spec

    for dependant in self.get_dependants(dependees_by_target, roots):
      yield dependant.address.spec

  def get_dependants(self, dependees_by_target, roots):
    check = set(roots)
    known_dependants = set()
    while True:
      dependants = set(known_dependants)
      for target in check:
        dependants.update(dependees_by_target[target])
      check = dependants - known_dependants
      if not check or not self._transitive:
        return dependants - set(roots)
      known_dependants = dependants

  def get_concrete_target(self, target):
    return target.concrete_derived_from
