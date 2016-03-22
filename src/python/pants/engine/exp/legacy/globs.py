# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty
from hashlib import sha1

from pants.engine.exp.fs import PathGlobs
from pants.engine.exp.nodes import Throw
from pants.source import wrapped_globs
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Lobs(AbstractClass):
  @abstractproperty
  def path_globs_kwarg(self):
    pass

  @abstractproperty
  def legacy_globs_class(self):
    pass

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
    def calc_files():
      pathglobs = PathGlobs.create_from_specs(relpath, filespecs.get('globs', []))
      # Execute a request for the Paths for the computed PathGlobs.
      request = scheduler.execution_request([FileFingerprint], [engine.storage.put(pathglobs)])
      result = engine.execute(request)
      if result.error:
        raise result.error
      # Expect a value containing the list of Path results.
      value_key, = result.root_products.values()
      value = engine.storage.get(value_key)
      if type(value) is Throw:
        raise ValueError('Failed to compute sources for {} relative to {}: {}'.format(
          self.patterns, relpath, value.exc))
      return [p.path for p in value.value]
    return wrapped_globs.FilesetWithSpec('', filespecs, calc_files)


class Files(Lobs):
  path_globs_kwarg = 'files'
  legacy_globs_class = wrapped_globs.Globs


class Globs(Lobs):
  path_globs_kwarg = 'globs'
  legacy_globs_class = wrapped_globs.Globs


class RGlobs(Lobs):
  path_globs_kwarg = 'rglobs'
  legacy_globs_class = wrapped_globs.RGlobs


class ZGlobs(Lobs):
  path_globs_kwarg = 'zglobs'
  legacy_globs_class = wrapped_globs.ZGlobs


class FileFingerprint(datatype('FileFingerprint', ['path', 'fingerprint'])):
  """The sha1 of a file.

  NB: This is a support shim to give the ExpGraph access to a file fingerprint. Tasks that
  run _in_ the engine are automatically invalidated, and thus do not need explicit access
  to fingerprints.
  """


def file_fingerprint(file_content):
  """Given a FileContent, return a FileFingerprint object."""
  content = file_content.content
  fingerprint = sha1(content).hexdigest() if content is not None else '<does not exist>'
  return FileFingerprint(file_content.path, fingerprint)
