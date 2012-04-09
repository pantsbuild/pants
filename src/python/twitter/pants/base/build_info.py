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

from collections import namedtuple
import getpass
import os
import socket
import subprocess
from time import strftime, localtime

def safe_call(cmd):
  po = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  so, se = po.communicate()
  if po.returncode == 0:
    return so
  return ""

def get_build_root():
  build_root = os.path.abspath(os.getcwd())
  while not os.path.exists(os.path.join(build_root, '.git')):
    if build_root == os.path.dirname(build_root):
      break
    build_root = os.path.dirname(build_root)
  return os.path.realpath(build_root)

BuildInfo = namedtuple('BuildInfo', 'date time timestamp branch tag sha name machine path')

def get_build_info():
  buildroot = get_build_root()

  revision = safe_call(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
  tag = safe_call(['git', 'describe']).strip()
  tag = 'none' if b'cannot' in tag else tag.decode('utf-8')
  branchname = revision
  for branchname in safe_call(['git', 'branch']).splitlines():
    if branchname.startswith(b'* '):
      branchname = branchname[2:].strip().decode('utf-8')
      break

  now = localtime()
  return BuildInfo(
    date=strftime('%A %b %d, %Y', now),
    time=strftime('%H:%M:%S', now),
    timestamp=strftime('%m.%d.%Y %H:%M', now),
    branch=branchname,
    tag=tag,
    sha=revision,
    name=getpass.getuser(),
    machine=socket.gethostname(),
    path=buildroot)
