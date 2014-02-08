# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

import subprocess
import errno


class Xargs(object):
  """A subprocess execution wrapper in the spirit of the xargs command line tool.

  Specifically allows encapsulated commands to be passed very large argument lists by chunking up
  the argument lists into a minimal set and then invoking the encapsulated command against each
  chunk in turn.
  """

  @classmethod
  def subprocess(cls, cmd, **kwargs):
    """Creates an xargs engine that uses subprocess.call to execute the given cmd array with extra
    arg chunks.
    """
    def call(args):
      return subprocess.call(cmd + args, **kwargs)
    return cls(call)

  def __init__(self, cmd):
    """Creates an xargs engine that calls cmd with argument chunks.

    :param cmd: A function that can execute a command line in the form of a list of strings
      passed as its sole argument.
    """
    self._cmd = cmd

  def _split_args(self, args):
    half = len(args) // 2
    return args[:half], args[half:]

  def execute(self, args):
    """Executes the configured cmd passing args in one or more rounds xargs style.

    :param list args: Extra arguments to pass to cmd.
    """
    all_args = list(args)
    try:
      return self._cmd(all_args)
    except OSError as e:
      if errno.E2BIG == e.errno:
        args1, args2 = self._split_args(all_args)
        result = self.execute(args1)
        if result != 0:
          return result
        return self.execute(args2)
      else:
        raise e
