# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import cast

from humbug.consent import HumbugConsent  # type: ignore
from humbug.report import Modes, Report, Reporter  # type: ignore

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.docutil import bracketed_docs_url

logger = logging.getLogger(__name__)


_bugout_access_token = "3ae76900-9a68-4a87-a127-7c9f179d7272"
_bugout_journal_id = "801e9b3c-6b03-40a7-870f-5b25d326da66"
_telemetry_docs_url = bracketed_docs_url("anonymous-telemetry")
_telemetry_docs_referral = f"See {_telemetry_docs_url} for details"


class AnonymousTelemetry(Subsystem):
    options_scope = "anonymous-telemetry"
    help = "Options related to sending anonymous stats to the Pants project, to aid development."

    @classmethod
    def register_options(cls, register):
        register(
            "--enabled",
            advanced=True,
            type=bool,
            default=False,
            help=(
                f"Whether to send anonymous telemetry to the Pants project.\nTelemetry is sent "
                f"asynchronously, with silent failure, and does not impact build times or "
                f"outcomes.\n{_telemetry_docs_referral}."
            ),
        )
        register(
            "--repo-id",
            advanced=True,
            type=str,
            default=None,
            help=(
                f"An anonymized ID representing this repo.\nFor private repos, you likely want the "
                f"ID to not be derived from, or algorithmically convertible to, anything "
                f"identifying the repo.\nFor public repos the ID may be visible in that repo's "
                f"config file, so anonymity of the repo is not guaranteed (although user anonymity "
                f"is always guaranteed).\n{_telemetry_docs_referral}."
            ),
        )

    @property
    def enabled(self) -> bool:
        return cast(bool, self.options.enabled)

    @property
    def repo_id(self) -> str | None:
        return cast("str | None", self.options.repo_id)


class AnonymousTelemetryCallback(WorkunitsCallback):
    def __init__(self, anonymous_telemetry: AnonymousTelemetry) -> None:
        super().__init__()
        self._anonymous_telemetry = anonymous_telemetry

    @property
    def can_finish_async(self) -> bool:
        # Because we don't log anything, it's safe to finish in the background.
        return True

    @staticmethod
    def validate_repo_id(repo_id: str) -> bool:
        is_valid = re.match(r"^[a-zA-Z0-9-_]{30,60}$", repo_id) is not None
        if not is_valid:
            logger.error(
                "The repo_id must be between 30 and 60 characters long, and consist of only "
                "alphanumeric characters, dashes and underscores."
            )
        return is_valid

    def __call__(
        self,
        *,
        started_workunits: tuple[Workunit, ...],
        completed_workunits: tuple[Workunit, ...],
        finished: bool,
        context: StreamingWorkunitContext,
    ) -> None:
        if not finished:
            return

        if self._anonymous_telemetry.options.is_default("enabled"):
            logger.warning(
                f"Please either set `enabled = true` in the [anonymous-telemetry] section of "
                f"pants.toml to enable sending anonymous stats to the Pants project to aid "
                f"development, or set `enabled = false` to disable it. No telemetry sent "
                f"for this run. An explicit setting will get rid of this message. "
                f"{_telemetry_docs_referral}."
            )

        if self._anonymous_telemetry.enabled:
            repo_id = self._anonymous_telemetry.repo_id
            if repo_id is None:
                logger.error(
                    f'Please set `repo_id = "<uuid>"` in the [anonymous-telemetry] section '
                    f"of pants.toml, where `<uuid>` is some fixed random identifier, such as "
                    f"one generated by uuidgen. No telemetry sent for this run. "
                    f"{_telemetry_docs_referral}."
                )
            elif self.validate_repo_id(repo_id):
                # Assemble and send the telemetry.
                # Note that this method is called with finished=True only after the
                # StreamingWorkunitHandler context ends, i.e., after end_run() has been called,
                # so the RunTracker will have had a chance to finalize its state.
                telemetry_data = context.run_tracker.get_anonymous_telemetry_data(repo_id)
                # TODO: Add information about any errors that occurred.

                reporter = Reporter(
                    name="pantsbuild/pants",
                    # We've already established consent at this point.
                    consent=HumbugConsent(True),
                    session_id=telemetry_data.get("run_id", str(uuid.uuid4())),
                    bugout_token=_bugout_access_token,
                    bugout_journal_id=_bugout_journal_id,
                    timeout_seconds=5,
                    # We don't want to spawn a thread in the engine, and we're
                    # already running in a background thread in pantsd.
                    mode=Modes.SYNCHRONOUS,
                )

                # This is copied from humbug code, to ensure that future changes to humbug
                # don't add tags that inadvertently violate our anonymity promise.
                system_tags = [
                    "humbug",
                    "source:{}".format(reporter.name),
                    "os:{}".format(reporter.system_information.os),
                    "arch:{}".format(reporter.system_information.machine),
                    "python:{}".format(reporter.system_information.python_version_major),
                    "python:{}.{}".format(
                        reporter.system_information.python_version_major,
                        reporter.system_information.python_version_minor,
                    ),
                    "python:{}".format(reporter.system_information.python_version),
                    "session:{}".format(reporter.session_id),
                ]
                tags = (
                    system_tags
                    + [
                        f"pants_version:{telemetry_data.get('pants_version')}",
                        # This is hashed, unlike the contents of the repo_id var.
                        f"repo:{telemetry_data.get('repo_id')}",
                        f"user:{telemetry_data.get('user_id', 'UNKNOWN')}",
                        f"machine:{telemetry_data.get('machine_id', 'UNKNOWN')}",
                        f"duration:{telemetry_data.get('duration', '0')}",
                        f"outcome:{telemetry_data.get('outcome', 'UNKNOWN')}",
                    ]
                    + [f"goal:{goal}" for goal in telemetry_data.get("standard_goals", [])]
                )

                report = Report(
                    title=f"pants run {reporter.session_id}",
                    tags=tags,
                    content=json.dumps(telemetry_data, sort_keys=True),
                )
                reporter.publish(report)


class AnonymousTelemetryCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of the WorkunitsCallback."""


@rule
def construct_callback(
    _: AnonymousTelemetryCallbackFactoryRequest, anonymous_telemetry: AnonymousTelemetry
) -> WorkunitsCallbackFactory:
    return WorkunitsCallbackFactory(lambda: AnonymousTelemetryCallback(anonymous_telemetry))


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, AnonymousTelemetryCallbackFactoryRequest),
        *collect_rules(),
    ]
