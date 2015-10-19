# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import subprocess
from collections import defaultdict, namedtuple
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.address import Address
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.memo import memoized_property

from pants.contrib.go.subsystems.fetchers import Fetchers
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_task import GoTask


class GoTargetGenerator(object):
  """Automatically generates a Go target graph given pre-existing target roots."""

  class GenerationError(Exception):
    """Raised to indicate an error auto-generating a Go target."""

  class WrongLocalSourceTargetTypeError(GenerationError):
    """Indicates a local source target was defined with the wrong type.

    For example, a Go main package was defined as a GoLibrary instead of a GoBinary.
    """

  class NewRemoteEncounteredButRemotesNotAllowedError(GenerationError):
    """Indicates a new remote library dependency was found but --remote was not enabled."""

  def __init__(self, workunit_factory, go_distribution, build_graph, local_root, fetchers,
               generate_remotes=False, remote_root=None):
    self._workunit_factory = workunit_factory
    self._go_distribution = go_distribution
    self._build_graph = build_graph
    self._local_source_root = local_root
    self._fetchers = fetchers
    self._generate_remotes = generate_remotes
    self._remote_source_root = remote_root

  def generate(self, local_go_targets):
    """Automatically generates a Go target graph for the given local go targets.

    :param iter local_go_targets: The target roots to fill in a target graph for.
    :raises: :class:`GoTargetGenerator.GenerationError` if any missing targets cannot be generated.
    """
    visited = {l.import_path: l.address for l in local_go_targets}
    with temporary_dir() as gopath:
      for local_go_target in local_go_targets:
        name, import_paths = self._list_deps(gopath, local_go_target.address)
        self._generate_missing(gopath, local_go_target.address, name, import_paths, visited)
    return visited.items()

  def _generate_missing(self, gopath, local_address, name, import_paths, visited):
    target_type = GoBinary if name == 'main' else GoLibrary
    existing = self._build_graph.get_target(local_address)
    if not existing:
      self._build_graph.inject_synthetic_target(address=local_address, target_type=target_type)
    elif existing and not isinstance(existing, target_type):
      raise self.WrongLocalSourceTargetTypeError('{} should be a {}'
                                                 .format(existing, target_type.__name__))

    for import_path in import_paths:
      if import_path not in self._go_stdlib:
        if import_path not in visited:
          fetcher = self._fetchers.maybe_get_fetcher(import_path)
          if fetcher:
            remote_root = fetcher.root(import_path)
            remote_pkg_path = GoRemoteLibrary.remote_package_path(remote_root, import_path)
            name = remote_pkg_path or os.path.basename(import_path)
            address = Address(os.path.join(self._remote_source_root, remote_root), name)
            found = self._build_graph.get_target(address)
            if not found:
              if not self._generate_remotes:
                raise self.NewRemoteEncounteredButRemotesNotAllowedError(
                  'Cannot generate dependency for remote import path {}'.format(import_path))
              self._build_graph.inject_synthetic_target(address=address,
                                                        target_type=GoRemoteLibrary,
                                                        pkg=remote_pkg_path)
          else:
            # Recurse on local targets.
            address = Address(os.path.join(self._local_source_root, import_path),
                              os.path.basename(import_path))
            name, import_paths = self._list_deps(gopath, address)
            self._generate_missing(gopath, address, name, import_paths, visited)
          visited[import_path] = address
        dependency_address = visited[import_path]
        self._build_graph.inject_dependency(local_address, dependency_address)

  @memoized_property
  def _go_stdlib(self):
    out = self._go_distribution.create_go_cmd('list', args=['std']).check_output()
    return frozenset(out.strip().split())

  def _list_deps(self, gopath, local_address):
    # TODO(John Sirois): Lift out a local go sources target chroot util - GoWorkspaceTask and
    # GoTargetGenerator both create these chroot symlink trees now.
    import_path = GoLocalSource.local_import_path(self._local_source_root, local_address)
    src_path = os.path.join(gopath, 'src', import_path)
    safe_mkdir(src_path)
    package_src_root = os.path.join(get_buildroot(), local_address.spec_path)
    for source_file in os.listdir(package_src_root):
      source_path = os.path.join(package_src_root, source_file)
      if GoLocalSource.is_go_source(source_path):
        dest_path = os.path.join(src_path, source_file)
        os.symlink(source_path, dest_path)

    # TODO(John Sirois): Lift up a small `go list utility` - GoFetch and GoTargetGenerator both use
    # this go command now as well as a version of the stdlib gathering done above in _go_stdlib.
    go_cmd = self._go_distribution.create_go_cmd('list', args=['-json', import_path], gopath=gopath)
    with self._workunit_factory(local_address.reference(),
                                cmd=str(go_cmd),
                                labels=[WorkUnitLabel.TOOL]) as workunit:
      # TODO(John Sirois): It would be nice to be able to tee the stdout to the workunit to we have
      # a capture of the json available for inspection in the server console.
      process = go_cmd.spawn(stdout=subprocess.PIPE, stderr=workunit.output('stderr'))
      out, _ = process.communicate()
      returncode = process.returncode
      workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
      if returncode != 0:
        raise self.GenerationError('Problem listing imports for {}: {} failed with exit code {}'
                                   .format(local_address, go_cmd, returncode))
      data = json.loads(out)
      return data.get('Name'), data.get('Imports', []) + data.get('TestImports', [])


class GoBuildgen(GoTask):
  """Automatically generates Go BUILD files."""

  @classmethod
  def global_subsystems(cls):
    return super(GoBuildgen, cls).global_subsystems() + (Fetchers,)

  @classmethod
  def _default_template(cls):
    return dedent("""\
    {{#target.parameters?}}
    {{target.type}}(
      {{#target.parameters}}
      {{#deps?}}
      dependencies=[
        {{#deps}}
        '{{.}}',
        {{/deps}}
      ]
      {{/deps?}}
      {{#rev}}
      rev='{{.}}',
      {{/rev}}
      {{#pkgs?}}
      packages=[
        {{#pkgs}}
        '{{.}}',
        {{/pkgs}}
      ]
      {{/pkgs?}}
      {{/target.parameters}}
    )
    {{/target.parameters?}}
    {{^target.parameters?}}
    {{target.type}}()
    {{/target.parameters?}}
    """)

  @classmethod
  def register_options(cls, register):
    register('--remote', action='store_true', advanced=True, fingerprint=True,
             help='Allow auto-generation of remote dependencies without pinned versions.')

    register('--materialize', action='store_true', advanced=True, fingerprint=True,
             help='Instead of just auto-generating missing go_binary and go_library targets in '
                  'memory, (re-)generate them on disk using the installed Go BUILD file template.')

    # TODO(John Sirois): Add docs for the template parameters.
    register('--template', metavar='<template>', fromfile=True,
             default=cls._default_template(),
             advanced=True, fingerprint=True,
             help='A Go BUILD file mustache template to use with --materialize.')

    register('--extension', default='', metavar='<ext>', advanced=True, fingerprint=True,
             help='An optional extension for all materialized BUILD files (should include the .)')

  def execute(self):
    materialize = self.get_options().materialize
    if materialize:
      local_go_targets = None  # We want a full scan, which passing no local go targets signals.
      if self.context.target_roots:
        self.context.log.warn('{} ignoring targets passed on the command line and re-materializing '
                              'the complete Go BUILD forest.'.format(self.options_scope))
    else:
      local_go_targets = self.context.targets(self.is_local_src)
      if not local_go_targets:
        return

    generation_result = self.generate_targets(local_go_targets=local_go_targets)
    if not generation_result:
      return

    if not materialize:
      msg = ('Auto generated the following Go targets: target (import path):\n\t{}'
             .format('\n\t'.join(sorted('{} ({})'.format(addr.reference(), ip)
                                        for ip, addr in generation_result.generated))))
      self.context.log.info(msg)
    elif generation_result:
      self._materialize(generation_result)

  class TemplateResult(namedtuple('TemplateResult', ['build_file_path', 'data', 'import_paths',
                                                     'needs_rev', 'rev'])):

    def log(self, logger):
      log = logger.warn if (self.needs_rev and not self.rev) else logger.info
      log('\t{} ({}){}'.format(self.build_file_path,
                               ' '.join(sorted(self.import_paths)),
                               ' {}'.format(self.rev or 'FLOATING') if self.needs_rev else ''))

  def _materialize(self, generation_result):
    remote = self.get_options().remote
    existing_go_buildfiles = set()

    def gather_go_buildfiles(rel_path):
      address_mapper = self.context.address_mapper
      for build_file in address_mapper.scan_buildfiles(root_dir=get_buildroot(),
                                                       base_path=rel_path,
                                                       spec_excludes=self.context.spec_excludes):
        existing_go_buildfiles.add(build_file.relpath)

    gather_go_buildfiles(generation_result.local_root)
    if remote and generation_result.remote_root != generation_result.local_root:
      gather_go_buildfiles(generation_result.remote_root)

    targets = set(self.context.build_graph.targets(self.is_go))
    if remote and generation_result.remote_root:
      # Generation only walks out from local source, but we might have transitive remote
      # dependencies under the remote root which are not linked except by `resolve.go`.  Add all
      # the remotes we can find to ensure they are re-materialized too.
      remote_root = os.path.join(get_buildroot(), generation_result.remote_root)
      targets.update(self.context.scan(remote_root).targets(self.is_remote_lib))

    for result in self.generate_build_files(targets):
      existing_go_buildfiles.discard(result.build_file_path)
      result.log(self.context.log)

    if existing_go_buildfiles:
      deleted = []
      for existing_go_buildfile in existing_go_buildfiles:
        spec_path = os.path.dirname(existing_go_buildfile)
        for address in self.context.address_mapper.addresses_in_spec_path(spec_path):
          target = self.context.address_mapper.resolve(address)
          if isinstance(target, GoLocalSource):
            os.unlink(existing_go_buildfile)
            deleted.append(existing_go_buildfile)
      if deleted:
        self.context.log.info('Deleted the following obsolete BUILD files:\n\t{}'
                              .format('\n\t'.join(sorted(deleted))))

  class NoLocalRootsError(TaskError):
    """Indicates the Go local source owning targets' source roots are invalid."""

  class InvalidLocalRootsError(TaskError):
    """Indicates the Go local source owning targets' source roots are invalid."""

  class UnrootedLocalSourceError(TaskError):
    """Indicates there are Go local source owning targets that fall outside the source root."""

  class InvalidRemoteRootsError(TaskError):
    """Indicates the Go remote library source roots are invalid."""

  class GenerationError(TaskError):
    """Indicates an error generating Go targets."""

    def __init__(self, cause):
      super(GoBuildgen.GenerationError, self).__init__(str(cause))
      self.cause = cause

  class GenerationResult(namedtuple('GenerationResult', ['generated',
                                                         'local_root',
                                                         'remote_root'])):
    """Captures the result of a Go target generation round."""

  def generate_targets(self, local_go_targets=None):
    """Generate Go targets in memory to form a complete Go graph.

    :param local_go_targets: The local Go targets to fill in a complete target graph for.  If
                             `None`, then all local Go targets under the Go source root are used.
    :type local_go_targets: :class:`collections.Iterable` of
                            :class:`pants.contrib.go.targets.go_local_source import GoLocalSource`
    :returns: A generation result if targets were generated, else `None`.
    :rtype: :class:`GoBuildgen.GenerationResult`
    """
    # TODO(John Sirois): support multiple source roots like GOPATH does?
    # The GOPATH's 1st element is read-write, the rest are read-only; ie: their sources build to
    # the 1st element's pkg/ and bin/ dirs.

    # TODO: Add "find source roots for lang" functionality to SourceRoots and use that instead.
    all_roots = list(self.context.source_roots.all_roots())
    local_roots = [sr.path for sr in all_roots if 'go' in sr.langs]
    if not local_roots:
      raise self.NoLocalRootsError('Can only BUILD gen if a Go local sources source root is '
                                   'defined.')
    if len(local_roots) > 1:
      raise self.InvalidLocalRootsError('Can only BUILD gen for a single Go local sources source '
                                        'root, found:\n\t{}'
                                        .format('\n\t'.join(sorted(local_roots))))
    local_root = local_roots.pop()

    if local_go_targets:
      unrooted_locals = {t for t in local_go_targets if t.target_base != local_root}
      if unrooted_locals:
        raise self.UnrootedLocalSourceError('Cannot BUILD gen until the following targets are '
                                            'relocated to the source root at {}:\n\t{}'
                                            .format(local_root,
                                                    '\n\t'.join(sorted(t.address.reference()
                                                                       for t in unrooted_locals))))
    else:
      root = os.path.join(get_buildroot(), local_root)
      local_go_targets = self.context.scan(root=root).targets(self.is_local_src)
      if not local_go_targets:
        return None

    remote_roots = [sr.path for sr in all_roots if 'go_remote' in sr.langs]
    if len(remote_roots) > 1:
      raise self.InvalidRemoteRootsError('Can only BUILD gen for a single Go remote library source '
                                         'root, found:\n\t{}'
                                         .format('\n\t'.join(sorted(remote_roots))))
    remote_root = remote_roots.pop() if remote_roots else None

    generator = GoTargetGenerator(self.context.new_workunit,
                                  self.go_dist,
                                  self.context.build_graph,
                                  local_root,
                                  Fetchers.global_instance(),
                                  generate_remotes=self.get_options().remote,
                                  remote_root=remote_root)
    with self.context.new_workunit('go.buildgen', labels=[WorkUnitLabel.MULTITOOL]):
      try:
        generated = generator.generate(local_go_targets)
        return self.GenerationResult(generated=generated,
                                     local_root=local_root,
                                     remote_root=remote_root)
      except generator.GenerationError as e:
        raise self.GenerationError(e)

  def generate_build_files(self, targets):
    goal_name = self.options_scope
    flags = '--materialize'
    if self.get_options().remote:
      flags += ' --remote'
    template_header = dedent("""\
      # Auto-generated by pants!
      # To re-generate run: `pants {goal_name} {flags}`

      """).format(goal_name=goal_name, flags=flags)
    template_text = template_header + self.get_options().template
    build_file_basename = 'BUILD' + self.get_options().extension

    targets_by_spec_path = defaultdict(set)
    for target in targets:
      targets_by_spec_path[target.address.spec_path].add(target)

    for spec_path, targets in targets_by_spec_path.items():
      rel_path = os.path.join(spec_path, build_file_basename)
      result = self._create_template_data(rel_path, list(targets))
      if result:
        generator = Generator(template_text, target=result.data)
        build_file_path = os.path.join(get_buildroot(), rel_path)
        with safe_open(build_file_path, mode='w') as fp:
          generator.write(stream=fp)
        yield result

  class NonUniformRemoteRevsError(TaskError):
    """Indicates packages with mis-matched versions are defined for a single remote root."""

  def _create_template_data(self, build_file_path, targets):
    if len(targets) == 1 and self.is_local_src(targets[0]):
      local_target = targets[0]
      data = self._data(target_type='go_binary' if self.is_binary(local_target) else 'go_library',
                        deps=[d.address.reference() for d in local_target.dependencies])
      return self.TemplateResult(build_file_path=build_file_path,
                                 data=data,
                                 import_paths=[local_target.import_path],
                                 needs_rev=False,
                                 rev=None)
    elif self.get_options().remote:
      if len(targets) == 1 and not targets[0].pkg:
        remote_lib = targets[0]
        data = self._data(target_type='go_remote_library',
                          rev=remote_lib.rev)
        return self.TemplateResult(build_file_path=build_file_path,
                                   data=data,
                                   import_paths=(remote_lib.import_path,),
                                   needs_rev=True,
                                   rev=remote_lib.rev)
      else:
        revs = {t.rev for t in targets if t.rev}
        if len(revs) > 1:
          msg = ('Cannot create BUILD file {} for the following packages at remote root {}, '
                 'they must all have the same version:\n\t{}'
                 .format(build_file_path, targets[0].remote_root,
                         '\n\t'.join('{} {}'.format(t.pkg, t.rev) for t in targets)))
          raise self.NonUniformRemoteRevsError(msg)
        rev = revs.pop() if revs else None

        data = self._data(target_type='go_remote_libraries',
                          rev=rev,
                          pkgs=sorted({t.pkg for t in targets}))
        return self.TemplateResult(build_file_path=build_file_path,
                                   data=data,
                                   import_paths=tuple(t.import_path for t in targets),
                                   needs_rev=True,
                                   rev=rev)
    else:
      return None

  def _data(self, target_type, deps=None, rev=None, pkgs=None):
    parameters = TemplateData(deps=deps, rev=rev, pkgs=pkgs) if (deps or rev or pkgs) else None
    return TemplateData(type=target_type, parameters=parameters)
