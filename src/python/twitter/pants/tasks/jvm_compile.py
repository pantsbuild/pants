from twitter.pants.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from twitter.pants.tasks.nailgun_task import NailgunTask


class JvmCompile(NailgunTask):
  _language = None  # Subclasses must set.

  @staticmethod
  def setup_parser(subcls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('missing-deps'),
                            dest=subcls._language+'_missing_deps',
                            choices=['off', 'warn', 'fatal'],
                            # TODO(Benjy): Change to fatal after we iron out all outstanding missing deps.
                            default='warn',
                            help='[%default] One of off, warn, fatal. '
                                 'Check for missing dependencies in ' +  subcls._language + 'code. '
                                 'Reports actual dependencies A -> B where there is no '
                                 'transitive BUILD file dependency path from A to B.'
                                 'If fatal, missing deps are treated as a build error.')

    option_group.add_option(mkflag('missing-direct-deps'),
                            dest=subcls._language+'_missing_direct_deps',
                            choices=['off', 'warn', 'fatal'],
                            default='off',
                            help='[%default] One of off, warn, fatal. '
                                 'Check for missing direct dependencies in ' + subcls._language + ' code. '
                                 'Reports actual dependencies A -> B where there is no direct '
                                 'BUILD file dependency path from A to B. '
                                 'This is a very strict check, as in practice it is common to rely on '
                                 'transitive, non-direct dependencies, e.g., due to type inference or when '
                                 'the main target in a BUILD file is modified to depend on other targets in '
                                 'the same BUILD file as an implementation detail. It may still be useful '
                                 'to set it to fatal temorarily, to detect these.')

    option_group.add_option(mkflag('unnecessary-deps'),
                            dest=subcls._language+'_unnecessary_deps',
                            choices=['off', 'warn', 'fatal'],
                            default='off',
                            help='[%default] One of off, warn, fatal. '
                                 'Check for declared dependencies in ' +  subcls._language + ' code '
                                 'that are not needed. This is a very strict check. For example, '
                                 'generated code will often legitimately have BUILD dependencies that '
                                 'are unused in practice.')

  def __init__(self, context, workdir):
    NailgunTask.__init__(self, context, workdir=workdir)

    # Set up dep checking if needed.
    def get_lang_specific_option(opt):
      full_opt_name = self.language() + '_' + opt
      return getattr(context.options, full_opt_name, None)

    def munge_flag(flag):
      return None if flag == 'off' else flag
    check_missing_deps = munge_flag(get_lang_specific_option('missing_deps'))
    check_missing_direct_deps = munge_flag(get_lang_specific_option('missing_direct_deps'))
    check_unnecessary_deps = munge_flag(get_lang_specific_option('unnecessary_deps'))

    if check_missing_deps or check_missing_direct_deps or check_unnecessary_deps:
      # Must init it here, so it can set requirements on the context.
      self._dep_analyzer = JvmDependencyAnalyzer(self.context,
                                                 check_missing_deps,
                                                 check_missing_direct_deps,
                                                 check_unnecessary_deps)
    else:
      self._dep_analyzer = None

  def language(self):
    return self._language

  def check_for_missing_dependencies(self, srcs, actual_deps):
    if self._dep_analyzer:
      with self.context.new_workunit(name='find-missing-dependencies'):
        self._dep_analyzer.check(srcs, actual_deps)
