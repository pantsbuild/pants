# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir_for
from pants.util.fileutil import atomic_copy

from pants.contrib.awslambda.python.targets.python_awslambda import PythonAWSLambda
from pants.contrib.awslambda.python.tasks.lambdex_prep import LambdexPrep


class LambdexRun(Task):
  """Runs Lambdex to convert pexes to AWS Lambda functions.

  Note that your pex must be built to run on Amazon Linux, e.g., if it contains native code.
  When deploying the lambda, its handler should be set to `lambdex_handler.handler`, which
  is a wrapper around the target-specified handler.
  """

  @staticmethod
  def _is_python_lambda(target):
    return isinstance(target, PythonAWSLambda)

  @classmethod
  def product_types(cls):
    return ['python_aws_lambda']

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require_data(LambdexPrep.tool_instance_cls)
    round_manager.require('pex_archives')

  @classmethod
  def create_target_dirs(self):
    return True

  def execute(self):
    targets = self.get_targets(self._is_python_lambda)
    with self.invalidated(targets=targets, invalidate_dependents=True) as invalidation_check:
      python_lambda_product = self.context.products.get_data('python_aws_lambda', dict)
      for vt in invalidation_check.all_vts:
        lambda_path = os.path.join(vt.results_dir, '{}.pex'.format(vt.target.name))
        if not vt.valid:
          self.context.log.debug('Existing lambda for {} is invalid, rebuilding'.format(vt.target))
          self._create_lambda(vt.target, lambda_path)
        else:
          self.context.log.debug('Using existing lambda for {}'.format(vt.target))

        python_lambda_product[vt.target] = lambda_path
        self.context.log.debug('created {}'.format(os.path.relpath(lambda_path, get_buildroot())))

        # Put a copy in distdir.
        lambda_copy = os.path.join(self.get_options().pants_distdir, os.path.basename(lambda_path))
        safe_mkdir_for(lambda_copy)
        atomic_copy(lambda_path, lambda_copy)
        self.context.log.info('created lambda {}'.format(
          os.path.relpath(lambda_copy, get_buildroot())))

  def _create_lambda(self, target, lambda_path):
    orig_pex_path = self._get_pex_path(target.binary)
    with temporary_dir() as tmpdir:
      # lambdex modifies the pex in-place, so we operate on a copy.
      tmp_lambda_path = os.path.join(tmpdir, os.path.basename(lambda_path))
      shutil.copy(orig_pex_path, tmp_lambda_path)
      lambdex = self.context.products.get_data(LambdexPrep.tool_instance_cls)
      workunit_factory = functools.partial(self.context.new_workunit,
                                           name='run-lambdex',
                                           labels=[WorkUnitLabel.TOOL])
      cmdline, exit_code = lambdex.run(workunit_factory,
                                       ['build', '-e', target.handler, tmp_lambda_path])
      if exit_code != 0:
        raise TaskError('{} ... exited non-zero ({}).'.format(cmdline, exit_code),
                        exit_code=exit_code)
      shutil.move(tmp_lambda_path, lambda_path)
    return lambda_path

  # TODO(benjy): Switch python_binary_create to use data products, and get rid of this wrinkle
  # here and in python_bundle.py.
  def _get_pex_path(self, binary_tgt):
    pex_archives = self.context.products.get('pex_archives')
    paths = []
    for basedir, filenames in pex_archives.get(binary_tgt).items():
      for filename in filenames:
        paths.append(os.path.join(basedir, filename))
    if len(paths) != 1:
      raise TaskError('Expected one binary but found: {}'.format(', '.join(sorted(paths))))
    return paths[0]
