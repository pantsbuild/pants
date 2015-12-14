# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os

from pex import resolver
from pex.base import requirement_is_exact
from pex.package import EggPackage, SourcePackage
from pkg_resources import working_set as global_working_set
from pkg_resources import Requirement

# TODO(John Sirois): this dependency looks strange although I think it makes sense for pants to
# ship with the python backend even if all other backends do get broken into seperate sdists.
# Consider moving PythonRepos and PythonSetup to a non-backend package, perhaps pants.runtime or
# pants.python
from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.option.global_options import GlobalOptionsRegistrar
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_open
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class PluginResolver(object):
  def __init__(self, options_bootstrapper):
    self._options_bootstrapper = options_bootstrapper

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
    for req in sorted(self._plugin_requirements):
      hasher.update(req)
    resolve_hash = hasher.hexdigest()
    resolved_plugins_list = os.path.join(self.plugin_cache_dir,
                                         'plugins-{}.txt'.format(resolve_hash))

    if not os.path.exists(resolved_plugins_list):
      tmp_plugins_list = resolved_plugins_list + '~'
      with safe_open(tmp_plugins_list, 'w') as fp:
        for plugin in self._resolve_plugins():
          fp.write(plugin.location)
          fp.write('\n')
      os.rename(tmp_plugins_list, resolved_plugins_list)
    with open(resolved_plugins_list) as fp:
      for plugin_location in fp:
        yield plugin_location.strip()

  def _resolve_plugins(self):
    # When bootstrapping plugins without the full pants python backend machinery in-play, we are not
    # guaranteed a properly initialized interpreter with wheel support so we enforce eggs only for
    # bdists with this custom precedence.
    precedence = (EggPackage, SourcePackage)

    logger.info('Resolving new plugins...:\n  {}'.format('\n  '.join(self._plugin_requirements)))
    return resolver.resolve(self._plugin_requirements,
                            fetchers=self._python_repos.get_fetchers(),
                            context=self._python_repos.get_network_context(),
                            precedence=precedence,
                            cache=self.plugin_cache_dir,
                            cache_ttl=self._python_setup.resolver_cache_ttl)

  @memoized_property
  def plugin_cache_dir(self):
    """The path of the directory pants plugins bdists are cached in."""
    return self._plugin_cache_dir

  @memoized_property
  def _python_repos(self):
    return self._create_global_subsystem(PythonRepos)

  @memoized_property
  def _python_setup(self):
    return self._create_global_subsystem(PythonSetup)

  def _create_global_subsystem(self, subsystem_type):
    options_scope = subsystem_type.options_scope
    return subsystem_type(options_scope, self._options.for_scope(options_scope))

  @memoized_property
  def _options(self):
    # NB: The PluginResolver runs very early in the pants startup sequence before the standard
    # Subsystem facility is wired up.  As a result PluginResolver is not itself a Subsystem with
    # (PythonRepos, PythonSetup) returned as `dependencies()`.  Instead it does the minimum possible
    # work to hand-roll bootstrapping of the Subsystems it needs.
    subsystems = Subsystem.closure([PythonRepos, PythonSetup])
    known_scope_infos = [subsystem.get_scope_info() for subsystem in subsystems]
    options = self._options_bootstrapper.get_full_options(known_scope_infos)

    # Ignore command line flags since we'd blow up on any we don't understand (most of them).
    # If someone wants to bootstrap plugins in a one-off custom way they'll need to use env vars
    # or a --config-override pointing to a custom pants.ini snippet.
    defaulted_only_options = options.drop_flag_values()

    GlobalOptionsRegistrar.register_options_on_scope(defaulted_only_options)
    for subsystem in subsystems:
      subsystem.register_options_on_scope(defaulted_only_options)
    return defaulted_only_options
