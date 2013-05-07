import getpass
import os
import re
import socket
import time

from twitter.common.dirutil import safe_mkdir_for
from twitter.pants import get_scm, get_buildroot


class RunInfo(object):
  """A little plaintext file containing very basic info about a pants run.

  Can only be appended to, never edited."""
  def __init__(self, info_file):
    self._info_file = info_file
    safe_mkdir_for(self._info_file)
    self._info = {}
    if os.path.exists(self._info_file):
      with open(self._info_file, 'r') as infile:
        info = infile.read()
      for m in re.finditer("""^([^:]+):(.*)$""", info, re.MULTILINE):
        self._info[m.group(1).strip()] = m.group(2).strip()

  def path(self):
    return self._info_file

  def get_info(self, key):
    return self._info.get(key, None)

  def __getitem__(self, key):
    ret = self.get_info(key)
    if ret is None:
      raise KeyError(key)
    return ret

  def get_as_dict(self):
    return self._info.copy()

  def add_info(self, key, val):
    self.add_infos((key, val))

  def add_infos(self, *keyvals):
    with open(self._info_file, 'a') as outfile:
      for key, val in keyvals:
        key = key.strip()
        val = val.strip()
        if ':' in key:
          raise Exception, 'info key must not contain a colon'
        outfile.write('%s: %s\n' % (key, val))
        self._info[key] = val

  def add_basic_info(self, run_id, timestamp):
    """A helper function to add basic build info."""
    datetime = time.strftime('%A %b %d, %Y %H:%M:%S', time.localtime(timestamp))
    user = getpass.getuser()
    machine = socket.gethostname()
    path = get_buildroot()
    self.add_infos(('id', run_id), ('timestamp', timestamp), ('datetime', datetime),
                   ('user', user), ('machine', machine), ('path', path))

  def add_scm_info(self):
    """A helper function to add SCM-related info."""
    scm = get_scm()
    if scm:
      revision = scm.commit_id
      tag = scm.tag_name or 'none'
      branch = scm.branch_name or revision
    else:
      revision, tag, branch = 'none', 'none', 'none'
    self.add_infos(('revision', revision), ('tag', tag), ('branch', branch))
