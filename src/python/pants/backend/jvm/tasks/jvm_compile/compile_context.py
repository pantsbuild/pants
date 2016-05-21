# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import zipfile
from contextlib import contextmanager

from pants.build_graph.target import Target
from pants.util.contextutil import open_zip
from pants.util.memo import memoized_property


class DependencyContext(object):
  def __init__(self, compiler_plugins, target_closure_kwargs):
    """
    :param compiler_plugins: A dict of compiler plugin target types and their
      additional classpath entries.
    :param target_closure_kwargs: kwargs for the `target.closure` method.
    """
    self.compiler_plugins = compiler_plugins
    self.target_closure_kwargs = target_closure_kwargs

  @memoized_property
  def compiler_plugin_types(self):
    return tuple(self.compiler_plugins.keys())


class CompileContext(object):
  """A context for the compilation of a target.

  This can be used to differentiate between a partially completed compile in a temporary location
  and a finalized compile in its permanent location.
  """

  def __init__(self, target, analysis_file, portable_analysis_file, classes_dir, jar_file,
               log_file, sources, strict_deps):
    self.target = target
    self.analysis_file = analysis_file
    self.portable_analysis_file = portable_analysis_file
    self.classes_dir = classes_dir
    self.jar_file = jar_file
    self.log_file = log_file
    self.sources = sources
    self.strict_deps = strict_deps

  @contextmanager
  def open_jar(self, mode):
    with open_zip(self.jar_file, mode=mode, compression=zipfile.ZIP_STORED) as jar:
      yield jar

  def dependencies(self, dep_context):
    """Yields the compile time dependencies of this target, in the given DependencyContext."""
    if self.strict_deps:
      return self.strict_dependencies(dep_context)
    else:
      return self.all_dependencies(dep_context)

  def _plugin_dependencies(self, dep_context):
    """If this target is a compiler plugin, yields additional compiler plugin dependencies."""
    for plugin_dep in dep_context.compiler_plugins.get(type(self.target), []):
      yield plugin_dep

  def declared_dependencies(self, dep_context, compiler_plugins=True, exported=True):
    """Compute the declared dependencies for this target, recursively resolving target aliases.

    TODO: Formalize the `exported` tag.
    TODO: Switch to using scopes rather than types to identify plugins.
    TODO: Consider moving this API to `Target`.
    TODO: Javac plugins/processors should use -processorpath instead of the classpath.
    """
    def resolve(t):
      for declared in t.dependencies:
        if type(declared) == Target:
          # Is an alias. Recurse to expand.
          for r in resolve(declared):
            yield r
        elif 'exported' in declared.tags:
          # Is exported: include the target and its declared dependencies.
          if exported:
            yield declared
            for r in resolve(declared):
              yield r
        elif isinstance(declared, dep_context.compiler_plugin_types):
          if compiler_plugins:
            yield declared
        else:
          yield declared

    for dep in resolve(self.target):
      yield dep

  def strict_dependencies(self, dep_context):
    """Compute the 'strict' compile target dependencies for this target.

    Results in a list similar to the list for `declared_dependencies`, with the addition
    of compiler plugins and their transitive deps, since compiletime is actually runtime for them.
    """
    for dep in self._plugin_dependencies(dep_context):
      yield dep
    yield self.target
    for declared in self.declared_dependencies(dep_context, compiler_plugins=True):
      if isinstance(declared, dep_context.compiler_plugin_types):
        for r in declared.closure(bfs=True, **dep_context.target_closure_kwargs):
          yield r
      else:
        yield declared

  def all_dependencies(self, dep_context):
    """All transitive dependencies of the context's target."""
    for dep in self._plugin_dependencies(dep_context):
      yield dep
    for dep in self.target.closure(bfs=True, **dep_context.target_closure_kwargs):
      yield dep

  @property
  def _id(self):
    return (self.target, self.analysis_file, self.classes_dir)

  def __eq__(self, other):
    return self._id == other._id

  def __ne__(self, other):
    return self._id != other._id

  def __hash__(self):
    return hash(self._id)
