# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot


class ReverseDepmap(ConsoleTask):
  """Outputs all targets whose dependencies include at least one of the input targets."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ReverseDepmap, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
                            dest="reverse_depmap_transitive", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] List transitive dependees.")

    option_group.add_option(mkflag("closed"), mkflag("closed", negate=True),
                            dest="reverse_depmap_closed", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Include the input targets in the output along with "
                                 "the dependees.")

    option_group.add_option(mkflag('type'), dest='dependees_type', action='append', default=[],
                            help="Identifies target types to include. Multiple type inclusions "
                                 "can be specified at once in a comma separated list or else by "
                                 "using multiple instances of this flag.")

  def __init__(self, *args, **kwargs):
    super(ReverseDepmap, self).__init__(*args, **kwargs)

    self._transitive = self.context.options.reverse_depmap_transitive
    self._closed = self.context.options.reverse_depmap_closed
    self._dependees_type = self.context.options.dependees_type

  def console_output(self, _):
    buildfiles = OrderedSet()
    if self._dependees_type:
      base_paths = OrderedSet()
      for dependees_type in self._dependees_type:
        # FIXME(pl): This should be a standard function provided by the plugin/BuildFileParser
        # machinery
        try:
          # Try to do a fully qualified import 1st for filtering on custom types.
          from_list, module, type_name = dependees_type.rsplit('.', 2)
          module = __import__('%s.%s' % (from_list, module), fromlist=[from_list])
          target_type = getattr(module, type_name)
        except (ImportError, ValueError):
          # Fall back on pants provided target types.
          registered_aliases = self.context.build_file_parser.registered_aliases()
          if dependees_type not in registered_aliases.targets:
            raise TaskError('Invalid type name: %s' % dependees_type)
          target_type = registered_aliases.targets[dependees_type]

        # Try to find the SourceRoot for the given input type
        try:
          roots = SourceRoot.roots(target_type)
          base_paths.update(roots)
        except KeyError:
          pass

      if not base_paths:
        raise TaskError('No SourceRoot set for any target type in %s.' % self._dependees_type +
                        '\nPlease define a source root in BUILD file as:' +
                        '\n\tsource_root(\'<src-folder>\', %s)' % ', '.join(self._dependees_type))
      for base_path in base_paths:
        buildfiles.update(BuildFile.scan_buildfiles(get_buildroot(),
                                                    os.path.join(get_buildroot(), base_path)))
    else:
      buildfiles = BuildFile.scan_buildfiles(get_buildroot())

    build_graph = self.context.build_graph
    build_file_parser = self.context.build_file_parser

    dependees_by_target = defaultdict(set)
    for build_file in buildfiles:
      build_file_parser.parse_build_file(build_file)
      for address in build_file_parser.addresses_by_build_file[build_file]:
        build_file_parser.inject_spec_closure_into_build_graph(address.spec, build_graph)
      for address in build_file_parser.addresses_by_build_file[build_file]:
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
