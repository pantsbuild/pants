# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.awslambda.python.target_types import PythonAwsLambdaRuntime
from pants.build_graph.address import Address
from pants.engine.target import InvalidFieldException


@pytest.mark.parametrize(
    ["runtime", "expected_major", "expected_minor"],
    (
        # The available runtimes at the time of writing.
        # See https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html.
        ["python2.7", 2, 7],
        ["python3.6", 3, 6],
        ["python3.7", 3, 7],
        ["python3.8", 3, 8],
    ),
)
def test_to_interpreter_version(runtime, expected_major, expected_minor):
    assert (expected_major, expected_minor) == PythonAwsLambdaRuntime(
        raw_value=runtime, address=Address.parse("foo/bar:baz")
    ).to_interpreter_version()


@pytest.mark.parametrize(["invalid_runtime"], (["python88.99"], ["fooobar"],))
def test_runtime_validation(invalid_runtime):
    with pytest.raises(InvalidFieldException):
        PythonAwsLambdaRuntime(raw_value=invalid_runtime, address=Address.parse("foo/bar:baz"))
