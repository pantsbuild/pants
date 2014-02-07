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

import os.path
import re

from twitter.pants.base.config import Config
from twitter.pants.process.xargs import Xargs
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.nailgun_task import NailgunTask


class Scalastyle(NailgunTask):
  """Checks scala source files to ensure they're stylish.

  Scalastyle is configured via the 'scalastyle' pants.ini section.

  * ``config`` - Required path of the scalastyle configuration file.
  * ``excludes`` - Optional path of an excludes file that contains
    lines of regular expressions used to exclude matching files
    from style checks. File names matched against these regular
    expressions are relative to the repository root
    (e.g.: com/twitter/mybird/MyBird.scala).
  """

  _CONFIG_SECTION = 'scalastyle'
  _MAIN = 'org.scalastyle.Main'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True),
                            dest="scalastyle_skip", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Skip scalastyle.")

  def __init__(self, context):
    NailgunTask.__init__(self, context)
    self._scalastyle_config = self.context.config.get_required(
      Scalastyle._CONFIG_SECTION, 'config')
    if not os.path.exists(self._scalastyle_config):
      raise Config.ConfigError(
          'Scalastyle config file does not exist: %s' % self._scalastyle_config)

    excludes_file = self.context.config.get(Scalastyle._CONFIG_SECTION, 'excludes')
    self._excludes = set()
    if excludes_file:
      if not os.path.exists(excludes_file):
        raise Config.ConfigError('Scalastyle excludes file does not exist: %s' % excludes_file)
      self.context.log.debug('Using scalastyle excludes file %s' % excludes_file)
      with open(excludes_file) as fh:
        for pattern in fh.readlines():
          self._excludes.add(re.compile(pattern.strip()))

    self._scalastyle_bootstrap_key = 'scalastyle'
    self.register_jvm_tool(self._scalastyle_bootstrap_key, [':scalastyle'])

  def execute(self, targets):
    if self.context.options.scalastyle_skip:
      self.context.log.debug('Skipping checkstyle.')
      return

    check_targets = list()
    for target in targets:
      for tgt in target.resolve():
        if tgt.has_sources('.scala'):
          check_targets.append(tgt)

    def filter_excludes(filename):
      if self._excludes:
        for exclude in self._excludes:
          if exclude.match(filename):
            return False
      return True

    scala_sources = list()
    for target in check_targets:
      def collect(filename):
        if filename.endswith('.scala'):
          scala_sources.append(os.path.join(target.target_base, filename))
      map(collect, filter(filter_excludes, target.sources))

    if scala_sources:
      def call(srcs):
        cp = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._scalastyle_bootstrap_key)
        return self.runjava(classpath=cp,
                            main=Scalastyle._MAIN,
                            args=['-c', self._scalastyle_config] + srcs)
      result = Xargs(call).execute(scala_sources)
      if result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (Scalastyle._MAIN, result))
