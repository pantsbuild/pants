# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import re
import shutil
from contextlib import contextmanager

from pex.interpreter import PythonInterpreter
from wheel.install import WheelFile

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.link_shared_libraries import SharedLibrary
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.pex_build_util import _resolve_multi
from pants.backend.python.tasks.setup_py import SetupPyExecutionEnvironment, SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.build_graph.address import Address
from pants.task.task import Task
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir, split_basename_and_dirname
from pants.util.memo import memoized_property
from pants.util.objects import Exactly


class BuildLocalPythonDistributions(Task):
  """Create python distributions (.whl) from python_dist targets."""

  options_scope = 'python-create-distributions'

  @classmethod
  def product_types(cls):
    # Note that we don't actually place the products in the product map. We stitch
    # them into the build graph instead.  This is just to force the round engine
    # to run this task when dists need to be built.
    return [PythonRequirementLibrary, 'local_wheels']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require(SharedLibrary)

  @classmethod
  def implementation_version(cls):
    return super(BuildLocalPythonDistributions, cls).implementation_version() + [('BuildLocalPythonDistributions', 2)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(BuildLocalPythonDistributions, cls).subsystem_dependencies() + (NativeToolchain.scoped(cls),)

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def _request_single(self, product, subject):
    # FIXME(cosmicexplorer): This is not supposed to be exposed to Tasks yet -- see #4769 to track
    # the status of exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]

  @memoized_property
  def _setup_py_environment(self):
    return self._request_single(SetupPyExecutionEnvironment, self._native_toolchain)

  # TODO: this should be made into a class property!!!
  @property
  def cache_target_dirs(self):
    return True

  source_target_constraint = Exactly(PythonDistribution)

  def _ensure_setup_requires_site_dir(self, dist_targets, interpreter, site_dir):
    reqs_to_resolve = set()

    for tgt in dist_targets:
      for setup_req_lib_addr in tgt.setup_requires:
        for req_lib in self.context.build_graph.resolve(setup_req_lib_addr):
          for req in req_lib.requirements:
            reqs_to_resolve.add(req)

    if not reqs_to_resolve:
      return None
    self.context.log.debug('python_dist target(s) with setup_requires detected. '
                           'Installing setup requirements: {}\n\n'
                           .format([req.key for req in reqs_to_resolve]))

    setup_requires_dists = _resolve_multi(interpreter, reqs_to_resolve, ['current'], None)

    overrides = {
      'purelib': site_dir,
      'headers': os.path.join(site_dir, 'headers'),
      'scripts': os.path.join(site_dir, 'bin'),
      'platlib': site_dir,
      'data': site_dir
    }

    # The `python_dist` target builds for the current platform only.
    for obj in setup_requires_dists['current']:
      wf = WheelFile(obj.location)
      wf.install(overrides=overrides, force=True)

    return site_dir

  def execute(self):
    dist_targets = self.context.targets(self.source_target_constraint.satisfied_by)
    if not dist_targets:
      return

    interpreter = self.context.products.get_data(PythonInterpreter)
    shared_libs_product = self.context.products.get(SharedLibrary)

    with self.invalidated(dist_targets, invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.invalid_vts:
        native_artifact_deps = self._get_native_artifact_deps(vt.target)
        setup_req_dir = os.path.join(vt.results_dir, 'setup_requires_site')
        pythonpath = self._ensure_setup_requires_site_dir(dist_targets, interpreter, setup_req_dir)
        self._create_dist(vt.target, vt.results_dir, interpreter, shared_libs_product,
                          native_artifact_deps, pythonpath=pythonpath)

      local_wheel_products = self.context.products.get('local_wheels')
      for vt in invalidation_check.all_vts:
        dist = self._get_whl_from_dir(os.path.join(vt.results_dir, 'dist'))
        req_lib_addr = Address.parse('{}__req_lib'.format(vt.target.address.spec))
        self._inject_synthetic_dist_requirements(dist, req_lib_addr)
        # Make any target that depends on the dist depend on the synthetic req_lib,
        # for downstream consumption.
        for dependent in self.context.build_graph.dependents_of(vt.target.address):
          self.context.build_graph.inject_dependency(dependent, req_lib_addr)
        dist_dir, dist_base = split_basename_and_dirname(dist)
        local_wheel_products.add(vt.target, dist_dir).append(dist_base)

  def _get_native_artifact_deps(self, target):
    native_artifact_targets = []
    if target.dependencies:
      for dep_tgt in target.dependencies:
        if not NativeLibrary.provides_native_artifact(dep_tgt):
          raise TargetDefinitionException(
            target,
            "Target '{}' is invalid: the only dependencies allowed in python_dist() targets "
            "are {}() targets with a provides= kwarg."
            .format(dep_tgt.address.spec, CLibrary.alias()))
        native_artifact_targets.append(dep_tgt)
    return native_artifact_targets

  def _copy_sources(self, dist_tgt, dist_target_dir):
    # Copy sources and setup.py over to vt results directory for packaging.
    # NB: The directory structure of the destination directory needs to match 1:1
    # with the directory structure that setup.py expects.
    all_sources = list(dist_tgt.sources_relative_to_target_base())
    for src_relative_to_target_base in all_sources:
      src_rel_to_results_dir = os.path.join(dist_target_dir, src_relative_to_target_base)
      safe_mkdir(os.path.dirname(src_rel_to_results_dir))
      abs_src_path = os.path.join(get_buildroot(),
                                  dist_tgt.address.spec_path,
                                  src_relative_to_target_base)
      shutil.copyfile(abs_src_path, src_rel_to_results_dir)

  def _add_artifacts(self, dist_target_dir, shared_libs_product, platform, native_artifact_targets):
    all_shared_libs = []
    # FIXME: dedup names of native artifacts? should that happen in the LinkSharedLibraries step?
    # (yes it should)
    for tgt in native_artifact_targets:
      product_mapping = shared_libs_product.get(tgt)
      base_dirs = product_mapping.keys()
      assert(len(base_dirs) == 1)
      single_base_dir = base_dirs[0]
      shared_libs_list = product_mapping[single_base_dir]
      assert(len(shared_libs_list) == 1)
      single_product = shared_libs_list[0]
      all_shared_libs.append(single_product)

    for shared_lib in all_shared_libs:
      basename = os.path.basename(shared_lib.path)
      resolved_outname = platform.resolve_platform_specific({
        # NB: We convert everything to .so here so that the setup.py can just
        # declare .so to build for either platform.
        'darwin': lambda: re.sub(r'\.dylib\Z', '.so', basename),
        'linux': lambda: basename,
      })
      dest_path = os.path.join(dist_target_dir, resolved_outname)
      shutil.copyfile(shared_lib.path, dest_path)

  # FIXME(cosmicexplorer): We should be isolating the path to just our provided
  # toolchain, but this causes errors in Travis because distutils looks for
  # "x86_64-linux-gnu-gcc" when linking native extensions. We almost definitely
  # will need to introduce a subclass of UnixCCompiler and expose it to the
  # setup.py to be able to invoke our toolchain on hosts that already have a
  # compiler installed. Right now we just put our tools at the end of the PATH.
  @contextmanager
  def _setup_py_execution_environment(self, pythonpath=None):
    setup_py_env = self._request_single(
      SetupPyExecutionEnvironment, self._native_toolchain)
    env = setup_py_env.as_environment()
    if pythonpath:
      self.context.log.debug('Setting PYTHONPATH with setup_requires site directory: {}'
                             .format(pythonpath))
      env['PYTHONPATH'] = pythonpath
    with environment_as(**env):
      yield

  def _create_dist(self, dist_tgt, dist_target_dir, interpreter, shared_libs_product,
                   native_artifact_targets, pythonpath=None):
    """Create a .whl file for the specified python_distribution target."""
    self._copy_sources(dist_tgt, dist_target_dir)
    self._add_artifacts(dist_target_dir, shared_libs_product, self._setup_py_environment.platform, native_artifact_targets)

    # We are platform-specific, because we have compiled artifacts.
    platform = None
    if len(native_artifact_targets) > 0:
      platform = self._setup_py_environment.platform
    setup_runner = SetupPyRunner.for_bdist_wheel(dist_target_dir, platform=platform)
    # TODO(cosmicexplorer): don't invoke the native toolchain unless the current
    # dist_tgt.has_native_sources? Would need some way to check whether the
    # toolchain is invoked in an integration test.
    with self._setup_py_execution_environment(pythonpath=pythonpath):
      # Build a whl using SetupPyRunner and return its absolute path.
      setup_runner.run()

  def _inject_synthetic_dist_requirements(self, dist, req_lib_addr):
    """Inject a synthetic requirements library that references a local wheel.

    :param dist: Path of the locally built wheel to reference.
    :param req_lib_addr:  :class: `Address` to give to the synthetic target.
    :return: a :class: `PythonRequirementLibrary` referencing the locally-built wheel.
    """
    whl_dir, base = split_basename_and_dirname(dist)
    whl_metadata = base.split('-')
    req_name = '=='.join([whl_metadata[0], whl_metadata[1]])
    req = PythonRequirement(req_name, repository=whl_dir)
    self.context.build_graph.inject_synthetic_target(req_lib_addr, PythonRequirementLibrary,
                                                     requirements=[req])

  @staticmethod
  def _get_whl_from_dir(install_dir):
    """Return the absolute path of the whl in a setup.py install directory."""
    dists = glob.glob(os.path.join(install_dir, '*.whl'))
    if len(dists) == 0:
      raise TaskError('No distributions were produced by python_create_distribution task.')
    if len(dists) > 1:
      raise TaskError('Ambiguous local python distributions found: {}'.format(dists))
    return dists[0]
