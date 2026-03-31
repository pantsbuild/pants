# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

from pants.util.pip_requirement import PipRequirement
from pants.util.requirements import parse_requirements_file


def test_parse_requirements_file() -> None:
    content = dedent(
        r"""\
        # Comment.
        --find-links=https://duckduckgo.com
        -r more_reqs.txt
        ansicolors>=1.18.0
        Django==3.2 ; python_version>'3'
        Un-Normalized-PROJECT  # Inline comment.
        pip@ git+https://github.com/pypa/pip.git
        setuptools==54.1.2; python_version >= "3.6" \
            --hash=sha256:dd20743f36b93cbb8724f4d2ccd970dce8b6e6e823a13aa7e5751bb4e674c20b \
            --hash=sha256:ebd0148faf627b569c8d2a1b20f5d3b09c873f12739d71c7ee88f037d5be82ff
        wheel==1.2.3 --hash=sha256:dd20743f36b93cbb8724f4d2ccd970dce8b6e6e823a13aa7e5751bb4e674c20b
        """
    )
    assert set(parse_requirements_file(content, rel_path="foo.txt")) == {
        PipRequirement.parse("ansicolors>=1.18.0"),
        PipRequirement.parse("Django==3.2 ; python_version>'3'"),
        PipRequirement.parse("Un-Normalized-PROJECT"),
        PipRequirement.parse("pip@ git+https://github.com/pypa/pip.git"),
        PipRequirement.parse("setuptools==54.1.2; python_version >= '3.6'"),
        PipRequirement.parse("wheel==1.2.3"),
    }
