# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import os
import site

from pex import resolver
from pex.base import requirement_is_exact
from pex.interpreter import PythonInterpreter
from pkg_resources import Requirement
from pkg_resources import working_set as global_working_set
from wheel.install import WheelFile

from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.option.global_options import GlobalOptionsRegistrar
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.memo import memoized_property
from pants.util.strutil import ensure_text
from pants.version import PANTS_SEMVER


logger = logging.getLogger(__name__)


class PluginResolver:
  @staticmethod
  def _is_wheel(path):
    return os.path.isfile(path) and path.endswith('.whl')

  @classmethod
  def _activate_wheel(cls, wheel_path):
    install_dir = '{}-install'.format(wheel_path)
    if not os.path.isdir(install_dir):
      with temporary_dir(root_dir=os.path.dirname(install_dir)) as tmp:
        cls._install_wheel(wheel_path, tmp)
        os.rename(tmp, install_dir)
    # Activate any .pth files installed above.
    site.addsitedir(install_dir)
    return install_dir

  @classmethod
  def _install_wheel(cls, wheel_path, install_dir):
    safe_mkdir(install_dir, clean=True)
    WheelFile(wheel_path).install(force=True,
                                  overrides={
                                    'purelib': install_dir,
                                    'headers': os.path.join(install_dir, 'headers'),
                                    'scripts': os.path.join(install_dir, 'bin'),
                                    'platlib': install_dir,
                                    'data': install_dir
                                  })

  def __init__(self, options_bootstrapper, *, interpreter=None):
    self._options_bootstrapper = options_bootstrapper
    self._interpreter = interpreter or PythonInterpreter.get()

    bootstrap_options = self._options_bootstrapper.get_bootstrap_options().for_global_scope()
    self._plugin_requirements = bootstrap_options.plugins
    self._plugin_cache_dir = bootstrap_options.plugin_cache_dir

  def resolve(self, working_set=None):
    """Resolves any configured plugins and adds them to the global working set.

    :param working_set: The working set to add the resolved plugins to instead of the global
                        working set (for testing).
    :type: :class:`pkg_resources.WorkingSet`
    """
    working_set = working_set or global_working_set
    if self._plugin_requirements:
      for plugin_location in self._resolve_plugin_locations():
        if self._is_wheel(plugin_location):
          plugin_location = self._activate_wheel(plugin_location)
        working_set.add_entry(plugin_location)
    return working_set

  def _resolve_plugin_locations(self):
    # We jump through some hoops here to avoid a live resolve if possible for purposes of speed.
    # Even with a local resolve cache fully up to date, running a resolve to activate a plugin
    # takes ~250ms whereas loading from a pre-cached list takes ~50ms.
    if all(requirement_is_exact(Requirement.parse(req)) for req in self._plugin_requirements):
      return self._resolve_exact_plugin_locations()
    else:
      return (plugin.location for plugin in self._resolve_plugins())

  def _resolve_exact_plugin_locations(self):
    hasher = hashlib.sha1()

    # Assume we have platform-specific plugin requirements and pessimistically mix the ABI
    # identifier into the hash to ensure re-resolution of plugins for different interpreter ABIs.
    hasher.update(self._interpreter.identity.abi_tag.encode())  # EG: cp36m

    for req in sorted(self._plugin_requirements):
      hasher.update(req.encode())
    resolve_hash = hasher.hexdigest()
    resolved_plugins_list = os.path.join(self.plugin_cache_dir, f'plugins-{resolve_hash}.txt')

    if not os.path.exists(resolved_plugins_list):
      tmp_plugins_list = resolved_plugins_list + '~'
      with safe_open(tmp_plugins_list, 'w') as fp:
        for plugin in self._resolve_plugins():
          fp.write(ensure_text(plugin.location))
          fp.write('\n')
      os.rename(tmp_plugins_list, resolved_plugins_list)
    with open(resolved_plugins_list, 'r') as fp:
      for plugin_location in fp:
        yield plugin_location.strip()

  def _resolve_plugins(self):
    logger.info('Resolving new plugins...:\n  {}'.format('\n  '.join(self._plugin_requirements)))
    resolved_dists = resolver.resolve(self._plugin_requirements,
                                      fetchers=self._python_repos.get_fetchers(),
                                      interpreter=self._interpreter,
                                      context=self._python_repos.get_network_context(),
                                      cache=self.plugin_cache_dir,
                                      # Effectively never expire.
                                      cache_ttl=10 * 365 * 24 * 60 * 60,
                                      allow_prereleases=PANTS_SEMVER.is_prerelease,
                                      # Plugins will all depend on `pantsbuild.pants` which is
                                      # distributed as a manylinux wheel.
                                      use_manylinux=True)
    return [resolved_dist.distribution for resolved_dist in resolved_dists]

  @memoized_property
  def plugin_cache_dir(self):
    """The path of the directory pants plugins bdists are cached in."""
    return self._plugin_cache_dir

  @memoized_property
  def _python_repos(self):
    return self._create_global_subsystem(PythonRepos)

  def _create_global_subsystem(self, subsystem_type):
    options_scope = subsystem_type.options_scope

    # NB: The PluginResolver runs very early in the pants startup sequence before the standard
    # Subsystem facility is wired up.  As a result PluginResolver is not itself a Subsystem with
    # PythonRepos as a dependency.  Instead it does the minimum possible work to hand-roll
    # bootstrapping of the Subsystems it needs.
    known_scope_infos = [ksi
                         for optionable in [GlobalOptionsRegistrar, PythonRepos]
                         for ksi in optionable.known_scope_infos()]
    options = self._options_bootstrapper.get_full_options(known_scope_infos)

    # Ignore command line flags since we'd blow up on any we don't understand (most of them).
    # If someone wants to bootstrap plugins in a one-off custom way they'll need to use env vars
    # or a --pants-config-files pointing to a custom pants.ini snippet.
    defaulted_only_options = options.drop_flag_values()

    # Finally, construct the Subsystem.
    return subsystem_type(options_scope, defaulted_only_options.for_scope(options_scope))
