# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_method
from pants.util.strutil import safe_shlex_split

from pants.contrib.go.targets.go_target import GoTarget
from pants.contrib.go.tasks.go_binary_fingerprint_strategy import GoBinaryFingerprintStrategy
from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoCompile(GoWorkspaceTask):
  """Compiles a Go package into either a library binary or executable binary.

  GoCompile will populate the "bin/" and "pkg/" directories of each target's Go
  workspace (see GoWorkspaceTask) with executables and library binaries respectively.
  """

  @classmethod
  def implementation_version(cls):
    return super().implementation_version() + [('GoCompile', 1)]

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    # Build flags fingerprint is handled by a custom strategy to enable
    # merging with task-specific flags.
    register('--build-flags', default='', help='Build flags to pass to Go compiler.')

  @classmethod
  def product_types(cls):
    return ['exec_binary', 'deployable_archives']

  def execute(self):
    get_build_flags_func = functools.partial(self._get_build_flags,
                                             self.get_options().build_flags,
                                             self.get_options().is_flagged('build_flags'))
    fingerprint_strategy = GoBinaryFingerprintStrategy(get_build_flags_func)
    self.context.products.safe_create_data('exec_binary', lambda: {})
    with self.invalidated(self.context.targets(self.is_go),
                          invalidate_dependents=True,
                          fingerprint_strategy=fingerprint_strategy,
                          topological_order=True) as invalidation_check:
      # Maps each local/remote library target to its compiled binary.
      lib_binary_map = {}
      go_exec_binary = self.context.products.get_data('exec_binary')
      go_deployable_archive = self.context.products.get('deployable_archives')
      for vt in invalidation_check.all_vts:
        gopath = self.get_gopath(vt.target)
        if not isinstance(vt.target, GoTarget):
          continue
        if not vt.valid:
          self.ensure_workspace(vt.target)
          self._sync_binary_dep_links(vt.target, gopath, lib_binary_map)
          build_flags = get_build_flags_func(vt.target)
          self._go_install(vt.target, gopath, build_flags)
        if self.is_binary(vt.target):
          subdir, extension = self._get_cross_compiling_subdir_and_extension(gopath)
          binary_path = os.path.join(gopath, 'bin', subdir, os.path.basename(vt.target.address.spec_path) + extension)
          go_exec_binary[vt.target] = binary_path
          go_deployable_archive.add(vt.target, os.path.dirname(binary_path)).append(os.path.basename(binary_path))
        else:
          lib_binary_map[vt.target] = os.path.join(gopath, 'pkg', self.goos_goarch,
                                                   vt.target.import_path + '.a')

  @classmethod
  @memoized_method
  def _get_build_flags(cls, build_flags_from_option, is_flagged, target):
    """Merge build flags with global < target < command-line order

    Build flags can be defined as globals (in `pants.ini`), as arguments to a Target, and
    via the command-line.
    """
    # If self.get_options().build_flags returns a quoted string, remove the outer quotes,
    # which happens for flags passed from the command-line.
    if (build_flags_from_option.startswith('\'') and build_flags_from_option.endswith('\'')) or \
        (build_flags_from_option.startswith('"') and build_flags_from_option.endswith('"')):
      bfo = build_flags_from_option[1:-1]
    else:
      bfo = build_flags_from_option
    global_build_flags, ephemeral_build_flags = ('', bfo) if is_flagged else (bfo, '')
    target_build_flags = target.build_flags if getattr(target, 'build_flags', None) else ''
    joined_build_flags = ' '.join([global_build_flags, target_build_flags, ephemeral_build_flags])
    return cls._split_build_flags(joined_build_flags)

  @staticmethod
  def _split_build_flags(build_flags):
    return safe_shlex_split(build_flags)  # Visible for testing

  def _go_install(self, target, gopath, build_flags):
    """Create and execute a `go install` command."""
    args = build_flags + [target.import_path]
    result, go_cmd = self.go_dist.execute_go_cmd(
      'install', gopath=gopath, args=args,
      workunit_factory=self.context.new_workunit,
      workunit_name='install {}'.format(target.import_path),
      workunit_labels=[WorkUnitLabel.COMPILER])
    if result != 0:
      raise TaskError('{} failed with exit code {}'.format(go_cmd, result))

  def _sync_binary_dep_links(self, target, gopath, lib_binary_map):
    """Syncs symlinks under gopath to the library binaries of target's transitive dependencies.

    :param Target target: Target whose transitive dependencies must be linked.
    :param str gopath: $GOPATH of target whose "pkg/" directory must be populated with links
                       to library binaries.
    :param dict<Target, str> lib_binary_map: Dictionary mapping a remote/local Go library to the
                                             path of the compiled binary (the ".a" file) of the
                                             library.

    Required links to binary dependencies under gopath's "pkg/" dir are either created if
    non-existent, or refreshed if the link is older than the underlying binary. Any pre-existing
    links within gopath's "pkg/" dir that do not correspond to a transitive dependency of target
    are deleted.
    """
    required_links = set()
    for dep in target.closure():
      if dep == target:
        continue
      if not isinstance(dep, GoTarget):
        continue
      lib_binary = lib_binary_map[dep]
      lib_binary_link = os.path.join(gopath, os.path.relpath(lib_binary, self.get_gopath(dep)))
      safe_mkdir(os.path.dirname(lib_binary_link))
      if os.path.islink(lib_binary_link):
        if os.stat(lib_binary).st_mtime > os.lstat(lib_binary_link).st_mtime:
          # The binary under the link was updated after the link was created. Refresh
          # the link so the mtime (modification time) of the link is greater than the
          # mtime of the binary. This stops Go from needlessly re-compiling the library.
          os.unlink(lib_binary_link)
          os.symlink(lib_binary, lib_binary_link)
      else:
        os.symlink(lib_binary, lib_binary_link)
      required_links.add(lib_binary_link)
    self.remove_unused_links(os.path.join(gopath, 'pkg'), required_links)

  def _get_cross_compiling_subdir_and_extension(self, gopath):
    # Note that environment variables don't invalidate the build graph, so changes to GOOS or GOARCH
    # require a clean-all.

    host_goos = self.go_dist.create_go_cmd('env', gopath=gopath, args=["GOHOSTOS"]).check_output().decode().strip()
    target_goos = self.go_dist.create_go_cmd('env', gopath=gopath, args=["GOOS"]).check_output().decode().strip()
    host_arch = self.go_dist.create_go_cmd('env', gopath=gopath, args=["GOARCH"]).check_output().decode().strip()
    target_arch = self.go_dist.create_go_cmd('env', gopath=gopath, args=["GOHOSTARCH"]).check_output().decode().strip()

    host_pair = "{}_{}".format(host_goos, host_arch)
    target_pair = "{}_{}".format(target_goos, target_arch)

    ext = ".exe" if target_goos == "windows" else ""

    if host_pair != target_pair:
      return (target_pair, ext)
    return (".", ext)
