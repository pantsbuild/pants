# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from enum import Enum
from typing import Match, Optional, Tuple, cast

from pants.backend.python.target_types import (
    PexCompletePlatformsField,
    PexLayoutField,
    PythonResolveField,
)
from pants.backend.python.util_rules.faas import (
    PythonFaaSCompletePlatforms,
    PythonFaaSDependencies,
    PythonFaaSHandlerField,
    PythonFaaSPex3VenvCreateExtraArgsField,
    PythonFaaSRuntimeField,
)
from pants.backend.python.util_rules.faas import rules as faas_rules
from pants.core.goals.package import OutputPathField
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules
from pants.engine.target import COMMON_TARGET_FIELDS, InvalidFieldException, StringField, Target
from pants.util.docutil import doc_url
from pants.util.strutil import help_text, softwrap


class PythonGoogleCloudFunctionHandlerField(PythonFaaSHandlerField):
    # GCP requires "Your main file must be named main.py"
    # https://cloud.google.com/functions/docs/writing#directory-structure-python
    reexported_handler_module = "main"

    help = help_text(
        f"""
        Entry point to the Google Cloud Function handler.

        {PythonFaaSHandlerField.help}

        This is re-exported at `{reexported_handler_module}.handler` in the resulting package to
        used as the configured handler of the Google Cloud Function in GCP.  It can also be accessed
        under its source-root-relative module path, for example: `path.to.module.handler_func`.
        """
    )


class PythonGoogleCloudFunctionRuntimes(Enum):
    PYTHON_37 = "python37"
    PYTHON_38 = "python38"
    PYTHON_39 = "python39"
    PYTHON_310 = "python310"
    PYTHON_311 = "python311"
    PYTHON_312 = "python312"


class PythonGoogleCloudFunctionRuntime(PythonFaaSRuntimeField):
    PYTHON_RUNTIME_REGEX = r"^python(?P<major>\d)(?P<minor>\d+)$"

    valid_choices = PythonGoogleCloudFunctionRuntimes
    help = help_text(
        """
        The identifier of the Google Cloud Function runtime to target (pythonXY). See
        https://cloud.google.com/functions/docs/concepts/python-runtime.

        In general you'll want to define either a `runtime` or one `complete_platforms` but not
        both. Specifying a `runtime` is simpler, but less accurate. If you have issues either
        packaging the Google Cloud Function PEX or running it as a deployed Google Cloud Function,
        you should try using `complete_platforms` instead.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not re.match(cls.PYTHON_RUNTIME_REGEX, value):
            raise InvalidFieldException(
                f"The `{cls.alias}` field in target at {address} must be of the form pythonXY, "
                f"but was {value}."
            )
        return value

    def to_interpreter_version(self) -> Optional[Tuple[int, int]]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        if self.value is None:
            return None
        mo = cast(Match, re.match(self.PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))

    @classmethod
    def from_interpreter_version(cls, py_major: int, py_minor) -> str:
        return f"python{py_major}{py_minor}"


class GoogleCloudFunctionTypes(Enum):
    EVENT = "event"
    HTTP = "http"


class PythonGoogleCloudFunctionType(StringField):
    alias = "type"
    required = True
    valid_choices = GoogleCloudFunctionTypes
    help = help_text(
        """
        The trigger type of the cloud function. Can either be `'event'` or `'http'`.
        See https://cloud.google.com/functions/docs/concepts/python-runtime for reference to
        `--trigger-http`.
        """
    )


class PythonGoogleCloudFunction(Target):
    alias = "python_google_cloud_function"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        PythonFaaSDependencies,
        PythonGoogleCloudFunctionHandlerField,
        PythonGoogleCloudFunctionRuntime,
        PythonFaaSCompletePlatforms,
        PythonGoogleCloudFunctionType,
        PythonFaaSPex3VenvCreateExtraArgsField,
        PythonResolveField,
        EnvironmentField,
        PexLayoutField,
    )
    help = help_text(
        f"""
        A self-contained Python function suitable for uploading to Google Cloud Function.

        See {doc_url('docs/python/integrations/google-cloud-functions')}.
        """
    )

    def validate(self) -> None:
        has_runtime = self[PythonGoogleCloudFunctionRuntime].value is not None
        has_complete_platforms = self[PexCompletePlatformsField].value is not None

        runtime_alias = self[PythonGoogleCloudFunctionRuntime].alias
        complete_platforms_alias = self[PexCompletePlatformsField].alias

        if has_runtime and has_complete_platforms:
            raise ValueError(
                softwrap(
                    f"""
                    The `{complete_platforms_alias}` takes precedence over the `{runtime_alias}` field, if
                    it is set. Remove the `{runtime_alias}` field to only use the `{complete_platforms_alias}`
                    value, or remove the `{complete_platforms_alias}` field to use the default platform
                    implied by `{runtime_alias}`.
                    """
                ),
            )


def rules():
    return (
        *collect_rules(),
        *faas_rules(),
    )
