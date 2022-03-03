# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.dependency_inference.module_mapper import (
    ModuleProviderType,
    ThirdPartyPythonModuleMapping,
)
from pants.engine.addresses import Address
from pants.util.docutil import doc_url


class MissingPythonCodegenRuntimeLibrary(Exception):
    pass


class AmbiguousPythonCodegenRuntimeLibrary(Exception):
    pass


def find_python_runtime_library_or_raise_error(
    module_mapping: ThirdPartyPythonModuleMapping,
    codegen_address: Address,
    runtime_library_module: str,
    *,
    resolve: str,
    resolves_enabled: bool,
    recommended_requirement_name: str,
    recommended_requirement_url: str,
    disable_inference_option: str,
) -> Address:
    addresses = [
        module_provider.addr
        for module_provider in module_mapping.providers_for_module(
            runtime_library_module, resolve=resolve
        )
        if module_provider.typ == ModuleProviderType.IMPL
    ]
    if len(addresses) == 1:
        return addresses[0]

    for_resolve_str = f" for the resolve '{resolve}'" if resolves_enabled else ""
    if not addresses:
        resolve_note = (
            (
                "Note that because `[python].enable_resolves` is set, you must specifically have a "
                f"`python_requirement` target that uses the same resolve '{resolve}' as the target "
                f"{codegen_address}. Alternatively, update {codegen_address} to use a different "
                "resolve.\n\n"
            )
            if resolves_enabled
            else ""
        )
        raise MissingPythonCodegenRuntimeLibrary(
            f"No `python_requirement` target was found with the module `{runtime_library_module}` "
            f"in your project{for_resolve_str}, so the Python code generated from the target "
            f"{codegen_address} will not work properly. See "
            f"{doc_url('python-third-party-dependencies')} for how to "
            "add a requirement, such as adding to requirements.txt. Usually you will want to use "
            f"the `{recommended_requirement_name}` project at {recommended_requirement_url}.\n\n"
            f"{resolve_note}"
            f"To ignore this error, set `{disable_inference_option} = false` in `pants.toml`."
        )

    alternative_solution = (
        (
            f"Alternatively, change the resolve field for {codegen_address} to use a different "
            "resolve from `[python].resolves`."
        )
        if resolves_enabled
        else (
            "Alternatively, if you do want to have "
            f"multiple conflicting versions of the `{runtime_library_module}` requirement, set "
            f"`{disable_inference_option} = false` in `pants.toml`. "
            f"Then manually add a dependency on the relevant `python_requirement` target to each "
            "target that directly depends on this generated code (e.g. `python_source` targets)."
        )
    )
    raise AmbiguousPythonCodegenRuntimeLibrary(
        "Multiple `python_requirement` targets were found with the module "
        f"`{runtime_library_module}` in your project{for_resolve_str}, so it is ambiguous which to "
        f"use for the runtime library for the Python code generated from the the target "
        f"{codegen_address}: {sorted(addr.spec for addr in addresses)}\n\n"
        f"To fix, remove one of these `python_requirement` targets{for_resolve_str} so that "
        f"there is no ambiguity and Pants can infer a dependency. {alternative_solution}"
    )
