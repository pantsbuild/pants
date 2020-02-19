# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import multiprocessing
import os
import re
import subprocess
from collections import namedtuple
from multiprocessing.pool import ThreadPool

from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.build_graph.target_scopes import Scopes
from pants.task.target_restriction_mixins import (
    HasSkipAndTransitiveOptionsMixin,
    SkipAndTransitiveOptionsRegistrar,
)
from pants.util import desktop
from pants.util.dirutil import safe_mkdir, safe_walk
from pants.util.memo import memoized_property

Jvmdoc = namedtuple("Jvmdoc", ["tool_name", "product_type"])


# TODO: Shouldn't this be a NailgunTask?
# TODO(John Sirois): The --skip flag supports the JarPublish task and is an abstraction leak.
# It allows folks doing a local-publish to skip an expensive and un-needed step.
# Remove this flag and instead support conditional requirements being registered against
# the round manager.  This may require incremental or windowed flag parsing that happens bit by
# bit as tasks are recursively prepared vs. the current all-at once style.
class JvmdocGen(SkipAndTransitiveOptionsRegistrar, HasSkipAndTransitiveOptionsMixin, JvmTask):
    @classmethod
    def jvmdoc(cls):
        """Subclasses should return their Jvmdoc configuration."""
        raise NotImplementedError()

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        tool_name = cls.jvmdoc().tool_name

        register(
            "--include-codegen",
            type=bool,
            fingerprint=True,
            help=f"Create {tool_name} for generated code.",
        )

        register(
            "--combined",
            type=bool,
            fingerprint=True,
            help="Generate {0} for all targets combined, instead of each target "
            "individually.".format(tool_name),
        )

        register(
            "--open",
            type=bool,
            help=f"Open the generated {tool_name} in a browser (implies --combined).",
        )

        register(
            "--ignore-failure",
            type=bool,
            fingerprint=True,
            help=f"Do not consider {tool_name} errors to be build errors.",
        )

        register(
            "--exclude-patterns",
            type=list,
            default=[],
            fingerprint=True,
            help="Patterns for targets to be excluded from doc generation.",
        )

    @classmethod
    def product_types(cls):
        return [cls.jvmdoc().product_type]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        options = self.get_options()
        self._include_codegen = options.include_codegen
        self.open = options.open
        self.combined = self.open or options.combined
        self.ignore_failure = options.ignore_failure

    @memoized_property
    def _exclude_patterns(self):
        return [re.compile(x) for x in set(self.get_options().exclude_patterns or [])]

    def generate_doc(self, language_predicate, create_jvmdoc_command):
        """Generate an execute method given a language predicate and command to create
        documentation.

        language_predicate: a function that accepts a target and returns True if the target is of that
                            language
        create_jvmdoc_command: (classpath, directory, *targets) -> command (string) that will generate
                               documentation documentation for targets
        """
        catalog = self.context.products.isrequired(self.jvmdoc().product_type)
        if catalog and self.combined:
            raise TaskError(
                f"Cannot provide {self.jvmdoc().product_type} target mappings for combined output"
            )

        def docable(target):
            if not language_predicate(target):
                self.context.log.debug(
                    f"Skipping [{target.address.spec}] because it is does not pass the language predicate"
                )
                return False
            if not self._include_codegen and target.is_synthetic:
                self.context.log.debug(
                    f"Skipping [{target.address.spec}] because it is a synthetic target"
                )
                return False
            for pattern in self._exclude_patterns:
                if pattern.search(target.address.spec):
                    self.context.log.debug(
                        f"Skipping [{target.address.spec}] because it matches exclude pattern '{pattern.pattern}'"
                    )
                    return False
            return True

        targets = self.get_targets(predicate=docable)
        if not targets:
            return

        with self.invalidated(targets, invalidate_dependents=self.combined) as invalidation_check:

            def find_invalid_targets():
                invalid_targets = set()
                for vt in invalidation_check.invalid_vts:
                    invalid_targets.update(vt.targets)
                return invalid_targets

            invalid_targets = list(find_invalid_targets())
            if invalid_targets:
                if self.combined:
                    self._generate_combined(targets, create_jvmdoc_command)
                else:
                    self._generate_individual(invalid_targets, create_jvmdoc_command)

        if self.open and self.combined:
            try:
                desktop.ui_open(os.path.join(self.workdir, "combined", "index.html"))
            except desktop.OpenError as e:
                raise TaskError(e)

        if catalog:
            for target in targets:
                gendir = self._gendir(target)
                jvmdocs = []
                for root, dirs, files in safe_walk(gendir):
                    jvmdocs.extend(os.path.relpath(os.path.join(root, f), gendir) for f in files)
                self.context.products.get(self.jvmdoc().product_type).add(target, gendir, jvmdocs)

    def _generate_combined(self, targets, create_jvmdoc_command):
        gendir = os.path.join(self.workdir, "combined")
        if targets:
            classpath = self.classpath(targets, include_scopes=Scopes.JVM_COMPILE_SCOPES)
            safe_mkdir(gendir, clean=True)
            command = create_jvmdoc_command(classpath, gendir, *targets)
            if command:
                self.context.log.debug(
                    f"Running create_jvmdoc in {gendir} with {' '.join(command)}"
                )
                result, gendir = create_jvmdoc(command, gendir)
                self._handle_create_jvmdoc_result(targets, result, command)

    def _generate_individual(self, targets, create_jvmdoc_command):
        jobs = {}
        for target in targets:
            gendir = self._gendir(target)
            classpath = self.classpath([target], include_scopes=Scopes.JVM_COMPILE_SCOPES)
            command = create_jvmdoc_command(classpath, gendir, target)
            if command:
                jobs[gendir] = (target, command)

        if jobs:
            # Use ThreadPool as there may be dangling processes that cause identical run id and
            # then buildstats error downstream. https://github.com/pantsbuild/pants/issues/6785
            with contextlib.closing(
                ThreadPool(processes=min(len(jobs), multiprocessing.cpu_count()))
            ) as pool:
                # map would be a preferable api here but fails after the 1st batch with an internal:
                # ...
                #  File "...src/python/pants/backend/jvm/tasks/jar_create.py", line 170, in javadocjar
                #      pool.map(createjar, jobs)
                #    File "...lib/python2.6/multiprocessing/pool.py", line 148, in map
                #      return self.map_async(func, iterable, chunksize).get()
                #    File "...lib/python2.6/multiprocessing/pool.py", line 422, in get
                #      raise self._value
                #  NameError: global name 'self' is not defined
                futures = []
                self.context.log.debug(
                    "Begin multiprocessing section; output may be misordered or garbled"
                )
                try:
                    for gendir, (target, command) in jobs.items():
                        self.context.log.debug(
                            "Running create_jvmdoc in {} with {}".format(gendir, " ".join(command))
                        )
                        futures.append(pool.apply_async(create_jvmdoc, args=(command, gendir)))

                    for future in futures:
                        result, gendir = future.get()
                        target, command = jobs[gendir]
                        self._handle_create_jvmdoc_result([target], result, command)
                finally:
                    # In the event of an exception, we want to call terminate() because otherwise
                    # we get errors on exit when multiprocessing tries to do it, because what
                    # is dead may never die.
                    pool.terminate()
                    self.context.log.debug("End multiprocessing section")

    def _handle_create_jvmdoc_result(self, targets, result, command):
        if result != 0:
            targetlist = ", ".join(target.address.spec for target in targets)
            message = "Failed to process {} for {} [{}]: {}".format(
                self.jvmdoc().tool_name, targetlist, result, " ".join(command)
            )
            if self.ignore_failure:
                self.context.log.warn(message)
            else:
                raise TaskError(message)

    def _gendir(self, target):
        return os.path.join(self.workdir, target.id)


def create_jvmdoc(command, gendir):
    try:
        safe_mkdir(gendir, clean=True)
        process = subprocess.Popen(command)
        result = process.wait()
        return result, gendir
    except OSError:
        return 1, gendir
