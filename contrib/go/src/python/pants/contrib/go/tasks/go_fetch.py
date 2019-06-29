# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from collections import defaultdict

from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir

from pants.contrib.go.subsystems.fetcher_factory import FetcherFactory
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_task import GoTask


class GoFetch(GoTask):
  """Fetches third-party Go libraries."""

  @classmethod
  def implementation_version(cls):
    return super().implementation_version() + [('GoFetch', 2)]

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (FetcherFactory,)

  @classmethod
  def product_types(cls):
    return ['go_remote_lib_src']

  @classmethod
  def register_options(cls, register):
    pass

  @property
  def cache_target_dirs(self):
    # TODO(John Sirois): See TODO in _fetch_pkg, re-consider how artifact caching works for fetches.
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

  @staticmethod
  def _get_fetcher(import_path):
    return FetcherFactory.global_instance().get_fetcher(import_path)

  def _fetch_pkg(self, gopath, pkg, rev):
    """Fetch the package and setup symlinks."""
    fetcher = self._get_fetcher(pkg)
    root = fetcher.root()
    root_dir = os.path.join(self.workdir, 'fetches', root, rev)

    # Only fetch each remote root once.
    if not os.path.exists(root_dir):
      with temporary_dir() as tmp_fetch_root:
        with self.context.new_workunit('fetch {}'.format(pkg)):
          fetcher.fetch(dest=tmp_fetch_root, rev=rev)
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

  # Note: Will update import_root_map.
  def _map_fetched_remote_source(self, go_remote_lib, gopath, all_known_remote_libs,
                                 resolved_remote_libs, undeclared_deps, import_root_map):
    # See if we've computed the remote import paths for this rev of this lib in a previous run.
    remote_import_paths_cache = os.path.join(os.path.dirname(gopath), 'remote_import_paths.txt')
    if os.path.exists(remote_import_paths_cache):
      with open(remote_import_paths_cache, 'r') as fp:
        remote_import_paths = [line.strip() for line in fp.readlines()]
    else:
      remote_import_paths = self._get_remote_import_paths(go_remote_lib.import_path,
                                                          gopath=gopath)
      with safe_concurrent_creation(remote_import_paths_cache) as safe_path:
        with open(safe_path, 'w') as fp:
          for path in remote_import_paths:
            fp.write('{}\n'.format(path))

    for remote_import_path in remote_import_paths:
      remote_root = import_root_map.get(remote_import_path)
      if remote_root is None:
        fetcher = self._get_fetcher(remote_import_path)
        remote_root = fetcher.root()
        import_root_map[remote_import_path] = remote_root

      spec_path = os.path.join(go_remote_lib.target_base, remote_root)

      package_path = GoRemoteLibrary.remote_package_path(remote_root, remote_import_path)
      target_name = package_path or os.path.basename(remote_root)

      address = Address(spec_path, target_name)
      if not any(address == lib.address for lib in all_known_remote_libs):
        try:
          # If we've already resolved a package from this remote root, its ok to define an
          # implicit synthetic remote target for all other packages in the same remote root.
          same_remote_libs = [lib for lib in all_known_remote_libs
                              if spec_path == lib.address.spec_path]
          implicit_ok = any(same_remote_libs)

          # If we're creating a synthetic remote target, we should pin it to the same
          # revision as the rest of the library.
          rev = None
          if implicit_ok:
            rev = same_remote_libs[0].rev

          remote_lib = self._resolve(go_remote_lib, address, package_path, rev, implicit_ok)
          resolved_remote_libs.add(remote_lib)
          all_known_remote_libs.add(remote_lib)
        except self.UndeclaredRemoteLibError as e:
          undeclared_deps[go_remote_lib].add((remote_import_path, e.address))
      self.context.build_graph.inject_dependency(go_remote_lib.address, address)

  def _transitive_download_remote_libs(self, go_remote_libs, all_known_remote_libs=None):
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

    all_known_remote_libs = all_known_remote_libs or set()
    all_known_remote_libs.update(go_remote_libs)

    resolved_remote_libs = set()
    undeclared_deps = defaultdict(set)
    go_remote_lib_src = self.context.products.get_data('go_remote_lib_src')

    with self.invalidated(go_remote_libs) as invalidation_check:
      # We accumulate mappings from import path to root (e.g., example.org/pkg/foo -> example.org)
      # from all targets in this map, so that targets share as much of this information as
      # possible during this run.
      # We cache these mappings. to avoid repeatedly fetching them over the network via the
      # meta tag protocol. Note that this mapping is unversioned: It's defined as "whatever meta
      # tag is currently being served at the relevant URL", which is inherently independent of
      # the rev of the remote library.  We (and the entire Go ecosystem) assume that this mapping
      # never changes, in practice.
      import_root_map = {}
      for vt in invalidation_check.all_vts:
        import_root_map_path = os.path.join(vt.results_dir, 'pkg_root_map.txt')
        import_root_map.update(self._read_import_root_map_file(import_root_map_path))

        go_remote_lib = vt.target
        gopath = os.path.join(vt.results_dir, 'gopath')
        if not vt.valid:
          self._fetch_pkg(gopath, go_remote_lib.import_path, go_remote_lib.rev)
        # _map_fetched_remote_source() will modify import_root_map.
        self._map_fetched_remote_source(go_remote_lib, gopath, all_known_remote_libs,
                                        resolved_remote_libs, undeclared_deps, import_root_map)
        go_remote_lib_src[go_remote_lib] = os.path.join(gopath, 'src', go_remote_lib.import_path)

        # Cache the mapping against this target's key.  Note that because we accumulate
        # mappings across targets, the file may contain mappings that this target doesn't
        # need or care about (although it will contain all the mappings this target does need).
        # But the file is small, so there's no harm in this redundancy.
        self._write_import_root_map_file(import_root_map_path, import_root_map)

    # Recurse after the invalidated block, so the libraries we downloaded are now "valid"
    # and thus we don't try to download a library twice.
    trans_undeclared_deps = self._transitive_download_remote_libs(resolved_remote_libs,
                                                                  all_known_remote_libs)
    undeclared_deps.update(trans_undeclared_deps)

    return undeclared_deps

  class UndeclaredRemoteLibError(Exception):
    def __init__(self, address):
      self.address = address

  def _resolve(self, dependent_remote_lib, address, pkg, rev, implicit_ok):
    """Resolves the GoRemoteLibrary at `address` defining the given `pkg`.

    If `implicit_ok` is True, then a GoRemoteLibrary to own `pkg` is always synthesized if it does
    not already exist; otherwise the address must already exist in the build graph (a BUILD file
    must exist on disk that owns the given `pkg` and declares a `rev` for it).

    :param dependent_remote_lib: The remote library that depends on the remote `pkg`.
    :type: :class:`pants.contrib.go.targets.go_remote_library.GoRemoteLibrary`
    :param address: The address of the remote library that should own `pkg`.
    :type: :class:`pants.base.Address`
    :param string pkg: The remote package path whose owning target needs to be resolved.
    :param string rev: The revision of the package. None defaults to `master`.
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
                                    pkg=pkg,
                                    rev=rev)
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

  @staticmethod
  def _read_import_root_map_file(path):
    """Reads a file mapping import paths to roots (e.g., example.org/pkg/foo -> example.org)."""
    if os.path.exists(path):
      with open(path, 'r') as fp:
        return dict({import_path: root for import_path, root in
                     (x.strip().split('\t') for x in fp.readlines())})
    else:
      return {}

  @staticmethod
  def _write_import_root_map_file(path, import_root_map):
    """Writes a file mapping import paths to roots."""
    with safe_concurrent_creation(path) as safe_path:
      with open(safe_path, 'w') as fp:
        for import_path, root in sorted(import_root_map.items()):
          fp.write('{}\t{}\n'.format(import_path, root))
