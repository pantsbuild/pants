# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import TargetMacro
from pants.build_graph.target import Target


class AliasTarget(Target):
  """A target that gets replaced by its dependencies."""


class AliasTargetMacro(TargetMacro):
  """Macro for creating target aliases."""

  def __init__(self, parse_context):
    self._parse_context = parse_context

  def expand(self, name=None, target=None, **kwargs):
    """
    :param string name: The name for this alias.
    :param string target: The address of the destination target.
    """
    if name is None:
      raise TargetDefinitionException('{}:?'.format(self._parse_context.rel_path, name),
                                      'The alias() must have a name!')
    if target is None:
      raise TargetDefinitionException('{}:{}'.format(self._parse_context.rel_path, name),
                                      'The alias() must have a "target" parameter.')
    self._parse_context.create_object(
      AliasTarget,
      type_alias='alias',
      name=name,
      dependencies=[target] if target else [],
      **kwargs
    )


class AliasTargetFactory(TargetMacro.Factory):
  """Creates an alias for a target, so that it can be referred to with another spec.

  Note that this does not current work with deferred source (from_target()); you must still use the
  target's actual address in that case.
  """

  @property
  def target_types(self):
    return {AliasTarget}

  def macro(self, parse_context):
    return AliasTargetMacro(parse_context)
