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

  @staticmethod
  def _is_thrift(target):
    return target.is_thrift

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ThriftLinter, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('ignore-errors'), dest='thrift_linter_ignore_errors',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Ignore lint errors')

  @classmethod
  def product_types(cls):
    # Fake product. The linter produces warnings and errors.
    return ['thrift-linter']


  def __init__(self, context, workdir):
    super(ThriftLinter, self).__init__(context, workdir)

    self._bootstrap_key = 'scrooge-linter'

    bootstrap_tools = context.config.getlist('scrooge-linter', 'bootstrap-tools',
                                             default=[':scrooge-linter'])
    self.register_jvm_tool(self._bootstrap_key, bootstrap_tools)

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    # This is needed to resolve jars before running.
    round_manager.require_data('ivy_jar_products')
    # round_manager.require_data('exclusives_groups')

  def lint(self, path):
    self.context.log.debug("Linting %s" % path)

    classpath = self.tool_classpath(self._bootstrap_key)
    returncode = self.runjava(classpath=classpath,
                              main='com.twitter.scrooge.linter.Main',
                              args=[path],
                              workunit_labels=[WorkUnit.COMPILER],  # to let stdout/err through.
                              )
    if returncode != 0:
      if self.context.options.thrift_linter_ignore_errors:
        self.context.log.warn("Ignoring thrift linter errors in %s\n" % path)
      else:
        raise TaskError('Lint errors in %s.' % path)

  def execute(self):
    thrift_targets = self.context.targets(self._is_thrift)
    for target in thrift_targets:
      for path in target.sources_relative_to_buildroot():
        self.lint(path)

