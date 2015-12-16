# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from colors import blue, cyan, green

from pants.help.build_dictionary_info_extracter import BuildDictionaryInfoExtracter
from pants.task.console_task import ConsoleTask


class TargetsHelp(ConsoleTask):
  """List available target types."""

  @classmethod
  def register_options(cls, register):
    super(TargetsHelp, cls).register_options(register)
    register('--details', help='Show details about this target type.')

  def console_output(self, targets):
    buildfile_aliases = self.context.build_file_parser.registered_aliases()
    extracter = BuildDictionaryInfoExtracter(buildfile_aliases)

    alias = self.get_options().details
    if alias:
      target_types = buildfile_aliases.target_types_by_alias.get(alias)
      if target_types:
        tti = next(x for x in extracter.get_target_type_info() if x.build_file_alias == alias)
        yield blue('\n{}\n'.format(tti.description))
        yield blue('{}('.format(alias))

        for arg in extracter.get_target_args(list(target_types)[0]):
          default = green('(default: {})'.format(arg.default) if arg.has_default else '')
          yield '{:<30} {}'.format(
            cyan('  {} = ...,'.format(arg.name)),
            ' {}{}{}'.format(arg.description, ' ' if arg.description else '', default))

        yield blue(')')
      else:
        yield 'No such target type: {}'.format(alias)
    else:
      for tti in extracter.get_target_type_info():
        description = tti.description or '<Add description>'
        yield '{} {}'.format(cyan('{:>30}:'.format(tti.build_file_alias)), description)
