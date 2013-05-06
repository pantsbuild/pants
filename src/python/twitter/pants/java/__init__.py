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

from .distribution import Distribution
from .executor import Executor, SubprocessExecutor
from .nailgun_client import NailgunClient
from .nailgun_executor import NailgunExecutor


def runjava(classpath, main, args=None, jvm_args=None, **subprocess_kwargs):
  """Spawns a java process with the supplied configuration and returns its exit code.

  Any extra kwargs are passed through to ``subprocess.Popen`` to control the spawned process
  environment further,

  :param list classpath: the classpath for the java program
  :param string main: the fully qualified class name of the java program's entry point
  :param list args: an optional sequence of args to pass to the java program
  :param list jvm_args: an optional sequence of args for the underlying jvm
  """
  java = SubprocessExecutor()
  return java.spawn(classpath, main, args=args, jvm_args=jvm_args, **subprocess_kwargs).wait()


__all__ = (
    'runjava',
    'Distribution',
    'Executor',
    'NailgunClient',
    'NailgunExecutor',
    'SubprocessExecutor',
)
