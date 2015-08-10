# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import subprocess
from collections import defaultdict
from io import BytesIO

import requests
from pants.base.address import BuildFileAddress
from pants.base.build_environment import get_buildroot
from pants.base.build_file import FilesystemBuildFile
from pants.base.build_graph import AddressLookupError
from pants.base.exceptions import TaskError
from pants.util.contextutil import open_zip
from pants.util.dirutil import get_basedir, safe_mkdir, safe_open

from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_task import GoTask


class GoFetch(GoTask):
  """Downloads a 3rd party Go library."""

  @classmethod
  def product_types(cls):
    return ['go_remote_lib_src']

  def __init__(self, *args, **kwargs):
    super(GoFetch, self).__init__(*args, **kwargs)
    self._go_stdlib = None

  @property
  def go_stdlib(self):
    if self._go_stdlib is None:
      args = ['go', 'list', 'std']
      out = subprocess.check_output(args)
      self._go_stdlib = set(out.strip().split())
    return self._go_stdlib

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    self.context.products.safe_create_data('go_remote_lib_src', lambda: defaultdict(str))
    undeclared_deps = self._transitive_download_remote_libs(self.context.targets(self.is_remote_lib))
    if undeclared_deps:
      self._log_undeclared_deps(undeclared_deps)
      raise TaskError('Failed to resolve transitive Go remote dependencies.')

  def _log_undeclared_deps(self, undeclared_deps):
    for import_id, deps in undeclared_deps.items():
      self.context.log.error('{import_id} has remote dependencies which require local declaration:'
                             .format(import_id=import_id))
      for dep_import_id, spec_path in deps:
        self.context.log.error('\t--> {dep_import_id} (expected go_remote_library declaration '
                               'at {spec_path})'.format(dep_import_id=dep_import_id,
                                                        spec_path=spec_path))

  def _transitive_download_remote_libs(self, go_remote_libs):
    """Recursively attempt to resolve / download all remote transitive deps of go_remote_libs.

    Returns a dict<str, set<tuple<str, str>>>, which maps a global import id of a remote dep to a
    set of unresolved remote dependencies, each dependency expressed as a tuple containing the
    global import id of the dependency and the location of the expected BUILD file. If all
    transitive dependencies were successfully resolved, returns and empty dict.

    Downloads as many invalidated transitive dependencies as possible, and returns as many
    undeclared dependencies as possible. However, because the dependencies of a remote library
    can only be determined _after_ it has been downloaded, a transitive dependency of an undeclared
    remote library will never be detected.

    Because go_remote_libraries do not declare dependencies (rather, they are inferred), injects
    all successfully resolved transitive dependencies into the build graph.
    """
    if not go_remote_libs:
      return {}

    resolved_remote_libs = []
    undeclared_deps = defaultdict(set)

    # Remove duplicate remote libraries.
    go_remote_libs = set(go_remote_libs)
    with self.invalidated(go_remote_libs) as invalidation_check:
      for vt in invalidation_check.all_vts:
        import_id = self.global_import_id(vt.target)
        dest_dir = os.path.join(vt.results_dir, import_id)

        if not vt.valid:
          # Only download invalidated remote libraries.
          rev = vt.target.payload.get_field_value('rev')
          zip_url = vt.target.payload.get_field_value('zip_url').format(id=import_id, rev=rev)
          if not zip_url:
            raise TaskError('No zip url specified for go_remote_library {id}'
                            .format(id=import_id))
          self._download_zip(zip_url, dest_dir)

        self.context.products.get_data('go_remote_lib_src')[vt.target] = dest_dir

        for remote_import_id in self._get_remote_import_ids(dest_dir):
          try:
            remote_lib = self._resolve_and_inject(vt.target, remote_import_id)
            resolved_remote_libs.append(remote_lib)
          except self.UndeclaredRemoteLibError as e:
            undeclared_deps[import_id].add((remote_import_id, e.spec_path))

    # Recurse after the invalidated block, so the libraries we downloaded are now "valid"
    # and thus we don't try to download a library twice.
    trans_undeclared_deps = self._transitive_download_remote_libs(resolved_remote_libs)
    self._absorb_dict(undeclared_deps, trans_undeclared_deps)

    return undeclared_deps

  class UndeclaredRemoteLibError(Exception):
    def __init__(self, spec_path):
      self.spec_path = spec_path

  def _resolve_and_inject(self, dependent_remote_lib, dependee_import_id):
    """Resolves dependee_import_id's BUILD file and injects it into the build graph.

    :param GoRemoteLibrary dependent_remote_lib:
        Injects the resolved target of dependee_import_id as a dependency of this
        remote library.
    :param str dependee_import_id:
        Global import id of the remote library whose BUILD file to look up.
    :return GoRemoteLibrary:
        Returns the resulting resolved remote library after injecting it in the build graph.
    :raises UndeclaredRemoteLibError:
        If no BUILD file exists for dependee_import_id under the same source root of
        dependent_remote_lib, raises exception.
    """
    remote_source_root = dependent_remote_lib.target_base
    spec_path = os.path.join(remote_source_root, dependee_import_id)
    try:
      build_file = FilesystemBuildFile(get_buildroot(), relpath=spec_path)
    except FilesystemBuildFile.MissingBuildFileError:
      raise self.UndeclaredRemoteLibError(spec_path)
    address = BuildFileAddress(build_file)
    self.context.build_graph.inject_address_closure(address)
    self.context.build_graph.inject_dependency(dependent_remote_lib.address, address)
    return self.context.build_graph.get_target(address)

  @staticmethod
  def _absorb_dict(main_dict, other_dict):
    for k, v in other_dict.items():
      if k not in main_dict:
        main_dict[k] = v

  def _download_zip(self, zip_url, dest_dir):
    """Downloads a zip file at the given URL into the given directory.

    :param str zip_url: Full URL pointing to zip file.
    :param str dest_dir: Absolute path of directory into which the unzipped contents
                         will be placed into, not including the zip directory itself.
    """
    # TODO(cgibb): Wrap with workunits, progress meters, checksums.
    self.context.log.info('Downloading {}...'.format(zip_url))
    res = requests.get(zip_url)
    if not res.status_code == requests.codes['ok']:
      raise TaskError('Failed to download {} ({} error)'.format(zip_url, res.status_code))

    with open_zip(BytesIO(res.content)) as zfile:
      safe_mkdir(dest_dir)
      for info in zfile.infolist():
        if info.filename.endswith('/'):
          # Skip directories.
          continue
        # Strip zip directory name from files.
        filename = os.path.relpath(info.filename, get_basedir(info.filename))
        f = safe_open(os.path.join(dest_dir, filename), 'w')
        f.write(zfile.read(info))
        f.close()

  def _get_remote_import_ids(self, pkg_dir):
    """Returns the remote import ids declared by the Go package at pkg_dir."""
    args = ['go', 'list', '-json', os.path.join(pkg_dir, '*.go')]
    # Needs to execute through shell for wildcard ('*.go').
    out = subprocess.check_output(' '.join(args), shell=True)
    imports = json.loads(out)['Imports']
    return [imp for imp in imports if imp not in self.go_stdlib]
