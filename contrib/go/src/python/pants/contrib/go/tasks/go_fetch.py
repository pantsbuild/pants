# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import shutil
from collections import defaultdict

import requests
from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir

from pants.contrib.go.subsystems.fetchers import Fetchers
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_task import GoTask


class GoFetch(GoTask):
  """Fetches third-party Go libraries."""

  @classmethod
  def global_subsystems(cls):
    return super(GoFetch, cls).global_subsystems() + (Fetchers,)

  @classmethod
  def product_types(cls):
    return ['go_remote_lib_src']

  @property
  def cache_target_dirs(self):
    # TODO(John Sirois): See TODO in _transitive_download_remote_libs, re-consider how artifact
    # caching works for fetches.
    return True

  def execute(self):
    self.context.products.safe_create_data('go_remote_lib_src', lambda: defaultdict(str))
    go_remote_libs = self.context.targets(self.is_remote_lib)
    if not go_remote_libs:
      return

    undeclared_deps = self._transitive_download_remote_libs(set(go_remote_libs))
    if undeclared_deps:
      self._log_undeclared_deps(undeclared_deps)
      raise TaskError('Failed to resolve transitive Go remote dependencies.')

  def _log_undeclared_deps(self, undeclared_deps):
    for dependee, deps in undeclared_deps.items():
      self.context.log.error('{address} has remote dependencies which require local declaration:'
                             .format(address=dependee.address.reference()))
      for dep_import_path, address in deps:
        self.context.log.error('\t--> {import_path} (expected go_remote_library declaration '
                               'at {address})'.format(import_path=dep_import_path,
                                                      address=address.reference()))

  def _get_fetcher(self, import_path):
    return Fetchers.global_instance().get_fetcher(import_path)

  @classmethod
  def _check_for_meta_tag(cls, import_path):
    """Looks for go-import meta tags for the provided import_path.

    Returns three values. First is the import prefix which designates where the
    root of the repo should be set up. Next is the version control system that
    must be used to copy down the repository. Finally is the URL to access the
    repository.

    If the meta tag is not found in the page's source, None is returned for all
    three values.

    More info: https://golang.org/cmd/go/#hdr-Remote_import_paths
    """
    session = requests.session()
    # Override default http adapters with a retriable one.
    retriable_http_adapter = requests.adapters.HTTPAdapter(max_retries=2)
    session.mount("http://", retriable_http_adapter)
    session.mount("https://", retriable_http_adapter)
    try:
      page_data = session.get('http://{import_path}?go-get=1'.format(import_path=import_path))
    except requests.ConnectionError:
      return None, None, None

    if not page_data:
      return None, None, None

    root, vcs, url = cls._find_meta_tag(page_data.text)
    if root and vcs and url:
      # Check to make sure returned root is an exact match to the provided import path. If it is
      # not then run a recursive check on the returned and return the values provided by that call.
      if root == import_path:
        return root, vcs, url
      elif import_path.startswith(root):
        return cls._check_for_meta_tag(root)

    return None, None, None

  @classmethod
  def _find_meta_tag(cls, page_html):
    """Returns the content of the meta tag if found inside of the provided HTML."""

    meta_import_regex = re.compile(r'<meta\s+name="go-import"\s+content="(?P<root>[^\s]+)\s+(?P<vcs>[^\s]+)\s+(?P<url>[^\s]+)"\s*>')
    matched = meta_import_regex.search(page_html)
    if matched:
      return matched.groups()
    return None

  def _transitive_download_remote_libs(self, go_remote_libs, all_known_addresses=None):
    """Recursively attempt to resolve / download all remote transitive deps of go_remote_libs.

    Returns a dict<GoRemoteLibrary, set<tuple<str, Address>>>, which maps a go remote library to a
    set of unresolved remote dependencies, each dependency expressed as a tuple containing the
    the import path of the dependency and the expected target address. If all transitive
    dependencies were successfully resolved, returns an empty dict.

    Downloads as many invalidated transitive dependencies as possible, and returns as many
    undeclared dependencies as possible. However, because the dependencies of a remote library
    can only be determined _after_ it has been downloaded, a transitive dependency of an undeclared
    remote library will never be detected.

    Because go_remote_libraries do not declare dependencies (rather, they are inferred), injects
    all successfully resolved transitive dependencies into the build graph.
    """
    if not go_remote_libs:
      return {}

    all_known_addresses = all_known_addresses or set()
    all_known_addresses.update(lib.address for lib in go_remote_libs)

    resolved_remote_libs = set()
    undeclared_deps = defaultdict(set)
    go_remote_lib_src = self.context.products.get_data('go_remote_lib_src')

    with self.invalidated(go_remote_libs) as invalidation_check:
      for vt in invalidation_check.all_vts:
        go_remote_lib = vt.target
        gopath = vt.results_dir
        fetcher = self._get_fetcher(go_remote_lib.import_path)

        if not vt.valid:
          meta_root, meta_protocol, meta_repo_url = self._check_for_meta_tag(go_remote_lib.import_path)

          if meta_root:
            root = fetcher.root(meta_root)
          else:
            root = fetcher.root(go_remote_lib.import_path)

          fetch_dir = os.path.join(self.workdir, 'fetches')
          root_dir = os.path.join(fetch_dir, root)

          # Only fetch each remote root once.
          if not os.path.exists(root_dir):
            with temporary_dir() as tmp_fetch_root:
              fetcher.fetch(go_remote_lib.import_path, dest=tmp_fetch_root,
                            rev=go_remote_lib.rev, meta_repo_url=meta_repo_url)
              safe_mkdir(root_dir)
              for path in os.listdir(tmp_fetch_root):
                shutil.move(os.path.join(tmp_fetch_root, path), os.path.join(root_dir, path))

          # TODO(John Sirois): Circle back and get get rid of this symlink tree.
          # GoWorkspaceTask will further symlink a single package from the tree below into a
          # target's workspace when it could just be linking from the fetch_dir.  The only thing
          # standing in the way is a determination of what we want to artifact cache.  If we don't
          # want to cache fetched zips, linking straight from the fetch_dir works simply.  Otherwise
          # thought needs to be applied to using the artifact cache directly or synthesizing a
          # canonical owner target for the fetched files that 'child' targets (subpackages) can
          # depend on and share the fetch from.
          dest_dir = os.path.join(gopath, 'src', root)
          # We may have been `invalidate`d and not `clean-all`ed so we need a new empty symlink
          # chroot to avoid collision; thus `clean=True`.
          safe_mkdir(dest_dir, clean=True)
          for path in os.listdir(root_dir):
            os.symlink(os.path.join(root_dir, path), os.path.join(dest_dir, path))

        # Map the fetched remote sources.
        pkg = go_remote_lib.import_path
        go_remote_lib_src[go_remote_lib] = os.path.join(gopath, 'src', pkg)

        for remote_import_path in self._get_remote_import_paths(pkg, gopath=gopath):
          fetcher = self._get_fetcher(remote_import_path)
          remote_root = fetcher.root(remote_import_path)
          spec_path = os.path.join(go_remote_lib.target_base, remote_root)

          package_path = GoRemoteLibrary.remote_package_path(remote_root, remote_import_path)
          target_name = package_path or os.path.basename(remote_root)

          address = Address(spec_path, target_name)
          if address not in all_known_addresses:
            try:
              # If we've already resolved a package from this remote root, its ok to define an
              # implicit synthetic remote target for all other packages in the same remote root.
              implicit_ok = any(spec_path == a.spec_path for a in all_known_addresses)

              remote_lib = self._resolve(go_remote_lib, address, package_path, implicit_ok)
              resolved_remote_libs.add(remote_lib)
              all_known_addresses.add(address)
            except self.UndeclaredRemoteLibError as e:
              undeclared_deps[go_remote_lib].add((remote_import_path, e.address))
          self.context.build_graph.inject_dependency(go_remote_lib.address, address)

  # Recurse after the invalidated block, so the libraries we downloaded are now "valid"
    # and thus we don't try to download a library twice.
    trans_undeclared_deps = self._transitive_download_remote_libs(resolved_remote_libs,
                                                                  all_known_addresses)
    undeclared_deps.update(trans_undeclared_deps)

    return undeclared_deps

  class UndeclaredRemoteLibError(Exception):
    def __init__(self, address):
      self.address = address

  def _resolve(self, dependent_remote_lib, address, pkg, implicit_ok):
    """Resolves the GoRemoteLibrary at `address` defining the given `pkg`.

    If `implicit_ok` is True, then a GoRemoteLibrary to own `pkg` is always synthesized if it does
    not already exist; otherwise the address must already exist in the build graph (a BUILD file
    must exist on disk that owns the given `pkg` and declares a `rev` for it).

    :param dependent_remote_lib: The remote library that depends on the remote `pkg`.
    :type: :class:`pants.contrib.go.targets.go_remote_library.GoRemoteLibrary`
    :param address: The address of the remote library that should own `pkg`.
    :type: :class:`pants.base.Address`
    :param string pkg: The remote package path whose owning target needs to be resolved.
    :param bool implicit_ok: `False` if the given `address` must be defined in a BUILD file on disk;
                             otherwise a remote library to own `pkg` will always be created and
                             returned.
    :returns: The resulting resolved remote library after injecting it in the build graph.
    :rtype: :class:`pants.contrib.go.targets.go_remote_library.GoRemoteLibrary`
    :raises: :class:`GoFetch.UndeclaredRemoteLibError`: If no BUILD file exists for the remote root
             `pkg` lives in.
    """
    try:
      self.context.build_graph.inject_address_closure(address)
    except AddressLookupError:
      if implicit_ok:
        self.context.add_new_target(address=address,
                                    target_base=dependent_remote_lib.target_base,
                                    target_type=GoRemoteLibrary,
                                    pkg=pkg)
      else:
        raise self.UndeclaredRemoteLibError(address)
    return self.context.build_graph.get_target(address)

  @staticmethod
  def _is_relative(import_path):
    return import_path.startswith('.')

  def _get_remote_import_paths(self, pkg, gopath=None):
    """Returns the remote import paths declared by the given remote Go `pkg`.

    NB: This only includes production code imports, no test code imports.
    """
    import_listing = self.import_oracle.list_imports(pkg, gopath=gopath)
    return [imp for imp in import_listing.imports
            if (not self.import_oracle.is_go_internal_import(imp) and
                # We assume relative imports are local to the package and skip attempts to
                # recursively resolve them.
                not self._is_relative(imp))]
