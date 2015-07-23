import os
import shutil
import subprocess

from abc import abstractmethod
from contextlib import closing

from twitter.common.lang import Compatibility

from pants.backend.core.tasks.task import Task
from pants.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree

from pants.contrib.npm_module.tasks.resource_preprocessors.npm_module_subsystem import NpmModuleSubsystem

if Compatibility.PY3:
  from urllib.request import urlopen
else:
  from urllib2 import urlopen


class NpmModuleBase(Task):
  """
    Class to downloads the module tar.gz from science-binaries and runs the
    binary specified in bin_file
  """

  class NpmModuleError(Exception):
    """Indicates a NpmModule download has failed."""

    def __init__(self, *args, **kwargs):
      super(NpmModule.NpmModuleError, self).__init__(*args, **kwargs)

  @classmethod
  def global_subsystems(cls):
    return super(NpmModuleBase, cls).global_subsystems() + (NpmModuleSubsystem, )

  @classmethod
  def register_options(cls, register):
    super(NpmModuleBase, cls).register_options(register)
    register('--supportdir', default='bin', help='Look for binaries in this directory')
    register('--version', default=cls.MODULE_VERSION, help='Look for binaries in this directory')

  def __init__(self, *args, **kwargs):
    super(NpmModuleBase, self).__init__(*args, **kwargs)
    self._cachedir = None
    self._chdir = None
    self._skip_bootstrap = NpmModuleSubsystem.global_instance().get_options().skip_bootstrap
    self._force_get = NpmModuleSubsystem.global_instance().get_options().force_get
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
    return os.path.join(self.binary, self.MODULE_EXECUTABLE)

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
      self._chdir = self.binary
    return self._chdir

  def _get_npm_module(self):
    safe_mkdir(self.binary)

  def execute_npm_module(self, target):
    self.binary = BinaryUtil.from_options(self.get_options()).select_binary(self.module_name)
    with pushd(self.chdir):
      files = self.execute_cmd(target)
      return files

  @abstractmethod
  def execute_cmd(self, target):
    """Runs the npm module command."""
