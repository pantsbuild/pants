# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type
from pants.base.build_environment import get_buildroot
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.source.wrapped_globs import EagerFilesetWithSpec, RGlobs

from pants.contrib.rust.targets.synthetic.cargo_project_binary import CargoProjectBinary
from pants.contrib.rust.targets.synthetic.cargo_project_library import CargoProjectLibrary
from pants.contrib.rust.targets.synthetic.cargo_project_test import CargoProjectTest
from pants.contrib.rust.targets.synthetic.cargo_synthetic_binary import CargoSyntheticBinary
from pants.contrib.rust.targets.synthetic.cargo_synthetic_custom_build import \
  CargoSyntheticCustomBuild
from pants.contrib.rust.targets.synthetic.cargo_synthetic_library import CargoSyntheticLibrary
from pants.contrib.rust.targets.synthetic.cargo_synthetic_proc_macro import CargoSyntheticProcMacro
from pants.contrib.rust.tasks.cargo_task import CargoTask


class Workspace(CargoTask):
  # https://docs.rs/cargo/0.20.0/cargo/core/manifest/enum.TargetKind.html
  _synthetic_target_kind = {
    'bin': CargoSyntheticBinary,
    'lib': CargoSyntheticLibrary,
    'cdylib': CargoSyntheticLibrary,
    'custom-build': CargoSyntheticCustomBuild,
    'proc-macro': CargoSyntheticProcMacro,
  }

  _project_target_kind = {
    'bin': CargoProjectBinary,
    'lib': CargoProjectLibrary,
    'cdylib': CargoProjectLibrary,
    'test': CargoProjectTest,
  }

  @classmethod
  def implementation_version(cls):
    return super(Workspace, cls).implementation_version() + [('Cargo_Workspace', 1)]

  @staticmethod
  def is_target_a_member(target_name, member_names):
    return target_name in member_names

  def is_workspace_member(self, target_definition, workspace_target):
    if not self.is_cargo_original_workspace(workspace_target):
      return False
    else:
      target_is_a_member = self.is_target_a_member(target_definition.name,
                                                   workspace_target.member_names)
      if target_is_a_member and (
              self.is_lib_or_bin_target(target_definition) or self.is_test_target(
        target_definition)):
        return True
      else:
        return False

  @staticmethod
  def is_lib_or_bin_target(target_definition):
    if target_definition.kind == 'lib' or target_definition.kind == 'bin' or target_definition.kind == 'cdylib':
      return True
    else:
      return False

  @staticmethod
  def is_test_target(target_definition):
    if target_definition.kind == 'test' or target_definition.compile_mode == 'test':
      return True
    else:
      return False

  def inject_member_target(self, target_definition, workspace_target):
    def find_member(target_name, members):
      for member in members:
        name, _, _ = member
        if target_name == name:
          return member

    member_definitions = tuple((name, path, workspace_target.include_sources) for (name, path) in
                               zip(workspace_target.member_names, workspace_target.member_paths))

    member_definition = find_member(target_definition.name, member_definitions)
    target_sources = self.get_member_sources_files(member_definition)

    if self.is_test_target(target_definition):
      synthetic_target_type = self._project_target_kind['test']
    else:
      synthetic_target_type = self._project_target_kind[target_definition.kind]

    synthetic_of_original_target = self.context.add_new_target(address=target_definition.address,
                                                               target_type=synthetic_target_type,
                                                               derived_from=workspace_target,
                                                               dependencies=workspace_target.dependencies,
                                                               cargo_invocation=target_definition.invocation,
                                                               sources=target_sources)

    self.inject_synthetic_of_original_target_into_build_graph(synthetic_of_original_target,
                                                              workspace_target)

  def inject_synthetic_of_original_target_into_build_graph(self, synthetic_target, original_target):
    # https://github.com/pantsbuild/pants/blob/fedc91cb2e1455b7a8dca9c843bbd8b553a04241/src/python/pants/task/simple_codegen_task.py#L359
    build_graph = self.context.build_graph
    for dependent_address in build_graph.dependents_of(original_target.address):
      build_graph.inject_dependency(
        dependent=dependent_address,
        dependency=synthetic_target.address,
      )

    for concrete_dependency_address in build_graph.dependencies_of(original_target.address):
      build_graph.inject_dependency(
        dependent=synthetic_target.address,
        dependency=concrete_dependency_address,
      )

    if original_target in self.context.target_roots:
      self.context.target_roots.append(synthetic_target)

  def get_member_sources_files(self, member_definition):
    _, path, include_sources = member_definition
    rglobs = RGlobs.to_filespec(include_sources, root=path)
    path_globs = [PathGlobsAndRoot(
      PathGlobs(tuple(rglobs['globs'])),
      text_type(get_buildroot()),
    )]
    snapshot = self.context._scheduler.capture_snapshots(tuple(path_globs))
    fileset = EagerFilesetWithSpec(path, rglobs, snapshot[0])
    return fileset
