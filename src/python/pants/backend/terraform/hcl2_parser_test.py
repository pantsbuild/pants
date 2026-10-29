# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from pathlib import Path, PurePath
from types import ModuleType
from typing import Any

import pytest

from pants.backend.terraform.hcl2_parser import LEGACY_HCL2_MARKER, main, resolve_pure_path


def test_resolve_pure_path() -> None:
    assert resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("../../grok")) == PurePath(
        "foo/bar/grok"
    )
    assert resolve_pure_path(
        PurePath("foo/bar/hello/world"), PurePath("../../../../grok")
    ) == PurePath("grok")
    with pytest.raises(ValueError):
        resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("../../../../../grok"))
    assert resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("./grok")) == PurePath(
        "foo/bar/hello/world/grok"
    )


PARSED_MODULE = {"module": [{"grok": {"source": "../grok"}}]}


def run_main_with_fake_hcl2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **hcl2_attrs: Any
) -> None:
    hcl2 = ModuleType("hcl2")
    hcl2.__dict__.update(hcl2_attrs)
    monkeypatch.setitem(sys.modules, "hcl2", hcl2)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "main.tf").write_text('module "grok" {\n  source = "../grok"\n}\n')
    main(["foo/main.tf"])


def test_main_strips_string_quotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    class SerializationOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    def loads(content: str, *, serialization_options: SerializationOptions) -> dict:
        assert serialization_options.kwargs == {"strip_string_quotes": True}
        return PARSED_MODULE

    run_main_with_fake_hcl2(
        monkeypatch, tmp_path, loads=loads, SerializationOptions=SerializationOptions
    )

    out, err = capsysbinary.readouterr()
    assert out.splitlines() == [b"grok"]
    assert LEGACY_HCL2_MARKER not in err


def test_main_falls_back_for_legacy_hcl2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    # python-hcl2 before 8.x has no `SerializationOptions`, and strips the quotes itself.
    def loads(content: str) -> dict:
        return PARSED_MODULE

    run_main_with_fake_hcl2(monkeypatch, tmp_path, loads=loads)

    out, err = capsysbinary.readouterr()
    assert out.splitlines() == [b"grok"]
    assert LEGACY_HCL2_MARKER in err
