# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.docker.parser.dockerfile_commands import (
    BaseImage,
    Copy,
    DockerfileCommand,
    EntryPoint,
    InvalidDockerfileCommandArgument,
)


@pytest.mark.parametrize(
    "command_line, expect",
    [
        ("FROM simple", BaseImage(image="simple")),
        ("FROM simple AS name", BaseImage(image="simple", name="name")),
        # case insensitive test
        ("from simple as name", BaseImage(image="simple", name="name")),
        ("FROM repo/proj:latest", BaseImage(image="repo/proj", tag="latest")),
        ("FROM repo/proj@12345", BaseImage(image="repo/proj", digest="12345")),
        ("FROM repo/proj err", pytest.raises(InvalidDockerfileCommandArgument)),
        (
            "FROM custom.registry:443/inhouse/registry",
            BaseImage(image="inhouse/registry", registry="custom.registry:443"),
        ),
        (
            "FROM --platform=linux/amd64 custom.registry:443/full/blown:1.2.3 AS stage",
            BaseImage(
                image="full/blown",
                tag="1.2.3",
                name="stage",
                registry="custom.registry:443",
                platform="linux/amd64",
            ),
        ),
        ("ENTRYPOINT command", EntryPoint("command", tuple(), form=EntryPoint.Form.SHELL)),
        (
            "ENTRYPOINT command param1 param2",
            EntryPoint(
                "command",
                arguments=(
                    "param1",
                    "param2",
                ),
                form=EntryPoint.Form.SHELL,
            ),
        ),
        ("""ENTRYPOINT ["command"]""", EntryPoint("command", tuple(), form=EntryPoint.Form.EXEC)),
        (
            """ENTRYPOINT ["command", "param1", "param2"]""",
            EntryPoint(
                "command",
                arguments=(
                    "param1",
                    "param2",
                ),
                form=EntryPoint.Form.EXEC,
            ),
        ),
        ("COPY foo /bar/", Copy(src=("foo",), dest="/bar/")),
        (
            "COPY foo bar baz quux/",
            Copy(
                src=(
                    "foo",
                    "bar",
                    "baz",
                ),
                dest="quux/",
            ),
        ),
        ("""COPY ["foo bar", "/foo-bar"]""", Copy(src=("foo bar",), dest="/foo-bar")),
        (
            "COPY --chown=bin:staff files* /somedir/",
            Copy(src=("files*",), dest="/somedir/", chown="bin:staff"),
        ),
        ("COPY --from=build app /bin/", Copy(src=("app",), dest="/bin/", copy_from="build")),
        (
            "COPY --chown=10:20 --from=build app /bin/",
            Copy(src=("app",), dest="/bin/", chown="10:20", copy_from="build"),
        ),
        (
            "COPY --from=other/image:1.0 --chown=order:test app /bin/",
            Copy(src=("app",), dest="/bin/", chown="order:test", copy_from="other/image:1.0"),
        ),
    ],
)
def test_decode_dockerfile_command(command_line, expect):
    if isinstance(expect, DockerfileCommand):
        assert expect == DockerfileCommand.decode(command_line)
    else:
        with expect:
            DockerfileCommand.decode(command_line)
