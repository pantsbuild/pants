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


class manual(object):
  """Annotate things that should appear in generated documents"""

  @staticmethod
  def builddict(tags=[]):
    """Decorator to mark something that belongs in the BUILD Dictionary doc.

    Use it on a function to mention the function. Use it on a class to
    mention the class; use it on a class' method to mention that method
    within the class' doc. (Default behavior uses the constructor but
    ignores methods. You want to decorate methods that are kosher for
    BUILD files.)

    tags: E.g., tags=["python"] means This thingy should appear in the
          Python section"
    """
    def builddictdecorator(funcorclass):
      funcorclass.builddictdict = {"tags": tags}
      return funcorclass
    return builddictdecorator


def get_builddict_info(funcorclass):
  """Return None if arg doesn't belong in BUILD dictionary, else something"""
  if hasattr(funcorclass, "builddictdict"):
    return getattr(funcorclass, "builddictdict")
  else:
    return None
