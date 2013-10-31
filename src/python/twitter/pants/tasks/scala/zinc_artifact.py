# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'Benjy Weinberger'

import itertools
import os
import shutil

from collections import defaultdict, namedtuple

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir, safe_rmtree

from twitter.pants.base.target import Target
from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.targets import resolve_target_sources
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.scala.zinc_artifact_state import ZincArtifactState, ZincArtifactStateDiff


class ZincArtifactFactory(object):
  """Creates objects representing zinc artifacts."""
  def __init__(self, workdir, context, zinc_utils):
    self._workdir = workdir
    self.context = context
    self.zinc_utils = zinc_utils

    self._classes_dirs_base = os.path.join(self._workdir, 'classes')
    self._analysis_files_base = os.path.join(self._workdir, 'analysis')
    safe_mkdir(self._classes_dirs_base)
    safe_mkdir(self._analysis_files_base)

  def artifact_for_target(self, target):
    """The artifact representing the specified target."""
    targets = [target]
    sources_by_target = {target: ZincArtifactFactory._calculate_sources(target)}
    factory = self
    return _ZincArtifact(factory, targets, sources_by_target, *self._artifact_args([target]))

  def merged_artifact(self, artifacts):
    """The artifact merged from those of the specified artifacts."""
    targets = list(itertools.chain.from_iterable([a.targets for a in artifacts]))
    sources_by_target = dict(itertools.chain.from_iterable(
      [a.sources_by_target.items() for a in artifacts]))
    factory = self
    return _MergedZincArtifact(artifacts, factory, targets, sources_by_target,
                               *self._artifact_args(targets))

  # There are two versions of the zinc analysis file: The one zinc creates on compilation, which
  # contains full paths and is therefore not portable, and the portable version, that we create by
  # rebasing the full path prefixes to placeholders. We refer to this as "relativizing" the
  # analysis file. The inverse, replacing placeholders with full path prefixes so we can use the
  # file again when compiling, is referred to as "localizing" the analysis file.
  #
  # This is necessary only when using the artifact cache: We must relativize before uploading to
  # the cache, and localize after pulling from the cache.
  @staticmethod
  def portable(analysis_file):
    """Returns the path to the portable version of the zinc analysis file."""
    return analysis_file + '.portable'

  def _artifact_args(self, targets):
    """Returns the artifact paths for the given target set."""
    artifact_id = Target.maybe_readable_identify(targets)
    # Each compilation must output to its own directory, so zinc can then associate those with the
    # appropriate analysis files of previous compilations.
    classes_dir = os.path.join(self._classes_dirs_base, artifact_id)
    analysis_file = os.path.join(self._analysis_files_base, artifact_id) + '.analysis'
    return artifact_id, classes_dir, analysis_file

  @staticmethod
  def _calculate_sources(target):
    """Find a target's source files."""
    sources = []
    srcs = \
      [os.path.join(target.target_base, src) for src in target.sources if src.endswith('.scala')]
    sources.extend(srcs)
    if (isinstance(target, ScalaLibrary) or isinstance(target, ScalaTests)) and target.java_sources:
      sources.extend(resolve_target_sources(target.java_sources, '.java'))
    return sources


class _ZincArtifact(object):
  """Locations of the files in a zinc build artifact.

  An artifact consists of:
    A) A classes directory
    B) A zinc analysis file.

  Represents the result of building some set of targets.

  Don't create instances of this directly. Use ZincArtifactFactory instead.
  """
  def __init__(self, factory, targets, sources_by_target,
               artifact_id, classes_dir, analysis_file):
    self.factory = factory
    self.targets = targets
    self.sources_by_target = sources_by_target
    self.sources = list(itertools.chain.from_iterable(sources_by_target.values()))
    self.artifact_id = artifact_id
    self.classes_dir = classes_dir
    self.analysis_file = analysis_file
    self.portable_analysis_file = ZincArtifactFactory.portable(analysis_file)
    self.relations_file = analysis_file + '.relations'  # The human-readable zinc relations file.
    self.log = self.factory.context.log

  def current_state(self):
    """Returns the current state of this artifact."""
    return ZincArtifactState(self)

  def __eq__(self, other):
    return self.artifact_id == other.artifact_id

  def __ne__(self, other):
    return self.artifact_id != other.artifact_id


class _MergedZincArtifact(_ZincArtifact):
  """An artifact merged from some underlying artifacts.

  A merged artifact consists of:
    A) A classes dir containing all the classes from all the underlying artifacts' classes dirs.
    B) An analysis file containing all the information from all the underlying artifact's analyses.
  """
  def __init__(self, underlying_artifacts, factory , targets, sources_by_target,
               artifact_id, classes_dir, analysis_file):
    _ZincArtifact.__init__(self, factory, targets, sources_by_target, artifact_id,
                           classes_dir, analysis_file)
    self.underlying_artifacts = underlying_artifacts

  def merge(self, force=False):
    """Actually combines the underlying artifacts into a single merged one.

    Creates a single merged analysis file and a single merged classes dir.
    """
    if len(self.underlying_artifacts) <= 1:
      return self.current_state()

    # Note that if the merged analysis file already exists we don't re-merge it.
    # Ditto re the merged classes dir. In some unlikely corner cases they may
    # be less up to date than the artifact we could create by re-merging, but this
    # heuristic is worth it so that in the common case we don't spend a lot of time
    # copying files around.

    # If this is a complete no-op, don't even create a workunit, as it would be confusing
    # to the user to see spurious 'merge' work.
    if not force and os.path.exists(self.analysis_file) and os.path.exists(self.classes_dir):
      return self.current_state()

    # At least one of the analysis file or the classes dir doesn't exist, or we're forcing, so merge.
    with self.factory.context.new_workunit(name='merge'):
      # Must merge analysis before computing current state.
      if force or not os.path.exists(self.analysis_file):
        with self.factory.context.new_workunit(name='analysis'):
          self._merge_analysis()
      current_state = self.current_state()
      if force or not os.path.exists(self.classes_dir):
        with self.factory.context.new_workunit(name='classes'):
          self._merge_classes_dir(current_state)
    return current_state

  def _merge_analysis(self):
    """Merge the analysis files from the underlying artifacts into a single file."""
    if len(self.underlying_artifacts) <= 1:
      return
    with temporary_dir() as tmpdir:
      artifact_analysis_files = []
      with self.factory.context.new_workunit(name='rebase', labels=[WorkUnit.MULTITOOL]):
        for artifact in self.underlying_artifacts:
          # Rebase a copy of the per-target analysis files to reflect the merged classes dir.
          if os.path.exists(artifact.classes_dir) and os.path.exists(artifact.analysis_file):
            self.log.debug('Rebasing analysis file %s before merging' % artifact.analysis_file)
            analysis_file_tmp = os.path.join(tmpdir, artifact.artifact_id)
            shutil.copyfile(artifact.analysis_file, analysis_file_tmp)
            artifact_analysis_files.append(analysis_file_tmp)
            if self.factory.zinc_utils.run_zinc_rebase(analysis_file_tmp,
                                                       [(artifact.classes_dir, self.classes_dir)]):
              self.log.warn('Zinc failed to rebase analysis file %s. ' \
                            'Target may require a full rebuild.' % analysis_file_tmp)

      self.log.debug('Merging into analysis file %s' % self.analysis_file)
      if self.factory.zinc_utils.run_zinc_merge(artifact_analysis_files, self.analysis_file):
        self.log.warn('zinc failed to merge analysis files %s to %s. Target may require a full ' \
                      'rebuild.' % (':'.join(artifact_analysis_files), self.analysis_file))

  def _merge_classes_dir(self, state):
    """Merge the classes dirs from the underlying artifacts into a single dir.

    May symlink instead of copying, when it's OK to do so.

    Postcondition: symlinks are of leaf packages only.
    """
    self.log.debug('Merging classes dirs into %s' % self.classes_dir)
    safe_rmtree(self.classes_dir)
    symlinkable_packages = self._symlinkable_packages(state)
    for artifact in self.underlying_artifacts:
      classnames_by_package = defaultdict(list)
      for cls in state.classes_by_target.get(artifact.targets[0], []):
        classnames_by_package[os.path.dirname(cls)].append(os.path.basename(cls))

      for package, classnames in classnames_by_package.items():
        if package == "":
          raise  TaskError("Found class files %s with empty package" % classnames)
        artifact_package_dir = os.path.join(artifact.classes_dir, package)
        merged_package_dir = os.path.join(self.classes_dir, package)

        if package in symlinkable_packages:
          if os.path.islink(merged_package_dir):
            assert os.readlink(merged_package_dir) == artifact_package_dir
          elif os.path.exists(merged_package_dir):
            safe_rmtree(merged_package_dir)
            os.symlink(artifact_package_dir, merged_package_dir)
          else:
            safe_mkdir(os.path.dirname(merged_package_dir))
            os.symlink(artifact_package_dir, merged_package_dir)
        else:
          safe_mkdir(merged_package_dir)
          for classname in classnames:
            src = os.path.join(artifact_package_dir, classname)
            dst = os.path.join(merged_package_dir, classname)
            self._maybe_hardlink(src, dst)

  def split(self, old_state=None, portable=False):
    """Actually split the merged artifact into per-target artifacts."""
    current_state = self.current_state()

    if len(self.underlying_artifacts) <= 1:
      return current_state

    with self.factory.context.new_workunit(name='split'):
      diff = ZincArtifactStateDiff(old_state, current_state) if old_state else None
      if not diff or diff.analysis_changed:
        with self.factory.context.new_workunit(name='analysis'):
          self._split_analysis('analysis_file')
          if portable:
            self._split_analysis('portable_analysis_file')
      with self.factory.context.new_workunit(name='classes'):
        self._split_classes_dir(current_state, diff)
    return current_state

  def _split_analysis(self, analysis_file_attr):
    """Split the merged analysis into one file per underlying artifact.

    analysis_file_attr: one of 'analysis_file' or 'portable_analysis_file'.
    """
    if len(self.underlying_artifacts) <= 1:
      return
    # Specifies that the list of sources defines a split to the classes dir and analysis file.
    SplitInfo = namedtuple('SplitInfo', ['sources', 'dst_classes_dir', 'dst_analysis_file'])

    def _analysis(artifact):
      return getattr(artifact, analysis_file_attr)

    if len(self.underlying_artifacts) <= 1:
      return

    analysis_to_split = _analysis(self)
    if not os.path.exists(analysis_to_split):
      return

    splits = []
    for artifact in self.underlying_artifacts:
      splits.append(SplitInfo(artifact.sources, artifact.classes_dir, _analysis(artifact)))

    split_args = [(x.sources, x.dst_analysis_file) for x in splits]
    self.log.debug('Splitting analysis file %s' % analysis_to_split)
    if self.factory.zinc_utils.run_zinc_split(analysis_to_split, split_args):
      raise TaskError('zinc failed to split analysis files %s from %s' % \
                      (':'.join([x.dst_analysis_file for x in splits]), analysis_to_split))

    with self.factory.context.new_workunit(name='rebase', labels=[WorkUnit.MULTITOOL]):
      for split in splits:
        if os.path.exists(split.dst_analysis_file):
          self.log.debug('Rebasing analysis file %s after split' % split.dst_analysis_file)
          if self.factory.zinc_utils.run_zinc_rebase(split.dst_analysis_file,
                                                     [(self.classes_dir, split.dst_classes_dir)]):
            raise TaskError('Zinc failed to rebase analysis file %s' % split.dst_analysis_file)

  def _split_classes_dir(self, state, diff):
    """Split the merged classes dir into one dir per underlying artifact."""
    if len(self.underlying_artifacts) <= 1:
      return

    def map_classes_by_package(classes):
      # E.g., com/foo/bar/Bar.scala, com/foo/bar/Baz.scala to com/foo/bar -> [Bar.scala, Baz.scala].
      ret = defaultdict(list)
      for cls in classes:
        ret[os.path.dirname(cls)].append(os.path.basename(cls))
      return ret
    self.log.debug('Splitting classes dir %s' % self.classes_dir)
    if diff:
      new_or_changed_classnames_by_package = map_classes_by_package(diff.new_or_changed_classes)
      deleted_classnames_by_package = map_classes_by_package(diff.deleted_classes)
    else:
      new_or_changed_classnames_by_package = None
      deleted_classnames_by_package = None

    symlinkable_packages = self._symlinkable_packages(state)
    for artifact in self.underlying_artifacts:
      classnames_by_package = \
        map_classes_by_package(state.classes_by_target.get(artifact.targets[0], []))

      for package, classnames in classnames_by_package.items():
        if package == "":
          raise  TaskError("Found class files %s with empty package" % classnames)
        artifact_package_dir = os.path.join(artifact.classes_dir, package)
        merged_package_dir = os.path.join(self.classes_dir, package)

        if package in symlinkable_packages:
          if os.path.islink(merged_package_dir):
            current_link = os.readlink(merged_package_dir)
            if current_link != artifact_package_dir:
              # The code moved to a different target.
              os.unlink(merged_package_dir)
              safe_rmtree(artifact_package_dir)
              shutil.move(current_link, artifact_package_dir)
              os.symlink(artifact_package_dir, merged_package_dir)
          else:
            safe_rmtree(artifact_package_dir)
            shutil.move(merged_package_dir, artifact_package_dir)
            os.symlink(artifact_package_dir, merged_package_dir)
        else:
          safe_mkdir(artifact_package_dir)
          new_or_changed_classnames = \
            set(new_or_changed_classnames_by_package.get(package, [])) if diff else None
          for classname in classnames:
            if not diff or classname in new_or_changed_classnames:
              src = os.path.join(merged_package_dir, classname)
              dst = os.path.join(artifact_package_dir, classname)
              self._maybe_hardlink(src, dst)
          if diff:
            for classname in deleted_classnames_by_package.get(package, []):
              path = os.path.join(artifact_package_dir, classname)
              if os.path.exists(path):
                os.unlink(path)

  def _symlinkable_packages(self, state):
    targets_by_pkg = self._targets_by_package(state)
    package_targets_pairs = sorted(targets_by_pkg.items(), key=lambda x: len(x[0]), reverse=True)
    ret = set(targets_by_pkg.keys())  # Putatively assume all are symlinkable.

    # Note that we'll visit child packages before their parents.
    for package, targets in package_targets_pairs:
      # If a package a non-empty ancestor, neither it nor its ancestors are symlinkable.
      parent = os.path.dirname(package)
      while parent:
        if parent in ret:
          ret.remove(parent)
          ret.discard(package)
        parent = os.path.dirname(parent)
      # If multiple targets have classes in a package, it's not symlinkable.
      if len(targets) > 1:
        ret.discard(package)
    return ret

  def _targets_by_package(self, state):
    targets_by_package = defaultdict(set)
    for target, classes in state.classes_by_target.items():
      for cls in classes:
        targets_by_package[os.path.dirname(cls)].add(target)
    return targets_by_package

  def _maybe_hardlink(self, src, dst):
    if os.path.exists(src):
      if os.path.exists(dst):
        if not os.path.samefile(src, dst):
          os.unlink(dst)
          os.link(src, dst)
      else:
        os.link(src, dst)

