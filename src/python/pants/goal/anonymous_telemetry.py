# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import cast

from humbug.consent import HumbugConsent
from humbug.report import HumbugReporter, Modes, Report

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


_bugout_access_token = "974b1acc-e052-4e5f-a45e-bae928e47bb0"
_telemetry_docs_referral = f"See {doc_url('anonymous-telemetry')} for details"


class AnonymousTelemetry(Subsystem):
    options_scope = "anonymous-telemetry"
    help = "Options related to sending anonymous stats to the Pants project, to aid development."

    enabled = BoolOption(
        default=False,
        help=softwrap(
            f"""
            Whether to send anonymous telemetry to the Pants project.

            Telemetry is sent asynchronously, with silent failure, and does not impact build times
            or outcomes.

            {_telemetry_docs_referral}.
            """
        ),
        advanced=True,
    )
    repo_id = StrOption(
        default=None,
        help=softwrap(
            f"""
            An anonymized ID representing this repo.

            For private repos, you likely want the ID to not be derived from, or algorithmically
            convertible to, anything identifying the repo.

            For public repos the ID may be visible in that repo's config file, so anonymity of the
            repo is not guaranteed (although user anonymity is always guaranteed).

            {_telemetry_docs_referral}.
            """
        ),
        advanced=True,
    )


class AnonymousTelemetryCallback(WorkunitsCallback):
    def __init__(self, unhashed_repo_id: str) -> None:
        super().__init__()
        self._unhashed_repo_id = unhashed_repo_id

    # Broken out into a staticmethod for testing.
    @staticmethod
    def validate_repo_id(unhashed_repo_id: str) -> bool:
        return re.match(r"^[a-zA-Z0-9-_]{30,60}$", unhashed_repo_id) is not None

    @property
    def can_finish_async(self) -> bool:
        # Because we don't log anything, it's safe to finish in the background.
        return True

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

        # Assemble and send the telemetry.
        # Note that this method is called with finished=True only after the
        # StreamingWorkunitHandler context ends, i.e., after end_run() has been called,
        # so the RunTracker will have had a chance to finalize its state.
        telemetry_data = context.run_tracker.get_anonymous_telemetry_data(self._unhashed_repo_id)
        # TODO: Add information about any errors that occurred.

        reporter = HumbugReporter(
            name="pantsbuild/pants",
            # We've already established consent at this point.
            consent=HumbugConsent(True),
            session_id=str(telemetry_data.get("run_id", uuid.uuid4())),
            bugout_token=_bugout_access_token,
            timeout_seconds=5,
            # We don't want to spawn a thread in the engine, and we're
            # already running in a background thread in pantsd.
            mode=Modes.SYNCHRONOUS,
        )

        # This is copied from humbug code, to ensure that future changes to humbug
        # don't add tags that inadvertently violate our anonymity promise.
        system_tags = [
            f"source:{reporter.name}",
            f"os:{reporter.system_information.os}",
            f"arch:{reporter.system_information.machine}",
            f"python:{reporter.system_information.python_version_major}",
            "python:{}.{}".format(
                reporter.system_information.python_version_major,
                reporter.system_information.python_version_minor,
            ),
            f"python:{reporter.system_information.python_version}",
            f"session:{reporter.session_id}",
        ]
        tags = (
            system_tags
            + [
                f"pants_version:{telemetry_data.get('pants_version')}",
                # This is hashed, unlike the contents of the unhashed_repo_id var.
                f"repo:{telemetry_data.get('repo_id', 'UNKNOWN')}",
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


@dataclass(frozen=True)
class AnonymousTelemetryCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of the WorkunitsCallback."""


@rule
def construct_callback(
    _: AnonymousTelemetryCallbackFactoryRequest, anonymous_telemetry: AnonymousTelemetry
) -> WorkunitsCallbackFactory:
    enabled = anonymous_telemetry.enabled
    unhashed_repo_id = anonymous_telemetry.repo_id

    if anonymous_telemetry.options.is_default("enabled"):
        logger.warning(
            softwrap(
                f"""
                Please either set `enabled = true` in the [anonymous-telemetry] section of
                pants.toml to enable sending anonymous stats to the Pants project to aid
                development, or set `enabled = false` to disable it. No telemetry sent
                for this run. An explicit setting will get rid of this message.
                {_telemetry_docs_referral}.
                """
            )
        )
    if enabled:
        if unhashed_repo_id is None:
            logger.error(
                softwrap(
                    f"""
                    Please set `repo_id = "<uuid>"` in the [anonymous-telemetry] section
                    of pants.toml, where `<uuid>` is some fixed random identifier, such as
                    one generated by uuidgen.

                    Example (using a randomly generated UUID):

                        [anonymous-telemetry]
                        repo_id = "{uuid.uuid4()}"

                    No telemetry will be sent for this run.
                    {_telemetry_docs_referral}.
                    """
                )
            )
            enabled = False
        elif not AnonymousTelemetryCallback.validate_repo_id(unhashed_repo_id):
            logger.error(
                softwrap(
                    """
                    The repo_id option in the [anonymous-telemetry] scope must be between 30 and
                    60 characters long, and consist of only alphanumeric characters, dashes
                    and underscores.
                    """
                )
            )
            enabled = False

    return WorkunitsCallbackFactory(
        lambda: AnonymousTelemetryCallback(cast(str, unhashed_repo_id)) if enabled else None
    )


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, AnonymousTelemetryCallbackFactoryRequest),
        *collect_rules(),
    ]
