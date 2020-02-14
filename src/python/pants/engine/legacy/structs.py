# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os.path
from abc import ABCMeta, abstractmethod
from collections.abc import MutableSequence, MutableSet
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple, Type, Union, cast

from pants.base.specs import OriginSpec
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.engine.addressable import addressable_list
from pants.engine.fs import GlobExpansionConjunction, PathGlobs
from pants.engine.objects import Locatable, union
from pants.engine.rules import UnionRule
from pants.engine.struct import Struct, StructWithDeps
from pants.source import wrapped_globs
from pants.util.contextutil import exception_logging
from pants.util.meta import classproperty
from pants.util.objects import Exactly


logger = logging.getLogger(__name__)


class TargetAdaptor(StructWithDeps):
  """A Struct to imitate the existing Target.

  Extends StructWithDeps to add a `dependencies` field marked Addressable.
  """

  @property
  def address(self) -> Address:
    # TODO: this isn't actually safe to override as not being Optional. There are
    # some cases where this property is not defined. But, then we get a ton of MyPy issues.
    return cast(Address, super().address)

  def get_sources(self) -> Optional["GlobsWithConjunction"]:
    """Returns target's non-deferred sources if exists or the default sources if defined.

    NB: once ivy is implemented in the engine, we can fetch sources natively here, and/or
    refactor how deferred sources are implemented.
      see: https://github.com/pantsbuild/pants/issues/2997
    """
    source = getattr(self, 'source', None)
    sources = getattr(self, 'sources', None)

    if source is not None and sources is not None:
      raise Target.IllegalArgument(
        self.address.spec,
        'Cannot specify both source and sources attribute.'
      )

    if source is not None:
      if not isinstance(source, str):
        raise Target.IllegalArgument(
          self.address.spec,
          f"source must be a str containing a path relative to the target, but got {source} of "
          f"type {type(source)}"
        )
      sources = [source]

    # N.B. Here we check specifically for `sources is None`, as it's possible for sources
    # to be e.g. an explicit empty list (sources=[]).
    if sources is None:
      if self.default_sources_globs is None:
        return None
      default_globs = Files(
        *(
          *self.default_sources_globs,
          *(f"!{glob}" for glob in self.default_sources_exclude_globs or []),
        ),
        spec_path=self.address.spec_path,
      )
      return GlobsWithConjunction(default_globs, GlobExpansionConjunction.any_match)

    globs = BaseGlobs.from_sources_field(sources, self.address.spec_path)
    return GlobsWithConjunction(globs, GlobExpansionConjunction.all_match)

  @property
  def field_adaptors(self) -> Tuple:
    """Returns a tuple of Fields for captured fields which need additional treatment."""
    with exception_logging(logger, 'Exception in `field_adaptors` property'):
      conjunction_globs = self.get_sources()
      if conjunction_globs is None:
        return tuple()

      sources = conjunction_globs.non_path_globs
      if not sources:
        return tuple()

      base_globs = BaseGlobs.from_sources_field(sources, self.address.spec_path)
      path_globs = base_globs.to_path_globs(self.address.spec_path, conjunction_globs.conjunction)
      sources_field = SourcesField(
        self.address,
        'sources',
        base_globs.filespecs,
        base_globs,
        path_globs,
        self.validate_sources,
      )
      return sources_field,

  @classproperty
  def default_sources_globs(cls):
    return None

  @classproperty
  def default_sources_exclude_globs(cls):
    return None

  def validate_sources(self, sources):
    """" Validate that the sources argument is allowed.

    Examples may be to check that the number of sources is correct, that file extensions are as
    expected, etc.

    TODO: Replace this with some kind of field subclassing, as per
    https://github.com/pantsbuild/pants/issues/4535

    :param sources EagerFilesetWithSpec resolved sources.
    """


@union
class HydrateableField:
  """A marker for Target(Adaptor) fields for which the engine might perform extra construction."""


@dataclass(frozen=True)
class SourcesField:
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
  :param validate_fn: A function which takes an EagerFilesetWithSpec and throws if it's not
    acceptable. This API will almost certainly change in the near future.
  """
  address: Address
  arg: str
  filespecs: wrapped_globs.Filespec
  base_globs: "BaseGlobs"
  path_globs: PathGlobs
  validate_fn: Callable

  def __hash__(self):
    return hash((self.address, self.arg))

  def __repr__(self):
    return '{}(address={}, input_globs={}, arg={}, filespecs={!r})'.format(
      type(self).__name__, self.address, self.base_globs, self.arg, self.filespecs)


class JvmBinaryAdaptor(TargetAdaptor):
  def validate_sources(self, sources):
    if len(sources.files) > 1:
      raise Target.IllegalArgument(self.address.spec,
                'jvm_binary must have exactly 0 or 1 sources (typically used to specify the class '
                'containing the main method). '
                'Other sources should instead be placed in a java_library, which '
                'should be referenced in the jvm_binary\'s dependencies.'
              )


class PageAdaptor(TargetAdaptor):
  def validate_sources(self, sources):
    if len(sources.files) != 1:
      raise Target.IllegalArgument(
        self.address.spec,
        'page targets must have exactly 1 source, but found {} ({})'.format(
          len(sources.files),
          ', '.join(sources.files),
        )
      )


@dataclass(frozen=True)
class BundlesField:
  """Represents the `bundles` argument, each of which has a PathGlobs to represent its `fileset`."""
  address: Address
  bundles: Any
  filespecs_list: List[wrapped_globs.Filespec]
  path_globs_list: List[PathGlobs]

  def __hash__(self):
    return hash(self.address)


class BundleAdaptor(Struct):
  """A Struct to capture the args for the `bundle` object.

  Bundles have filesets which we need to capture in order to execute them in the engine.

  TODO: Bundles should arguably be Targets, but that distinction blurs in the `exp` examples
  package, where a Target is just a collection of configuration.
  """


class AppAdaptor(TargetAdaptor):
  def __init__(self, bundles=None, **kwargs):
    """
    :param list bundles: A list of `BundleAdaptor` objects
    """
    super().__init__(**kwargs)
    self.bundles = bundles

  @addressable_list(Exactly(BundleAdaptor))
  def bundles(self):
    """The BundleAdaptors for this JvmApp."""
    return self.bundles

  @property
  def field_adaptors(self) -> Tuple:
    with exception_logging(logger, 'Exception in `field_adaptors` property'):
      field_adaptors = super().field_adaptors
      if getattr(self, 'bundles', None) is None:
        return field_adaptors

      bundles_field = self._construct_bundles_field()
      return (*field_adaptors, bundles_field)

  def _construct_bundles_field(self) -> BundlesField:
    filespecs_list: List[wrapped_globs.Filespec] = []
    path_globs_list: List[PathGlobs] = []
    for bundle in self.bundles:
      # NB: if a bundle has a rel_path, then the rel_root of the resulting file globs must be
      # set to that rel_path.
      rel_root = getattr(bundle, 'rel_path', self.address.spec_path)

      base_globs = BaseGlobs.from_sources_field(bundle.fileset, rel_root)
      path_globs = base_globs.to_path_globs(rel_root, GlobExpansionConjunction.all_match)

      filespecs_list.append(base_globs.filespecs)
      path_globs_list.append(path_globs)

    return BundlesField(
      self.address, self.bundles, filespecs_list, path_globs_list,
    )


class JvmAppAdaptor(AppAdaptor): pass


class PythonAppAdaptor(AppAdaptor): pass


class ResourcesAdaptor(TargetAdaptor): pass


class RemoteSourcesAdaptor(TargetAdaptor):
  def __init__(self, dest=None, **kwargs):
    """
    :param dest: A target constructor.
    """
    if not isinstance(dest, str):
      dest = dest._type_alias
    super().__init__(dest=dest, **kwargs)


class PythonTargetAdaptor(TargetAdaptor):
  @property
  def field_adaptors(self) -> Tuple:
    with exception_logging(logger, 'Exception in `field_adaptors` property'):
      field_adaptors = super().field_adaptors
      if getattr(self, 'resources', None) is None:
        return field_adaptors
      base_globs = BaseGlobs.from_sources_field(self.resources, self.address.spec_path)
      path_globs = base_globs.to_path_globs(self.address.spec_path, GlobExpansionConjunction.all_match)
      sources_field = SourcesField(self.address,
                                   'resources',
                                   base_globs.filespecs,
                                   base_globs,
                                   path_globs,
                                   lambda _: None)
      return (*field_adaptors, sources_field)


class PythonBinaryAdaptor(PythonTargetAdaptor):
  def validate_sources(self, sources):
    if len(sources.files) > 1:
      raise Target.IllegalArgument(self.address.spec,
        'python_binary must have exactly 0 or 1 sources (typically used to specify the file '
        'containing the entry point). '
        'Other sources should instead be placed in a python_library, which '
        'should be referenced in the python_binary\'s dependencies.'
      )


class PythonTestsAdaptor(PythonTargetAdaptor): pass


class PythonAWSLambdaAdaptor(TargetAdaptor): pass


class PythonRequirementLibraryAdaptor(TargetAdaptor): pass


class PantsPluginAdaptor(PythonTargetAdaptor):
  def get_sources(self) -> "GlobsWithConjunction":
    return GlobsWithConjunction.for_literal_files(['register.py'], self.address.spec_path)


# TODO(#7490): Remove this once we have multiple params support so that rules can do something
# like `await Get[TestResult](Params(Address(..), Origin(..)))`.
@dataclass(frozen=True)
class TargetAdaptorWithOrigin:
  adaptor: TargetAdaptor
  origin: OriginSpec

  @staticmethod
  def create(adaptor: TargetAdaptor, origin: OriginSpec) -> "TargetAdaptorWithOrigin":
    adaptor_with_origin_cls: Type["TargetAdaptorWithOrigin"] = {
      TargetAdaptor: TargetAdaptorWithOrigin,
      AppAdaptor: AppAdaptorWithOrigin,
      JvmAppAdaptor: JvmAppAdaptorWithOrigin,
      PythonAppAdaptor: PythonAppAdaptorWithOrigin,
      ResourcesAdaptor: ResourcesAdaptorWithOrigin,
      RemoteSourcesAdaptor: RemoteSourcesAdaptorWithOrigin,
      PythonTargetAdaptor: PythonTargetAdaptorWithOrigin,
      PythonBinaryAdaptor: PythonBinaryAdaptorWithOrigin,
      PythonTestsAdaptor: PythonTestsAdaptorWithOrigin,
      PythonAWSLambdaAdaptor: PythonAWSLambdaAdaptorWithOrigin,
      PythonRequirementLibraryAdaptor: PythonRequirementLibraryAdaptorWithOrigin,
      PantsPluginAdaptor: PantsPluginAdaptorWithOrigin,
    }[type(adaptor)]
    return adaptor_with_origin_cls(adaptor, origin)


@dataclass(frozen=True)
class AppAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: AppAdaptor


@dataclass(frozen=True)
class JvmAppAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: JvmAppAdaptor


@dataclass(frozen=True)
class PythonAppAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PythonAppAdaptor


@dataclass(frozen=True)
class ResourcesAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: ResourcesAdaptor


@dataclass(frozen=True)
class RemoteSourcesAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: RemoteSourcesAdaptor


@dataclass(frozen=True)
class PythonTargetAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PythonTargetAdaptor


@dataclass(frozen=True)
class PythonBinaryAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PythonBinaryAdaptor


@dataclass(frozen=True)
class PythonTestsAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PythonTestsAdaptor


@dataclass(frozen=True)
class PythonAWSLambdaAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PythonAWSLambdaAdaptor


@dataclass(frozen=True)
class PythonRequirementLibraryAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PythonRequirementLibraryAdaptor


@dataclass(frozen=True)
class PantsPluginAdaptorWithOrigin(TargetAdaptorWithOrigin):
  adaptor: PantsPluginAdaptor


# TODO: Remove all the subclasses once we remove globs et al. The only remaining subclass would be
# Files, which should simply be unified into BaseGlobs.
class BaseGlobs(Locatable, metaclass=ABCMeta):
  """An adaptor class to allow BUILD file parsing from ContextAwareObjectFactories."""

  @staticmethod
  def from_sources_field(
    sources: Union[None, str, Iterable[str], "BaseGlobs"], spec_path: str,
  ) -> "BaseGlobs":
    """Return a BaseGlobs for the given sources field."""
    if sources is None:
      return Files(spec_path=spec_path)
    if isinstance(sources, BaseGlobs):
      return sources
    if isinstance(sources, str):
      return Files(sources, spec_path=spec_path)
    if (
      isinstance(sources, (MutableSet, MutableSequence, tuple))
      and all(isinstance(s, str) for s in sources)
    ):
      return Files(*sources, spec_path=spec_path)
    raise ValueError(f'Expected either a glob or list of literal sources. Got: {sources}')

  @property
  @abstractmethod
  def path_globs_kwarg(self) -> str:
    """The name of the `PathGlobs` parameter corresponding to this BaseGlobs instance."""

  @property
  @abstractmethod
  def legacy_globs_class(self) -> Type[wrapped_globs.FilesetRelPathWrapper]:
    """The corresponding `wrapped_globs` class for this BaseGlobs."""

  # TODO: stop accepting an `exclude` argument once we remove `globs` et al.
  def __init__(
    self, *patterns: str, spec_path: str, exclude: Optional[List[str]] = None, **kwargs,
  ) -> None:
    self._patterns = patterns
    self._spec_path = spec_path
    self._raw_exclude = exclude

    if isinstance(exclude, str):
      raise ValueError(f'Excludes should be a list of strings. Got: {exclude!r}')
    if kwargs:
      raise ValueError(f'kwargs not supported. Got: {kwargs}')

    # TODO: once we remove `globs`, `rglobs`, and `zglobs`, we should change as follows:
    #  * Stop setting `self._parsed_include` and `self._parsed_exclude`. Only save `self._patterns`.
    #    All the below code should be deleted. For now, we must have these values to ensure that we
    #    properly parse the `globs()` function.
    #  * `to_path_globs()` will still need to strip the leading `!` from the exclude pattern, call
    #    `os.path.join`, and then prepend it back with `!`. But, it will do that when traversing
    #     over `self._patterns`, rather than `self._parsed_exclude`. We have a new unit test to
    #     ensure that we don't break this.
    #  * `filespecs()` must still need to split out the includes from excludes to maintain backwards
    #     compatibility. The below for loop splitting out the `self._patterns` should be moved
    #     into `filespecs()`. We have a new unit test to ensure that we don't break this.
    self._parsed_include: List[str] = []
    self._parsed_exclude: List[str] = []
    if isinstance(self, Files):
      for glob in self._patterns:
        if glob.startswith("!"):
          self._parsed_exclude.append(glob[1:])
        else:
          self._parsed_include.append(glob)
    else:
      self._parsed_include = self.legacy_globs_class.to_filespec(patterns)['globs']
      self._parsed_exclude = self._parse_exclude(exclude or [])

  @property
  def filespecs(self) -> wrapped_globs.Filespec:
    """Return a filespecs dict representing both globs and excludes."""
    filespecs: wrapped_globs.Filespec = {'globs': self._parsed_include}
    if self._parsed_exclude:
      filespecs['exclude'] = [{'globs': self._parsed_exclude}]
    return filespecs

  def to_path_globs(self, relpath: str, conjunction: GlobExpansionConjunction) -> PathGlobs:
    """Return a PathGlobs representing the included and excluded Files for these patterns."""
    return PathGlobs(
      globs=(
        *(os.path.join(relpath, glob) for glob in self._parsed_include),
        *(f"!{os.path.join(relpath, glob)}" for glob in self._parsed_exclude)
      ),
      conjunction=conjunction,
    )

  def _parse_exclude(self, raw_exclude: List[str]) -> List[str]:
    excluded_patterns: List[str] = []
    for raw_element in raw_exclude:
      exclude_filespecs = BaseGlobs.from_sources_field(raw_element, self._spec_path).filespecs
      if exclude_filespecs.get('exclude'):
        raise ValueError('Nested excludes are not supported: got {}'.format(raw_element))
      excluded_patterns.extend(exclude_filespecs['globs'])
    return excluded_patterns

  def _gen_init_args_str(self) -> str:
    all_arg_strs = []
    positional_args = ', '.join(repr(p) for p in self._patterns)
    if positional_args:
      all_arg_strs.append(positional_args)
    all_arg_strs.append(f"spec_path={self._spec_path}")
    if self._raw_exclude:
      all_arg_strs.append(f"exclude={self._raw_exclude}")
    return ', '.join(all_arg_strs)

  def __repr__(self) -> str:
    # TODO: remove this once we finish deprecating `globs` et al. Use the __str__ implementation.
    return f'{type(self).__name__}({self._gen_init_args_str()})'

  def __str__(self) -> str:
    return f'{self.path_globs_kwarg}({self._gen_init_args_str()})'


class Files(BaseGlobs):
  path_globs_kwarg = 'files'
  legacy_globs_class = wrapped_globs.Globs

  def __str__(self) -> str:
    return f"[{', '.join(repr(p) for p in self._patterns)}]"


class Globs(BaseGlobs):
  path_globs_kwarg = 'globs'
  legacy_globs_class = wrapped_globs.Globs


class RGlobs(BaseGlobs):
  path_globs_kwarg = 'rglobs'
  legacy_globs_class = wrapped_globs.RGlobs


class ZGlobs(BaseGlobs):
  path_globs_kwarg = 'zglobs'
  legacy_globs_class = wrapped_globs.ZGlobs


@dataclass(frozen=True)
class GlobsWithConjunction:
  non_path_globs: BaseGlobs
  conjunction: GlobExpansionConjunction

  @classmethod
  def for_literal_files(cls, file_paths: Sequence[str], spec_path: str) -> "GlobsWithConjunction":
    return cls(Files(*file_paths, spec_path=spec_path), GlobExpansionConjunction.all_match)


def rules():
  return [
    UnionRule(HydrateableField, SourcesField),
    UnionRule(HydrateableField, BundlesField),
  ]
