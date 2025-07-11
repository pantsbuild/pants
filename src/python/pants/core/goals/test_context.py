from typing import Tuple
from dataclasses import dataclass

from pants.engine.fs import Digest, EMPTY_DIGEST, MergeDigests
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.engine.rules import rule, collect_rules, Get, MultiGet

from .test import TestExtraEnvVarsField, RuntimePackageDependenciesField, BuiltPackageDependencies, BuildPackageDependenciesRequest



@dataclass(frozen=True)
class TestContext:
    env: EnvironmentVars = EnvironmentVars()
    digest: Digest = EMPTY_DIGEST
    # Processes for background services?


@union
@dataclass(frozen=True)
class TestContextFieldSet(FieldSet, metaclass=ABCMeta):
    pass


@dataclass(frozen=True)
class ExtraEnvVarsFieldSet(TestContextFieldSet):
    required_fields = (TestExtraEnvVarsField,)

    extra_env_vars: TestExtraEnvVarsField


@dataclass(frozen=True)
class RuntimePackageDependenciesFieldset(TestContextFieldSet):
    required_fields = (RuntimePackageDependenciesField,)
    
    runtime_package_dependencies: RuntimePackageDependenciesField

@rule
async def get_extra_env_vars_ctx(fieldset: ExtraEnvVarsFieldSet) -> TestContext:
    env = await Get(EnvironmentVars, EnvironmentVarsRequest(fieldset.extra_env_vars))
    return TestContext(env=env)


@rule
async def get_runtime_package_dependencies(fieldset: RuntimePackageDependenciesFieldset) -> TestContext:
    built_packages = await Get(
        BuiltPackageDependencies,
        BuildPackageDependenciesRequest(fieldset.runtime_package_dependencies),
    )
    digest = await Get(Digest, MergeDigests(pkg.digest for pkg in built_packages))
    return TestContext(digest=digest)


@rule
async def get_target_context(target: Target, union_membership: UnionMembership) -> TestContext:
    test_context_members = union_membership[TestContextFieldSet]

    concrete_requests = [
        request_type(
            request_type.field_set_type.create(target)
        )
        for request_type in test_context_members
        if request_type.field_set_type.is_valid(target)
    ]
    results = await MultiGet(
        Get(TestContext, TestContextFieldSet, concrete_request)
        for concrete_request in concrete_requests
    )

    context_env = EnvironmentVars()

    context_digests = []

    for result in results:
        context_digests.append(result.digest)

        # TODO: Warn on collision?
        context_env = EnvironmentVars(**context_env, **result.env)

    digest = await Get(Digest, MergeDigests([result.digest for result in results]))
    return TestContext(env=context_env, digest=digest)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExtraEnvVarsFieldSet, TestContextFieldSet),
        UnionRule(RuntimePackageDependenciesFieldset, TestContextFieldSet),
    ]