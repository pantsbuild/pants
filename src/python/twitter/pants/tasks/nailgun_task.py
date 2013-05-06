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
import time

from twitter.pants.base.workunit import WorkUnit
from twitter.pants.ivy import profile_classpath as profile_cp
from twitter.pants.java import Distribution, SubprocessExecutor, NailgunExecutor

from . import Task, TaskError

from .java import util


class NailgunTask(Task):

  _DAEMON_OPTION_PRESENT = False

  @staticmethod
  def killall(logger=None, everywhere=False):
    """Kills all nailgun servers launched by pants in the current repo.

    Returns ``True`` if all nailguns were successfully killed, ``False`` otherwise.

    :param logger: a callable that accepts a message string describing the killed nailgun process
    :param bool everywhere: ``True`` to kill all nailguns servers launched by pants on this machine
    """
    if not NailgunExecutor.killall:
      return False
    else:
      return NailgunExecutor.killall(logger=logger, everywhere=everywhere)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    if not NailgunTask._DAEMON_OPTION_PRESENT:
      option_group.parser.add_option("--ng-daemons", "--no-ng-daemons", dest="nailgun_daemon",
                                     default=True, action="callback", callback=mkflag.set_bool,
                                     help="[%default] Use nailgun daemons to execute java tasks.")
      NailgunTask._DAEMON_OPTION_PRESENT = True

  def __init__(self, context, minimum_version=None, jdk=False):
    super(NailgunTask, self).__init__(context)

    workdir = os.path.join(context.config.get('nailgun', 'workdir'), self.__class__.__name__)

    start = time.time()
    try:
      self._dist = Distribution.cached(minimum_version=minimum_version, jdk=jdk)
      # TODO(John Sirois): Use a context timer when AWESOME-1265 gets merged.
      context.log.debug('Located java distribution in %.3fs' % (time.time() - start))
    except Distribution.Error as e:
      raise TaskError(e)

    if context.options.nailgun_daemon:
      nailgun_profile = context.config.get('nailgun', 'profile', default='nailgun')
      classpath = self.profile_classpath(nailgun_profile)
      self._java = NailgunExecutor(workdir, classpath, distribution=self._dist)
    else:
      self._java = SubprocessExecutor(self._dist)

  @property
  def java_executor(self):
    """Returns the active java executor in use by this task."""
    return self._java

  @property
  def jvm_args(self):
    """Default jvm args the nailgun will be launched with.

    By default no special jvm args are used.  If a value for ``jvm_args`` is specified in pants.ini
    globally in the ``DEFAULT`` section or in the ``nailgun`` section, then that list will be used.
    """
    return self.context.config.getlist('nailgun', 'jvm_args', default=[])

  def runjava(self, classpath, main, args=None, jvm_args=None, workunit_name=None,
              workunit_labels=None):
    """Runs the java main using the given classpath and args.

    If --no-ng-daemons is specified then the java main is run in a freshly spawned subprocess,
    otherwise a persistent nailgun server dedicated to this Task subclass is used to speed up
    amortized run times.
    """
    try:
      return util.execute_java(classpath,
                               main,
                               args=args,
                               jvm_args=jvm_args,
                               executor=self.java_executor,
                               workunit_factory=self.context.new_workunit,
                               workunit_name=workunit_name,
                               workunit_labels=workunit_labels)
    except self._java.Error as e:
      raise TaskError(e)

  def profile_classpath(self, profile):
    # TODO(John Sirois): XXX use new jvm tool work
    """Ensures the classpath for the given profile ivy.xml is available and returns it as a list of
    paths.

    If the classpath has changed since the last check for this profile this Task's build cache is
    invalidated.

    profile: The name of the tool profile classpath to ensure.
    """
    updated, classpath = profile_cp(profile,
                                    java_executor=SubprocessExecutor(self._dist),
                                    config=self.context.config)
    if updated:
      # This is probably overly conservative - its unlikely nailgun upgrades affect cached work
      # from subclasses.
      self.invalidate()
    return classpath
