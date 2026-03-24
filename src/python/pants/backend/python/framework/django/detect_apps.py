# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField, PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import find_interpreter
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import FileGlobSpec, RawSpecs
from pants.engine.fs import AddPrefix, CreateDigest, FileContent, MergeDigests
from pants.engine.internals.graph import hydrate_sources, resolve_targets
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import add_prefix, create_digest, merge_digests
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import HydrateSourcesRequest, SourcesField, Target
from pants.util.frozendict import FrozenDict
from pants.util.resources import read_resource


@dataclass(frozen=True)
class DjangoApp:
    name: str
    config_file: str


class DjangoApps(FrozenDict[str, DjangoApp]):
    @property
    def label_to_name(self) -> FrozenDict[str, str]:
        return FrozenDict((label, app.name) for label, app in self.items())

    @property
    def label_to_file(self) -> FrozenDict[str, str]:
        return FrozenDict((label, app.config_file) for label, app in self.items())

    def add_from_json(self, json_bytes: bytes, strip_prefix: str = "") -> DjangoApps:
        json_dict: dict[str, dict[str, str]] = json.loads(json_bytes.decode())
        apps = {
            label: DjangoApp(
                val["app_name"], val["config_file"].partition(f"{strip_prefix}{os.sep}")[2]
            )
            for label, val in json_dict.items()
        }
        combined = dict(self, **apps)
        return DjangoApps(sorted(combined.items()))


_script_resource = "scripts/app_detector.py"


@rule
async def detect_django_apps(python_setup: PythonSetup) -> DjangoApps:
    # A Django app has a "name" - the full import path to the app ("path.to.myapp"),
    # and a "label" - a short name, usually the last segment of the import path ("myapp").
    #
    # An app provides this information via a subclass of AppConfig, living in a
    # file named apps.py.  Django loads this information into an app registry at runtime.
    #
    # Some parts of Django, notably migrations, use the label to reference apps. So to do custom
    # Django dep inference, we need to know the label -> name mapping.
    #
    # The only truly correct way to enumerate Django apps is to run the Django app registry code.
    # However we can't do this until after dep inference has completed, and even then it would be
    # complicated: we wouldn't know which settings.py to use, or whether it's safe to run Django
    # against that settings.py. Instead, we do this statically via parsing the apps.py file.
    #
    # NB: Legacy Django apps may not have an apps.py, in which case the label is assumed to be
    #  the name of the app dir, but the recommendation for many years has been to have it, and
    #  the Django startapp tool creates it for you. If an app does not have such an apps.py,
    #  then we won't be able to infer deps on that app unless we find other ways of detecting it.
    #  We should only do that if that case turns out to be common, and for some reason users can't
    #  simply create an apps.py to fix the issue.
    #
    # NB: Right now we only detect first-party apps in repo. We assume that third-party apps will
    #  be dep-inferred as a whole via the full package path in settings.py anyway.
    #  In the future we may find a way to map third-party apps here as well.
    django_apps = DjangoApps(FrozenDict())
    targets = await resolve_targets(
        **implicitly(
            RawSpecs.create(
                specs=[FileGlobSpec("**/apps.py")],
                description_of_origin="Django app detection",
                unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
            )
        )
    )
    if not targets:
        return django_apps

    script_file_content = FileContent(
        "script/__visitor.py", read_resource(__name__, _script_resource)
    )
    script_digest = await create_digest(CreateDigest([script_file_content]))
    apps_sandbox_prefix = "_apps_to_detect"

    # Partition by ICs, so we can run the detector on the appropriate interpreter.
    ics_to_tgts: dict[InterpreterConstraints, list[Target]] = defaultdict(list)
    for tgt in targets:
        ics = InterpreterConstraints(
            tgt[InterpreterConstraintsField].value_or_configured_default(
                python_setup, tgt[PythonResolveField] if tgt.has_field(PythonResolveField) else None
            )
        )
        ics_to_tgts[ics].append(tgt)

    for ics, tgts in ics_to_tgts.items():
        sources = await concurrently(
            [
                hydrate_sources(HydrateSourcesRequest(tgt[SourcesField]), **implicitly())
                for tgt in tgts
            ]
        )
        apps_digest = await merge_digests(MergeDigests([src.snapshot.digest for src in sources]))
        prefixed_apps_digest = await add_prefix(AddPrefix(apps_digest, apps_sandbox_prefix))

        input_digest = await merge_digests(MergeDigests([prefixed_apps_digest, script_digest]))
        python_interpreter = await find_interpreter(ics, **implicitly())

        process_result = await execute_process_or_raise(
            **implicitly(
                Process(
                    argv=[
                        python_interpreter.path,
                        script_file_content.path,
                        apps_sandbox_prefix,
                    ],
                    input_digest=input_digest,
                    description="Detect Django apps",
                )
            )
        )
        django_apps = django_apps.add_from_json(
            process_result.stdout or b"{}", strip_prefix=apps_sandbox_prefix
        )

    return django_apps


def rules() -> Iterable[Rule]:
    return collect_rules()
