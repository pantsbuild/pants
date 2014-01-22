
import os
import itertools
import shutil
import uuid
from twitter.common import contextutil
from twitter.common.contextutil import open_zip
from twitter.common.dirutil import safe_rmtree, safe_mkdir
from twitter.pants import get_buildroot, Task
from twitter.pants.base import Target
from twitter.pants.base.worker_pool import Work
from twitter.pants.reporting.reporting_utils import items_to_report_element
from twitter.pants.targets import resolve_target_sources
from twitter.pants.tasks.jvm_compile.jvm_dependency_analyzer import JvmDependencyAnalyzer
from twitter.pants.tasks.nailgun_task import NailgunTask


class JvmCompile(NailgunTask):
  """A common framework for JVM compilation.

  To subclass for a specific JVM language, implement the static values and methods
  mentioned below under "Subclasses must implement".
  """

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
                            default='fatal',
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


  # Subclasses must implement.
  # --------------------------

  _language = None
  _file_suffix = None
  _config_section = None

  def create_analysis_tools(self):
    """Returns an AnalysisTools implementation.

    Subclasses must implement.
    """
    raise NotImplementedError()

  def compile(self, args, classpath, sources, classes_output_dir, analysis_file):
    """Invoke the compiler.

    Must raise TaskError on compile failure.

    Subclasses must implement."""
    raise NotImplementedError()


  # Subclasses may override.
  # ------------------------

  def extra_classpath_elements(self):
    """Extra classpath elements common to all compiler invocations.

    E.g., jars for compiler plugins.
    """
    return []

  def extra_products(self, target):
    """Any extra, out-of-band products created for a target.

    E.g., targets that produce scala compiler plugins produce an info file.
    Returns list of (basedir, prods), where prods is a list of files under basedir.
    """
    return []

  def post_process(self, relevant_targets):
    """Any extra post-execute work."""
    pass


  # Common code.
  # ------------

  @staticmethod
  def _analysis_for_target(analysis_dir, target):
    return os.path.join(analysis_dir, target.id + '.analysis')

  @staticmethod
  def _portable_analysis_for_target(analysis_dir, target):
    return JvmCompile._analysis_for_target(analysis_dir, target) + '.portable'

  def __init__(self, context, workdir):
    NailgunTask.__init__(self, context, workdir=workdir)
    concrete_class = self.__class__
    config_section = concrete_class._config_section

    def get_lang_specific_option(opt):
      full_opt_name = self._language + '_' + opt
      return getattr(context.options, full_opt_name, None)

    # Global workdir.
    self._pants_workdir = context.config.getdefault('pants_workdir')

    # Various working directories.
    workdir = context.config.get(config_section, 'workdir')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._resources_dir = os.path.join(workdir, 'resources')
    self._analysis_dir = os.path.join(workdir, 'analysis')

    safe_mkdir(self._classes_dir)
    safe_mkdir(self._analysis_dir)

    self._analysis_file = os.path.join(self._analysis_dir, 'global_analysis.valid')
    self._invalid_analysis_file = os.path.join(self._analysis_dir, 'global_analysis.invalid')

    # A temporary, but well-known, dir in which to munge analysis/dependency files in before caching.
    # It must be well-known so we know where to find the files when we retrieve them from the cache.
    self._analysis_tmpdir = os.path.join(self._analysis_dir, 'artifact_cache_tmpdir')

    # We can't create analysis tools until after construction.
    self._lazy_analysis_tools = None

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

    self._class_to_jarfile = None  # Computed lazily as needed.

    self.context.products.require_data('exclusives_groups')
    self.setup_artifact_cache_from_config(config_section=config_section)

    # Sources present in the last analysis that have since been deleted.
    # Generated lazily, so do not access directly. Call self._get_deleted_sources().
    self._deleted_sources = None

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  # TODO(benjy): Break this monstrosity up? Previous attempts to do so
  #              turned out to be more trouble than it was worth.
  def execute(self, targets):
    # TODO(benjy): Add a pre-execute phase for injecting deps into targets, so e.g.,
    # we can inject a dep on the scala runtime library and still have it ivy-resolve.

    relevant_targets = [t for t in targets if t.has_sources(self._file_suffix)]

    if not relevant_targets:
      return

    # Get the exclusives group for the targets to compile.
    # Group guarantees that they'll be a single exclusives key for them.
    egroups = self.context.products.get_data('exclusives_groups')
    group_id = egroups.get_group_key_for_target(relevant_targets[0])

    # Add resource dirs to the classpath for us and for downstream tasks.
    for conf in self._confs:
      egroups.update_compatible_classpaths(group_id, [(conf, self._resources_dir)])

    # Get the classpath generated by upstream JVM tasks (including previous calls to execute()).
    classpath = egroups.get_classpath_for_group(group_id)

    # Add any extra classpath elements.
    for conf in self._confs:
      for jar in self.extra_classpath_elements():
        classpath.insert(0, (conf, jar))

    sources_by_target = self._compute_sources_by_target(relevant_targets)

    # Invalidation check. Everything inside the with block must succeed for the
    # invalid targets to become valid.
    with self.invalidated(relevant_targets, invalidate_dependents=True,
                          partition_size_hint=self._partition_size_hint) as invalidation_check:
      if invalidation_check.invalid_vts and not self.dry_run:
        # The analysis for invalid and deleted sources is no longer valid.
        invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
        invalid_sources_by_target = {}
        for tgt in invalid_targets:
          invalid_sources_by_target[tgt] = sources_by_target[tgt]
        invalid_sources = list(itertools.chain.from_iterable(invalid_sources_by_target.values()))
        deleted_sources = self._get_deleted_sources()

        # Work in a tmpdir so we don't stomp the main analysis files on error.
        # The tmpdir is cleaned up in a shutdown hook, because background work
        # may need to access files we create here even after this method returns.
        self._ensure_analysis_tmpdir()
        tmpdir = os.path.join(self._analysis_tmpdir, str(uuid.uuid4()))
        os.mkdir(tmpdir)
        valid_analysis_tmp = os.path.join(tmpdir, 'valid_analysis')
        newly_invalid_analysis_tmp = os.path.join(tmpdir, 'newly_invalid_analysis')
        invalid_analysis_tmp = os.path.join(tmpdir, 'invalid_analysis')
        if self._analysis_parser.is_nonempty_analysis(self._analysis_file):
          with self.context.new_workunit(name='prepare-analysis'):
            self._analysis_tools.split_to_paths(self._analysis_file,
              [(invalid_sources + deleted_sources, newly_invalid_analysis_tmp)], valid_analysis_tmp)
            if self._analysis_parser.is_nonempty_analysis(self._invalid_analysis_file):
              self._analysis_tools.merge_from_paths(
                [self._invalid_analysis_file, newly_invalid_analysis_tmp], invalid_analysis_tmp)
            else:
              invalid_analysis_tmp = newly_invalid_analysis_tmp

            # Now it's OK to overwrite the main analysis files with the new state.
            shutil.move(valid_analysis_tmp, self._analysis_file)
            shutil.move(invalid_analysis_tmp, self._invalid_analysis_file)

        if self.context.products.isrequired('classes'):
          # Register products for all the valid targets.
          # We register as we go, so dependency checking code can use this data.
          valid_targets = list(set(relevant_targets) - set(invalid_targets))
          self._add_products_to_genmap(valid_targets, sources_by_target, self._analysis_file)

        # Figure out the sources and analysis belonging to each partition.
        partitions = []  # Each element is a triple (vts, sources_by_target, analysis).
        for vts in invalidation_check.invalid_vts_partitioned:
          partition_tmpdir = os.path.join(tmpdir, Target.maybe_readable_identify(vts.targets))
          os.mkdir(partition_tmpdir)
          sources = list(itertools.chain.from_iterable(
            [invalid_sources_by_target.get(t, []) for t in vts.targets]))
          analysis_file = os.path.join(partition_tmpdir, 'analysis')
          partitions.append((vts, sources, analysis_file))

        # Split per-partition files out of the global invalid analysis.
        if self._analysis_parser.is_nonempty_analysis(self._invalid_analysis_file) and partitions:
          with self.context.new_workunit(name='partition-analysis'):
            splits = [(x[1], x[2]) for x in partitions]
            self._analysis_tools.split_to_paths(self._invalid_analysis_file, splits)

        # Now compile partitions one by one.
        for partition in partitions:
          (vts, sources, analysis_file) = partition
          cp_entries = [entry for conf, entry in classpath if conf in self._confs]
          self._process_target_partition(partition, cp_entries)
          # No exception was thrown, therefore the compile succeded and analysis_file is now valid.
          if os.path.exists(analysis_file):  # The compilation created an analysis.
            # Merge the newly-valid analysis with our global valid analysis.
            new_valid_analysis = analysis_file + '.valid.new'
            if self._analysis_parser.is_nonempty_analysis(self._analysis_file):
              with self.context.new_workunit(name='update-upstream-analysis'):
                self._analysis_tools.merge_from_paths([self._analysis_file, analysis_file], new_valid_analysis)
            else:  # We need to keep analysis_file around. Background tasks may need it.
              shutil.copy(analysis_file, new_valid_analysis)

            # Move the merged valid analysis to its proper location.
            # We do this before checking for missing dependencies, so that we can still
            # enjoy an incremental compile after fixing missing deps.
            shutil.move(new_valid_analysis, self._analysis_file)

            if self.context.products.isrequired('classes'):
              # Update the products with the latest classes.
              self._add_products_to_genmap(vts.targets, sources_by_target, analysis_file)
            if self._dep_analyzer:
              # Check for missing dependencies.
              self._dep_analyzer.update(vts.targets)  # Make sure it knows about the latest classes.
              actual_deps = self._analysis_parser.parse_deps_from_path(analysis_file,
                  lambda: self._compute_classpath_elements_by_class(cp_entries))
              with self.context.new_workunit(name='find-missing-dependencies'):
                self._dep_analyzer.check(sources, actual_deps)

            # Kick off the background artifact cache write.
            if self.artifact_cache_writes_enabled():
              self._write_to_artifact_cache(analysis_file, vts, invalid_sources_by_target)

          if self._analysis_parser.is_nonempty_analysis(self._invalid_analysis_file):
            with self.context.new_workunit(name='trim-downstream-analysis'):
              # Trim out the newly-valid sources from our global invalid analysis.
              new_invalid_analysis = analysis_file + '.invalid.new'
              discarded_invalid_analysis = analysis_file + '.invalid.discard'
              self._analysis_tools.split_to_paths(self._invalid_analysis_file,
                [(sources, discarded_invalid_analysis)], new_invalid_analysis)
              shutil.move(new_invalid_analysis, self._invalid_analysis_file)

          # Now that all the analysis accounting is complete, and we have no missing deps,
          # we can safely mark the targets as valid.
          vts.update()
      elif self.context.products.isrequired('classes'):
        # Nothing to build. Register products for all the targets in one go.
        self._add_products_to_genmap(relevant_targets, sources_by_target, self._analysis_file)

    # Update the classpath for downstream tasks.
    for conf in self._confs:
      egroups.update_compatible_classpaths(group_id, [(conf, self._classes_dir)])

    self.post_process(relevant_targets)

  def _process_target_partition(self, partition, classpath):
    """Needs invoking only on invalid targets.

    partition - a triple (vts, sources_by_target, analysis_file).
    classpath - a list of classpath entries.

    May be invoked concurrently on independent target sets.

    Postcondition: The individual targets in vts are up-to-date, as if each were
                   compiled individually.
    """
    (vts, sources, analysis_file) = partition

    if not sources:
      self.context.log.warn('Skipping %s compile for targets with no sources:\n  %s' % \
                            (self._language, vts.targets))
    else:
      # Do some reporting.
      self.context.log.info(
        'Compiling a partition containing ',
        items_to_report_element(sources, 'source'),
        ' in ',
        items_to_report_element([t.address.reference() for t in vts.targets], 'target'), '.')
      with self.context.new_workunit('compile'):
        # The compiler may delete classfiles, then later exit on a compilation error. Then if the
        # change triggering the error is reverted, we won't rebuild to restore the missing
        # classfiles. So we force-invalidate here, to be on the safe side.
        vts.force_invalidate()
        self.compile(self._args, classpath, sources, self._classes_dir, analysis_file)

  def check_artifact_cache(self, vts):
    # Special handling for scala analysis files. Class files are retrieved directly into their
    # final locations in the global classes dir.

    def post_process_cached_vts(cached_vts):
      # Merge the localized analysis with the global one (if any).
      analyses_to_merge = []
      for vt in cached_vts:
        for target in vt.targets:
          analysis_file = JvmCompile._analysis_for_target(self._analysis_tmpdir, target)
          portable_analysis_file = JvmCompile._portable_analysis_for_target(self._analysis_tmpdir, target)
          if os.path.exists(portable_analysis_file):
            self._analysis_tools.localize(portable_analysis_file, analysis_file)
          if os.path.exists(analysis_file):
            analyses_to_merge.append(analysis_file)

      if len(analyses_to_merge) > 0:
        if os.path.exists(self._analysis_file):
          analyses_to_merge.append(self._analysis_file)
        with contextutil.temporary_dir() as tmpdir:
          tmp_analysis = os.path.join(tmpdir, 'analysis')
          self._analysis_tools.merge_from_paths(analyses_to_merge, tmp_analysis)
          shutil.move(tmp_analysis, self._analysis_file)

    self._ensure_analysis_tmpdir()
    return Task.do_check_artifact_cache(self, vts, post_process_cached_vts=post_process_cached_vts)

  def _write_to_artifact_cache(self, analysis_file, vts, sources_by_target):
    vt_by_target = dict([(vt.target, vt) for vt in vts.versioned_targets])

    split_analysis_files = \
      [JvmCompile._analysis_for_target(self._analysis_tmpdir, t) for t in vts.targets]
    portable_split_analysis_files = \
      [JvmCompile._portable_analysis_for_target(self._analysis_tmpdir, t) for t in vts.targets]

    # Set up args for splitting the analysis into per-target files.
    splits = zip([sources_by_target.get(t, []) for t in vts.targets], split_analysis_files)
    splits_args_tuples = [(analysis_file, splits)]

    # Set up args for rebasing the splits.
    relativize_args_tuples = zip(split_analysis_files, portable_split_analysis_files)

    # Set up args for artifact cache updating.
    vts_artifactfiles_pairs = []
    classes_by_source = self._compute_classes_by_source(analysis_file)
    for target, sources in sources_by_target.items():
      artifacts = []
      for source in sources:
        for cls in classes_by_source.get(source, []):
          artifacts.append(os.path.join(self._classes_dir, cls))
      vt = vt_by_target.get(target)
      if vt is not None:
        # NOTE: analysis_file doesn't exist yet.
        vts_artifactfiles_pairs.append(
          (vt, artifacts + [JvmCompile._portable_analysis_for_target(self._analysis_tmpdir, target)]))

    update_artifact_cache_work = \
      self.get_update_artifact_cache_work(vts_artifactfiles_pairs)
    if update_artifact_cache_work:
      work_chain = [
        Work(self._analysis_tools.split_to_paths, splits_args_tuples, 'split'),
        Work(self._analysis_tools.relativize, relativize_args_tuples, 'relativize'),
        update_artifact_cache_work
      ]
      self.context.submit_background_work_chain(work_chain, parent_workunit_name='cache')

  def _compute_classes_by_source(self, analysis_file=None):
    """Compute src->classes."""
    if analysis_file is None:
      analysis_file = self._analysis_file

    if not os.path.exists(analysis_file):
      return {}
    buildroot = get_buildroot()
    products = self._analysis_parser.parse_products_from_path(analysis_file)
    classes_by_src = {}
    for src, classes in products.items():
      relsrc = os.path.relpath(src, buildroot)
      classes_by_src[relsrc] = [os.path.relpath(cls, self._classes_dir) for cls in classes]
    return classes_by_src

  def _get_deleted_sources(self):
    """Returns the list of sources present in the last analysis that have since been deleted.

    This is a global list. We have no way of associating them to individual targets.
    """
    # We compute the list lazily.
    if self._deleted_sources is None:
      with self.context.new_workunit('find-deleted-sources'):
        if os.path.exists(self._analysis_file):
          products = self._analysis_parser.parse_products_from_path(self._analysis_file)
          buildroot = get_buildroot()
          old_sources = [os.path.relpath(src, buildroot) for src in products.keys()]
          self._deleted_sources = filter(lambda x: not os.path.exists(x), old_sources)
        else:
          self._deleted_sources = []
    return self._deleted_sources

  def _compute_sources_by_target(self, targets):
    def calculate_sources(target):
      sources = [os.path.join(target.target_base, src) for src in target.sources if src.endswith(self._file_suffix)]
      # TODO: Make this less hacky. Ideally target.java_sources will point to sources, not targets.
      if hasattr(target, 'java_sources') and target.java_sources:
        sources.extend(resolve_target_sources(target.java_sources, '.java'))
      return sources
    return dict([(t, calculate_sources(t)) for t in targets])

  def _compute_classpath_elements_by_class(self, classpath):
    # Don't consider loose classes dirs in our classpath. Those will be considered
    # separately, by looking at products.
    def non_product(path):
      return not (path.startswith(self._pants_workdir) and os.path.isdir(path))
    classpath_jars = filter(non_product, classpath)
    if self._class_to_jarfile is None:
      self._class_to_jarfile = {}
      for jarpath in self.find_all_bootstrap_jars() + classpath_jars:
        # Per the classloading spec, a 'jar' in this context can also be a .zip file.
        if os.path.isfile(jarpath) and ((jarpath.endswith('.jar') or jarpath.endswith('.zip'))):
          with open_zip(jarpath, 'r') as jar:
            for cls in jar.namelist():
              # First jar with a given class wins, just like when classloading.
              if cls.endswith('.class') and not cls in self._class_to_jarfile:
                self._class_to_jarfile[cls] = jarpath
        elif os.path.isdir(jarpath):
          for dirpath, _, filenames in os.walk(jarpath, followlinks=True):
            for f in filter(lambda x: x.endswith('.class'), filenames):
              cls = os.path.relpath(os.path.join(dirpath, f), jarpath)
              if not cls in self._class_to_jarfile:
                self._class_to_jarfile[cls] = jarpath
    return self._class_to_jarfile

  def find_all_bootstrap_jars(self):
    def get_path(key):
      return self.context.java_sysprops.get(key, '').split(':')

    def find_jars_in_dirs(dirs):
      ret = []
      for d in dirs:
        if os.path.isdir(d):
          ret.extend(filter(lambda s: s.endswith('.jar'), os.listdir(d)))
      return ret

    # Note: assumes HotSpot, or some JVM that supports sun.boot.class.path.
    # TODO: Support other JVMs? Not clear if there's a standard way to do so.
    # May include loose classes dirs.
    boot_classpath = get_path('sun.boot.class.path')

    # Note that per the specs, overrides and extensions must be in jars.
    # Loose class files will not be found by the JVM.
    override_jars = find_jars_in_dirs(get_path('java.endorsed.dirs'))
    extension_jars = find_jars_in_dirs(get_path('java.ext.dirs'))

    # Note that this order matters: it reflects the classloading order.
    bootstrap_jars = filter(os.path.isfile, override_jars + boot_classpath + extension_jars)
    return bootstrap_jars  # Technically, may include loose class dirs from boot_classpath.

  @property
  def _analysis_tools(self):
    if self._lazy_analysis_tools is None:
      self._lazy_analysis_tools = self.create_analysis_tools()
    return self._lazy_analysis_tools

  @property
  def _analysis_parser(self):
    return self._analysis_tools.parser

  def _ensure_analysis_tmpdir(self):
    # Do this lazily, so we don't trigger creation of a worker pool unless we need it.
    if not os.path.exists(self._analysis_tmpdir):
      os.makedirs(self._analysis_tmpdir)
      self.context.background_worker_pool().add_shutdown_hook(lambda: safe_rmtree(self._analysis_tmpdir))

  def _add_products_to_genmap(self, targets, sources_by_target, analysis_file):
    # Map generated classes to the owning targets and sources.
    classes_by_source = self._compute_classes_by_source(analysis_file)
    genmap = self.context.products.get('classes')
    for target in targets:
      for source in sources_by_target[target]:
        classes = classes_by_source.get(source, [])
        relsrc = os.path.relpath(source, target.target_base)
        genmap.add(relsrc, self._classes_dir, classes)
        genmap.add(target, self._classes_dir, classes)
      for basedir, prod in self.extra_products(target):
        genmap.add(target, basedir, prod)
