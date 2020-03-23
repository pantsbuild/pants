# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.scala_exclude import ScalaExclude
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.base.build_environment import get_buildroot
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.subsystem.util import init_subsystem


class JarDependencyTest(unittest.TestCase):
    def test_jar_dependency_excludes_change_hash(self):
        with_excludes = self._mkjardep()
        without_excludes = self._mkjardep(excludes=[])
        self.assertNotEqual(with_excludes.cache_key(), without_excludes.cache_key())

    def test_jar_dependency_copy(self):
        self._test_copy(self._mkjardep())

    def test_scala_jar_dependency_copy(self):
        self._test_copy(self._mkjardep(tpe=ScalaJarDependency))

    def test_scala_exclude(self):
        init_subsystem(ScalaPlatform)

        name = "foo_lib"
        suffixed_name = ScalaPlatform.global_instance().suffix_version(name)

        self.assertEqual(suffixed_name, ScalaExclude(org="example.com", name=name).name)

    def test_get_url(self):
        """Test using relative url and absolute url are equivalent."""
        abs_url = f"file://{get_buildroot()}/a/b/c"
        rel_url = "file:c"
        base_path = "a/b"

        jar_with_rel_url = self._mkjardep(url=rel_url, base_path=base_path)
        self.assertEqual(abs_url, jar_with_rel_url.get_url())
        self.assertEqual(rel_url, jar_with_rel_url.get_url(relative=True))

        jar_with_abs_url = self._mkjardep(url=abs_url, base_path=base_path)
        self.assertEqual(abs_url, jar_with_abs_url.get_url())
        self.assertEqual(rel_url, jar_with_abs_url.get_url(relative=True))

    def _test_copy(self, original):
        # A no-op clone results in an equal object.
        self.assertEqual(original, original.copy())
        # Excludes included in equality.
        excludes_added = original.copy(excludes=[Exclude(org="com.blah", name="blah")])
        self.assertNotEqual(original, excludes_added)
        # Clones are equal with equal content.
        self.assertEqual(original.copy(rev="1.2.3"), original.copy(rev="1.2.3"))

    def _mkjardep(
        self,
        org="foo",
        name="foo",
        excludes=(Exclude(org="example.com", name="foo-lib"),),
        tpe=JarDependency,
        **kwargs,
    ):
        return tpe(org=org, name=name, excludes=excludes, **kwargs)
