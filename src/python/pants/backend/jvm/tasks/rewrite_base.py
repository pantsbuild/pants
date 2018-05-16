# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod, abstractproperty

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class RewriteBase(NailgunTask, AbstractClass):
  """Abstract base class for JVM-based tools that check/rewrite sources."""

  @classmethod
  def register_options(cls, register):
    super(RewriteBase, cls).register_options(register)
    register('--target-types',
             default=cls.target_types(),
             advanced=True, type=list,
             help='The target types to apply formatting to.')

  @classmethod
  def target_types(cls):
    """Returns a list of target type names (e.g.: `scala_library`) this rewriter operates on."""
    raise NotImplementedError()

  @classmethod
  def source_extension(cls):
    """Returns the source extension this rewriter operates on (e.g.: `.scala`)"""
    raise NotImplementedError()

  @memoized_property
  def _formatted_target_types(self):
    aliases = set(self.get_options().target_types)
    registered_aliases = self.context.build_file_parser.registered_aliases()
    return tuple({target_type
                  for alias in aliases
                  for target_type in registered_aliases.target_types_by_alias[alias]})

  @property
  def cache_target_dirs(self):
    return not self.sideeffecting

  def execute(self):
    """Runs the tool on all source files that are located."""
    relevant_targets = self._get_non_synthetic_targets(self.get_targets())

    if self.sideeffecting:
      # Always execute sideeffecting tasks without invalidation.
      self._execute_for(relevant_targets)
    else:
      # If the task is not sideeffecting we can use invalidation.
      with self.invalidated(relevant_targets) as invalidation_check:
        self._execute_for([vt.target for vt in invalidation_check.invalid_vts])

  def _execute_for(self, targets):
    target_sources = self._calculate_sources(targets)
    if not target_sources:
      return

    result = Xargs(self._invoke_tool_in_place).execute(target_sources)
    if result != 0:
      raise TaskError('{} is improperly implemented: a failed process '
                      'should raise an exception earlier.'.format(type(self).__name__))

  def _invoke_tool_in_place(self, target_sources):
    # Invoke in place.
    result = self.invoke_tool(get_buildroot(), target_sources)
    self.process_result(result)
    return result

  @abstractmethod
  def invoke_tool(self, absolute_root, target_sources):
    """Invoke the tool on the given (target, absolute source) tuples.

    Sources are guaranteed to be located below the given root.

    Returns the UNIX return code of the tool.
    """

  @abstractproperty
  def sideeffecting(self):
    """True if this command has sideeffects: ie, mutates the working copy."""

  @abstractmethod
  def process_result(self, return_code):
    """Given a return code, process the result of the tool.

    No return value is expected. If an error occurred while running the tool, raising a TaskError
    with a useful error message is required.
    """

  def _get_non_synthetic_targets(self, targets):
    return filter(
      lambda target: isinstance(target, self._formatted_target_types)
                     and target.has_sources(self.source_extension())
                     and (not target.is_synthetic),
      targets)

  def _calculate_sources(self, targets):
    return [(target, os.path.join(get_buildroot(), source))
            for target in targets
            for source in target.sources_relative_to_buildroot()
            if source.endswith(self.source_extension())]
