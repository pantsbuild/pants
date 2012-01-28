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

import os
import sys
import subprocess

from twitter.common.collections import OrderedSet
from twitter.common.python import PythonLauncher
from twitter.pants.python.python_chroot import PythonChroot
from twitter.pants.targets import PythonEgg

try:
  import pylint
  _HAVE_PYLINT = True
except ImportError:
  _HAVE_PYLINT = False

class PythonLintBuilder(object):
  def __init__(self, targets, args, root_dir):
    self.targets = targets
    self.args = args
    self.root_dir = root_dir

  def run(self):
    if not _HAVE_PYLINT:
      print >> sys.stderr, 'ERROR: Pylint not found!  Skipping.'
      return 1
    return self._run_lints(self.targets, self.args)

  def _run_lint(self, target, args):
    chroot = PythonChroot(target, self.root_dir)
    launcher = PythonLauncher(chroot.dump().path())

    interpreter_args = ['-m', 'pylint.lint',
      '--rcfile=%s' % os.path.join(self.root_dir, 'build-support', 'pylint', 'pylint.rc')]
    if args:
      interpreter_args.extend(args)
    sources = OrderedSet([])
    if not isinstance(target, PythonEgg):
      target.walk(lambda trg: sources.update(trg.sources),
                  lambda trg: not isinstance(trg, PythonEgg))
    launcher.run(
      interpreter_args=interpreter_args,
      args=list(sources),
      extra_deps=sys.path, # TODO(wickman) Extract only the pylint dependencies from sys.path
      with_chroot=True)

  def _run_lints(self, targets, args):
    for target in targets:
      self._run_lint(target, args)
    return 0
