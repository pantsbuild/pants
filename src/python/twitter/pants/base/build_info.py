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

import getpass
import socket

from collections import namedtuple
from time import strftime, localtime

from .build_environment import get_buildroot, get_scm

BuildInfo = namedtuple('BuildInfo', 'date time timestamp branch tag sha user machine path')


def get_build_info(scm=None):
  """Calculates the current BuildInfo using the supplied scm or else the globally configured one
  if any.
  """
  now = localtime()
  buildroot = get_buildroot()

  scm = scm or get_scm()
  revision = scm.commit_id if scm else 'unknown'
  tag = (scm.tag_name or 'none') if scm else 'unknown'
  branchname = (scm.branch_name or revision) if scm else 'unknown'

  return BuildInfo(
      date=strftime('%A %b %d, %Y', now),
      time=strftime('%H:%M:%S', now),
      timestamp=strftime('%m.%d.%Y %H:%M', now),
      branch=branchname,
      tag=tag,
      sha=revision,
      user=getpass.getuser(),
      machine=socket.gethostname(),
      path=buildroot)
