# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import operator
import re
import sys

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.exceptions import TaskError
from pants.base.target import Target


_identity = lambda x: x


def _extract_modifier(value):
  if value.startswith('+'):
    return _identity, value[1:]
  elif value.startswith('-'):
    return operator.not_, value[1:]
  else:
    return _identity, value


def _create_filters(list_option, predicate):
  for value in list_option:
    modifier, value = _extract_modifier(value)
    predicates = map(predicate, value.split(','))
    def filter(target):
      return modifier(any(map(lambda predicate: predicate(target), predicates)))
    yield filter


class Filter(ConsoleTask):
  """Filters targets based on various criteria."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(Filter, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('type'), dest='filter_type', action='append', default=[],
                            help="Identifies target types to include (optional '+' prefix) or "
                                 "exclude ('-' prefix).  Multiple type inclusions or exclusions "
                                 "can be specified at once in a comma separated list or else by "
                                 "using multiple instances of this flag.")

    option_group.add_option(mkflag('target'), dest='filter_target', action='append', default=[],
                            help="Identifies specific targets to include (optional '+' prefix) or "
                                 "exclude ('-' prefix).  Multiple target inclusions or exclusions "
                                 "can be specified at once in a comma separated list or else by "
                                 "using multiple instances of this flag.")

    option_group.add_option(mkflag('ancestor'), dest='filter_ancestor', action='append', default=[],
                            help="Identifies ancestor targets (containing targets) that make a "
                                 "select child (contained) targets to include "
                                 "(optional '+' prefix) or exclude ('-' prefix).  Multiple "
                                 "ancestor inclusions or exclusions can be specified at once in "
                                 "a comma separated list or else by using multiple instances of "
                                 "this flag.")

    option_group.add_option(mkflag('regex'), dest='filter_regex', action='append', default=[],
                            help="Identifies regexes of target addresses to include "
                                 "(optional '+' prefix) or exclude ('-' prefix).  Multiple target "
                                 "inclusions or exclusions can be specified at once in a comma "
                                 "separated list or else by using multiple instances of this flag.")

  def __init__(self, context, workdir, outstream=sys.stdout):
    super(Filter, self).__init__(context, workdir, outstream)

    self._filters = []

    def _get_targets(spec):
      try:
        spec_parser = CmdLineSpecParser(get_buildroot(), self.context.build_file_parser)
        addresses = spec_parser.parse_addresses(spec)
      except (IOError, ValueError) as e:
        raise TaskError('Failed to parse spec: %s: %s' % (spec, e))
      matches = set(self.context.build_graph.get_target(address) for address in addresses)
      if not matches:
        raise TaskError('No matches for spec: %s' % spec)
      return matches

    def filter_for_address(spec):
      matches = _get_targets(spec)
      return lambda target: target in matches
    self._filters.extend(_create_filters(context.options.filter_target, filter_for_address))

    def filter_for_type(name):
      # FIXME(pl): This should be a standard function provided by the plugin/BuildFileParser
      # machinery
      try:
        # Try to do a fully qualified import 1st for filtering on custom types.
        from_list, module, type_name = name.rsplit('.', 2)
        module = __import__('%s.%s' % (from_list, module), fromlist=[from_list])
        target_type = getattr(module, type_name)
      except (ImportError, ValueError):
        # Fall back on pants provided target types.
        if name not in self.context.build_file_parser.report_target_aliases():
          raise TaskError('Invalid type name: %s' % name)
        target_type = self.context.build_file_parser.report_target_aliases()[name]
      if not issubclass(target_type, Target):
        raise TaskError('Not a Target type: %s' % name)
      return lambda target: isinstance(target, target_type)
    self._filters.extend(_create_filters(context.options.filter_type, filter_for_type))

    def filter_for_ancestor(spec):
      ancestors = _get_targets(spec)
      children = set()
      for ancestor in ancestors:
        ancestor.walk(children.add)
      return lambda target: target in children
    self._filters.extend(_create_filters(context.options.filter_ancestor, filter_for_ancestor))

    def filter_for_regex(regex):
      parser = re.compile(regex)
      return lambda target: parser.search(str(target.address.spec))
    self._filters.extend(_create_filters(context.options.filter_regex, filter_for_regex))

  def console_output(self, _):
    filtered = set()
    for target in self.context.target_roots:
      if target not in filtered:
        filtered.add(target)
        for filter in self._filters:
          if not filter(target):
            break
        else:
          yield target.address.spec
