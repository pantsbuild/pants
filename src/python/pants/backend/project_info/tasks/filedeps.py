# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated_conditional
from pants.task.console_task import ConsoleTask


class FileDeps(ConsoleTask):
    """List all source and BUILD files a target transitively depends on.

    Files may be listed with absolute or relative paths and any BUILD files implied in the
    transitive closure of targets are also included.
    """

    # TODO: In 1.28.0.dev0, once we default to `--no-transitive`, remove this and go back to using
    # ConsoleTask's implementation of `--transitive`.
    _register_console_transitivity_option = False

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--globs",
            type=bool,
            help="Instead of outputting filenames, output globs (ignoring excludes)",
        )
        register(
            "--absolute",
            type=bool,
            default=True,
            help="If True output with absolute path, else output with path relative to the build root",
        )
        register(
            "--transitive",
            type=bool,
            default=True,
            fingerprint=True,
            help="If True, use all targets in the build graph, else use only target roots.",
        )

    @property
    def act_transitively(self):
        # NB: Stop overriding this property once the deprecation is complete.
        deprecated_conditional(
            lambda: self.get_options().is_default("transitive"),
            entity_description=f"Pants defaulting to `--filedeps-transitive`",
            removal_version="1.28.0.dev0",
            hint_message="Currently, Pants defaults to `--filedeps-transitive`, which means that it "
            "will find all transitive files used by the target, rather than only direct "
            "file dependencies. This is a useful feature, but surprising to be the default."
            "\n\nTo prepare for this change to the default value, set in `pants.toml` under "
            "the section `filedeps` the value `transitive = false`. In Pants 1.28.0, "
            "you can safely remove the setting.",
        )
        return self.get_options().transitive

    def _file_path(self, path):
        return os.path.join(get_buildroot(), path) if self.get_options().absolute else path

    def console_output(self, targets):
        concrete_targets = set()
        for target in targets:
            concrete_target = target.concrete_derived_from
            concrete_targets.add(concrete_target)
            # TODO(John Sirois): This hacks around ScalaLibraries' pseudo-deps on JavaLibraries.  We've
            # already tried to tuck away this hack by subclassing closure() in ScalaLibrary - but in this
            # case that's not enough when a ScalaLibrary with java_sources is an interior node of the
            # active context graph.  This awkwardness should be eliminated when ScalaLibrary can point
            # to a java source set as part of its 1st class sources.
            if isinstance(concrete_target, ScalaLibrary):
                concrete_targets.update(concrete_target.java_sources)

        files = set()
        output_globs = self.get_options().globs

        # Filter out any synthetic targets, which will not have a build_file attr.
        concrete_targets = {target for target in concrete_targets if not target.is_synthetic}
        for target in concrete_targets:
            files.add(self._file_path(target.address.rel_path))
            if output_globs or target.has_sources():
                if output_globs:
                    globs_obj = target.globs_relative_to_buildroot()
                    if globs_obj:
                        files.update(self._file_path(src) for src in globs_obj["globs"])
                else:
                    files.update(
                        self._file_path(src) for src in target.sources_relative_to_buildroot()
                    )
            # TODO(John Sirois): BundlePayload should expose its sources in a way uniform to
            # SourcesPayload to allow this special-casing to go away.
            if isinstance(target, JvmApp) and not output_globs:
                for bundle in target.bundles:
                    files.update(
                        bundle.filemap.keys()
                        if self.get_options().absolute
                        else bundle.relative_filemap.keys()
                    )
        return files
