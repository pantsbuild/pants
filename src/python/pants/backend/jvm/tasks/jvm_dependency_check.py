# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import defaultdict

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.build_graph.resources import Resources
from pants.build_graph.target_scopes import Scopes
from pants.java.distribution.distribution import DistributionLocator
from pants.task.task import Task
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet


class JvmDependencyCheck(Task):
    """Checks true dependencies of a JVM target and ensures that they are consistent with BUILD
    files."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--missing-direct-deps",
            choices=["off", "warn", "fatal"],
            default="off",
            fingerprint=True,
            help="Check for missing direct dependencies in compiled code. Reports actual "
            "dependencies A -> B where there is no direct BUILD file dependency path from "
            "A to B. This is a very strict check; In practice it is common to rely on "
            "transitive, indirect dependencies, e.g., due to type inference or when the main "
            "target in a BUILD file is modified to depend on other targets in the same BUILD "
            "file, as an implementation detail. However it may still be useful to use this "
            "on occasion. ",
        )

        register(
            "--missing-deps-whitelist",
            type=list,
            default=[],
            fingerprint=True,
            help="Don't report these targets even if they have missing deps.",
        )

        register(
            "--unnecessary-deps",
            choices=["off", "warn", "fatal"],
            default="off",
            fingerprint=True,
            help="Check for declared dependencies in compiled code that are not needed. "
            "This is a very strict check. For example, generated code will often "
            "legitimately have BUILD dependencies that are unused in practice.",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (DependencyContext, DistributionLocator)

    @staticmethod
    def _skip(options):
        """Return true if the task should be entirely skipped, and thus have no product
        requirements."""
        values = [options.missing_direct_deps, options.unnecessary_deps]
        return all(v == "off" for v in values)

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        if not cls._skip(options):
            round_manager.require_data("product_deps_by_target")
            round_manager.require_data("runtime_classpath")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set up dep checking if needed.
        def munge_flag(flag):
            flag_value = self.get_options().get(flag, None)
            return None if flag_value == "off" else flag_value

        self._check_missing_direct_deps = munge_flag("missing_direct_deps")
        self._check_unnecessary_deps = munge_flag("unnecessary_deps")
        self._target_whitelist = [
            Address.parse(s) for s in self.get_options().missing_deps_whitelist
        ]

    @property
    def cache_target_dirs(self):
        return True

    @memoized_property
    def _distribution(self):
        return DistributionLocator.cached()

    @memoized_property
    def _analyzer(self):
        return JvmDependencyAnalyzer(
            get_buildroot(), self._distribution, self.context.products.get_data("runtime_classpath")
        )

    def execute(self):
        if self._skip(self.get_options()):
            return

        classpath_product = self.context.products.get_data("runtime_classpath")
        fingerprint_strategy = DependencyContext.global_instance().create_fingerprint_strategy(
            classpath_product
        )

        targets = [target for target in self.context.targets() if hasattr(target, "strict_deps")]

        with self.invalidated(
            targets, fingerprint_strategy=fingerprint_strategy, invalidate_dependents=True
        ) as invalidation_check:
            for vt in invalidation_check.invalid_vts:
                product_deps_for_target = self.context.products.get_data(
                    "product_deps_by_target"
                ).get(vt.target)
                if product_deps_for_target is not None:
                    self.check(vt.target, product_deps_for_target)

    def check(self, src_tgt, actual_deps):
        """Check for missing deps.

        See docstring for _compute_missing_deps for details.
        """
        if self._check_missing_direct_deps or self._check_unnecessary_deps:
            missing_file_deps, missing_direct_tgt_deps = self._compute_missing_deps(
                src_tgt, actual_deps
            )

            buildroot = get_buildroot()

            def shorten(path):  # Make the output easier to read.
                if path.startswith(buildroot):
                    return os.path.relpath(path, buildroot)
                return path

            def filter_whitelisted(missing_deps):
                # Removing any targets that exist in the whitelist from the list of dependency issues.
                return [
                    (tgt_pair, evidence)
                    for (tgt_pair, evidence) in missing_deps
                    if tgt_pair[0].address not in self._target_whitelist
                ]

            missing_direct_tgt_deps = filter_whitelisted(missing_direct_tgt_deps)

            if self._check_missing_direct_deps and missing_direct_tgt_deps:
                log_fn = (
                    self.context.log.error
                    if self._check_missing_direct_deps == "fatal"
                    else self.context.log.warn
                )
                for (tgt_pair, evidence) in missing_direct_tgt_deps:
                    evidence_str = "\n".join(
                        ["  {} uses {}".format(e[0].address.spec, shorten(e[1])) for e in evidence]
                    )
                    log_fn(
                        "Missing direct BUILD dependency {} -> {} because:\n{}".format(
                            tgt_pair[0].address.spec, tgt_pair[1].address.spec, evidence_str
                        )
                    )
                if self._check_missing_direct_deps == "fatal":
                    raise TaskError("Missing direct deps.")

            if self._check_unnecessary_deps:
                log_fn = (
                    self.context.log.error
                    if self._check_unnecessary_deps == "fatal"
                    else self.context.log.warn
                )
                had_unused = self._do_check_unnecessary_deps(src_tgt, actual_deps, log_fn)
                if had_unused and self._check_unnecessary_deps == "fatal":
                    raise TaskError("Unnecessary deps.")

    def _compute_missing_deps(self, src_tgt, actual_deps):
        """Computes deps that are used by the compiler but not specified in a BUILD file.

        These deps are bugs waiting to happen: the code may happen to compile because the dep was
        brought in some other way (e.g., by some other root target), but that is obviously fragile.

        Note that in practice we're OK with reliance on indirect deps that are only brought in
        transitively. E.g., in Scala type inference can bring in such a dep subtly. Fortunately these
        cases aren't as fragile as a completely missing dependency. It's still a good idea to have
        explicit direct deps where relevant, so we optionally warn about indirect deps, to make them
        easy to find and reason about.

        - actual_deps: a map src -> list of actual deps (source, class or jar file) as noted by the
          compiler.

        Returns a tuple (missing_file_deps, missing_direct_tgt_deps) where:

        - missing_file_deps: a list of dep_files where src_tgt requires dep_file, and we're unable
          to map to a target (because its target isn't in the total set of targets in play,
          and we don't want to parse every BUILD file in the workspace just to find it).

        - missing_direct_tgt_deps: a list of dep_tgts where src_tgt is missing a direct dependency
                                   on dep_tgt but has a transitive dep on it.

        All paths in the input and output are absolute.
        """
        analyzer = self._analyzer

        def must_be_explicit_dep(dep):
            # We don't require explicit deps on the java runtime, so we shouldn't consider that
            # a missing dep.
            return dep not in analyzer.bootstrap_jar_classfiles and not dep.startswith(
                self._distribution.real_home
            )

        def target_or_java_dep_in_targets(target, targets):
            # We want to check if the target is in the targets collection
            #
            # However, for the special case of scala_library that has a java_sources
            # reference we're ok if that exists in targets even if the scala_library does not.

            if target in targets:
                return True
            elif isinstance(target, ScalaLibrary):
                return any(t in targets for t in target.java_sources)
            else:
                return False

        # Find deps that are actual but not specified.
        missing_file_deps = OrderedSet()  # (src, src).
        missing_direct_tgt_deps_map = defaultdict(list)  # The same, but for direct deps.

        targets_by_file = analyzer.targets_by_file(self.context.targets())
        for actual_dep in filter(must_be_explicit_dep, actual_deps):
            actual_dep_tgts = targets_by_file.get(actual_dep)
            # actual_dep_tgts is usually a singleton. If it's not, we only need one of these
            # to be in our declared deps to be OK.
            if actual_dep_tgts is None:
                missing_file_deps.add((src_tgt, actual_dep))
            elif not target_or_java_dep_in_targets(src_tgt, actual_dep_tgts):
                # Obviously intra-target deps are fine.
                canonical_actual_dep_tgt = next(iter(actual_dep_tgts))
                if canonical_actual_dep_tgt not in src_tgt.dependencies:
                    # The canonical dep is the only one a direct dependency makes sense on.
                    # TODO get rid of src usage here. we dont have a way to map class
                    # files back to source files when using jdeps. I think we can get away without
                    # listing the src file directly and just list the target which has the transient
                    # dep
                    missing_direct_tgt_deps_map[(src_tgt, canonical_actual_dep_tgt)].append(
                        (src_tgt, actual_dep)
                    )

        return (list(missing_file_deps), list(missing_direct_tgt_deps_map.items()))

    def _do_check_unnecessary_deps(self, target, actual_deps, log_fn):
        replacement_deps = self._compute_unnecessary_deps(target, actual_deps)
        if not replacement_deps:
            return False

        # Warn or error for unused.
        def joined_dep_msg(deps):
            return "\n  ".join("'{}',".format(dep.address.spec) for dep in sorted(deps))

        flat_replacements = {r for replacements in replacement_deps.values() for r in replacements}
        replacements_msg = ""
        if flat_replacements:
            replacements_msg = f"Suggested replacements:\n  {joined_dep_msg(flat_replacements)}\n"
        unused_msg = (
            "unnecessary BUILD dependencies:\n  {}\n{}"
            "(If you're seeing this message in error, you might need to "
            "change the `scope` of the dependencies.)".format(
                joined_dep_msg(list(replacement_deps.keys())), replacements_msg,
            )
        )
        log_fn(f"Target {target.address.spec} had {unused_msg}")
        return True

    def _compute_unnecessary_deps(self, target, actual_deps):
        """Computes unused deps for the given Target.

        :returns: A dict of directly declared but unused targets, to sets of suggested replacements.
        """
        # Flatten the product deps of this target.
        product_deps = set()
        # TODO update actual deps will just be a list, not a dict when switching to
        # product_deps_by_target_product.
        for dep_entries in actual_deps.values():
            product_deps.update(dep_entries)

        # Determine which of the DEFAULT deps in the declared set of this target were used.
        used = set()
        unused = set()
        for dep, _ in self._analyzer.resolve_aliases(target, scope=Scopes.DEFAULT):
            if dep in used or dep in unused:
                continue
            # TODO: What's a better way to accomplish this check? Filtering by `has_sources` would
            # incorrectly skip "empty" `*_library` targets, which could then be used as a loophole.
            if isinstance(dep, (Resources, UnpackedJars)):
                continue
            # If any of the target's jars or classfiles were used, consider it used.
            if product_deps.isdisjoint(self._analyzer.files_for_target(dep)):
                unused.add(dep)
            else:
                used.add(dep)

        # If there were no unused deps, break.
        if not unused:
            return {}

        # For any deps that were used, count their derived-from targets used as well.
        # TODO: Refactor to do some of this above once tests are in place.
        for dep in list(used):
            for derived_from in dep.derived_from_chain:
                if derived_from in unused:
                    unused.remove(derived_from)
                    used.add(derived_from)

        # Prune derived targets that would be in the set twice.
        for dep in list(unused):
            if set(dep.derived_from_chain) & unused:
                unused.remove(dep)

        if not unused:
            return {}

        # For any deps that were not used, determine whether their transitive deps were used, and
        # recommend those as replacements.
        replacements = {}
        for dep in unused:
            replacements[dep] = set()
            for t in dep.closure():
                if t in used or t in unused:
                    continue
                if not product_deps.isdisjoint(self._analyzer.files_for_target(t)):
                    replacements[dep].add(t.concrete_derived_from)

        return replacements
