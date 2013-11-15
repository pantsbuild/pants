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

import hashlib
import os
import time

from collections import defaultdict

from twitter.pants import get_buildroot
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.scala.zinc_analysis_collection import ZincAnalysisCollection


class ZincArtifactState(object):
  """The current state of a zinc artifact."""
  def __init__(self, artifact):
    self.artifact = artifact

    # Fingerprint the text version, as the binary one may vary even when the analysis is identical.
    relfile = self.artifact.relations_file
    self.analysis_fprint = \
      ZincArtifactState._fprint_file(relfile) if os.path.exists(relfile) else None

    self.classes_by_src = ZincArtifactState._compute_classes_by_src(self.artifact)
    self.classes_by_target = \
      ZincArtifactState._compute_classes_by_target(self.classes_by_src,
                                                   self.artifact.sources_by_target)
    self.classes = set()
    # Note: It's important to use classes_by_src here, not classes_by_target, because a now-deleted
    # src won't be reflected in any target, which will screw up our computation of deleted classes.
    for classes in self.classes_by_src.values():
      self.classes.update(classes)

    self.timestamp = time.time()

  def find_filesystem_classes(self):
    return ZincArtifactState._find_filesystem_classes(self.artifact)

  @staticmethod
  def _fprint_file(path):
    """Compute the md5 hash of a file."""
    hasher = hashlib.md5()
    with open(path, 'r') as f:
      hasher.update(f.read())
    return hasher.hexdigest()

  @staticmethod
  def _compute_classes_by_src(artifact):
    """Compute src->classes."""
    if not os.path.exists(artifact.analysis_file):
      return {}
    len_rel_classes_dir = len(artifact.classes_dir) - len(get_buildroot())
    analysis = ZincAnalysisCollection(stop_after=ZincAnalysisCollection.PRODUCTS)
    analysis.add_and_parse_file(artifact.analysis_file, artifact.classes_dir)
    classes_by_src = {}
    for src, classes in analysis.products.items():
      classes_by_src[src] = [cls[len_rel_classes_dir:] for cls in classes]
    return classes_by_src

  @staticmethod
  def _compute_classes_by_target(classes_by_src, srcs_by_target):
    """Compute target -> classes."""
    classes_by_target = defaultdict(set)
    for target, srcs in srcs_by_target.items():
      for src in srcs:
        classes_by_target[target].update(classes_by_src.get(src, []))
    return classes_by_target

  @staticmethod
  def _find_filesystem_classes(artifact):
    """Finds all the classfiles that are actually on the filesystem.

    Does not follow symlinks."""
    classes = []
    classes_dir_prefix_len = len(artifact.classes_dir) + 1
    for (dirpath, _, filenames) in os.walk(artifact.classes_dir, followlinks=False):
      for f in filenames:
        classes.append(os.path.join(dirpath, f)[classes_dir_prefix_len:])
    return classes

class ZincArtifactStateDiff(object):
  """The diff between two states of the same zinc artifact."""
  def __init__(self, old_state, new_state):
    if old_state.artifact != new_state.artifact:
      raise TaskError('Cannot diff state of two different artifacts.')
    self.artifact = old_state.artifact
    self.new_or_changed_classes = set(filter(
      lambda f: os.path.getmtime(os.path.join(self.artifact.classes_dir, f)) > old_state.timestamp,
      new_state.classes))
    self.deleted_classes = old_state.classes - new_state.classes
    self.analysis_changed = old_state.analysis_fprint != new_state.analysis_fprint

  def __repr__(self):
    return 'Analysis changed: %s. New or changed classes: %d. Deleted classes: %d.' % \
           (self.analysis_changed, len(self.new_or_changed_classes), len(self.deleted_classes))
