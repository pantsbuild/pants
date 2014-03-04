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

from contextlib import closing
from StringIO import StringIO

from twitter.pants.tasks.builddictionary import assemble, BuildBuildDictionary
from twitter.pants.tasks.test_base import prepare_task, TaskTest


OUTDIR = "/tmp/dist"

sample_ini_test_1 = """
[DEFAULT]
outdir: %s
""" % OUTDIR


class BaseBuildBuildDictionaryTest(TaskTest):

  def execute_task(self, config=sample_ini_test_1):
    with closing(StringIO()) as output:
      task = prepare_task(BuildBuildDictionary, config=config)
      task.execute(())
      return output.getvalue()


class BuildBuildDictionaryTestEmpty(BaseBuildBuildDictionaryTest):

  def test_builddict_empty(self):
    """Execution should be silent."""
    # We don't care _that_ much that execution be silent. Nice if at least
    # one test executes the task and doesn't explode, tho.
    self.assertEqual('', self.execute_task())


class ExtractedContentSanityTests(BaseBuildBuildDictionaryTest):
  def test_usual_syms(self):
    usual_syms = assemble()
    usual_names = usual_syms.keys()
    self.assertTrue(len(usual_names) > 20, "Strangely few symbols found")
    for expected in ['jvm_binary', 'python_binary']:
      self.assertTrue(expected in usual_names, "Didn't find %s" % expected)
    for unexpected in ['__builtins__', 'Target']:
      self.assertTrue(unexpected not in usual_names, "Found %s" % unexpected)
