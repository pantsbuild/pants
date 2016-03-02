# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time
from contextlib import contextmanager
from textwrap import dedent

import pytest
from pex.crawler import Crawler
from pex.installer import Packager
from pex.resolver import Unsatisfiable
from pkg_resources import Requirement, WorkingSet

from pants.bin.plugin_resolver import PluginResolver
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open, safe_rmtree, touch


req = Requirement.parse


def create_plugin(distribution_repo_dir, plugin, version=None):
  with safe_open(os.path.join(distribution_repo_dir, plugin, 'setup.py'), 'w') as fp:
    fp.write(dedent("""
      from setuptools import setup


      setup(name="{plugin}", version="{version}")
    """).format(plugin=plugin, version=version or '0.0.0'))
  packager = Packager(source_dir=os.path.join(distribution_repo_dir, plugin),
                      install_dir=distribution_repo_dir)
  packager.run()


@contextmanager
def plugin_resolution(chroot=None, plugins=None):
  @contextmanager
  def provide_chroot(existing):
    if existing:
      yield existing, False
    else:
      with temporary_dir() as new_chroot:
        yield new_chroot, True

  with provide_chroot(chroot) as (root_dir, create_artifacts):
    env = {'PANTS_BOOTSTRAPDIR': root_dir}
    repo_dir = None
    if plugins:
      repo_dir = os.path.join(root_dir, 'repo')
      env.update(PANTS_PYTHON_REPOS_REPOS='[{!r}]'.format(repo_dir),
                 PANTS_PYTHON_REPOS_INDEXES='[]',
                 PANTS_PYTHON_SETUP_RESOLVER_CACHE_TTL='1')
      plugin_list = []
      for plugin in plugins:
        version = None
        if isinstance(plugin, tuple):
          plugin, version = plugin
        plugin_list.append('{}=={}'.format(plugin, version) if version else plugin)
        if create_artifacts:
          create_plugin(repo_dir, plugin, version)
      env['PANTS_PLUGINS'] = '[{}]'.format(','.join(map(repr, plugin_list)))

    configpath = os.path.join(root_dir, 'pants.ini')
    if create_artifacts:
      touch(configpath)
    args = ["--pants-config-files=['{}']".format(configpath)]

    options_bootstrapper = OptionsBootstrapper(env=env, args=args)
    plugin_resolver = PluginResolver(options_bootstrapper)
    cache_dir = plugin_resolver.plugin_cache_dir
    yield plugin_resolver.resolve(WorkingSet(entries=[])), root_dir, repo_dir, cache_dir


def test_no_plugins():
  with plugin_resolution() as (working_set, _, _, _):
    assert [] == working_set.entries


def test_plugins():
  with plugin_resolution(plugins=[('jake', '1.2.3'), 'jane']) as (working_set, _, _, cache_dir):
    assert 2 == len(working_set.entries)

    dist = working_set.find(req('jake'))
    assert dist is not None
    assert os.path.realpath(cache_dir) == os.path.realpath(os.path.dirname(dist.location))

    dist = working_set.find(req('jane'))
    assert dist is not None
    assert os.path.realpath(cache_dir) == os.path.realpath(os.path.dirname(dist.location))


def test_exact_requirements():
  with plugin_resolution(plugins=[('jake', '1.2.3'), ('jane', '3.4.5')]) as results:
    working_set, chroot, repo_dir, cache_dir = results

    assert 2 == len(working_set.entries)

    # Kill the the repo source dir and re-resolve.  If the PluginResolver truly detects exact
    # requirements it should skip any resolves and load directly from the still in-tact cache.
    safe_rmtree(repo_dir)

    with plugin_resolution(chroot=chroot,
                           plugins=[('jake', '1.2.3'), ('jane', '3.4.5')]) as results2:
      working_set2, _, _, _ = results2

      assert working_set.entries == working_set2.entries


def test_inexact_requirements():
  with plugin_resolution(plugins=[('jake', '1.2.3'), 'jane']) as results:
    working_set, chroot, repo_dir, cache_dir = results

    assert 2 == len(working_set.entries)

    # Kill the cache and the repo source dir and wait past our 1s test TTL, if the PluginResolver
    # truly detects inexact plugin requirements it should skip perma-caching and fall through to
    # pex to a TLL expiry resolve and then fail.
    safe_rmtree(repo_dir)
    safe_rmtree(cache_dir)
    Crawler.reset_cache()
    time.sleep(1.5)

    with pytest.raises(Unsatisfiable):
      with plugin_resolution(chroot=chroot, plugins=[('jake', '1.2.3'), 'jane']):
        assert False, 'Should not reach here, should raise first.'
