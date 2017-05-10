# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import zipfile
from contextlib import contextmanager

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.build_graph.aliased_target import AliasTarget
from pants.build_graph.target import Target
from pants.util.contextutil import open_zip


class SyntheticTargetNotFound(Exception):
  pass


def _get_synthetic_target(target, thrift_dep):
  """Find a thrift target's corresponding synthetic target."""
  for dep in target.dependencies:
    if dep != thrift_dep and dep.is_synthetic and dep.derived_from == thrift_dep:
      return dep
  return None


def _resolve_strict_dependencies(target):
  for declared in target.dependencies:
    if type(declared) in (AliasTarget, Target):
      # Is an alias. Recurse to expand.
      for r in _resolve_strict_dependencies(declared):
        yield r
    else:
      yield declared

    for export in _resolve_exports(declared):
      yield export


def _resolve_exports(target):
  for export in getattr(target, 'exports', []):
    if not isinstance(export, Target):
      addr = Address.parse(export, relative_to=target.address.spec_path)
      export = target._build_graph.get_target(addr)
      if export not in target.dependencies:
        # A target can only export its dependencies.
        raise TargetDefinitionException(target, 'Invalid exports: "{}" is not a dependency of {}'.format(export, target))

    if type(export) in (AliasTarget, Target):
      # If exported target is an alias, expand its dependencies.
      for dep in _resolve_strict_dependencies(export):
        yield dep
    else:
      if isinstance(export, JavaThriftLibrary):
        synthetic_target = _get_synthetic_target(target, export)
        if synthetic_target is None:
          raise SyntheticTargetNotFound('No synthetic target is found for thrift target: {}'.format(export))
        yield synthetic_target
      else:
        yield export

      for exp in _resolve_exports(export):
        yield exp


def strict_dependencies(target, dep_context):
  """Compute the 'strict' compile target dependencies for this target.

  Results the declared dependencies of a target after alias expansion, with the addition
  of compiler plugins and their transitive deps, since compiletime is actually runtime for them.
  """
  for declared in _resolve_strict_dependencies(target):
    if isinstance(declared, dep_context.compiler_plugin_types):
      for r in declared.closure(bfs=True, **dep_context.target_closure_kwargs):
        yield r
    else:
      yield declared


def all_dependencies(target, dep_context):
  """All transitive dependencies of the context's target."""
  for dep in target.closure(bfs=True, **dep_context.target_closure_kwargs):
    yield dep


class DependencyContext(object):
  def __init__(self, compiler_plugin_types, target_closure_kwargs):
    """
    :param compiler_plugins: A dict of compiler plugin target types and their
      additional classpath entries.
    :param target_closure_kwargs: kwargs for the `target.closure` method.
    """
    self.compiler_plugin_types = compiler_plugin_types
    self.target_closure_kwargs = target_closure_kwargs


class CompileContext(object):
  """A context for the compilation of a target.

  This can be used to differentiate between a partially completed compile in a temporary location
  and a finalized compile in its permanent location.
  """

  def __init__(self, target, analysis_file, portable_analysis_file, classes_dir, jar_file,
               log_file, zinc_args_file, sources, strict_deps):
    self.target = target
    self.analysis_file = analysis_file
    self.portable_analysis_file = portable_analysis_file
    self.classes_dir = classes_dir
    self.jar_file = jar_file
    self.log_file = log_file
    self.zinc_args_file = zinc_args_file
    self.sources = sources
    self.strict_deps = strict_deps

  @contextmanager
  def open_jar(self, mode):
    with open_zip(self.jar_file, mode=mode, compression=zipfile.ZIP_STORED) as jar:
      yield jar

  def dependencies(self, dep_context):
    """Yields the compile time dependencies of this target, in the given DependencyContext."""
    if self.strict_deps:
      return strict_dependencies(self.target, dep_context)
    else:
      return all_dependencies(self.target, dep_context)

  @property
  def _id(self):
    return (self.target, self.analysis_file, self.classes_dir)

  def __eq__(self, other):
    return self._id == other._id

  def __ne__(self, other):
    return self._id != other._id

  def __hash__(self):
    return hash(self._id)
