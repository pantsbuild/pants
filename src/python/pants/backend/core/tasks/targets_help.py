# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import inspect
import textwrap
from string import Template

from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.backend.core.tasks.console_task import ConsoleTask


class TargetsHelp(ConsoleTask):
  """Provides online help for installed targets.

  This task provides online help modes for installed targets. Without args,
  all installed targets are listed with their one-line description.
  An optional flag allows users to specify a target they want detailed
  help about."""

  INSTALLED_TARGETS_HEADER = '\n'.join([
    'For details about a specific target, try: ./pants goal targets --targets-details=target_name',
    'Installed target types:\n',
  ])

  DETAILS_HEADER = Template('TARGET NAME\n\n  $name -- $desc\n\nTARGET ARGUMENTS\n')


  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(TargetsHelp, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("details"), dest="goal_targets_details", default=None,
                            help='Display detailed information about the specific target type.')

  def console_output(self, targets):
    """Display a list of installed target types, or details about a specific target type."""

    # To illustrate and avoid confusion on various terms target_????, here is one example:
    # target_type: <class 'pants.backend.jvm.targets.jar_library.JarLibrary'>
    # target_alias: jar_library
    installed_target_aliases_to_target_types = self.get_installed_target_aliases_to_target_types()

    # get the optional target alias, if specified, on command line.
    target_alias = self.context.options.goal_targets_details

    if target_alias is None:
      return self._get_installed_targets(installed_target_aliases_to_target_types)
    if target_alias not in installed_target_aliases_to_target_types.keys():
      raise ValueError("Invalid target alias '{target_alias}'.\n{installed_targets}"
          .format(
              target_alias=target_alias,
              installed_targets='\n'.join(
                  self._get_installed_targets(installed_target_aliases_to_target_types))))
    target_type = installed_target_aliases_to_target_types[target_alias]

    return self._get_details(target_alias, target_type)


  def get_installed_target_aliases_to_target_types(self):
    all_target_aliases_to_target_types = self.context.build_file_parser.registered_aliases().targets
    installed_target_types = SourceRoot._ROOTS_BY_TYPE.keys()
    result = {}
    for target_alias, target_type in all_target_aliases_to_target_types.items():
      if target_type in installed_target_types:
        result[target_alias] = target_type
    return result


  @staticmethod
  def _get_arg_help(docstring):
    """Given a docstring, return a map of arg to help string.

    Pants target constructor docstrings should document arguments as follows.
    Note constructor docstrings only document arguments. All documentation about
    the class itself belong in the class docstring.

    myarg: the description
    anotherarg: this description is continued
      on the next line"""
    arg_help = {}

    if docstring is None:
      return arg_help

    last = None
    import re
    for line in docstring.split('\n'):
      if line == '':
        continue
      match = re.search('^\s*:param[\w ]* (\w+):\s(.*)$', line)
      if match:
        last = match.group(1)
        arg_help[last] = match.group(2)
      else:
        arg_help[last] += ' %s' % line.strip()
    return arg_help


  @staticmethod
  def _get_installed_targets(installed_target_aliases_to_target_types):
    """List installed targets and their one-line description."""

    target_aliases = installed_target_aliases_to_target_types.keys()
    max_alias_length = max(len(target_alias) for target_alias in target_aliases)

    lines = [TargetsHelp.INSTALLED_TARGETS_HEADER]
    for target_alias in sorted(target_aliases):
      if installed_target_aliases_to_target_types[target_alias].__doc__ is None:
        desc = 'Description unavailable.'
      else:
        desc = installed_target_aliases_to_target_types[target_alias].__doc__.split('\n')[0]
      lines.append('  %s: %s' % (target_alias.rjust(max_alias_length), desc))
    return lines


  @staticmethod
  def _get_details(target_alias, target_type):
    """Get detailed help for the given target type."""
    assert target_type is not None and issubclass(target_type, Target)

    arg_spec = inspect.getargspec(target_type.__init__)
    arg_help = TargetsHelp._get_arg_help(target_type.__init__.__doc__)

    min_default_idx = 0
    if arg_spec.defaults is None:
      min_default_idx = len(arg_spec.args)
    elif len(arg_spec.args) > len(arg_spec.defaults):
      min_default_idx = len(arg_spec.args) - len(arg_spec.defaults)

    lines = [TargetsHelp.DETAILS_HEADER.substitute(name=target_alias, desc=target_type.__doc__)]

    max_width = 0
    for arg in arg_spec.args:
      max_width = max(max_width, len(arg))

    wrapper = textwrap.TextWrapper(subsequent_indent=' '*(max_width+4))

    for idx, val in enumerate(arg_spec.args):
      has_default = False
      default_val = None

      if idx >= min_default_idx:
        has_default = True
        default_val = arg_spec.defaults[idx-min_default_idx]

      if val == 'self':
        continue
      help_str = 'No help available for this argument.'
      try:
        help_str = arg_help[val]
      except KeyError:
        pass
      if has_default:
        help_str += ' (default: %s) ' % str(default_val)
      lines.append('  %s: %s' % (val.rjust(max_width), '\n'.join(wrapper.wrap(help_str))))
    return lines
