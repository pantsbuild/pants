# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.dependency_inference.module_mapper import (
    ModuleProviderType,
    PythonModuleOwners,
)
from pants.engine.addresses import Address
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class MissingPythonCodegenRuntimeLibrary(Exception):
    pass


class AmbiguousPythonCodegenRuntimeLibrary(Exception):
    pass


def find_python_runtime_library_or_raise_error(
    module_owners: PythonModuleOwners,
    codegen_address: Address,
    runtime_library_module: str,
    *,
    resolve: str,
    resolves_enabled: bool,
    recommended_requirement_name: str,
    recommended_requirement_url: str,
    disable_inference_option: str,
) -> Address:
    addresses = module_owners.unambiguous
    if module_owners.unambiguous:
        return module_owners.unambiguous[0]

    addresses = module_owners.ambiguous

    for_resolve_str = f" for the resolve '{resolve}'" if resolves_enabled else ""
    if not addresses:
        resolve_note = softwrap(
            (
                f"""
                Note that because `[python].enable_resolves` is set, you must specifically have a
                `python_requirement` target that uses the same resolve '{resolve}' as the target
                {codegen_address}. Alternatively, update {codegen_address} to use a different
                resolve.
                """
            )
            if resolves_enabled
            else ""
        )
        raise MissingPythonCodegenRuntimeLibrary(
            softwrap(
                f"""
                No `python_requirement` target was found with the module `{runtime_library_module}`
                in your project{for_resolve_str}, so the Python code generated from the target
                {codegen_address} will not work properly. See
                {doc_url('python-third-party-dependencies')} for how to add a requirement, such as
                adding to requirements.txt. Usually you will want to use the
                `{recommended_requirement_name}` project at {recommended_requirement_url}.

                {resolve_note}

                To ignore this error, set `{disable_inference_option} = false` in `pants.toml`.
                """
            )
        )

    alternative_solution = softwrap(
        (
            f"""
            Alternatively, change the resolve field for {codegen_address} to use a different resolve
            from `[python].resolves`.
            """
        )
        if resolves_enabled
        else (
            f"""
            Alternatively, if you do want to have multiple conflicting versions of the
            `{runtime_library_module}` requirement, set `{disable_inference_option} = false` in
            `pants.toml`. Then manually add a dependency on the relevant `python_requirement` target
            to each target that directly depends on this generated code (e.g. `python_source` targets).
            """
        )
    )
    raise AmbiguousPythonCodegenRuntimeLibrary(
        softwrap(
            f"""
            Multiple `python_requirement` targets were found with the module `{runtime_library_module}`
            in your project{for_resolve_str}, so it is ambiguous which to use for the runtime library
            for the Python code generated from the target {codegen_address}:
            {sorted(addr.spec for addr in addresses)}

            To fix, remove one of these `python_requirement` targets{for_resolve_str} so that
            there is no ambiguity and Pants can infer a dependency. It
            might also help to set
            `[python-infer].ambiguity-resolution = "by_source_root"`. {alternative_solution}
            """
        )
    )
