# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from colors import black, blue, cyan, green, magenta, red, white

from pants.base.revision import Revision
from pants.option.ranked_value import RankedValue
from pants.task.console_task import ConsoleTask
from pants.version import PANTS_SEMVER


class ExplainOptionsTask(ConsoleTask):
  """Display meta-information about options.

  This "meta-information" includes what values options have, and what values they *used* to have
  before they were overridden by a higher-rank value (eg, a HARDCODED value overridden by a CONFIG
  value and then a cli FLAG value).
  """

  @classmethod
  def register_options(cls, register):
    super(ExplainOptionsTask, cls).register_options(register)
    register('--scope', help='Only show options in this scope.')
    register('--name', help='Only show options with this name.')
    register('--rank', choices=RankedValue.get_names(),
             help='Only show options with at least this importance.')
    register('--show-history', type=bool,
             help='Show the previous values options had before being overridden.')
    register('--only-overridden', type=bool,
             help='Only show values that overrode defaults.')
    register('--skip-inherited', type=bool, default=True,
             help='Do not show inherited options, unless their values differ from their parents.')

  def _scope_filter(self, scope):
    pattern = self.get_options().scope
    return not pattern or scope.startswith(pattern)

  def _option_filter(self, option):
    pattern = self.get_options().name
    if not pattern:
      return True
    pattern = pattern.replace('-', '_')
    return option == pattern

  def _rank_filter(self, rank):
    pattern = self.get_options().rank
    if not pattern:
      return True
    return rank >= RankedValue.get_rank_value(pattern)

  def _rank_color(self, rank):
    if not self.get_options().colors:
      return lambda x: x
    if rank == RankedValue.NONE: return white
    if rank == RankedValue.HARDCODED: return white
    if rank == RankedValue.ENVIRONMENT: return red
    if rank == RankedValue.CONFIG: return blue
    if rank == RankedValue.FLAG: return magenta
    return black

  def _format_scope(self, scope, option):
    scope_color = cyan if self.get_options().colors else lambda x: x
    option_color = blue if self.get_options().colors else lambda x: x
    return '{scope}{option}'.format(
      scope=scope_color('{}.'.format(scope) if scope else ''),
      option=option_color(option),
    )

  def _format_record(self, record):
    value_color = green if self.get_options().colors else lambda x: x
    rank_color = self._rank_color(record.rank)
    return '{value} {rank}'.format(
      value=value_color(str(record.value)),
      rank=rank_color('(from {rank}{details})'.format(
        rank=RankedValue.get_rank_name(record.rank),
        details=' {}'.format(record.details) if record.details else '',
      )),
    )

  def _show_history(self, history):
    for record in reversed(list(history)[:-1]):
      if record.rank > RankedValue.NONE:
        yield '  overrode {}'.format(self._format_record(record))

  def _force_option_parsing(self):
    scopes = filter(self._scope_filter, list(self.context.options.known_scope_to_info.keys()))
    for scope in scopes:
      self.context.options.for_scope(scope)

  def _get_parent_scope_option(self, scope, name):
    if not scope:
      return None, None
    parent_scope = ''
    if '.' in scope:
      parent_scope, _ = scope.rsplit('.', 1)
    options = self.context.options.for_scope(parent_scope)
    try:
      return parent_scope, options[name]
    except AttributeError:
      return None, None

  def console_output(self, targets):
    self._force_option_parsing()
    for scope, options in sorted(self.context.options.tracker.option_history_by_scope.items()):
      if not self._scope_filter(scope):
        continue
      for option, history in sorted(options.items()):
        if not self._option_filter(option):
          continue
        if not self._rank_filter(history.latest.rank):
          continue
        if self.get_options().only_overridden and not history.was_overridden:
          continue
        # Skip the option if it has already passed the deprecation period.
        if history.latest.deprecation_version and PANTS_SEMVER >= Revision.semver(
          history.latest.deprecation_version):
          continue
        if self.get_options().skip_inherited:
          parent_scope, parent_value = self._get_parent_scope_option(scope, option)
          if parent_scope is not None and parent_value == history.latest.value:
            continue
        yield '{} = {}'.format(self._format_scope(scope, option),
                               self._format_record(history.latest))
        if self.get_options().show_history:
          for line in self._show_history(history):
            yield line
