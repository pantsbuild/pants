# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from abc import abstractmethod
from collections import OrderedDict
from typing import Optional, Tuple, Type

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.target import Target
from pants.engine.fs import Digest, PathGlobs, PathGlobsAndRoot
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper
from pants.task.task import Task
from pants.util.dirutil import fast_relpath, safe_delete
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class SimpleCodegenTask(Task):
    """A base-class for code generation for a single target language.

    :API: public
    """

    # Subclasses may override to provide the type of gen targets the target acts on.
    # E.g., JavaThriftLibrary. If not provided, the subclass must implement is_gentarget.
    gentarget_type: Optional[Type[Target]] = None

    # Subclasses may override to provide a list of glob patterns matching the generated sources,
    # relative to the target's workdir.
    # These must be a tuple of strings, e.g. ('**/*.java',).
    sources_globs: Optional[Tuple[str, ...]] = None

    # Tuple of glob patterns to exclude from the above matches.
    sources_exclude_globs = ()

    def __init__(self, context, workdir):
        """Add pass-thru Task Constructor for public API visibility.

        :API: public
        """
        super().__init__(context, workdir)

    @classmethod
    def product_types(cls):
        # NB(gmalmquist): This is a hack copied from the old CodeGen base class to get the round manager
        # to properly run codegen before resolve and compile. It would be more correct to just have each
        # individual codegen class declare what languages it generates, but would cause problems with
        # scala. See https://rbcommons.com/s/twitter/r/2540/.
        return ["java", "scala", "python"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--allow-empty",
            type=bool,
            default=True,
            fingerprint=True,
            help="Skip targets with no sources defined.",
            advanced=True,
        )
        register(
            "--allow-dups",
            type=bool,
            fingerprint=True,
            help="Allow multiple targets specifying the same sources. If duplicates are "
            "allowed, the task will associate generated sources with the least-dependent "
            "targets that generate them.",
            advanced=True,
        )

    @classmethod
    def get_fingerprint_strategy(cls):
        """Override this method to use a fingerprint strategy other than the default one.

        :API: public

        :return: a fingerprint strategy, or None to use the default strategy.
        """
        return None

    @property
    def cache_target_dirs(self):
        return True

    @property
    def validate_sources_present(self):
        """A property indicating whether input targets require sources.

        If targets should have sources, the `--allow-empty` flag indicates whether it is a
        warning or an error for sources to be missing.

        :API: public
        """
        return True

    def synthetic_target_extra_dependencies(self, target, target_workdir):
        """Gets any extra dependencies generated synthetic targets should have.

        This method is optional for subclasses to implement, because some code generators may have no
        extra dependencies.
        :param Target target: the Target from which we are generating a synthetic Target. E.g., 'target'
        might be a JavaProtobufLibrary, whose corresponding synthetic Target would be a JavaLibrary.
        It may not be necessary to use this parameter depending on the details of the subclass.

        :API: public

        :return: a list of dependencies.
        """
        return []

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("SimpleCodegenTask", 2)]

    def synthetic_target_extra_exports(self, target, target_workdir):
        """Gets any extra exports generated synthetic targets should have.

        This method is optional for subclasses to implement, because some code generators may have no
         extra exports.
         NB: Extra exports must also be present in the extra dependencies.
         :param Target target: the Target from which we are generating a synthetic Target. E.g., 'target'
         might be a JavaProtobufLibrary, whose corresponding synthetic Target would be a JavaLibrary.
         It may not be necessary to use this parameter depending on the details of the subclass.

         :API: public

         :return: a list of exported targets.
        """
        return []

    def synthetic_target_type(self, target):
        """The type of target this codegen task generates.

        For example, the target type for JaxbGen would simply be JavaLibrary.

        :API: public

        :return: a type (class) that inherits from Target.
        """
        raise NotImplementedError

    def is_gentarget(self, target):
        """Predicate which determines whether the target in question is relevant to this codegen
        task.

        E.g., the JaxbGen task considers JaxbLibrary targets to be relevant, and nothing else.

        :API: public

        :param Target target: The target to check.
        :return: True if this class can generate code for the given target, False otherwise.
        """
        if self.gentarget_type:
            return isinstance(target, self.gentarget_type)
        else:
            raise NotImplementedError

    def ignore_dup(self, tgt1, tgt2, rel_src):
        """Subclasses can override to omit a specific generated source file from dup checking."""
        return False

    def codegen_targets(self):
        """Finds codegen targets in the dependency graph.

        :API: public

        :return: an iterable of dependency targets.
        """
        return self.get_targets(self.is_gentarget)

    def _do_validate_sources_present(self, target):
        """Checks whether sources is empty, and either raises a TaskError or just returns False.

        The specifics of this behavior are defined by whether the user sets --allow-empty to True/False:
        --allow-empty=False will result in a TaskError being raised in the event of an empty source
        set. If --allow-empty=True, this method will just return false and log a warning.

        Shared for all SimpleCodegenTask subclasses to help keep errors consistent and descriptive.

        :param target: Target to validate.
        :return: True if sources is not empty, False otherwise.
        """
        if not self.validate_sources_present:
            return True
        sources = target.sources_relative_to_buildroot()
        if not sources:
            message = "Target {} has no sources.".format(target.address.spec)
            if not self.get_options().allow_empty:
                raise TaskError(message)
            else:
                logging.warn(message)
                return False
        return True

    def _get_synthetic_address(self, target, target_workdir):
        synthetic_name = target.id
        sources_rel_path = fast_relpath(target_workdir, get_buildroot())
        synthetic_address = Address(sources_rel_path, synthetic_name)
        return synthetic_address

    @classmethod
    def _validate_sources_globs(cls):
        if cls.sources_globs is None:
            raise Exception("Task {} must define a `sources_globs` property.".format(cls.__name__))

    def execute(self):
        codegen_targets = self.codegen_targets()
        if not codegen_targets:
            return

        self._validate_sources_globs()

        with self.invalidated(
            codegen_targets,
            invalidate_dependents=True,
            topological_order=True,
            fingerprint_strategy=self.get_fingerprint_strategy(),
        ) as invalidation_check:

            with self.context.new_workunit(name="execute", labels=[WorkUnitLabel.MULTITOOL]):
                vts_to_sources = OrderedDict()
                for vt in invalidation_check.all_vts:

                    vts_to_sources[vt] = None

                    # Build the target and handle duplicate sources.
                    if not vt.valid:
                        if self._do_validate_sources_present(vt.target):
                            self.execute_codegen(vt.target, vt.current_results_dir)
                            sources = self._capture_sources((vt,))[0]
                            # _handle_duplicate_sources may delete files from the filesystem, so we need to
                            # re-capture the sources.
                            if not self._handle_duplicate_sources(vt, sources):
                                vts_to_sources[vt] = sources
                        vt.update()

                vts_to_capture = tuple(
                    key for key, sources in vts_to_sources.items() if sources is None
                )
                filesets = self._capture_sources(vts_to_capture)
                for key, fileset in zip(vts_to_capture, filesets):
                    vts_to_sources[key] = fileset
                for vt, fileset in vts_to_sources.items():
                    self._inject_synthetic_target(vt, fileset)
                self._mark_transitive_invalidation_hashes_dirty(
                    vt.target.address for vt in invalidation_check.all_vts
                )

    def _mark_transitive_invalidation_hashes_dirty(self, addresses):
        self.context.build_graph.walk_transitive_dependee_graph(
            addresses, work=lambda t: t.mark_transitive_invalidation_hash_dirty(),
        )

    @property
    def _copy_target_attributes(self):
        """Return a list of attributes to be copied from the target to derived synthetic targets.

        By default, propagates the provides, scope, and tags attributes.
        """
        return ["provides", "tags", "scope"]

    def synthetic_target_dir(self, target, target_workdir):
        """
    :API: public
    """
        return target_workdir

    # Accepts tuple of VersionedTarget instances.
    # Returns tuple of EagerFilesetWithSpecs in matching order.
    def _capture_sources(self, vts):
        to_capture = []
        results_dirs = []
        filespecs = []

        for vt in vts:
            target = vt.target
            # Compute the (optional) subdirectory of the results_dir to generate code to. This
            # path will end up in the generated FilesetWithSpec and target, and thus needs to be
            # located below the stable/symlinked `vt.results_dir`.
            synthetic_target_dir = self.synthetic_target_dir(target, vt.results_dir)

            files = self.sources_globs

            results_dir_relpath = fast_relpath(synthetic_target_dir, get_buildroot())
            buildroot_relative_globs = tuple(
                os.path.join(results_dir_relpath, file) for file in files
            )
            buildroot_relative_excludes = tuple(
                f"!{os.path.join(results_dir_relpath, file)}" for file in self.sources_exclude_globs
            )
            to_capture.append(
                PathGlobsAndRoot(
                    PathGlobs(globs=(*buildroot_relative_globs, *buildroot_relative_excludes)),
                    get_buildroot(),
                    # The digest is stored adjacent to the hash-versioned `vt.current_results_dir`.
                    Digest.load(vt.current_results_dir),
                )
            )
            results_dirs.append(results_dir_relpath)
            filespecs.append(FilesetRelPathWrapper.to_filespec(buildroot_relative_globs))

        snapshots = self.context._scheduler.capture_snapshots(tuple(to_capture))

        for snapshot, vt in zip(snapshots, vts):
            snapshot.directory_digest.dump(vt.current_results_dir)

        return tuple(
            EagerFilesetWithSpec(results_dir_relpath, filespec, snapshot,)
            for (results_dir_relpath, filespec, snapshot) in zip(results_dirs, filespecs, snapshots)
        )

    def _inject_synthetic_target(self, vt, sources):
        """Create, inject, and return a synthetic target for the given target and workdir.

        :param vt: A codegen input VersionedTarget to inject a synthetic target for.
        :param sources: A FilesetWithSpec to inject for the target.
        """
        target = vt.target

        # NB: For stability, the injected target exposes the stable-symlinked `vt.results_dir`,
        # rather than the hash-named `vt.current_results_dir`.
        synthetic_target_dir = self.synthetic_target_dir(target, vt.results_dir)
        synthetic_target_type = self.synthetic_target_type(target)
        synthetic_extra_dependencies = self.synthetic_target_extra_dependencies(
            target, synthetic_target_dir
        )

        copied_attributes = {}
        for attribute in self._copy_target_attributes:
            copied_attributes[attribute] = getattr(target, attribute)

        if self._supports_exports(synthetic_target_type):
            extra_exports = self.synthetic_target_extra_exports(target, synthetic_target_dir)

            extra_exports_not_in_extra_dependencies = set(extra_exports).difference(
                set(synthetic_extra_dependencies)
            )
            if len(extra_exports_not_in_extra_dependencies) > 0:
                raise self.MismatchedExtraExports(
                    "Extra synthetic exports included targets not in the extra dependencies: {}. Affected target: {}".format(
                        extra_exports_not_in_extra_dependencies, target
                    )
                )

            extra_export_specs = {e.address.spec for e in extra_exports}
            original_export_specs = self._original_export_specs(target)
            union = set(original_export_specs).union(extra_export_specs)

            copied_attributes["exports"] = sorted(union)

        synthetic_target = self.context.add_new_target(
            address=self._get_synthetic_address(target, synthetic_target_dir),
            target_type=synthetic_target_type,
            dependencies=synthetic_extra_dependencies,
            sources=sources,
            derived_from=target,
            **copied_attributes,
        )

        build_graph = self.context.build_graph
        # NB(pl): This bypasses the convenience function (Target.inject_dependency) in order
        # to improve performance.  Note that we can walk the transitive dependee subgraph once
        # for transitive invalidation rather than walking a smaller subgraph for every single
        # dependency injected.
        for dependent_address in build_graph.dependents_of(target.address):
            build_graph.inject_dependency(
                dependent=dependent_address, dependency=synthetic_target.address,
            )
        # NB(pl): See the above comment.  The same note applies.
        for concrete_dependency_address in build_graph.dependencies_of(target.address):
            build_graph.inject_dependency(
                dependent=synthetic_target.address, dependency=concrete_dependency_address,
            )

        if target in self.context.target_roots:
            self.context.target_roots.append(synthetic_target)

        return synthetic_target

    def _supports_exports(self, target_type):
        return hasattr(target_type, "export_specs")

    def _original_export_specs(self, target):
        return [t.spec for t in target.export_addresses]

    def resolve_deps(self, unresolved_deps):
        """
        :API: public
        """
        deps = OrderedSet()
        for dep in unresolved_deps:
            try:
                deps.update(self.context.resolve(dep))
            except AddressLookupError as e:
                raise AddressLookupError(
                    "{message}\n  on dependency {dep}".format(message=e, dep=dep)
                )
        return deps

    @abstractmethod
    def execute_codegen(self, target, target_workdir):
        """Generate code for the given target.

        :param target: A target to generate code for
        :param target_workdir: A clean directory into which to generate code
        """

    def _handle_duplicate_sources(self, vt, sources):
        """Handles duplicate sources generated by the given gen target by either failure or
        deletion.

        This method should be called after all dependencies have been injected into the graph, but
        before injecting the synthetic version of this target.

        Returns a boolean indicating whether it modified the underlying filesystem.

        NB(gm): Some code generators may re-generate code that their dependent libraries generate.
        This results in targets claiming to generate sources that they really don't, so we try to
        filter out sources that were actually generated by dependencies of the target. This causes
        the code generated by the dependencies to 'win' over the code generated by dependees. By
        default, this behavior is disabled, and duplication in generated sources will raise a
        TaskError. This is controlled by the --allow-dups flag.
        """
        target = vt.target
        target_workdir = vt.results_dir

        # Walk dependency gentargets and record any sources owned by those targets that are also
        # owned by this target.
        duplicates_by_target = OrderedDict()

        def record_duplicates(dep):
            if dep == target or not self.is_gentarget(dep.concrete_derived_from):
                return False
            duped_sources = [
                s
                for s in dep.sources_relative_to_source_root()
                if s in sources.files and not self.ignore_dup(target, dep, s)
            ]
            if duped_sources:
                duplicates_by_target[dep] = duped_sources

        target.walk(record_duplicates)

        # If there were no dupes, we're done.
        if not duplicates_by_target:
            return False

        # If there were duplicates warn or error.
        messages = [
            "{target} generated sources that had already been generated by dependencies.".format(
                target=target.address.spec
            )
        ]
        for dep, duped_sources in duplicates_by_target.items():
            messages.append("\t{} also generated:".format(dep.concrete_derived_from.address.spec))
            messages.extend(["\t\t{}".format(source) for source in duped_sources])
        message = "\n".join(messages)
        if self.get_options().allow_dups:
            logger.warning(message)
        else:
            raise self.DuplicateSourceError(message)

        did_modify = False

        # Finally, remove duplicates from the workdir. This prevents us from having to worry
        # about them during future incremental compiles.
        for dep, duped_sources in duplicates_by_target.items():
            for duped_source in duped_sources:
                safe_delete(os.path.join(target_workdir, duped_source))
                did_modify = True
        if did_modify:
            Digest.clear(vt.current_results_dir)
        return did_modify

    class DuplicateSourceError(TaskError):
        """A target generated the same code that was generated by one of its dependencies.

        This is only thrown when --allow-dups=False.
        """

    class MismatchedExtraExports(Exception):
        """An extra export didn't have an accompanying explicit extra dependency for the same
        target.

        NB: Exports without accompanying dependencies are caught during compile, but this error will
        allow errors caused by injected exports to be surfaced earlier.
        """
