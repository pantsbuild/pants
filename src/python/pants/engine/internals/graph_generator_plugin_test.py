import os

from pants.base.specs import Specs
from pants.engine.addresses import Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.internals.graph import _DependencyMapping, _DependencyMappingRequest, Owners, OwnersRequest
from pants.engine.internals.native_engine import Address
from pants.engine.internals.parametrize import _TargetParametrizations, _TargetParametrizationsRequest, Parametrize
from pants.engine.rules import QueryRule
from pants.engine.target import FieldDefaultFactoryRequest, TargetFilesGenerator, Target, SingleSourceField, Tags, \
    MultipleSourcesField, OverridesField, AllTargets
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


class MockSingleSourceField(SingleSourceField):
    pass


class MockMultipleSourcesField(MultipleSourcesField):
    pass

class MockGeneratedTarget(Target):
    alias = "generated"
    core_fields = (
        # MockDependencies,
        Tags,
        MockSingleSourceField)



class MockTargetGenerator(TargetFilesGenerator):
    alias = "generator"
    core_fields = (MockMultipleSourcesField, OverridesField)
    generated_target_cls = MockGeneratedTarget
    copied_fields = ()
    moved_fields = (Tags,)




def test_foo() -> None:
    rule_runner = RuleRunner(
        rules=[
            QueryRule(Addresses, [Specs]),
            QueryRule(_DependencyMapping, [_DependencyMappingRequest]),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest, EnvironmentName]),
            QueryRule(Owners, [OwnersRequest]),
            QueryRule(AllTargets, []),
            # UnionRule(FieldDefaultFactoryRequest, ResolveFieldDefaultFactoryRequest),
            # resolve_field_default_factory,
        ],
        target_types=[MockTargetGenerator, MockGeneratedTarget],
        objects={"parametrize": Parametrize},
        # NB: The `graph` module masks the environment is most/all positions. We disable the
        # inherent environment so that the positions which do require the environment are
        # highlighted.
        inherent_environment=None,
    )

    # build_content = "generator(tags=parametrize(t1=['t1'], t2=['t2']), sources=['f1.ext'])"
    build_content = "generator(tags=['t1'], sources=['f1.ext'])"
    files = ["f1.ext"]
    address = Address("demo")

    rule_runner.write_files(
        {
            f"{address.spec_path}/BUILD": build_content,
            **{os.path.join(address.spec_path, f): "" for f in files},
        }
    )
    owners = rule_runner.request(
        Owners,
        [
            OwnersRequest(
                tuple(["demo/BUILD"]),
                match_if_owning_build_file_included_in_sources=True,
            )
        ],
    )

    assert {Address("demo", relative_file_path="f1.ext")} == set(owners)

    targets = rule_runner.request(AllTargets, [])
    
    assert targets
