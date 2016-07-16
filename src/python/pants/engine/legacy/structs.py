# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractproperty

from six import string_types

from pants.build_graph.address import Addresses
from pants.engine.addressable import Exactly, addressable_list
from pants.engine.fs import PathGlobs
from pants.engine.struct import Struct, StructWithDeps
from pants.source import wrapped_globs
from pants.util.contextutil import exception_logging
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class TargetAdaptor(StructWithDeps):
  """A Struct to imitate the existing Target.

  Extends StructWithDeps to add a `dependencies` field marked Addressable.
  """

  @property
  def has_concrete_sources(self):
    """Returns true if this target has non-deferred sources.

    NB: once ivy is implemented in the engine, we can fetch sources natively here, and/or
    refactor how deferred sources are implemented.
      see: https://github.com/pantsbuild/pants/issues/2997
    """
    sources = getattr(self, 'sources', None)
    return sources is not None and not isinstance(sources, Addresses)

  @property
  def field_adaptors(self):
    """Returns a tuple of Fields for captured fields which need additional treatment."""
    with exception_logging(logger, 'Exception in `field_adaptors` property'):
      if not self.has_concrete_sources:
        return tuple()
      base_globs = BaseGlobs.from_sources_field(self.sources)
      path_globs, excluded_path_globs = base_globs.to_path_globs(self.address.spec_path)
      return (SourcesField(self.address, 'sources', base_globs.filespecs, path_globs, excluded_path_globs),)


class Field(object):
  """A marker for Target(Adaptor) fields for which the engine might perform extra construction."""


class SourcesField(datatype('SourcesField', ['address', 'arg', 'filespecs', 'path_globs', 'excluded_path_globs']), Field):
  """Represents the `sources` argument for a particular Target.

  Sources are currently eagerly computed in-engine in order to provide the `BuildGraph`
  API efficiently; once tasks are explicitly requesting particular Products for Targets,
  lazy construction will be more natural.
    see https://github.com/pantsbuild/pants/issues/3560

  :param address: The Address of the TargetAdaptor for which this field is an argument.
  :param arg: The name of this argument: usually 'sources', but occasionally also 'resources' in the
    case of python resource globs.
  :param filespecs: The merged filespecs dict the describes the paths captured by this field.
  :param path_globs: A PathGlobs describing included files.
  :param excluded_path_globs: A PathGlobs describing files excluded (ie, subtracted) from the
    include set.
  """

  def __eq__(self, other):
    return type(self) == type(other) and self.address == other.address and self.arg == other.arg

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.address)

  def __repr__(self):
    return str(self)

  def __str__(self):
    return 'SourcesField(address={}, arg={}, filespecs={!r})'.format(self.address, self.arg, self.filespecs)


class BundlesField(datatype('BundlesField', ['address', 'bundles', 'filespecs_list', 'path_globs_list', 'excluded_path_globs_list']), Field):
  """Represents the `bundles` argument, each of which has a PathGlobs to represent its `fileset`."""

  def __eq__(self, other):
    return type(self) == type(other) and self.address == other.address

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.address)


class BundleAdaptor(Struct):
  """A Struct to capture the args for the `bundle` object.

  Bundles have filesets which we need to capture in order to execute them in the engine.

  TODO: Bundles should arguably be Targets, but that distinction blurs in the `exp` examples
  package, where a Target is just a collection of configuration.
  """


class JvmAppAdaptor(TargetAdaptor):
  def __init__(self, bundles=None, **kwargs):
    """
    :param list bundles: A list of `BundleAdaptor` objects
    """
    super(JvmAppAdaptor, self).__init__(**kwargs)
    self.bundles = bundles

  @addressable_list(Exactly(BundleAdaptor))
  def bundles(self):
    """The BundleAdaptors for this JvmApp."""
    return self.bundles

  @property
  def field_adaptors(self):
    with exception_logging(logger, 'Exception in `field_adaptors` property'):
      field_adaptors = super(JvmAppAdaptor, self).field_adaptors
      if getattr(self, 'bundles', None) is None:
        return field_adaptors
      # Construct a field for the `bundles` argument.
      filespecs_list = []
      path_globs_list = []
      excluded_path_globs_list = []
      for bundle in self.bundles:
        base_globs = BaseGlobs.from_sources_field(bundle.fileset)
        filespecs_list.append(base_globs.filespecs)
        path_globs, excluded_path_globs = base_globs.to_path_globs(self.address.spec_path)
        path_globs_list.append(path_globs)
        excluded_path_globs_list.append(excluded_path_globs)
      bundles_field = BundlesField(self.address,
                                   self.bundles,
                                   filespecs_list,
                                   path_globs_list,
                                   excluded_path_globs_list)
      return field_adaptors + (bundles_field,)


class PythonTargetAdaptor(TargetAdaptor):
  @property
  def field_adaptors(self):
    with exception_logging(logger, 'Exception in `field_adaptors` property'):
      field_adaptors = super(PythonTargetAdaptor, self).field_adaptors
      if getattr(self, 'resources', None) is None:
        return field_adaptors
      base_globs = BaseGlobs.from_sources_field(self.resources)
      path_globs, excluded_path_globs = base_globs.to_path_globs(self.address.spec_path)
      sources_field = SourcesField(self.address,
                                   'resources',
                                   base_globs.filespecs,
                                   path_globs,
                                   excluded_path_globs)
      return field_adaptors + (sources_field,)


class BaseGlobs(AbstractClass):
  """An adaptor class to allow BUILD file parsing from ContextAwareObjectFactories."""

  @staticmethod
  def from_sources_field(sources):
    """Return a BaseGlobs for the given sources field.

    `sources` may be None, a list/tuple/set, a string or a BaseGlobs instance.
    """
    if sources is None:
      return Files()
    elif isinstance(sources, BaseGlobs):
      return sources
    elif isinstance(sources, string_types):
      return Files(sources)
    elif isinstance(sources, (set, list, tuple)):
      return Files(*sources)
    else:
      raise AssertionError('Could not construct PathGlobs from {}'.format(sources))

  @staticmethod
  def _filespec_for_excludes(raw_excludes):
    if isinstance(raw_excludes, string_types):
      raise ValueError('Excludes of type `{}` are not supported: got "{}"'
                       .format(type(raw_excludes).__name__, raw_excludes))

    excluded_patterns = []
    for raw_exclude in raw_excludes:
      exclude_filespecs = BaseGlobs.from_sources_field(raw_exclude).filespecs
      if exclude_filespecs.get('exclude', []):
        raise ValueError('Nested excludes are not supported: got {}'.format(raw_excludes))
      excluded_patterns.extend(exclude_filespecs.get('globs', []))
    return {'globs': excluded_patterns}

  @abstractproperty
  def path_globs_kwarg(self):
    """The name of the `PathGlobs` parameter corresponding to this BaseGlobs instance."""

  @abstractproperty
  def legacy_globs_class(self):
    """The corresponding `wrapped_globs` class for this BaseGlobs."""

  def __init__(self, *patterns, **kwargs):
    self._filespecs = self.legacy_globs_class.to_filespec(patterns).get('globs', [])
    raw_excludes = kwargs.pop('exclude', [])
    self._excluded_filespecs = self._filespec_for_excludes(raw_excludes).get('globs', [])

    # `follow_links=True` is the default behavior for wrapped globs, so we pop the old kwarg
    # and warn here to bridge the gap from v1->v2 BUILD files.
    follow_links = kwargs.pop('follow_links', None)
    if follow_links is not None:
      logger.warn(
        'Ignoring `follow_links={}` kwarg on glob. Default behavior is to follow all links.'
        .format(follow_links)
      )

    if kwargs:
      raise ValueError('kwargs not supported for {}. Got: {}'.format(type(self), kwargs))

  @property
  def filespecs(self):
    """Return a filespecs dict representing both globs and excludes."""
    return {'globs': self._filespecs, 'exclude': self._excluded_filespecs}

  def to_path_globs(self, relpath):
    """Return two PathGlobs representing the included and excluded Files for these patterns."""
    return (
        PathGlobs.create_from_specs(relpath, self._filespecs),
        PathGlobs.create_from_specs(relpath, self._excluded_filespecs)
      )


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
