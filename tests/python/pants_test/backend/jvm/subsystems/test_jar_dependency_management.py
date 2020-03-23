# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.backend.jvm.subsystems.jar_dependency_management import (
    JarDependencyManagement,
    PinnedJarArtifactSet,
)
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.subsystem.subsystem import Subsystem
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.test_base import TestBase


class JarDependencyManagementTest(TestBase):

    _coord_any = M2Coordinate("foobar", "foobar")
    _coord_one = M2Coordinate("foobar", "foobar", "1.1")
    _coord_two = M2Coordinate("foobar", "foobar", "1.2")

    def _jar_dependency_management(self, **flags):
        Subsystem.reset()
        options = {
            JarDependencyManagement.options_scope: flags,
        }
        return global_subsystem_instance(JarDependencyManagement, options=options)

    def test_conflict_strategy_short_circuits(self):
        manager = self._jar_dependency_management(conflict_strategy="FAIL")
        manager.resolve_version_conflict(
            direct_coord=self._coord_any, managed_coord=self._coord_one,
        )
        manager.resolve_version_conflict(
            direct_coord=self._coord_one, managed_coord=self._coord_one,
        )

    def test_conflict_strategy_fail(self):
        manager = self._jar_dependency_management(conflict_strategy="FAIL")
        with self.assertRaises(JarDependencyManagement.DirectManagedVersionConflict):
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            )

    def test_conflict_strategy_use_direct(self):
        manager = self._jar_dependency_management(conflict_strategy="USE_DIRECT")
        self.assertEqual(
            self._coord_one,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            ),
        )
        manager = self._jar_dependency_management(
            conflict_strategy="USE_DIRECT", suppress_conflict_messages=True
        )
        self.assertEqual(
            self._coord_one,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            ),
        )

    def test_conflict_strategy_use_managed(self):
        manager = self._jar_dependency_management(conflict_strategy="USE_MANAGED")
        self.assertEqual(
            self._coord_two,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            ),
        )
        manager = self._jar_dependency_management(
            conflict_strategy="USE_MANAGED", suppress_conflict_messages=True
        )
        self.assertEqual(
            self._coord_two,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            ),
        )

    def test_conflict_strategy_use_forced(self):
        manager = self._jar_dependency_management(conflict_strategy="USE_DIRECT_IF_FORCED")
        self.assertEqual(
            self._coord_two,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            ),
        )
        self.assertEqual(
            self._coord_one,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two, force=True,
            ),
        )

    def test_conflict_strategy_use_newer(self):
        manager = self._jar_dependency_management(conflict_strategy="USE_NEWER")
        self.assertEqual(
            self._coord_two,
            manager.resolve_version_conflict(
                direct_coord=self._coord_one, managed_coord=self._coord_two,
            ),
        )
        self.assertEqual(
            self._coord_two,
            manager.resolve_version_conflict(
                direct_coord=self._coord_two, managed_coord=self._coord_one,
            ),
        )

    def test_conflict_resolution_input_validation(self):
        manager = self._jar_dependency_management()
        with self.assertRaises(ValueError):
            manager.resolve_version_conflict(
                M2Coordinate("org", "foo", "1.2"), M2Coordinate("com", "bar", "7.8")
            )
        with self.assertRaises(ValueError):
            manager.resolve_version_conflict(
                M2Coordinate("org", "foo", "1.2"), M2Coordinate("com", "bar", "1.2")
            )


class PinnedJarArtifactSetTest(unittest.TestCase):
    def test_equality(self):
        set1 = PinnedJarArtifactSet(
            pinned_coordinates=[
                M2Coordinate("org", "foo", "1.2"),
                M2Coordinate("org", "bar", "7.8"),
            ]
        )
        set2 = PinnedJarArtifactSet(
            pinned_coordinates=[
                M2Coordinate("org", "foo", "1.2"),
                M2Coordinate("org", "bar", "7.8"),
            ]
        )
        self.assertEqual(set1, set2)
        self.assertEqual(hash(set1), hash(set2))

    def test_iter(self):
        set1 = PinnedJarArtifactSet(
            pinned_coordinates=[
                M2Coordinate("org", "foo", "1.2"),
                M2Coordinate("org", "bar", "7.8"),
            ]
        )
        self.assertEqual(2, len(set1))
        set2 = PinnedJarArtifactSet(set1)
        self.assertEqual(2, len(set2))
        self.assertEqual(set1, set2)

    def test_replace(self):
        set1 = PinnedJarArtifactSet(
            pinned_coordinates=[
                M2Coordinate("org", "foo", "1.2"),
                M2Coordinate("org", "bar", "7.8"),
            ]
        )
        set1.put(M2Coordinate("org", "hello", "9"))
        self.assertEqual(3, len(set1))
        set1.put(M2Coordinate("org", "foo", "1.3"))
        self.assertEqual(3, len(set1))
        self.assertEqual(M2Coordinate("org", "foo", "1.3"), set1[M2Coordinate("org", "foo")])

    def test_put_failure(self):
        set1 = PinnedJarArtifactSet()
        with self.assertRaises(PinnedJarArtifactSet.MissingVersion):
            set1.put(M2Coordinate("hello", "there"))

    def test_lookup(self):
        set1 = PinnedJarArtifactSet(
            pinned_coordinates=[
                M2Coordinate("org", "foo", "1.2"),
                M2Coordinate("org", "bar", "7.8"),
                M2Coordinate("org", "foo", "1.8", ext="tar"),
            ]
        )
        self.assertEqual("1.2", set1[M2Coordinate("org", "foo")].rev)
        self.assertEqual("7.8", set1[M2Coordinate("org", "bar")].rev)
        self.assertEqual("1.8", set1[M2Coordinate("org", "foo", ext="tar")].rev)
        self.assertEqual({coord.rev for coord in set1}, {"1.2", "7.8", "1.8"})
        self.assertIn(M2Coordinate("org", "foo"), set1)
        self.assertIn(M2Coordinate("org", "foo", "27"), set1)
        self.assertNotIn(M2Coordinate("hello", "there"), set1)

    def test_lookup_noop(self):
        self.assertEqual(
            M2Coordinate("org", "foo", "1.2"),
            PinnedJarArtifactSet()[M2Coordinate("org", "foo", "1.2")],
        )

    def test_id(self):
        set1 = PinnedJarArtifactSet(
            pinned_coordinates=[
                M2Coordinate("org", "foo", "1.2"),
                M2Coordinate("org", "bar", "7.8"),
                M2Coordinate("org", "foo", "1.8", ext="tar"),
            ]
        )
        self.assertFalse(set1.id is None)
        self.assertFalse(set1._id is None)
        set1.put(M2Coordinate("hello", "there", "9"))
        self.assertTrue(set1._id is None)
        self.assertFalse(set1.id is None)
        set1.put(M2Coordinate("org", "foo", "1.2"))
        self.assertFalse(
            set1._id is None
        )  # Should be no change, because version was already there.
