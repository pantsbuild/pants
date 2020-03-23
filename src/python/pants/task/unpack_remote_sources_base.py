# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import re
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Tuple

from twitter.common.dirutil.fileset import fnmatch_translate_extended

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.task.task import Task
from pants.util.meta import classproperty

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnpackedArchives:
    found_files: Tuple
    rel_unpack_dir: str


class UnpackRemoteSourcesBase(Task, metaclass=ABCMeta):
    @property
    def cache_target_dirs(cls):
        return True

    @classmethod
    def product_types(cls):
        return [UnpackedArchives]

    @classproperty
    @abstractmethod
    def source_target_constraint(cls):
        """Return a type constraint which is evaluated to determine "source" targets for this task.

        :return: :class:`pants.util.objects.TypeConstraint`
        """

    @abstractmethod
    def unpack_target(self, unpackable_target, unpack_dir):
        """Unpack the remote resources indicated by `unpackable_target` into `unpack_dir`."""

    @property
    def _unpacked_sources_product(self):
        return self.context.products.get_data(UnpackedArchives, lambda: {})

    @classmethod
    def _file_filter(cls, filename, include_patterns, exclude_patterns):
        """:returns: `True` if the file should be allowed through the filter."""
        logger.debug("filename: {}".format(filename))
        for exclude_pattern in exclude_patterns:
            if exclude_pattern.match(filename):
                return False
        if include_patterns:
            found = False
            for include_pattern in include_patterns:
                if include_pattern.match(filename):
                    found = True
                    break
            if not found:
                return False
        return True

    class InvalidPatternError(Exception):
        """Raised if a pattern can't be compiled for including or excluding args."""

    @classmethod
    def compile_patterns(cls, patterns, field_name="Unknown", spec="Unknown"):
        logger.debug(f"patterns before removing trailing stars: {patterns}")
        # NB: `fnmatch_translate_extended()` will convert a '*' at the end into '([^/]+)' for some
        # reason -- it should be '('[^/]*)'. This should be fixed upstream in general, but in the case
        # where the star is at the end we can use this heuristic for now.
        patterns.extend(
            re.sub(r"\*$", "", p) for p in patterns if isinstance(p, str) and re.match(r".*\*$", p)
        )
        logger.debug(
            f"patterns with any trailing stars have a version with a star removed: {patterns}"
        )
        compiled_patterns = []
        for p in patterns:
            try:
                compiled_patterns.append(re.compile(fnmatch_translate_extended(p)))
            except (TypeError, re.error) as e:
                raise cls.InvalidPatternError(
                    'In {spec}, "{field_value}" in {field_name} can\'t be compiled: {msg}'.format(
                        field_name=field_name, field_value=p, spec=spec, msg=e
                    )
                )
        return compiled_patterns

    @classmethod
    def _calculate_unpack_filter(cls, includes=None, excludes=None, spec=None):
        """Take regex patterns and return a filter function.

        :param list includes: List of include patterns to pass to _file_filter.
        :param list excludes: List of exclude patterns to pass to _file_filter.
        """
        include_patterns = cls.compile_patterns(
            includes or [], field_name="include_patterns", spec=spec
        )
        logger.debug("include_patterns: {}".format(list(p.pattern for p in include_patterns)))
        exclude_patterns = cls.compile_patterns(
            excludes or [], field_name="exclude_patterns", spec=spec
        )
        logger.debug("exclude_patterns: {}".format(list(p.pattern for p in exclude_patterns)))
        return lambda f: cls._file_filter(f, include_patterns, exclude_patterns)

    @classmethod
    def get_unpack_filter(cls, unpackable_target):
        """Calculate a filter function from the include/exclude patterns of a Target.

        :param ImportRemoteSourcesMixin unpackable_target: A target with include_patterns and
                                                           exclude_patterns attributes.
        """
        # TODO: we may be able to make use of glob matching in the engine to avoid doing this filtering.
        return cls._calculate_unpack_filter(
            includes=unpackable_target.payload.include_patterns,
            excludes=unpackable_target.payload.exclude_patterns,
            spec=unpackable_target.address.spec,
        )

    class DuplicateUnpackedSourcesError(TaskError):
        pass

    def _traverse_unpacked_dir(self, unpack_dir):
        found_files = []
        for root, dirs, files in os.walk(unpack_dir):
            for f in files:
                relpath = os.path.relpath(os.path.join(root, f), unpack_dir)
                found_files.append(relpath)
        rel_unpack_dir = os.path.relpath(unpack_dir, get_buildroot())
        return found_files, rel_unpack_dir

    def _add_unpacked_sources_for_target(self, target, unpack_dir):
        maybe_existing_sources = self._unpacked_sources_product.get(target, None)
        if maybe_existing_sources:
            raise self.DuplicateUnpackedSourcesError(
                "Target {} must not have any unpacked sources already registered!\n"
                "The existing value was: {}\n"
                "The second unpacked directory registered was: {}".format(
                    target, maybe_existing_sources, unpack_dir
                )
            )

        found_files, rel_unpack_dir = self._traverse_unpacked_dir(unpack_dir)
        self.context.log.debug(
            "target: {}, rel_unpack_dir: {}, found_files: {}".format(
                target, rel_unpack_dir, found_files
            )
        )
        self._unpacked_sources_product[target] = UnpackedArchives(
            tuple(found_files), rel_unpack_dir
        )

    class MissingUnpackedDirsError(Exception):
        """Raised if a directory that is expected to be unpacked doesn't exist."""

    def execute(self):
        with self.invalidated(
            self.get_targets(self.source_target_constraint.satisfied_by),
            fingerprint_strategy=self.get_fingerprint_strategy(),
            invalidate_dependents=True,
        ) as invalidation_check:
            for vt in invalidation_check.invalid_vts:
                self.unpack_target(vt.target, vt.results_dir)

            for vt in invalidation_check.all_vts:
                self._add_unpacked_sources_for_target(vt.target, vt.results_dir)
