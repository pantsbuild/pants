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

from twitter.pants.base import Target

class Credentials(Target):
  """Supplies credentials for a maven repository on demand."""

  def __init__(self, name, username=None, password=None,
               exclusives=None):
    """
      :name The name of these credentials
      :username Either a constant username value or else a callable that can fetch one
      :password Either a constant password value or else a callable that can fetch one
    """
    Target.__init__(self, name, exclusives=exclusives)
    self._username = username if callable(username) else lambda: username
    self._password = password if callable(password) else lambda: password

  def username(self):
    """Returns the username in java system property argument form."""
    return self._username()

  def password(self):
    """Returns the password in java system property argument form."""
    return self._password()
