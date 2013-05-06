# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import pytest
import unittest

from twitter.pants.base.revision import Revision


class RevisionTest(unittest.TestCase):
  def assertComponents(self, revision, *expected):
    self.assertEqual(list(expected), revision.components)


class SemverTest(RevisionTest):
  def test_bad(self):
    for bad_rev in ('a.b.c', '1.b.c', '1.2.c', '1.2.3;4', '1.2.3;4+5'):
      with pytest.raises(Revision.BadRevision):
        Revision.semver(bad_rev)

  def test_simple(self):
    self.assertEqual(Revision.semver('1.2.3'), Revision.semver('1.2.3'))
    self.assertComponents(Revision.semver('1.2.3'), 1, 2, 3, None, None)

    self.assertTrue(Revision.semver('1.2.3') > Revision.semver('1.2.2'))
    self.assertTrue(Revision.semver('1.3.0') > Revision.semver('1.2.2'))
    self.assertTrue(Revision.semver('1.3.10') > Revision.semver('1.3.2'))
    self.assertTrue(Revision.semver('2.0.0') > Revision.semver('1.3.2'))

  def test_pre_release(self):
    self.assertEqual(Revision.semver('1.2.3-pre1.release.1'),
                     Revision.semver('1.2.3-pre1.release.1'))
    self.assertComponents(Revision.semver('1.2.3-pre1.release.1'),
                          1, 2, 3, 'pre1', 'release', 1, None)

    self.assertTrue(
      Revision.semver('1.2.3-pre1.release.1') < Revision.semver('1.2.3-pre2.release.1'))
    self.assertTrue(
      Revision.semver('1.2.3-pre1.release.2') < Revision.semver('1.2.3-pre1.release.10'))

    self.assertTrue(Revision.semver('1.2.3') < Revision.semver('1.2.3-pre2.release.1'))

  def test_build(self):
    self.assertEqual(Revision.semver('1.2.3+pre1.release.1'),
                     Revision.semver('1.2.3+pre1.release.1'))
    self.assertComponents(Revision.semver('1.2.3+pre1.release.1'),
                          1, 2, 3, None, 'pre1', 'release', 1)

    self.assertTrue(
      Revision.semver('1.2.3+pre1.release.1') < Revision.semver('1.2.3+pre2.release.1'))
    self.assertTrue(
      Revision.semver('1.2.3+pre1.release.2') < Revision.semver('1.2.3+pre1.release.10'))

    self.assertTrue(Revision.semver('1.2.3') < Revision.semver('1.2.3+pre2.release.1'))
    self.assertTrue(
      Revision.semver('1.2.3+pre1.release.2') < Revision.semver('1.2.3-pre1.release.2'))

  def test_pre_release_build(self):
    self.assertEqual(Revision.semver('1.2.3-pre1.release.1+1'),
                     Revision.semver('1.2.3-pre1.release.1+1'))
    self.assertComponents(Revision.semver('1.2.3-pre1.release.1+1'),
                          1, 2, 3, 'pre1', 'release', 1, 1)

    self.assertTrue(
      Revision.semver('1.2.3-pre1.release.1') < Revision.semver('1.2.3-pre2.release.1+1'))
    self.assertTrue(
      Revision.semver('1.2.3-pre1.release.2') > Revision.semver('1.2.3-pre1.release.1+1'))

    self.assertTrue(Revision.semver('1.2.3') < Revision.semver('1.2.3-pre2.release.2+1.foo'))
    self.assertTrue(
      Revision.semver('1.2.3-pre1.release.2+1') < Revision.semver('1.2.3-pre1.release.2+1.foo'))
    self.assertTrue(
      Revision.semver('1.2.3-pre1.release.2+1') < Revision.semver('1.2.3-pre1.release.2+2'))


class LenientTest(RevisionTest):
  def test(self):
    self.assertComponents(Revision.lenient('1.2.3'), 1, 2, 3)
    self.assertComponents(Revision.lenient('1.2.3-SNAPSHOT-eabc'), 1, 2, 3, 'SNAPSHOT', 'eabc')
    self.assertComponents(Revision.lenient('1.2.3-SNAPSHOT4'), 1, 2, 3, 'SNAPSHOT', 4)

    self.assertTrue(Revision.lenient('a') < Revision.lenient('b'))
    self.assertTrue(Revision.lenient('1') < Revision.lenient('2'))
    self.assertTrue(Revision.lenient('1') < Revision.lenient('a'))

    self.assertEqual(Revision.lenient('1.2.3'), Revision.lenient('1.2.3'))
    self.assertTrue(Revision.lenient('1.2.3') < Revision.lenient('1.2.3-SNAPSHOT'))
    self.assertTrue(Revision.lenient('1.2.3-SNAPSHOT') < Revision.lenient('1.2.3-SNAPSHOT-abc'))
    self.assertTrue(Revision.lenient('1.2.3-SNAPSHOT-abc') < Revision.lenient('1.2.3-SNAPSHOT-bcd'))
    self.assertTrue(
      Revision.lenient('1.2.3-SNAPSHOT-abc6') < Revision.lenient('1.2.3-SNAPSHOT-abc10'))
