# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from dataclasses import dataclass
from typing import Any, Tuple

from pants.backend.native.config.environment import Linker
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.native_compile import ObjectFiles
from pants.backend.native.tasks.native_task import NativeTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.engine.platform import Platform
from pants.util.enums import match
from pants.util.memo import memoized_property


@dataclass(frozen=True)
class SharedLibrary:
    name: Any
    path: Any


@dataclass(frozen=True)
class LinkSharedLibraryRequest:
    linker: Linker
    object_files: Tuple
    native_artifact: NativeArtifact
    output_dir: Any
    external_lib_dirs: Tuple
    external_lib_names: Tuple


class LinkSharedLibraries(NativeTask):

    options_scope = "link-shared-libraries"

    @classmethod
    def product_types(cls):
        return [SharedLibrary]

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require(ObjectFiles)

    @property
    def cache_target_dirs(self):
        return True

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("LinkSharedLibraries", 1)]

    class LinkSharedLibrariesError(TaskError):
        pass

    def linker(self, native_library_target):
        # NB: we are using the C++ toolchain here for linking every type of input, including compiled C
        # source files.
        return self.get_cpp_toolchain_variant(native_library_target).cpp_linker

    @memoized_property
    def platform(self) -> Platform:
        # TODO: convert this to a v2 engine dependency injection.
        return Platform.current

    def execute(self):
        targets_providing_artifacts = self.context.targets(
            NativeLibrary.produces_ctypes_native_library
        )
        compiled_objects_product = self.context.products.get(ObjectFiles)
        shared_libs_product = self.context.products.get(SharedLibrary)

        all_shared_libs_by_name = {}

        with self.invalidated(
            targets_providing_artifacts, invalidate_dependents=True
        ) as invalidation_check:
            for vt in invalidation_check.all_vts:
                if vt.valid:
                    shared_library = self._retrieve_shared_lib_from_cache(vt)
                else:
                    # TODO: We need to partition links based on proper dependency edges and not
                    # perform a link to every packaged_native_library() for all targets in the closure.
                    # https://github.com/pantsbuild/pants/issues/6178
                    link_request = self._make_link_request(vt, compiled_objects_product)
                    self.context.log.debug("link_request: {}".format(link_request))
                    shared_library = self._execute_link_request(link_request)

                same_name_shared_lib = all_shared_libs_by_name.get(shared_library.name, None)
                if same_name_shared_lib:
                    # TODO: test this branch!
                    raise self.LinkSharedLibrariesError(
                        "The name '{name}' was used for two shared libraries: {prev} and {cur}.".format(
                            name=shared_library.name, prev=same_name_shared_lib, cur=shared_library
                        )
                    )
                else:
                    all_shared_libs_by_name[shared_library.name] = shared_library

                self._add_product_at_target_base(shared_libs_product, vt.target, shared_library)

    def _retrieve_shared_lib_from_cache(self, vt):
        native_artifact = vt.target.ctypes_native_library
        path_to_cached_lib = os.path.join(
            vt.results_dir, native_artifact.as_shared_lib(self.platform)
        )
        if not os.path.isfile(path_to_cached_lib):
            raise self.LinkSharedLibrariesError(
                "The shared library at {} does not exist!".format(path_to_cached_lib)
            )
        return SharedLibrary(name=native_artifact.lib_name, path=path_to_cached_lib)

    def _make_link_request(self, vt, compiled_objects_product):
        self.context.log.debug("link target: {}".format(vt.target))

        deps = self.native_deps(vt.target)

        all_compiled_object_files = []
        for dep_tgt in deps:
            if compiled_objects_product.get(dep_tgt):
                self.context.log.debug("dep_tgt: {}".format(dep_tgt))
                object_files = self._retrieve_single_product_at_target_base(
                    compiled_objects_product, dep_tgt
                )
                self.context.log.debug("object_files: {}".format(object_files))
                object_file_paths = object_files.file_paths()
                self.context.log.debug("object_file_paths: {}".format(object_file_paths))
                all_compiled_object_files.extend(object_file_paths)

        external_lib_dirs = []
        external_lib_names = []
        for ext_dep in self.packaged_native_deps(vt.target):
            external_lib_dirs.append(
                os.path.join(get_buildroot(), ext_dep._sources_field.rel_path, ext_dep.lib_relpath)
            )

            native_lib_names = ext_dep.native_lib_names
            if isinstance(native_lib_names, dict):
                # `native_lib_names` is a dictionary mapping the string representation of the Platform
                # ('darwin' vs. 'linux') to a list of strings. We use the Enum's `.value` to get the
                # underlying string value to lookup the relevant key in the dictionary.
                native_lib_names = native_lib_names[self.platform.value]
            external_lib_names.extend(native_lib_names)

        link_request = LinkSharedLibraryRequest(
            linker=self.linker(vt.target),
            object_files=tuple(all_compiled_object_files),
            native_artifact=vt.target.ctypes_native_library,
            output_dir=vt.results_dir,
            external_lib_dirs=tuple(external_lib_dirs),
            external_lib_names=tuple(external_lib_names),
        )

        self.context.log.debug(repr(link_request))

        return link_request

    def _execute_link_request(self, link_request):
        object_files = link_request.object_files

        if len(object_files) == 0:
            raise self.LinkSharedLibrariesError(
                "No object files were provided in request {}!".format(link_request)
            )

        linker = link_request.linker
        native_artifact = link_request.native_artifact
        output_dir = link_request.output_dir
        resulting_shared_lib_path = os.path.join(
            output_dir, native_artifact.as_shared_lib(self.platform)
        )

        self.context.log.debug("resulting_shared_lib_path: {}".format(resulting_shared_lib_path))
        # We are executing in the results_dir, so get absolute paths for everything.
        cmd = (
            [linker.exe_filename]
            + match(self.platform, {Platform.darwin: ["-Wl,-dylib"], Platform.linux: ["-shared"]})
            + list(linker.extra_args)
            + ["-o", os.path.abspath(resulting_shared_lib_path)]
            + ["-L{}".format(lib_dir) for lib_dir in link_request.external_lib_dirs]
            + ["-l{}".format(lib_name) for lib_name in link_request.external_lib_names]
            + [os.path.abspath(obj) for obj in object_files]
        )

        self.context.log.info("selected linker exe name: '{}'".format(linker.exe_filename))
        self.context.log.debug("linker argv: {}".format(cmd))

        env = linker.invocation_environment_dict
        self.context.log.debug("linker invocation environment: {}".format(env))

        with self.context.new_workunit(
            name="link-shared-libraries", labels=[WorkUnitLabel.LINKER]
        ) as workunit:
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=output_dir,
                    stdout=workunit.output("stdout"),
                    stderr=workunit.output("stderr"),
                    env=env,
                )
            except OSError as e:
                workunit.set_outcome(WorkUnit.FAILURE)
                raise self.LinkSharedLibrariesError(
                    "Error invoking the native linker with command {cmd} and environment {env} "
                    "for request {req}: {err}.".format(cmd=cmd, env=env, req=link_request, err=e),
                    e,
                )

            rc = process.wait()
            if rc != 0:
                workunit.set_outcome(WorkUnit.FAILURE)
                raise self.LinkSharedLibrariesError(
                    "Error linking native objects with command {cmd} and environment {env} "
                    "for request {req}. Exit code was: {rc}.".format(
                        cmd=cmd, env=env, req=link_request, rc=rc
                    )
                )

        return SharedLibrary(name=native_artifact.lib_name, path=resulting_shared_lib_path)
