# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime
import logging

from pants.backend.observability.opentelemetry.exception_logging_processor import (
    ExceptionLoggingProcessor,
)
from pants.backend.observability.opentelemetry.opentelemetry_config import OtlpParameters
from pants.backend.observability.opentelemetry.opentelemetry_processor import get_processor
from pants.backend.observability.opentelemetry.single_threaded_processor import (
    SingleThreadedProcessor,
)
from pants.backend.observability.opentelemetry.subsystem import TelemetrySubsystem
from pants.backend.observability.opentelemetry.workunit_handler import TelemetryWorkunitsCallback
from pants.base.build_root import BuildRoot
from pants.core.util_rules.env_vars import (
    environment_vars_subset,
)
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.streaming_workunit_handler import (
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class TelemetryWorkunitsCallbackFactoryRequest(WorkunitsCallbackFactoryRequest):
    pass


@rule
async def telemetry_workunits_callback_factory_request(
    _: TelemetryWorkunitsCallbackFactoryRequest,
    telemetry: TelemetrySubsystem,
    build_root: BuildRoot,
) -> WorkunitsCallbackFactory:
    logger.debug(
        f"telemetry_workunits_callback_factory_request: telemetry.enabled={telemetry.enabled}; telemetry.exporter={telemetry.exporter}; "
        f"bool(telemetry.exporter)={bool(telemetry.exporter)}"
    )

    traceparent_env_var: str | None = None
    otel_resource_attributes: str | None = None
    if telemetry.enabled and telemetry.exporter:
        env_vars = await environment_vars_subset(
            EnvironmentVarsRequest(["TRACEPARENT", "OTEL_RESOURCE_ATTRIBUTES"]), **implicitly()
        )  # type: ignore[arg-type,unused-ignore]
        if telemetry.parse_traceparent:
            traceparent_env_var = env_vars.get("TRACEPARENT")
            logger.debug(f"Found TRACEPARENT: {traceparent_env_var}")
        otel_resource_attributes = env_vars.get("OTEL_RESOURCE_ATTRIBUTES")
        logger.debug(f"Found OTEL_RESOURCE_ATTRIBUTES: {otel_resource_attributes}")

    def workunits_callback_factory() -> WorkunitsCallback | None:
        if not telemetry.enabled or not telemetry.exporter:
            logger.debug("Skipping enabling OpenTelemetry work unit handler.")
            return None

        logger.debug("Enabling OpenTelemetry work unit handler.")

        otel_processor = get_processor(
            span_exporter_name=telemetry.exporter,
            otlp_parameters=OtlpParameters(
                endpoint=telemetry.exporter_endpoint,
                traces_endpoint=telemetry.exporter_traces_endpoint,
                certificate_file=telemetry.exporter_certificate_file,
                client_key_file=telemetry.exporter_client_key_file,
                client_certificate_file=telemetry.exporter_client_certificate_file,
                headers=telemetry.exporter_headers,
                timeout=telemetry.exporter_timeout,
                compression=(
                    telemetry.exporter_compression.value if telemetry.exporter_compression else None
                ),
            ),
            build_root=build_root.pathlib_path,
            traceparent_env_var=traceparent_env_var,
            otel_resource_attributes=otel_resource_attributes,
            json_file=telemetry.json_file,
            trace_link_template=telemetry.trace_link_template,
        )

        processor = SingleThreadedProcessor(
            ExceptionLoggingProcessor(otel_processor, name="OpenTelemetry")
        )

        processor.initialize()

        return TelemetryWorkunitsCallback(
            processor=processor,
            finish_timeout=finish_timeout,
            async_completion=telemetry.async_completion,
        )

    finish_timeout = datetime.timedelta(seconds=telemetry.finish_timeout)
    return WorkunitsCallbackFactory(
        callback_factory=workunits_callback_factory,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(WorkunitsCallbackFactoryRequest, TelemetryWorkunitsCallbackFactoryRequest),
    )
