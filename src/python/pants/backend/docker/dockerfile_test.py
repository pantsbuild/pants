# -*- mode: python -*-
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
            
import pytest
from pants.backend.docker.dockerfile import Dockerfile, DockerfileCommand, BaseImage, InvalidDockerfileCommandArgument, EntryPoint, Copy
from textwrap import dedent


@pytest.mark.parametrize('command_line, expect', [
    ("FROM simple", BaseImage(image="simple")),
    ("FROM repo/proj:latest", BaseImage(image="repo/proj", tag="latest")),
    ("FROM repo/proj@12345", BaseImage(image="repo/proj", digest="12345")),
    ("FROM repo/proj err", pytest.raises(InvalidDockerfileCommandArgument)),
    ("FROM custom.registry:443/inhouse/registry", BaseImage(image="inhouse/registry", registry="custom.registry:443")),
    (
        "FROM --platform=linux/amd64 custom.registry:443/full/blown:1.2.3 AS stage",
        BaseImage(image="full/blown", tag="1.2.3", name="stage", registry="custom.registry:443", platform="linux/amd64")
    ),
    ("ENTRYPOINT command", EntryPoint("command", tuple(), form=EntryPoint.Form.SHELL)),
    (
        "ENTRYPOINT command param1 param2",
        EntryPoint("command", arguments=("param1", "param2",), form=EntryPoint.Form.SHELL),
    ),
    ("""ENTRYPOINT ["command"]""", EntryPoint("command", tuple(), form=EntryPoint.Form.EXEC)),
    (
        """ENTRYPOINT ["command", "param1", "param2"]""",
        EntryPoint("command", arguments=("param1", "param2",), form=EntryPoint.Form.EXEC),
    ),
    ("COPY foo /bar/", Copy(src=("foo",), dest="/bar/")),
    ("COPY foo bar baz quux/", Copy(src=("foo", "bar", "baz",), dest="quux/")),
    ("""COPY ["foo bar", "/foo-bar"]""", Copy(src=("foo bar",), dest="/foo-bar")),
    ("COPY --chown=bin:staff files* /somedir/", Copy(src=("files*",), dest="/somedir/", chown="bin:staff")),
])
def test_decode_dockerfile_command(command_line, expect):
    if isinstance(expect, DockerfileCommand):
        assert expect == DockerfileCommand.decode(command_line)
    else:
        with expect:
            DockerfileCommand.decode(command_line)


@pytest.mark.parametrize('contents, expect', [
    (
        dedent(
            """\
            FROM baseimage:tag
            ENTRYPOINT ["main", "arg1", "arg2"]
            # ENV option=value
            # COPY src/path/a dst/path/1
            # COPY src/path/b dst/path/2
            # RUN some command
            """
        ),
        Dockerfile(
            baseimage=BaseImage(image="baseimage", tag="tag"),
            entry_point=EntryPoint(executable="main", arguments=("arg1", "arg2",), form=EntryPoint.Form.EXEC),
        ),
    ),
])
def test_parse_dockerfile(contents, expect):
    if isinstance(expect, Dockerfile):
        assert expect == Dockerfile.parse(contents)
    else:
        with expect:
            Dockerfile.parse(contents)


@pytest.mark.parametrize('dockerfile, expect', [
    (
        Dockerfile(
            baseimage=BaseImage("baseimage", tag="tag"),
            entry_point=EntryPoint(executable="main", arguments=("arg1", "arg2",), form=EntryPoint.Form.EXEC),
            copy=(
                Copy(("source/test.txt",), "/opt/dir/", chown="1"),
            ),
        ),
        dedent(
            """\
            FROM baseimage:tag
            ENTRYPOINT ["main", "arg1", "arg2"]
            COPY --chown=1 source/test.txt /opt/dir/
            """
        ),
    ),
    (
        Dockerfile(
            entry_point=EntryPoint(executable="main", arguments=("arg1", "arg2",), form=EntryPoint.Form.SHELL),
        ),
        dedent(
            """\
            ENTRYPOINT main arg1 arg2
            """
        ),
    ),
])
def test_compile_dockerfile(dockerfile, expect):
    if isinstance(expect, str):
        assert expect.strip() == dockerfile.compile().strip()
    else:
        with expect:
            dockerfile.compile()


@pytest.mark.parametrize('contents, expect', [
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
])
def test_dockerfile_command_lines(contents, expect):
    if isinstance(expect, list):
        assert expect == list(Dockerfile._iter_command_lines(contents))
    else:
        with expect:
            list(Dockerfile._iter_command_lines(contents))
