# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.option.custom_types import (
    DictValueComponent,
    ListValueComponent,
    UnsetBool,
    dir_option,
    file_option,
)
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def test_fingerprint_dict() -> None:
    d1 = {"b": 1, "a": 2}
    d2 = {"a": 2, "b": 1}
    d3 = {"a": 1, "b": 2}
    fp1, fp2, fp3 = (
        OptionsFingerprinter().fingerprint(DictValueComponent.create, d) for d in (d1, d2, d3)
    )
    assert fp1 == fp2
    assert fp1 != fp3


def test_fingerprint_list() -> None:
    l1 = [1, 2, 3]
    l2 = [1, 3, 2]
    fp1, fp2 = (OptionsFingerprinter().fingerprint(ListValueComponent.create, l) for l in (l1, l2))
    assert fp1 != fp2


def test_fingerprint_file(rule_runner: RuleRunner) -> None:
    fp1, fp2, fp3 = (
        OptionsFingerprinter().fingerprint(file_option, rule_runner.write_files({f: c})[0])
        for (f, c) in (
            ("foo/bar.config", "blah blah blah"),
            ("foo/bar.config", "meow meow meow"),
            ("spam/egg.config", "blah blah blah"),
        )
    )
    assert fp1 != fp2
    assert fp1 != fp3
    assert fp2 != fp3


def test_fingerprint_file_outside_buildroot(tmp_path: Path, rule_runner: RuleRunner) -> None:
    outside_buildroot = rule_runner.write_files({(tmp_path / "foobar").as_posix(): "foobar"})[0]
    with pytest.raises(ValueError):
        OptionsFingerprinter().fingerprint(file_option, outside_buildroot)


def test_fingerprint_file_list(rule_runner: RuleRunner) -> None:
    f1, f2, f3 = (
        rule_runner.write_files({f: c})[0]
        for (f, c) in (
            ("foo/bar.config", "blah blah blah"),
            ("foo/bar.config", "meow meow meow"),
            ("spam/egg.config", "blah blah blah"),
        )
    )
    fp1 = OptionsFingerprinter().fingerprint(file_option, [f1, f2])
    fp2 = OptionsFingerprinter().fingerprint(file_option, [f2, f1])
    fp3 = OptionsFingerprinter().fingerprint(file_option, [f1, f3])
    assert fp1 == fp2
    assert fp1 != fp3


def test_fingerprint_primitive() -> None:
    fp1, fp2 = (OptionsFingerprinter().fingerprint("", v) for v in ("foo", 5))
    assert fp1 != fp2


def test_fingerprint_unset_bool() -> None:
    fp1 = OptionsFingerprinter().fingerprint(UnsetBool, UnsetBool)
    fp2 = OptionsFingerprinter().fingerprint(UnsetBool, UnsetBool)
    assert fp1 == fp2


def test_fingerprint_dir(rule_runner: RuleRunner) -> None:
    d1 = rule_runner.create_dir("a")
    d2 = rule_runner.create_dir("b")
    d3 = rule_runner.create_dir("c")

    rule_runner.write_files(
        {
            "a/bar/bar.config": "blah blah blah",
            "a/foo/foo.config": "meow meow meow",
            "b/foo/foo.config": "meow meow meow",
            "b/bar/bar.config": "blah blah blah",
            "c/bar/bar.config": "blah meow blah",
        }
    )

    dp1 = OptionsFingerprinter().fingerprint(dir_option, [d1])
    dp2 = OptionsFingerprinter().fingerprint(dir_option, [d1, d2])
    dp3 = OptionsFingerprinter().fingerprint(dir_option, [d2, d1])
    dp4 = OptionsFingerprinter().fingerprint(dir_option, [d3])

    assert dp1 == dp1
    assert dp2 == dp2
    assert dp1 != dp3
    assert dp1 != dp4
    assert dp2 != dp3
