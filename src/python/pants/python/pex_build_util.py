# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.platforms import Platform
from pex.resolver import resolve
from pex.util import DistributionHelper
from pex.version import __version__ as pex_version
from pkg_resources import Distribution, get_provider

from pants.backend.python.subsystems.ipex import ipex_launcher
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.files import Files
from pants.build_graph.target import Target
from pants.option.custom_types import UnsetBool
from pants.python.python_repos import PythonRepos
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_file
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import module_dirname


def is_python_target(tgt: Target) -> bool:
    # We'd like to take all PythonTarget subclasses, but currently PythonThriftLibrary and
    # PythonAntlrLibrary extend PythonTarget, and until we fix that (which we can't do until
    # we remove the old python pipeline entirely) we want to ignore those target types here.
    return isinstance(tgt, (PythonLibrary, PythonTests, PythonBinary))


def has_python_sources(tgt: Target) -> bool:
    return is_python_target(tgt) and tgt.has_sources()


def is_local_python_dist(tgt: Target) -> bool:
    return isinstance(tgt, PythonDistribution)


def has_resources(tgt: Target) -> bool:
    return isinstance(tgt, Files) and tgt.has_sources()


def has_python_requirements(tgt: Target) -> bool:
    return isinstance(tgt, PythonRequirementLibrary)


def always_uses_default_python_platform(tgt: Target) -> bool:
    return isinstance(tgt, PythonTests)


def may_have_explicit_python_platform(tgt: Target) -> bool:
    return isinstance(tgt, PythonBinary)


def targets_by_platform(targets, python_setup):
    targets_requiring_default_platforms = []
    explicit_platform_settings = defaultdict(OrderedSet)
    for target in targets:
        if always_uses_default_python_platform(target):
            targets_requiring_default_platforms.append(target)
        elif may_have_explicit_python_platform(target):
            for platform in target.platforms if target.platforms else python_setup.platforms:
                explicit_platform_settings[platform].add(target)
    # There are currently no tests for this because they're super platform specific and it's hard for
    # us to express that on CI, but https://github.com/pantsbuild/pants/issues/7616 has an excellent
    # repro case for why this is necessary.
    for target in targets_requiring_default_platforms:
        for platform in python_setup.platforms:
            explicit_platform_settings[platform].add(target)
    return dict(explicit_platform_settings)


def identify_missing_init_files(sources: Sequence[str]) -> Set[str]:
    """Return the list of paths that would need to be added to ensure that every package has an
    __init__.py."""
    packages: Set[str] = set()
    for source in sources:
        if source.endswith(".py"):
            pkg_dir = os.path.dirname(source)
            if pkg_dir and pkg_dir not in packages:
                package = ""
                for component in pkg_dir.split(os.sep):
                    package = os.path.join(package, component)
                    packages.add(package)

    return {os.path.join(package, "__init__.py") for package in packages} - set(sources)


class PexBuilderWrapper:
    """Wraps PEXBuilder to provide an API that consumes targets and other BUILD file entities."""

    class Factory(Subsystem):
        options_scope = "pex-builder-wrapper"

        @classmethod
        def register_options(cls, register):
            super(PexBuilderWrapper.Factory, cls).register_options(register)
            # TODO: make an analogy to cls.register_jvm_tool that can be overridden for python subsystems
            # by a python_requirement_library() target, not just via pants.ini!
            register(
                "--setuptools-version",
                advanced=True,
                default="40.6.3",
                fingerprint=True,
                help="The setuptools version to include in the pex if namespace packages need "
                "to be injected.",
            )
            register(
                "--pex-version",
                advanced=True,
                default=pex_version,
                fingerprint=True,
                help="The pex version to include in any generated ipex files. "
                "NOTE: This should ideally be the same as the pex version which pants "
                f"itself depends on, which right now is {pex_version}.",
            )

        @classmethod
        def subsystem_dependencies(cls):
            return super(PexBuilderWrapper.Factory, cls).subsystem_dependencies() + (
                PythonRepos,
                PythonSetup,
            )

        @classmethod
        def create(cls, builder, log=None, generate_ipex=False):
            options = cls.global_instance().get_options()
            setuptools_requirement = f"setuptools=={options.setuptools_version}"
            pex_requirement = f"pex=={options.pex_version}"

            log = log or logging.getLogger(__name__)

            return PexBuilderWrapper(
                builder=builder,
                python_repos_subsystem=PythonRepos.global_instance(),
                python_setup_subsystem=PythonSetup.global_instance(),
                setuptools_requirement=PythonRequirement(setuptools_requirement),
                pex_requirement=PythonRequirement(pex_requirement),
                log=log,
                generate_ipex=generate_ipex,
            )

    def __init__(
        self,
        builder: PEXBuilder,
        python_repos_subsystem: PythonRepos,
        python_setup_subsystem: PythonSetup,
        setuptools_requirement: PythonRequirement,
        pex_requirement: PythonRequirement,
        log,
        generate_ipex: bool = False,
    ):
        assert log is not None

        self._builder = builder
        self._python_repos_subsystem = python_repos_subsystem
        self._python_setup_subsystem = python_setup_subsystem
        self._setuptools_requirement = setuptools_requirement
        self._pex_requirement = pex_requirement
        self._log = log

        self._distributions: Dict[str, Distribution] = {}
        self._frozen = False

        self._generate_ipex = generate_ipex
        # If we generate a .ipex, we need to ensure all the code we copy into the underlying PEXBuilder
        # is also added to the new PEXBuilder created in `._shuffle_original_build_info_into_ipex()`.
        self._all_added_sources_resources: List[Path] = []
        # If we generate a dehydrated "ipex" file, we need to make sure that it is aware of any special
        # find_links repos attached to any single requirement, so it can later resolve those
        # requirements when it is first bootstrapped, using the same resolve options.
        self._all_find_links: OrderedSet[str] = OrderedSet()

    def add_requirement_libs_from(self, req_libs, platforms=None):
        """Multi-platform dependency resolution for PEX files.

        :param builder: Dump the requirements into this builder.
        :param interpreter: The :class:`PythonInterpreter` to resolve requirements for.
        :param req_libs: A list of :class:`PythonRequirementLibrary` targets to resolve.
        :param log: Use this logger.
        :param platforms: A list of :class:`Platform`s to resolve requirements for.
                                            Defaults to the platforms specified by PythonSetup.
        """
        reqs = [req for req_lib in req_libs for req in req_lib.requirements]
        self.add_resolved_requirements(reqs, platforms=platforms)

    class SingleDistExtractionError(Exception):
        pass

    def extract_single_dist_for_current_platform(self, reqs, dist_key) -> Distribution:
        """Resolve a specific distribution from a set of requirements matching the current platform.

        :param list reqs: A list of :class:`PythonRequirement` to resolve.
        :param str dist_key: The value of `distribution.key` to match for a `distribution` from the
                                                 resolved requirements.
        :return: The single :class:`pkg_resources.Distribution` matching `dist_key`.
        :raises: :class:`self.SingleDistExtractionError` if no dists or multiple dists matched the
                 given `dist_key`.
        """
        distributions = self.resolve_distributions(reqs, platforms=["current"])
        try:
            matched_dist = assert_single_element(
                dist for dists in distributions.values() for dist in dists if dist.key == dist_key
            )
        except (StopIteration, ValueError) as e:
            raise self.SingleDistExtractionError(
                f"Exactly one dist was expected to match name {dist_key} in requirements {reqs}: {e!r}"
            )
        return matched_dist

    def resolve_distributions(
        self, reqs: List[PythonRequirement], platforms: Optional[List[Platform]] = None,
    ) -> Dict[str, List[Distribution]]:
        """Multi-platform dependency resolution.

        :param reqs: A list of :class:`PythonRequirement` to resolve.
        :param platforms: A list of platform strings to resolve requirements for.
                          Defaults to the platforms specified by PythonSetup.
        :returns: A tuple `(map, transitive_reqs)`, where `map` is a dict mapping distribution name
                  to a list of resolved distributions, and `reqs` contains all transitive ==
                  requirements
                  needed to resolve the initial given requirements `reqs` for the given platforms.
        """
        deduped_reqs = OrderedSet(reqs)
        find_links: OrderedSet[str] = OrderedSet()
        for req in deduped_reqs:
            self._log.debug(f"  Dumping requirement: {req}")
            self._builder.add_requirement(str(req.requirement))
            if req.repository:
                find_links.add(req.repository)

        # Resolve the requirements into distributions.
        distributions = self._resolve_multi(
            self._builder.interpreter, list(deduped_reqs), platforms, list(find_links),
        )
        return distributions

    def add_resolved_requirements(
        self,
        reqs: List[PythonRequirement],
        platforms: Optional[List[Platform]] = None,
        override_ipex_build_do_actually_add_distribution: bool = False,
    ) -> None:
        """Multi-platform dependency resolution for PEX files.

        :param builder: Dump the requirements into this builder.
        :param interpreter: The :class:`PythonInterpreter` to resolve requirements for.
        :param reqs: A list of :class:`PythonRequirement` to resolve.
        :param log: Use this logger.
        :param platforms: A list of :class:`Platform`s to resolve requirements for.
                                            Defaults to the platforms specified by PythonSetup.
        :param bool override_ipex_build_do_actually_add_distribution: When this PexBuilderWrapper is configured with
                                                                        generate_ipex=True, this method won't add any distributions to
                                                                        the output pex. The internal implementation of this class adds a
                                                                        pex dependency to the output ipex file, and therefore needs to
                                                                        override the default behavior of this method.
        """
        distributions = self.resolve_distributions(reqs, platforms=platforms)
        locations: Set[str] = set()
        for platform, dists in distributions.items():
            for dist in dists:
                if dist.location not in locations:
                    if self._generate_ipex and not override_ipex_build_do_actually_add_distribution:
                        self._log.debug(
                            f"  *AVOIDING* dumping distribution into ipex: .../{os.path.basename(dist.location)}"
                        )
                        self._register_distribution(dist)
                    else:
                        self._log.debug(
                            f"  Dumping distribution: .../{os.path.basename(dist.location)}"
                        )
                        self.add_distribution(dist)
                locations.add(dist.location)

    def _resolve_multi(
        self,
        interpreter: PythonInterpreter,
        requirements: List[PythonRequirement],
        platforms: Optional[List[Platform]],
        find_links: Optional[List[str]],
    ) -> Dict[str, List[Distribution]]:
        """Multi-platform dependency resolution for PEX files.

        Returns a tuple containing a list of distributions that must be included in order to satisfy a
        set of requirements, and the transitive == requirements for thosee distributions. This may
        involve distributions for multiple platforms.

        :param interpreter: The :class:`PythonInterpreter` to resolve for.
        :param requirements: A list of :class:`PythonRequirement` objects to resolve.
        :param platforms: A list of :class:`Platform`s to resolve for.
        :param find_links: Additional paths to search for source packages during resolution.
        :return: Map of platform name -> list of :class:`pkg_resources.Distribution` instances needed
                         to satisfy the requirements on that platform.
        """
        python_setup = self._python_setup_subsystem
        python_repos = self._python_repos_subsystem
        platforms = platforms or python_setup.platforms

        find_links = list(find_links) if find_links else []
        find_links.extend(python_repos.repos)

        # Individual requirements from pants may have a `repository` link attached to them, which is
        # extracted in `self.resolve_distributions()`. When generating a .ipex file with
        # `generate_ipex=True`, we want to ensure these repos are known to the ipex launcher when it
        # tries to resolve all the requirements from BOOTSTRAP-PEX-INFO.
        self._all_find_links.update(OrderedSet(find_links))

        distributions: Dict[str, List[Distribution]] = defaultdict(list)

        for platform in platforms:
            requirements_cache_dir = os.path.join(
                python_setup.resolver_cache_dir, str(interpreter.identity)
            )
            resolved_dists = resolve(
                requirements=[str(req.requirement) for req in requirements],
                interpreter=interpreter,
                platform=platform,
                indexes=python_repos.indexes,
                find_links=find_links,
                cache=requirements_cache_dir,
                allow_prereleases=python_setup.resolver_allow_prereleases,
                manylinux=python_setup.manylinux,
            )
            for resolved_dist in resolved_dists:
                distributions[platform].append(resolved_dist.distribution)

        return distributions

    def _create_source_dumper(self, tgt: Target) -> Callable[[str], None]:
        buildroot = get_buildroot()

        def get_chroot_path(relpath: str) -> str:
            if type(tgt) == Files:
                # Loose `Files`, as opposed to `Resources` or `PythonTarget`s, have no (implied) package
                # structure and so we chroot them relative to the build root so that they can be accessed
                # via the normal Python filesystem APIs just as they would be accessed outside the
                # chrooted environment. NB: This requires we mark the pex as not zip safe so
                # these `Files` can still be accessed in the context of a built pex distribution.
                self._builder.info.zip_safe = False
                return relpath
            return str(Path(relpath).relative_to(tgt.target_base))

        def dump_source(relpath: str) -> None:
            source_path = str(Path(buildroot, relpath))
            dest_path = get_chroot_path(relpath)

            self._all_added_sources_resources.append(Path(dest_path))
            if has_resources(tgt):
                self._builder.add_resource(filename=source_path, env_filename=dest_path)
            else:
                self._builder.add_source(filename=source_path, env_filename=dest_path)

        return dump_source

    def add_sources_from(self, tgt: Target) -> None:
        dump_source = self._create_source_dumper(tgt)
        self._log.debug(f"  Dumping sources: {tgt}")
        for relpath in tgt.sources_relative_to_buildroot():
            try:
                dump_source(relpath)
            except OSError:
                self._log.error(f"Failed to copy {relpath} for target {tgt.address.spec}")
                raise

        if getattr(tgt, "_resource_target_specs", None) or getattr(
            tgt, "_synthetic_resources_target", None
        ):
            # No one should be on old-style resources any more.  And if they are,
            # switching to the new python pipeline will be a great opportunity to fix that.
            raise TaskError(
                f"Old-style resources not supported for target {tgt.address.spec}. Depend on resources() "
                "targets instead."
            )

    def _prepare_inits(self) -> Set[str]:
        chroot = self._builder.chroot()
        sources = chroot.get("source") | chroot.get("resource")
        missing_init_files = identify_missing_init_files(sources)
        if missing_init_files:
            with temporary_file(permissions=0o644) as ns_package:
                ns_package.write(
                    b'__import__("pkg_resources").declare_namespace(__name__)  # type: ignore[attr-defined]'
                )
                ns_package.flush()
                for missing_init_file in missing_init_files:
                    self._all_added_sources_resources.append(Path(missing_init_file))
                    self._builder.add_source(
                        filename=ns_package.name, env_filename=missing_init_file
                    )
        return missing_init_files

    def set_emit_warnings(self, emit_warnings):
        self._builder.info.emit_warnings = emit_warnings

    def _set_major_minor_interpreter_constraint_for_ipex(
        self, info: PexInfo, identity: PythonIdentity,
    ) -> PexInfo:
        interpreter_name = identity.requirement.name
        major, minor, _patch = identity.version
        major_minor_only_constraint = f"{interpreter_name}=={major}.{minor}.*"
        return ipex_launcher.modify_pex_info(
            info, interpreter_constraints=[str(major_minor_only_constraint)]
        )

    def _shuffle_underlying_pex_builder(self) -> Tuple[PexInfo, Path]:
        """Replace the original builder with a new one, and just pull files from the old chroot."""
        # Ensure that (the interpreter selected to resolve requirements when the ipex is first run) is
        # (the exact same interpreter we used to resolve those requirements here). This is the only (?)
        # way to ensure that the ipex bootstrap uses the *exact* same interpreter version.
        self._builder.info = self._set_major_minor_interpreter_constraint_for_ipex(
            self._builder.info, self._builder.interpreter.identity
        )

        # Remove all the original top-level requirements in favor of the transitive == requirements.
        self._builder.info = ipex_launcher.modify_pex_info(self._builder.info, requirements=[])
        transitive_reqs = [dist.as_requirement() for dist in self._distributions.values()]
        self.add_direct_requirements(transitive_reqs)

        orig_info = self._builder.info.copy()

        orig_chroot = self._builder.chroot()

        # Mutate the PexBuilder object which is manipulated by this subsystem.
        self._builder = PEXBuilder(interpreter=self._builder.interpreter)
        self._builder.info = self._set_major_minor_interpreter_constraint_for_ipex(
            self._builder.info, self._builder.interpreter.identity
        )

        self._distributions = {}

        return (orig_info, Path(orig_chroot.path()))

    def _shuffle_original_build_info_into_ipex(self):
        """Create a "dehydrated" ipex file without any of its requirements, and specify that in two.

        *-INFO files.

        See ipex_launcher.py for details of how these files are used.
        """
        orig_pex_info, orig_chroot = self._shuffle_underlying_pex_builder()

        # Gather information needed to create IPEX-INFO.
        all_code = [str(src) for src in self._all_added_sources_resources]
        prefixed_code_paths = [os.path.join(ipex_launcher.APP_CODE_PREFIX, src) for src in all_code]
        for src, prefixed in zip(all_code, prefixed_code_paths):
            # NB: Need to add under 'source' label for `self._prepare_inits()` to pick it up!
            self._builder.chroot().copy(
                os.path.join(str(orig_chroot), src), prefixed, label="source"
            )

        python_repos = self._python_repos_subsystem
        python_setup = self._python_setup_subsystem

        # NB: self._all_find_links is updated on every call to self._resolve_multi(), and therefore
        # includes all of the links from python_repos.repos, as well as any links added within any
        # individual requirements from that resolve.

        resolver_settings = dict(
            indexes=list(python_repos.indexes),
            find_links=list(self._all_find_links),
            allow_prereleases=UnsetBool.coerce_bool(
                python_setup.resolver_allow_prereleases, default=True
            ),
            manylinux=python_setup.manylinux,
        )

        # IPEX-INFO: A json mapping interpreted in ipex_launcher.py:
        # {
        #   "code": [<which source files to add to the "hydrated" pex when bootstrapped>],
        #   "resolver_settings": {<which indices to search for requirements from when bootstrapping>},
        # }
        ipex_info = dict(code=prefixed_code_paths, resolver_settings=resolver_settings,)
        with temporary_file(permissions=0o644) as ipex_info_file:
            ipex_info_file.write(json.dumps(ipex_info).encode())
            ipex_info_file.flush()
            self._builder.add_resource(filename=ipex_info_file.name, env_filename="IPEX-INFO")

        # BOOTSTRAP-PEX-INFO: The original PEX-INFO, which should be the PEX-INFO in the hydrated .pex
        #                     file that is generated when the .ipex is first executed.
        with temporary_file(permissions=0o644) as bootstrap_pex_info_file:
            bootstrap_pex_info_file.write(orig_pex_info.dump().encode())
            bootstrap_pex_info_file.flush()
            self._builder.add_resource(
                filename=bootstrap_pex_info_file.name, env_filename="BOOTSTRAP-PEX-INFO"
            )

        # ipex.py: The special bootstrap script to hydrate the .ipex with the fully resolved
        #          requirements when it is first executed.
        # Extract the file contents of our custom app launcher script from the pants package.
        parent_module = module_dirname(module_dirname(ipex_launcher.__name__))
        ipex_launcher_provider = get_provider(parent_module)
        ipex_launcher_script = ipex_launcher_provider.get_resource_string(
            parent_module, "ipex/ipex_launcher.py"
        )
        with temporary_file(permissions=0o644) as ipex_launcher_file:
            ipex_launcher_file.write(ipex_launcher_script)
            ipex_launcher_file.flush()
            # Our .ipex file will use our custom app launcher!
            self._builder.set_executable(ipex_launcher_file.name, env_filename="ipex.py")

        # The PEX-INFO we generate shouldn't have any requirements (except pex itself), or they will
        # fail to bootstrap because they were unable to find those distributions. Instead, the .pex file
        # produced when the .ipex is first executed will read and resolve all those requirements from
        # the BOOTSTRAP-PEX-INFO.
        self.add_resolved_requirements(
            [self._pex_requirement, self._setuptools_requirement],
            override_ipex_build_do_actually_add_distribution=True,
        )

    def freeze(self) -> None:
        if self._frozen:
            return

        if self._prepare_inits():
            dist = self._distributions.get("setuptools")
            if not dist:
                self.add_resolved_requirements([self._setuptools_requirement])

        if self._generate_ipex:
            self._shuffle_original_build_info_into_ipex()

        self._builder.freeze(bytecode_compile=False)
        self._frozen = True

    def set_entry_point(self, entry_point):
        self._builder.set_entry_point(entry_point)

    def build(self, safe_path):
        self.freeze()
        self._builder.build(safe_path, bytecode_compile=False, deterministic_timestamp=True)

    def set_shebang(self, shebang):
        self._builder.set_shebang(shebang)

    def add_interpreter_constraint(self, constraint):
        self._builder.add_interpreter_constraint(constraint)

    def add_interpreter_constraints_from(self, constraint_tgts):
        # TODO this would be a great place to validate the constraints and present a good error message
        # if they are incompatible because all the sources of the constraints are available.
        # See: https://github.com/pantsbuild/pex/blob/584b6e367939d24bc28aa9fa36eb911c8297dac8/pex/interpreter_constraints.py
        constraint_tuples = {
            self._python_setup_subsystem.compatibility_or_constraints(tgt.compatibility)
            for tgt in constraint_tgts
        }
        for constraint_tuple in constraint_tuples:
            for constraint in constraint_tuple:
                self.add_interpreter_constraint(constraint)

    def add_direct_requirements(self, reqs):
        for req in reqs:
            self._builder.add_requirement(str(req))

    def add_distribution(self, dist):
        self._builder.add_distribution(dist)
        self._register_distribution(dist)

    def add_dist_location(self, location):
        self._builder.add_dist_location(location)
        dist = DistributionHelper.distribution_from_path(location)
        self._register_distribution(dist)

    def _register_distribution(self, dist):
        self._distributions[dist.key] = dist

    def set_script(self, script):
        self._builder.set_script(script)
