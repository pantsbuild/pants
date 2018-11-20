# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os.path
import sys
from builtins import str

from pants.engine.fs import Digest, MergedDirectories, Snapshot, UrlToFetch
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import rule
from pants.engine.selectors import Get, Select
from pants.rules.core.core_test_model import Status, TestResult


# This class currently exists so that other rules could be added which turned a HydratedTarget into
# a language-specific test result, and could be installed alongside run_python_test.
# Hopefully https://github.com/pantsbuild/pants/issues/4535 should help resolve this.
class PyTestResult(TestResult):
  pass


# TODO: Support deps
# TODO: Support resources
@rule(PyTestResult, [Select(HydratedTarget)])
def run_python_test(target):

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  pex_snapshot = yield Get(Snapshot, UrlToFetch("https://github.com/pantsbuild/pex/releases/download/v1.5.2/pex27",
                                                Digest('8053a79a5e9c2e6e9ace3999666c9df910d6289555853210c1bbbfa799c3ecda', 1757011)))

  # TODO: This should be configurable, both with interpreter constraints, and for remote execution.
  python_binary = sys.executable

  argv = [
    './{}'.format(pex_snapshot.files[0].path),
    '-e', 'pytest:main',
    '--python', python_binary,
    # TODO: This is non-hermetic because pytest will be resolved on the fly by pex27, where it should be hermetically provided in some way.
    # We should probably also specify a specific version.
    'pytest',
  ]

  merged_input_files = yield Get(
    Digest,
    MergedDirectories,
    MergedDirectories(directories=(target.adaptor.sources.snapshot.directory_digest, pex_snapshot.directory_digest)),
  )

  request = ExecuteProcessRequest(
    argv=tuple(argv),
    input_files=merged_input_files,
    description='Run pytest for {}'.format(target.address.reference()),
    # TODO: This should not be necessary
    env={'PATH': os.path.dirname(python_binary)}
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  # TODO: Do something with stderr?
  status = Status.SUCCESS if result.exit_code == 0 else Status.FAILURE

  yield PyTestResult(status=status, stdout=str(result.stdout))
