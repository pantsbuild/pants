# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Goal for publishing packaged targets to any repository or registry etc.

Plugins implement the publish protocol that provides this goal with the processes to run in order to
publish the artifacts.

The publish protocol consists of defining two union members and one rule, returning the processes to
run. See the doc for the corresponding classes in this module for details on the classes to define.

Example rule:

    @rule
    async def publish_example(request: PublishToMyRepoRequest, ...) -> PublishProcesses:
      # Create `InteractiveProcess` instances or `Process` instances as required by the `request`.
      return PublishProcesses(...)
"""

from __future__ import annotations

import itertools
import json
import logging
from abc import ABCMeta
from collections.abc import Coroutine, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from itertools import chain
from typing import Any, ClassVar, Generic, Literal, Self, TypeVar, cast, final, overload

from pants.core.goals.package import (
    BuiltPackage,
    EnvironmentAwarePackageRequest,
    PackageFieldSet,
    environment_aware_package,
)
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.specs_rules import find_valid_field_sets_for_target_roots
from pants.engine.intrinsics import execute_process, run_interactive_process_in_environment
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
    ProcessCacheScope,
)
from pants.engine.rules import collect_rules, concurrently, goal_rule, implicitly, rule
from pants.engine.target import (
    FieldSet,
    ImmutableValue,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.option_types import EnumOption, StrOption
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


_F = TypeVar("_F", bound=FieldSet)


class PublishOutputData(FrozenDict[str, ImmutableValue]):
    pass


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class PublishRequest(Generic[_F]):
    """Implement a union member subclass of this union class along with a PublishFieldSet subclass
    that appoints that member subclass in order to receive publish requests for targets compatible
    with the field set.

    The `packages` hold all artifacts produced for a given target to be published.

    Example:

        PublishToMyRepoRequest(PublishRequest):
          pass

        PublishToMyRepoFieldSet(PublishFieldSet):
          publish_request_type = PublishToMyRepoRequest

          # Standard FieldSet semantics from here on:
          required_fields = (MyRepositories,)
          ...
    """

    field_set: _F
    packages: tuple[BuiltPackage, ...]


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class CheckSkipRequest(Generic[_F]):
    package_fs: PackageFieldSet
    publish_fs: _F

    @property
    def address(self) -> Address:
        return self.publish_fs.address


_T = TypeVar("_T", bound=PublishRequest)


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class PublishFieldSet(Generic[_T], FieldSet, metaclass=ABCMeta):
    """FieldSet for PublishRequest.

    Union members may list any fields required to fulfill the instantiation of the
    `PublishProcesses` result of the publish rule.
    """

    # Subclasses must provide this, to a union member (subclass) of `PublishRequest`.
    publish_request_type: ClassVar[type[_T]]

    @final
    def _request(self, packages: tuple[BuiltPackage, ...]) -> _T:
        """Internal helper for the core publish goal."""
        return self.publish_request_type(field_set=self, packages=packages)

    def check_skip_request(self, package_fs: PackageFieldSet) -> CheckSkipRequest[Self] | None:
        """Subclasses can override this method if they want to preempt packaging for publish
        requests that are just going to be skipped."""
        return None

    @final
    @classmethod
    def rules(cls) -> tuple[UnionRule, ...]:
        """Helper method for registering the union members."""
        return (
            UnionRule(PublishFieldSet, cls),
            UnionRule(PublishRequest, cls.publish_request_type),
        )

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData({"target": self.address})


# This is the same as the Enum in the test goal.  It is initially separate as
# DRYing out is easier than undoing pre-mature abstraction.
class ShowOutput(Enum):
    """Which publish actions to emit detailed output for."""

    ALL = "all"
    FAILED = "failed"
    NONE = "none"


@dataclass(frozen=True)
class PublishPackages:
    """Processes to run in order to publish the named artifacts.

    The `names` should list all artifacts being published by the `process` command.

    The `process` may be `None`, indicating that it will not be published. This will be logged as
    `skipped`. If the process returns a non-zero exit code, it will be logged as `failed`. The `process`
    can either be a Process or an InteractiveProcess. In most cases, InteractiveProcess will be wanted.
    However, some tools have non-interactive publishing modes and can leverage parallelism. See
    https://github.com/pantsbuild/pants/issues/17613#issuecomment-1323913381 for more context.

    The `description` may be a reason explaining why the publish was skipped, or identifying which
    repository the artifacts are published to.
    """

    names: tuple[str, ...]
    process: InteractiveProcess | Process | None = None
    description: str | None = None
    data: PublishOutputData = field(default_factory=PublishOutputData)

    def get_output_data(self, **extra_data) -> PublishOutputData:
        return PublishOutputData(
            {
                "names": self.names,
                **self.data,
                **extra_data,
            }
        )


@dataclass(frozen=True)
class CheckSkipResult:
    """PublishPackages that were pre-emptively skipped.

    If `skipped_packages` is empty, this indicates that this request should NOT be skipped.
    """

    skipped_packages: tuple[PublishPackages, ...]
    _skip_packaging_only: bool

    def __init__(self, inner: Iterable[PublishPackages], skip_packaging_only: bool = False) -> None:
        object.__setattr__(self, "skipped_packages", tuple(inner))
        object.__setattr__(self, "_skip_packaging_only", skip_packaging_only)

    def __post_init__(self):
        if any(pp.process is not None for pp in self.skipped_packages):
            raise ValueError("CheckSkipResult must not have any non-None processes")

    @property
    def skip_publish(self) -> bool:
        return bool(self.skipped_packages)

    @property
    def skip_package(self) -> bool:
        return self.skip_publish or self._skip_packaging_only

    @overload
    @classmethod
    def skip(cls, *, skip_packaging_only: Literal[True]) -> Self: ...

    @overload
    @classmethod
    def skip(
        cls,
        *,
        names: Iterable[str],
        description: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Self: ...

    @classmethod
    def skip(
        cls,
        *,
        skip_packaging_only: bool = False,
        names: Iterable[str] = (),
        description: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Self:
        args = (
            ((), True)
            if skip_packaging_only
            else (
                [
                    PublishPackages(
                        names=tuple(names),
                        description=description,
                        data=PublishOutputData.deep_freeze(data) if data else PublishOutputData(),
                    )
                ],
                False,
            )
        )
        return cls(*args)

    @classmethod
    def no_skip(cls) -> Self:
        return cls((), False)


class PublishProcesses(Collection[PublishPackages]):
    """Collection of what processes to run for all built packages.

    This is returned from implementing rules in response to a PublishRequest.

    Depending on the capabilities of the publishing tool, the work may be partitioned based on
    number of artifacts and/or repositories to publish to.
    """


@rule(polymorphic=True)
async def preemptive_skip_publish_packages(
    request: CheckSkipRequest, environment_name: EnvironmentName
) -> CheckSkipResult:
    raise NotImplementedError()


@rule(polymorphic=True)
async def create_publish_processes(
    req: PublishRequest,
    environment_name: EnvironmentName,
) -> PublishProcesses:
    raise NotImplementedError()


@dataclass(frozen=True)
class PublishProcessesRequest:
    """Internal request taking all field sets for a target and turning it into a `PublishProcesses`
    collection (via registered publish plugins)."""

    package_field_sets: tuple[PackageFieldSet, ...]
    publish_field_sets: tuple[PublishFieldSet, ...]


class PublishSubsystem(GoalSubsystem):
    name = "publish"
    help = "Publish deliverables (assets, distributions, images, etc)."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return PackageFieldSet in union_membership and PublishFieldSet in union_membership

    output = StrOption(
        default=None,
        help="Filename for JSON structured publish information.",
    )

    noninteractive_process_output = EnumOption(
        default=ShowOutput.ALL,
        help=softwrap(
            """
            Show stdout/stderr when publishing with
            noninteractively.  This only has an effect for those
            publish subsystems that support a noninteractive mode.
            """
        ),
    )


class Publish(Goal):
    subsystem_cls = PublishSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS


def _to_publish_output_results_and_data(
    pub: PublishPackages, res: FallibleProcessResult | InteractiveProcessResult, console: Console
) -> tuple[list[str], list[PublishOutputData]]:
    if res.exit_code == 0:
        sigil = console.sigil_succeeded()
        status = "published"
        prep = "to"
    else:
        sigil = console.sigil_failed()
        status = "failed"
        prep = "for"

    if pub.description:
        status += f" {prep} {pub.description}"

    results = []
    output_data = []
    for name in pub.names:
        results.append(f"{sigil} {name} {status}.")

    output_data.append(
        pub.get_output_data(
            exit_code=res.exit_code,
            published=res.exit_code == 0,
            status=status,
        )
    )
    return results, output_data


@rule
async def package_for_publish(
    request: PublishProcessesRequest, local_environment: ChosenLocalEnvironmentName
) -> PublishProcesses:
    packages = await concurrently(
        environment_aware_package(EnvironmentAwarePackageRequest(package_fs))
        for package_fs in request.package_field_sets
    )

    for pkg in packages:
        for artifact in pkg.artifacts:
            if artifact.relpath:
                logger.info(f"Packaged {artifact.relpath}")
            elif artifact.extra_log_lines:
                logger.info(str(artifact.extra_log_lines[0]))

    publish = await concurrently(
        create_publish_processes(
            **implicitly(
                {
                    field_set._request(packages): PublishRequest,
                    local_environment.val: EnvironmentName,
                }
            )
        )
        for field_set in request.publish_field_sets
    )

    # Flatten and dress each publish processes collection with data about its origin.
    publish_processes = [
        replace(
            publish_process,
            data=PublishOutputData({**publish_process.data, **field_set.get_output_data()}),
        )
        for processes, field_set in zip(publish, request.publish_field_sets)
        for publish_process in processes
    ]

    return PublishProcesses(publish_processes)


@goal_rule
async def run_publish(
    console: Console,
    publish: PublishSubsystem,
    local_environment: ChosenLocalEnvironmentName,
) -> Publish:
    target_roots_to_publish_field_sets: TargetRootsToFieldSets[PublishFieldSet]
    target_roots_to_package_field_sets, target_roots_to_publish_field_sets = await concurrently(
        find_valid_field_sets_for_target_roots(
            TargetRootsToFieldSetsRequest(
                PackageFieldSet,
                goal_description="",
                # Don't warn/error here because it's already covered by `PublishFieldSet`.
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.ignore,
            ),
            **implicitly(),
        ),
        find_valid_field_sets_for_target_roots(
            TargetRootsToFieldSetsRequest(
                PublishFieldSet,
                goal_description="the `publish` goal",
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
            ),
            **implicitly(),
        ),
    )

    # Only keep field sets that both package something, and have something to publish.
    targets = set(target_roots_to_package_field_sets.targets).intersection(
        set(target_roots_to_publish_field_sets.targets)
    )

    if not targets:
        return Publish(exit_code=0)

    skip_check_requests = [
        skip_request
        for tgt in targets
        for package_fs in target_roots_to_package_field_sets.mapping[tgt]
        for publish_fs in target_roots_to_publish_field_sets.mapping[tgt]
        if (skip_request := publish_fs.check_skip_request(package_fs))
    ]
    skip_check_results = await concurrently(
        preemptive_skip_publish_packages(
            **implicitly({skip_request: CheckSkipRequest, local_environment.val: EnvironmentName})
        )
        for skip_request in skip_check_requests
    )
    # In `package_skips`, True represents skip, False represents a definitive non-skip, and not present means we don't know yet.
    package_skips: dict[PackageFieldSet, bool] = {}
    # In `publish_skips`, the value is a list of PublishPackages means skip, None is a non-skip, and not present means we don't know yet.
    publish_skips: dict[PublishFieldSet, list[PublishPackages] | None] = {}
    for skip_request, maybe_skip in zip(skip_check_requests, skip_check_results):
        skip_package = maybe_skip.skip_package
        package_skip_seen = skip_request.package_fs in package_skips
        # If skip_package is False, set to False, otherwise set only if this package_fs has not been seen yet.
        if (package_skip_seen and not skip_package) or not package_skip_seen:
            package_skips[skip_request.package_fs] = skip_package
        if maybe_skip.skip_publish:
            try:
                skip_publish_packages = publish_skips[skip_request.publish_fs]
            except KeyError:
                publish_skips[skip_request.publish_fs] = list(maybe_skip.skipped_packages)
            else:
                if skip_publish_packages is not None:
                    skip_publish_packages.extend(maybe_skip.skipped_packages)
        else:
            publish_skips[skip_request.publish_fs] = None

    skipped_publishes: list[PublishPackages] = list(
        itertools.chain.from_iterable(pubskip for pubskip in publish_skips.values() if pubskip)
    )
    # Build all packages and request the processes to run for each field set.
    processes = await concurrently(
        package_for_publish(
            PublishProcessesRequest(
                tuple(
                    pfs
                    for pfs in target_roots_to_package_field_sets.mapping[tgt]
                    if not package_skips.get(pfs, False)
                ),
                tuple(
                    pfs
                    for pfs in target_roots_to_publish_field_sets.mapping[tgt]
                    if not publish_skips.get(pfs)
                ),
            ),
            **implicitly(),
        )
        for tgt in targets
    )

    exit_code: int = 0
    outputs: list[PublishOutputData] = []
    results: list[str] = []

    flattened_processes = list(chain.from_iterable(processes))
    background_publishes: list[PublishPackages] = [
        pub for pub in flattened_processes if isinstance(pub.process, Process)
    ]
    foreground_publishes: list[PublishPackages] = [
        pub for pub in flattened_processes if isinstance(pub.process, InteractiveProcess)
    ]
    skipped_publishes.extend(pub for pub in flattened_processes if pub.process is None)
    background_requests: list[Coroutine[Any, Any, FallibleProcessResult]] = []
    for pub in background_publishes:
        process = cast(Process, pub.process)
        # Because this is a publish process, we want to ensure we don't cache this process.
        assert process.cache_scope == ProcessCacheScope.PER_SESSION
        background_requests.append(
            execute_process(
                **implicitly({process: Process, local_environment.val: EnvironmentName})
            )
        )

    # Process all non-interactive publishes
    logger.debug(f"Awaiting {len(background_requests)} background publishes")
    background_results = await concurrently(background_requests)
    for pub, background_res in zip(background_publishes, background_results):
        logger.debug(f"Processing {pub.process} background process")
        pub_results, pub_output = _to_publish_output_results_and_data(pub, background_res, console)
        results.extend(pub_results)
        outputs.extend(pub_output)

        names = "'" + "', '".join(pub.names) + "'"
        output_msg = f"Output for publishing {names}"
        if background_res.stdout:
            output_msg += f"\n{background_res.stdout.decode()}"
        if background_res.stderr:
            output_msg += f"\n{background_res.stderr.decode()}"

        if publish.noninteractive_process_output == ShowOutput.ALL or (
            publish.noninteractive_process_output == ShowOutput.FAILED
            and background_res.exit_code == 0
        ):
            console.print_stdout(output_msg)

        if background_res.exit_code != 0:
            exit_code = background_res.exit_code

    for pub in skipped_publishes:
        sigil = console.sigil_skipped()
        status = "skipped"
        if pub.description:
            status += f" {pub.description}"
        for name in pub.names:
            results.append(f"{sigil} {name} {status}.")
        outputs.append(pub.get_output_data(published=False, status=status))

    # Process all interactive publishes
    for pub in foreground_publishes:
        logger.debug(f"Execute {pub.process}")
        res = await run_interactive_process_in_environment(
            cast(InteractiveProcess, pub.process), local_environment.val
        )
        pub_results, pub_output = _to_publish_output_results_and_data(pub, res, console)
        results.extend(pub_results)
        outputs.extend(pub_output)
        if res.exit_code != 0:
            exit_code = res.exit_code

    console.print_stderr("")
    if not results:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing published.")

    # We collect all results to the end, so all output from the interactive processes are done,
    # before printing the results.
    for line in sorted(results):
        console.print_stderr(line)

    # Log structured output
    output_data = json.dumps(outputs, cls=_PublishJsonEncoder, indent=2, sort_keys=True)
    logger.debug(f"Publish result data:\n{output_data}")
    if publish.output:
        with open(publish.output, mode="w") as fd:
            fd.write(output_data)

    return Publish(exit_code)


class _PublishJsonEncoder(json.JSONEncoder):
    safe_to_str_types = (Address,)

    def default(self, o):
        """Return a serializable object for o."""
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, Mapping):
            return dict(o)
        if isinstance(o, Sequence):
            return list(o)
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def rules():
    return collect_rules()
