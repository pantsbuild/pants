import os
import shutil
import subprocess

from abc import abstractmethod
from contextlib import closing

from twitter.common.lang import Compatibility

from pants.backend.core.tasks.task import Task
from pants.fs.archive import TGZ
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree

if Compatibility.PY3:
  from urllib.request import urlopen
else:
  from urllib2 import urlopen


class NpmModuleBase(Task):
  """
    Class to downloads the module tar.gz from science-binaries and runs the
    binary specified in bin_file
  """
  SCIENCE_BINARIES = 'https://science-binaries.local.twitter.com/home/third_party/modules'

  class NpmModuleError(Exception):
    """Indicates a NpmModule download has failed."""

    def __init__(self, *args, **kwargs):
      super(NpmModule.NpmModuleError, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(NpmModuleBase, cls).register_options(register)
    register('--force-get', default=False, action='store_true',
             help='Force downloading of npm module')
    register('--skip-bootstrap', default=False, action='store_true',
             help='Skip bootstrapping of tool')

  def __init__(self, *args, **kwargs):
    super(NpmModuleBase, self).__init__(*args, **kwargs)
    self._cachedir = None
    self._chdir = None
    self._skip_bootstrap = self.get_options().skip_bootstrap
    self._force_get = self.get_options().force_get
    self.task_name = (self.__class__.__name__).lower()

  @property
  def skip_bootstrap(self):
    return self._skip_bootstrap

  @property
  def force_get(self):
    return self._force_get

  @property
  def module_name(self):
    """Name of the NPM Module"""
    return self.MODULE_NAME

  @property
  def module_version(self):
    """Version of the NPM Module"""
    return self.MODULE_VERSION

  @property
  def bin_path(self):
    """Executable file for the Module"""
    return os.path.join(self.cachedir, self.MODULE_EXECUTABLE)

  @property
  def cachedir(self):
    """Directory where module is cached"""
    if not self._cachedir:
      self._cachedir = os.path.join(self.workdir, self.module_name, self.module_version)
    return self._cachedir

  @property
  def chdir(self):
    """This property specifies the directory for the executing the command."""
    if not self._chdir:
      self._chdir = self.cachedir
    return self._chdir

  def _bootstrap_or_get_module(self):
    get_module = True
    if not self.force_get:
      if os.path.exists(self.cachedir) and not self._skip_bootstrap:
        try:
          # This is to safe gaurd against case where the workdir exists, But its corrupt.
          if subprocess.call([self.bin_path, '-v']) == 1:
            get_module = False
        except OSError:
          get_module = True
      elif os.path.exists(self.cachedir):
        get_module = False
      else:
        get_module = True
    if get_module:
      self._get_npm_module()

  def _get_npm_module(self):
    safe_mkdir(self.cachedir)
    url = ('%s/%s/%s/%s' % (NpmModuleBase.SCIENCE_BINARIES, self.module_name, self.module_version,
                            '%s-%s.tar' % (self.module_name, self.module_version)))
    try:
      with closing(urlopen(url, timeout=5)) as url_fp:
        with temporary_dir(cleanup=False) as staging_dir:
          stage_tgz = os.path.join(staging_dir, 'stage.tgz')
          with safe_open(stage_tgz, 'w') as tmp_fp:
            tmp_fp.write(url_fp.read())
          stage_root = os.path.join(staging_dir, 'stage')
          TGZ.extract(stage_tgz, stage_root)
          safe_rmtree(self.cachedir)
          shutil.move(stage_root, self.cachedir)
    except IOError as e:
      NpmModuleBase.NpmModuleError('Failed to pull module %s due to %s' % (url, e))

  def execute_npm_module(self, target):
    self._bootstrap_or_get_module()
    with pushd(self.chdir):
      files = self.execute_cmd(target)
      return files

  @abstractmethod
  def execute_cmd(self, target):
    """Runs the npm module command."""
