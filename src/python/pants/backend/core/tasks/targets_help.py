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

  # TODO(Travis Crawford): Eliminate this mapping once pants has been moved to Github.
  # Since pants already aliases Target names, the ideal way of doing this would be:
  #
  #   (a) Add a method to all Target objects that provides their alias, rather
  #       than renaming elsewhere. This way Target instances are self-contained.
  #       Of course, if BUILD files used a template system this would not be necessary.
  #
  #       @classmethod
  #       def get_alias(cls):
  #         raise ValueError('subclasses must override alias name.')
  #
  #   (b) Replace aliases with something like:
  #       https://cgit.twitter.biz/science/tree/src/python/pants/__init__.py#n88
  #
  #       to_alias = [AnnotationProcessor, ...]
  #       for t in to_alias:
  #         vars()[t.get_alias()] = t
  TARGET_TO_ALIAS = {
    'AndroidBinary': 'android_binary',
    'AndroidResources': 'android_resources',
    'AnnotationProcessor': 'annotation_processor',
    'Artifact': 'artifact',
    'Benchmark': 'benchmark',
    'Bundle': 'bundle',
    'Credentials': 'credentials',
    'JarLibrary': 'dependencies',
    'PythonEgg': 'egg',
    'Exclude': 'exclude',
    'Pants': 'fancy_pants',
    'JarDependency': 'jar',
    'JavaLibrary': 'java_library',
    'JavaAntlrLibrary': 'java_antlr_library',
    'JavaProtobufLibrary': 'java_protobuf_library',
    'JavaTests': 'junit_tests',
    'JavaThriftLibrary': 'java_thrift_library',
    'JavaThriftstoreDMLLibrary': 'java_thriftstore_dml_library',
    'JvmBinary': 'jvm_binary',
    'JvmApp': 'jvm_app',
    # For testing. When targets define their own alias (or we use a template
    # system for BUILD files) this need to register targets goes away.
    'MyTarget': 'my_target',
    'OinkQuery': 'oink_query',
    'Page': 'page',
    'PythonArtifact': 'python_artifact',
    'PythonBinary': 'python_binary',
    'PythonLibrary': 'python_library',
    'PythonAntlrLibrary': 'python_antlr_library',
    'PythonRequirement': 'python_requirement',
    'PythonThriftLibrary': 'python_thrift_library',
    'PythonTests': 'python_tests',
    'Repository': 'repo',
    'Resources': 'resources',
    'ScalaLibrary': 'scala_library',
    'ScalaTests': 'scala_specs',
    'ScalacPlugin': 'scalac_plugin',
    'SourceRoot': 'source_root',
    'ThriftJar': 'thrift_jar',
    'ThriftLibrary': 'thrift_library',
    'Wiki': 'wiki',
  }

  ALIAS_TO_TARGET = {}
  MAX_ALIAS_LEN = 0

  for k, v in TARGET_TO_ALIAS.items():
    ALIAS_TO_TARGET[v] = k
    MAX_ALIAS_LEN = max(MAX_ALIAS_LEN, len(v))

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(TargetsHelp, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("details"), dest="goal_targets_details", default=None,
                            help='Display detailed information about the specific target type.')

  def console_output(self, targets):
    """Display a list of installed target types, or details about a specific target type."""
    target_types = {}
    for target_type in SourceRoot._ROOTS_BY_TYPE.keys():
      target_types[target_type.__name__] = target_type

    if self.context.options.goal_targets_details is None:
      return self._get_installed_targets(target_types)
    else:
      return self._get_details(target_types[self.ALIAS_TO_TARGET[self.context.options.goal_targets_details]])

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
  def _get_installed_targets(target_types):
    """List installed targets and their one-line description."""
    lines = [TargetsHelp.INSTALLED_TARGETS_HEADER]
    for target_type in sorted(target_types.keys()):
      if target_types[target_type].__doc__ is None:
        desc = 'Description unavailable.'
      else:
        desc = target_types[target_type].__doc__.split('\n')[0]
      lines.append('  %s: %s' % (
        TargetsHelp.TARGET_TO_ALIAS[target_type].rjust(TargetsHelp.MAX_ALIAS_LEN), desc))
    return lines

  @staticmethod
  def _get_details(target):
    """Get detailed help for the given target."""
    assert target is not None and issubclass(target, Target)

    arg_spec = inspect.getargspec(target.__init__)
    arg_help = TargetsHelp._get_arg_help(target.__init__.__doc__)

    min_default_idx = 0
    if arg_spec.defaults is None:
      min_default_idx = len(arg_spec.args)
    elif len(arg_spec.args) > len(arg_spec.defaults):
      min_default_idx = len(arg_spec.args) - len(arg_spec.defaults)

    lines = [TargetsHelp.DETAILS_HEADER.substitute(
      name=TargetsHelp.TARGET_TO_ALIAS[target.__name__], desc=target.__doc__)]

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
