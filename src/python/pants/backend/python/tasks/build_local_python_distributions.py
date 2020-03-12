# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import re
import shutil
from pathlib import Path

from pex.interpreter import PythonInterpreter
from wheel import pep425tags

from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.link_shared_libraries import SharedLibrary
from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.python.pex_build_util import is_local_python_dist
from pants.python.python_requirement import PythonRequirement
from pants.python.setup_py_runner import SetupPyRunner
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.dirutil import safe_mkdir_for, split_basename_and_dirname
from pants.util.memo import memoized_property
from pants.util.strutil import safe_shlex_join


# TODO: make this a SimpleCodegenTask!!!
class BuildLocalPythonDistributions(Task):
    """Create python distributions (.whl) from python_dist targets."""

    options_scope = "python-create-distributions"

    # NB: these are all the immediate subdirectories of the target's results directory.
    # This contains any modules from a setup_requires().
    _SETUP_REQUIRES_SITE_SUBDIR = "setup_requires_site"
    # This will contain the sources used to build the python_dist().
    _DIST_SOURCE_SUBDIR = "python_dist_subdir"

    setup_requires_pex_filename = "setup-requires.pex"

    # This defines the output directory when building the dist, so we know where the output wheel is
    # located. It is a subdirectory of `_DIST_SOURCE_SUBDIR`.
    _DIST_OUTPUT_DIR = "dist"

    @classmethod
    def product_types(cls):
        # Note that we don't actually place the products in the product map. We stitch
        # them into the build graph instead.  This is just to force the round engine
        # to run this task when dists need to be built.
        return [PythonRequirementLibrary, "local_wheels"]

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data(PythonInterpreter)
        round_manager.optional_product(SharedLibrary)

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("BuildLocalPythonDistributions", 3)]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            SetupPyRunner.Factory.scoped(cls),
            PythonNativeCode.scoped(cls),
        )

    class BuildLocalPythonDistributionsError(TaskError):
        pass

    @memoized_property
    def _python_native_code_settings(self):
        return PythonNativeCode.scoped_instance(self)

    def _build_setup_py_runner(self, extra_reqs=None, interpreter=None, pex_file_path=None):
        return SetupPyRunner.Factory.create(
            scope=self, extra_reqs=extra_reqs, interpreter=interpreter, pex_file_path=pex_file_path
        )

    # TODO: This should probably be made into an @classproperty (see PR #5901).
    @property
    def cache_target_dirs(self):
        return True

    def _get_setup_requires_to_resolve(self, dist_target):
        if not dist_target.setup_requires:
            return None

        reqs_to_resolve = set()

        for setup_req_lib_addr in dist_target.setup_requires:
            for maybe_req_lib in self.context.build_graph.resolve(setup_req_lib_addr):
                if isinstance(maybe_req_lib, PythonRequirementLibrary):
                    for req in maybe_req_lib.requirements:
                        reqs_to_resolve.add(req)

        if not reqs_to_resolve:
            return None

        return reqs_to_resolve

    @classmethod
    def _get_output_dir(cls, results_dir):
        return os.path.join(results_dir, cls._DIST_SOURCE_SUBDIR)

    @classmethod
    def _get_dist_dir(cls, results_dir):
        return os.path.join(cls._get_output_dir(results_dir), cls._DIST_OUTPUT_DIR)

    def execute(self):
        dist_targets = self.context.targets(is_local_python_dist)

        if dist_targets:
            interpreter = self.context.products.get_data(PythonInterpreter)
            shared_libs_product = self.context.products.get(SharedLibrary)

            with self.invalidated(dist_targets, invalidate_dependents=True) as invalidation_check:
                for vt in invalidation_check.invalid_vts:
                    self._prepare_and_create_dist(interpreter, shared_libs_product, vt)

                local_wheel_products = self.context.products.get("local_wheels")
                for vt in invalidation_check.all_vts:
                    dist = self._get_whl_from_dir(vt.results_dir)
                    req_lib_addr = Address.parse(f"{vt.target.address.spec}__req_lib")
                    self._inject_synthetic_dist_requirements(dist, req_lib_addr)
                    # Make any target that depends on the dist depend on the synthetic req_lib,
                    # for downstream consumption.
                    for dependent in self.context.build_graph.dependents_of(vt.target.address):
                        self.context.build_graph.inject_dependency(dependent, req_lib_addr)
                    dist_dir, dist_base = split_basename_and_dirname(dist)
                    local_wheel_products.add(vt.target, dist_dir).append(dist_base)

    def _get_native_artifact_deps(self, target):
        native_artifact_targets = []
        if target.dependencies:
            for dep_tgt in target.dependencies:
                if not NativeLibrary.produces_ctypes_native_library(dep_tgt):
                    raise TargetDefinitionException(
                        target,
                        "Target '{}' is invalid: the only dependencies allowed in python_dist() targets "
                        "are C or C++ targets with a ctypes_native_library= kwarg.".format(
                            dep_tgt.address.spec
                        ),
                    )
                native_artifact_targets.append(dep_tgt)
        return native_artifact_targets

    def _copy_sources(self, dist_tgt, dist_target_dir):
        # Copy sources and setup.py over to vt results directory for packaging.
        # NB: The directory structure of the destination directory needs to match 1:1
        # with the directory structure that setup.py expects.
        all_sources = list(dist_tgt.sources_relative_to_target_base())
        for src_relative_to_target_base in all_sources:
            src_rel_to_results_dir = os.path.join(dist_target_dir, src_relative_to_target_base)
            safe_mkdir_for(src_rel_to_results_dir)
            abs_src_path = os.path.join(
                get_buildroot(), dist_tgt.address.spec_path, src_relative_to_target_base
            )
            shutil.copyfile(abs_src_path, src_rel_to_results_dir)

    def _add_artifacts(self, dist_target_dir, shared_libs_product, native_artifact_targets):
        all_shared_libs = []
        for tgt in native_artifact_targets:
            product_mapping = shared_libs_product.get(tgt)
            base_dir = assert_single_element(product_mapping.keys())
            shared_lib = assert_single_element(product_mapping[base_dir])
            all_shared_libs.append(shared_lib)

        for shared_lib in all_shared_libs:
            basename = os.path.basename(shared_lib.path)
            # NB: We convert everything to .so here so that the setup.py can just
            # declare .so to build for either platform.
            resolved_outname = re.sub(r"\..*\Z", ".so", basename)
            dest_path = os.path.join(dist_target_dir, resolved_outname)
            safe_mkdir_for(dest_path)
            shutil.copyfile(shared_lib.path, dest_path)

        return all_shared_libs

    def _prepare_and_create_dist(self, interpreter, shared_libs_product, versioned_target):
        dist_target = versioned_target.target

        native_artifact_deps = self._get_native_artifact_deps(dist_target)

        results_dir = versioned_target.results_dir

        dist_output_dir = self._get_output_dir(results_dir)

        all_native_artifacts = self._add_artifacts(
            dist_output_dir, shared_libs_product, native_artifact_deps
        )

        # TODO: remove the triplication all of this validation across _get_native_artifact_deps(),
        # check_build_for_current_platform_only(), and len(all_native_artifacts) > 0!
        is_platform_specific = (
            # We are including a platform-specific shared lib in this dist, so mark it as such.
            len(all_native_artifacts) > 0
            or self._python_native_code_settings.check_build_for_current_platform_only(
                # NB: This doesn't reach into transitive dependencies, but that doesn't matter currently.
                [dist_target]
                + dist_target.dependencies
            )
        )

        versioned_target_fingerprint = versioned_target.cache_key.hash

        setup_requires_dir = os.path.join(results_dir, self._SETUP_REQUIRES_SITE_SUBDIR)
        setup_reqs_to_resolve = self._get_setup_requires_to_resolve(dist_target)
        if setup_reqs_to_resolve:
            self.context.log.debug(
                "python_dist target(s) with setup_requires detected. "
                "Installing setup requirements: {}\n\n".format(
                    [req.key for req in setup_reqs_to_resolve]
                )
            )

        pex_file_path = os.path.join(
            setup_requires_dir, f"setup-py-runner-{versioned_target_fingerprint}.pex"
        )
        setup_py_runner = self._build_setup_py_runner(
            interpreter=interpreter, extra_reqs=setup_reqs_to_resolve, pex_file_path=pex_file_path
        )
        self.context.log.debug(f"Using pex file as setup.py interpreter: {setup_py_runner}")

        self._create_dist(
            dist_target,
            dist_output_dir,
            setup_py_runner,
            versioned_target_fingerprint,
            is_platform_specific,
        )

    # NB: "snapshot" refers to a "snapshot release", not a Snapshot.
    def _generate_snapshot_bdist_wheel_argv(self, snapshot_fingerprint, is_platform_specific):
        """Create a command line to generate a wheel via `setup.py`.

        Note that distutils will convert `snapshot_fingerprint` into a string suitable for a version
        tag. Currently for versioned target fingerprints, this seems to convert all punctuation into
        '.' and downcase all ASCII chars. See https://www.python.org/dev/peps/pep-0440/ for further
        information on allowed version names.

        NB: adds a '+' before the fingerprint to the build tag!
        """
        egg_info_snapshot_tag_args = ["egg_info", f"--tag-build=+{snapshot_fingerprint}"]
        bdist_whl_args = ["bdist_wheel"]
        if is_platform_specific:
            platform_args = ["--plat-name", pep425tags.get_platform()]
        else:
            platform_args = []

        dist_dir_args = ["--dist-dir", self._DIST_OUTPUT_DIR]

        return egg_info_snapshot_tag_args + bdist_whl_args + platform_args + dist_dir_args

    def _create_dist(
        self, dist_tgt, dist_target_dir, setup_py_runner, snapshot_fingerprint, is_platform_specific
    ):
        """Create a .whl file for the specified python_distribution target."""
        self._copy_sources(dist_tgt, dist_target_dir)

        setup_py_snapshot_version_argv = self._generate_snapshot_bdist_wheel_argv(
            snapshot_fingerprint, is_platform_specific
        )

        cmd = safe_shlex_join(setup_py_runner.cmdline(setup_py_snapshot_version_argv))
        with self.context.new_workunit(
            "setup.py", cmd=cmd, labels=[WorkUnitLabel.TOOL]
        ) as workunit:
            try:
                setup_py_runner.run_setup_command(
                    source_dir=Path(dist_target_dir),
                    setup_command=setup_py_snapshot_version_argv,
                    stdout=workunit.output("stdout"),
                    stderr=workunit.output("stderr"),
                )
            except SetupPyRunner.CommandFailure as e:
                raise self.BuildLocalPythonDistributionsError(
                    f"Installation of python distribution from target {dist_tgt} into directory "
                    f"{dist_target_dir} failed using the host system's compiler and linker: {e}"
                )

    # TODO: convert this into a SimpleCodegenTask, which does the exact same thing as this method!
    def _inject_synthetic_dist_requirements(self, dist, req_lib_addr):
        """Inject a synthetic requirements library that references a local wheel.

        :param dist: Path of the locally built wheel to reference.
        :param req_lib_addr:  :class: `Address` to give to the synthetic target.
        :return: a :class: `PythonRequirementLibrary` referencing the locally-built wheel.
        """
        whl_dir, base = split_basename_and_dirname(dist)
        whl_metadata = base.split("-")
        req_name = "==".join([whl_metadata[0], whl_metadata[1]])
        req = PythonRequirement(req_name, repository=whl_dir)
        self.context.build_graph.inject_synthetic_target(
            req_lib_addr, PythonRequirementLibrary, requirements=[req]
        )

    @classmethod
    def _get_whl_from_dir(cls, install_dir):
        """Return the absolute path of the whl in a setup.py install directory."""
        dist_dir = cls._get_dist_dir(install_dir)
        dists = glob.glob(os.path.join(dist_dir, "*.whl"))
        if len(dists) == 0:
            raise cls.BuildLocalPythonDistributionsError(
                "No distributions were produced by python_create_distribution task.\n"
                "dist_dir: {}, install_dir: {}".format(dist_dir, install_dir)
            )
        if len(dists) > 1:
            # TODO: is this ever going to happen?
            raise cls.BuildLocalPythonDistributionsError(
                "Ambiguous local python distributions found: {}".format(dists)
            )
        return dists[0]
