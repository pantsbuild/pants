# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from pex.resolver import resolve
from pex.util import DistributionHelper
from pex.version import __version__ as pex_version
from pkg_resources import Distribution

from pants.python.python_repos import PythonRepos
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


def identify_missing_init_files(sources: Sequence[str]) -> FrozenOrderedSet[str]:
    """Return the paths to add to ensure that every package has an __init__.py.

    NB: If the sources have not had their source roots (e.g., 'src/python') stripped, this
    function will add superfluous __init__.py files at and above the source roots, (e.g.,
    src/python/__init__.py, src/__init__.py). It is the caller's responsibility to filter these
    out if necessary. If the sources have had their source roots stripped, then this function
    will only identify missing __init__.py in actual packages.
    """
    packages: Set[str] = set()
    for source in sources:
        if not source.endswith(".py"):
            continue
        pkg_dir = os.path.dirname(source)
        if not pkg_dir or pkg_dir in packages:
            continue
        package = ""
        for component in pkg_dir.split(os.sep):
            package = os.path.join(package, component)
            packages.add(package)

    return FrozenOrderedSet(
        sorted({os.path.join(package, "__init__.py") for package in packages} - set(sources))
    )


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
        set of requirements, and the transitive == requirements for those distributions. This may
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
        return set(missing_init_files)

    def set_emit_warnings(self, emit_warnings):
        self._builder.info.emit_warnings = emit_warnings

    def freeze(self) -> None:
        if self._frozen:
            return

        if self._prepare_inits():
            dist = self._distributions.get("setuptools")
            if not dist:
                self.add_resolved_requirements([self._setuptools_requirement])

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
