# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Sequence, Set, Tuple, cast

from pex.fetcher import Fetcher, PyPIFetcher
from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from pex.resolver import resolve
from pex.util import DistributionHelper
from pkg_resources import Distribution, Requirement
from twitter.common.collections import OrderedSet

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.base.exceptions import TaskError
from pants.base.hash_utils import stable_json_sha1
from pants.build_graph.files import Files
from pants.build_graph.target import Target
from pants.subsystem.subsystem import Subsystem
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_open
from pants.util.memo import memoized_method


@dataclass(frozen=True)
class PexResolveRequest:
  interpreter: PythonInterpreter
  requirements: Tuple[Requirement, ...]
  indexes: Tuple[str, ...]
  find_links: Tuple[str, ...]
  allow_prereleases: bool
  cache_ttl: int
  use_manylinux: bool
  platforms: Tuple[str, ...]

  @memoized_method
  def fetchers(self):
    return [
      *[PyPIFetcher(url) for url in self.indexes],
      *[Fetcher([url]) for url in self.find_links],
    ]

  @memoized_method
  def as_cache_key(self) -> str:
    return stable_json_sha1((
      str(self.interpreter.identity),
      self.requirements,
      self.indexes,
      self.find_links,
      self.allow_prereleases,
      self.cache_ttl,
      self.use_manylinux,
      self.platforms,
    ))


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
  """Return the list of paths that would need to be added to ensure that every package has
  an __init__.py. """
  packages: Set[str] = set()
  for source in sources:
    if source.endswith('.py'):
      pkg_dir = os.path.dirname(source)
      if pkg_dir and pkg_dir not in packages:
        package = ''
        for component in pkg_dir.split(os.sep):
          package = os.path.join(package, component)
          packages.add(package)

  return {os.path.join(package, '__init__.py') for package in packages} - set(sources)


def _create_source_dumper(builder: PEXBuilder, tgt: Target) -> Callable[[str], None]:
  buildroot = get_buildroot()

  def get_chroot_path(relpath: str) -> str:
    if type(tgt) == Files:
      # Loose `Files`, as opposed to `Resources` or `PythonTarget`s, have no (implied) package
      # structure and so we chroot them relative to the build root so that they can be accessed
      # via the normal Python filesystem APIs just as they would be accessed outside the
      # chrooted environment. NB: This requires we mark the pex as not zip safe so
      # these `Files` can still be accessed in the context of a built pex distribution.
      builder.info.zip_safe = False
      return relpath
    return str(Path(relpath).relative_to(tgt.target_base))

  def dump_source(relpath: str) -> None:
    source_path = str(Path(buildroot, relpath))
    dest_path = get_chroot_path(relpath)
    if has_resources(tgt):
      builder.add_resource(filename=source_path, env_filename=dest_path)
    else:
      builder.add_source(filename=source_path, env_filename=dest_path)

  return dump_source


class PexBuilderWrapper:
  """Wraps PEXBuilder to provide an API that consumes targets and other BUILD file entities."""

  class Factory(Subsystem):
    options_scope = 'pex-builder-wrapper'

    @classmethod
    def register_options(cls, register):
      super(PexBuilderWrapper.Factory, cls).register_options(register)
      register('--setuptools-version', advanced=True, default='40.6.3',
               help='The setuptools version to include in the pex if namespace packages need to be '
                    'injected.')
      register('--cache-monolithic-resolve', type=bool, advanced=True, fingerprint=True,
               help='Whether to use a shared cache for the result of a pex resolve. This avoids '
                    're-running a pex resolve on the local machine, if the inputs are the same.')
      register('--monolithic-resolve-cache-dir', advanced=True,
               default=os.path.join(get_pants_cachedir(), 'monolithic-pex-resolves'),
               help='Cache json files representing the result of a pex resolve here when '
                    '--cache-monolithic-resolve is on.')

    @classmethod
    def subsystem_dependencies(cls):
      return super(PexBuilderWrapper.Factory, cls).subsystem_dependencies() + (
        PythonRepos,
        PythonSetup,
      )

    @classmethod
    def create(cls, builder, log=None):
      options = cls.global_instance().get_options()
      setuptools_requirement = f'setuptools=={options.setuptools_version}'

      log = log or logging.getLogger(__name__)

      return PexBuilderWrapper(builder=builder,
                               python_repos_subsystem=PythonRepos.global_instance(),
                               python_setup_subsystem=PythonSetup.global_instance(),
                               setuptools_requirement=PythonRequirement(setuptools_requirement),
                               log=log,
                               monolithic_resolve_cache_dir=Path(options.monolithic_resolve_cache_dir),
                               cache_monolithic_resolve=cast(bool, options.cache_monolithic_resolve))

  def __init__(self,
               builder,
               python_repos_subsystem,
               python_setup_subsystem,
               setuptools_requirement,
               log,
               monolithic_resolve_cache_dir: Path,
               cache_monolithic_resolve: bool = False):
    assert isinstance(builder, PEXBuilder)
    assert isinstance(python_repos_subsystem, PythonRepos)
    assert isinstance(python_setup_subsystem, PythonSetup)
    assert isinstance(setuptools_requirement, PythonRequirement)
    assert log is not None

    self._builder = builder
    self._python_repos_subsystem = python_repos_subsystem
    self._python_setup_subsystem = python_setup_subsystem
    self._setuptools_requirement = setuptools_requirement
    self._log = log

    self._distributions: Dict[str, Distribution] = {}
    self._frozen = False

    self._monolithic_resolve_cache_dir = monolithic_resolve_cache_dir
    self._cache_monolithic_resolve = cache_monolithic_resolve

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

  class SingleDistExtractionError(Exception): pass

  def extract_single_dist_for_current_platform(self, reqs, dist_key):
    """Resolve a specific distribution from a set of requirements matching the current platform.

    :param list reqs: A list of :class:`PythonRequirement` to resolve.
    :param str dist_key: The value of `distribution.key` to match for a `distribution` from the
                         resolved requirements.
    :return: The single :class:`pkg_resources.Distribution` matching `dist_key`.
    :raises: :class:`self.SingleDistExtractionError` if no dists or multiple dists matched the given
             `dist_key`.
    """
    distributions = self._resolve_distributions_by_platform(reqs, platforms=['current'])
    try:
      matched_dist = assert_single_element(list(
        dist
        for _, dists in distributions.items()
        for dist in dists
        if dist.key == dist_key
      ))
    except (StopIteration, ValueError) as e:
      raise self.SingleDistExtractionError(
        f"Exactly one dist was expected to match name {dist_key} in requirements {reqs}: {e!r}"
      )
    return matched_dist

  def _resolve_distributions_by_platform(self, reqs, platforms):
    deduped_reqs = OrderedSet(reqs)
    find_links = OrderedSet()
    for req in deduped_reqs:
      self._log.debug(f'  Dumping requirement: {req}')
      self._builder.add_requirement(str(req.requirement))
      if req.repository:
        find_links.add(req.repository)

    # Resolve the requirements into distributions.
    distributions = self._resolve_multi(self._builder.interpreter, deduped_reqs, platforms,
      find_links)
    return distributions

  def add_resolved_requirements(self, reqs, platforms=None):
    """Multi-platform dependency resolution for PEX files.

    :param builder: Dump the requirements into this builder.
    :param interpreter: The :class:`PythonInterpreter` to resolve requirements for.
    :param reqs: A list of :class:`PythonRequirement` to resolve.
    :param log: Use this logger.
    :param platforms: A list of :class:`Platform`s to resolve requirements for.
                      Defaults to the platforms specified by PythonSetup.
    """
    distributions = self._resolve_distributions_by_platform(reqs, platforms=platforms)
    locations = set()
    for platform, dists in distributions.items():
      for dist in dists:
        if dist.location not in locations:
          self._log.debug(f'  Dumping distribution: .../{os.path.basename(dist.location)}')
          self.add_distribution(dist)
        locations.add(dist.location)

  @staticmethod
  def _coerce_current_platform_string(platform: str) -> str:
    return cast(str, Platform.current().platform) if platform == 'current' else platform

  def _maybe_read_cached_resolve(self, cached_resolve_json_file):
    if self._cache_monolithic_resolve and os.path.isfile(cached_resolve_json_file):
      self._log.debug(f'found monolithic resolve at {cached_resolve_json_file}')
      with open(cached_resolve_json_file) as fp:
        json_payload = json.load(fp)
        distributions = {
          plat: [
            Distribution(**init_args)
            for init_args in dists
          ]
          for plat, dists in json_payload.items()
        }
        return distributions
    return None

  def _maybe_write_cached_resolve(self, cached_resolve_json_file, distributions):
    if self._cache_monolithic_resolve:
      with safe_open(cached_resolve_json_file, 'w') as fp:
        json_payload = {
          self._coerce_current_platform_string(plat): [
            dict(location=dist.location,
                 project_name=dist.project_name,
                 version=dist.version,
                 py_version=dist.py_version)
            for dist in dists
          ]
          for plat, dists in distributions.items()
        }
        json.dump(json_payload, fp, indent=4)

  def _maybe_cached_resolve(self, pex_resolve_options, resolver_cache_dir, network_context):
    cached_resolve_json_file = os.path.join(
      str(self._monolithic_resolve_cache_dir),
      pex_resolve_options.as_cache_key(),
      'resolve-cache.json')

    cached_resolve = self._maybe_read_cached_resolve(cached_resolve_json_file)
    if cached_resolve:
      return cached_resolve

    requirements_cache_dir = os.path.join(resolver_cache_dir,
                                          str(pex_resolve_options.interpreter.identity))

    distributions = {}
    for platform in pex_resolve_options.platforms:
      resolved_dists = resolve(
        requirements=pex_resolve_options.requirements,
        interpreter=pex_resolve_options.interpreter,
        fetchers=pex_resolve_options.fetchers(),
        platform=platform,
        context=network_context,
        cache=requirements_cache_dir,
        cache_ttl=pex_resolve_options.cache_ttl,
        allow_prereleases=pex_resolve_options.allow_prereleases,
        use_manylinux=pex_resolve_options.use_manylinux,
      )
      distributions[platform] = [resolved_dist.distribution for resolved_dist in resolved_dists]

    self._maybe_write_cached_resolve(cached_resolve_json_file, distributions)

    return distributions

  def _resolve_multi(self, interpreter, requirements, platforms, find_links):
    """Multi-platform dependency resolution for PEX files.

    Returns a list of distributions that must be included in order to satisfy a set of requirements.
    That may involve distributions for multiple platforms.

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
    find_links = find_links or []

    pex_resolve_options = PexResolveRequest(
      requirements=[str(req.requirement) for req in requirements],
      interpreter=interpreter,
      indexes=python_repos.indexes,
      find_links=find_links,
      allow_prereleases=bool(python_setup.resolver_allow_prereleases),
      cache_ttl=python_setup.resolver_cache_ttl,
      use_manylinux=python_setup.use_manylinux,
      platforms=[self._coerce_current_platform_string(plat) for plat in platforms],
    )

    return self._maybe_cached_resolve(pex_resolve_options,
                                      resolver_cache_dir=python_setup.resolver_cache_dir,
                                      network_context=python_repos.get_network_context())

  def add_sources_from(self, tgt: Target) -> None:
    dump_source = _create_source_dumper(self._builder, tgt)
    self._log.debug(f'  Dumping sources: {tgt}')
    for relpath in tgt.sources_relative_to_buildroot():
      try:
        dump_source(relpath)
      except OSError:
        self._log.error(f'Failed to copy {relpath} for target {tgt.address.spec}')
        raise

    if (getattr(tgt, '_resource_target_specs', None) or
      getattr(tgt, '_synthetic_resources_target', None)):
      # No one should be on old-style resources any more.  And if they are,
      # switching to the new python pipeline will be a great opportunity to fix that.
      raise TaskError(
        f'Old-style resources not supported for target {tgt.address.spec}. Depend on resources() '
        'targets instead.'
      )

  def _prepare_inits(self) -> Set[str]:
    chroot = self._builder.chroot()
    sources = chroot.get('source') | chroot.get('resource')
    missing_init_files = identify_missing_init_files(sources)
    if missing_init_files:
      with temporary_file(permissions=0o644) as ns_package:
        ns_package.write(b'__import__("pkg_resources").declare_namespace(__name__)  # type: ignore[attr-defined]')
        ns_package.flush()
        for missing_init_file in missing_init_files:
          self._builder.add_source(filename=ns_package.name, env_filename=missing_init_file)
    return missing_init_files

  def set_emit_warnings(self, emit_warnings):
    self._builder.info.emit_warnings = emit_warnings

  def freeze(self) -> None:
    if self._frozen:
      return
    if self._prepare_inits():
      dist = self._distributions.get('setuptools')
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
