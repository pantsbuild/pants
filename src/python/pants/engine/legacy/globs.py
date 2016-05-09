# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.engine.fs import Files as FSFiles
from pants.engine.fs import FileContent, PathGlobs
from pants.engine.nodes import Throw
from pants.source import wrapped_globs
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class BaseGlobs(AbstractClass):
  """An adaptor class to allow BUILD file parsing from ContextAwareObjectFactories."""

  @abstractproperty
  def path_globs_kwarg(self):
    """The name of the `PathGlobs` parameter corresponding to this BaseGlobs instance."""

  @abstractproperty
  def legacy_globs_class(self):
    """The corresponding `wrapped_globs` class for this BaseGlobs."""

  def __init__(self, *patterns, **kwargs):
    self.patterns = patterns
    self.excludes = self.legacy_globs_class.process_raw_excludes(kwargs.pop('exclude', []))

    if kwargs:
      raise ValueError('kwargs not supported for {}. Got: {}'.format(type(self), kwargs))

  def to_fileset_with_spec(self, engine, scheduler, relpath):
    """Return a `FilesetWithSpec` object for these files, computed using the given engine."""
    filespecs = self.legacy_globs_class.to_filespec(self.patterns)
    excluded_patterns = []
    for exclude in self.excludes:
      if isinstance(exclude, BaseGlobs):
        file_set = exclude.to_fileset_with_spec(engine, scheduler, relpath).files
        for file_path in file_set:
          excluded_patterns.append(fast_relpath(file_path, relpath))
      else:
        excluded_patterns.extend(exclude)

    excluded_filespecs = self.legacy_globs_class.to_filespec(excluded_patterns)

    pathglobs = PathGlobs.create_from_specs(FSFiles, relpath, filespecs.get('globs', []))
    excluded_pathglobs = PathGlobs.create_from_specs(FSFiles, relpath, excluded_filespecs.get('globs', []))

    lfc = LazyFilesContent(engine, scheduler, pathglobs, excluded_pathglobs)
    return wrapped_globs.FilesetWithSpec('',
                                         filespecs,
                                         files_calculator=lfc.files,
                                         file_content_calculator=lfc.file_content)


class LazyFilesContent(object):
  def __init__(self, engine, scheduler, pathglobs, excluded_pathglobs):
    self._engine = engine
    self._scheduler = scheduler
    self._pathglobs = pathglobs
    self._excluded_pathglobs = excluded_pathglobs

  @memoized_property
  def _file_contents(self):
    # Execute a request for content for the computed PathGlobs.
    # TODO: It might be useful to split requesting FileContent from requesting Paths, but
    # in realistic cases this just populates caches that will be used for followup builds.
    request = self._scheduler.execution_request([FileContent], [self._pathglobs, self._excluded_pathglobs])
    result = self._engine.execute(request)
    if result.error:
      raise result.error

    included = result.root_products[request.roots[0]]
    excluded = result.root_products[request.roots[1]]

    def _check_throw(pairs):
      for subject, product in pairs:
        if type(product) is Throw:
          raise ValueError('Failed to compute sources for {}: {}'.format(subject, product.exc))

    _check_throw([(self._pathglobs, included), (self._excluded_pathglobs, excluded)])

    excluded_set = set(excluded.value)
    return {fc.path: fc.content for fc in included.value if fc not in excluded_set}

  def files(self):
    return self._file_contents.keys()

  def file_content(self, path):
    return self._file_contents.get(path, None)


class Files(BaseGlobs):
  path_globs_kwarg = 'files'
  legacy_globs_class = wrapped_globs.Globs


class Globs(BaseGlobs):
  path_globs_kwarg = 'globs'
  legacy_globs_class = wrapped_globs.Globs


class RGlobs(BaseGlobs):
  path_globs_kwarg = 'rglobs'
  legacy_globs_class = wrapped_globs.RGlobs


class ZGlobs(BaseGlobs):
  path_globs_kwarg = 'zglobs'
  legacy_globs_class = wrapped_globs.ZGlobs
