# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jar_publish import PushDb
from pants.task.console_task import ConsoleTask


class CheckPublishedDeps(ConsoleTask):
    """Find references to outdated JVM artifacts."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--print-uptodate", type=bool, help="Print up-to-date dependencies.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._print_uptodate = self.get_options().print_uptodate
        # We look at the repos for the JarPublish task.
        # TODO: Yuck. The repos should be a subsystem that both tasks use.
        self.repos = self.context.options.for_scope("publish.jar").repos
        self._artifacts_to_targets = {}

        def is_published(tgt):
            return isinstance(tgt, ExportableJvmLibrary) and tgt.provides

        for target in self.context.scan().targets(predicate=is_published):
            provided_jar, _ = target.get_artifact_info()
            artifact = (provided_jar.org, provided_jar.name)
            if artifact not in self._artifacts_to_targets:
                self._artifacts_to_targets[artifact] = target

    def console_output(self, targets):
        push_dbs = {}

        def get_version_and_sha(target):
            db = target.provides.repo.push_db(target)
            if db not in push_dbs:
                push_dbs[db] = PushDb.load(db)
            pushdb_entry = push_dbs[db].get_entry(target)
            return pushdb_entry.sem_ver, pushdb_entry.sha

        visited = set()
        for target in self.context.targets():
            if isinstance(target, (JarLibrary, JvmTarget)):
                for dep in target.jar_dependencies:
                    artifact = (dep.org, dep.name)
                    if artifact in self._artifacts_to_targets and artifact not in visited:
                        visited.add(artifact)
                        artifact_target = self._artifacts_to_targets[artifact]
                        semver, sha = get_version_and_sha(artifact_target)
                        if semver.version() != dep.rev:
                            yield f"outdated {dep.org}#{dep.name} {dep.rev} latest {semver.version()}"
                        elif self._print_uptodate:
                            yield f"up-to-date {dep.org}#{dep.name} {semver.version()}"
