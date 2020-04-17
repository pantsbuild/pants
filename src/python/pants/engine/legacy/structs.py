# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os.path
from collections.abc import MutableSequence, MutableSet
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple, Union, cast

from pants.base.deprecated import warn_or_error
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.engine.addressable import addressable_sequence
from pants.engine.fs import GlobExpansionConjunction, PathGlobs
from pants.engine.objects import Locatable, union
from pants.engine.rules import UnionRule
from pants.engine.struct import Struct, StructWithDeps
from pants.source import wrapped_globs
from pants.util.collections import ensure_str_list
from pants.util.contextutil import exception_logging
from pants.util.meta import classproperty
from pants.util.objects import Exactly

logger = logging.getLogger(__name__)


class TargetAdaptor(StructWithDeps):
    """A Struct to imitate the existing Target.

    Extends StructWithDeps to add a `dependencies` field marked Addressable.
    """

    # NB: This overridden `__init__()` is weird. We solely have it so that MyPy can infer
    # `TargetAdaptor.dependencies` as `Tuple[Address, ...]`.
    def __init__(self, dependencies=None, **kwargs) -> None:
        super().__init__(dependencies, **kwargs)
        self.dependencies: Tuple[Address, ...]

    @property
    def address(self) -> Address:
        return cast(Address, super().address)

    def get_sources(self) -> Optional["GlobsWithConjunction"]:
        """Returns target's non-deferred sources if exists or the default sources if defined.

        NB: once ivy is implemented in the engine, we can fetch sources natively here, and/or
        refactor how deferred sources are implemented.
          see: https://github.com/pantsbuild/pants/issues/2997
        """
        source = getattr(self, "source", None)
        sources = getattr(self, "sources", None)

        if source is not None and sources is not None:
            raise Target.IllegalArgument(
                self.address.spec, "Cannot specify both source and sources attribute."
            )

        if source is not None:
            if not isinstance(source, str):
                raise Target.IllegalArgument(
                    self.address.spec,
                    f"source must be a str containing a path relative to the target, but got {source} of "
                    f"type {type(source)}",
                )
            script_instructions = (
                "curl -L -o convert_source_to_sources.py 'https://git.io/JvbN3' && chmod +x "
                "convert_source_to_sources.py && ./convert_source_to_sources.py "
                f"root_folder1/ root_folder2/"
            )
            warn_or_error(
                deprecated_entity_description="using `source` instead of `sources` in a BUILD file",
                removal_version="1.29.0.dev0",
                hint=(
                    f"Instead of `source={repr(source)}`, use `sources=[{repr(source)}]`. We "
                    "recommend using our migration script to automate fixing your entire "
                    f"repository by running `{script_instructions}`."
                ),
            )
            sources = [source]

        # N.B. Here we check specifically for `sources is None`, as it's possible for sources
        # to be e.g. an explicit empty list (sources=[]).
        if sources is None:
            if self.default_sources_globs is None:
                return None
            default_sources = SourceGlobs(
                *(
                    *self.default_sources_globs,
                    *(f"!{glob}" for glob in self.default_sources_exclude_globs or []),
                ),
            )
            return GlobsWithConjunction(default_sources, GlobExpansionConjunction.any_match)

        source_globs = SourceGlobs.from_sources_field(sources)
        return GlobsWithConjunction(source_globs, GlobExpansionConjunction.all_match)

    @property
    def field_adaptors(self) -> Tuple:
        """Returns a tuple of Fields for captured fields which need additional treatment."""
        with exception_logging(logger, "Exception in `field_adaptors` property"):
            conjunction_globs = self.get_sources()
            if conjunction_globs is None:
                return tuple()

            sources = conjunction_globs.globs
            if not sources:
                return tuple()

            sources_field = SourcesField(
                address=self.address,
                arg="sources",
                source_globs=sources,
                conjunction=conjunction_globs.conjunction,
                validate_fn=self.validate_sources,
            )
            return (sources_field,)

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

    # TODO: do we want to support the `extension` parameter from Target.has_sources()? In V1,
    # it's used to distinguish between Java vs. Scala files. For now, we should leave it off to
    # keep things as simple as possible, but we may want to add it in the future.
    def has_sources(self) -> bool:
        """Return True if the target has `sources` defined with resolved entries.

        This checks after the sources have been resolved, e.g. after any globs have been expanded
        and any ignores have been applied.
        """
        return hasattr(self, "sources") and bool(self.sources.snapshot.files)


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
    source_globs: "SourceGlobs"
    conjunction: GlobExpansionConjunction = GlobExpansionConjunction.any_match
    validate_fn: Callable = lambda _: None

    @property
    def path_globs(self) -> PathGlobs:
        return self.source_globs.to_path_globs(
            relpath=self.address.spec_path, conjunction=self.conjunction
        )

    def __hash__(self):
        return hash((self.address, self.arg))

    def __str__(self):
        return f"{self.address}({self.arg}={self.source_globs})"


class JvmBinaryAdaptor(TargetAdaptor):
    def validate_sources(self, sources):
        if len(sources.files) > 1:
            raise Target.IllegalArgument(
                self.address.spec,
                "jvm_binary must have exactly 0 or 1 sources (typically used to specify the class "
                "containing the main method). "
                "Other sources should instead be placed in a java_library, which "
                "should be referenced in the jvm_binary's dependencies.",
            )


class PageAdaptor(TargetAdaptor):
    def validate_sources(self, sources):
        if len(sources.files) != 1:
            raise Target.IllegalArgument(
                self.address.spec,
                "page targets must have exactly 1 source, but found {} ({})".format(
                    len(sources.files), ", ".join(sources.files),
                ),
            )


@dataclass(frozen=True)
class BundlesField:
    """Represents the `bundles` argument, each of which has a PathGlobs to represent its
    `fileset`."""

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

    @addressable_sequence(Exactly(BundleAdaptor))
    def bundles(self):
        """The BundleAdaptors for this JvmApp."""
        return self.bundles

    @property
    def field_adaptors(self) -> Tuple:
        with exception_logging(logger, "Exception in `field_adaptors` property"):
            field_adaptors = super().field_adaptors
            if getattr(self, "bundles", None) is None:
                return field_adaptors

            bundles_field = self._construct_bundles_field()
            return (*field_adaptors, bundles_field)

    def _construct_bundles_field(self) -> BundlesField:
        filespecs_list: List[wrapped_globs.Filespec] = []
        path_globs_list: List[PathGlobs] = []
        for bundle in self.bundles:
            # NB: if a bundle has a rel_path, then the rel_root of the resulting file globs must be
            # set to that rel_path.
            rel_root = getattr(bundle, "rel_path", self.address.spec_path)

            source_globs = SourceGlobs.from_sources_field(bundle.fileset)
            path_globs = source_globs.to_path_globs(rel_root, GlobExpansionConjunction.all_match)

            filespecs_list.append(source_globs.filespecs)
            path_globs_list.append(path_globs)

        return BundlesField(self.address, self.bundles, filespecs_list, path_globs_list)


class JvmAppAdaptor(AppAdaptor):
    pass


class PythonAppAdaptor(AppAdaptor):
    pass


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
        with exception_logging(logger, "Exception in `field_adaptors` property"):
            field_adaptors = super().field_adaptors
            if getattr(self, "resources", None) is None:
                return field_adaptors
            source_globs = SourceGlobs.from_sources_field(self.resources)
            sources_field = SourcesField(
                address=self.address,
                arg="resources",
                source_globs=source_globs,
                conjunction=GlobExpansionConjunction.all_match,
            )
            return (*field_adaptors, sources_field)

    # TODO(#4535): remove this once its superseded by the target API.
    @property
    def compatibility(self) -> Optional[List[str]]:
        if "compatibility" not in self._kwargs:
            return None
        return ensure_str_list(self._kwargs["compatibility"], allow_single_str=True)


class PythonBinaryAdaptor(PythonTargetAdaptor):
    def validate_sources(self, sources):
        if len(sources.files) > 1:
            raise Target.IllegalArgument(
                self.address.spec,
                "python_binary must have exactly 0 or 1 sources (typically used to specify the file "
                "containing the entry point). "
                "Other sources should instead be placed in a python_library, which "
                "should be referenced in the python_binary's dependencies.",
            )


class PythonTestsAdaptor(PythonTargetAdaptor):
    pass


class PantsPluginAdaptor(PythonTargetAdaptor):
    def get_sources(self) -> "GlobsWithConjunction":
        return GlobsWithConjunction.for_literal_files(["register.py"])


class SourceGlobs(Locatable):
    """A light wrapper around a target's `sources`.

    This allows BUILD file parsing from ContextAwareObjectFactories.
    """

    @staticmethod
    def from_sources_field(sources: Union[None, str, Iterable[str]]) -> "SourceGlobs":
        """Return a BaseGlobs for the given sources field."""
        if sources is None:
            return SourceGlobs()
        if isinstance(sources, str):
            return SourceGlobs(sources)
        if isinstance(sources, (MutableSet, MutableSequence, tuple)) and all(
            isinstance(s, str) for s in sources
        ):
            return SourceGlobs(*sources)
        raise ValueError(f"Expected a list of literal source files and globs. Got: {sources}.")

    def __init__(self, *patterns: str) -> None:
        self._patterns = patterns

    @property
    def filespecs(self) -> wrapped_globs.Filespec:
        """Return a filespecs dict representing both globs and excludes."""
        includes = []
        excludes = []
        for glob in self._patterns:
            if glob.startswith("!"):
                excludes.append(glob[1:])
            else:
                includes.append(glob)
        filespecs: wrapped_globs.Filespec = {"globs": includes}
        if excludes:
            filespecs["exclude"] = [{"globs": excludes}]
        return filespecs

    def to_path_globs(self, relpath: str, conjunction: GlobExpansionConjunction) -> PathGlobs:
        """Return a PathGlobs representing the included and excluded Files for these patterns."""

        def join_with_relpath(glob: str) -> str:
            if glob.startswith("!"):
                return f"!{os.path.join(relpath, glob[1:])}"
            return os.path.join(relpath, glob)

        return PathGlobs(
            globs=(join_with_relpath(glob) for glob in self._patterns), conjunction=conjunction,
        )

    def __repr__(self) -> str:
        return f"[{', '.join(repr(p) for p in self._patterns)}]"


@dataclass(frozen=True)
class GlobsWithConjunction:
    globs: SourceGlobs
    conjunction: GlobExpansionConjunction

    @classmethod
    def for_literal_files(cls, file_paths: Sequence[str]) -> "GlobsWithConjunction":
        return cls(SourceGlobs(*file_paths), GlobExpansionConjunction.all_match)


def rules():
    return [
        UnionRule(HydrateableField, SourcesField),
        UnionRule(HydrateableField, BundlesField),
    ]
