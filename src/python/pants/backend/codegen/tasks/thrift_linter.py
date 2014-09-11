from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask

class ThriftLinter(NailgunTask, JvmToolTaskMixin):
  """Print linter warnings for thrift files.
  """

  # Thrift linter vs scrooge linter:
  # thrift linter is the function.
  # scrooge linter is the implementation detail.
  _CONFIG_SECTION = 'scrooge-linter'

  IGNORE_ERRORS_DEFAULT = True

  @staticmethod
  def _is_thrift(target):
    return target.is_thrift

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ThriftLinter, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option("--thrift-linter-strict", "--no-thrift-linter-strict",
                            dest='thrift_linter_strict',
                            default=None,
                            action="callback", callback=mkflag.set_bool,
                            help='[%default] Ignore lint errors')

  @classmethod
  def product_types(cls):
    # Set dependency. Gen depends on linter.
    return ['thrift-linter']


  def __init__(self, *args, **kwargs):
    super(ThriftLinter, self).__init__(*args, **kwargs)

    self._bootstrap_key = 'scrooge-linter'

    bootstrap_tools = self.context.config.getlist('scrooge-linter', 'bootstrap-tools',
                                                  default=[':scrooge-linter'])
    self.register_jvm_tool(self._bootstrap_key, bootstrap_tools)

    print('Testing config reading', self.context.config.get('scrooge-linter', 'ignore-errors',
                                                            default=False))

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    # Linter depends on ivy running before it.
    round_manager.require_data('ivy_imports')

  def getIgnoreErrorsConfigValue(self):
    return self.context.config.get('scrooge-linter', 'ignore-errors',
                                   default=ThriftLinter.IGNORE_ERRORS_DEFAULT)

  def ignoreErrors(self):
    # Sometimes options don't have the thrift_linter_ignore_errors attribute
    # (when linter is called as a dependency. Not sure why/how to fix this).
    return getattr(self.context.options, 'thrift_linter_ignore_errors',
                   self.getIgnoreErrorsConfigValue())

  def lint(self, path):
    self.context.log.debug("Linting %s" % path)

    print(55, getattr(self.context.options, 'thrift_linter_strict', None))

    classpath = self.tool_classpath(self._bootstrap_key)
    args = [path, '--verbose']
    if self.ignoreErrors():
      args.append('--ignore-errors')

    # If runjava returns non-zero, this marks the workunit as a
    # FAILURE, and there is no way to wrap this here.
    returncode = self.runjava(classpath=classpath,
                              main='com.twitter.scrooge.linter.Main',
                              args=args,
                              workunit_labels=[WorkUnit.COMPILER],  # to let stdout/err through.
                              )

    if returncode != 0:
      if self.ignoreErrors():
        self.context.log.warn("Ignoring thrift linter errors in %s\n" % path)
      else:
        raise TaskError('Lint errors in %s.' % path)

  def execute(self):
    thrift_targets = self.context.targets(self._is_thrift)
    for target in thrift_targets:
      for path in target.sources_relative_to_buildroot():
        self.lint(path)
