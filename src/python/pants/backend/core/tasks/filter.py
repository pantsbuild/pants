# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import operator
import re

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.address_lookup_error import AddressLookupError
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
  def register_options(cls, register):
    super(Filter, cls).register_options(register)
    register('--type', action='append',
             help="Target types to include (optional '+' prefix) or exclude ('-' prefix).  "
                  "Multiple type inclusions or exclusions can be specified in a comma-separated "
                  "list or by using multiple instances of this flag.")
    register('--target', action='append',
             help="Targets to include (optional '+' prefix) or exclude ('-' prefix).  Multiple "
                  "target inclusions or exclusions can be specified in a comma-separated list or "
                  "by using multiple instances of this flag.")
    register('--ancestor', action='append',
             help="Dependency targets of targets to include (optional '+' prefix) or exclude "
                  "('-' prefix).  Multiple ancestor inclusions or exclusions can be specified "
                  "in a comma-separated list or by using multiple instances of this flag.")
    register('--regex', action='append',
             help="Regex patterns of target addresses to include (optional '+' prefix) or exclude "
                  "('-' prefix).  Multiple target inclusions or exclusions can be specified "
                  "in a comma-separated list or by using multiple instances of this flag.")
    register('--tag', action='append',
             help="Tags to include (optional '+' prefix) or exclude ('-' prefix).  Multiple "
                  "attribute inclusions or exclusions can be specified in a comma-separated list "
                  "or by using multiple instances of this flag. Format: "
                  "--tag='+foo,-bar'")
    register('--tag-regex', action='append',
             help="Regex patterns of tags to include (optional '+' prefix) or exclude "
                  "('-' prefix).  Multiple attribute inclusions or exclusions can be specified in "
                  "a comma-separated list or by using multiple instances of this flag. Format: "
                  "--tag-regex='+foo,-bar'")

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
    self._filters.extend(_create_filters(self.get_options().target, filter_for_address))

    def filter_for_type(name):
      # FIXME(pl): This should be a standard function provided by the plugin/BuildFileParser
      # machinery
      try:
        # Try to do a fully qualified import 1st for filtering on custom types.
        from_list, module, type_name = name.rsplit('.', 2)
        module = __import__('{}.{}'.format(from_list, module), fromlist=[from_list])
        target_type = getattr(module, type_name)
      except (ImportError, ValueError):
        # Fall back on pants provided target types.
        registered_aliases = self.context.build_file_parser.registered_aliases()
        if name not in registered_aliases.targets:
          raise TaskError('Invalid type name: {}'.format(name))
        target_type = registered_aliases.targets[name]
      if not issubclass(target_type, Target):
        raise TaskError('Not a Target type: {}'.format(name))
      return lambda target: isinstance(target, target_type)
    self._filters.extend(_create_filters(self.get_options().type, filter_for_type))

    def filter_for_ancestor(spec):
      ancestors = _get_targets(spec)
      children = set()
      for ancestor in ancestors:
        ancestor.walk(children.add)
      return lambda target: target in children
    self._filters.extend(_create_filters(self.get_options().ancestor, filter_for_ancestor))

    def filter_for_regex(regex):
      try:
        parser = re.compile(regex)
      except re.error as e:
        raise TaskError("Invalid regular expression: {}: {}".format(regex, e))
      return lambda target: parser.search(str(target.address.spec))
    self._filters.extend(_create_filters(self.get_options().regex, filter_for_regex))

    def filter_for_tag_regex(tag_regex):
      try:
        regex = re.compile(tag_regex)
      except re.error as e:
        raise TaskError("Invalid regular expression: {}: {}".format(tag_regex, e))
      return lambda target: any(map(regex.search, map(str, target.tags)))
    self._filters.extend(_create_filters(self.get_options().tag_regex, filter_for_tag_regex))

    def filter_for_tag(tag):
      return lambda target: tag in map(str, target.tags)
    self._filters.extend(_create_filters(self.get_options().tag, filter_for_tag))

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
