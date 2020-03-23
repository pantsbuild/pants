# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.base.revision import Revision


class RevisionTest(unittest.TestCase):
    pass


class SemverTest(RevisionTest):
    def test_bad(self):
        for bad_rev in ("a.b.c", "1.b.c", "1.2.c", "1.2.3;4", "1.2.3;4+5"):
            with self.assertRaises(Revision.BadRevision):
                Revision.semver(bad_rev)

    def test_simple(self):
        assert Revision.semver("1.2.3") == Revision.semver("1.2.3")
        assert Revision.semver("1.2.3").components == [1, 2, 3, None, None]

        assert Revision.semver("1.2.3") > Revision.semver("1.2.2")
        assert Revision.semver("1.3.0") > Revision.semver("1.2.2")
        assert Revision.semver("1.3.10") > Revision.semver("1.3.2")
        assert Revision.semver("2.0.0") > Revision.semver("1.3.2")

    def test_pre_release(self):
        assert Revision.semver("1.2.3-pre1.release.1") == Revision.semver("1.2.3-pre1.release.1")

        assert Revision.semver("1.2.3-pre1.release.1").components == [
            1,
            2,
            3,
            "pre1",
            "release",
            1,
            None,
        ]

        assert Revision.semver("1.2.3-pre1.release.1") < Revision.semver("1.2.3-pre2.release.1")

        assert Revision.semver("1.2.3-pre1.release.2") < Revision.semver("1.2.3-pre1.release.10")

        assert Revision.semver("1.2.3") < Revision.semver("1.2.3-pre2.release.1")

    def test_build(self):
        # TODO in semver 2.0.0, build data has no effect on precedence.
        assert Revision.semver("1.2.3+pre1.release.1") == Revision.semver("1.2.3+pre1.release.1")
        assert Revision.semver("1.2.3+pre1.release.1").components == [
            1,
            2,
            3,
            None,
            "pre1",
            "release",
            1,
        ]

        assert Revision.semver("1.2.3+pre1.release.1") < Revision.semver("1.2.3+pre2.release.1")
        assert Revision.semver("1.2.3+pre1.release.2") < Revision.semver("1.2.3+pre1.release.10")
        assert Revision.semver("1.2.3") < Revision.semver("1.2.3+pre2.release.1")
        assert Revision.semver("1.2.3+pre1.release.2") < Revision.semver("1.2.3-pre1.release.2")

    def test_pre_release_build(self):
        assert Revision.semver("1.2.3-pre1.release.1+1") == Revision.semver(
            "1.2.3-pre1.release.1+1"
        )
        assert Revision.semver("1.2.3-pre1.release.1+1").components == [
            1,
            2,
            3,
            "pre1",
            "release",
            1,
            1,
        ]

        assert Revision.semver("1.2.3-pre1.release.1") < Revision.semver("1.2.3-pre2.release.1+1")

        assert Revision.semver("1.2.3-pre1.release.2") > Revision.semver("1.2.3-pre1.release.1+1")

        assert Revision.semver("1.2.3") < Revision.semver("1.2.3-pre2.release.2+1.foo")

        assert Revision.semver("1.2.3-pre1.release.2+1") < Revision.semver(
            "1.2.3-pre1.release.2+1.foo"
        )

        assert Revision.semver("1.2.3-pre1.release.2+1") < Revision.semver("1.2.3-pre1.release.2+2")


class LenientTest(RevisionTest):
    def test(self):
        # TODO we may want to change these particular cases
        assert Revision.lenient("1") > Revision.lenient("1.0.0")
        assert Revision.lenient("1.0") > Revision.lenient("1.0.0")

        assert Revision.lenient("1") < Revision.lenient("1.0.1")
        assert Revision.lenient("1.0") < Revision.lenient("1.0.1")
        assert Revision.lenient("1.0.1") < Revision.lenient("1.0.2")

        assert Revision.lenient("1.2.3").components == [1, 2, 3]
        assert Revision.lenient("1.2.3-SNAPSHOT-eabc").components == [1, 2, 3, "SNAPSHOT", "eabc"]
        assert Revision.lenient("1.2.3-SNAPSHOT4").components == [1, 2, 3, "SNAPSHOT", 4]

        assert Revision.lenient("a") < Revision.lenient("b")
        assert Revision.lenient("1") < Revision.lenient("2")
        assert Revision.lenient("1") < Revision.lenient("a")

        assert Revision.lenient("1.2.3") == Revision.lenient("1.2.3")
        assert Revision.lenient("1.2.3") < Revision.lenient("1.2.3-SNAPSHOT")
        assert Revision.lenient("1.2.3-SNAPSHOT") < Revision.lenient("1.2.3-SNAPSHOT-abc")
        assert Revision.lenient("1.2.3-SNAPSHOT-abc") < Revision.lenient("1.2.3-SNAPSHOT-bcd")
        assert Revision.lenient("1.2.3-SNAPSHOT-abc6") < Revision.lenient("1.2.3-SNAPSHOT-abc10")
