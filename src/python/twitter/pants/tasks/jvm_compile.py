from twitter.pants.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from twitter.pants.tasks.nailgun_task import NailgunTask


class JvmCompile(NailgunTask):
  _language = None  # Subclasses must set.

  @staticmethod
  def setup_parser(subcls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('check-missing-deps'),
                            mkflag('check-missing-deps', negate=True),
                            dest=subcls._language+'_check_missing_deps',
                            action='callback', callback=mkflag.set_bool,
                            default=True,
                            help='[%default] Error on missing dependencies in ' +  subcls._language + 'code. '
                                 'Reports actual dependencies A -> B where there is no '
                                 'transitive BUILD file dependency path from A to B.')

    option_group.add_option(mkflag('warn-missing-direct-deps'),
                            mkflag('warn-missing-direct-deps', negate=True),
                            dest=subcls._language+'_warn_missing_direct_deps',
                            action='callback', callback=mkflag.set_bool,
                            default=False,
                            help='[%default] Warn for missing direct dependencies in ' + subcls._language + ' code. '
                                 'Reports actual dependencies A -> B where there is no direct '
                                 'BUILD file dependency path from A to B. '
                                 'This is a very strict check, as in practice it is common to rely on '
                                 'transitive, non-direct dependencies, e.g., due to type inference or when '
                                 'the main target in a BUILD file is modified to depend on other targets in '
                                 'the same BUILD file as an implementation detail.')

    option_group.add_option(mkflag('warn-unnecessary-deps'),
                            mkflag('warn-unnecessary-deps', negate=True),
                            dest=subcls._language+'_warn_unnecessary_deps',
                            action='callback', callback=mkflag.set_bool,
                            default=False,
                            help='[%default] Warn for declared dependencies in ' +  subcls._language + ' code '
                                 'that are not needed. This is a very strict check. For example, '
                                 'generated code will often legitimately have BUILD dependencies that '
                                 'are unused in practice.')

  def __init__(self, context, workdir):
    NailgunTask.__init__(self, context, workdir=workdir)

    # Set up dep checking if needed.
    def get_lang_specific_option(opt):
      full_opt_name = self.language() + '_' + opt
      return getattr(context.options, full_opt_name, None)

    check_missing_deps = get_lang_specific_option('check_missing_deps')
    warn_missing_direct_deps = get_lang_specific_option('warn_missing_direct_deps')
    warn_unnecessary_deps = get_lang_specific_option('warn_unnecessary_deps')

    if check_missing_deps or warn_missing_direct_deps or warn_unnecessary_deps:
      # Must init it here, so it can set requirements on the context.
      self._dep_analyzer = JvmDependencyAnalyzer(self.context, check_missing_deps,
                                                 warn_missing_direct_deps, warn_unnecessary_deps)
    else:
      self._dep_analyzer = None

  def language(self):
    return self._language

  def check_for_missing_dependencies(self, srcs, actual_deps):
    if self._dep_analyzer:
      with self.context.new_workunit(name='find-missing-dependencies'):
        self._dep_analyzer.check(srcs, actual_deps)
