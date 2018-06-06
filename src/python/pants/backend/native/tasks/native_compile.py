# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from abc import abstractmethod
from collections import defaultdict

from pants.backend.native.targets.native_library import NativeLibrary
# FIXME: when i deleted toolchain_task.py, it kept using the .pyc file. this shouldn't happen (the
# import should have failed)!!!
from pants.backend.native.tasks.native_task import NativeTask
from pants.base.exceptions import TaskError
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import SubclassesOf, datatype


class NativeSourcesByType(datatype(['rel_root', 'headers', 'sources'])):
  """???"""


# TODO: verify that filenames are valid fileNAMES and not deeper paths? does this matter?
class ObjectFiles(datatype(['root_dir', 'filenames'])):

  def file_paths(self):
    return [os.path.join(self.root_dir, fname) for fname in self.filenames]


class NativeCompile(NativeTask):

  @classmethod
  def product_types(cls):
    return [ObjectFiles]

  @property
  def cache_target_dirs(self):
    return True

  # FIXME: add NB: to note how you have to override this or whatever
  default_header_file_extensions = None
  default_source_file_extensions = None

  @classmethod
  def register_options(cls, register):
    super(NativeCompile, cls).register_options(register)

    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='???/The default for the "fatal_warnings" argument for targets of this language.')

    # TODO(cosmicexplorer): make a list of file extension option type?
    register('--header-file-extensions', type=list, default=cls.default_header_file_extensions,
             fingerprint=True, advanced=True,
             help='???/the allowed file extensions, as a list of strings (file extensions)')
    register('--source-file-extensions', type=list, default=cls.default_source_file_extensions,
             fingerprint=True, advanced=True,
             help='???/the allowed file extensions, as a list of strings (file extensions)')

  @classmethod
  def implementation_version(cls):
    return super(NativeCompile, cls).implementation_version() + [('NativeCompile', 0)]

  class NativeCompileError(TaskError):
    """???"""

  # NB: these are not provided by NativeTask, but are a convention.
  # TODO: mention that you gotta override at least the source target constraint (???)
  source_target_constraint = None
  dependent_target_constraint = SubclassesOf(NativeLibrary)

  def execute(self):
    object_files_product = self.context.products.get(ObjectFiles)
    source_targets = self.context.targets(self.source_target_constraint.satisfied_by)

    with self.invalidated(source_targets, invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if vt.valid:
          object_files = self.collect_cached_objects(vt)
        else:
          object_files = self.compile(vt)

        object_files_product.add(vt.target, vt.target.target_base).append(object_files)

  @memoized_method
  def include_dirs_for_target(self, target):
    deps = self.native_deps(target)
    sources_fields = [dep_tgt.sources_relative_to_target_base() for dep_tgt in deps]
    return [src_field.rel_root for src_field in sources_fields]

  @memoized_property
  def _header_exts(self):
    return self.get_options().header_file_extensions

  @memoized_property
  def _source_exts(self):
    return self.get_options().source_file_extensions

  @memoized_method
  def get_sources_headers_for_target(self, target):
    header_extensions = self._header_exts
    source_extensions = self._source_exts

    header_files = []
    source_files = []
    # Relative to source root so the exception message makes sense.
    target_relative_sources = target.sources_relative_to_target_base()
    rel_root = target_relative_sources.rel_root
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
        dashed_options_scope = re.sub(r'\.', '-', self.options_scope)
        raise self.NativeCompileError(
          "Source file '{source_file}' for target '{target}' "
          "does not have any of this task's known file extensions. "
          "The known file extensions can be extended with the below options:\n"
          "--{processed_scope}-header-file-extensions: (value was: {header_exts})\n"
          "--{processed_scope}-source-file-extensions: (value was: {source_exts})"
          .format(source_file=src,
                  target=target.address.spec,
                  processed_scope=dashed_options_scope,
                  header_exts=header_extensions,
                  source_exts=source_extensions))

    self.context.log.debug("header_files: {}".format(header_files))
    self.context.log.debug("source_files: {}".format(source_files))

    # Unique file names are required because we just dump object files into a single directory, and
    # the compiler will silently just produce a single object file if provided non-unique filenames.
    # TODO(cosmicexplorer): add some shading to file names so we can remove this check.
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
    self.context.log.debug("target: {}, target.target_base: {}, source root: {}, rel_path: {}, headers_for_compile: {}, sources_for_compile: {}"
                           .format(target, target.target_base, target._sources_field.source_root, target._sources_field.rel_path, headers_for_compile, sources_for_compile))
    return NativeSourcesByType(rel_root, headers_for_compile, sources_for_compile)

  # TODO: document how these two are supposed to both produce an ObjectFiles (getting from the cache
  # vs getting from a compile).
  @abstractmethod
  def collect_cached_objects(self, versioned_target):
    """???/use vt.results_dir!"""

  @abstractmethod
  def compile(self, versioned_target):
    """???"""
