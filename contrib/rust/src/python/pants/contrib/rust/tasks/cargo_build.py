# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import copy
import functools
import hashlib
import json
import os
import shutil

from future.utils import PY3
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.invalidation.build_invalidator import CacheKeyGenerator
from pants.util.dirutil import absolute_symlink, read_file, safe_file_dump, safe_mkdir

from pants.contrib.rust.tasks.cargo_fingerprint_strategy import CargoFingerprintStrategy
from pants.contrib.rust.tasks.cargo_workspace import Workspace
from pants.contrib.rust.utils.basic_invocation.args_rules import (args_rules, c_flag_rules,
                                                                  l_flag_rules)
from pants.contrib.rust.utils.basic_invocation.env_rules import env_rules
from pants.contrib.rust.utils.basic_invocation_conversion import \
  convert_into_pants_invocation as convert_basic_into_pants_invocation
from pants.contrib.rust.utils.custom_build_invocation_conversion import \
  convert_into_pants_invocation as convert_custom_build_into_pants_invocation
from pants.contrib.rust.utils.custom_build_output_parsing import (filter_cargo_statements,
                                                                  parse_multiple_cargo_statements)


class Build(Workspace):
  _build_script_output_cache = {}
  _build_index = {}
  _package_out_dirs = {}
  _libraries_dir_path = None
  _build_index_dir_path = None

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
      help='Additional cargo build options e.g. `--release`.')
    register(
      '--ignore-rerun',
      type=bool,
      default=False,
      help='Ignore rebuilding build scripts which include a cargo `rerun-if-changed` statement.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(Build, cls).prepare(options, round_manager)
    round_manager.require_data('cargo_env')
    round_manager.require_data('cargo_toolchain')

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def product_types(cls):
    return ['rust_libs', 'rust_bins', 'rust_tests']

  def execute(self):
    self.prepare_task()
    self.prepare_cargo_targets()

    cargo_targets = self.context.build_graph.targets(self.is_cargo_synthetic)
    self.build_targets(cargo_targets)
    self.write_build_index()

  def prepare_task(self):
    self.context.products.safe_create_data('rust_libs', lambda: {})
    self.context.products.safe_create_data('rust_bins', lambda: {})
    self.context.products.safe_create_data('rust_tests', lambda: {})
    self._libraries_dir_path = self.create_libraries_dir()
    self._build_index_dir_path = self.create_build_index_dir()
    self.read_build_index()

  def create_libraries_dir(self):
    libraries_dir_path = os.path.join(self.versioned_workdir, 'deps')
    safe_mkdir(libraries_dir_path)
    return libraries_dir_path

  def create_build_index_dir(self):
    build_index_dir_path = os.path.join(self.versioned_workdir, 'build_index')
    safe_mkdir(build_index_dir_path)
    return build_index_dir_path

  def prepare_cargo_targets(self):
    cargo_targets = self.get_targets(self.is_cargo_original)
    for target in cargo_targets:
      cargo_build_plan = self.get_cargo_build_plan(target)
      target_definitions = self.get_target_definitions_out_of_cargo_build_plan(cargo_build_plan)
      self.generate_targets(target_definitions, target)

    if self.get_options().ignore_rerun is False:
      self.check_if_build_scripts_are_invalid()

  def get_cargo_build_plan(self, target):
    abs_manifest_path = os.path.join(target.manifest, self.manifest_name())

    self.context.log.info(
      'Getting cargo build plan for manifest: {0}\nAdditional cargo options: {1}'.format(
        abs_manifest_path, self.get_options().cargo_opt))

    toolchain = "+{}".format(self.context.products.get_data('cargo_toolchain'))

    cmd = ['cargo', toolchain, 'build',
           '--manifest-path', abs_manifest_path,
           '--build-plan', '-Z', 'unstable-options']

    if self.include_compiling_tests():
      cmd.extend(['--tests'])

    cmd.extend(self.get_options().cargo_opt)

    env = {
      'CARGO_HOME': (self.context.products.get_data('cargo_env')['CARGO_HOME'], False),
      'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)
    }

    returncode, std_output, std_error = self.execute_command_and_get_output(cmd,
                                                                            'cargo-build-plan',
                                                                            [
                                                                              WorkUnitLabel.COMPILER],
                                                                            env_vars=env,
                                                                            current_working_dir=target.manifest)

    if returncode != 0:
      self.print_std_out_and_std_err(std_output, std_error)
      raise TaskError('Cannot create build plan for: {}'.format(abs_manifest_path))

    cargo_build_plan = json.loads(std_output)

    return cargo_build_plan

  def include_compiling_tests(self):
    return self.context.products.is_required_data('rust_tests')

  def get_target_definitions_out_of_cargo_build_plan(self, cargo_build_plan):
    cargo_invocations = cargo_build_plan['invocations']
    return list(
      map(lambda invocation: self.create_target_definition(invocation), cargo_invocations))

  def create_target_definition(self, cargo_invocation):
    TargetDefinition = collections.namedtuple('TargetDefinition',
                                              'name, id, address, '
                                              'dependencies, kind, '
                                              'invocation, compile_mode')
    name = cargo_invocation['package_name']
    fingerprint = self.calculate_target_definition_fingerprint(cargo_invocation)
    id = "{}_{}".format(name, fingerprint)
    rel_path = os.path.relpath(cargo_invocation['cwd'], get_buildroot())
    dependencies = cargo_invocation.pop('deps')
    assert (len(cargo_invocation['target_kind']) == 1)
    kind = cargo_invocation['target_kind'][0]
    compile_mode = cargo_invocation['compile_mode']
    return TargetDefinition(name, id, Address(rel_path, id), dependencies, kind, cargo_invocation,
                            compile_mode)

  def calculate_target_definition_fingerprint(self, cargo_invocation):
    invocation = copy.deepcopy(cargo_invocation)

    invocation.pop('deps')
    invocation.pop('outputs')
    invocation.pop('links')

    c_flag_rule = {
      'incremental': lambda _: "",
    }

    l_flag_rule = {
      'dependency': lambda _: "",
    }

    args_rules_set = {
      '--out-dir': lambda _: "",
      '-C': functools.partial(c_flag_rules, rules=c_flag_rule),
      '-L': functools.partial(l_flag_rules, rules=l_flag_rule),
      '--extern': lambda _: ""
    }

    args_rules(invocation['args'], rules=args_rules_set)

    env_rules_set = {
      'OUT_DIR': lambda _: "",
      # nightly-2018-12-31 macOS
      'DYLD_LIBRARY_PATH': lambda _: "",
      # nightly macOS
      'DYLD_FALLBACK_LIBRARY_PATH': lambda _: "",
      # nightly-2018-12-31 linux
      'LD_LIBRARY_PATH': lambda _: ""
    }

    env_rules(invocation['env'], rules=env_rules_set)

    if invocation['compile_mode'] == 'run-custom-build':
      invocation.pop('program')

    hasher = hashlib.md5(json.dumps(invocation, sort_keys=True).encode('utf-8'))
    return hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')

  def generate_targets(self, target_definitions, cargo_target):
    for target in target_definitions:
      target_exist = self.context.build_graph.get_target(target.address)
      if not target_exist:
        if self.is_workspace_member(target, cargo_target):
          self.context.log.debug(
            'Add project member target: {0}\ttarget kind: {1}'.format(target.id, target.kind))
          self.inject_member_target(target, cargo_target)
        elif self.is_lib_or_bin(target, cargo_target):
          self.context.log.debug(
            'Add project target: {0}\ttarget kind: {1}'.format(target.id, target.kind))
          self.inject_lib_or_bin_target(target, cargo_target)
        else:
          self.context.log.debug(
            'Add synthetic target: {0}\ttarget kind: {1}'.format(target.id, target.kind))
          self.context.build_graph.inject_synthetic_target(address=target.address,
                                                           target_type=self._synthetic_target_kind[
                                                             target.kind],
                                                           cargo_invocation=target.invocation)
        for dependency in target.dependencies:
          dependency = target_definitions[dependency]
          self.context.log.debug(
            '\tInject dependency: {0}\tfor: {1}\ttarget kind: {2}'.format(dependency.id, target.id,
                                                                          dependency.kind))
          self.context.build_graph.inject_dependency(target.address, dependency.address)

  def is_lib_or_bin(self, target_definition, original_target):
    if not self.is_cargo_original_library(original_target) and not self.is_cargo_original_binary(
            original_target):
      return False
    else:
      is_original_target = target_definition.name == original_target.name

      if is_original_target and (
              self.is_lib_or_bin_target(target_definition) or self.is_test_target(
        target_definition)):
        return True
      else:
        return False

  def inject_lib_or_bin_target(self, target_definition, original_target):
    if self.is_test_target(target_definition):
      synthetic_target_type = self._project_target_kind['test']
    else:
      synthetic_target_type = self._project_target_kind[target_definition.kind]

    synthetic_of_original_target = self.context.add_new_target(address=target_definition.address,
                                                               target_type=synthetic_target_type,
                                                               cargo_invocation=target_definition.invocation,
                                                               dependencies=original_target.dependencies,
                                                               derived_from=original_target,
                                                               sources=original_target.sources_relative_to_target_base())

    self.inject_synthetic_of_original_target_into_build_graph(synthetic_of_original_target,
                                                              original_target)

  def get_build_flags(self):
    get_build_flags_func = copy.copy(self.get_options().cargo_opt)
    get_build_flags_func.sort()
    get_build_flags_func.append(self.context.products.get_data('cargo_toolchain'))
    if self.include_compiling_tests():
      get_build_flags_func.append('--tests')
    return ' '.join(get_build_flags_func)

  def build_targets(self, targets):
    build_flags = self.get_build_flags()
    fingerprint_strategy = CargoFingerprintStrategy(build_flags)
    with self.invalidated(targets, invalidate_dependents=True,
                          fingerprint_strategy=fingerprint_strategy,
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
    if self.is_cargo_synthetic_library(vt.target):
      self.context.log.debug(
        'Convert library invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_synthetic_binary(vt.target):
      self.context.log.debug(
        'Convert binary invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_project_test(vt.target):
      self.context.log.debug(
        'Convert test invocation for: {0}'.format(vt.target.address.target_name))
      pants_invocation = convert_basic_into_pants_invocation(vt.target, vt.results_dir,
                                                             self._package_out_dirs,
                                                             self._libraries_dir_path)
    elif self.is_cargo_synthetic_custom_build(vt.target):
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
    self.context.log.info(
      '{0} v{1}'.format(pants_invocation['package_name'], pants_invocation['package_version']))

    self.create_directories(pants_invocation['pants_make_dirs'])

    cmd = self.create_command(pants_invocation['program'], pants_invocation['args'], target)

    env = self.create_env(pants_invocation['env'], target)

    if pants_invocation['program'] == 'rustc':
      self.execute_rustc(pants_invocation['package_name'],
                         cmd, '{}-{}'.format(pants_invocation['compile_mode'],
                                             pants_invocation['target_kind'][0]),
                         env, pants_invocation['cwd'])
    else:
      self.execute_custom_build(cmd,
                                pants_invocation['compile_mode'],
                                env, pants_invocation['cwd'], target)

    self.create_copies(pants_invocation['links'])

    if 'pants_make_sym_links' in pants_invocation:
      self.create_library_symlink(pants_invocation['pants_make_sym_links'],
                                  self._libraries_dir_path)

  def save_and_parse_build_script_output(self, std_output, out_dir, target):
    cargo_statements = self.parse_build_script_output(std_output)
    output_path = self.create_build_script_output_path(out_dir)
    safe_file_dump(output_path, '\n'.join(cargo_statements), mode='w')
    self._build_index.update({target.address.spec: output_path})
    return parse_multiple_cargo_statements(cargo_statements)

  def parse_build_script_output(self, output):
    lines = output.split('\n')
    return filter_cargo_statements(lines)

  def create_build_script_output_path(self, out_dir):
    head, base = os.path.split(out_dir)
    output_path = os.path.join(head, 'output')
    return output_path

  def create_build_script_stderr_path(self, out_dir):
    head, base = os.path.split(out_dir)
    stderr_path = os.path.join(head, 'stderr')
    return stderr_path

  def create_directories(self, make_dirs):
    build_root = get_buildroot()
    for dir in make_dirs:
      self.context.log.debug('Create directory: {0}'.format(os.path.relpath(dir, build_root)))
      safe_mkdir(dir)

  def create_library_symlink(self, make_symlinks, libraries_dir):
    build_root = get_buildroot()
    for file in make_symlinks:
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
    return self.extend_args_with_cargo_statement(cmd, target)

  def extend_args_with_cargo_statement(self, cmd, target):
    def extend_cmd(cmd, build_script_output):
      for output_cmd in build_script_output:
        cmd.extend(output_cmd)
      return cmd

    for dependency in target.dependencies:
      build_script_output = self._build_script_output_cache.get(dependency.address.target_name,
                                                                None)
      if build_script_output:
        self.context.log.debug(
          'Custom build outputs:\n{0}'.format(self.pretty(build_script_output)))
        cmd = extend_cmd(cmd, build_script_output['rustc-link-lib'])
        cmd = extend_cmd(cmd, build_script_output['rustc-link-search'])
        cmd = extend_cmd(cmd, build_script_output['rustc-flags'])
        cmd = extend_cmd(cmd, build_script_output['rustc-cfg'])
    return cmd

  def create_env(self, invocation_env, target):
    env = {
      'PATH': (self.context.products.get_data('cargo_env')['PATH'], True),
      'RUSTUP_TOOLCHAIN': (self.context.products.get_data('cargo_toolchain'), False)
    }

    env = self._add_env_vars(env, invocation_env)

    return self.extend_env_with_cargo_statement(env, target)

  def extend_env_with_cargo_statement(self, env, target):
    for dependency in target.dependencies:
      build_script_output = self._build_script_output_cache.get(dependency.address.target_name,
                                                                None)
      if build_script_output:
        self.context.log.debug(
          'Custom build output:\n{0}'.format(self.pretty(build_script_output['rustc-env'])))
        for rustc_env in build_script_output['rustc-env']:
          # is PATH also possible?
          name, value = rustc_env
          env = self._add_env_var(env, name, value)
    return env

  def execute_custom_build(self, cmd, workunit_name, env, cwd, target):
    returncode, std_output, std_error = self.execute_command_and_get_output(cmd,
                                                                            workunit_name,
                                                                            [
                                                                              WorkUnitLabel.COMPILER],
                                                                            env_vars=env,
                                                                            current_working_dir=cwd)

    if returncode != 0:
      self.print_std_out_and_std_err(std_output, std_error)
      raise TaskError('Cannot execute build script for: {}'.format(cwd))

    build_script_std_out_dir = self._package_out_dirs[target.address.target_name][1]
    self._build_script_output_cache[target.address.target_name] = \
      self.save_and_parse_build_script_output(std_output, build_script_std_out_dir, target)

    if len(std_error) > 0:
      stderr_path = self.create_build_script_stderr_path(build_script_std_out_dir)
      safe_file_dump(stderr_path, std_error, mode='w')
      self.context.log.warn(
        'STD_ERR of {0} saved in: {1}'.format(target.address.target_name, stderr_path))

    for warning in self._build_script_output_cache[target.address.target_name]['warning']:
      self.context.log.warn('Warning: {0}'.format(warning))

  def execute_rustc(self, package_name, cmd, workunit_name, env, cwd):
    returncode = self.execute_command(cmd,
                                      workunit_name,
                                      [WorkUnitLabel.COMPILER],
                                      env_vars=env,
                                      current_working_dir=cwd)

    if returncode != 0:
      raise TaskError('Cannot build target: {}'.format(package_name))

  def add_rust_products(self, target, pants_invocation):
    name = pants_invocation['package_name']
    links = pants_invocation['links']
    if self.is_cargo_project_library(target):
      rust_libs = self.context.products.get_data('rust_libs')
      current = rust_libs.get(name, [])
      current.extend(list(filter(lambda path: os.path.exists(path), links.keys())))
      rust_libs.update({name: current})
    elif self.is_cargo_project_binary(target):
      rust_bins = self.context.products.get_data('rust_bins')
      current = rust_bins.get(name, [])
      current.extend(list(filter(lambda path: os.path.exists(path), links.keys())))
      rust_bins.update({name: current})
    elif self.is_cargo_project_test(target):
      env = pants_invocation['env']
      cwd_test = pants_invocation['cwd_test']
      rust_tests = self.context.products.get_data('rust_tests')
      current = rust_tests.get(target.address.target_name, [])
      current.extend(list(
        map(lambda path: (path, cwd_test, env),
            filter(lambda path: os.path.exists(path) and os.path.isfile(path), links.keys()))))
      rust_tests.update({target.address.target_name: current})

  def mark_target_invalid(self, address):
    target = self.context.build_graph.get_target(address)
    self._build_invalidator.force_invalidate((CacheKeyGenerator().key_for_target(target)))

    def mark_dependee_invalid(dependee):
      self._build_invalidator.force_invalidate((CacheKeyGenerator().key_for_target(dependee)))

    self.context.build_graph.walk_transitive_dependee_graph(
      [address],
      work=lambda dependee: mark_dependee_invalid(dependee),
    )

  def check_if_build_scripts_are_invalid(self):
    for target_addr_spec, build_script_output_path in self._build_index.items():
      target_address = Address.parse(target_addr_spec)
      if self.context.build_graph.get_target(target_address) and os.path.isfile(
              build_script_output_path):
        build_scripts_output = read_file(build_script_output_path, binary_mode=False)
        cargo_statements = self.parse_build_script_output(build_scripts_output)
        parsed_statements = parse_multiple_cargo_statements(cargo_statements)
        if len(parsed_statements['rerun-if-changed']) != 0 or len(
                parsed_statements['rerun-if-env-changed']) != 0:
          self.context.log.info('Rebuild target: {0}'.format(target_address.target_name))
          self.mark_target_invalid(target_address)

  def get_build_index_file_path(self):
    return os.path.join(self._build_index_dir_path, 'index.json')

  def read_build_index(self):
    build_index_path = self.get_build_index_file_path()
    if not os.path.isfile(build_index_path):
      self.context.log.debug('No build index was found.')
      self._build_index = {}
      self.invalidate()
    else:
      self.context.log.debug('Read build index from: {0}'.format(build_index_path))
      with open(build_index_path, 'r') as build_index_json_file:
        try:
          self._build_index = json.load(build_index_json_file)
        except ValueError as ve:
          self.context.log.debug(ve)
          self._build_index = {}
          self.invalidate()

  def write_build_index(self):
    build_index_path = self.get_build_index_file_path()
    self.context.log.debug('Write build index to: {0}'.format(build_index_path))
    mode = 'w' if PY3 else 'wb'
    with open(build_index_path, mode) as build_index_json_file:
      json.dump(self._build_index, build_index_json_file, indent=2, separators=(',', ': '))

  def print_std_out_and_std_err(self, std_output, std_error):
    self.context.log.error('==== stdout ====\n{0}'.format(std_output))
    self.context.log.error('==== stderr ====\n{0}'.format(std_error))
