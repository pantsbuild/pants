# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile

from pants.invalidation.build_invalidator import CacheKeyGenerator
from pants.invalidation.cache_manager import InvalidationCacheManager, VersionedTargetSet
from pants.util.dirutil import safe_mkdir, safe_rmtree
from pants_test.base_test import BaseTest


class InvalidationCacheManagerTest(BaseTest):

  @staticmethod
  def is_empty(dir_name):
    return not os.listdir(dir_name)

  @staticmethod
  def has_symlinked_result_dir(vt):
    return os.path.realpath(vt.results_dir) == os.path.realpath(vt.current_results_dir)

  @staticmethod
  def clobber_symlink(vt):
    # Munge the state to mimic a common error found before we added the clean- it accidentally clobbers the symlink!
    # Commonly caused by safe_mkdir(vt.results_dir, clean=True), broken up here to keep the tests from being brittle.
    safe_rmtree(vt.results_dir)
    safe_mkdir(vt.results_dir)

  def setUp(self):
    super(InvalidationCacheManagerTest, self).setUp()
    self._dir = tempfile.mkdtemp()
    self.cache_manager = InvalidationCacheManager(
      results_dir_root=os.path.join(self._dir, 'results'),
      cache_key_generator=CacheKeyGenerator(),
      build_invalidator_dir=os.path.join(self._dir, 'build_invalidator'),
      invalidate_dependents=True,
    )

  def tearDown(self):
    shutil.rmtree(self._dir, ignore_errors=True)
    super(InvalidationCacheManagerTest, self).tearDown()

  def make_vt(self, invalid=False):
    # Create an arbitrary VT. If invalid is False, it will mimic the state of the VT handed back by a task.
    a_target = self.make_target(':a', dependencies=[])
    ic = self.cache_manager.check([a_target])
    vt = ic.all_vts[0]
    if not invalid:
      self.task_execute(vt)
      vt.update()
    return vt

  def task_execute(self, vt):
    vt.create_results_dir()
    task_output = os.path.join(vt.results_dir, 'a_file')
    self.create_file(task_output, 'foo')

  def test_creates_stable_result_dir_symlink(self):
    vt = self.make_vt()
    vt.create_results_dir()
    parent, unstable_dir_name = os.path.split(vt._current_results_dir)
    self.assertSetEqual({'current', unstable_dir_name}, set(os.listdir(parent)))
    symlink = os.path.join(parent, 'current')
    self.assertTrue(os.path.islink(symlink))
    self.assertTrue(unstable_dir_name, os.readlink(symlink))
    self.assertEquals(symlink, vt.results_dir)

  def test_creates_stable_results_dir_prefix_symlink(self):
    parent, unstable_dir_name = os.path.split(self.cache_manager._results_dir_prefix)
    self.assertSetEqual({'current', unstable_dir_name}, set(os.listdir(parent)))
    symlink = os.path.join(parent, 'current')
    self.assertTrue(os.path.islink(symlink))
    self.assertTrue(unstable_dir_name, os.readlink(symlink))

  def test_check_marks_all_as_invalid_by_default(self):
    a = self.make_target(':a', dependencies=[])
    b = self.make_target(':b', dependencies=[a])
    c = self.make_target(':c', dependencies=[b])
    d = self.make_target(':d', dependencies=[c, a])
    e = self.make_target(':e', dependencies=[d])

    targets = [a, b, c, d, e]

    ic = self.cache_manager.check(targets)

    all_vts = ic.all_vts
    invalid_vts = ic.invalid_vts

    self.assertEquals(5, len(invalid_vts))
    self.assertEquals(5, len(all_vts))
    vts_targets = [vt.targets[0] for vt in all_vts]
    self.assertEquals(set(targets), set(vts_targets))

  def test_force_invalidate(self):
    vt = self.make_vt()
    self.assertTrue(vt.valid)
    vt.force_invalidate()
    self.assertFalse(vt.valid)

  def test_invalid_vts_are_cleaned(self):
    # Ensure that calling create_results_dir on an invalid target will wipe any pre-existing output.
    vt = self.make_vt()
    self.assertFalse(self.is_empty(vt.results_dir))

    # Force invalidate should change no state under the results_dir.
    vt.force_invalidate()
    self.assertFalse(self.is_empty(vt.results_dir))

    vt.create_results_dir()
    self.assertTrue(self.has_symlinked_result_dir(vt))
    self.assertTrue(self.is_empty(vt.results_dir))

  def test_valid_vts_are_not_cleaned(self):
    # No cleaning of results_dir occurs, since create_results_dir short-circuits if the VT is valid.
    vt = self.make_vt()
    self.assertFalse(self.is_empty(vt.results_dir))
    file_names = os.listdir(vt.results_dir)

    vt.create_results_dir()
    self.assertFalse(self.is_empty(vt.results_dir))
    self.assertTrue(self.has_symlinked_result_dir(vt))

    # Show that the files inside the directory have not changed during the create_results_dir noop.
    self.assertEqual(file_names, os.listdir(vt.results_dir))

  def test_illegal_results_dir_cannot_be_updated_to_valid(self):
    # A regression test for a former bug. Calling safe_mkdir(vt.results_dir, clean=True) would silently
    # delete the results_dir symlink and yet leave any existing crufty content behind in the vt.current_results_dir.
    # https://github.com/pantsbuild/pants/issues/4137
    # https://github.com/pantsbuild/pants/issues/4051

    vt = self.make_vt()
    # Show all is right with the world, there is content from the task run and it's visible from both legal result_dirs.
    self.assertFalse(self.is_empty(vt.results_dir))
    self.assertTrue(self.has_symlinked_result_dir(vt))
    vt.force_invalidate()
    self.clobber_symlink(vt)

    # Arg, and the resultingly unlinked current_results_dir is uncleaned. The two directories have diverging contents!
    self.assertFalse(self.has_symlinked_result_dir(vt))
    self.assertFalse(self.has_symlinked_result_dir(vt))

    # Big consequences- the files used for Products(vt.results_dir) and the cache(vt.current_results_dir) have diverged!
    self.assertNotEqual(os.listdir(vt.results_dir), os.listdir(vt.current_results_dir))

    # The main protection for this is the exception raised when the cache_manager attempts to mark the VT valid.
    self.assertFalse(vt.valid)
    with self.assertRaises(VersionedTargetSet.IllegalResultsDir):
      vt.update()

  def test_exception_for_invalid_vt_result_dirs(self):
    # Show that the create_results_dir will error if a previous operation changed the results_dir from a symlink.
    vt = self.make_vt()
    self.clobber_symlink(vt)
    self.assertFalse(self.has_symlinked_result_dir(vt))

    # This only is caught here if the VT is still invalid for some reason, otherwise it's caught by the update() method.
    vt.force_invalidate()
    with self.assertRaisesRegexp(ValueError, r'Path for link.*overwrite an existing directory*'):
      vt.create_results_dir()

  def test_raises_for_clobbered_symlink(self):
    vt = self.make_vt()
    self.clobber_symlink(vt)
    with self.assertRaisesRegexp(VersionedTargetSet.IllegalResultsDir, r'The.*symlink*'):
      vt.ensure_legal()

  def test_raises_missing_current_results_dir(self):
    vt = self.make_vt()
    safe_rmtree(vt.current_results_dir)
    with self.assertRaisesRegexp(VersionedTargetSet.IllegalResultsDir, r'The.*current_results_dir*'):
      vt.ensure_legal()

  def test_raises_both_clobbered_symlink_and_missing_current_results_dir(self):
    vt = self.make_vt()
    self.clobber_symlink(vt)
    safe_rmtree(vt.current_results_dir)
    with self.assertRaisesRegexp(VersionedTargetSet.IllegalResultsDir, r'The.*symlink*'):
      vt.ensure_legal()
    with self.assertRaisesRegexp(VersionedTargetSet.IllegalResultsDir, r'The.*current_results_dir*'):
      vt.ensure_legal()

  def test_for_illegal_vts(self):
    # The update() checks this through vts.ensure_legal, checked here since those checks are on different branches.
    vt = self.make_vt()
    self.clobber_symlink(vt)
    vts = VersionedTargetSet.from_versioned_targets([vt])
    with self.assertRaises(VersionedTargetSet.IllegalResultsDir):
      vts.update()
