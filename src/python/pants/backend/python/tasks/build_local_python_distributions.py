# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import shutil
from contextlib import contextmanager

from pex.interpreter import PythonInterpreter

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.setup_py import SetupPyInvocationEnvironment, SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.build_graph.address import Address
from pants.task.task import Task
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_method


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

  @classmethod
  def implementation_version(cls):
    return super(BuildLocalPythonDistributions, cls).implementation_version() + [('BuildLocalPythonDistributions', 1)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(BuildLocalPythonDistributions, cls).subsystem_dependencies() + (NativeToolchain.scoped(cls),)

  @memoized_method
  def _native_toolchain_instance(self):
    return NativeToolchain.scoped_instance(self)

  @property
  def cache_target_dirs(self):
    return True

  @staticmethod
  def filter_target(tgt):
    return type(tgt) is PythonDistribution

  def execute(self):
    dist_targets = self.context.targets(self.filter_target)

    if dist_targets:
      with self.invalidated(dist_targets,
                            fingerprint_strategy=DefaultFingerprintStrategy(),
                            invalidate_dependents=True) as invalidation_check:
        interpreter = self.context.products.get_data(PythonInterpreter)

        for vt in invalidation_check.invalid_vts:
          if vt.target.dependencies:
            raise TargetDefinitionException(
              vt.target, 'The `dependencies` field is disallowed on `python_dist` targets. '
                         'List any 3rd party requirements in the install_requirements argument '
                         'of your setup function.'
            )
          self._create_dist(vt.target, vt.results_dir, interpreter)

        local_wheel_products = self.context.products.get('local_wheels')
        for vt in invalidation_check.all_vts:
          dist = self._get_whl_from_dir(os.path.join(vt.results_dir, 'dist'))
          req_lib_addr = Address.parse('{}__req_lib'.format(vt.target.address.spec))
          self._inject_synthetic_dist_requirements(dist, req_lib_addr)
          # Make any target that depends on the dist depend on the synthetic req_lib,
          # for downstream consumption.
          for dependent in self.context.build_graph.dependents_of(vt.target.address):
            self.context.build_graph.inject_dependency(dependent, req_lib_addr)
          local_wheel_products.add(vt.target, os.path.dirname(dist)).append(os.path.basename(dist))

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

  def _request_single(self, product, subject):
    # This is not supposed to be exposed to Tasks yet -- see #4769 to track the
    # status of exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]

  # FIXME(cosmicexplorer): We should be isolating the path to just our provided
  # toolchain, but this causes errors in Travis because distutils looks for
  # "x86_64-linux-gnu-gcc" when linking native extensions. We almost definitely
  # will need to introduce a subclass of UnixCCompiler and expose it to the
  # setup.py to be able to invoke our toolchain on hosts that already have a
  # compiler installed. Right now we just put our tools at the end of the PATH.
  @contextmanager
  def _setup_py_invocation_environment(self):
    setup_py_env = self._request_single(
      SetupPyInvocationEnvironment, self._native_toolchain_instance())
    with environment_as(**setup_py_env.as_env_dict()):
      yield

  def _create_dist(self, dist_tgt, dist_target_dir, interpreter):
    """Create a .whl file for the specified python_distribution target."""
    self._copy_sources(dist_tgt, dist_target_dir)

    # TODO(cosmicexplorer): don't invoke the native toolchain unless the current
    # dist_tgt.has_native_sources? Would need some way to check whether the
    # toolchain is invoked in an integration test.
    with self._setup_py_invocation_environment():
      # Build a whl using SetupPyRunner and return its absolute path.
      setup_runner = SetupPyRunner(dist_target_dir, 'bdist_wheel', interpreter=interpreter)
      setup_runner.run()

  def _inject_synthetic_dist_requirements(self, dist, req_lib_addr):
    """Inject a synthetic requirements library that references a local wheel.

    :param dist: Path of the locally built wheel to reference.
    :param req_lib_addr:  :class: `Address` to give to the synthetic target.
    :return: a :class: `PythonRequirementLibrary` referencing the locally-built wheel.
    """
    base = os.path.basename(dist)
    whl_dir = os.path.dirname(dist)
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
