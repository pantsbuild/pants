import os
from twitter.common.dirutil import safe_rmtree, safe_mkdir
from twitter.pants.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from twitter.pants.tasks.nailgun_task import NailgunTask


class JvmCompile(NailgunTask):
  # Subclasses must set.
  _language = None
  _config_section = None

  @staticmethod
  def setup_parser(subcls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('warnings'), mkflag('warnings', negate=True),
                            dest=subcls._language+'_compile_warnings', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Compile with all configured warnings enabled.')

    option_group.add_option(mkflag('partition-size-hint'),
                            dest=subcls._language+'_partition_size_hint',
                            action='store', type='int', default=-1,
                            help='Roughly how many source files to attempt to compile together. Set to a large number ' \
                                 'to compile all sources together. Set this to 0 to compile target-by-target. ' \
                                 'Default is set in pants.ini.')

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
    concrete_class = self.__class__
    config_section = concrete_class._config_section

    def get_lang_specific_option(opt):
      full_opt_name = self.language() + '_' + opt
      return getattr(context.options, full_opt_name, None)

    # Various working directories.
    workdir = context.config.get(config_section, 'workdir')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._resources_dir = os.path.join(workdir, 'resources')
    self._analysis_dir = os.path.join(workdir, 'analysis')

    safe_mkdir(self._classes_dir)
    safe_mkdir(self._analysis_dir)

    # A temporary, but well-known, dir to munge analysis/dependency files in before caching.
    # It must be well-known so we know where to find the files when we retrieve them from the cache.
    self._analysis_tmpdir = os.path.join(self._analysis_dir, 'artifact_cache_tmpdir')

    # Compiler options.
    self._args = context.config.getlist(config_section, 'args')
    if get_lang_specific_option('compile_warnings'):
      self._args.extend(context.config.getlist(config_section, 'warning_args'))
    else:
      self._args.extend(context.config.getlist(config_section, 'no_warning_args'))

    # The rough number of source files to build in each compiler pass.
    self._partition_size_hint = get_lang_specific_option('partition_size_hint')
    if self._partition_size_hint == -1:
      self._partition_size_hint = \
        context.config.getint(config_section, 'partition_size_hint', default=1000)

    # JVM options for running the compiler.
    self._jvm_options = context.config.getlist(config_section, 'jvm_args')

    # The ivy confs for which we're building.
    self._confs = context.config.getlist(config_section, 'confs')

    # Set up dep checking if needed.
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

    self.context.products.require_data('exclusives_groups')
    self.setup_artifact_cache_from_config(config_section=config_section)

  def language(self):
    return self._language

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  def _ensure_analysis_tmpdir(self):
    # Do this lazily, so we don't trigger creation of a worker pool unless we need it.
    if not os.path.exists(self._analysis_tmpdir):
      os.makedirs(self._analysis_tmpdir)
      self.context.background_worker_pool().add_shutdown_hook(lambda: safe_rmtree(self._analysis_tmpdir))

  def check_for_missing_dependencies(self, srcs, actual_deps):
    if self._dep_analyzer:
      with self.context.new_workunit(name='find-missing-dependencies'):
        self._dep_analyzer.check(srcs, actual_deps)
