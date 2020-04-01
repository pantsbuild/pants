# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import cast

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.target_scopes import Scopes
from pants.python.pex_build_util import (
    PexBuilderWrapper,
    has_python_requirements,
    has_python_sources,
    has_resources,
    is_python_target,
)
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir_for
from pants.util.fileutil import atomic_copy
from pants.util.memo import memoized_property


class PythonBinaryCreate(Task):
    """Create an executable .pex file."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--include-run-information",
            type=bool,
            default=False,
            help="Include run information in the PEX's PEX-INFO for information like the timestamp the PEX was "
            "created and the command line used to create it. This information may be helpful to you, but means "
            "that the generated PEX will not be reproducible; that is, future runs of `./pants binary` will not "
            "create the same byte-for-byte identical .pex files.",
        )
        register(
            "--generate-ipex",
            type=bool,
            default=False,
            fingerprint=True,
            help='Whether to generate a .ipex file, which will "hydrate" its dependencies when '
            "it is first executed, rather than at build time (the normal pex behavior). "
            "This option can reduce the size of a shipped pex file by over 100x for common"
            "deps such as tensorflow, but it does require access to the network when "
            "first executed.",
        )
        register(
            "--output-file-extension",
            type=str,
            default=None,
            fingerprint=True,
            help="What extension to output the file with. This can be used to differentiate "
            "ipex files from others.",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            PexBuilderWrapper.Factory,
            PythonNativeCode.scoped(cls),
        )

    @memoized_property
    def _python_native_code_settings(self):
        return PythonNativeCode.scoped_instance(self)

    @classmethod
    def product_types(cls):
        return ["pex_archives", "deployable_archives"]

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("PythonBinaryCreate", 2)]

    @property
    def cache_target_dirs(self):
        return True

    @classmethod
    def prepare(cls, options, round_manager):
        # See comment below for why we don't use the GatherSources.PYTHON_SOURCES product.
        round_manager.require_data(PythonInterpreter)
        round_manager.optional_data("python")  # For codegen.
        round_manager.optional_product(PythonRequirementLibrary)  # For local dists.

    @staticmethod
    def is_binary(target):
        return isinstance(target, PythonBinary)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._distdir = self.get_options().pants_distdir

    @property
    def _generate_ipex(self) -> bool:
        return cast(bool, self.get_options().generate_ipex)

    def _get_output_pex_filename(self, target_name):
        file_ext = self.get_options().output_file_extension
        if file_ext is None:
            file_ext = ".ipex" if self._generate_ipex else ".pex"

        return f"{target_name}{file_ext}"

    def execute(self):
        binaries = self.context.targets(self.is_binary)

        # Check for duplicate binary names, since we write the pexes to <dist>/<name>.pex.
        names = {}
        for binary in binaries:
            name = binary.name
            if name in names:
                raise TaskError(
                    f"Cannot build two binaries with the same name in a single invocation. "
                    "{binary} and {names[name]} both have the name {name}."
                )
            names[name] = binary

        with self.invalidated(binaries, invalidate_dependents=True) as invalidation_check:
            python_deployable_archive = self.context.products.get("deployable_archives")
            python_pex_product = self.context.products.get("pex_archives")
            for vt in invalidation_check.all_vts:
                pex_path = os.path.join(
                    vt.results_dir, self._get_output_pex_filename(vt.target.name)
                )
                if not vt.valid:
                    self.context.log.debug(f"cache for {vt.target} is invalid, rebuilding")
                    self._create_binary(vt.target, vt.results_dir)
                else:
                    self.context.log.debug(f"using cache for {vt.target}")

                basename = os.path.basename(pex_path)
                python_pex_product.add(vt.target, os.path.dirname(pex_path)).append(basename)
                python_deployable_archive.add(vt.target, os.path.dirname(pex_path)).append(basename)
                self.context.log.debug(
                    "created {}".format(os.path.relpath(pex_path, get_buildroot()))
                )

                # Create a copy for pex.
                pex_copy = os.path.join(self._distdir, os.path.basename(pex_path))
                safe_mkdir_for(pex_copy)
                atomic_copy(pex_path, pex_copy)
                self.context.log.info(
                    "created pex {}".format(os.path.relpath(pex_copy, get_buildroot()))
                )

    def _create_binary(self, binary_tgt, results_dir):
        """Create a .pex file for the specified binary target."""
        # Note that we rebuild a chroot from scratch, instead of using the REQUIREMENTS_PEX
        # and PYTHON_SOURCES products, because those products are already-built pexes, and there's
        # no easy way to merge them into a single pex file (for example, they each have a __main__.py,
        # metadata, and so on, which the merging code would have to handle specially).
        interpreter = self.context.products.get_data(PythonInterpreter)
        with temporary_dir() as tmpdir:
            # Create the pex_info for the binary.
            build_properties = PexInfo.make_build_properties()
            if self.get_options().include_run_information:
                run_info_dict = self.context.run_tracker.run_info.get_as_dict()
                build_properties.update(run_info_dict)
            pex_info = binary_tgt.pexinfo.copy()
            pex_info.build_properties = build_properties

            pex_builder = PexBuilderWrapper.Factory.create(
                builder=PEXBuilder(
                    path=tmpdir, interpreter=interpreter, pex_info=pex_info, copy=True
                ),
                log=self.context.log,
                generate_ipex=self._generate_ipex,
            )

            if binary_tgt.shebang:
                self.context.log.info(
                    "Found Python binary target {} with customized shebang, using it: {}".format(
                        binary_tgt.name, binary_tgt.shebang
                    )
                )
                pex_builder.set_shebang(binary_tgt.shebang)
            else:
                self.context.log.debug(f"No customized shebang found for {binary_tgt.name}")

            # Find which targets provide sources and which specify requirements.
            source_tgts = []
            req_tgts = []
            constraint_tgts = []
            for tgt in binary_tgt.closure(exclude_scopes=Scopes.COMPILE):
                if has_python_sources(tgt) or has_resources(tgt):
                    source_tgts.append(tgt)
                elif has_python_requirements(tgt):
                    req_tgts.append(tgt)
                if is_python_target(tgt):
                    constraint_tgts.append(tgt)

            # Add interpreter compatibility constraints to pex info. Note that we only add the constraints for the final
            # binary target itself, not its dependencies. The upstream interpreter selection tasks will already validate that
            # there are no compatibility conflicts among the dependencies and target. If the binary target does not have
            # `compatibility` in its BUILD entry, the global --python-setup-interpreter-constraints will be used.
            pex_builder.add_interpreter_constraints_from([binary_tgt])

            # Dump everything into the builder's chroot.
            for tgt in source_tgts:
                pex_builder.add_sources_from(tgt)

            # We need to ensure that we are resolving for only the current platform if we are
            # including local python dist targets that have native extensions.
            self._python_native_code_settings.check_build_for_current_platform_only(
                self.context.targets()
            )
            pex_builder.add_requirement_libs_from(req_tgts, platforms=binary_tgt.platforms)

            # Build the .pex file.
            pex_filename = self._get_output_pex_filename(binary_tgt.name)
            pex_path = os.path.join(results_dir, pex_filename)
            pex_builder.build(pex_path)
            return pex_path
