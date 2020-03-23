# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from abc import ABCMeta, abstractmethod

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.option.custom_types import dir_option
from pants.process.xargs import Xargs
from pants.util.dirutil import fast_relpath, safe_mkdir_for_all
from pants.util.memo import memoized_property


class RewriteBase(NailgunTask, metaclass=ABCMeta):
    """Abstract base class for JVM-based tools that check/rewrite sources."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--target-types",
            default=cls.target_types(),
            advanced=True,
            type=list,
            help="The target types to apply formatting to.",
        )
        if cls.sideeffecting:
            register(
                "--output-dir",
                advanced=True,
                type=dir_option,
                fingerprint=True,
                help="Path to output directory. Any updated files will be written here. "
                "If not specified, files will be modified in-place.",
            )

    @classmethod
    def target_types(cls):
        """Returns a list of target type names (e.g.: `scala_library`) this rewriter operates on."""
        raise NotImplementedError()

    @classmethod
    def source_extension(cls):
        """Returns the source extension this rewriter operates on (e.g.: `.scala`)"""
        raise NotImplementedError()

    @memoized_property
    def _formatted_target_types(self):
        aliases = set(self.get_options().target_types)
        registered_aliases = self.context.build_configuration.registered_aliases()
        return tuple(
            {
                target_type
                for alias in aliases
                for target_type in registered_aliases.target_types_by_alias[alias]
            }
        )

    @property
    def cache_target_dirs(self):
        return not self.sideeffecting

    def execute(self):
        """Runs the tool on all source files that are located."""
        relevant_targets = self._get_non_synthetic_targets(self.get_targets())

        if self.sideeffecting:
            # Always execute sideeffecting tasks without invalidation.
            self._execute_for(relevant_targets)
        else:
            # If the task is not sideeffecting we can use invalidation.
            with self.invalidated(relevant_targets) as invalidation_check:
                self._execute_for([vt.target for vt in invalidation_check.invalid_vts])

    def _execute_for(self, targets):
        target_sources = self._calculate_sources(targets)
        if not target_sources:
            return

        result = Xargs(self._invoke_tool).execute(target_sources)
        if result != 0:
            raise TaskError(
                "{} is improperly implemented: a failed process "
                "should raise an exception earlier.".format(type(self).__name__)
            )

    def _invoke_tool(self, target_sources):
        buildroot = get_buildroot()
        toolroot = buildroot
        if self.sideeffecting and self.get_options().output_dir:
            toolroot = self.get_options().output_dir
            new_sources = [
                (target, os.path.join(toolroot, fast_relpath(source, buildroot)))
                for target, source in target_sources
            ]
            old_file_paths = [source for _, source in target_sources]
            new_file_paths = [source for _, source in new_sources]
            safe_mkdir_for_all(new_file_paths)
            for old, new in zip(old_file_paths, new_file_paths):
                shutil.copyfile(old, new)
            target_sources = new_sources
        result = self.invoke_tool(toolroot, target_sources)
        self.process_result(result)
        return result

    @abstractmethod
    def invoke_tool(self, absolute_root, target_sources):
        """Invoke the tool on the given (target, absolute source) tuples.

        Sources are guaranteed to be located below the given root.

        Returns the UNIX return code of the tool.
        """

    @property
    @abstractmethod
    def sideeffecting(self):
        """True if this command has sideeffects: ie, mutates the working copy."""

    @abstractmethod
    def process_result(self, return_code):
        """Given a return code, process the result of the tool.

        No return value is expected. If an error occurred while running the tool, raising a
        TaskError with a useful error message is required.
        """

    def _get_non_synthetic_targets(self, targets):
        return [
            target
            for target in targets
            if isinstance(target, self._formatted_target_types)
            and target.has_sources(self.source_extension())
            and not target.is_synthetic
        ]

    def _calculate_sources(self, targets):
        return [
            (target, os.path.join(get_buildroot(), source))
            for target in targets
            for source in target.sources_relative_to_buildroot()
            if source.endswith(self.source_extension())
        ]
