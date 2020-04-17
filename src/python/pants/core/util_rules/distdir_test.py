# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.core.util_rules.distdir import DistDir, InvalidDistDir, validate_distdir


def test_distdir():
    buildroot = Path("/buildroot")
    assert DistDir(relpath=Path("dist")) == validate_distdir(Path("dist"), buildroot)
    assert DistDir(relpath=Path("dist")) == validate_distdir(Path("/buildroot/dist"), buildroot)
    with pytest.raises(InvalidDistDir):
        validate_distdir(Path("/other/dist"), buildroot)
