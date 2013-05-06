# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import operator
import re
import sys

import twitter.pants

from twitter.pants import get_buildroot
from twitter.pants.base.address import Address
from twitter.pants.base.target import Target

from twitter.pants.tasks import TaskError
from twitter.pants.tasks.console_task import ConsoleTask


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


def _get_target(address):
  try:
    address = Address.parse(get_buildroot(), address, is_relative=False)
  except IOError as e:
    raise TaskError('Failed to parse address: %s: %s' % (address, e))
  match = Target.get(address)
  if not match:
    raise TaskError('Invalid target address: %s' % address)
  return match


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

  def __init__(self, context, outstream=sys.stdout):
    super(Filter, self).__init__(context, outstream)

    self._filters = []

    def filter_for_address(address):
      match = _get_target(address)
      return lambda target: target == match
    self._filters.extend(_create_filters(context.options.filter_target, filter_for_address))

    def filter_for_type(name):
      try:
        # Try to do a fully qualified import 1st for filtering on custom types.
        from_list, module, type_name = name.rsplit('.', 2)
        module = __import__('%s.%s' % (from_list, module), fromlist=[from_list])
        target_type = getattr(module, type_name)
      except (ImportError, ValueError):
        # Fall back on pants provided target types.
        if not hasattr(twitter.pants, name):
          raise TaskError('Invalid type name: %s' % name)
        target_type = getattr(twitter.pants, name)
      if not issubclass(target_type, Target):
        raise TaskError('Not a Target type: %s' % name)
      return lambda target: isinstance(target, target_type)
    self._filters.extend(_create_filters(context.options.filter_type, filter_for_type))

    def filter_for_ancestor(address):
      ancestor = _get_target(address)
      children = set()
      ancestor.walk(children.add)
      return lambda target: target in children
    self._filters.extend(_create_filters(context.options.filter_ancestor, filter_for_ancestor))

    def filter_for_regex(regex):
      parser = re.compile(regex)
      return lambda target: parser.search(str(target.address))
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
          yield str(target.address)
