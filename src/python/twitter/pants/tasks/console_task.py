# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import sys

from twitter.pants.tasks import Task

__author__ = 'Dave Buchfuhrer'

class ConsoleTask(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("sep"), dest="console_%s_separator" % cls.__name__,
                            default='\\n', help="String to use to separate results.")

  def __init__(self, context, outstream=sys.stdout):
    Task.__init__(self, context)
    separator_option = "console_%s_separator" % self.__class__.__name__
    self._console_separator = getattr(context.options, separator_option).decode('string-escape')
    self._outstream = outstream

  def execute(self, targets):
    try:
      for value in self.console_output(targets):
        self._outstream.write(str(value))
        self._outstream.write(self._console_separator)
    finally:
      self._outstream.flush()

  def console_output(self, targets):
    raise NotImplementedError('console_output must be implemented by subclasses of ConsoleTask')
