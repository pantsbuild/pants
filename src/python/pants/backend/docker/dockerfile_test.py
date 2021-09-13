# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.docker.dockerfile import Dockerfile
from pants.backend.docker.dockerfile_commands import BaseImage, Copy, EntryPoint


@pytest.mark.parametrize(
    "contents, expect",
    [
        (
            dedent(
                """\
                FROM baseimage:tag
                ENTRYPOINT ["main", "arg1", "arg2"]
                # ENV option=value
                COPY src/path/a dst/path/1
                COPY src/path/b dst/path/2
                # RUN some command
                """
            ),
            Dockerfile(
                [
                    BaseImage(image="baseimage", tag="tag"),
                    EntryPoint(
                        executable="main",
                        arguments=(
                            "arg1",
                            "arg2",
                        ),
                        form=EntryPoint.Form.EXEC,
                    ),
                    Copy(src=("src/path/a",), dest="dst/path/1"),
                    Copy(src=("src/path/b",), dest="dst/path/2"),
                ]
            ),
        ),
    ],
)
def test_parse_dockerfile(contents, expect):
    if isinstance(expect, Dockerfile):
        assert expect == Dockerfile.parse(contents)
    else:
        with expect:
            Dockerfile.parse(contents)


@pytest.mark.parametrize(
    "dockerfile, expect",
    [
        (
            Dockerfile(
                [
                    BaseImage("baseimage", tag="tag"),
                    EntryPoint(
                        executable="main",
                        arguments=(
                            "arg1",
                            "arg2",
                        ),
                        form=EntryPoint.Form.EXEC,
                    ),
                    Copy(("source/test.txt",), "/opt/dir/", chown="1", copy_from="other"),
                ]
            ),
            dedent(
                """\
                FROM baseimage:tag
                ENTRYPOINT ["main", "arg1", "arg2"]
                COPY --from=other --chown=1 source/test.txt /opt/dir/
                """
            ),
        ),
        (
            Dockerfile(
                [
                    EntryPoint(
                        executable="main",
                        arguments=(
                            "arg1",
                            "arg2",
                        ),
                        form=EntryPoint.Form.SHELL,
                    ),
                ]
            ),
            dedent(
                """\
                ENTRYPOINT main arg1 arg2
                """
            ),
        ),
    ],
)
def test_compile_dockerfile(dockerfile, expect):
    if isinstance(expect, str):
        assert expect.strip() == dockerfile.compile().strip()
    else:
        with expect:
            dockerfile.compile()


@pytest.mark.parametrize(
    "contents, expect",
    [
        (
            dedent(
                """\
                WORKDIR /src
                RUN command arg1 arg2\
                    --flags=here\
                    --on-several=lines\
                    should work

                # ignore comments

                COPY this here
            """
            ),
            [
                "WORKDIR /src",
                "RUN command arg1 arg2 --flags=here --on-several=lines should work",
                "COPY this here",
            ],
        ),
    ],
)
def test_dockerfile__iter_command_lines(contents, expect):
    if isinstance(expect, list):
        assert expect == list(Dockerfile._iter_command_lines(contents))
    else:
        with expect:
            list(Dockerfile._iter_command_lines(contents))
