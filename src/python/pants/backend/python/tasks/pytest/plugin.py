# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
from zlib import crc32

import pytest


# NB: This file must keep Python 2 support because it is a resource that may be run with Python 2.




class NodeRenamerPlugin(object):
  """A pytest plugin to modify the console output of test names.

  Replaces the chroot-based source paths with the source-tree based ones, which are more readable to
  the end user.
  """

  def __init__(self, rootdir, sources_map):
    def rootdir_relative(path):
      return os.path.relpath(path, rootdir)

    self._sources_map = {rootdir_relative(k): rootdir_relative(v) for k, v in sources_map.items()}

  # We'd prefer to hook into pytest_runtest_logstart(), which actually prints the line we want to
  # fix, but we can't because we won't have access to any of its state, so we can't actually change
  # what it prints.
  #
  # Alternatively, we could hook into pytest_collect_file() and just set a custom nodeid for the
  # entire pytest run.  However this interferes with pytest internals, including fixture
  # registration, leading to  fixtures not running when they should.
  @pytest.hookimpl(hookwrapper=True)
  def pytest_runtest_protocol(self, item, nextitem):
    # Temporarily change the nodeid, which pytest uses for display.
    real_nodeid = item.nodeid
    real_path = real_nodeid.split('::', 1)[0]
    fixed_path = self._sources_map.get(real_path, real_path)
    fixed_nodeid = fixed_path + real_nodeid[len(real_path):]
    try:
      item._nodeid = fixed_nodeid
      yield
    finally:
      item._nodeid = real_nodeid


class ShardingPlugin(object):
  def __init__(self, shard, num_shards):
    self._shard = shard
    self._num_shards = num_shards

  def pytest_report_header(self, config):
    return ('shard: {shard} of {num_shards} (0-based shard numbering)'
            .format(shard=self._shard, num_shards=self._num_shards))

  def pytest_collection_modifyitems(self, session, config, items):
    total_count = len(items)
    removed = 0
    def is_conftest(itm):
      return itm.fspath and itm.fspath.basename == 'conftest.py'
    # We hash-mod to assign to shards to avoid hotspots when there are fewer tests than there
    # are shards.
    for i, item in enumerate(list(x for x in items if not is_conftest(x))):
      if crc32(str(item.nodeid).encode()) % self._num_shards != self._shard:
        del items[i - removed]
        removed += 1
    reporter = config.pluginmanager.getplugin('terminalreporter')
    reporter.write_line('Only executing {count} of {total} total tests in shard {shard} of '
                        '{num_shards}'.format(count=total_count - removed,
                                              total=total_count,
                                              shard=self._shard,
                                              num_shards=self._num_shards),
                        bold=True, invert=True, yellow=True)


def pytest_addoption(parser):
  group = parser.getgroup('pants', 'Pants testing support')
  group.addoption('--pants-sources-map-path',
                  dest='sources_map_path',
                  action='store',
                  metavar='PATH',
                  help='Path to a source mapping file that should contain JSON object mapping from'
                       'absolute source chroot path keys to the path of the original source '
                       'relative to the buildroot.')
  group.addoption('--pants-shard',
                  dest='shard',
                  action='store',
                  default=0,
                  type=int,
                  help='The shard of tests to select for this run.')
  group.addoption('--pants-num-shards',
                  dest='num_shards',
                  action='store',
                  default=1,
                  type=int,
                  help='The total number of shards being used to complete the run.')


def pytest_configure(config):
  if config.getoption('help'):
    # Don't configure our plugins when the user is just asking for help.
    return

  rootdir = str(config.rootdir)

  sources_map_path = config.getoption('sources_map_path')
  with open(sources_map_path) as fp:
    sources_map = json.load(fp)

  config.pluginmanager.register(NodeRenamerPlugin(rootdir, sources_map), 'pants_test_renamer')

  num_shards = config.getoption('num_shards')
  if num_shards > 1:
    shard = config.getoption('shard')
    config.pluginmanager.register(ShardingPlugin(shard, num_shards))
