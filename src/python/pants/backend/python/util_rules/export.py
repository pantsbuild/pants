# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable, Type

from typing_extensions import Protocol

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField, MainSpecification
from pants.backend.python.util_rules.export_types import ExportRules as ExportRules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.backend.python.util_rules.pex import PexRequest
from pants.engine.internals.native_engine import Digest
from pants.engine.rules import rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.memo import memoized
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


class ExportableSubsystem(Protocol):
    options_scope: str
    export_rules_type: ExportRules

    def to_pex_request(
        self,
        *,
        interpreter_constraints: InterpreterConstraints | None = None,
        extra_requirements: Iterable[str] = (),
        main: MainSpecification | None = None,
        sources: Digest | None = None,
    ) -> PexRequest:
        ...


class FirstPartyPluginsType(Protocol):
    requirement_strings: FrozenOrderedSet[str]
    interpreter_constraints_fields: FrozenOrderedSet[InterpreterConstraintsField]


@memoized
def default_export_rules(python_tool: Type[ExportableSubsystem]) -> Iterable:
    if getattr(python_tool, "export_rules_type", None) not in ExportRules:
        raise NotImplementedError(f"Subsystem type `{python_tool}` is missing `export_rules_type`!")

    if python_tool.export_rules_type == ExportRules.CUSTOM:
        return

    class ExportSentinel(ExportPythonToolSentinel):
        pass

    ExportSentinel.__name__ = f"{python_tool.__name__}ExportSentinel"
    ExportSentinel.__qualname__ = f"{__name__}.{python_tool.__name__}ExportSentinel"

    yield UnionRule(ExportPythonToolSentinel, ExportSentinel)

    tool_export = getattr(python_tool, "export", True)

    if python_tool.export_rules_type == ExportRules.NO_ICS:

        @rule(_param_type_overrides={"request": ExportSentinel, "tool": python_tool})
        async def export_python_tool_without_ics(
            request: ExportPythonToolSentinel,
            tool: ExportableSubsystem,
        ) -> ExportPythonTool:
            if not tool_export:
                return ExportPythonTool(resolve_name=python_tool.options_scope, pex_request=None)
            return ExportPythonTool(
                resolve_name=tool.options_scope, pex_request=tool.to_pex_request()
            )

        yield export_python_tool_without_ics
        return

    try:
        field_set_type: Type[FieldSet] = getattr(python_tool, "field_set_type")
    except AttributeError as e:
        raise Exception(
            softwrap(
                f"""
            `{python_tool}` set `export_rules_type` to `WITH_ICS` but doesn't declare a
            `field_set_type` class attribute. Please define `field_set_type`.
            """
            )
        ) from e

    if python_tool.export_rules_type == ExportRules.WITH_ICS:

        @rule(_param_type_overrides={"request": ExportSentinel, "tool": python_tool})
        async def export_python_tool_with_ics(
            request: ExportPythonToolSentinel,
            tool: ExportableSubsystem,
            python_setup: PythonSetup,
        ) -> ExportPythonTool:
            if not tool_export:
                return ExportPythonTool(resolve_name=python_tool.options_scope, pex_request=None)

            interpreter_constraints = await _find_all_unique_interpreter_constraints(
                python_setup, field_set_type
            )

            return ExportPythonTool(
                resolve_name=tool.options_scope,
                pex_request=tool.to_pex_request(interpreter_constraints=interpreter_constraints),
            )

        yield export_python_tool_with_ics
    else:
        assert python_tool.export_rules_type == ExportRules.WITH_FIRSTPARTY_PLUGINS
        try:
            firstparty_plugins_type: FirstPartyPluginsType = getattr(
                python_tool, "firstparty_plugins_type"
            )
        except AttributeError as e:
            raise Exception(
                softwrap(
                    f"""
                `{python_tool}` set `export_rules_type` to `WITH_FIRSTPARTY_PLUGINS` but doesn't declare a
                `firstparty_plugins_type` class attribute. Please define `firstparty_plugins_type`.
            """
                )
            ) from e

        @rule(
            _param_type_overrides={
                "request": ExportSentinel,
                "tool": python_tool,
                "firstparty_plugins": firstparty_plugins_type,
            }
        )
        async def export_python_tool_with_firstparty_plugins(
            request: ExportPythonToolSentinel,
            tool: ExportableSubsystem,
            python_setup: PythonSetup,
            firstparty_plugins: FirstPartyPluginsType,
        ) -> ExportPythonTool:
            if not tool_export:
                return ExportPythonTool(resolve_name=python_tool.options_scope, pex_request=None)

            constraints = await _find_all_unique_interpreter_constraints(
                python_setup,
                field_set_type,
                extra_constraints_per_tgt=firstparty_plugins.interpreter_constraints_fields,
            )
            return ExportPythonTool(
                resolve_name=python_tool.options_scope,
                pex_request=tool.to_pex_request(
                    interpreter_constraints=constraints,
                    extra_requirements=firstparty_plugins.requirement_strings,
                ),
            )

        yield export_python_tool_with_firstparty_plugins
