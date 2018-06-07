# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod
from collections import defaultdict

from pants.backend.native.config.environment import Executable
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.native_task import NativeTask
from pants.base.exceptions import TaskError
from pants.build_graph.dependency_context import DependencyContext
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import SubclassesOf, datatype


class NativeCompileRequest(datatype([
    ('compiler', SubclassesOf(Executable)),
    # TODO: add type checking for Collection.of(<type>)!
    'include_dirs',
    'sources',
    ('fatal_warnings', bool),
    'output_dir',
])): pass


# TODO: verify that filenames are valid fileNAMES and not deeper paths? does this matter?
class ObjectFiles(datatype(['root_dir', 'filenames'])):

  def file_paths(self):
    return [os.path.join(self.root_dir, fname) for fname in self.filenames]


# FIXME: this is a temporary hack -- we could introduce something like a "NativeRequirement" with
# dependencies, header, object file, library name (more?) instead of using multiple products.
class NativeTargetDependencies(datatype(['native_deps'])): pass


class NativeCompile(NativeTask):

  @classmethod
  def product_types(cls):
    return [ObjectFiles, NativeTargetDependencies]

  @property
  def cache_target_dirs(self):
    return True

  @abstractmethod
  def get_compile_settings(self):
    """An instance of `NativeCompileSettings` which is used in `NativeCompile`.

    :return: :class:`pants.backend.native.subsystems.native_compile_settings.NativeCompileSettings`
    """

  @memoized_property
  def _compile_settings(self):
    return self.get_compile_settings()

  @classmethod
  def implementation_version(cls):
    return super(NativeCompile, cls).implementation_version() + [('NativeCompile', 0)]

  @memoized_property
  def _header_file_extensions(self):
    return self._compile_settings.get_options().header_file_extensions

  @memoized_property
  def _source_file_extensions(self):
    return self._compile_settings.get_options().source_file_extensions

  class NativeCompileError(TaskError):
    """Raised for errors in this class's logic.

    Subclasses are advised to create their own exception class.
    """

  # `NativeCompile` will use the `source_target_constraint` to determine what targets have "sources"
  # to compile, and the `dependent_target_constraint` to determine which dependent targets to
  # operate on for `strict_deps` calculation.
  # NB: `source_target_constraint` must be overridden.
  source_target_constraint = None
  dependent_target_constraint = SubclassesOf(NativeLibrary)

  def native_deps(self, target):
    return self.strict_deps_for_target(
      target, predicate=self.dependent_target_constraint.satisfied_by)

  def strict_deps_for_target(self, target, predicate=None):
    """Get the dependencies of `target` filtered by `predicate`, accounting for 'strict_deps'.

    If 'strict_deps' is on, instead of using the transitive closure of dependencies, targets will
    only be able to see their immediate dependencies declared in the BUILD file. The 'strict_deps'
    setting is obtained from the result of `get_compile_settings()`.

    NB: This includes the current target in the result.
    """
    if self._compile_settings.get_subsystem_target_mirrored_field_value('strict_deps', target):
      strict_deps = target.strict_dependencies(DependencyContext())
      if predicate:
        filtered_deps = filter(predicate, strict_deps)
      else:
        filtered_deps = strict_deps
      deps = [target] + filtered_deps
    else:
      deps = self.context.build_graph.transitive_subgraph_of_addresses(
        [target.address], predicate=predicate)

    return deps

  @staticmethod
  def _add_product_at_target_base(product_mapping, target, value):
    product_mapping.add(target, target.target_base).append(value)

  def execute(self):
    object_files_product = self.context.products.get(ObjectFiles)
    native_deps_product = self.context.products.get(NativeTargetDependencies)
    source_targets = self.context.targets(self.source_target_constraint.satisfied_by)

    with self.invalidated(source_targets, invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.invalid_vts:
        deps = self.native_deps(vt.target)
        self._add_product_at_target_base(native_deps_product, vt.target, deps)
        compile_request = self._make_compile_request(vt, deps)
        self.context.log.debug("compile_request: {}".format(compile_request))
        self.compile(compile_request)

      for vt in invalidation_check.all_vts:
        object_files = self.collect_cached_objects(vt)
        self._add_product_at_target_base(object_files_product, vt.target, object_files)

  # This may be calculated many times for a target, so we memoize it.
  @memoized_method
  def _include_dirs_for_target(self, target):
    return target.sources_relative_to_target_base().rel_root

  class NativeSourcesByType(datatype(['rel_root', 'headers', 'sources'])): pass

  def get_sources_headers_for_target(self, target):
    """Split a target's sources into header and source files.

    This method will use the result of `get_compile_settings()` to get the extensions belonging to
    header and source files, and then it will group the sources by those extensions.

    :return: :class:`NativeCompile.NativeSourcesByType`
    :raises: :class:`NativeCompile.NativeCompileError` if there is an error processing the sources.
    """
    header_extensions = self._header_file_extensions
    source_extensions = self._source_file_extensions

    header_files = []
    source_files = []
    # Get source paths relative to the target base so the exception message with the target and
    # paths makes sense.
    target_relative_sources = target.sources_relative_to_target_base()
    rel_root = target_relative_sources.rel_root

    # Group the sources by extension. Check whether a file has an extension using `endswith()`.
    for src in target_relative_sources:
      found_file_ext = None
      for h_ext in header_extensions:
        if src.endswith(h_ext):
          header_files.append(src)
          found_file_ext = h_ext
          continue
      if found_file_ext:
        continue
      for s_ext in source_extensions:
        if src.endswith(s_ext):
          source_files.append(src)
          found_file_ext = s_ext
          continue
      if not found_file_ext:
        # TODO: test this error!
        raise self.NativeCompileError(
          "Source file '{source_file}' for target '{target}' "
          "does not have any of this task's known file extensions. "
          "The known file extensions can be extended with the below options:\n"
          "--{processed_scope}-header-file-extensions: (value was: {header_exts})\n"
          "--{processed_scope}-source-file-extensions: (value was: {source_exts})"
          .format(source_file=src,
                  target=target.address.spec,
                  processed_scope=self.get_options_scope_equivalent_flag_component(),
                  header_exts=header_extensions,
                  source_exts=source_extensions))

    # Unique file names are required because we just dump object files into a single directory, and
    # the compiler will silently just produce a single object file if provided non-unique filenames.
    # TODO: add some shading to file names so we can remove this check.
    seen_filenames = defaultdict(list)
    for src in source_files:
      seen_filenames[os.path.basename(src)].append(src)
    duplicate_filename_err_msgs = []
    for fname, source_paths in seen_filenames.items():
      if len(source_paths) > 1:
        duplicate_filename_err_msgs.append("filename: {}, paths: {}".format(fname, source_paths))
    if duplicate_filename_err_msgs:
      raise self.NativeCompileError(
        "Error in target '{}': source files must have a unique filename within a '{}' target. "
        "Conflicting filenames:\n{}"
        .format(target.address.spec, target.alias(), '\n'.join(duplicate_filename_err_msgs)))

    headers_for_compile = [os.path.join(rel_root, h) for h in header_files]
    sources_for_compile = [os.path.join(rel_root, s) for s in source_files]

    return self.NativeSourcesByType(rel_root, headers_for_compile, sources_for_compile)

  @abstractmethod
  def get_compiler(self):
    """An instance of `Executable` which can be invoked to compile files.

    :return: :class:`pants.backend.native.config.environment.Executable`
    """

  @memoized_property
  def _compiler(self):
    return self.get_compiler()

  def _make_compile_request(self, versioned_target, dependencies):
    target = versioned_target.target
    include_dirs = [self._include_dirs_for_target(dep_tgt) for dep_tgt in dependencies]
    sources_by_type = self.get_sources_headers_for_target(target)
    return NativeCompileRequest(
      compiler=self._compiler,
      include_dirs=include_dirs,
      sources=sources_by_type.sources,
      fatal_warnings=self._compile_settings.get_subsystem_target_mirrored_field_value(
        'fatal_warnings', target),
      output_dir=versioned_target.results_dir)

  @abstractmethod
  def compile(self, compile_request):
    """Perform the process of compilation, writing object files to the request's 'output_dir'.

    NB: This method must arrange the output files so that `collect_cached_objects()` can collect all
    of the results (or vice versa)!
    """

  def collect_cached_objects(self, versioned_target):
    """Scan `versioned_target`'s results directory and return the output files from that directory.

    :return: :class:`ObjectFiles`
    """
    return ObjectFiles(versioned_target.results_dir, os.listdir(versioned_target.results_dir))
