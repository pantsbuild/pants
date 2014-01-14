# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

import os
import sys

from twitter.common.collections import OrderedSet
from twitter.common.python.pex import PEX

from twitter.pants.base import Target, Address
from twitter.pants.python.python_chroot import PythonChroot

try:
  import pylint
  _HAVE_PYLINT = True
except ImportError:
  _HAVE_PYLINT = False

class PythonLintBuilder(object):
  def __init__(self, targets, args, root_dir, conn_timeout=None):
    self.targets = targets
    self.args = args
    self.root_dir = root_dir
    self._conn_timeout = conn_timeout

  def run(self):
    if not _HAVE_PYLINT:
      print('ERROR: Pylint not found!  Skipping.', file=sys.stderr)
      return 1
    return self._run_lints(self.targets, self.args)

  def _run_lint(self, target, args):
    chroot = PythonChroot(target, self.root_dir, extra_targets=[
      Target.get(Address.parse(self.root_dir, '3rdparty/python:pylint'))],
      conn_timeout=self._conn_timeout)
    chroot.builder.info.ignore_errors = True
    builder = chroot.dump()
    builder.info.entry_point = 'pylint.lint'
    builder.freeze()

    interpreter_args = [
      '--rcfile=%s' % os.path.join(self.root_dir, 'build-support', 'pylint', 'pylint.rc')]
    interpreter_args.extend(args or [])
    sources = OrderedSet([])
    target.walk(lambda trg: sources.update(
      trg.sources if hasattr(trg, 'sources') and trg.sources is not None else []))
    pex = PEX(builder.path())
    pex.run(args=interpreter_args + list(sources), with_chroot=True)

  def _run_lints(self, targets, args):
    for target in targets:
      self._run_lint(target, args)
    return 0
