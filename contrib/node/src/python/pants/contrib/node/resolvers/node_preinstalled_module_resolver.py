# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import closing

import six.moves.urllib.error as urllib_error
import six.moves.urllib.request as urllib_request
from pants.base.exceptions import TaskError
from pants.fs.archive import TGZ
from pants.util.dirutil import safe_mkdtemp, safe_open

from pants.contrib.node.resolvers.node_resolver_base import NodeResolverBase


class NodePreinstalledModuleResolver(NodeResolverBase):

  def resolve_target(self, node_task, target, results_dir, node_paths):
    self._copy_sources(target, results_dir)

    temp_dir = safe_mkdtemp()

    download_path = os.path.join(temp_dir, 'node_modules.tar.gz')
    try:
      with closing(urllib_request.urlopen(target.url)) as opened_tar_url:
        with safe_open(download_path, 'wb') as downloaded_tar_file:
          downloaded_tar_file.write(opened_tar_url.read())
    except (IOError, urllib_error.HTTPError, urllib_error.URLError, ValueError) as e:
      raise TaskError('Failed to fetch preinstalled node_modules for {target} from {url}: {error}'
                      .format(target=target.address.reference(), url=target.url, error=e))

    TGZ.extract(download_path, temp_dir)

    extracted_node_modules = os.path.join(temp_dir, 'node_modules')
    if not os.path.isdir(extracted_node_modules):
      raise TaskError('Did not find an extracted node_modules directory for {target} inside {url}'
                      .format(target=target.address.reference(), url=target.url))

    os.rename(extracted_node_modules, os.path.join(results_dir, 'node_modules'))
