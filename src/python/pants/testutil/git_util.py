# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from textwrap import dedent
from typing import Iterator, Optional

from pants.base.build_environment import get_buildroot
from pants.base.revision import Revision
from pants.scm.git import Git
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open

MIN_REQUIRED_GIT_VERSION = Revision.semver("1.7.10")


def git_version() -> Revision:
    """Get a Version() based on installed command-line git's version."""
    stdout = subprocess.run(
        ["git", "--version"], stdout=subprocess.PIPE, encoding="utf-8", check=True
    ).stdout
    # stdout is like 'git version 1.9.1.598.g9119e8b\n'  We want '1.9.1.598'
    matches = re.search(r"\s(\d+(?:\.\d+)*)[\s\.]", stdout)
    if matches is None:
        raise ValueError(f"Not able to parse git version from {stdout}.")
    return Revision.lenient(matches.group(1))


@contextmanager
def initialize_repo(worktree: str, *, gitdir: Optional[str] = None) -> Iterator[Git]:
    """Initialize a git repository for the given `worktree`.

    NB: The given `worktree` must contain at least one file which will be committed to form an initial
    commit.

    :param worktree: The path to the git work tree.
    :param gitdir: An optional path to the `.git` dir to use.
    :returns: A `Git` repository object that can be used to interact with the repo.
    """

    @contextmanager
    def use_gitdir() -> Iterator[str]:
        if gitdir:
            yield gitdir
        else:
            with temporary_dir() as d:
                yield d

    with use_gitdir() as git_dir, environment_as(GIT_DIR=git_dir, GIT_WORK_TREE=worktree):
        subprocess.run(["git", "init"], check=True)
        subprocess.run(["git", "config", "user.email", "you@example.com"], check=True)
        # TODO: This method inherits the global git settings, so if a developer has gpg signing on, this
        # will turn that off. We should probably just disable reading from the global config somehow:
        # https://git-scm.com/docs/git-config.
        subprocess.run(["git", "config", "commit.gpgSign", "false"], check=True)
        subprocess.run(["git", "config", "user.name", "Your Name"], check=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-am", "Add project files."], check=True)
        yield Git(gitdir=git_dir, worktree=worktree)


def create_file_in(worktree, path, content):
    """Creates a file in the given worktree, and returns its path."""
    write_path = os.path.join(worktree, path)
    with safe_open(write_path, "w") as f:
        f.write(dedent(content))
    return write_path


@contextmanager
def mutated_working_copy(files_to_mutate, to_append="\n "):
    """Given a list of files, append whitespace to each of them to trigger a git diff - then reset."""
    assert to_append, "to_append may not be empty"

    for f in files_to_mutate:
        with open(f, "a") as fh:
            fh.write(to_append)
    try:
        yield
    finally:
        seek_point = len(to_append) * -1
        for f in files_to_mutate:
            with open(f, "ab") as fh:
                fh.seek(seek_point, os.SEEK_END)
                fh.truncate()


@contextmanager
def create_isolated_git_repo(to_copy=[]):
    # Isolated Git Repo Structure:
    # worktree
    # |--README
    # |--pants.toml
    # |--3rdparty
    #    |--BUILD
    # |--src
    #    |--resources
    #       |--org/pantsbuild/resourceonly
    #          |--BUILD
    #          |--README.md
    #    |--java
    #       |--org/pantsbuild/helloworld
    #          |--BUILD
    #          |--helloworld.java
    #    |--python
    #       |--python_targets
    #          |--BUILD
    #          |--test_binary.py
    #          |--test_library.py
    #          |--test_unclaimed_src.py
    #       |--sources
    #          |--BUILD
    #          |--sources.py
    #          |--sources.txt
    # |--tests
    #    |--scala
    #       |--org/pantsbuild/cp-directories
    #          |--BUILD
    #          |--ClasspathDirectoriesSpec.scala
    with temporary_dir(root_dir=get_buildroot()) as worktree:

        def create_file(path, content):
            """Creates a file in the isolated git repo."""
            return create_file_in(worktree, path, content)

        def copy_into(path, to_path=None):
            """Copies a file from the real git repo into the isolated git repo."""
            write_path = os.path.join(worktree, to_path or path)
            if os.path.isfile(path):
                safe_mkdir(os.path.dirname(write_path))
                shutil.copyfile(path, write_path)
            elif os.path.isdir(path):
                shutil.copytree(path, write_path)
            else:
                raise TypeError(f"path {path} does not exist or is not a file or directory!")
            return write_path

        create_file("README", "N.B. This is just a test tree.")
        create_file(
            "pants.toml",
            """
            [GLOBAL]
            pythonpath = [
                "{0}/contrib/go/src/python",
                "{0}/pants-plugins/src/python"
            ]
            backend_packages.add = [
                "internal_backend.utilities",
                "pants.contrib.go"
            ]
            backend_packages2.add = [
                "pants.backend.python.lint.black",
            ]
            """.format(
                get_buildroot()
            ),
        )
        copy_into(".gitignore")

        for to_copy in to_copy:
            copy_into(to_copy)

        with initialize_repo(worktree=worktree, gitdir=os.path.join(worktree, ".git")) as git:

            def add_to_git(commit_msg, *files):
                git.add(*files)
                git.commit(commit_msg)

            add_to_git(
                "a go target with default sources",
                create_file("src/go/tester/BUILD", "go_binary()"),
                create_file(
                    "src/go/tester/main.go",
                    """
                    package main
                    import "fmt"
                    func main() {
                      fmt.Println("hello, world")
                    }
                    """,
                ),
            )

            add_to_git(
                "resource file",
                create_file(
                    "src/resources/org/pantsbuild/resourceonly/BUILD",
                    """
                    resources(
                      name='resource',
                      sources=['README.md']
                    )
                    """,
                ),
                create_file(
                    "src/resources/org/pantsbuild/resourceonly/README.md", "Just a resource."
                ),
            )

            add_to_git(
                "hello world java program with a dependency on a resource file",
                create_file(
                    "src/java/org/pantsbuild/helloworld/BUILD",
                    """
                    jvm_binary(
                      dependencies=[
                        'src/resources/org/pantsbuild/resourceonly:resource',
                      ],
                      source='helloworld.java',
                      main='org.pantsbuild.helloworld.HelloWorld',
                    )
                    """,
                ),
                create_file(
                    "src/java/org/pantsbuild/helloworld/helloworld.java",
                    """
                    package org.pantsbuild.helloworld;

                    class HelloWorld {
                      public static void main(String[] args) {
                        System.out.println("Hello, World!\n");
                      }
                    }
                    """,
                ),
            )

            add_to_git(
                "scala test target",
                copy_into(
                    "testprojects/tests/scala/org/pantsbuild/testproject/cp-directories",
                    "tests/scala/org/pantsbuild/cp-directories",
                ),
            )

            add_to_git(
                "python targets",
                copy_into("testprojects/src/python/python_targets", "src/python/python_targets"),
            )

            add_to_git(
                'a python_library with resources=["filename"]',
                copy_into("testprojects/src/python/sources", "src/python/sources"),
            )

            add_to_git("3rdparty/BUILD", copy_into("3rdparty/BUILD"))

            with environment_as(PANTS_BUILDROOT_OVERRIDE=worktree):
                yield worktree
