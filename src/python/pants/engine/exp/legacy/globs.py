# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.engine.exp.fs import FileContent, PathGlobs
from pants.engine.exp.nodes import Throw
from pants.source import wrapped_globs
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
    if kwargs:
      # TODO
      raise ValueError('kwargs not supported for {}. Got: {}'.format(type(self), kwargs))

  def to_fileset_with_spec(self, engine, scheduler, relpath):
    """Return a `FilesetWithSpec` object for these files, computed using the given engine.

    TODO: Simplify the engine API. See: https://github.com/pantsbuild/pants/issues/3070
    """
    filespecs = self.legacy_globs_class.to_filespec(self.patterns)
    pathglobs = PathGlobs.create_from_specs(relpath, filespecs.get('globs', []))
    lfc = LazyFilesContent(engine, scheduler, pathglobs)
    return wrapped_globs.FilesetWithSpec('',
                                         filespecs,
                                         files_calculator=lfc.files,
                                         file_content_calculator=lfc.file_content)


class LazyFilesContent(object):
  def __init__(self, engine, scheduler, pathglobs):
    self._engine = engine
    self._scheduler = scheduler
    self._pathglobs = pathglobs

  @memoized_property
  def _file_contents(self):
    # Execute a request for content for the computed PathGlobs.
    # TODO: It might be useful to split requesting FileContent from requesting Paths, but
    # in realistic cases this just populates caches that will be used for followup builds.
    request = self._scheduler.execution_request([FileContent], [self._pathglobs])
    result = self._engine.execute(request)
    if result.error:
      raise result.error
    # Expect a value containing the list of Path results.
    value, = result.root_products.values()
    if type(value) is Throw:
      raise ValueError('Failed to compute sources for {}: {}'.format(self._pathglobs, value.exc))
    return {fc.path: fc.content for fc in value.value}

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
