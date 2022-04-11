# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.python.pip_requirement import PipRequirement


def test_parse_simple() -> None:
    req = PipRequirement.parse("Foo.bar==1.2.3")
    assert req.project_name == "Foo.bar"
    assert req.specs == [("==", "1.2.3")]
    assert req.url is None


def test_parse_old_style_vcs() -> None:
    req = PipRequirement.parse("git+https://github.com/django/django.git@stable/2.1.x#egg=Django")
    assert req.project_name == "Django"
    assert req.specs == []
    assert req.url == "git+https://github.com/django/django.git@stable/2.1.x"


def test_parse_pep440_vcs() -> None:
    req = PipRequirement.parse("Django@ git+https://github.com/django/django.git@stable/2.1.x")
    assert req.project_name == "Django"
    assert req.specs == []
    assert req.url == "git+https://github.com/django/django.git@stable/2.1.x"


def test_error() -> None:
    with pytest.raises(ValueError) as exc_info:
        PipRequirement.parse("not valid! === 3.1", description_of_origin="some origin")
    assert "Invalid requirement 'not valid! === 3.1' in some origin:" in str(exc_info.value)
