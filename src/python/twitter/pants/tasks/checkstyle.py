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

__author__ = 'John Sirois'

import os

from twitter.common import log
from twitter.common.dirutil import safe_open
from twitter.pants import is_codegen, is_java
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.nailgun_task import NailgunTask


CHECKSTYLE_MAIN = 'com.puppycrawl.tools.checkstyle.Main'


class Checkstyle(NailgunTask):
  @staticmethod
  def _is_checked(target):
    return is_java(target) and not is_codegen(target)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True),
                            dest="checkstyle_skip", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Skip checkstyle.")

  def __init__(self, context):
    self._profile = context.config.get('checkstyle', 'profile')
    workdir = context.config.get('checkstyle', 'nailgun_dir')
    NailgunTask.__init__(self, context, workdir=workdir)

    self._configuration_file = context.config.get('checkstyle', 'configuration')

    self._work_dir = context.config.get('checkstyle', 'workdir')
    self._properties = context.config.getdict('checkstyle', 'properties')
    self._confs = context.config.getlist('checkstyle', 'confs')

  def execute(self, targets):
    if not self.context.options.checkstyle_skip:
      with self.invalidated(filter(Checkstyle._is_checked, targets)) as invalidated:
        sources = self.calculate_sources(invalidated.invalid_targets())
        if sources:
          result = self.checkstyle(sources)
          if result != 0:
            raise TaskError('%s returned %d' % (CHECKSTYLE_MAIN, result))

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update([os.path.join(target.target_base, source)
                      for source in target.sources if source.endswith('.java')])
    return sources

  def checkstyle(self, sources):
    classpath = nailgun_profile_classpath(self, self._profile)
    with self.context.state('classpath', []) as cp:
      classpath.extend(jar for conf, jar in cp if conf in self._confs)

    args = [
      '-c', self._configuration_file,
      '-f', 'plain'
    ]

    if self._properties:
      properties_file = os.path.join(self._work_dir, 'checkstyle.properties')
      with safe_open(properties_file, 'w') as pf:
        for k, v in self._properties.items():
          pf.write('%s=%s\n' % (k, v))
      args.extend(['-p', properties_file])

    args.extend(sources)
    log.debug('Executing: %s %s' % (CHECKSTYLE_MAIN, ' '.join(args)))
    return self.runjava(CHECKSTYLE_MAIN, classpath=classpath, args=args)
