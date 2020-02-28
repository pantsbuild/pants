# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.option.custom_types import (
    DictValueComponent,
    ListValueComponent,
    UnsetBool,
    dict_with_files_option,
    dir_option,
    file_option,
    target_option,
)
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir


class OptionsFingerprinterTest(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.options_fingerprinter = OptionsFingerprinter(self.context().build_graph)

    def test_fingerprint_dict(self) -> None:
        d1 = {"b": 1, "a": 2}
        d2 = {"a": 2, "b": 1}
        d3 = {"a": 1, "b": 2}
        fp1, fp2, fp3 = (
            self.options_fingerprinter.fingerprint(DictValueComponent.create, d)
            for d in (d1, d2, d3)
        )
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)

    def test_fingerprint_dict_with_non_string_keys(self) -> None:
        d = {("a", 2): (3, 4)}
        fp = self.options_fingerprinter.fingerprint(DictValueComponent.create, d)
        self.assertEqual(fp, "3852a094612ce1c22c08ee2ddcdc03d09e87ad97")

    def test_fingerprint_list(self) -> None:
        l1 = [1, 2, 3]
        l2 = [1, 3, 2]
        fp1, fp2 = (
            self.options_fingerprinter.fingerprint(ListValueComponent.create, l) for l in (l1, l2)
        )
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_target_spec(self) -> None:
        specs = [":t1", ":t2"]
        payloads = [Payload() for i in range(2)]
        for i, (s, p) in enumerate(zip(specs, payloads)):
            p.add_field("foo", PrimitiveField(i))
            self.make_target(s, payload=p)
        s1, s2 = specs

        fp_spec = lambda spec: self.options_fingerprinter.fingerprint(target_option, spec)
        fp1 = fp_spec(s1)
        fp2 = fp_spec(s2)
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_target_spec_list(self) -> None:
        specs = [":t1", ":t2", ":t3"]
        payloads = [Payload() for i in range(3)]
        for i, (s, p) in enumerate(zip(specs, payloads)):
            p.add_field("foo", PrimitiveField(i))
            self.make_target(s, payload=p)
        s1, s2, s3 = specs

        fp_specs = lambda specs: self.options_fingerprinter.fingerprint(target_option, specs)
        fp1 = fp_specs([s1, s2])
        fp2 = fp_specs([s2, s1])
        fp3 = fp_specs([s1, s3])
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)

    def test_fingerprint_file(self) -> None:
        fp1, fp2, fp3 = (
            self.options_fingerprinter.fingerprint(file_option, self.create_file(f, contents=c))
            for (f, c) in (
                ("foo/bar.config", "blah blah blah"),
                ("foo/bar.config", "meow meow meow"),
                ("spam/egg.config", "blah blah blah"),
            )
        )
        self.assertNotEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)
        self.assertNotEqual(fp2, fp3)

    def test_fingerprint_file_outside_buildroot(self) -> None:
        with temporary_dir() as tmp:
            outside_buildroot = self.create_file(os.path.join(tmp, "foobar"), contents="foobar")
            with self.assertRaises(ValueError):
                self.options_fingerprinter.fingerprint(file_option, outside_buildroot)

    def test_fingerprint_file_list(self) -> None:
        f1, f2, f3 = (
            self.create_file(f, contents=c)
            for (f, c) in (
                ("foo/bar.config", "blah blah blah"),
                ("foo/bar.config", "meow meow meow"),
                ("spam/egg.config", "blah blah blah"),
            )
        )
        fp1 = self.options_fingerprinter.fingerprint(file_option, [f1, f2])
        fp2 = self.options_fingerprinter.fingerprint(file_option, [f2, f1])
        fp3 = self.options_fingerprinter.fingerprint(file_option, [f1, f3])
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)

    def test_fingerprint_primitive(self) -> None:
        fp1, fp2 = (self.options_fingerprinter.fingerprint("", v) for v in ("foo", 5))
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_unset_bool(self) -> None:
        fp1 = self.options_fingerprinter.fingerprint(UnsetBool, UnsetBool)
        fp2 = self.options_fingerprinter.fingerprint(UnsetBool, UnsetBool)
        self.assertEqual(fp1, fp2)

    def test_fingerprint_dir(self) -> None:
        d1 = self.create_dir("a")
        d2 = self.create_dir("b")
        d3 = self.create_dir("c")

        for f, c in [
            ("a/bar/bar.config", "blah blah blah"),
            ("a/foo/foo.config", "meow meow meow"),
            ("b/foo/foo.config", "meow meow meow"),
            ("b/bar/bar.config", "blah blah blah"),
            ("c/bar/bar.config", "blah meow blah"),
        ]:
            self.create_file(f, contents=c)

        dp1 = self.options_fingerprinter.fingerprint(dir_option, [d1])
        dp2 = self.options_fingerprinter.fingerprint(dir_option, [d1, d2])
        dp3 = self.options_fingerprinter.fingerprint(dir_option, [d2, d1])
        dp4 = self.options_fingerprinter.fingerprint(dir_option, [d3])

        self.assertEqual(dp1, dp1)
        self.assertEqual(dp2, dp2)
        self.assertNotEqual(dp1, dp3)
        self.assertNotEqual(dp1, dp4)
        self.assertNotEqual(dp2, dp3)

    def test_fingerprint_dict_with_files_order(self) -> None:
        f1, f2 = (
            self.create_file(f, contents=c)
            for (f, c) in (
                ("foo/bar.config", "blah blah blah"),
                ("foo/bar.config", "meow meow meow"),
            )
        )
        fp1 = self.options_fingerprinter.fingerprint(
            dict_with_files_option, {"properties": f"{f1},{f2}"}
        )
        fp2 = self.options_fingerprinter.fingerprint(
            dict_with_files_option, {"properties": f"{f2},{f1}"}
        )
        self.assertEqual(fp1, fp2)

    def test_fingerprint_dict_with_files_content_change(self) -> None:
        f1, f2 = (
            self.create_file(f, contents=c)
            for (f, c) in (
                ("foo/bar.config", "blah blah blah"),
                ("foo/bar.config", "meow meow meow"),
            )
        )

        fp1 = self.options_fingerprinter.fingerprint(
            dict_with_files_option, {"properties": f"{f1},{f2}"}
        )
        with open(f1, "w") as f:
            f.write("123")

        fp2 = self.options_fingerprinter.fingerprint(
            dict_with_files_option, {"properties": f"{f1},{f2}"}
        )
        self.assertNotEqual(fp1, fp2)
