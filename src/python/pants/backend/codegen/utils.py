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


def find_python_runtime_library_or_error(
    module_mapping: ThirdPartyPythonModuleMapping,
    codegen_address: Address,
    runtime_library_module: str,
    *,
    recommended_requirement_name: str,
    recommended_requirement_url: str,
    disable_inference_option: str,
) -> Address:
    addresses = [
        module_provider.addr
        for module_provider in module_mapping.providers_for_module(
            runtime_library_module, resolve=None
        )
        if module_provider.typ == ModuleProviderType.IMPL
    ]

    if not addresses:
        raise MissingPythonCodegenRuntimeLibrary(
            f"No `python_requirement` found with the module `{runtime_library_module}` in your "
            f"project, so the Python code generated from the target {codegen_address} will "
            f"not work properly. See {doc_url('python-third-party-dependencies')} for how to "
            "add a requirement, such as adding to requirements.txt. Usually you will want to use "
            f"the `{recommended_requirement_name}` project at {recommended_requirement_url}.\n\n"
            f"To ignore this error, set `{disable_inference_option} = false` in `pants.toml`."
        )

    if len(addresses) > 1:
        raise AmbiguousPythonCodegenRuntimeLibrary(
            "Multiple `python_requirement` targets found with the module "
            f"`{runtime_library_module}` in your project, so it is ambiguous which to use for the "
            f"runtime library for the Python code generated from the the target {codegen_address}: "
            f"{sorted(addr.spec for addr in addresses)}\n\n"
            "To fix, remove one of these `python_requirement` targets so that there is no "
            "ambiguity and Pants can infer a dependency. Alternatively, if you do want to have "
            f"multiple conflicting versions of the `{runtime_library_module}` requirement, set "
            f"`{disable_inference_option} = false` in `pants.toml`. "
            f"Then manually add a dependency on the relevant `python_requirement` target to each "
            "target that directly depends on this generated code (e.g. `python_source` targets)."
        )
    return addresses[0]
