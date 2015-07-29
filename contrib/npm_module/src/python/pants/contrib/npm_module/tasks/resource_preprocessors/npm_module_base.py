import os
import shutil

from abc import abstractmethod

from pants.backend.core.tasks.task import Task
from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree

from twitter.common.util.command_util import CommandUtil

class NpmModuleBase(Task):
  """
    Class to downloads the module tar.gz from hosted binaries and runs the
    binary specified in bin_file
  """

  NODE_VERSION = '0.12.7'
  NODE_WORKDIR = 'node'
  NODE_EXECUTABLE = 'bin'

  class NpmModuleError(Exception):
    """Indicates a NpmModule download has failed."""

    def __init__(self, *args, **kwargs):
      super(NpmModuleBase.NpmModuleError, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(NpmModuleBase, cls).register_options(register)
    register('--supportdir', default=os.path.join('bin', 'node'),
             help='Look for binaries in this directory')
    register('--version', default=cls.NODE_VERSION, help='Version')

  def __init__(self, *args, **kwargs):
    super(NpmModuleBase, self).__init__(*args, **kwargs)
    self._module_name = self.MODULE_NAME
    self._module_version = self.MODULE_VERSION
    self._chdir = None
    self._cachedir = None
    self._node_cachedir = None

  @property
  def skip_bootstrap(self):
    return self._skip_bootstrap

  @property
  def force_get(self):
    return self._force_get

  @property
  def module_name(self):
    """Name of the NPM Module"""
    return self._module_name

  @property
  def module_version(self):
    """Name of the NPM Module"""
    return self._module_version

  @property
  def node_cachedir(self):
    """Directory where module is cached"""
    if not self._node_cachedir:
      self._node_cachedir = os.path.join(self.context.options.for_global_scope().pants_workdir,
                                         NpmModuleBase.NODE_WORKDIR, NpmModuleBase.NODE_VERSION)
    return self._node_cachedir

  @property
  def cachedir(self):
    """Directory where module is cached"""
    if not self._cachedir:
      self._cachedir = os.path.join(self.node_cachedir, NpmModuleBase.NODE_EXECUTABLE,
                                    'node_modules', self.module_name)
    return self._cachedir

  @property
  def chdir(self):
    """This property specifies the directory for the executing the command."""
    if not self._chdir:
      self._chdir = self.cachedir
    return self._chdir

  def _get_npm_module(self):
    safe_mkdir(self.binary)

  def _bootstrap_node(self):
    try:
      binary_util = BinaryUtil.Factory.create()
      node_path = binary_util.select_binary(self.get_options().supportdir,
                                            self.get_options().version,
                                            'node-v{0}.tar.gz'.format(NpmModuleBase.NODE_VERSION),
                                            write_mode='w')
      with temporary_dir(cleanup=False) as staging_dir:
        stage_root = os.path.join(staging_dir, 'stage')
        TGZ.extract(node_path, stage_root, 'r:gz')
        safe_rmtree(self.node_cachedir)
        self.context.log.debug("Moving %s to %s" %(stage_root, self.node_cachedir))
        shutil.move(stage_root, self.node_cachedir)
    except IOError as e:
      NpmModuleBase.NpmModuleError('Failed to install fetch node due to {0}'.format(e))

  def _install_module(self):
    self.context.log.debug('Installing npm module {0}'.format(self._module_name))
    CommandUtil.execute_suppress_stdout(['./npm', 'install', self.module_name])

  def execute_npm_module(self, target):
    if not os.path.exists(self.node_cachedir):
      self._bootstrap_node()
    if not os.path.exists(self.cachedir):
      safe_mkdir(self.cachedir)
      with pushd(os.path.join(self.node_cachedir, NpmModuleBase.NODE_EXECUTABLE)):
        self._install_module()
    with pushd(self.chdir):
      node_environ = os.environ.copy()
      node_environ['PATH'] = os.pathsep.join([os.path.join(self.node_cachedir,
                                                           NpmModuleBase.NODE_EXECUTABLE),
                                              node_environ['PATH']])
      files = self.execute_cmd(target, node_environ)
      return files

  @abstractmethod
  def execute_cmd(self, target):
    """Runs the npm module command."""
