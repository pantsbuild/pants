# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.tasks.target_filter_task_mixin import TargetFilterTaskMixin
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.exceptions import TaskError
from pants.util.filtering import create_filters, wrap_filters


class Filter(TargetFilterTaskMixin, ConsoleTask):
  """Filter the input targets based on various criteria.

  Each of the filtering options below is a comma-separated list of filtering criteria, with an
  implied logical OR between them, so that a target passes the filter if it matches any of the
  criteria in the list.  A '-' prefix inverts the sense of the entire comma-separated list, so that
  a target passes the filter only if it matches none of the criteria in the list.

  Each of the filtering options may be specified multiple times, with an implied logical AND
  between them.
  """

  @classmethod
  def register_options(cls, register):
    super(Filter, cls).register_options(register)
    register('--type', action='append', metavar='[+-]type1,type2,...',
             help='Filter on these target types.')
    register('--target', action='append', metavar='[+-]spec1,spec2,...',
             help='Filter on these target addresses.')
    register('--ancestor', action='append', metavar='[+-]spec1,spec2,...',
             help='Filter on targets that these targets depend on.')
    register('--regex', action='append', metavar='[+-]regex1,regex2,...',
             help='Filter on target addresses matching these regexes.')
    # TODO: Do we need this now that we have a global --tag flag? Deprecate this if not.
    register('--tag', action='append', metavar='[+-]tag1,tag2,...',
             help='Filter on targets with these tags.')
    register('--tag-regex', action='append', metavar='[+-]regex1,regex2,...',
             help='Filter on targets with tags matching these regexes.')

  def __init__(self, *args, **kwargs):
    super(Filter, self).__init__(*args, **kwargs)
    self._filters = []

    def _get_targets(spec):
      try:
        spec_parser = CmdLineSpecParser(get_buildroot(), self.context.address_mapper)
        addresses = spec_parser.parse_addresses(spec)
      except AddressLookupError as e:
        raise TaskError('Failed to parse address selector: {spec}\n {message}'.format(spec=spec, message=e))
      # filter specs may not have been parsed as part of the context: force parsing
      matches = set()
      for address in addresses:
        self.context.build_graph.inject_address_closure(address)
        matches.add(self.context.build_graph.get_target(address))
      if not matches:
        raise TaskError('No matches for address selector: {spec}'.format(spec=spec))
      return matches

    def filter_for_address(spec):
      matches = _get_targets(spec)
      return lambda target: target in matches
    self._filters.extend(create_filters(self.get_options().target, filter_for_address))

    def filter_for_type(name):
      target_types = self.target_types_for_alias(name)
      return lambda target: isinstance(target, tuple(target_types))
    self._filters.extend(create_filters(self.get_options().type, filter_for_type))

    def filter_for_ancestor(spec):
      ancestors = _get_targets(spec)
      children = set()
      for ancestor in ancestors:
        ancestor.walk(children.add)
      return lambda target: target in children
    self._filters.extend(create_filters(self.get_options().ancestor, filter_for_ancestor))

    def filter_for_regex(regex):
      try:
        parser = re.compile(regex)
      except re.error as e:
        raise TaskError("Invalid regular expression: {}: {}".format(regex, e))
      return lambda target: parser.search(str(target.address.spec))
    self._filters.extend(create_filters(self.get_options().regex, filter_for_regex))

    def filter_for_tag_regex(tag_regex):
      try:
        regex = re.compile(tag_regex)
      except re.error as e:
        raise TaskError("Invalid regular expression: {}: {}".format(tag_regex, e))
      return lambda target: any(map(regex.search, map(str, target.tags)))
    self._filters.extend(create_filters(self.get_options().tag_regex, filter_for_tag_regex))

    def filter_for_tag(tag):
      return lambda target: tag in map(str, target.tags)
    self._filters.extend(create_filters(self.get_options().tag, filter_for_tag))

  def console_output(self, _):
    wrapped_filter = wrap_filters(self._filters)
    filtered = set()
    for target in self.context.target_roots:
      if target not in filtered:
        filtered.add(target)
        if wrapped_filter(target):
          yield target.address.spec
