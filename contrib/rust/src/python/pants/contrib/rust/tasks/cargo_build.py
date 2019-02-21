# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import hashlib
import json
import os
import shutil

from future.utils import PY3
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.address import Address
from pants.util.dirutil import absolute_symlink, safe_file_dump, safe_mkdir

from pants.contrib.rust.targets.cargo_base_target import CargoBaseTarget
from pants.contrib.rust.tasks.cargo_workspace import Workspace
from pants.contrib.rust.utils.basic_invocation_conversion import \
  convert_into_pants_invocation as convert_basic_into_pants_invocation
from pants.contrib.rust.utils.custom_build_invocation_conversion import \
  convert_into_pants_invocation as convert_custom_build_into_pants_invocation
from pants.contrib.rust.utils.custom_build_output_parsing import (filter_cargo_statements,
                                                                  parse_multiple_cargo_statements)


class Build(Workspace):
  _build_script_output = dict()
  _package_out_dirs = dict()
  _libraries_dir_path = None

  @classmethod
  def implementation_version(cls):
    return super(Build, cls).implementation_version() + [('Cargo_Build', 1)]

  @classmethod
  def register_options(cls, register):
    super(Build, cls).register_options(register)
    register(
      '--cargo-opt',
      type=list,
      default=[],
      help='Append these options to the cargo command line.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(Build, cls).prepare(options, round_manager)
    round_manager.require_data('cargo_env')

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def product_types(cls):
    return ['rust_libs', 'rust_bins', 'rust_tests']

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    self.prepare_task()
    self.prepare_cargo_targets()

    cargo_targets = self.context.build_graph.targets(self.is_cargo_base_target)
    self.build_targets(cargo_targets)

  def prepare_task(self):
    self.context.products.safe_create_data('rust_libs', lambda: {})
    self.context.products.safe_create_data('rust_bins', lambda: {})
    self.context.products.safe_create_data('rust_tests', lambda: {})
    self._libraries_dir_path = self.create_libraries_dir()

  def create_libraries_dir(self):
    libraries_dir_path = os.path.join(self.versioned_workdir, 'deps')
    safe_mkdir(libraries_dir_path)
    return libraries_dir_path

  def prepare_cargo_targets(self):
    cargo_targets = self.get_targets(self.is_cargo_workspace)
    for target in cargo_targets:
      cargo_build_plan = self.get_cargo_build_plan(target)
      target_definitions = self.get_target_definitions_out_of_cargo_build_plan(cargo_build_plan)
      self.generate_targets(target_definitions, target)

  def get_cargo_build_plan(self, target):
    with self.context.new_workunit(name='cargo-build-plan',
                                   labels=[WorkUnitLabel.COMPILER]) as workunit:
      abs_manifest_path = os.path.join(get_buildroot(), target.manifest, self.manifest_name())

      self.context.log.info(
        'Getting cargo build plan for manifest: {0}\nAdditional cargo options: {1}'.format(
          abs_manifest_path, self.get_options().cargo_opt))

      cmd = ['cargo', 'build',
             '--manifest-path', abs_manifest_path,
             '--build-plan', '-Z', 'unstable-options']

      if self.include_compiling_tests():
        cmd.extend(['--tests'])

      cmd.extend(self.get_options().cargo_opt)

      env = {
        'CARGO_HOME': (self.context.products.get_data('cargo_env')['CARGO_HOME'], False),
        'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)
      }

      std_output = self.run_command_and_get_output(cmd, target.toolchain, env, workunit)
      cargo_build_plan = json.loads(std_output)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.info(workunit.outcome_string(workunit.outcome()))

    return cargo_build_plan

  def include_compiling_tests(self):
    return 'test' in self.context.requested_goals

  def get_target_definitions_out_of_cargo_build_plan(self, cargo_build_plan):
    cargo_invocations = cargo_build_plan['invocations']
    target_definitions = []
    TargetDefinition = collections.namedtuple('TargetDefinition',
                                              'name, id, address, dependencies, kind, invocation, compile_mode')
    for invocation in cargo_invocations:
      rel_path = os.path.relpath(invocation['cwd'], get_buildroot())
      # remove deps out of the fingerprint because the order of the targets is not fixed
      dependencies = invocation.pop('deps')
      # create a fingerprint over the item because the cargo build_plan dosen't provide a unique id
      hasher = hashlib.md5(json.dumps(invocation, sort_keys=True).encode('utf-8'))
      fingerprint = hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')
      name = invocation['package_name']
      id = name + '_' + fingerprint
      kind = invocation['target_kind'][0]
      compile_mode = invocation['compile_mode']
      target_definitions.append(
        TargetDefinition(name, id, Address(rel_path, id), dependencies, kind, invocation,
                         compile_mode))
    return target_definitions

  def generate_targets(self, target_definitions, cargo_target):
    for target in target_definitions:
      target_exist = self.context.build_graph.get_target(target.address)
      if not target_exist:
        if self.is_workspace_member(target, cargo_target):
          self.context.log.debug(
            'Add project member target: {0}\ttarget kind: {1}'.format(target.id, target.kind))
          self.inject_member_target(target, cargo_target)
        else:
          self.context.log.debug(
            'Add synthetic target: {0}\ttarget kind: {1}'.format(target.id, target.kind))
          self.context.build_graph.inject_synthetic_target(address=target.address,
                                                           target_type=self._synthetic_target_kind.get(
                                                             target.kind, CargoBaseTarget),
                                                           cargo_invocation=target.invocation)
        for dependency in target.dependencies:
          dependency = target_definitions[dependency]
          self.context.log.debug(
            '\tInject dependency: {0}\tfor: {1}\ttarget kind: {2}'.format(dependency.id, target.id,
                                                                          dependency.kind))
          self.context.build_graph.inject_dependency(target.address, dependency.address)

  def build_targets(self, targets):
    with self.invalidated(targets, invalidate_dependents=True,
                          topological_order=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        pants_invocation = self.convert_cargo_invocation_into_pants_invocation(vt)
        if not vt.valid:
          self.build_target(vt.target, pants_invocation)
        else:
          self.context.log.info('{0} v{1} is up to date.'.format(pants_invocation['package_name'],
                                                                 pants_invocation[
                                                                   'package_version']))
        self.add_rust_products(vt.target, pants_invocation)

  def convert_cargo_invocation_into_pants_invocation(self, vt):
    if self.is_cargo_base_library(vt.target):
      self.context.log.debug(
        'Convert library invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_base_proc_macro(vt.target):
      self.context.log.debug(
        'Convert pro macro invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_base_binary(vt.target):
      self.context.log.debug(
        'Convert binary invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_test(vt.target):
      self.context.log.debug(
        'Convert test invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_base_custom_build(vt.target):
      self.context.log.debug(
        'Convert custom build invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_custom_build_into_pants_invocation(vt.target, vt.results_dir,
                                                                    self._package_out_dirs,
                                                                    self._libraries_dir_path)
    else:
      raise TaskError(
        'Unsupported target kind for target: {0}'.format(vt.target.address.target_name))
    return pants_invocation

  def build_target(self, target, pants_invocation):
    with self.context.new_workunit(name=pants_invocation['compile_mode'],
                                   labels=[WorkUnitLabel.COMPILER]) as workunit:
      self.context.log.info(
        '{0} v{1}'.format(pants_invocation['package_name'], pants_invocation['package_version']))

      self.create_directories(pants_invocation['pants_make_dirs'])

      cmd = self.create_command(pants_invocation['program'], pants_invocation['args'], target)

      env = {
        'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)
      }

      env = self._add_env_vars(env, pants_invocation['env'])

      if pants_invocation['program'] == 'rustc':
        self.run_command(cmd, pants_invocation['cwd'], env, workunit)
      else:
        std_output = self.run_command_and_get_output(cmd, pants_invocation['cwd'], env, workunit)
        build_script_std_out_dir = self._package_out_dirs[target.address.target_name]
        self._build_script_output[
          target.address.target_name] = self.parse_and_save_build_script_output(std_output,
                                                                                build_script_std_out_dir[
                                                                                  1])

      self.create_copies(pants_invocation['links'])

      if 'pants_make_sym_links' in pants_invocation:
        self.create_library_symlink(pants_invocation['pants_make_sym_links'],
                                    self._libraries_dir_path)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.info(workunit.outcome_string(workunit.outcome()))

  def parse_and_save_build_script_output(self, std_output, out_dir):
    lines = std_output.split('\n')
    cargo_statements = filter_cargo_statements(lines)
    head, base = os.path.split(out_dir)
    safe_file_dump(os.path.join(head, 'output'), '\n'.join(cargo_statements), mode='w')
    return parse_multiple_cargo_statements(cargo_statements)

  def create_directories(self, make_dirs):
    build_root = get_buildroot()
    for dir in make_dirs.keys():
      self.context.log.debug('Create directory: {0}'.format(os.path.relpath(dir, build_root)))
      safe_mkdir(dir)

  def create_library_symlink(self, make_symlinks, libraries_dir):
    build_root = get_buildroot()
    for file in make_symlinks.keys():
      self.context.log.debug(
        'Create sym link: {0}\n\tto: {1}'.format(os.path.relpath(file, build_root),
                                                 os.path.relpath(libraries_dir, build_root)))
      file_name = os.path.basename(file)
      destination = os.path.join(libraries_dir, file_name)
      absolute_symlink(file, destination)

  def create_copies(self, links):
    build_root = get_buildroot()
    for destination, source in links.items():
      self.context.log.debug('Copy: {0}\n\tto: {1}'.format(os.path.relpath(source, build_root),
                                                           os.path.relpath(destination,
                                                                           build_root)))
      if not os.path.exists(source):
        ## --release flag doesn't create dSYM folder
        self.context.log.warn('{0} doesn\'t exist.'.format(os.path.relpath(source, build_root)))
      else:
        if os.path.isfile(source):
          shutil.copy(source, destination)
        else:
          shutil.copytree(source, destination)

  def create_command(self, program, args, target):
    cmd = [program]
    cmd.extend(args)
    return self.extend_args(cmd, target)

  def extend_args(self, cmd, target):
    def extend_cmd(cmd, cargo_outputs):
      for output in cargo_outputs:
        cmd.extend(output)
      return cmd

    for dependency in target.dependencies:
      cargo_outputs = self._build_script_output.get(dependency.address.target_name, None)
      if cargo_outputs:
        self.context.log.debug('Custom build outputs:\n{0}'.format(self.stringify(cargo_outputs)))
        cmd = extend_cmd(cmd, cargo_outputs['rustc-link-lib'])
        cmd = extend_cmd(cmd, cargo_outputs['rustc-link-search'])
        cmd = extend_cmd(cmd, cargo_outputs['rustc-flags'])
        cmd = extend_cmd(cmd, cargo_outputs['rustc-cfg'])
    return cmd

  def add_rust_products(self, target, pants_invocation):
    name = pants_invocation['package_name']
    links = pants_invocation['links']
    if self.is_cargo_library(target):
      rust_libs = self.context.products.get_data('rust_libs')
      current = rust_libs.get(name, [])
      current.extend(list(filter(lambda path: os.path.exists(path), links.keys())))
      rust_libs.update({name: current})
    elif self.is_cargo_binary(target):
      rust_bins = self.context.products.get_data('rust_bins')
      current = rust_bins.get(name, [])
      current.extend(list(filter(lambda path: os.path.exists(path), links.keys())))
      rust_bins.update({name: current})
    elif self.is_cargo_test(target):
      cwd_test = pants_invocation['cwd_test']
      rust_tests = self.context.products.get_data('rust_tests')
      current = rust_tests.get(target.address.target_name, [])
      current.extend(list(
        map(lambda path: (path, cwd_test),
            filter(lambda path: os.path.exists(path), links.keys()))))
      rust_tests.update({target.address.target_name: current})

  def stringify(self, obj):
    return json.dumps(obj, indent=4, separators=(',', ': '))
