# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from pants.backend.native.tasks.native_task import NativeTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import classproperty
from pants.util.objects import TypeConstraint


@dataclass(frozen=True)
class NativeCompileRequest:
    compiler: Any
    include_dirs: Any
    sources: Any
    compiler_options: Any
    output_dir: Any
    header_file_extensions: Any


# TODO(#5950): perform all process execution in the v2 engine!
@dataclass(frozen=True)
class ObjectFiles:
    root_dir: Any
    filenames: Any

    def file_paths(self):
        return [os.path.join(self.root_dir, fname) for fname in self.filenames]


class NativeCompile(NativeTask, metaclass=ABCMeta):
    # `NativeCompile` will use the `source_target_constraint` to determine what targets have "sources"
    # to compile, and the `dependent_target_constraint` to determine which dependent targets to
    # operate on for `strict_deps` calculation.
    # NB: `source_target_constraint` must be overridden.
    source_target_constraint: Optional[TypeConstraint] = None

    @classproperty
    @abstractmethod
    def workunit_label(cls):
        """A string describing the work being done during compilation.

        `NativeCompile` will use `workunit_label` as the name of the workunit when executing the
        compiler process.

        :rtype: str
        """

    @classmethod
    def product_types(cls):
        return [ObjectFiles]

    @property
    def cache_target_dirs(self):
        return True

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("NativeCompile", 1)]

    class NativeCompileError(TaskError):
        """Raised for errors in this class's logic.

        Subclasses are advised to create their own exception class.
        """

    def execute(self):
        object_files_product = self.context.products.get(ObjectFiles)
        source_targets = self.context.targets(self.source_target_constraint.satisfied_by)

        with self.invalidated(source_targets, invalidate_dependents=True) as invalidation_check:
            for vt in invalidation_check.all_vts:
                if not vt.valid:
                    compile_request = self._make_compile_request(vt)
                    self.context.log.debug("compile_request: {}".format(compile_request))
                    self._compile(compile_request)

                object_files = self.collect_cached_objects(vt)
                self._add_product_at_target_base(object_files_product, vt.target, object_files)

    # This may be calculated many times for a target, so we memoize it.
    @memoized_method
    def _include_dirs_for_target(self, target):
        return os.path.join(get_buildroot(), target.address.spec_path)

    @dataclass(frozen=True)
    class NativeSourcesByType:
        rel_root: Any
        headers: Any
        sources: Any

    def get_sources_headers_for_target(self, target):
        """Return a list of file arguments to provide to the compiler.

        NB: result list will contain both header and source files!

        :raises: :class:`NativeCompile.NativeCompileError` if there is an error processing the sources.
        """
        # Get source paths relative to the target base so the exception message with the target and
        # paths makes sense.
        target_relative_sources = target.sources_relative_to_target_base()
        rel_root = target_relative_sources.rel_root

        # Unique file names are required because we just dump object files into a single directory, and
        # the compiler will silently just produce a single object file if provided non-unique filenames.
        # TODO: add some shading to file names so we can remove this check.
        # NB: It shouldn't matter if header files have the same name, but this will raise an error in
        # that case as well. We won't need to do any shading of header file names.
        seen_filenames = defaultdict(list)
        for src in target_relative_sources:
            seen_filenames[os.path.basename(src)].append(src)
        duplicate_filename_err_msgs = []
        for fname, source_paths in seen_filenames.items():
            if len(source_paths) > 1:
                duplicate_filename_err_msgs.append(
                    "filename: {}, paths: {}".format(fname, source_paths)
                )
        if duplicate_filename_err_msgs:
            raise self.NativeCompileError(
                "Error in target '{}': source files must have a unique filename within a '{}' target. "
                "Conflicting filenames:\n{}".format(
                    target.address.spec, target.alias(), "\n".join(duplicate_filename_err_msgs)
                )
            )

        return [os.path.join(get_buildroot(), rel_root, src) for src in target_relative_sources]

    @abstractmethod
    def get_compile_settings(self):
        """Return an instance of NativeBuildStep.

        NB: Subclasses will be queried for the compile settings once and the result cached.
        """

    @memoized_property
    def _compile_settings(self):
        return self.get_compile_settings()

    @abstractmethod
    def get_compiler(self, native_library_target):
        """An instance of `_CompilerMixin` which can be invoked to compile files.

        NB: Subclasses will be queried for the compiler instance once and the result cached.

        :return: :class:`pants.backend.native.config.environment._CompilerMixin`
        """

    def _compiler(self, native_library_target):
        return self.get_compiler(native_library_target)

    def _make_compile_request(self, versioned_target):
        target = versioned_target.target

        include_dirs = []
        for dep in self.native_deps(target):
            source_lib_base_dir = os.path.join(get_buildroot(), dep._sources_field.rel_path)
            include_dirs.append(source_lib_base_dir)
        for ext_dep in self.packaged_native_deps(target):
            external_lib_include_dir = os.path.join(
                get_buildroot(), ext_dep._sources_field.rel_path, ext_dep.include_relpath
            )
            self.context.log.debug(
                "ext_dep: {}, external_lib_include_dir: {}".format(
                    ext_dep, external_lib_include_dir
                )
            )
            include_dirs.append(external_lib_include_dir)

        sources_and_headers = self.get_sources_headers_for_target(target)
        compiler_option_sets = self._compile_settings.native_build_step.get_compiler_option_sets_for_target(
            target
        )
        self.context.log.debug(
            "target: {}, compiler_option_sets: {}".format(target, compiler_option_sets)
        )

        compile_request = NativeCompileRequest(
            compiler=self._compiler(target),
            include_dirs=include_dirs,
            sources=sources_and_headers,
            compiler_options=(
                self._compile_settings.native_build_step.get_merged_args_for_compiler_option_sets(
                    compiler_option_sets
                )
            ),
            output_dir=versioned_target.results_dir,
            header_file_extensions=self._compile_settings.header_file_extensions,
        )

        self.context.log.debug(repr(compile_request))

        return compile_request

    def _iter_sources_minus_headers(self, compile_request):
        for s in compile_request.sources:
            if not s.endswith(tuple(compile_request.header_file_extensions)):
                yield s

    class _HeaderOnlyLibrary(Exception):
        pass

    def _make_compile_argv(self, compile_request):
        """Return a list of arguments to use to compile sources.

        Subclasses can override and append.
        """

        sources_minus_headers = list(self._iter_sources_minus_headers(compile_request))
        if len(sources_minus_headers) == 0:
            raise self._HeaderOnlyLibrary()

        compiler = compile_request.compiler
        compiler_options = compile_request.compiler_options
        # We are going to execute in the target output, so get absolute paths for everything.
        buildroot = get_buildroot()
        # TODO: add -v to every compiler and linker invocation!
        argv = (
            [compiler.exe_filename]
            + list(compiler.extra_args)
            +
            # TODO: If we need to produce static libs, don't add -fPIC! (could use Variants -- see #5788).
            ["-c", "-fPIC"]
            + list(compiler_options)
            + [
                "-I{}".format(os.path.join(buildroot, inc_dir))
                for inc_dir in compile_request.include_dirs
            ]
            + [os.path.join(buildroot, src) for src in sources_minus_headers]
        )

        self.context.log.info("selected compiler exe name: '{}'".format(compiler.exe_filename))
        self.context.log.debug("compile argv: {}".format(argv))

        return argv

    def _compile(self, compile_request):
        """Perform the process of compilation, writing object files to the request's 'output_dir'.

        NB: This method must arrange the output files so that `collect_cached_objects()` can collect all
        of the results (or vice versa)!
        """

        try:
            argv = self._make_compile_argv(compile_request)
        except self._HeaderOnlyLibrary:
            self.context.log.debug("{} is a header-only library".format(compile_request))
            return

        compiler = compile_request.compiler
        output_dir = compile_request.output_dir
        env = compiler.invocation_environment_dict

        with self.context.new_workunit(
            name=self.workunit_label, labels=[WorkUnitLabel.COMPILER]
        ) as workunit:
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=output_dir,
                    stdout=workunit.output("stdout"),
                    stderr=workunit.output("stderr"),
                    env=env,
                )
            except OSError as e:
                workunit.set_outcome(WorkUnit.FAILURE)
                raise self.NativeCompileError(
                    "Error invoking '{exe}' with command {cmd} and environment {env} for request {req}: {err}".format(
                        exe=compiler.exe_filename, cmd=argv, env=env, req=compile_request, err=e
                    )
                )

            rc = process.wait()
            if rc != 0:
                workunit.set_outcome(WorkUnit.FAILURE)
                raise self.NativeCompileError(
                    "Error in '{section_name}' with command {cmd} and environment {env} for request {req}. "
                    "Exit code was: {rc}.".format(
                        section_name=self.workunit_label,
                        cmd=argv,
                        env=env,
                        req=compile_request,
                        rc=rc,
                    )
                )

    def collect_cached_objects(self, versioned_target):
        """Scan `versioned_target`'s results directory and return the output files from that
        directory.

        :return: :class:`ObjectFiles`
        """
        return ObjectFiles(versioned_target.results_dir, os.listdir(versioned_target.results_dir))
