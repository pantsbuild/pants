# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

import six.moves.urllib.parse as urllib_parse
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.fs.archive import archiver_for_path
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir

from pants.contrib.node.subsystems.resolvers.node_resolver_base import NodeResolverBase
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.tasks.node_resolve import NodeResolve


class NodePreinstalledModuleResolver(Subsystem, NodeResolverBase):
  options_scope = 'node-preinstalled-module-resolver'

  @classmethod
  def register_options(cls, register):
    register('--fetch-timeout-secs', type=int, advanced=True, default=10,
             help='Timeout the fetch if the connection is idle for longer than this value.')
    super(NodePreinstalledModuleResolver, cls).register_options(register)
    NodeResolve.register_resolver_for_type(NodePreinstalledModule, cls)

  def resolve_target(self, node_task, target, results_dir, node_paths):
    self._copy_sources(target, results_dir)

    with temporary_dir() as temp_dir:
      archive_file_name = urllib_parse.urlsplit(target.dependencies_archive_url).path.split('/')[-1]
      if not archive_file_name:
        raise TaskError('Could not determine archive file name for {target} from {url}'
                        .format(target=target.address.reference(),
                                url=target.dependencies_archive_url))

      download_path = os.path.join(temp_dir, archive_file_name)

      node_task.context.log.info(
        'Downloading archive {archive_file_name} from '
        '{dependencies_archive_url} to {path}'
        .format(archive_file_name=archive_file_name,
                dependencies_archive_url=target.dependencies_archive_url,
                path=download_path))

      try:
        Fetcher(get_buildroot()).download(target.dependencies_archive_url,
                                          listener=Fetcher.ProgressListener(),
                                          path_or_fd=download_path,
                                          timeout_secs=self.get_options().fetch_timeout_secs)
      except Fetcher.Error as error:
        raise TaskError('Failed to fetch preinstalled node_modules for {target} from {url}: {error}'
                        .format(target=target.address.reference(),
                                url=target.dependencies_archive_url,
                                error=error))

      node_task.context.log.info(
        'Fetched archive {archive_file_name} from {dependencies_archive_url} to {path}'
        .format(archive_file_name=archive_file_name,
                dependencies_archive_url=target.dependencies_archive_url,
                path=download_path))

      archiver_for_path(archive_file_name).extract(download_path, temp_dir)

      extracted_node_modules = os.path.join(temp_dir, 'node_modules')
      if not os.path.isdir(extracted_node_modules):
        raise TaskError('Did not find an extracted node_modules directory for {target} '
                        'inside {dependencies_archive_url}'
                        .format(target=target.address.reference(),
                                dependencies_archive_url=target.dependencies_archive_url))

      shutil.move(extracted_node_modules, os.path.join(results_dir, 'node_modules'))
