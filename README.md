# Pants Build System

Pants is a build system for software projects in a variety of languages.
It works particularly well for a source code repository that contains
many distinct projects.

Friendly documentation: http://www.pantsbuild.org/

We release to [PyPI](https://pypi.python.org/pypi)
[![version](https://img.shields.io/pypi/v/pantsbuild.pants.svg)](https://pypi.python.org/pypi/pantsbuild.pants)
[![license](https://img.shields.io/pypi/l/pantsbuild.pants.svg)](https://pypi.python.org/pypi/pantsbuild.pants)
[![downloads](https://img.shields.io/pypi/dm/pantsbuild.pants.svg)](https://pypi.python.org/pypi/pantsbuild.pants)

We use [Travis CI](https://travis-ci.org) to verify the build
[![Build Status](https://travis-ci.org/pantsbuild/pants.svg?branch=master)](https://travis-ci.org/pantsbuild/pants/branches).

We use [Coveralls](https://coveralls.io) to monitor test coverage
[![Coverage Status](https://coveralls.io/repos/pantsbuild/pants/badge.png?branch=master)](https://coveralls.io/r/pantsbuild/pants).

# Requirements

At a minimum, pants requires the following to run properly:

* Linux or Mac OS X
* Python 2.7.x (the latest stable version of 2.7 is recommended)
* A C compiler, system headers, Python headers (to compile native Python modules) and the libffi
  library and headers (to compile and link modules that use CFFI to access native code).
* Internet access (so that pants can fully bootstrap itself)

Additionally, if you use the jvm backend to work with java or scala code (installed by default):

* OpenJDK or Oracle JDK version 7 or greater
