# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import defaultdict, namedtuple
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.memo import memoized

from pants.contrib.go.subsystems.fetcher_factory import FetcherFactory
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_task import GoTask


class GoTargetGenerator:
    """Automatically generates a Go target graph given pre-existing target roots."""

    class GenerationError(Exception):
        """Raised to indicate an error auto-generating a Go target."""

    class WrongLocalSourceTargetTypeError(GenerationError):
        """Indicates a local source target was defined with the wrong type.

        For example, a Go main package was defined as a GoLibrary instead of a GoBinary.
        """

    class NewRemoteEncounteredButRemotesNotAllowedError(GenerationError):
        """Indicates a new remote library dependency was found but --remote was not enabled."""

    def __init__(
        self,
        import_oracle,
        build_graph,
        local_root,
        fetcher_factory,
        generate_remotes=False,
        remote_root_func=None,
    ):
        self._import_oracle = import_oracle
        self._build_graph = build_graph
        self._local_source_root = local_root
        self._fetcher_factory = fetcher_factory
        self._generate_remotes = generate_remotes
        # We invoke self._remote_source_root_func lazily to create self._remote_source_root,
        # then set it to None so we know that there's no need to reinvoke it.
        self._remote_source_root_func = remote_root_func
        self._remote_source_root = None

    def _get_remote_source_root(self):
        if self._remote_source_root_func:
            self._remote_source_root = self._remote_source_root_func()
            self._remote_source_root_func = None
        return self._remote_source_root

    def generate(self, local_go_targets):
        """Automatically generates a Go target graph for the given local go targets.

        :param iter local_go_targets: The target roots to fill in a target graph for.
        :raises: :class:`GoTargetGenerator.GenerationError` if any missing targets cannot be generated.
        """
        visited = {l.import_path: l.address for l in local_go_targets}
        with temporary_dir() as gopath:
            for local_go_target in local_go_targets:
                deps = self._list_deps(gopath, local_go_target.address)
                self._generate_missing(gopath, local_go_target.address, deps, visited)
        # We don't want to trigger an exception if there's no remote root and we didn't need
        # one, so we return self._remote_source_root directly, instead of calling
        # self._get_remote_source_root().
        return list(visited.items()), self._remote_source_root

    def _generate_missing(self, gopath, local_address, import_listing, visited):
        target_type = GoBinary if import_listing.pkg_name == "main" else GoLibrary
        existing = self._build_graph.get_target(local_address)
        if not existing:
            self._build_graph.inject_synthetic_target(
                address=local_address, target_type=target_type
            )
        elif existing and not isinstance(existing, target_type):
            raise self.WrongLocalSourceTargetTypeError(
                "{} should be a {}".format(existing, target_type.__name__)
            )

        for import_path in import_listing.all_imports:
            if not self._import_oracle.is_go_internal_import(import_path):
                if import_path not in visited:
                    if self._import_oracle.is_remote_import(import_path):
                        remote_root = self._fetcher_factory.get_fetcher(import_path).root()
                        remote_pkg_path = GoRemoteLibrary.remote_package_path(
                            remote_root, import_path
                        )
                        name = remote_pkg_path or os.path.basename(import_path)
                        address = Address(
                            os.path.join(self._get_remote_source_root(), remote_root), name
                        )
                        try:
                            self._build_graph.inject_address_closure(address)
                        except AddressLookupError:
                            if not self._generate_remotes:
                                raise self.NewRemoteEncounteredButRemotesNotAllowedError(
                                    f"Cannot generate dependency for remote import path {import_path}"
                                )
                            self._build_graph.inject_synthetic_target(
                                address=address, target_type=GoRemoteLibrary, pkg=remote_pkg_path
                            )
                    else:
                        # Recurse on local targets.
                        address = Address(
                            os.path.join(self._local_source_root, import_path),
                            os.path.basename(import_path),
                        )
                        deps = self._list_deps(gopath, address)
                        self._generate_missing(gopath, address, deps, visited)
                    visited[import_path] = address
                dependency_address = visited[import_path]
                self._build_graph.inject_dependency(local_address, dependency_address)

    def _list_deps(self, gopath, local_address):
        # TODO(John Sirois): Lift out a local go sources target chroot util - GoWorkspaceTask and
        # GoTargetGenerator both create these chroot symlink trees now.
        import_path = GoLocalSource.local_import_path(self._local_source_root, local_address)
        src_path = os.path.join(gopath, "src", import_path)
        safe_mkdir(src_path)
        package_src_root = os.path.join(get_buildroot(), local_address.spec_path)
        for source_file in os.listdir(package_src_root):
            source_path = os.path.join(package_src_root, source_file)
            if GoLocalSource.is_go_source(source_path):
                dest_path = os.path.join(src_path, source_file)
                os.symlink(source_path, dest_path)

        return self._import_oracle.list_imports(import_path, gopath=gopath)


class GoBuildgen(GoTask):
    """Automatically generates Go BUILD files."""

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (FetcherFactory,)

    @classmethod
    def _default_template(cls):
        return dedent(
            """\
            {{#target.parameters?}}
            {{target.type}}(
              {{#target.parameters}}
              {{#deps?}}
              dependencies=[
                {{#deps}}
                '{{.}}',
                {{/deps}}
              ]
              {{/deps?}}
              {{#rev}}
              rev='{{.}}',
              {{/rev}}
              {{#pkgs?}}
              packages=[
                {{#pkgs}}
                '{{.}}',
                {{/pkgs}}
              ]
              {{/pkgs?}}
              {{/target.parameters}}
            )
            {{/target.parameters?}}
            {{^target.parameters?}}
            {{target.type}}()
            {{/target.parameters?}}
            """
        )

    @classmethod
    def register_options(cls, register):
        register(
            "--remote",
            type=bool,
            advanced=True,
            fingerprint=True,
            help="Allow auto-generation of remote dependencies without pinned versions "
            "(FLOATING versions).",
        )

        register(
            "--fail-floating",
            type=bool,
            advanced=True,
            fingerprint=True,
            help="After generating all dependencies, fail if any newly generated or pre-existing "
            "dependencies have un-pinned - aka FLOATING - versions.",
        )

        register(
            "--materialize",
            type=bool,
            advanced=True,
            fingerprint=True,
            help="Instead of just auto-generating missing go_binary and go_library targets in "
            "memory, (re-)generate them on disk using the installed Go BUILD file template.",
        )

        # TODO(John Sirois): Add docs for the template parameters.
        register(
            "--template",
            metavar="<template>",
            default=cls._default_template(),
            advanced=True,
            fingerprint=True,
            help="A Go BUILD file mustache template to use with --materialize.",
        )

        register(
            "--extension",
            default="",
            metavar="<ext>",
            advanced=True,
            fingerprint=True,
            help="An optional extension for all materialized BUILD files (should include the .)",
        )

        register(
            "--remote-root",
            default=None,
            metavar="<path>",
            advanced=True,
            fingerprint=True,
            help="Path to the remote golang source root, if any.",
        )

    def execute(self):
        materialize = self.get_options().materialize
        if materialize:
            local_go_targets = (
                None  # We want a full scan, which passing no local go targets signals.
            )
            if self.context.target_roots:
                self.context.log.warn(
                    "{} ignoring targets passed on the command line and re-materializing "
                    "the complete Go BUILD forest.".format(self.options_scope)
                )
        else:
            local_go_targets = self.context.targets(self.is_local_src)
            if not local_go_targets:
                return

        generation_result = self.generate_targets(local_go_targets=local_go_targets)
        if not generation_result:
            return

        # TODO(John Sirois): It would be nice to fail for floating revs for either the materialize or
        # in-memory cases.  Right now we only fail for the materialize case.
        if not materialize:
            msg = "Auto generated the following Go targets: target (import path):\n\t{}".format(
                "\n\t".join(
                    sorted(
                        "{} ({})".format(addr.reference(), ip)
                        for ip, addr in generation_result.generated
                    )
                )
            )
            self.context.log.info(msg)
        elif generation_result:
            self._materialize(generation_result)

    class TemplateResult(
        namedtuple(
            "TemplateResult",
            ["build_file_path", "data", "import_paths", "local", "rev", "fail_floating"],
        )
    ):
        @classmethod
        def local_target(cls, build_file_path, data, import_paths):
            return cls(
                build_file_path=build_file_path,
                data=data,
                import_paths=import_paths,
                local=True,
                rev=None,
                fail_floating=False,
            )

        @classmethod
        def remote_target(cls, build_file_path, data, import_paths, rev, fail_floating):
            return cls(
                build_file_path=build_file_path,
                data=data,
                import_paths=import_paths,
                local=False,
                rev=rev,
                fail_floating=fail_floating,
            )

        def log(self, logger):
            """Log information about the generated target including its BUILD file and import paths.

            :param logger: The logger to log with.
            :type logger: A :class:`logging.Logger` compatible object.
            """
            log = logger.info if self.local or self.rev else logger.warn
            log(f"\t{self}")

        @property
        def failed(self):
            """Return `True` if the generated target should be considered a failed generation.

            :rtype: bool
            """
            return self.fail_floating and not self.rev

        def __str__(self):
            import_paths = " ".join(sorted(self.import_paths))
            rev = "" if self.local else f" {self.rev or 'FLOATING'}"
            return f"{self.build_file_path} ({import_paths}){rev}"

    class FloatingRemoteError(TaskError):
        """Indicates Go remote libraries exist or were generated that don't specify a `rev`."""

    def _materialize(self, generation_result):
        remote = self.get_options().remote
        existing_go_buildfiles = set()

        # We scan for existing BUILD files containing Go targets before we begin to materialize
        # things, because once we have created files (possibly next to existing files), collisions
        # between the existing definitions and the new definitions are possible.
        def gather_go_buildfiles(rel_path, is_relevant_target):
            for build_file in self.context.address_mapper.scan_build_files(rel_path):
                spec_path = os.path.dirname(build_file)
                for address in self.context.address_mapper.addresses_in_spec_path(spec_path):
                    if is_relevant_target(self.context.build_graph.resolve_address(address)):
                        existing_go_buildfiles.add(address.rel_path)

        gather_go_buildfiles(generation_result.local_root, lambda t: isinstance(t, GoLocalSource))
        if remote and generation_result.remote_root != generation_result.local_root:
            gather_go_buildfiles(
                generation_result.remote_root, lambda t: isinstance(t, GoRemoteLibrary)
            )

        targets = set(self.context.build_graph.targets(self.is_go))
        if remote and generation_result.remote_root:
            # Generation only walks out from local source, but we might have transitive remote
            # dependencies under the remote root which are not linked except by `resolve.go`.  Add all
            # the remotes we can find to ensure they are re-materialized too.
            remote_root = os.path.join(get_buildroot(), generation_result.remote_root)
            targets.update(self.context.scan(remote_root).targets(self.is_remote_lib))

        # Generate targets, and discard any BUILD files that were overwritten.
        failed_results = []
        for result in self.generate_build_files(targets):
            existing_go_buildfiles.discard(result.build_file_path)
            result.log(self.context.log)
            if result.failed:
                failed_results.append(result)

        # Finally, unlink any BUILD files that were invalidated but not otherwise overwritten.
        if existing_go_buildfiles:
            deleted = []
            for existing_go_buildfile in existing_go_buildfiles:
                os.unlink(os.path.join(get_buildroot(), existing_go_buildfile))
                deleted.append(existing_go_buildfile)
            if deleted:
                self.context.log.info(
                    "Deleted the following obsolete BUILD files:\n\t{}".format(
                        "\n\t".join(sorted(deleted))
                    )
                )

        if failed_results:
            self.context.log.error(
                "Un-pinned (FLOATING) Go remote library dependencies are not "
                "allowed in this repository!\n"
                "Found the following FLOATING Go remote libraries:\n\t{}".format(
                    "\n\t".join("{}".format(result) for result in failed_results)
                )
            )
            self.context.log.info(
                "You can fix this by editing the target in each FLOATING BUILD file "
                "listed above to include a `rev` parameter that points to a sha, tag "
                "or commit id that pins the code in the source repository to a fixed, "
                "non-FLOATING version."
            )
            raise self.FloatingRemoteError("Un-pinned (FLOATING) Go remote libraries detected.")

    class InvalidLocalRootsError(TaskError):
        """Indicates the Go local source owning targets' source roots are invalid."""

    class InvalidRemoteRootsError(TaskError):
        """Indicates the Go remote library source roots are invalid."""

    class GenerationError(TaskError):
        """Indicates an error generating Go targets."""

        def __init__(self, cause):
            super(GoBuildgen.GenerationError, self).__init__(str(cause))
            self.cause = cause

    class GenerationResult(
        namedtuple("GenerationResult", ["generated", "local_root", "remote_root"])
    ):
        """Captures the result of a Go target generation round."""

    def generate_targets(self, local_go_targets=None):
        """Generate Go targets in memory to form a complete Go graph.

        :param local_go_targets: The local Go targets to fill in a complete target graph for.  If
                                 `None`, then all local Go targets under the Go source root are used.
        :type local_go_targets: :class:`collections.Iterable` of
                                :class:`pants.contrib.go.targets.go_local_source import GoLocalSource`
        :returns: A generation result if targets were generated, else `None`.
        :rtype: :class:`GoBuildgen.GenerationResult`
        """
        # TODO(John Sirois): support multiple source roots like GOPATH does?
        # The GOPATH's 1st element is read-write, the rest are read-only; ie: their sources build to
        # the 1st element's pkg/ and bin/ dirs.

        if not local_go_targets:
            local_go_targets = self.context.scan().targets(self.is_local_src)
            if not local_go_targets:
                return None

        local_roots = {t.target_base for t in local_go_targets}
        if len(local_roots) > 1:
            raise self.InvalidLocalRootsError(
                "BUILD gen requires a single local Go source root, but found Go targets under "
                f"multiple build roots: {', '.join(sorted(local_roots))}"
            )
        local_root = local_roots.pop()

        @memoized
        def infer_remote_root():
            inferrable_roots = ["3rdparty/go", "3rd_party/go", "thirdparty/go", "third_party/go"]
            msg = (
                f"You can provide an explicit remote source root by setting remote_root in the "
                f"[{self.options_scope}] section of your config file."
            )
            rr = None
            for path in inferrable_roots:
                if os.path.isdir(path):
                    if rr:
                        raise self.InvalidRemoteRootsError(
                            f"Couldn't infer a single remote root. Found {rr} and {path}. {msg}"
                        )
                    rr = path
            if not rr:
                raise self.InvalidRemoteRootsError(
                    f"Couldn't infer remote root.  Found none of: {','.join(inferrable_roots)}. {msg}"
                )
            return rr

        remote_root_func = lambda: self.get_options().remote_root or infer_remote_root()

        generator = GoTargetGenerator(
            self.import_oracle,
            self.context.build_graph,
            local_root,
            self.get_fetcher_factory(),
            generate_remotes=self.get_options().remote,
            remote_root_func=remote_root_func,
        )
        with self.context.new_workunit("go.buildgen", labels=[WorkUnitLabel.MULTITOOL]):
            try:
                generated, remote_root = generator.generate(local_go_targets)
                return self.GenerationResult(
                    generated=generated, local_root=local_root, remote_root=remote_root
                )
            except generator.GenerationError as e:
                raise self.GenerationError(e)

    def get_fetcher_factory(self):
        return FetcherFactory.global_instance()

    def generate_build_files(self, targets):
        goal_name = self.options_scope
        flags = "--materialize"
        if self.get_options().remote:
            flags += " --remote"
        template_header = dedent(
            """\
            # Auto-generated by pants!
            # To re-generate run: `pants {goal_name} {flags}`

            """
        ).format(goal_name=goal_name, flags=flags)
        template_text = template_header + self.get_options().template
        build_file_basename = "BUILD" + self.get_options().extension

        targets_by_spec_path = defaultdict(set)
        for target in targets:
            targets_by_spec_path[target.address.spec_path].add(target)

        for spec_path, targets in targets_by_spec_path.items():
            rel_path = os.path.join(spec_path, build_file_basename)
            result = self._create_template_data(rel_path, list(targets))
            if result:
                generator = Generator(template_text, target=result.data)
                build_file_path = os.path.join(get_buildroot(), rel_path)
                with safe_open(build_file_path, mode="w") as fp:
                    generator.write(stream=fp)
                yield result

    class NonUniformRemoteRevsError(TaskError):
        """Indicates packages with mis-matched versions are defined for a single remote root."""

    def _create_template_data(self, build_file_path, targets):
        if len(targets) == 1 and self.is_local_src(targets[0]):
            local_target = targets[0]
            data = self._data(
                target_type="go_binary" if self.is_binary(local_target) else "go_library",
                deps=[d.address.reference() for d in local_target.dependencies],
            )
            return self.TemplateResult.local_target(
                build_file_path=build_file_path, data=data, import_paths=[local_target.import_path]
            )
        elif self.get_options().remote:
            fail_floating = self.get_options().fail_floating
            if len(targets) == 1 and not targets[0].pkg:
                remote_lib = targets[0]
                rev = remote_lib.rev
                data = self._data(target_type="go_remote_library", rev=rev)
                import_paths = (remote_lib.import_path,)
                return self.TemplateResult.remote_target(
                    build_file_path=build_file_path,
                    data=data,
                    import_paths=import_paths,
                    rev=rev,
                    fail_floating=fail_floating,
                )
            else:
                revs = {t.rev for t in targets if t.rev}
                if len(revs) > 1:
                    msg = (
                        "Cannot create BUILD file {} for the following packages at remote root {}, "
                        "they must all have the same version:\n\t{}".format(
                            build_file_path,
                            targets[0].remote_root,
                            "\n\t".join("{} {}".format(t.pkg, t.rev) for t in targets),
                        )
                    )
                    raise self.NonUniformRemoteRevsError(msg)
                rev = revs.pop() if revs else None

                data = self._data(
                    target_type="go_remote_libraries",
                    rev=rev,
                    pkgs=sorted({t.pkg for t in targets}),
                )
                import_paths = tuple(t.import_path for t in targets)
                return self.TemplateResult.remote_target(
                    build_file_path=build_file_path,
                    data=data,
                    import_paths=import_paths,
                    rev=rev,
                    fail_floating=fail_floating,
                )
        else:
            return None

    def _data(self, target_type, deps=None, rev=None, pkgs=None):
        parameters = TemplateData(deps=deps, rev=rev, pkgs=pkgs) if (deps or rev or pkgs) else None
        return TemplateData(type=target_type, parameters=parameters)
