Master Pre-Releases
===================

This document describes ``dev`` releases which occur weekly from master, and which do
not undergo the vetting associated with ``stable`` releases.

1.4.0.dev0 (5/12/2017)
----------------------

API Changes
~~~~~~~~~~~

* Support "exports" for thrift targets (#4564)
  `PR #4564 <https://github.com/pantsbuild/pants/pull/4564>`_

* Make setup_py tasks provide 'python_dists' product. (#4498)
  `PR #4498 <https://github.com/pantsbuild/pants/pull/4498>`_

* Include API that will store target info in run_tracker (#4561)
  `PR #4561 <https://github.com/pantsbuild/pants/pull/4561>`_

Bugfixes
~~~~~~~~

* Fix built-in macros for the mutable ParseContext (#4583)
  `PR #4583 <https://github.com/pantsbuild/pants/pull/4583>`_

* Exclude only roots for exclude-target-regexp in v2 (#4578)
  `PR #4578 <https://github.com/pantsbuild/pants/pull/4578>`_
  `PR #451) <https://github.com/twitter/commons/pull/451)>`_

* Fix a pytest path mangling bug. (#4565)
  `PR #4565 <https://github.com/pantsbuild/pants/pull/4565>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Specify a workunit for node.js test and run. (#4572)
  `PR #4572 <https://github.com/pantsbuild/pants/pull/4572>`_

* Include transitive Resources targets in PrepareResources. (#4569)
  `PR #4569 <https://github.com/pantsbuild/pants/pull/4569>`_

* [engine] Don't recreate a graph just for validation (#4566)
  `PR #4566 <https://github.com/pantsbuild/pants/pull/4566>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Update release docs to use a label instead of a spreadsheet for backports. (#4574)
  `PR #4574 <https://github.com/pantsbuild/pants/pull/4574>`_


1.3.0rc0 (05/08/2017)
---------------------

The first release candidate for the 1.3.0 stable release branch! Almost 7 months
in the making, this release brings a huge set of changes, which will be summarized
for the 1.3.0 final release.

Please test this release candidate to help ensure a stable stable 1.3.0 release!

API Changes
~~~~~~~~~~~

* [engine] Deprecate and replace `traversable_dependency_specs`. (#4542)
  `PR #4542 <https://github.com/pantsbuild/pants/pull/4542>`_

* Move scalastyle and java checkstyle into the `lint` goal (#4540)
  `PR #4540 <https://github.com/pantsbuild/pants/pull/4540>`_

Bugfixes
~~~~~~~~

* Warn when implicit_sources would be used, but is disabled (#4559)
  `PR #4559 <https://github.com/pantsbuild/pants/pull/4559>`_

* Ignore dot-directories by default (#4556)
  `PR #4556 <https://github.com/pantsbuild/pants/pull/4556>`_

* Dockerize native engine builds. (#4554)
  `PR #4554 <https://github.com/pantsbuild/pants/pull/4554>`_

* Make "changed" tasks work with deleted files (#4546)
  `PR #4546 <https://github.com/pantsbuild/pants/pull/4546>`_

* Fix tag builds after the more-complete isort edit. (#4532)
  `PR #4532 <https://github.com/pantsbuild/pants/pull/4532>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [engine] Support tracebacks in engine traces; only show them w/ flag (#4549)
  `PR #4549 <https://github.com/pantsbuild/pants/pull/4549>`_

* Fix two usages of Address.build_file that avoided detection during the deprecation. (#4538)
  `PR #4538 <https://github.com/pantsbuild/pants/pull/4538>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Update target scope docs (#4553)
  `PR #4553 <https://github.com/pantsbuild/pants/pull/4553>`_

* [engine] use rust doc comments instead of javadoc style comments (#4550)
  `PR #4550 <https://github.com/pantsbuild/pants/pull/4550>`_

1.3.0.dev19 (4/28/2017)
-----------------------
A weekly unstable release.

API Changes
~~~~~~~~~~~

* Add support for 'deployable_archives' for go and cpp rules. (#4518)
  `PR #4518 <https://github.com/pantsbuild/pants/pull/4518>`_

* Deprecate `BuildFileAddress.build_file` (#4511)
  `PR #4511 <https://github.com/pantsbuild/pants/pull/4511>`_

* Make usage of pantsd imply usage of watchman. (#4512)
  `PR #4512 <https://github.com/pantsbuild/pants/pull/4512>`_

* Enable --compile-zinc-use-classpath-jars by default (#4525)
  `PR #4525 <https://github.com/pantsbuild/pants/pull/4525>`_

Bugfixes
~~~~~~~~

* Fix the kythe bootclasspath. (#4527)
  `PR #4527 <https://github.com/pantsbuild/pants/pull/4527>`_

* Revert the zinc `1.0.0-X7` upgrade (#4510)
  `PR #4510 <https://github.com/pantsbuild/pants/pull/4510>`_

* Invoke setup-py using an interpreter that matches the target. (#4482)
  `PR #4482 <https://github.com/pantsbuild/pants/pull/4482>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [pantsd] Ensure rust panics surface in output or daemon logs (#4522)
  `PR #4522 <https://github.com/pantsbuild/pants/pull/4522>`_

* Make the release script more idempotent. (#4504)
  `PR #4504 <https://github.com/pantsbuild/pants/pull/4504>`_

* [engine] pass on ResolveErrors during address injection (#4523)
  `PR #4523 <https://github.com/pantsbuild/pants/pull/4523>`_

* [engine] Improve error messages for missing/empty dirs (#4517)
  `PR #4517 <https://github.com/pantsbuild/pants/pull/4517>`_

* Render failed junit tests with no target owner. (#4521)
  `PR #4521 <https://github.com/pantsbuild/pants/pull/4521>`_

* [engine] Better error messages for missing targets (#4509)
  `PR #4509 <https://github.com/pantsbuild/pants/pull/4509>`_

* Options should only default to --color=True when sys.stdout isatty (#4503)
  `PR #4503 <https://github.com/pantsbuild/pants/pull/4503>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Add a scala specs2 example (#4516)
  `PR #4516 <https://github.com/pantsbuild/pants/pull/4516>`_


1.3.0.dev18 (4/21/2017)
-----------------------
A weekly unstable release.

API Changes
~~~~~~~~~~~

* Create a lint goal and put checkstyle tasks in it. (#4481)
  `PR #4481 <https://github.com/pantsbuild/pants/pull/4481>`_

Bugfixes
~~~~~~~~

* Fix some incorrectly formatted dev release semvers. (#4501)
  `PR #4501 <https://github.com/pantsbuild/pants/pull/4501>`_

* Make go targets work with v2 changed. (#4500)
  `PR #4500 <https://github.com/pantsbuild/pants/pull/4500>`_

* Fix pytest fixture registration bug. (#4497)
  `PR #4497 <https://github.com/pantsbuild/pants/pull/4497>`_

* Don't trigger deprecated scope warnings for options from the DEFAULT section (#4487)
  `PR #4487 <https://github.com/pantsbuild/pants/pull/4487>`_

* Ensure that incomplete scalac plugin state doesn't get memoized. (#4480)
  `PR #4480 <https://github.com/pantsbuild/pants/pull/4480>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [engine] Skip re-creating copy of address if no variants (#4032)
  `PR #4032 <https://github.com/pantsbuild/pants/pull/4032>`_

* Default `Fetcher.ProgressListener` to stderr. (#4499)
  `PR #4499 <https://github.com/pantsbuild/pants/pull/4499>`_

* A contrib plugin to run the Kythe indexer on Java source. (#4457)
  `PR #4457 <https://github.com/pantsbuild/pants/pull/4457>`_

* Keep failed target mapping free from `None` key. (#4493)
  `PR #4493 <https://github.com/pantsbuild/pants/pull/4493>`_

* Bring back --no-fast mode in pytest run. (#4491)
  `PR #4491 <https://github.com/pantsbuild/pants/pull/4491>`_

* [engine] Use enum for RuleEdges keys, add factory for Selects w/o variants (#4461)
  `PR #4461 <https://github.com/pantsbuild/pants/pull/4461>`_

* Bump scala platform versions to 2.11.11 and 2.12.2 (#4488)
  `PR #4488 <https://github.com/pantsbuild/pants/pull/4488>`_

* Get rid of the '2' registrations of the new python tasks. (#4486)
  `PR #4486 <https://github.com/pantsbuild/pants/pull/4486>`_

* Make pytest report sources paths relative to the buildroot. (#4472)
  `PR #4472 <https://github.com/pantsbuild/pants/pull/4472>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* [docs] fix broken link to certifi (#3508)
  `PR #3508 <https://github.com/pantsbuild/pants/pull/3508>`_

* [docs] Fix links in Go README (#3719)
  `PR #3719 <https://github.com/pantsbuild/pants/pull/3719>`_

* Update globs.md (#4476)
  `PR #4476 <https://github.com/pantsbuild/pants/pull/4476>`_

* Fix some compiler plugin documentation nits. (#4462)
  `PR #4462 <https://github.com/pantsbuild/pants/pull/4462>`_

* Convert readthedocs link for their .org -> .io migration for hosted projects (#3542)
  `PR #3542 <https://github.com/pantsbuild/pants/pull/3542>`_


1.3.0.dev17 (4/15/2017)
-----------------------
A weekly unstable release, highlighted by setting the new python backend as the default.

API Changes
~~~~~~~~~~~
* Upgrade pants to current versions of pytest et al. (#4410)
  `PR #4410 <https://github.com/pantsbuild/pants/pull/4410>`_

* Add ParseContext singleton helper (#4466)
  `PR #4466 <https://github.com/pantsbuild/pants/pull/4466>`_

* Make the new python backend the default. (#4441)
  `PR #4441 <https://github.com/pantsbuild/pants/pull/4441>`_

Bugfixes
~~~~~~~~
* Correctly inject Yarn into the Node path when it is in use (#4455)
  `PR #4455 <https://github.com/pantsbuild/pants/pull/4455>`_

* Fix resource loading issue in the python eval task. (#4452)
  `PR #4452 <https://github.com/pantsbuild/pants/pull/4452>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* [engine] Use RuleGraph for task lookup instead of Tasks (#4371)
  `PR #4371 <https://github.com/pantsbuild/pants/pull/4371>`_

* Re-use pre-built Linux engine binaries for bintray upload. (#4454)
  `PR #4454 <https://github.com/pantsbuild/pants/pull/4454>`_

* Replace `indices` with `indexes` in docs (#4453)
  `PR #4453 <https://github.com/pantsbuild/pants/pull/4453>`_

* Avoid re-walking for every target root in minimize (#4463)
  `PR #4463 <https://github.com/pantsbuild/pants/pull/4463>`_


1.3.0.dev16 (4/08/2017)
-----------------------
A weekly unstable release.

This release brings the new `pantsbuild.pants.contrib.jax_ws
<https://github.com/pantsbuild/pants/tree/master/contrib/jax_ws>`_ plugin that can generate Java
client stubs from WSDL sources. Thanks to Chris Heisterkamp for this!

The release also pulls in a few fixes for python requirement resolution in the PEX library used by
pants. In the past, the python-setup.resolver_allow_prereleases configuration option would not
always be resepected; it now is. Additionally, a longstanding bug in transitive requirement
resolution that would lead to erroneous 'Ambiguous resolvable' errors has now been fixed. Thanks to
Todd Gardner and Nathan Butler for these fixes!

New Features
~~~~~~~~~~~~

* Add JAX-WS plugin to generate client stub files from WSDL files (#4411)
  `PR #4411 <https://github.com/pantsbuild/pants/pull/4411>`_

API Changes
~~~~~~~~~~~

* Disable unused deps by default (#4440)
  `PR #4440 <https://github.com/pantsbuild/pants/pull/4440>`_

* Bump pex version to 1.2.6 (#4442)
  `PR #4442 <https://github.com/pantsbuild/pants/pull/4442>`_

* Upgrade to pex 1.2.5. (#4434)
  `PR #4434 <https://github.com/pantsbuild/pants/pull/4434>`_

* Update 3rdparty jars: args4j to 2.33, jsr305 to 3.0.2, easymock to 3.4, burst-junit4 to 1.1.1, commons-io to 2.5, and mockito-core to 2.7.21 (#4421)
  `PR #4421 <https://github.com/pantsbuild/pants/pull/4421>`_

Bugfixes
~~~~~~~~

* Default --resolver-allow-prereleases to None. (#4445)
  `PR #4445 <https://github.com/pantsbuild/pants/pull/4445>`_

* Fully hydrate a BuildGraph for the purposes of ChangedCalculator. (#4424)
  `PR #4424 <https://github.com/pantsbuild/pants/pull/4424>`_

* Upgrade zinc to `1.0.0-X7` (python portion) (#4419)
  `Issue #75 <https://github.com/sbt/util/issues/75>`_
  `Issue #218 <https://github.com/sbt/zinc/issues/218>`_
  `PR #4419 <https://github.com/pantsbuild/pants/pull/4419>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [engine] New shared impl (#4429)
  `PR #4429 <https://github.com/pantsbuild/pants/pull/4429>`_
  `PR #442) <https://github.com/alexcrichton/futures-rs/pull/442)>`_

* Speed up changed task when backed by v2 engine. (#4422)
  `PR #4422 <https://github.com/pantsbuild/pants/pull/4422>`_

1.3.0.dev15 (4/03/2017)
-----------------------
A weekly unstable release, delayed by a week!

This release contains multiple significant new features, including the "exports" literal
on JVM targets (to better support common cases in repositories using "strict_deps"), the
initial release of the new python backend with caching support, a new "outdated.ivy" goal
to report which JVM dependencies are out of date, speedups for go builds, and last but not
least: the first release with the v2 engine enabled by default (to enable stabilization of
the pants daemon before the 1.3.x stable releases).

Thanks to the contributors!

New Features
~~~~~~~~~~~~

* Add outdated.ivy command that looks for 3rd party jar updates with Ivy (#4386)
  `PR #4386 <https://github.com/pantsbuild/pants/pull/4386>`_

* Implement exports literal in jvm_target (#4329)
  `PR #4329 <https://github.com/pantsbuild/pants/pull/4329>`_

* Make jar_library target export all its dependencies (#4395)
  `PR #4395 <https://github.com/pantsbuild/pants/pull/4395>`_

* A temporary `python2` backend with just the new python pipeline tasks. (#4378)
  `PR #4378 <https://github.com/pantsbuild/pants/pull/4378>`_

* [engine] include rule graph in dot files generated with --visualize-to (#4367)
  `PR #4367 <https://github.com/pantsbuild/pants/pull/4367>`_

* Speed up typical go builds. (#4362)
  `PR #4362 <https://github.com/pantsbuild/pants/pull/4362>`_

* Enable v2 engine by default. (#4340)
  `PR #4340 <https://github.com/pantsbuild/pants/pull/4340>`_

API Changes
~~~~~~~~~~~

* Use released ivy-dependency-update-checker jar tool for outdated.ivy command (#4406)
  `PR #4406 <https://github.com/pantsbuild/pants/pull/4406>`_

* Improve our use of gofmt. (#4379)
  `PR #4379 <https://github.com/pantsbuild/pants/pull/4379>`_

* Bump the default scala 2.12 minor version to 2.12.1. (#4383)
  `PR #4383 <https://github.com/pantsbuild/pants/pull/4383>`_

Bugfixes
~~~~~~~~

* [pantsd] Lazily initialize `CpuPool` for `Core` and `PosixFS` to address `SchedulerService` crash on Linux. (#4412)
  `PR #4412 <https://github.com/pantsbuild/pants/pull/4412>`_

* [pantsd] Address pantsd-runner hang on Linux and re-enable integration test. (#4407)
  `PR #4407 <https://github.com/pantsbuild/pants/pull/4407>`_

* Switch the new PytestRun task to use junitxml output. (#4403)
  `Issue #3837 <https://github.com/pantsbuild/pants/issues/3837>`_
  `PR #4403 <https://github.com/pantsbuild/pants/pull/4403>`_

* [contrib/go] only pass go sources to gofmt (#4402)
  `PR #4402 <https://github.com/pantsbuild/pants/pull/4402>`_

* Remove Address/BuildFileAddress ambiguity and fix list-owners (#4399)
  `PR #4399 <https://github.com/pantsbuild/pants/pull/4399>`_

* Avoid creating deprecated resources in JavaAgent's constructor (#4400)
  `PR #4400 <https://github.com/pantsbuild/pants/pull/4400>`_

* Invalidate all go compiles when the go version changes. (#4382)
  `PR #4382 <https://github.com/pantsbuild/pants/pull/4382>`_

* Repair handling on resources kwargs for changed. (#4396)
  `PR #4396 <https://github.com/pantsbuild/pants/pull/4396>`_

* python-binary-create task maps all product directories to the same target (#4390)
  `PR #4390 <https://github.com/pantsbuild/pants/pull/4390>`_

* Fix Go source excludes; Cleanup old filespec matching (#4350)
  `PR #4350 <https://github.com/pantsbuild/pants/pull/4350>`_

* inserted a www. into some pantsbuild links to un-break them (#4388)
  `PR #4388 <https://github.com/pantsbuild/pants/pull/4388>`_

* Switch to using the new PythonEval task instead of the old one. (#4374)
  `PR #4374 <https://github.com/pantsbuild/pants/pull/4374>`_

* Adding pragma back in the default coverage config (#4232)
  `PR #4232 <https://github.com/pantsbuild/pants/pull/4232>`_

* decode compile logs (#4368)
  `PR #4368 <https://github.com/pantsbuild/pants/pull/4368>`_

* Skip cycle detection test (#4361)
  `PR #4361 <https://github.com/pantsbuild/pants/pull/4361>`_

* [engine] Fix whitelisting of files in `pants_ignore` (#4357)
  `PR #4357 <https://github.com/pantsbuild/pants/pull/4357>`_

* Revert the shared workaround (#4354)
  `PR #4348 <https://github.com/pantsbuild/pants/pull/4348>`_
  `PR #4354 <https://github.com/pantsbuild/pants/pull/4354>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Cleanup and give better debug output for exclude patterns in findbugs and errorprone (#4408)
  `PR #4408 <https://github.com/pantsbuild/pants/pull/4408>`_

* [engine] Rules as decorators (#4369)
  `PR #4369 <https://github.com/pantsbuild/pants/pull/4369>`_

* [engine] Move snapshots from /tmp to pants workdir. (#4373)
  `PR #4373 <https://github.com/pantsbuild/pants/pull/4373>`_

* [engine] Init Tasks before Scheduler (#4381)
  `PR #4381 <https://github.com/pantsbuild/pants/pull/4381>`_

* TravisCI tuning. (#4385)
  `PR #4385 <https://github.com/pantsbuild/pants/pull/4385>`_

* Switch the pants repo entirely over to the new python pipeline. (#4316)
  `PR #4316 <https://github.com/pantsbuild/pants/pull/4316>`_

* Fix missing deps. (#4372)
  `PR #4372 <https://github.com/pantsbuild/pants/pull/4372>`_

* A PythonEval task that uses the new pipeline. (#4341)
  `PR #4341 <https://github.com/pantsbuild/pants/pull/4341>`_

* Create a pants.init package. (#4356)
  `PR #4356 <https://github.com/pantsbuild/pants/pull/4356>`_

* [engine] short circuit native engine build failures (#4353)
  `PR #4353 <https://github.com/pantsbuild/pants/pull/4353>`_

* Check for stale native_engine_version. (#4360)
  `PR #4360 <https://github.com/pantsbuild/pants/pull/4360>`_

* [engine] Improving performance by iteratively expanding products within SelectTransitive (#4349)
  `PR #4349 <https://github.com/pantsbuild/pants/pull/4349>`_

* Move all logic out of Context (#4343)
  `PR #4343 <https://github.com/pantsbuild/pants/pull/4343>`_

* Add support for subprojects in v2 (#4346)
  `PR #4346 <https://github.com/pantsbuild/pants/pull/4346>`_

* Fix missing and circular deps. (#4345)
  `Issue #4138 <https://github.com/pantsbuild/pants/issues/4138>`_
  `PR #4345 <https://github.com/pantsbuild/pants/pull/4345>`_

1.3.0.dev14 (3/17/2017)
-----------------------
A weekly unstable release.

API Changes
~~~~~~~~~~~

* [pantsd] Add an option to configure the watchman startup timeout. (#4332)
  `PR #4332 <https://github.com/pantsbuild/pants/pull/4332>`_

* Relativize jar_dependency.base_path (#4326)
  `PR #4326 <https://github.com/pantsbuild/pants/pull/4326>`_

Bugfixes
~~~~~~~~

* Fix bad import from race commits (#4335)
  `PR #4335 <https://github.com/pantsbuild/pants/pull/4335>`_

* Misc fixes to python tasks: (#4323)
  `PR #4323 <https://github.com/pantsbuild/pants/pull/4323>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix product mapping for ivy resolve when libraries are not jar files (#4339)
  `PR #4339 <https://github.com/pantsbuild/pants/pull/4339>`_

* Refactor the new SelectInterpreter and GatherSources tasks. (#4337)
  `PR #4337 <https://github.com/pantsbuild/pants/pull/4337>`_

* Lock down the native-engine-version (#4338)
  `PR #4338 <https://github.com/pantsbuild/pants/pull/4338>`_

* [engine] Inline execution of Select/Dependencies/Projection/Literal (#4331)
  `PR #4331 <https://github.com/pantsbuild/pants/pull/4331>`_

* Upgrade to mock 2.0.0. (#4336)
  `PR #4336 <https://github.com/pantsbuild/pants/pull/4336>`_

* [engine] Improve memory layout for Graph (#4333)
  `PR #4333 <https://github.com/pantsbuild/pants/pull/4333>`_

* [engine] Split SelectDependencies into SelectDependencies and SelectTransitive (#4334)
  `PR #4334 <https://github.com/pantsbuild/pants/pull/4334>`_

* Simplify PythonSetup usage (#4328)
  `PR #4328 <https://github.com/pantsbuild/pants/pull/4328>`_

* Bump native engine version. (#4330)
  `PR #4330 <https://github.com/pantsbuild/pants/pull/4330>`_

* [engine] Move to new-style CFFI callbacks. (#4324)
  `PR #4324 <https://github.com/pantsbuild/pants/pull/4324>`_

* Profile the pants invocations in integration tests. (#4325)
  `PR #4325 <https://github.com/pantsbuild/pants/pull/4325>`_

1.3.0.dev13 (3/10/2017)
-----------------------
A weekly unstable release.

API Changes
~~~~~~~~~~~

* Bump pex version to latest. (#4314)
  `PR #4314 <https://github.com/pantsbuild/pants/pull/4314>`_

New Features
~~~~~~~~~~~~

* Binary builder task for the new python pipeline. (#4313)
  `PR #4313 <https://github.com/pantsbuild/pants/pull/4313>`_

* [engine] rm python graphmaker; create dot formatted display (#4295)
  `PR #4295 <https://github.com/pantsbuild/pants/pull/4295>`_

* A setup_py task for the new python pipeline. (#4308)
  `PR #4308 <https://github.com/pantsbuild/pants/pull/4308>`_

Bugfixes
~~~~~~~~

* scrooge_gen task copy strict_deps field (#4321)
  `PR #4321 <https://github.com/pantsbuild/pants/pull/4321>`_

* [jvm-compile] Copy compile classpath into runtime classpath even if already defined (#4310)
  `PR #4310 <https://github.com/pantsbuild/pants/pull/4310>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix reliance on symlinks in testdata. (#4320)
  `PR #4320 <https://github.com/pantsbuild/pants/pull/4320>`_

* Introduce SUPPRESS_LABEL on workunit's console output and have thrift-linter and jar-tool adopt it (#4318)
  `PR #4318 <https://github.com/pantsbuild/pants/pull/4318>`_

1.3.0.dev12 (3/3/2017)
----------------------
A weekly unstable release.

API Changes
~~~~~~~~~~~

* Completely revamp how we support JVM compiler plugins. (#4287)
  `PR #4287 <https://github.com/pantsbuild/pants/pull/4287>`_


New Features
~~~~~~~~~~~~

* A PytestRun task for the new Python pipeline. (#4252)
  `PR #4252 <https://github.com/pantsbuild/pants/pull/4252>`_

* Add ability to specify subprojects (#4088)
  `PR #4088 <https://github.com/pantsbuild/pants/pull/4088>`_

Bugfixes
~~~~~~~~

* Fix missed native_engine_version.
  `Commit cbdb97515 <https://github.com/pantsbuild/pants/commit/cbdb97515>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [engine] Rust IO (#4265)
  `PR #4265 <https://github.com/pantsbuild/pants/pull/4265>`_

* [engine] Support implicit sources in v2 engine (#4294)
  `PR #4294 <https://github.com/pantsbuild/pants/pull/4294>`_

* SelectLiteral isn't tied to the requester's subject: it has its own. (#4293)
  `PR #4293 <https://github.com/pantsbuild/pants/pull/4293>`_

* Include Javascript files in JVM binary (#4264)
  `PR #4264 <https://github.com/pantsbuild/pants/pull/4264>`_

* Update errorprone to version 2.0.17 (#4291)
  `PR #4291 <https://github.com/pantsbuild/pants/pull/4291>`_

* node_modules and node_test support yarnpkg as package manager (#4255)
  `PR #4255 <https://github.com/pantsbuild/pants/pull/4255>`_


1.3.0.dev11 (2/24/2017)
-----------------------
A weekly unstable release.

API Changes
~~~~~~~~~~~

* Support local jar with relative path in JarDependency (#4279)
  `PR #4279 <https://github.com/pantsbuild/pants/pull/4279>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Upgrade default jarjar to 1.6.4. (#4271)
  `Issue #26 <https://github.com/pantsbuild/jarjar/issues/26>`_
  `PR #4271 <https://github.com/pantsbuild/pants/pull/4271>`_

* Memoize validation of deprecated versions (#4273)
  `PR #4273 <https://github.com/pantsbuild/pants/pull/4273>`_

* [engine] Remove type_id field from Value (#4274)
  `PR #4274 <https://github.com/pantsbuild/pants/pull/4274>`_

* [New Python Pipeline] Add resources to PEXes correctly. (#4275)
  `PR #4275 <https://github.com/pantsbuild/pants/pull/4275>`_

* Upgrade default go to 1.8. (#4272)
  `PR #4272 <https://github.com/pantsbuild/pants/pull/4272>`_

* Fix missed native_engine_version commit.
  `Commit d966f9592 <https://github.com/pantsbuild/pants/commit/d966f9592fba2040429fc8a64f8aa4deb5e61f2c>`_

* Make options fingerprinting very difficult to disable (#4262)
  `PR #4262 <https://github.com/pantsbuild/pants/pull/4262>`_

* Bump pex requirement to 1.2.3 (#4277)
  `PR #4277 <https://github.com/pantsbuild/pants/pull/4277>`_

* Strip the root-level __init__.py that apache thrift generates. (#4281)
  `PR #4281 <https://github.com/pantsbuild/pants/pull/4281>`_

* Small tweak to the Dockerfile. (#4263)
  `PR #4263 <https://github.com/pantsbuild/pants/pull/4263>`_

* Make "./pants changed" output correct results when BUILD files are modified (#4282)
  `PR #4282 <https://github.com/pantsbuild/pants/pull/4282>`_

* [engine] minor clean up `engine.close` usage in `visualizer` (#4284)
  `PR #4284 <https://github.com/pantsbuild/pants/pull/4284>`_


1.3.0.dev10 (2/17/2017)
-----------------------

Bugfixes
~~~~~~~~

* Treat PythonTarget dependencies on Resources targets appropriately. (#4249)
  `PR #4249 <https://github.com/pantsbuild/pants/pull/4249>`_

* [engine] fix address node creation in v2 build graph; fix filedeps (#4235)
  `PR #4235 <https://github.com/pantsbuild/pants/pull/4235>`_

* Repair `Broken pipe` on pantsd thin client execution when piped to a non-draining reader. (#4230)
  `PR #4230 <https://github.com/pantsbuild/pants/pull/4230>`_

API Changes
~~~~~~~~~~~

* Deprecate Python target resources= and resource_targets=. (#4251)
  `PR #4251 <https://github.com/pantsbuild/pants/pull/4251>`_

* Deprecate use of resources= in JVM targets. (#4248)
  `PR #4248 <https://github.com/pantsbuild/pants/pull/4248>`_

New Features
~~~~~~~~~~~~

* New python repl task. (#4219)
  `PR #4219 <https://github.com/pantsbuild/pants/pull/4219>`_

* Add a node bundle goal (#4212)
  `PR #4212 <https://github.com/pantsbuild/pants/pull/4212>`_

* A task to generate Python code from ANTLR3 grammars.
  `PR #4206 <https://github.com/pantsbuild/pants/pull/4206>`_

Documentation
~~~~~~~~~~~~~

* Fixing grammatical error in why use pants doc page (#4239)
  `PR #4239 <https://github.com/pantsbuild/pants/pull/4239>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Work around native engine/tag chicken-egg. (#4270)
  `PR #4270 <https://github.com/pantsbuild/pants/pull/4270>`_

* [engine] Make Graph.get generic and make Externs static (#4261)
  `PR #4261 <https://github.com/pantsbuild/pants/pull/4261>`_

* A Dockerfile for building a pants development image. (#4260)
  `PR #4260 <https://github.com/pantsbuild/pants/pull/4260>`_

* [engine] Use Value in invoke_runnable as the function instead of Function (#4258)
  `PR #4258 <https://github.com/pantsbuild/pants/pull/4258>`_

* [engine] `Storage` clean ups  (#4257)
  `PR #4257 <https://github.com/pantsbuild/pants/pull/4257>`_

* [engine] remove Field type in favor of using String directly (#4256)
  `PR #4256 <https://github.com/pantsbuild/pants/pull/4256>`_

* Remove our use of resources= and resource_targets= in python targets. (#4250)
  `PR #4250 <https://github.com/pantsbuild/pants/pull/4250>`_

* Get rid of resources=[] stanzas in our JVMTargets. (#4247)
  `PR #4247 <https://github.com/pantsbuild/pants/pull/4247>`_

* Change engine visual graph layout from LR to TB (#4245)
  `PR #4245 <https://github.com/pantsbuild/pants/pull/4245>`_

* Simplify ci script test running stanzas. (#4209)
  `PR #4209 <https://github.com/pantsbuild/pants/pull/4209>`_

* [engine] Porting validation to Rust pt ii (#4243)
  `PR #4243 <https://github.com/pantsbuild/pants/pull/4243>`_

* Require dev-suffixed deprecation versions (#4216)
  `PR #4216 <https://github.com/pantsbuild/pants/pull/4216>`_

* [engine] Begin port of engine rule graph validation to Rust (#4227)
  `PR #4227 <https://github.com/pantsbuild/pants/pull/4227>`_

* Derive object id used in the native context from object's content (#4233)
  `PR #4233 <https://github.com/pantsbuild/pants/pull/4233>`_

* [engine] Use futures for scheduling (#4221)
  `PR #4221 <https://github.com/pantsbuild/pants/pull/4221>`_

* Add a 'current' symlink to the task-versioned prefix of the workdir. (#4220)
  `PR #4220 <https://github.com/pantsbuild/pants/pull/4220>`_

* Improve BUILD file matching in the v2 path. (#4226)
  `PR #4226 <https://github.com/pantsbuild/pants/pull/4226>`_

* Batch address injections in dependees task. (#4222)
  `PR #4222 <https://github.com/pantsbuild/pants/pull/4222>`_


1.3.0.dev9 (1/27/2017)
----------------------

Bugfixes
~~~~~~~~

* Removes the slf4j implementation from the classpath when running Cobertura (#4198)
  `PR #4198 <https://github.com/pantsbuild/pants/pull/4198>`_

* Make open_zip print realpath when raising BadZipfile. (#4186)
  `PR #4186 <https://github.com/pantsbuild/pants/pull/4186>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Shard testprojects integration tests (#4205)
  `PR #4205 <https://github.com/pantsbuild/pants/pull/4205>`_

* Resolve only stable releases by default. (#4201)
  `PR #4201 <https://github.com/pantsbuild/pants/pull/4201>`_


1.3.0.dev8 (1/20/2017)
----------------------

API Changes
~~~~~~~~~~~

* Bump pex version to 1.1.20 (#4191)
  `PR #4191 <https://github.com/pantsbuild/pants/pull/4191>`_

* Ban some characters in target name (#4180)
  `PR #4180 <https://github.com/pantsbuild/pants/pull/4180>`_

New Features
~~~~~~~~~~~~

* Scrooge codegen improvements (#4177)
  `PR #4177 <https://github.com/pantsbuild/pants/pull/4177>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Kill review tooling remnants. (#4192)
  `PR #4192 <https://github.com/pantsbuild/pants/pull/4192>`_

* Only release native-engine for pants releases. (#4189)
  `PR #4189 <https://github.com/pantsbuild/pants/pull/4189>`_

* Add some useful tips to the release documentation. (#4183)
  `PR #4183 <https://github.com/pantsbuild/pants/pull/4183>`_

Bugfixes
~~~~~~~~

* Add __init__.py for tests/python directories (#4193)
  `PR #4193 <https://github.com/pantsbuild/pants/pull/4193>`_

* Fix `str`-typed options with `int` defaults. (#4184)
  `PR #4184 <https://github.com/pantsbuild/pants/pull/4184>`_


1.3.0.dev7 (1/13/2017)
----------------------

API Changes
~~~~~~~~~~~

* Upgrade zinc and default scala-platform in pants repo to 2.11 (#4176)
  `PR #4176 <https://github.com/pantsbuild/pants/pull/4176>`_

New Features
~~~~~~~~~~~~

* Add contrib module for Error Prone http://errorprone.info/ (#4163)
  `PR #4163 <https://github.com/pantsbuild/pants/pull/4163>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* add various codegen packages to default backend packages (#4175)
  `PR #4175 <https://github.com/pantsbuild/pants/pull/4175>`_

* Suggest missing dependencies from target's transitive dependencies (#4171)
  `PR #4171 <https://github.com/pantsbuild/pants/pull/4171>`_

* Reduce compilation invalidation scope of targets with strict_deps=True (#4143)
  `PR #4143 <https://github.com/pantsbuild/pants/pull/4143>`_

* Fork to post_stat (#4170)
  `PR #4170 <https://github.com/pantsbuild/pants/pull/4170>`_

Bugfixes
~~~~~~~~

* fix a small bug in ApacheThriftGenBase class (#4181)
  `PR #4181 <https://github.com/pantsbuild/pants/pull/4181>`_


1.3.0.dev6 (1/06/2017)
----------------------

API Changes
~~~~~~~~~~~

* Refactor the thrift codegen task. (#4155)
  `PR #4155 <https://github.com/pantsbuild/pants/pull/4155>`_

* Finish splitting up the codegen backend. (#4147)
  `PR #4147 <https://github.com/pantsbuild/pants/pull/4147>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix import order issues introduced by a previous commit. (#4156)
  `PR #4156 <https://github.com/pantsbuild/pants/pull/4156>`_

* Bump default nodejs version to 6.9.1 from 6.2.0 (#4161)
  `PR #4161 <https://github.com/pantsbuild/pants/pull/4161>`_

* Make post_stat async (#4157)
  `PR #4157 <https://github.com/pantsbuild/pants/pull/4157>`_

* Fix release script owners check.
  `Commit <https://github.com/pantsbuild/pants/commit/a40234429cc05f6483f91b08f10037429710b5b4>`_


1.3.0.dev5 (12/30/2016)
-----------------------

API Changes
~~~~~~~~~~~

* Upgrade default go to 1.7.4. (#4149)
  `PR #4149 <https://github.com/pantsbuild/pants/pull/4149>`_

Bugfixes
~~~~~~~~

* Fix instructions for ivy debug logging (#4141)
  `PR #4141 <https://github.com/pantsbuild/pants/pull/4141>`_

* Handle unicode in classpath entries (#4136)
  `PR #4136 <https://github.com/pantsbuild/pants/pull/4136>`_

* Ensure that invalid vts have results_dir cleaned before passing to ta… (#4139)
  `PR #4139 <https://github.com/pantsbuild/pants/pull/4139>`_

Documentation
~~~~~~~~~~~~~

* [docs] Update the cache section on the Task developer page. (#4152)
  `PR #4152 <https://github.com/pantsbuild/pants/pull/4152>`_

* Prepare notes for 1.2.1.rc0 (#4146)
  `PR #4146 <https://github.com/pantsbuild/pants/pull/4146>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Start breaking up the codegen backend. (#4147)
  `PR #4147 <https://github.com/pantsbuild/pants/pull/4147>`_

* Cleanup unused cffi handles to free memory (#4135)
  `PR #4135 <https://github.com/pantsbuild/pants/pull/4135>`_

* A new Python run task. (#4142)
  `PR #4142 <https://github.com/pantsbuild/pants/pull/4142>`_

1.3.0.dev4 (12/08/2016)
-----------------------

Bugfixes
~~~~~~~~

* Redirect bootstrapping calls in pants binary to stderr (#4131)
  `PR #4131 <https://github.com/pantsbuild/pants/pull/4131>`_

* Ensure that the protoc root import path is examined first (#4129)
  `PR #4129 <https://github.com/pantsbuild/pants/pull/4129>`_

* Allow the buildroot to be a source root (#4093)
  `PR #4093 <https://github.com/pantsbuild/pants/issues/4093>`_

* A flag to add the buildroot to protoc's import path (#4122)
  `PR #4122 <https://github.com/pantsbuild/pants/pull/4122>`_

* Drop libc dependency from native engine (#4124)
  `PR #4124 <https://github.com/pantsbuild/pants/pull/4124>`_

* Execute traces for all non-Return values (#4118)
  `PR #4118 <https://github.com/pantsbuild/pants/pull/4118>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* directly invoke runnable from native code (#4128)
  `PR #4128 <https://github.com/pantsbuild/pants/pull/4128>`_

* Bump pex version.

* [engine] model snapshots in validation, make root rules a dict instead of a set (#4125)
  `PR #4125 <https://github.com/pantsbuild/pants/pull/4125>`_

* classmap: a jvm console task that outputs mapping from class products to their targets (#4081)
  `PR #4081 <https://github.com/pantsbuild/pants/pull/4081>`_

* Update bintray deploys to use a shared account. (#4126)
  `PR #4126 <https://github.com/pantsbuild/pants/pull/4126>`_

* Plumb a configurable worker count to thrift linter. (#4121)
  `PR #4121 <https://github.com/pantsbuild/pants/pull/4121>`_

Documentation
~~~~~~~~~~~~~

* [docs] Add section for building multiplatform python binaries with native dependencies (#4119)
  `PR #4119 <https://github.com/pantsbuild/pants/pull/4119>`_


1.3.0.dev3 (12/02/2016)
-----------------------

A weekly unstable release.

API Changes
~~~~~~~~~~~

* Bump pex and setuptools to latest. (#4111)
  `PR #4111 <https://github.com/pantsbuild/pants/pull/4111>`_

* Bump setuptools version. (#4103)
  `PR #4103 <https://github.com/pantsbuild/pants/pull/4103>`_

Bugfixes
~~~~~~~~

* Update junit-runner to 1.0.17 (#4113)
  `PR #4113 <https://github.com/pantsbuild/pants/pull/4113>`_
  `PR #4106 <https://github.com/pantsbuild/pants/pull/4106>`_

* Don't exit the JUnitRunner with number of failures because Java will mod the exit code. (#4106)
  `PR #4106 <https://github.com/pantsbuild/pants/pull/4106>`_

* Allow for using the native engine from-source in another repo (#4105)
  `PR #4105 <https://github.com/pantsbuild/pants/pull/4105>`_

* Un-publish the `jar` goal. (#4095)
  `PR #4095 <https://github.com/pantsbuild/pants/pull/4095>`_

* Restore compile-zinc-name-hashing option to follow deprecation cycle (#4091)
  `PR #4091 <https://github.com/pantsbuild/pants/pull/4091>`_

* Fix a Python requirement resolution test bug. (#4087)
  `PR #4087 <https://github.com/pantsbuild/pants/pull/4087>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [engine] Remove variant selecting from native engine (#4108)
  `PR #4108 <https://github.com/pantsbuild/pants/pull/4108>`_

* Reduce hashing during v2 transitive graph walks (#4109)
  `PR #4109 <https://github.com/pantsbuild/pants/pull/4109>`_

* Add a native engine release check. (#4096)
  `PR #4096 <https://github.com/pantsbuild/pants/pull/4096>`_

* Remove coveralls from CI. (#4099)
  `PR #4099 <https://github.com/pantsbuild/pants/pull/4099>`_

* Run the proto compiler in workunit. (#4092)
  `PR #4092 <https://github.com/pantsbuild/pants/pull/4092>`_

* Restore propagation of thrown exceptions between rust and python (#4083)
  `PR #4083 <https://github.com/pantsbuild/pants/pull/4083>`_

* Make `cargo build --release` the default for native engine bootstrapping. (#4090)
  `PR #4090 <https://github.com/pantsbuild/pants/pull/4090>`_

Documentation
~~~~~~~~~~~~~

* Remove stale example from 3rdparty_jvm.md (#4112)
  `PR #4112 <https://github.com/pantsbuild/pants/pull/4112>`_

* Add "common tasks" docs (#4060)
  `PR #4060 <https://github.com/pantsbuild/pants/pull/4060>`_

* Fix typo in docs (#4097)
  `PR #4097 <https://github.com/pantsbuild/pants/pull/4097>`_

1.3.0dev2 (11/20/2016)
----------------------

A return to the regular schedule of weekly unstable releases.

API Changes
~~~~~~~~~~~
* Move SimpleCodegenTask into the pants core.
  `PR #4079 <https://github.com/pantsbuild/pants/pull/4079>`_

* Move the pytest-related runtime requirement specs  into a subsystem.
  `PR #4071 <https://github.com/pantsbuild/pants/pull/4071>`_

* Add the scala 2.12 platform
  `RB #4388 <https://rbcommons.com/s/twitter/r/4388>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Fixup OSX bintray prep. (#4086)
  `PR #4086 <https://github.com/pantsbuild/pants/pull/4086>`_

* Task to gather local python sources into a pex.
  `PR #4084 <https://github.com/pantsbuild/pants/pull/4084>`_

* [engine] Initial Trace implementation for rust engine (#4076)
  `Issue #4025 <https://github.com/pantsbuild/pants/issues/4025>`_
  `PR #4076 <https://github.com/pantsbuild/pants/pull/4076>`_

* Propose a github review workflow
  `RB #4333 <https://rbcommons.com/s/twitter/r/4333>`_

* Spelling mistake in first_tutorial (#4045)
  `PR #4045 <https://github.com/pantsbuild/pants/pull/4045>`_

* Replace instances of pantsbuild.github.io in the docs with pantsbuild.org.
  `PR #4074 <https://github.com/pantsbuild/pants/pull/4074>`_

* A task to resolve python requirements.
  `PR #4065 <https://github.com/pantsbuild/pants/pull/4065>`_

* Upgrade zinc's sbt dependency to 1.0.0: python portion
  `RB #4064 <https://rbcommons.com/s/twitter/r/4064>`_
  `RB #4340 <https://rbcommons.com/s/twitter/r/4340>`_
  `RB #4342 <https://rbcommons.com/s/twitter/r/4342>`_

* Skip failing tests to get CI green.
  `RB #4391 <https://rbcommons.com/s/twitter/r/4391>`_

* Avoid using expensive bootstrap artifacts from temporary cache location
  `RB #4342 <https://rbcommons.com/s/twitter/r/4342>`_
  `RB #4368 <https://rbcommons.com/s/twitter/r/4368>`_

1.3.0dev1 (11/16/2016)
----------------------

There has been a month gap between master releases and a corresponding large number of
changes. Most notably:

* Pants now ships with a new native engine core that is the future of pants scalability work.

* Pants has adopted a `code of conduct
  <https://github.com/pantsbuild/pants/blob/master/CODE_OF_CONDUCT.md>`_

API Changes
~~~~~~~~~~~

* Make findbugs task not transitive by default and modify findbugs progress output
  `RB #4376 <https://rbcommons.com/s/twitter/r/4376>`_

* Adding a Code of Conduct
  `RB #4354 <https://rbcommons.com/s/twitter/r/4354>`_

* Surface --dereference-symlinks flag to task caching level
  `RB #4338 <https://rbcommons.com/s/twitter/r/4338>`_

* support mutually_exclusive_group paramater in option registration
  `RB #4336 <https://rbcommons.com/s/twitter/r/4336>`_

* Deprecate the `java_tests` alias in favor of `junit_tests`.
  `RB #4322 <https://rbcommons.com/s/twitter/r/4322>`_

* Add a target-types option to scalafmt to avoid formatting all targets
  `RB #4328 <https://rbcommons.com/s/twitter/r/4328>`_

* Adding scalafmt formatting to fmt goal
  `RB #4312 <https://rbcommons.com/s/twitter/r/4312>`_

Bugfixes
~~~~~~~~

* Capture testcase for unknown test failures in the JUnit Xml
  `RB #4377 <https://rbcommons.com/s/twitter/r/4377>`_

* Correction on [resolve.node]
  `RB #4362 <https://rbcommons.com/s/twitter/r/4362>`_
  `RB #4364 <https://rbcommons.com/s/twitter/r/4364>`_

* Remove safe_mkdir on results_dir in [resolve.node]
  `RB #4362 <https://rbcommons.com/s/twitter/r/4362>`_

* Improve python_binary target fingerprinting.
  `RB #4353 <https://rbcommons.com/s/twitter/r/4353>`_

* Bugfix: when synthesizing remote libraries in Go, pin them to the same rev as adjacent libs.
  `RB #4325 <https://rbcommons.com/s/twitter/r/4325>`_

* Fix the SetupPy target ownership check.
  `RB #4315 <https://rbcommons.com/s/twitter/r/4315>`_

* Update junit runner to 1.0.15 to get java 7 compatibility
  `RB #4324 <https://rbcommons.com/s/twitter/r/4324>`_

* Fix erroneous deprecated scope warnings.
  `RB #4323 <https://rbcommons.com/s/twitter/r/4323>`_

* Back down the minimum required java version for running Pants tools to java 7
  `RB #4127 <https://rbcommons.com/s/twitter/r/4127>`_
  `RB #4253 <https://rbcommons.com/s/twitter/r/4253>`_
  `RB #4314 <https://rbcommons.com/s/twitter/r/4314>`_

* Fix exlucde_target_regexp breakage in test-changed and --files option breakage in changed with diffspec
  `RB #4321 <https://rbcommons.com/s/twitter/r/4321>`_

* Prevent cleanup error at end of pants test with --test-junit-html-report option, update safe_rmtree to be symlink aware
  `RB #4319 <https://rbcommons.com/s/twitter/r/4319>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Format / Sort COMMITTERS.md; Add Yujie Chen to Active list
  `RB #4382 <https://rbcommons.com/s/twitter/r/4382>`_

* Bump junit-runner to 1.0.16
  `RB #4381 <https://rbcommons.com/s/twitter/r/4381>`_

* Patch to make scala tests work
  `RB #4361 <https://rbcommons.com/s/twitter/r/4361>`_

* Kill un-used `pants.jenkins.ini`.
  `RB #4369 <https://rbcommons.com/s/twitter/r/4369>`_

* Kill unused Jenkins experiment.
  `RB #4366 <https://rbcommons.com/s/twitter/r/4366>`_

* Split test_zinc_compile_integration into two smaller tests
  `RB #4365 <https://rbcommons.com/s/twitter/r/4365>`_

* Upgrade zinc's sbt dependency to 1.0.0: JVM portion
  `Issue #144 <https://github.com/sbt/zinc/issues/144>`_
  `Issue #151 <https://github.com/sbt/zinc/issues/151>`_
  `Issue #185 <https://github.com/sbt/zinc/issues/185>`_
  `RB #3658 <https://rbcommons.com/s/twitter/r/3658>`_
  `RB #4342 <https://rbcommons.com/s/twitter/r/4342>`_
  `RB #4340 <https://rbcommons.com/s/twitter/r/4340>`_

* Perf improvement: rebase analyis file once instead of multiple times
  `Issue #8 <https://github.com/pantsbuild/zincutils/issues/8>`_
  `RB #4352 <https://rbcommons.com/s/twitter/r/4352>`_

* Leverage default sources where possible.
  `RB #4358 <https://rbcommons.com/s/twitter/r/4358>`_

* [python-ng] A task to select a python interpreter.
  `RB #4346 <https://rbcommons.com/s/twitter/r/4346>`_

* Parallize thrift linter
  `RB #4351 <https://rbcommons.com/s/twitter/r/4351>`_

* normalize filespec exclude usage
  `RB #4348 <https://rbcommons.com/s/twitter/r/4348>`_

* clean up deprecated global_subsystems and task_subsystems
  `RB #4349 <https://rbcommons.com/s/twitter/r/4349>`_

* [jvm-compile] Ensure all invalid dependencies of targets are correctly represented in compile graph
  `RB #4136 <https://rbcommons.com/s/twitter/r/4136>`_
  `RB #4343 <https://rbcommons.com/s/twitter/r/4343>`_

* Change default ./pants fmt.isort <empty> behavior to no-op; Add sources check for isort.
  `RB #4327 <https://rbcommons.com/s/twitter/r/4327>`_

* Allow targets to have sensible defaults for sources=.
  `RB #4300 <https://rbcommons.com/s/twitter/r/4300>`_

* Remove the long-deprecated Target.is_codegen().
  `RB #4318 <https://rbcommons.com/s/twitter/r/4318>`_

* Add one more shard to travis ci
  `RB #4320 <https://rbcommons.com/s/twitter/r/4320>`_

New Engine Work
~~~~~~~~~~~~~~~

* Revert "Revert "Generate 32 bit native engine binaries.""
  `RB #4380 <https://rbcommons.com/s/twitter/r/4380>`_
  `Issue #4035 <https://github.com/pantsbuild/pants/issues/4035>`_

* Add contrib, 3rdparty to copy list for mock buildroot as v2 engine to pass prefix checks.
  `RB #4379 <https://rbcommons.com/s/twitter/r/4379>`_

* Generate 32 bit native engine binaries.
  `RB #4373 <https://rbcommons.com/s/twitter/r/4373>`_

* Add support for publishing for OSX 10.7+.
  `RB #4371 <https://rbcommons.com/s/twitter/r/4371>`_

* Wire up native binary deploy to bintray.
  `RB #4370 <https://rbcommons.com/s/twitter/r/4370>`_

* Re-work native engine version.
  `RB #4367 <https://rbcommons.com/s/twitter/r/4367>`_

* First round of native engine feedback
  `Issue #4020 <https://github.com/pantsbuild/pants/issues/4020>`_
  `RB #4270 <https://rbcommons.com/s/twitter/r/4270>`_
  `RB #4359 <https://rbcommons.com/s/twitter/r/4359>`_

* [engine] Native scheduler implementation
  `RB #4270 <https://rbcommons.com/s/twitter/r/4270>`_

* Bootstrap the native engine from live sources.
  `RB #4345 <https://rbcommons.com/s/twitter/r/4345>`_

1.3.0dev0 (10/14/2016)
----------------------

The first unstable release of the 1.3.x series.

API Changes
~~~~~~~~~~~

* Add subsystem_utils to test_infra
  `RB #4303 <https://rbcommons.com/s/twitter/r/4303>`_

Bugfixes
~~~~~~~~

* Switch default deference back to True for tarball artifact
  `RB #4304 <https://rbcommons.com/s/twitter/r/4304>`_

* Filter inactive goals from `Goal.all`.
  `RB #4298 <https://rbcommons.com/s/twitter/r/4298>`_

* JUnit runner fix for len(args) > max_args in argfile.safe_args
  `RB #4294 <https://rbcommons.com/s/twitter/r/4294>`_

* Fix --changed-files option
  `RB #4309 <https://rbcommons.com/s/twitter/r/4309>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Migrate changed integration tests to isolated temp git repos and add an environment variable to override buildroot
  `RB #4295 <https://rbcommons.com/s/twitter/r/4295>`_

* Get rid of the "Skipped X files" messages from isort output.
  `RB #4301 <https://rbcommons.com/s/twitter/r/4301>`_

* Version clarification
  `RB #4299 <https://rbcommons.com/s/twitter/r/4299>`_

* Fix isort to run `./pants fmt.isort` once.
  `RB #4297 <https://rbcommons.com/s/twitter/r/4297>`_

* Dogfood `./pants fmt.isort`.
  `RB #4289 <https://rbcommons.com/s/twitter/r/4289>`_

* Extract the junit xml report parser.
  `RB #4292 <https://rbcommons.com/s/twitter/r/4292>`_

* Leverage default targets throughout pants BUILDs.
  `RB #4287 <https://rbcommons.com/s/twitter/r/4287>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Improve daemon run profiling.
  `RB #4293 <https://rbcommons.com/s/twitter/r/4293>`_

1.2.0rc0 (10/07/2016)
---------------------

First release candidate for stable 1.2.0.

New Features
~~~~~~~~~~~~

* Make the name= target keyword optional in BUILD files.
  `RB #4275 <https://rbcommons.com/s/twitter/r/4275>`_

* Add Scalafmt Support to Pants
  `RB #4216 <https://rbcommons.com/s/twitter/r/4216>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add libffi to pants pre-reqs, qualify JDK req.
  `RB #4285 <https://rbcommons.com/s/twitter/r/4285>`_

* Update the setup.py description.
  `RB #4283 <https://rbcommons.com/s/twitter/r/4283>`_

* Refactor Intermediate Target Generation Logic
  `RB #4277 <https://rbcommons.com/s/twitter/r/4277>`_

* Clean up after failed artifact extractions
  `RB #4255 <https://rbcommons.com/s/twitter/r/4255>`_

* Publish the CPP plugin
  `RB #4282 <https://rbcommons.com/s/twitter/r/4282>`_

* Change --no-dryrun to the new flag in docs
  `RB #4280 <https://rbcommons.com/s/twitter/r/4280>`_

* Add --no-transitive flag to findbugs so you can run findbugs only for the targets specified on the command line
  `RB #4276 <https://rbcommons.com/s/twitter/r/4276>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Rule Graph construction perf improvements
  `RB #4281 <https://rbcommons.com/s/twitter/r/4281>`_

* [engine] Introduce static analysis model and replace validator with it
  `RB #4251 <https://rbcommons.com/s/twitter/r/4251>`_


1.2.0dev12 (9/30/2016)
----------------------

Regularly scheduled unstable release, highlighted by engine work and OSX 10.12 support.
Thanks to the contributors!

Bugfixes
~~~~~~~~
* Remove deprecated `from_target` usage in examples.
  `RB #4262 <https://rbcommons.com/s/twitter/r/4262>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* show deprecation warning for options given in env and config
  `RB #4272 <https://rbcommons.com/s/twitter/r/4272>`_

* Update binary_util OS map for OSX Sierra.
  `RB #4266 <https://rbcommons.com/s/twitter/r/4266>`_

* Make LegacyAddressMapper v2 engine backed
  `RB #4239 <https://rbcommons.com/s/twitter/r/4239>`_

* Upgrade to junit-runner 1.0.14.
  `RB #4264 <https://rbcommons.com/s/twitter/r/4264>`_

* Fix handling of method specs.
  `RB #4258 <https://rbcommons.com/s/twitter/r/4258>`_

* Factor workunit failure into final exit code.
  `RB #4244 <https://rbcommons.com/s/twitter/r/4244>`_

New Engine Work
~~~~~~~~~~~~~~~
* [engine] Iterative improvements for`changed` and friends.
  `RB #4269 <https://rbcommons.com/s/twitter/r/4269>`_

* [engine] Allow injecting of intrinsic providers to ease testing
  `RB #4263 <https://rbcommons.com/s/twitter/r/4263>`_

* [engine] When requesting select nodes or regular nodes, return state values rather than requiring a separate call
  `RB #4261 <https://rbcommons.com/s/twitter/r/4261>`_

* [engine] Introduce TypeConstraint#satisfied_by_type
  `RB #4260 <https://rbcommons.com/s/twitter/r/4260>`_


1.2.0dev11 (9/23/2016)
----------------------

Regularly scheduled unstable release.

Heads up!: this release contains a change to an important default value for those who
use pants to build scala codebases. The default ``--scala-platform-version`` has changed
from ``2.10`` to ``2.11``. If you do not set this value in your pants.ini (highly recommended!)
this may result in a surprise scala upgrade for you.

Thanks to the contributors!

API Changes
~~~~~~~~~~~

* Bump default scala platform version to 2.11
  `RB #4256 <https://rbcommons.com/s/twitter/r/4256>`_

Bugfixes
~~~~~~~~

* Clean up analysis.tmp usage between pants and zinc wrapper (Part 1)
  `Issue #3667 <https://github.com/pantsbuild/pants/issues/3667>`_
  `RB #4245 <https://rbcommons.com/s/twitter/r/4245>`_

* Clean up analysis.tmp usage between pants and zinc wrapper (Part 2)
  `RB #4246 <https://rbcommons.com/s/twitter/r/4246>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Update minimum JDK requirements.
  `RB #4127 <https://rbcommons.com/s/twitter/r/4127>`_
  `RB #4253 <https://rbcommons.com/s/twitter/r/4253>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Move subselectors to selector properties
  `RB #4235 <https://rbcommons.com/s/twitter/r/4235>`_

* [engine] Daemon cacheable `changed`.
  `RB #4207 <https://rbcommons.com/s/twitter/r/4207>`_

1.2.0dev10 (9/20/2016)
----------------------
Regularly scheduled unstable release. Thanks to the contributors!
Version bump, previous release only did a partial upload.

Bugfixes
~~~~~~~~
* Correct Pants's incorrect guesses for go source roots.
  `RB #4247 <https://rbcommons.com/s/twitter/r/4247>`_

* Fix ng-killall by swallowing psutil exceptions in filter
  `RB #4237 <https://rbcommons.com/s/twitter/r/4237>`_

* Fix for idea-plugin goal that generates too long project filename
  `RB #4231 <https://rbcommons.com/s/twitter/r/4231>`_

* wrapped globs excludes - include incorrect arg in error message
  `RB #4232 <https://rbcommons.com/s/twitter/r/4232>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Inject an automatic dep on junit for all junit_tests targets.
  `RB #4228 <https://rbcommons.com/s/twitter/r/4228>`_

* Simplify failed test reporting.
  `RB #4240 <https://rbcommons.com/s/twitter/r/4240>`_

* Fixup the simple plugin setup docs.
  `RB #4241 <https://rbcommons.com/s/twitter/r/4241>`_

* Add description to type constraints
  `RB #4233 <https://rbcommons.com/s/twitter/r/4233>`_

* Differentiate between source root categories.
  `RB #4230 <https://rbcommons.com/s/twitter/r/4230>`_

* Restore ChangedTargetGoalsIntegrationTest.
  `RB #4227 <https://rbcommons.com/s/twitter/r/4227>`_

* Deprecate the `subsystem_instance` utility function.
  `RB #4220 <https://rbcommons.com/s/twitter/r/4220>`_

New Features
~~~~~~~~~~~~
* Add a timeout to scalajs tests
  `RB #4229 <https://rbcommons.com/s/twitter/r/4229>`_

* Disallow absolute file paths in specs in BUILD files
  `RB #4221 <https://rbcommons.com/s/twitter/r/4221>`_

New Engine Work
~~~~~~~~~~~~~~~
* [engine] Convert all isinstance product checks to using Exactly type constraints
  `RB #4236 <https://rbcommons.com/s/twitter/r/4236>`_

* [engine] Check that types passed to TypeConstraint inits are in fact types
  `RB #4209 <https://rbcommons.com/s/twitter/r/4209>`_

1.2.0dev9 (9/12/2016)
----------------------
Regularly scheduled unstable release. Thanks to the contributors!
Version bump, previous release only did a partial upload.

Bugfixes
~~~~~~~~
* Re-enable test_junit_tests_using_cucumber.
  `RB #4212 <https://rbcommons.com/s/twitter/r/4212>`_

* Reset subsystem state for integration tests.
  `RB #4219 <https://rbcommons.com/s/twitter/r/4219>`_

* Remove spurious pants.pex file that somehow ended up in the repo.
  `RB #4214 <https://rbcommons.com/s/twitter/r/4214>`_
  `RB #4218 <https://rbcommons.com/s/twitter/r/4218>`_

* Fix a non-determinism I added in the ANTLR support
  `RB #4187 <https://rbcommons.com/s/twitter/r/4187>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Edit Greeting{,Test}.java to get a known edit sha for tests.
  `RB #4217 <https://rbcommons.com/s/twitter/r/4217>`_

* Refactor memoization of the global distribution locator.
  `RB #4214 <https://rbcommons.com/s/twitter/r/4214>`_

* Clean up junit xml report file location logic.
  `RB #4211 <https://rbcommons.com/s/twitter/r/4211>`_

* Upgrade default go to 1.7.1.
  `RB #4210 <https://rbcommons.com/s/twitter/r/4210>`_

* Make util.objects.datatype classes not iterable
  `RB #4163 <https://rbcommons.com/s/twitter/r/4163>`_

1.2.0dev8 (09/02/2016)
----------------------

Regularly scheduled unstable release. Thanks to the contributors!
Version bump, previous release only did a partial upload.

1.2.0dev7 (09/02/2016)
----------------------

Regularly scheduled unstable release. Thanks to the contributors!

Bugfixes
~~~~~~~~
* [jvm-compile][bug] Fixes other target's class dir ending up on classpath
  `RB #4198 <https://rbcommons.com/s/twitter/r/4198>`_

* Fixed bugs in Go thrift generation with services
  `RB #4177 <https://rbcommons.com/s/twitter/r/4177>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Add Runnable State
  `RB #4158 <https://rbcommons.com/s/twitter/r/4158>`_

* [engine] Don't filter directories in watchman subscription
  `RB #4095 <https://rbcommons.com/s/twitter/r/4095>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Eliminate all direct use of pytest.
  `RB #4201 <https://rbcommons.com/s/twitter/r/4201>`_

* Update pants versioning to use python's packaging.version
  `RB #4200 <https://rbcommons.com/s/twitter/r/4200>`_

* [jvm-compile][test] Add test explicitly checking classpath for z.jars
  `RB #4199 <https://rbcommons.com/s/twitter/r/4199>`_

* Plumb fetch timeout through `BinaryUtil`.
  `RB #4196 <https://rbcommons.com/s/twitter/r/4196>`_

* Upgrade default go to 1.7.
  `RB #4195 <https://rbcommons.com/s/twitter/r/4195>`_

* Fixup `PythonTarget` `resource_targets` docs.
  `RB #4148 <https://rbcommons.com/s/twitter/r/4148>`_

* Customize tarfile module next() method
  `RB #4123 <https://rbcommons.com/s/twitter/r/4123>`_

1.2.0-dev6 (8/26/2016)
----------------------

Regularly scheduled unstable release. Thanks to the contributors!

New Features
~~~~~~~~~~~~

* A clear error message for checkstyle misconfiguration.
  `RB #4176 <https://rbcommons.com/s/twitter/r/4176>`_

Bugfixes
~~~~~~~~

* Performance fix for consolidated classpath
  `RB #4184 <https://rbcommons.com/s/twitter/r/4184>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Refactor classpath consolidation into a separate task.
  `RB #4152 <https://rbcommons.com/s/twitter/r/4152>`_

* Refactor idea-plugin goal
  `RB #4159 <https://rbcommons.com/s/twitter/r/4159>`_

* Remove all calls to create_subsystem() in tests.
  `RB #4178 <https://rbcommons.com/s/twitter/r/4178>`_

New Engine Work
~~~~~~~~~~~~~~~

* Support exclude_target_regexps and ignore_patterns in v2 engine
  `RB #4172 <https://rbcommons.com/s/twitter/r/4172>`_

1.2.0-dev5 (8/19/2016)
----------------------

Regularly scheduled unstable release.

New Engine Work
~~~~~~~~~~~~~~~

* Defer daemon-wise `LegacyBuildGraph` construction to post-fork.
  `RB #4168 <https://rbcommons.com/s/twitter/r/4168>`_

* [engine] Validate that variant_key of SelectVariant is string type git_shat msg: 5a7e838d512069a24d12ec0b7dcdc7b7d5bdfa3b
  `RB #4149 <https://rbcommons.com/s/twitter/r/4149>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Adjust the output file locations for the Antlr task.
  `RB #4161 <https://rbcommons.com/s/twitter/r/4161>`_

* build dictionary: one description per arg is plenty
  `RB #4164 <https://rbcommons.com/s/twitter/r/4164>`_

1.2.0-dev4 (8/12/2016)
----------------------

Regularly scheduled unstable release.

New Features
~~~~~~~~~~~~

* Introduce fmt goal, isort subgoal
  `RB #4134 <https://rbcommons.com/s/twitter/r/4134>`_

Bugfixes
~~~~~~~~

* Fix GitTest control of git `user.email`.
  `RB #4146 <https://rbcommons.com/s/twitter/r/4146>`_

* Restore publishing of the docsite during releases
  `RB #4140 <https://rbcommons.com/s/twitter/r/4140>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Fix bundle rel_path handling in engine
  `RB #4150 <https://rbcommons.com/s/twitter/r/4150>`_

* [engine] Fix running changed with v2 flag; Replace context address_mapper; Fix excludes filespecs in engine globs.
  `RB #4114 <https://rbcommons.com/s/twitter/r/4114>`_

* Fix BundleAdaptor to BundleProps Conversion
  `RB #4057 <https://rbcommons.com/s/twitter/r/4057>`_
  `RB #4129 <https://rbcommons.com/s/twitter/r/4129>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Eliminate use of mox in favor of mock.
  `RB #4143 <https://rbcommons.com/s/twitter/r/4143>`_

* Convert FetcherTest to use mock instead of mox.
  `RB #4142 <https://rbcommons.com/s/twitter/r/4142>`_

* [jvm-compile] narrow compile dependencies from full closure to just next nearest invalid compilation targets
  `RB #4136 <https://rbcommons.com/s/twitter/r/4136>`_


1.2.0-dev3 (8/7/2016)
---------------------

Unscheduled extra unstable release.

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Move the custom javac option to the Java subsystem.
  `RB #4141 <https://rbcommons.com/s/twitter/r/4141>`_


1.2.0-dev2 (8/5/2016)
---------------------

Regularly scheduled unstable release.

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Upgrade travis ci to use jdk 8
  `RB #4127 <https://rbcommons.com/s/twitter/r/4127>`_

* Additional checks for module type determination.
  `RB #4131 <https://rbcommons.com/s/twitter/r/4131>`_


1.2.0-dev1 (7/30/2016)
----------------------

Regularly scheduled unstable release.

New Features
~~~~~~~~~~~~

* Allow specification of an alternate javac location.
  `RB #4124 <https://rbcommons.com/s/twitter/r/4124>`_

* Add support to Fetcher for `file:` URLs.
  `RB #4099 <https://rbcommons.com/s/twitter/r/4099>`_

* JSON output format for Pants options
  `RB #4113 <https://rbcommons.com/s/twitter/r/4113>`_


API Changes
~~~~~~~~~~~


Bugfixes
~~~~~~~~

* Avoid clobbering `type_alias` kwarg in the `Registrar` if already explicitly set.
  `RB #4106 <https://rbcommons.com/s/twitter/r/4106>`_

* Fix JUnit -fail-fast, add test for early exit hook and remove unused code
  `RB #4060 <https://rbcommons.com/s/twitter/r/4060>`_
  `RB #4081 <https://rbcommons.com/s/twitter/r/4081>`_

* Fixup the 1.1.x notes, which were not being rendered on the site, and contained rendering errors.
  `RB #4098 <https://rbcommons.com/s/twitter/r/4098>`_


New Engine Work
~~~~~~~~~~~~~~~

* Ensure target `resources=` ordering is respected in the v2 engine.
  `RB #4128 <https://rbcommons.com/s/twitter/r/4128>`_

* [engine] Pass selectors to select nodes; Use selectors in error messages
  `RB #4031 <https://rbcommons.com/s/twitter/r/4031>`_

* Remove Duplicates in File System tasks in v2 Engine
  `RB #4096 <https://rbcommons.com/s/twitter/r/4096>`_



Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* A custom version of com.sun.tools.javac.api.JavacTool.
  `RB #4122 <https://rbcommons.com/s/twitter/r/4122>`_

* Time out Jenkins shards after 60 minutes.
  `RB #4082 <https://rbcommons.com/s/twitter/r/4082>`_

* Eliminate file listing ordering assumptions.
  `RB #4121 <https://rbcommons.com/s/twitter/r/4121>`_

* Upgrade the pants bootstrap venv to 15.0.2.
  `RB #4120 <https://rbcommons.com/s/twitter/r/4120>`_

* Bump default wheel version to latest.
  `RB #4116 <https://rbcommons.com/s/twitter/r/4116>`_

* Remove warnings from the release process.
  `RB #4119 <https://rbcommons.com/s/twitter/r/4119>`_

* Upgrade default go to 1.6.3.
  `RB #4115 <https://rbcommons.com/s/twitter/r/4115>`_

* Added a page on policies for pants committers
  `RB #4105 <https://rbcommons.com/s/twitter/r/4105>`_

* Cleanup `BinaryUtil`.
  `RB #4108 <https://rbcommons.com/s/twitter/r/4108>`_

* Update junit-runner to version 1.0.13
  `RB #4102 <https://rbcommons.com/s/twitter/r/4102>`_
  `RB #4101 <https://rbcommons.com/s/twitter/r/4101>`_
  `RB #4091 <https://rbcommons.com/s/twitter/r/4091>`_
  `RB #4081 <https://rbcommons.com/s/twitter/r/4081>`_
  `RB #4107 <https://rbcommons.com/s/twitter/r/4107>`_

* Enable autoFlush for JUnit printstream so we get output as the tests run
  `RB #4101 <https://rbcommons.com/s/twitter/r/4101>`_
  `RB #4102 <https://rbcommons.com/s/twitter/r/4102>`_

* Print a message for cycles in the graph when computing the target fingerprint
  `RB #4087 <https://rbcommons.com/s/twitter/r/4087>`_

* Pin remaining core-sensitive options.
  `RB #4100 <https://rbcommons.com/s/twitter/r/4100>`_
  `RB #4104 <https://rbcommons.com/s/twitter/r/4104>`_

* Set the encoding for javac in pantsbuild/pants
  `Issue #3702 <https://github.com/pantsbuild/pants/issues/3702>`_
  `RB #4103 <https://rbcommons.com/s/twitter/r/4103>`_

* Customize pants settings for Jenkins.
  `RB #4101 <https://rbcommons.com/s/twitter/r/4101>`_
  `RB #4100 <https://rbcommons.com/s/twitter/r/4100>`_

* Buffer the ConsoleRunner's use of stdio.
  `RB #4101 <https://rbcommons.com/s/twitter/r/4101>`_

* Extract `safe_args` to a jvm backend module.
  `RB #4090 <https://rbcommons.com/s/twitter/r/4090>`_

* Move `ui_open` into its own `util` module.
  `RB #4089 <https://rbcommons.com/s/twitter/r/4089>`_

* Simplify `ConcurrentRunnerScheduler` & cleanup.
  `RB #4091 <https://rbcommons.com/s/twitter/r/4091>`_


1.2.0-dev0 (7/18/2016)
----------------------

Regularly scheduled unstable release! Unstable releases from master will use the
``dev`` suffix from now on (see `#3382 <https://github.com/pantsbuild/pants/issues/3382>`_).

New Features
~~~~~~~~~~~~

None this week!

API Changes
~~~~~~~~~~~

* Bump Junit Runner to 1.0.12
  `RB #4072 <https://rbcommons.com/s/twitter/r/4072>`_
  `RB #4026 <https://rbcommons.com/s/twitter/r/4026>`_
  `RB #4047 <https://rbcommons.com/s/twitter/r/4047>`_

* Support for Tasks to request optional product requirements.
  `RB #4071 <https://rbcommons.com/s/twitter/r/4071>`_

Bugfixes
~~~~~~~~

* RGlobs.to_filespec should generate filespecs that match git spec
  `RB #4078 <https://rbcommons.com/s/twitter/r/4078>`_

* ivy runner make a copy of jvm_options before mutating it
  `RB #4080 <https://rbcommons.com/s/twitter/r/4080>`_

* Log exceptions from testRunFinished() in our listener
  `Issue #3638 <https://github.com/pantsbuild/pants/issues/3638>`_
  `RB #4060 <https://rbcommons.com/s/twitter/r/4060>`_

* Fix problems with unicode in junit XML output when writing to HTML report
  `RB #4051 <https://rbcommons.com/s/twitter/r/4051>`_

* [bugfix] Fix `remote_sources()` targets dependency injection.
  `RB #4052 <https://rbcommons.com/s/twitter/r/4052>`_

New Engine Work
~~~~~~~~~~~~~~~

* Convert BundleAdaptor to BundleProps during JvmApp target creation
  `RB #4057 <https://rbcommons.com/s/twitter/r/4057>`_

* Repair pantsd+watchman integration test flakiness.
  `RB #4067 <https://rbcommons.com/s/twitter/r/4067>`_

* [engine] Isolated Process Execution - First Cut
  `RB #4029 <https://rbcommons.com/s/twitter/r/4029>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Use ProjectTree in SourceRoots.all_roots().
  `RB #4079 <https://rbcommons.com/s/twitter/r/4079>`_

* Add a note indicating that scope=forced is available beginning in 1.1.0
  `RB #4070 <https://rbcommons.com/s/twitter/r/4070>`_

* Update version numbering and clarify notes updates
  `RB #4069 <https://rbcommons.com/s/twitter/r/4069>`_

* Improve deprecation warning for default backend option reliance.
  `RB #4061 <https://rbcommons.com/s/twitter/r/4061>`_
  `RB #4053 <https://rbcommons.com/s/twitter/r/4053>`_

* Cleanup the annotation test project code
  `RB #4056 <https://rbcommons.com/s/twitter/r/4056>`_

* Add documentation for scopes
  `RB #4050 <https://rbcommons.com/s/twitter/r/4050>`_

* Add collection literals note to styleguide
  `RB #4028 <https://rbcommons.com/s/twitter/r/4028>`_

1.1.0-rc0 (7/1/2016)
--------------------

This is the first `1.1.0-rc` release on the way to `1.1.0`.

New Features
~~~~~~~~~~~~

* Subprocess clean-all
  `RB #4011 <https://rbcommons.com/s/twitter/r/4011>`_

* expose products for jvm bundle create and python binary create tasks
  `RB #3959 <https://rbcommons.com/s/twitter/r/3959>`_
  `RB #4015 <https://rbcommons.com/s/twitter/r/4015>`_

* Implement zinc `unused deps` check
  `RB #3635 <https://rbcommons.com/s/twitter/r/3635>`_

API Changes
~~~~~~~~~~~

* Add `is_target_root` in export
  `RB #4030 <https://rbcommons.com/s/twitter/r/4030>`_

Bugfixes
~~~~~~~~

* ConsoleRunner bugfix for @TestSerial and other test cleanups
  `RB #4026 <https://rbcommons.com/s/twitter/r/4026>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Proper implementation of `**` globs in the v2 engine
  `RB #4034 <https://rbcommons.com/s/twitter/r/4034>`_

* [engine] Fix TargetMacro replacements of adapted aliases
  `Issue #3560 <https://github.com/pantsbuild/pants/issues/3560>`_
  `Issue #3561 <https://github.com/pantsbuild/pants/issues/3561>`_
  `RB #4000 <https://rbcommons.com/s/twitter/r/4000>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix dead apidocs link for guava.
  `RB #4037 <https://rbcommons.com/s/twitter/r/4037>`_

* Bump setproctitle to 1.1.10.
  `Issue #44 <https://github.com/dvarrazzo/py-setproctitle/issues/44>`_
  `RB #4035 <https://rbcommons.com/s/twitter/r/4035>`_

* Set a default read timeout for fetching node pre-installed modules. 1 second default often fails
  `RB #4025 <https://rbcommons.com/s/twitter/r/4025>`_

* Improve stderr handling for ProcessManager.get_subprocess_output().
  `RB #4019 <https://rbcommons.com/s/twitter/r/4019>`_

* Add AnnotatedParallelClassesAndMethodsTest* and AnnotatedParallelMethodsTest*
  `RB #4027 <https://rbcommons.com/s/twitter/r/4027>`_

1.1.0-pre6 (06/24/2016)
-----------------------

This is the seventh `1.1.0-pre` release on the way to the `1.1.0` stable branch.
It bumps the version of the JUnit runner and is highlighted by a new hybrid engine.

New Features
~~~~~~~~~~~~
* Create a hybrid optionally async engine.
  `RB #3897 <https://rbcommons.com/s/twitter/r/3897>`_

API Changes
~~~~~~~~~~~
* Ability to filter list options.
  `RB #3997 <https://rbcommons.com/s/twitter/r/3997>`_

* Add an :API: public exception for abstract members.
  `RB #3968 <https://rbcommons.com/s/twitter/r/3968>`_

Bugfixes
~~~~~~~~
* When source fields are strings, not collections, raise an error; Test deferred sources addresses error
  `RB #3970 <https://rbcommons.com/s/twitter/r/3970>`_

* Report JUnit tests with failing assumptions as skipped tests
  `RB #4010 <https://rbcommons.com/s/twitter/r/4010>`_

New Engine Work
~~~~~~~~~~~~~~~
* [engine] refine exception output
  `RB #3992 <https://rbcommons.com/s/twitter/r/3992>`_

* [engine] Fix imports of classes that moved from fs to project_tree
  `RB #4005 <https://rbcommons.com/s/twitter/r/4005>`_

* [engine] Use scandir, and preserve symlink paths in output
  `RB #3991 <https://rbcommons.com/s/twitter/r/3991>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Use junit-runner-1.0.10
  `RB #4010 <https://rbcommons.com/s/twitter/r/4010>`_
  `RB #4020 <https://rbcommons.com/s/twitter/r/4020>`_

* A `remote_sources` target as a better mechanism for from_target.
  `RB #3830 <https://rbcommons.com/s/twitter/r/3830>`_
  `RB #4014 <https://rbcommons.com/s/twitter/r/4014>`_

* dep-usage: output aliases information
  `RB #3984 <https://rbcommons.com/s/twitter/r/3984>`_

1.1.0-pre5 (06/10/2016)
-----------------------

This is the sixth `1.1.0-pre` release on the way to the `1.1.0` stable branch.

API Changes
~~~~~~~~~~~
* Remove docgen from list of default packages, don't deprecate the --default-backend-packages option.
  `RB #3972 <https://rbcommons.com/s/twitter/r/3972>`_
  `RB #3988 <https://rbcommons.com/s/twitter/r/3988>`_

* Delete the spindle-plugin from contrib.
  `RB #3990 <https://rbcommons.com/s/twitter/r/3990>`_

Bugfixes
~~~~~~~~
* Fix warnings about AliasTarget not having a BUILD alias.
  `RB #3993 <https://rbcommons.com/s/twitter/r/3993>`_

* Make checkstyle's options filename-agnostic.
  `Issue #3555 <https://github.com/pantsbuild/pants/issues/3555>`_
  `RB #3975 <https://rbcommons.com/s/twitter/r/3975>`_

New Engine Work
~~~~~~~~~~~~~~~
* [engine] Capture the `resources=globs` argument for Python targets
  `Issue #3506 <https://github.com/pantsbuild/pants/issues/3506>`_
  `RB #3979 <https://rbcommons.com/s/twitter/r/3979>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Use the z.jar files on the zinc classpath instead of the destination directory of the class files.
  `RB #3955 <https://rbcommons.com/s/twitter/r/3955>`_
  `RB #3982 <https://rbcommons.com/s/twitter/r/3982>`_

* logs kill server info when creating server
  `RB #3983 <https://rbcommons.com/s/twitter/r/3983>`_

* Add format to mustache filenames
  `RB #3976 <https://rbcommons.com/s/twitter/r/3976>`_

* Support for transitioning to making all backends opt-in.
  `RB #3972 <https://rbcommons.com/s/twitter/r/3972>`_

* dep-usage: create edge only for those direct or transitive dependencies.
  `RB #3978 <https://rbcommons.com/s/twitter/r/3978>`_

1.1.0-pre4 (06/03/2016)
-----------------------

This is the fifth `1.1.0-pre` release on the way to the `1.1.0` stable branch

API Changes
~~~~~~~~~~~

New Features
~~~~~~~~~~~~
* Introducing target aliases in BUILD files.
  `RB #3939 <https://rbcommons.com/s/twitter/r/3939>`_

* Add JUnit HTML report to the JUnit runner
  `RB #3958 <https://rbcommons.com/s/twitter/r/3958>`_

* Add FindBugs plugin to released plugins
  `RB #3909 <https://rbcommons.com/s/twitter/r/3909>`_

Bugfixes
~~~~~~~~
* Fix an issue introduced in go resolve refactoring
  `RB #3963 <https://rbcommons.com/s/twitter/r/3963>`_

* Fix unicode string on stdout causing taskerror
  `RB #3944 <https://rbcommons.com/s/twitter/r/3944>`_

New Engine Work
~~~~~~~~~~~~~~~
* [engine] Don't compute a cache key for things we aren't going to cache
  `RB #3971 <https://rbcommons.com/s/twitter/r/3971>`_

* [engine] Repair scope binding issue in BUILD parsing.
  `RB #3969 <https://rbcommons.com/s/twitter/r/3969>`_

* [engine] Fix support for TargetMacros in the new parser, and support default names
  `RB #3966 <https://rbcommons.com/s/twitter/r/3966>`_

* [engine] Make `follow_links` kwarg to globs non-fatal.
  `RB #3964 <https://rbcommons.com/s/twitter/r/3964>`_

* [engine] Directly use entries while scheduling
  `RB #3953 <https://rbcommons.com/s/twitter/r/3953>`_

* [engine] Optionally inline inlineable Nodes
  `RB #3931 <https://rbcommons.com/s/twitter/r/3931>`_

* [engine] skip hanging multiprocess engine tests
  `RB #3940 <https://rbcommons.com/s/twitter/r/3940>`_
  `RB #3941 <https://rbcommons.com/s/twitter/r/3941>`_

* [engine] clean up non in-memory storage usage, only needed for LocalMultiprocessEngine
  `RB #3940 <https://rbcommons.com/s/twitter/r/3940>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Update jdk paths reference in jvm_projects documentation
  `RB #3942 <https://rbcommons.com/s/twitter/r/3942>`_

* Make `JvmAppAdaptor` compatible with bare `bundle()` form.
  `RB #3965 <https://rbcommons.com/s/twitter/r/3965>`_

* Update junit-runner to version 1.0.9 and test new experimental runner logic
  `RB #3925 <https://rbcommons.com/s/twitter/r/3925>`_

* Make BaseGlobs.from_sources_field() work for sets and strings.
  `RB #3961 <https://rbcommons.com/s/twitter/r/3961>`_

* Advance JVM bundle options, and enable them in jvm_app target as well
  `RB #3910 <https://rbcommons.com/s/twitter/r/3910>`_

* Rename PARALLEL_BOTH to PARALLEL_CLASSES_AND_METHODS inside JUnit Runner
  `RB #3925 <https://rbcommons.com/s/twitter/r/3925>`_
  `RB #3962 <https://rbcommons.com/s/twitter/r/3962>`_

* Resolve backends before plugins
  `RB #3909 <https://rbcommons.com/s/twitter/r/3909>`_
  `RB #3950 <https://rbcommons.com/s/twitter/r/3950>`_

* Update contributors.sh script not to count publish commits
  `RB #3946 <https://rbcommons.com/s/twitter/r/3946>`_

* Don't fail running virtualenv inside of a git hook
  `RB #3945 <https://rbcommons.com/s/twitter/r/3945>`_

* Prepare 1.0.1
  `RB #3960 <https://rbcommons.com/s/twitter/r/3960>`_

* During releases, only publish the docsite from master
  `RB #3956 <https://rbcommons.com/s/twitter/r/3956>`_

* Decode Watchman file event filenames to UTF-8.
  `RB #3951 <https://rbcommons.com/s/twitter/r/3951>`_

* Bump pex requirement to 1.1.10.
  `Issue #265 <https://github.com/pantsbuild/pex/issues/265>`_
  `RB #3949 <https://rbcommons.com/s/twitter/r/3949>`_

* Refactor and simplify go fetcher code.
  `Issue #3439 <https://github.com/pantsbuild/pants/issues/3439>`_
  `Issue #3427 <https://github.com/pantsbuild/pants/issues/3427>`_
  `Issue #2018 <https://github.com/pantsbuild/pants/issues/2018>`_
  `RB #3902 <https://rbcommons.com/s/twitter/r/3902>`_

1.1.0-pre3 (05/27/2016)
-----------------------

This is the fourth `1.1.0-pre` release on the way to the `1.1.0` stable branch

Bugfixes
~~~~~~~~

* Fix hardcoded pants ignore from 'dist/' to '/rel_distdir/'. Use pants_ignore: +[...] in pants.ini
  `RB #3927 <https://rbcommons.com/s/twitter/r/3927>`_

New Engine Work
~~~~~~~~~~~~~~~

* Robustify pantsd + watchman integration tests.
  `RB #3912 <https://rbcommons.com/s/twitter/r/3912>`_

* Add an `--enable-engine` flag to leverage the v2 engine-backed LegacyBuildGraph without pantsd.
  `RB #3932 <https://rbcommons.com/s/twitter/r/3932>`_

* Adds in the experimental test runner
  `RB #3921 <https://rbcommons.com/s/twitter/r/3921>`_

* Flush out some bugs with the 'parallel methods' running in the legacy runner.
  `RB #3922 <https://rbcommons.com/s/twitter/r/3922>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Adding a special '$JAVA_HOME' symbol for use in jvm platforms args.
  `RB #3924 <https://rbcommons.com/s/twitter/r/3924>`_

* Defaulting to Node 6.2.0
  `Issue #3478 <https://github.com/pantsbuild/pants/issues/3478>`_
  `RB #3918 <https://rbcommons.com/s/twitter/r/3918>`_

* Add documentation on deploy_jar_rules for Maven experts
  `RB #3937 <https://rbcommons.com/s/twitter/r/3937>`_

* Bump pex requirement to pex==1.1.9.
  `RB #3935 <https://rbcommons.com/s/twitter/r/3935>`_

1.1.0-pre2 (05/21/2016)
-----------------------

This is the third `1.1.0-pre` release on the way to the `1.1.0` stable branch.

API Changes
~~~~~~~~~~~

* Deprecate ambiguous options scope name components.
  `RB #3893 <https://rbcommons.com/s/twitter/r/3893>`_

New Features
~~~~~~~~~~~~

* Make NodeTest task use the TestRunnerTaskMixin to support timeouts
  `Issue #3453 <https://github.com/pantsbuild/pants/issues/3453>`_
  `RB #3870 <https://rbcommons.com/s/twitter/r/3870>`_

* Support Scrooge generation of additional languages.
  `RB #3823 <https://rbcommons.com/s/twitter/r/3823>`_

Bugfixes
~~~~~~~~

* Adding product dependency for NodeResolve/NodeTest
  `RB #3870 <https://rbcommons.com/s/twitter/r/3870>`_
  `RB #3906 <https://rbcommons.com/s/twitter/r/3906>`_

* Make pinger.py work with both HTTP and HTTPS.
  `RB #3904 <https://rbcommons.com/s/twitter/r/3904>`_

* Fix the release script to include `pre` releases in the version match
  `RB #3903 <https://rbcommons.com/s/twitter/r/3903>`_

* Fix UnicodeDecodeError in pailgun when unicode is present in environment.
  `RB #3915 <https://rbcommons.com/s/twitter/r/3915>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Split release notes by release branch
  `RB #3890 <https://rbcommons.com/s/twitter/r/3890>`_
  `RB #3907 <https://rbcommons.com/s/twitter/r/3907>`_

* Update the release strategy docs
  `RB #3890 <https://rbcommons.com/s/twitter/r/3890>`_

* Bump junit-runner to 1.0.7 to pick up previous changes
  `RB #3908 <https://rbcommons.com/s/twitter/r/3908>`_

* junit-runner: Separate out parsing specs from making list of requests
  `RB #3846 <https://rbcommons.com/s/twitter/r/3846>`_

* New Google Analytics tracking code for www.pantsbuild.org.
  `RB #3917 <https://rbcommons.com/s/twitter/r/3917>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] yield only addresses associated with target specs, so `list` goal will work
  `RB #3873 <https://rbcommons.com/s/twitter/r/3873>`_


1.1.0-pre1 (05/17/2016)
-----------------------

This is the second `1.1.0-pre` release on the way to the `1.1.0` stable branch.

It adds support for JDK8 javac plugins to the core, adds a Java FindBugs module to contrib, and
improves the convenience of `dict` typed options.

API Changes
~~~~~~~~~~~

* Add 'transitive' and 'scope' attributes to export of target
  `RB #3845 <https://rbcommons.com/s/twitter/r/3845>`_

* Remove deprecated check_published_deps goal
  `RB #3893 <https://rbcommons.com/s/twitter/r/3893>`_
  `RB #3894 <https://rbcommons.com/s/twitter/r/3894>`_

New Features
~~~~~~~~~~~~

* Allow updating dict option values instead of replacing them.
  `RB #3896 <https://rbcommons.com/s/twitter/r/3896>`_

* Add FindBugs plugin to contrib
  `RB #3847 <https://rbcommons.com/s/twitter/r/3847>`_

* Implement options scope name deprecation.
  `RB #3884 <https://rbcommons.com/s/twitter/r/3884>`_

* Find custom jar manifests in added directories.
  `RB #3886 <https://rbcommons.com/s/twitter/r/3886>`_

* Support for javac plugins.
  `RB #3839 <https://rbcommons.com/s/twitter/r/3839>`_

* Making the permissions of the local artifact cache configurable.
  `RB #3869 <https://rbcommons.com/s/twitter/r/3869>`_

Bugfixes
~~~~~~~~

* Fix GoFetch and test.
  `RB #3888 <https://rbcommons.com/s/twitter/r/3888>`_

* Fix SourceRoots.all_roots to respect fixed roots.
  `RB #3881 <https://rbcommons.com/s/twitter/r/3881>`_

* Skip test_pantsd_run_with_watchman on OSX.
  `RB #3874 <https://rbcommons.com/s/twitter/r/3874>`_

* PrepCommandIntegration handles parallel runs.
  `RB #3864 <https://rbcommons.com/s/twitter/r/3864>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Link the Go doc to the site toc.
  `RB #3891 <https://rbcommons.com/s/twitter/r/3891>`_

* Make pants a good example of Go contrib usage.
  `RB #3889 <https://rbcommons.com/s/twitter/r/3889>`_

* Add a command line option for meta tag resolution
  `RB #3882 <https://rbcommons.com/s/twitter/r/3882>`_

* Add a note about fixing PANTS_VERSION mismatch.
  `RB #3887 <https://rbcommons.com/s/twitter/r/3887>`_

* Add a Go Plugin README.
  `RB #3866 <https://rbcommons.com/s/twitter/r/3866>`_

* Add the start of a Jenkins runbook.
  `RB #3871 <https://rbcommons.com/s/twitter/r/3871>`_

* Update packer docs to include canary process.
  `RB #3862 <https://rbcommons.com/s/twitter/r/3862>`_

* Move thrift language/rpc validation to codegen implementations
  `RB #3823 <https://rbcommons.com/s/twitter/r/3823>`_
  `RB #3876 <https://rbcommons.com/s/twitter/r/3876>`_

* Enhance options scope deprecation test.
  `RB #3901 <https://rbcommons.com/s/twitter/r/3901>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Use the appropriate `BaseGlobs` subclass for excludes
  `RB #3875 <https://rbcommons.com/s/twitter/r/3875>`_

* [engine] Avoid indexing on LegacyBuildGraph.reset().
  `RB #3868 <https://rbcommons.com/s/twitter/r/3868>`_

* [engine] Add a pantsd.ini for development use of the daemon + watchman + buildgraph caching.
  `RB #3859 <https://rbcommons.com/s/twitter/r/3859>`_

* [engine] Fix bundle handling
  `RB #3860 <https://rbcommons.com/s/twitter/r/3860>`_


1.1.0-pre0 (05/09/2016)
-----------------------

The **1.1.0-preN** releases start here.

Pants is building to the **1.1.0** release candidates and is **N** releases towards that milestone.

This release has several changes to tooling, lots of documentation updates, and some minor api changes.


API Changes
~~~~~~~~~~~

* Add 'transitve' and 'scope' attributes to export of target
  `RB #3582 <https://rbcommons.com/s/twitter/r/3582>`_
  `RB #3845 <https://rbcommons.com/s/twitter/r/3845>`_

* Add Support for "exclude" to globs in BUILD files
  `RB #3828 <https://rbcommons.com/s/twitter/r/3828>`_

* Add support for pants-ignore to ProjectTree
  `RB #3698 <https://rbcommons.com/s/twitter/r/3698>`_

* New -default-concurrency parameter to junit-runner
  `RB #3707 <https://rbcommons.com/s/twitter/r/3707>`_
  `RB #3753 <https://rbcommons.com/s/twitter/r/3753>`_

* Make :API: public types useable.
  `RB #3752 <https://rbcommons.com/s/twitter/r/3752>`_

* Add public API markers to targets and base tasks used by plugins.
  `RB #3746 <https://rbcommons.com/s/twitter/r/3746>`_

* De-publicize a FAPP private method.
  `RB #3750 <https://rbcommons.com/s/twitter/r/3750>`_


New Features
~~~~~~~~~~~~

* Introduce `idea-plugin` goal to invoke intellij pants plugin via CLI
  `Issue #58 <https://github.com/pantsbuild/intellij-pants-plugin/issues/58>`_
  `RB #3664 <https://rbcommons.com/s/twitter/r/3664>`_

* Enhance parallel testing junit_tests
  `Issue #3209 <https://github.com/pantsbuild/pants/issues/3209>`_
  `RB #3707 <https://rbcommons.com/s/twitter/r/3707>`_


Bugfixes
~~~~~~~~

* Use `JarBuilder` to build jars.
  `RB #3851 <https://rbcommons.com/s/twitter/r/3851>`_

* Ensure `DistributionLocator` is `_reset` after tests.
  `RB #3832 <https://rbcommons.com/s/twitter/r/3832>`_

* Handle values for list options that end with quotes
  `RB #3813 <https://rbcommons.com/s/twitter/r/3813>`_

* Addresses should not equal things that are not addresses.
  `RB #3791 <https://rbcommons.com/s/twitter/r/3791>`_

* Add transitive dep required by javac 8.
  `RB #3808 <https://rbcommons.com/s/twitter/r/3808>`_

* Fix distribution tests in the face of many javas.
  `RB #3778 <https://rbcommons.com/s/twitter/r/3778>`_

* Fixup `PEP8Error` to carry lines.
  `RB #3647 <https://rbcommons.com/s/twitter/r/3647>`_
  `RB #3806 <https://rbcommons.com/s/twitter/r/3806>`_

* Use NailgunTask's Java distribution consistently.
  `RB #3793 <https://rbcommons.com/s/twitter/r/3793>`_

* The thrift dep is indirect but required under JDK8.
  `RB #3787 <https://rbcommons.com/s/twitter/r/3787>`_

* Fix relative path in publish script.
  `RB #3789 <https://rbcommons.com/s/twitter/r/3789>`_

* Remove a failing test for deleted functionality.
  `RB #3783 <https://rbcommons.com/s/twitter/r/3783>`_

* Fixup `PythonChrootTest.test_thrift_issues_2005`.
  `RB #3774 <https://rbcommons.com/s/twitter/r/3774>`_

* Fix JDK 8 javadoc errors.
  `RB #3773 <https://rbcommons.com/s/twitter/r/3773>`_

* Fix `DIST_ROOT` trample in `test_distribution.py`.
  `RB #3747 <https://rbcommons.com/s/twitter/r/3747>`_

* Skip flaky pytest timeout failure ITs.
  `RB #3748 <https://rbcommons.com/s/twitter/r/3748>`_


Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Convert from JNLP to ssh.
  `RB #3855 <https://rbcommons.com/s/twitter/r/3855>`_

* Skip test_pantsd_run_with_watchman on Linux.
  `RB #3853 <https://rbcommons.com/s/twitter/r/3853>`_

* Fixup jenkins-slave-connect.service pre-reqs.
  `RB #3849 <https://rbcommons.com/s/twitter/r/3849>`_

* Expose JENKINS_LABELS to slaves.
  `RB #3844 <https://rbcommons.com/s/twitter/r/3844>`_

* Move node info to a script.
  `RB #3842 <https://rbcommons.com/s/twitter/r/3842>`_

* Retry git operations up to 2 times.
  `RB #3841 <https://rbcommons.com/s/twitter/r/3841>`_

* Add instance debug data to shard output.
  `RB #3837 <https://rbcommons.com/s/twitter/r/3837>`_

* Improve `jenkins-slave-connect.service` robustness.
  `RB #3836 <https://rbcommons.com/s/twitter/r/3836>`_

* Use `env` and `pwd()` to get rid of $ escaping.
  `RB #3835 <https://rbcommons.com/s/twitter/r/3835>`_

* Improve the packer docs.
  `RB #3834 <https://rbcommons.com/s/twitter/r/3834>`_

* Isolate Jenkins CI ivy caches.
  `RB #3829 <https://rbcommons.com/s/twitter/r/3829>`_

* Comment on release concurrency in the docs
  `RB #3827 <https://rbcommons.com/s/twitter/r/3827>`_

* Update plugin doc.
  `RB #3811 <https://rbcommons.com/s/twitter/r/3811>`_

* Use packer to create the jenkins linux slave AMI.
  `RB #3825 <https://rbcommons.com/s/twitter/r/3825>`_

* Upgrade cloc to 1.66.
  `RB #3820 <https://rbcommons.com/s/twitter/r/3820>`_

* Add an explicit legal exception to deprecation policy
  `RB #3809 <https://rbcommons.com/s/twitter/r/3809>`_

* Add a Jenkins2.0 CI configuration.
  `RB #3799 <https://rbcommons.com/s/twitter/r/3799>`_

* Scrooge gen: Cache resolved scrooge deps
  `RB #3790 <https://rbcommons.com/s/twitter/r/3790>`_

* Front Page update
  `RB #3807 <https://rbcommons.com/s/twitter/r/3807>`_

* remove 'staging' url from 1.0 release

* Fix various hardwired links to point to pantsbuild.org.
  `RB #3805 <https://rbcommons.com/s/twitter/r/3805>`_

* Push the docsite to benjyw.github.io as well as pantsbuild.github.io.
  `RB #3802 <https://rbcommons.com/s/twitter/r/3802>`_

* Add -L to allow curl to redirect in case we decide to move website later
  `RB #3804 <https://rbcommons.com/s/twitter/r/3804>`_

* Merge back in some content from the options page
  `RB #3767 <https://rbcommons.com/s/twitter/r/3767>`_
  `RB #3795 <https://rbcommons.com/s/twitter/r/3795>`_

* Update the community page
  `RB #3801 <https://rbcommons.com/s/twitter/r/3801>`_

* Updates for documentation followon from Radical site redesign
  `RB #3794 <https://rbcommons.com/s/twitter/r/3794>`_

* Use a set for the contains check in topo order path for invalidation
  `RB #3786 <https://rbcommons.com/s/twitter/r/3786>`_

* Rework ScalaPlatform.
  `RB #3779 <https://rbcommons.com/s/twitter/r/3779>`_

* Pants 1.0 Release announcement
  `RB #3781 <https://rbcommons.com/s/twitter/r/3781>`_

* Revisit the 'Why Use Pants' doc
  `RB #3788 <https://rbcommons.com/s/twitter/r/3788>`_

* Move src/python/pants/docs to src/docs.
  `RB #3782 <https://rbcommons.com/s/twitter/r/3782>`_

* Adding managed_jar_dependencies docs to 3rdparty_jvm.md.
  `RB #3776 <https://rbcommons.com/s/twitter/r/3776>`_

* Radical makeover of docsite.
  `RB #3767 <https://rbcommons.com/s/twitter/r/3767>`_

* Add changelog items from 1.0.x branch
  `RB #3772 <https://rbcommons.com/s/twitter/r/3772>`_

* Upgrade to pex 1.1.6.
  `RB #3768 <https://rbcommons.com/s/twitter/r/3768>`_

* convert RequestException into a more standard NonfatalArtifactCacheError
  `RB #3754 <https://rbcommons.com/s/twitter/r/3754>`_

* [docs] Remove setup difficulty caveat, and highlight install script
  `RB #3764 <https://rbcommons.com/s/twitter/r/3764>`_

* add JUnit XML tests for a TestSuite and a Parameterized Test
  `RB #3758 <https://rbcommons.com/s/twitter/r/3758>`_

* Adding Grapeshot to the Powered by page, approved by Katie Lucas of Grapeshot
  `RB #3760 <https://rbcommons.com/s/twitter/r/3760>`_

* Upgrade default go from 1.6.1 to 1.6.2.
  `RB #3755 <https://rbcommons.com/s/twitter/r/3755>`_

* Upgrade to pex 1.1.5.
  `RB #3743 <https://rbcommons.com/s/twitter/r/3743>`_


New Engine Work
~~~~~~~~~~~~~~~

* [engine] Don't cycle-detect into completed Nodes
  `RB #3848 <https://rbcommons.com/s/twitter/r/3848>`_

* Migrate `pants.engine.exp` to `pants.engine.v2`.
  `RB #3798 <https://rbcommons.com/s/twitter/r/3798>`_
  `RB #3800 <https://rbcommons.com/s/twitter/r/3800>`_

* [pantsd] Build graph caching via v2 engine integration.
  `RB #3798 <https://rbcommons.com/s/twitter/r/3798>`_

* [engine] Walk references in the ProductGraph
  `RB #3803 <https://rbcommons.com/s/twitter/r/3803>`_

* [engine] Add support for collection wrapping a class
  `RB #3769 <https://rbcommons.com/s/twitter/r/3769>`_

* [engine] Simplify ProductGraph.walk
  `RB #3792 <https://rbcommons.com/s/twitter/r/3792>`_

* [engine] Make ScmProjectTree pickable and fix most GitFSTest tests
  `Issue #3281 <https://github.com/pantsbuild/pants/issues/3281>`_
  `RB #3770 <https://rbcommons.com/s/twitter/r/3770>`_

* [engine] bug fix: to pickle/unpickle within the proper context
  `RB #3751 <https://rbcommons.com/s/twitter/r/3751>`_
  `RB #3761 <https://rbcommons.com/s/twitter/r/3761>`_

* [engine] Support for synthetic target injection
  `RB #3738 <https://rbcommons.com/s/twitter/r/3738>`_


1.0.0-rc1 (04/22/2016)
----------------------

This release has several changes related to documentation, CI fixes and work
in preparation for the 1.0 release.

* CI work to enable us to move to jenkins
* Documentation leading up to 1.0
* Engine work around handling of symlinks
* Set a global -Xmx default for JVMs
* improve cache hit rate with eager caching of zinc



* Add public api markers
  `RB #3727 <https://rbcommons.com/s/twitter/r/3727>`_

* Fix public API markers based on feedback
  `RB #3442 <https://rbcommons.com/s/twitter/r/3442>`_
  `RB #3718 <https://rbcommons.com/s/twitter/r/3718>`_


Bugfixes
~~~~~~~~

* A few fixes to config path computation, esp. in tests.
  `RB #3709 <https://rbcommons.com/s/twitter/r/3709>`_

* Fix built-in `graph_info` backend BUILD deps.
  `RB #3726 <https://rbcommons.com/s/twitter/r/3726>`_

* Improve android install robustness.
  `RB #3725 <https://rbcommons.com/s/twitter/r/3725>`_

* Fix `jvm_app` fingerprinting for bundles with non-existing files.
  `RB #3654 <https://rbcommons.com/s/twitter/r/3654>`_

* Fix `PEP8Error` `Nit` subclass line_range.
  `RB #3714 <https://rbcommons.com/s/twitter/r/3714>`_

* Fix import order issue.

* Some fixes to make tests more robust around jvm_options.
  `RB #3706 <https://rbcommons.com/s/twitter/r/3706>`_

* Fix a typo that caused problems with REPL in custom scala
  `RB #3703 <https://rbcommons.com/s/twitter/r/3703>`_

* Fix ProgressListener % progress.
  `RB #) <https://rbcommons.com/s/twitter/r/3710/)>`_
  `RB #3712 <https://rbcommons.com/s/twitter/r/3712>`_


Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Write artifacts to the cache when vt.update() is called.
  `RB #3722 <https://rbcommons.com/s/twitter/r/3722>`_

* Bump the open file ulimit on OSX.
  `RB #3733 <https://rbcommons.com/s/twitter/r/3733>`_

* Skip intermittently failing test_multiprocess_engine_multi.
  `RB #3731 <https://rbcommons.com/s/twitter/r/3731>`_

* Doc running pants from sources in other repos.
  `RB #3715 <https://rbcommons.com/s/twitter/r/3715>`_

* Add quiz-up to the powered by page
  `RB #3732 <https://rbcommons.com/s/twitter/r/3732>`_

* Point Node preinstalled-project at a better URL.
  `RB #3710 <https://rbcommons.com/s/twitter/r/3710>`_

* Show details in the builddict.
  `RB #3708 <https://rbcommons.com/s/twitter/r/3708>`_

* Add the Phabricator .arcconfig file.
  `RB #3728 <https://rbcommons.com/s/twitter/r/3728>`_

* Use requests/Fetcher to fetch Node pre-installed's.
  `RB #3711 <https://rbcommons.com/s/twitter/r/3711>`_

 Add --bootstrap-ivy-settings option
  `RB #3700 <https://rbcommons.com/s/twitter/r/3700>`_

* Prioritize command line option error and add ConfigValidationError for option error differentiation.
  `RB #3721 <https://rbcommons.com/s/twitter/r/3721>`_

* Set a global -Xmx default for JVMs
  `RB #3705 <https://rbcommons.com/s/twitter/r/3705>`_

* Enforce that an option name isn't registered twice in a scope.
  `Issue #3200) <https://github.com/pantsbuild/pants/issues/3200)>`_
  `RB #3695 <https://rbcommons.com/s/twitter/r/3695>`_


New Engine Work
~~~~~~~~~~~~~~~

* [engine] Split engine docs from example docs
  `RB #3734 <https://rbcommons.com/s/twitter/r/3734>`_

* [engine] Only request literal Variants for Address objects
  `RB #3724 <https://rbcommons.com/s/twitter/r/3724>`_

* [engine] Implement symlink handling
  `Issue #3189)) <https://github.com/pantsbuild/pants/issues/3189))>`_
  `RB #3691 <https://rbcommons.com/s/twitter/r/3691>`_


0.0.82 (04/15/2016)
-------------------

This release has several changes to tooling, bugfixes relating to symlinks, and some minor api changes.

* Downgraded the version of pex to fix a bug.
* Upgraded the version of zinc to fix a bug.
* Added "preferred_jvm_distributions" to the pants export data, deprecating "jvm_distributions". This
  way the IntelliJ plugin (and other tooling) can easily configure the project sdk that pants is
  actually using.
* Changed some option defaults for jvm_compile, zinc_compile, and the --ignore-patterns global option.

API Changes
~~~~~~~~~~~

* Export preferred_jvm_distributions that pants actually uses (and to deprecate jvm_distributions)
  `RB #3680 <https://rbcommons.com/s/twitter/r/3680>`_

* Change some option defaults.
  `RB #3678 <https://rbcommons.com/s/twitter/r/3678>`_

Bugfixes
~~~~~~~~

* Use the latest zinc release in order to pick up the canonical path fix.
  `RB #3692 <https://rbcommons.com/s/twitter/r/3692>`_
  `RB #3693 <https://rbcommons.com/s/twitter/r/3693>`_

* [zinc] Record the canonical path that was fingerprinted, rather than the input path
  `RB #3692 <https://rbcommons.com/s/twitter/r/3692>`_

* Resolve symlinks when generating sdists.
  `RB #3689 <https://rbcommons.com/s/twitter/r/3689>`_

* Downgrade pex to 2.1.2
  `Issue #226 <https://github.com/pantsbuild/pex/issues/226>`_
  `RB #3687 <https://rbcommons.com/s/twitter/r/3687>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Have all JvmToolMixins share the same --jvm-options option registration.
  `RB #3684 <https://rbcommons.com/s/twitter/r/3684>`_

* Upgrade default go from 1.6 to 1.6.1.
  `RB #3686 <https://rbcommons.com/s/twitter/r/3686>`_

* Remove unused config_section from codegen tasks.
  `RB #3683 <https://rbcommons.com/s/twitter/r/3683>`_

* Add duration pytest option to pants.travis-ci.ini
  `RB #3662 <https://rbcommons.com/s/twitter/r/3662>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Limit matches for FilesystemNode to only cases where lhs/rhs match
  `Issue #3117 <https://github.com/pantsbuild/pants/issues/3117>`_
  `RB #3688 <https://rbcommons.com/s/twitter/r/3688>`_

0.0.81 (04/10/2016)
-------------------

This release is primarily minor internal and engine improvements.

* The pants workspace lock has been renamed.  If you've been having
  issues with deadlocks after switching back and forth between old
  and new versions of pants, this release should fix that and
  remain backward compatible.
* Because of the lock rename, ensure that ``.pants.workdir.file_lock``
  and ``.pants.workdir.file_lock.lock_message`` are ignored by your SCM
  (e.g. in ``.gitignore``).
* The junit option --suppress-output has been removed following
  a deprecation cycle.  Use --output-mode instead.
* Several internal ivy utility methods have been removed following
  a deprecation cycle.

API Changes
~~~~~~~~~~~

* Add Public API markers for ivy and java APIs
  `RB #3655 <https://rbcommons.com/s/twitter/r/3655>`_

* Set public API markers for codegen
  `RB #3648 <https://rbcommons.com/s/twitter/r/3648>`_

Bugfixes
~~~~~~~~

* [CI] Skip hanging engine test.
  `RB #3653 <https://rbcommons.com/s/twitter/r/3653>`_

* Fix #3132: `./pants changed` doesn't fail on changed invalid `BUILD` files
  `RB #3646 <https://rbcommons.com/s/twitter/r/3646>`_

New Features
~~~~~~~~~~~~


Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove ivy utils deprecated methods and update test
  `RB #3675 <https://rbcommons.com/s/twitter/r/3675>`_

* Scrub some old migration code.
  `RB #3672 <https://rbcommons.com/s/twitter/r/3672>`_

* Rename the global lock from pants.run to pants.workdir.file_lock
  `RB #3633 <https://rbcommons.com/s/twitter/r/3633>`_
  `RB #3668 <https://rbcommons.com/s/twitter/r/3668>`_

* Deprecate action='store_true'/'store_false' options.
  `RB #3667 <https://rbcommons.com/s/twitter/r/3667>`_

* Give a hint on how to disable the Invalid config entries detected message
  `RB #3642 <https://rbcommons.com/s/twitter/r/3642>`_

* Mark an integration test as such.
  `RB #3659 <https://rbcommons.com/s/twitter/r/3659>`_

* Replace all action='store_true' options with type=bool.
  `RB #3661 <https://rbcommons.com/s/twitter/r/3661>`_

* minor: fix bundle deployjar help
  `RB #3133 <https://rbcommons.com/s/twitter/r/3133>`_
  `RB #3663 <https://rbcommons.com/s/twitter/r/3663>`_

* pythonstyle: Fix suppression support; improve SyntaxError reporting; Only report each nit once
  `RB #3647 <https://rbcommons.com/s/twitter/r/3647>`_

* Import zincutils
  `RB #3657 <https://rbcommons.com/s/twitter/r/3657>`_

* Squelch message from scm
  `RB #3645 <https://rbcommons.com/s/twitter/r/3645>`_

* Skip generating reports for empty resolves
  `RB #3625 <https://rbcommons.com/s/twitter/r/3625>`_

* Export manifest jar for external junit run
  `RB #3626 <https://rbcommons.com/s/twitter/r/3626>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] bug fix: ensure we catch all exceptions in subprocess
  `Issue #3149 <https://github.com/pantsbuild/pants/issues/3149>`_
  `Issue #3149 <https://github.com/pantsbuild/pants/issues/3149>`_
  `RB #3656 <https://rbcommons.com/s/twitter/r/3656>`_

* [engine] Move the visualizer into LocalScheduler.
  `RB #3649 <https://rbcommons.com/s/twitter/r/3649>`_

* [pantsd] Repair watchman startup flakiness.
  `RB #3644 <https://rbcommons.com/s/twitter/r/3644>`_

0.0.80 (04/01/2016)
-------------------

This release brings scopes for jvm dependencies.  Proper documentation has not
been added yet, but check out the review description for more info:
https://rbcommons.com/s/twitter/r/3582

The following deprecated items were removed:

Options:

* `--scala-platform-runtime`:
  Option is no longer used, `--version` is used to specify the major
  version. The runtime is created based on major version. The runtime
  target will be defined at the address `//:scala-library` unless it is
  overriden by the option `--runtime-spec` and a `--version` is set to
  custom.

* `--spec-excludes`:
  Use `--ignore-patterns` instead. Use .gitignore syntax for each item, to
  simulate old behavior prefix each item with "/".

* `PANTS_DEFAULT_*`:
  Use `PANTS_GLOBAL_*` instead of `PANTS_DEFAULT_*`

BUILD Files:

* `python_requirement(..., version_filter)`:
  The `version_filter` argument has been removed with no replacement.

API Changes
~~~~~~~~~~~

* Process 0.0.80 deprecation removals.
  `RB #3639 <https://rbcommons.com/s/twitter/r/3639>`_

* Delete the Haskell contrib package.
  `RB #3631 <https://rbcommons.com/s/twitter/r/3631>`_

Bugfixes
~~~~~~~~

* Add OwnerPrintingInterProcessFileLock and replace OwnerPrintingPIDLockFile.
  `RB #3633 <https://rbcommons.com/s/twitter/r/3633>`_

* Fix literal credentials
  `RB #3624 <https://rbcommons.com/s/twitter/r/3624>`_

* Remove defaults for custom scala tools.
  `RB #3609 <https://rbcommons.com/s/twitter/r/3609>`_

* Fix some bad three-state logic in thrift_linter.
  `RB #3621 <https://rbcommons.com/s/twitter/r/3621>`_

* stop adding test support classes to junit failure report
  `RB #3620 <https://rbcommons.com/s/twitter/r/3620>`_

New Features
~~~~~~~~~~~~

* Support options with type=bool.
  `RB #3623 <https://rbcommons.com/s/twitter/r/3623>`_

* Cache `dep-usage.jvm` results and provide ability to use cached results in analysis summary
  `RB #3612 <https://rbcommons.com/s/twitter/r/3612>`_

* Implementing scoped dependencies and classpath intransitivity.
  `RB #3582 <https://rbcommons.com/s/twitter/r/3582>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Speed up node repl integration test by using smaller targets
  `RB #3584 <https://rbcommons.com/s/twitter/r/3584>`_

New Engine Work
~~~~~~~~~~~~~~~

* [pantsd] Map filesystem events to ProductGraph invalidation.
  `RB #3629 <https://rbcommons.com/s/twitter/r/3629>`_

* [engine] Move GraphValidator to examples and make scheduler optionally take a validator.
  `RB #3608 <https://rbcommons.com/s/twitter/r/3608>`_

* [engine] Package cleanup: round one
  `RB #3622 <https://rbcommons.com/s/twitter/r/3622>`_

* [engine] Content address node and state only in engine
  `Issue #3070 <https://github.com/pantsbuild/pants/issues/3070>`_
  `RB #3597 <https://rbcommons.com/s/twitter/r/3597>`_
  `RB #3615 <https://rbcommons.com/s/twitter/r/3615>`_

0.0.79 (03/26/2016)
-------------------

This is the regularly scheduled release that would have been 0.0.78. Due to an upload issue and
a desire for immutable versions, the 0.0.78 version number was skipped: all deprecations have been
extended by one release to account for that.

Bugfixes
~~~~~~~~

* Only mark a build incremental if it is successfully cloned
  `RB #3613 <https://rbcommons.com/s/twitter/r/3613>`_

* Avoid pathological regex performance when linkifying large ivy output.
  `RB #3603 <https://rbcommons.com/s/twitter/r/3603>`_

* Convert ivy lock to use OwnerPrintingPIDLockFile
  `RB #3598 <https://rbcommons.com/s/twitter/r/3598>`_

* Fix errors due to iterating over None-types in ivy resolve.
  `RB #3596 <https://rbcommons.com/s/twitter/r/3596>`_

* Do not return directories from BUILD file's globs implementation
  `RB #3590 <https://rbcommons.com/s/twitter/r/3590>`_

* Fix unicode parsing of ini files.
  `RB #3595 <https://rbcommons.com/s/twitter/r/3595>`_

* Fix 'compute_hashes' for 'Page' target type
  `RB #3591 <https://rbcommons.com/s/twitter/r/3591>`_

* Fix globs for empty SourcesField
  `RB #3614 <https://rbcommons.com/s/twitter/r/3614>`_

New Features
~~~~~~~~~~~~

* Validate command line options regardless whether goals use them.
  `RB #3594 <https://rbcommons.com/s/twitter/r/3594>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Verify config by default.
  `RB #3636 <https://rbcommons.com/s/twitter/r/3636>`_

* Fix, document, or mark xfail tests that fail in Jenkins.
  `RB #3632 <https://rbcommons.com/s/twitter/r/3632>`_

* Allow a period in a namedver for publishing
  `RB #3611 <https://rbcommons.com/s/twitter/r/3611>`_

* Bump the junit runner release to 1.0.4 to pick up latest code changes
  `RB #3599 <https://rbcommons.com/s/twitter/r/3599>`_

* Re-add the ConsoleRunnerOutputTests and consolodate them into ConsoleRunnerTest, also move test clases used for testing into junit/lib directory
  `RB #2406 <https://rbcommons.com/s/twitter/r/2406>`_
  `RB #3588 <https://rbcommons.com/s/twitter/r/3588>`_

* Add the Android SDK to the linux CI and turn on Android tests.
  `RB #3538 <https://rbcommons.com/s/twitter/r/3538>`_

* Update pyflakes to 1.1.0, enable pyflakes checks and fix all warnings
  `RB #3601 <https://rbcommons.com/s/twitter/r/3601>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Calculate legacy target sources using the engine
  `Issue #3058 <https://github.com/pantsbuild/pants/issues/3058>`_
  `RB #3474 <https://rbcommons.com/s/twitter/r/3474>`_
  `RB #3592 <https://rbcommons.com/s/twitter/r/3592>`_

* Split literal from netrc credentials to allow pickling
  `Issue #3058 <https://github.com/pantsbuild/pants/issues/3058>`_
  `RB #3605 <https://rbcommons.com/s/twitter/r/3605>`_

* Make shader classes top-level to allow for pickling
  `RB #3606 <https://rbcommons.com/s/twitter/r/3606>`_

* [engine] no longer content address subject
  `Issue #3066 <https://github.com/pantsbuild/pants/issues/3066>`_
  `RB #3593 <https://rbcommons.com/s/twitter/r/3593>`_
  `RB #3604 <https://rbcommons.com/s/twitter/r/3604>`_

* Hide cycle in testprojects
  `RB #3600 <https://rbcommons.com/s/twitter/r/3600>`_

* [engine] Eliminate non-determinism computing cache keys
  `RB #3593 <https://rbcommons.com/s/twitter/r/3593>`_

0.0.77 (03/18/2016)
-------------------

Bugfixes
~~~~~~~~

* Update --pinger-tries option to int
  `RB #3541 <https://rbcommons.com/s/twitter/r/3541>`_
  `RB #3561 <https://rbcommons.com/s/twitter/r/3561>`_

New Features
~~~~~~~~~~~~

* Report @Ignore tests in xml reports from JUnit and create report for tests that fail in initialization
  `RB #3571 <https://rbcommons.com/s/twitter/r/3571>`_

* Record the compile classpath used to compile jvm targets.
  `RB #3576 <https://rbcommons.com/s/twitter/r/3576>`_

* Add ignore option to pyflakes check
  `RB #3569 <https://rbcommons.com/s/twitter/r/3569>`_

* Prepare for a global --shard flag.
  `RB #3560 <https://rbcommons.com/s/twitter/r/3560>`_


Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Bump junit-runner to 1.0.3
  `RB #3585 <https://rbcommons.com/s/twitter/r/3585>`_

* Remove unneeded args4j handler registrations that cause failures in
  tests and rename TestParser

  `Issue #1727 <https://github.com/pantsbuild/pants/issues/1727>`_
  `RB #3571 <https://rbcommons.com/s/twitter/r/3571>`_
  `RB #3583 <https://rbcommons.com/s/twitter/r/3583>`_

* Set public API markers for subsystem, process, reporting and scm
  `RB #3551 <https://rbcommons.com/s/twitter/r/3551>`_

* Create and use stable symlinks for the target results dir
  `RB #3553 <https://rbcommons.com/s/twitter/r/3553>`_

* Split Ivy Resolve into Resolve / Fetch steps
  `Issue #3052 <https://github.com/pantsbuild/pants/issues/3052>`_
  `Issue #3053 <https://github.com/pantsbuild/pants/issues/3053>`_
  `Issue #3054 <https://github.com/pantsbuild/pants/issues/3054>`_
  `Issue #3055 <https://github.com/pantsbuild/pants/issues/3055>`_
  `RB #3555 <https://rbcommons.com/s/twitter/r/3555>`_

* [pantsd] Add support for fetching watchman via BinaryUtil.
  `RB #3557 <https://rbcommons.com/s/twitter/r/3557>`_

* Only bootstrap the zinc worker pool if there is work to do
  `RB #3559 <https://rbcommons.com/s/twitter/r/3559>`_

* Bump pex requirement to 1.1.4.
  `RB #3568 <https://rbcommons.com/s/twitter/r/3568>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Introduce ProductGraph invalidation.
  `RB #3578 <https://rbcommons.com/s/twitter/r/3578>`_

* [engine] skip caching for native nodes
  `RB #3581 <https://rbcommons.com/s/twitter/r/3581>`_

* [engine] More pickle cleanups
  `RB #3577 <https://rbcommons.com/s/twitter/r/3577>`_

* [engine] cache StepResult under StepRequest
  `RB #3494 <https://rbcommons.com/s/twitter/r/3494>`_

* [engine] turn off pickle memoization
  `Issue #2969 <https://github.com/pantsbuild/pants/issues/2969>`_
  `RB #3574 <https://rbcommons.com/s/twitter/r/3574>`_

* [engine] Add support for directory matches to PathGlobs, and use for inference
  `RB #3567 <https://rbcommons.com/s/twitter/r/3567>`_


0.0.76 (03/11/2016)
-------------------

This release features:

* The removal of the --fail-slow option to pytest.  This is now the default,
  use --fail-fast for the opposite behavior.

* Moving the Android backend into contrib.

* Support for a special append syntax for list options: +=.

* Tightening up of some aspects of option type conversion. There may be options
  in plugins that were relying on broken behavior (such as when using a string where an
  int was expected), and that will now (correctly) break.

* Deprecation of the PANTS_DEFAULT_* env vars in favor of PANTS_GLOBAL_*.

* Lots of engine work.

* A fix to task implementation versions so that bumping the task version
  will also invalidate artifacts it produced (not just invalidate .pants.d entries).

API Changes
~~~~~~~~~~~

* Move Android into contrib and remove android special-casing.
  `RB #3530 <https://rbcommons.com/s/twitter/r/3530>`_
  `RB #3531 <https://rbcommons.com/s/twitter/r/3531>`_

Bugfixes
~~~~~~~~

* fix typo introduced in https://rbcommons.com/s/twitter/r/3531/
  `RB #3531 <https://rbcommons.com/s/twitter/r/3531>`_
  `RB #3552 <https://rbcommons.com/s/twitter/r/3552>`_

New Features
~~~~~~~~~~~~

* Reimplement list options to support appending.
  `RB #3541 <https://rbcommons.com/s/twitter/r/3541>`_

* Initial round of pantsd + new engine + watchman integration.
  `RB #3524 <https://rbcommons.com/s/twitter/r/3524>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Adds support for golang meta info for imports
  `Issue #2378 <https://github.com/pantsbuild/pants/issues/2378>`_
  `RB #3443 <https://rbcommons.com/s/twitter/r/3443>`_

* Update export TODO to point to the relevant intellij-plugin issue; rm ref to non-existent option
  `RB #3558 <https://rbcommons.com/s/twitter/r/3558>`_

* Use the task implementation version in the fingerprint of a task, to cause cache invalidation for TaskIdentityFingerprintStrategy.
  `RB #3546 <https://rbcommons.com/s/twitter/r/3546>`_

* Deprecate version_filter from python_requirement
  `RB #3545 <https://rbcommons.com/s/twitter/r/3545>`_

* Add _copy_target_attributes implementation to antlr
  `RB #3352 <https://rbcommons.com/s/twitter/r/3352>`_
  `RB #3402 <https://rbcommons.com/s/twitter/r/3402>`_
  `RB #3547 <https://rbcommons.com/s/twitter/r/3547>`_

* Make synthetic jar_library targets dependencies of android_binary.
  `RB #3526 <https://rbcommons.com/s/twitter/r/3526>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Move storage out of scheduler to engine
  `RB #3554 <https://rbcommons.com/s/twitter/r/3554>`_

* [engine] Add native filesystem node type.
  `RB #3550 <https://rbcommons.com/s/twitter/r/3550>`_

* [engine] Implement support for recursive path globs
  `RB #3540 <https://rbcommons.com/s/twitter/r/3540>`_

* [engine] Extract scheduler test setup to a helper
  `RB #3548 <https://rbcommons.com/s/twitter/r/3548>`_

* [bugfix] Properly opt out of zinc's fingerprinting of Resources.
  `RB #3185 <https://rbcommons.com/s/twitter/r/3185>`_

* [engine] switch content addressable storage from dict to a embedded db
  `RB #3517 <https://rbcommons.com/s/twitter/r/3517>`_

0.0.75 (03/07/2016)
-------------------

This release completes the deprecation cycle for several options:

* `--scala-platform-runtime`: The `--scala-platform-version` is now used to configure the scala runtime lib.
* `--use-old-naming-style` for the `export-classpath` goal: The old naming style is no longer supported.
* `--spec-excludes`: Use `--ignore-patterns` instead.

API Changes
~~~~~~~~~~~

* Remove deprecated code planned to remove in 0.0.74 and 0.0.75 versions
  `RB #3527 <https://rbcommons.com/s/twitter/r/3527>`_

Bugfixes
~~~~~~~~

* Lock ivy resolution based on the cache directory being used.
  `RB #3529 <https://rbcommons.com/s/twitter/r/3529>`_

* Fix an issue where ivy-bootstrap is ignoring http proxy setttings
  `RB #3522 <https://rbcommons.com/s/twitter/r/3522>`_

* Clone jars rather than mutating them during ivy resolve
  `RB #3203 <https://rbcommons.com/s/twitter/r/3203>`_

New Features
~~~~~~~~~~~~

* allow list-owners to accept multiple source files and output JSON
  `RB #2755 <https://rbcommons.com/s/twitter/r/2755>`_
  `RB #3534 <https://rbcommons.com/s/twitter/r/3534>`_

* add JSON output-format option to dependees
  `RB #3534 <https://rbcommons.com/s/twitter/r/3534>`_
  `RB #3536 <https://rbcommons.com/s/twitter/r/3536>`_

* Allow running prep_commands in goals other than test
  `RB #3519 <https://rbcommons.com/s/twitter/r/3519>`_

* When using ./pants options, hide options from super-scopes.
  `RB #3528 <https://rbcommons.com/s/twitter/r/3528>`_

* zinc: optionize fatal-warnings compiler args
  `RB #3509 <https://rbcommons.com/s/twitter/r/3509>`_

* An option to set the location of config files.
  `RB #3500 <https://rbcommons.com/s/twitter/r/3500>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix failing test on CI after 'Remove deprecated code planned to remove in 0.0.74 and 0.0.75 versions' change
  `RB #3527 <https://rbcommons.com/s/twitter/r/3527>`_
  `RB #3533 <https://rbcommons.com/s/twitter/r/3533>`_

* Set public API markers for task and util
  `RB #3520 <https://rbcommons.com/s/twitter/r/3520>`_

* Set public api markers for jvm backend
  `RB #3515 <https://rbcommons.com/s/twitter/r/3515>`_

* pythonstyle perf: dont parse the exclusions file for every source file.
  `RB #3518 <https://rbcommons.com/s/twitter/r/3518>`_

* Extract a BuildGraph interface
  `Issue #2979 <https://github.com/pantsbuild/pants/issues/2979>`_
  `RB #3514 <https://rbcommons.com/s/twitter/r/3514>`_

* increase compile.zinc integration test timeout
  `RB #3507 <https://rbcommons.com/s/twitter/r/3507>`_

* fix zinc testing instructions
  `RB #3513 <https://rbcommons.com/s/twitter/r/3513>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Implement the BuildGraph interface via the engine
  `RB #3516 <https://rbcommons.com/s/twitter/r/3516>`_

0.0.74 (02/27/2016)
-------------------

This release changes how pants detects the buildroot from using the location of a
'pants.ini' file, to using the location of a file named 'pants' (usually the name of
the pants executable script at the root of a repo). This is in service of allowing for
zero-or-more pants.ini/config files in the future.

Additionally, there is now support for validating that all options defined in a
pants.ini file are valid options. Passing or configuring '--verify-config' will trigger
this validation. To allow global options to be verified, a new [GLOBAL] section is now the
recommend place to specify global options. This differentiates them from [DEFAULT] options,
which may be used as template values in other config sections, and thus cannot be verified.

API Changes
~~~~~~~~~~~

* Set public api markers for jvm tasks
  `RB #3499 <https://rbcommons.com/s/twitter/r/3499>`_

* Change how we detect the buildroot.
  `RB #3489 <https://rbcommons.com/s/twitter/r/3489>`_

* Add public api markers for core_tasks
  `RB #3490 <https://rbcommons.com/s/twitter/r/3490>`_

* Add [GLOBAL] in pants.ini for pants global options; Add config file validations against options
  `RB #3475 <https://rbcommons.com/s/twitter/r/3475>`_

* Add public api markers for pantsd and options
  `RB #3484 <https://rbcommons.com/s/twitter/r/3484>`_

Bugfixes
~~~~~~~~

* Allow for running the invalidation report when clean-all is on the command line
  `RB #3503 <https://rbcommons.com/s/twitter/r/3503>`_

* Enable fail-fast for pytest so it works like fail-fast for junit
  `RB #3497 <https://rbcommons.com/s/twitter/r/3497>`_

* Reset Subsystems when creating a new context in tests
  `RB #3496 <https://rbcommons.com/s/twitter/r/3496>`_

* Set timeout for the long running 'testprojects' integration test
  `RB #3491 <https://rbcommons.com/s/twitter/r/3491>`_

New Features
~~~~~~~~~~~~

* Java checkstyle will optionally not include the runtime classpath with checkstyle
  `RB #3487 <https://rbcommons.com/s/twitter/r/3487>`_

* Error out on duplicate artifacts for jar publish.
  `RB #3481 <https://rbcommons.com/s/twitter/r/3481>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Change ivy resolve ordering to attempt load first and fall back to full resolve if load fails.
  `RB #3501 <https://rbcommons.com/s/twitter/r/3501>`_

* Clean up extraneous code in jvm_compile.
  `RB #3504 <https://rbcommons.com/s/twitter/r/3504>`_

* Retrieve jars from IvyInfo using a collection of coordinates instead of jar_library targets.
  `RB #3495 <https://rbcommons.com/s/twitter/r/3495>`_

* Document the 'timeout' parameter to junit_tests and python_tests
  `RB #3492 <https://rbcommons.com/s/twitter/r/3492>`_

* When a timeout triggers, first do SIGTERM, then wait a bit, and then do SIGKILL
  `RB #3479 <https://rbcommons.com/s/twitter/r/3479>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Introduce content-addressability
  `Issue #2968 <https://github.com/pantsbuild/pants/issues/2968>`_
  `Issue #2956 <https://github.com/pantsbuild/pants/issues/2956>`_
  `RB #3498 <https://rbcommons.com/s/twitter/r/3498>`_

* [engine] First round of work for 'native' filesystem support
  `Issue #2946, <https://github.com/pantsbuild/pants/issues/2946>`_
  `RB #3488 <https://rbcommons.com/s/twitter/r/3488>`_

* [engine] Implement recursive address walking
  `RB #3485 <https://rbcommons.com/s/twitter/r/3485>`_

0.0.73 (02/19/2016)
-------------------

This release features more formal public API docstrings for many modules
and classes.

API Changes
~~~~~~~~~~~

* Add public API markers for python backend and others
  `RB #3473 <https://rbcommons.com/s/twitter/r/3473>`_
  `RB #3469 <https://rbcommons.com/s/twitter/r/3469>`_

* Upgrade default go to 1.6.
  `RB #3476 <https://rbcommons.com/s/twitter/r/3476>`_

Bugfixes
~~~~~~~~

* Add styleguide to docs
  `RB #3456 <https://rbcommons.com/s/twitter/r/3456>`_

* Remove unused kwarg, locally_changed_targets, from Task.invalidated
  `RB #3467 <https://rbcommons.com/s/twitter/r/3467>`_

* support searching multiple linux java dist dirs
  `RB #3472 <https://rbcommons.com/s/twitter/r/3472>`_

* Separate cli spec parsing from filesystem walking
  `RB #3466 <https://rbcommons.com/s/twitter/r/3466>`_

New Features
~~~~~~~~~~~~

* Allow for random build ordering
  `RB #3462 <https://rbcommons.com/s/twitter/r/3462>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Bump junit runner and jar tool versions to newly published
  `RB #3477 <https://rbcommons.com/s/twitter/r/3477>`_

* Add Foursquare's Fsq.io to the "Powered By"  page.
  `RB #3323 <https://rbcommons.com/s/twitter/r/3323>`_

* Upgrade default go to 1.6.
  `RB #3476 <https://rbcommons.com/s/twitter/r/3476>`_

* Remove unused partitioning support in cache and invalidation support
  `RB #3467 <https://rbcommons.com/s/twitter/r/3467>`_
  `RB #3474 <https://rbcommons.com/s/twitter/r/3474>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Noop only a cyclic dependency, and not an entire Node
  `RB #3478 <https://rbcommons.com/s/twitter/r/3478>`_

* [engine] Tighten input validation
  `Issue #2525 <https://github.com/pantsbuild/pants/issues/2525>`_
  `Issue #2526 <https://github.com/pantsbuild/pants/issues/2526>`_
  `RB #3245 <https://rbcommons.com/s/twitter/r/3245>`_
  `RB #3448 <https://rbcommons.com/s/twitter/r/3448>`_


0.0.72 (02/16/2016)
-------------------
This release concludes the deprecation cycle for the old API for
scanning BUILD files.

The following classes were removed:

* ``FilesystemBuildFile`` (Create ``BuildFile`` with ``IoFilesystem`` instead.)
* ``ScmBuildFile`` (Create ``BuildFile`` with ``ScmFilesystem`` instead.)

The following methods were removed:

* ``BuildFile.scan_buildfiles`` (Use ``BuildFile.scan_build_files`` instead.)
* ``BuildFile.from_cache``
* ``BuildFile.file_exists``
* ``BuildFile.descendants``
* ``BuildFile.ancestors``
* ``BuildFile.siblings``
* ``BuildFile.family`` (Use ``get_build_files_family`` instead.)
* ``BuildFileAddressMapper.from_cache``
* ``BuildFileAddressMapper.scan_buildfiles``
* ``BuildFileAddressMapper.address_map_from_build_file`` (Use ``address_map_from_build_files`` instead.)
* ``BuildFileAddressMapper.parse_build_file_family`` (Use ``parse_build_files`` instead.)

This release features formal public API docstrings for many modules
and classes.  It also includes many bugfixes and minor improvements.

API Changes
~~~~~~~~~~~

* Add public api markers to the following:
  `RB #3453 <https://rbcommons.com/s/twitter/r/3453>`_

* add public api markers to several modules
  `RB #3442 <https://rbcommons.com/s/twitter/r/3442>`_

* add public api markers
  `RB #3440 <https://rbcommons.com/s/twitter/r/3440>`_

Bugfixes
~~~~~~~~

* Fix `./pants list` without arguments output
  `RB #3464 <https://rbcommons.com/s/twitter/r/3464>`_

* jar-tool properly skipping Manifest file using entry's jarPath
  `RB #3437 <https://rbcommons.com/s/twitter/r/3437>`_

* fix pathdeps for synthetic targets.
  `RB #3454 <https://rbcommons.com/s/twitter/r/3454>`_

* Add param to fingerprint_strategy __eq__
  `RB #3446 <https://rbcommons.com/s/twitter/r/3446>`_

* Increase resolution from .1 second to 1 second
  `RB #3311 <https://rbcommons.com/s/twitter/r/3311>`_

* Fix build break due to missing whitespace

* Fix linkify for relative paths pointing outside the buildroot
  `RB #3441 <https://rbcommons.com/s/twitter/r/3441>`_

New Features
~~~~~~~~~~~~

* Options goal to show only functioning options instead of all.
  `RB #3455 <https://rbcommons.com/s/twitter/r/3455>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Skip hashing in ivy fingerprint strategy if target doesn't need fingerprinting
  `RB #3447 <https://rbcommons.com/s/twitter/r/3447>`_

* Add 'Deprecation Policy' docs for 1.0.0.
  `RB #3457 <https://rbcommons.com/s/twitter/r/3457>`_

* Remove dead code
  `RB #3454 <https://rbcommons.com/s/twitter/r/3454>`_
  `RB #3461 <https://rbcommons.com/s/twitter/r/3461>`_

* Clean up stale builds in .pants.d
  `RB #2506 <https://rbcommons.com/s/twitter/r/2506>`_
  `RB #3444 <https://rbcommons.com/s/twitter/r/3444>`_

* Adding a newline symbol for unary shading rules.
  `RB #3452 <https://rbcommons.com/s/twitter/r/3452>`_

* Make IvyTaskMixin.ivy_resolve private, introduce ivy_classpath; clean up some ivy resolve tests
  `RB #3450 <https://rbcommons.com/s/twitter/r/3450>`_

* Move namedtuple declarations out of IvyUtils._generate_jar_template
  `RB #3451 <https://rbcommons.com/s/twitter/r/3451>`_

* Adjust type comment for targets param in JarDependencyManagement.targets_by_artifact_set
  `RB #3449 <https://rbcommons.com/s/twitter/r/3449>`_

* Only invalidate haskell-project targets.
  `RB #3445 <https://rbcommons.com/s/twitter/r/3445>`_

* Polishing --ignore-patterns change
  `RB #3438 <https://rbcommons.com/s/twitter/r/3438>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Minor import cleanups
  `RB #3458 <https://rbcommons.com/s/twitter/r/3458>`_

0.0.71 (02/05/2016)
-------------------

This release is primarily comprised of bugfixes, although there was also removal of support for the
deprecated `--use-old-naming-style` flag for the `export-classpath` goal.

If you use pants with custom plugins you've developed, you should be interested in the first
appearance of a means of communicating the public APIs you can rely on.  You can read
https://rbcommons.com/s/twitter/r/3417 to get a peek at what's to come.

API Changes
~~~~~~~~~~~

* Remove deprecated `--use-old-naming-style` flag.
  `RB #3427 <https://rbcommons.com/s/twitter/r/3427>`_

Bugfixes
~~~~~~~~

* bug fix: remove duplicate 3rdparty jars in the bundle
  `RB #3329 <https://rbcommons.com/s/twitter/r/3329>`_
  `RB #3412 <https://rbcommons.com/s/twitter/r/3412>`_

* Fix __metaclass__ T605:WARNING.
  `RB #3424 <https://rbcommons.com/s/twitter/r/3424>`_

* Retain file permissions when shading monolithic jars.
  `RB #3420 <https://rbcommons.com/s/twitter/r/3420>`_

* Bump jarjar.  The new version is faster and fixes a bug.
  `RB #3405 <https://rbcommons.com/s/twitter/r/3405>`_

* If the junit output file doesn't exist, it should still count as an error on the target
  `RB #3407 <https://rbcommons.com/s/twitter/r/3407>`_

* When a python test fails outside of a function, the resultslog message is just [EF] file.py, without the double-colons
  `RB #3397 <https://rbcommons.com/s/twitter/r/3397>`_

* Fix "ValueError: too many values to unpack" when parsing interpreter versions.
  `RB #3411 <https://rbcommons.com/s/twitter/r/3411>`_

* Update how_to_develop.md's examples
  `RB #3408 <https://rbcommons.com/s/twitter/r/3408>`_

* bug fix: is_app filter not applied when using wildcard
  `RB #3272 <https://rbcommons.com/s/twitter/r/3272>`_
  `RB #3398 <https://rbcommons.com/s/twitter/r/3398>`_

* Add validations to jvm_app bundles; Fix typo in BundleProps construction; fix relative globs
  `RB #3396 <https://rbcommons.com/s/twitter/r/3396>`_

* Add process-level buildroot validation to NailgunExecutor.
  `RB #3393 <https://rbcommons.com/s/twitter/r/3393>`_

* Adding support for multiline param help descriptions in Pants BUILD Dictionary
  `RB #3399 <https://rbcommons.com/s/twitter/r/3399>`_

New Features
~~~~~~~~~~~~

* Cleaning up jarjar rules, and adding support for keep and zap.
  `RB #3428 <https://rbcommons.com/s/twitter/r/3428>`_

* Introduce ignore_patterns option
  `RB #3414 <https://rbcommons.com/s/twitter/r/3414>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix bad test target deps.
  `RB #3425 <https://rbcommons.com/s/twitter/r/3425>`_

* add public api markers
  `RB #3417 <https://rbcommons.com/s/twitter/r/3417>`_

* Attempt a fix for flaky zinc compile failures under Travis-CI.
  `RB #3413 <https://rbcommons.com/s/twitter/r/3413>`_
  `RB #3426 <https://rbcommons.com/s/twitter/r/3426>`_

* Cleanup: rename ivy_resolve kwarg custom_args to extra_args; move / rm unnecessary conf or defaults; rm unnecessary extra_args
  `RB #3416 <https://rbcommons.com/s/twitter/r/3416>`_

* Use one zinc worker per core by default.
  `RB #3413 <https://rbcommons.com/s/twitter/r/3413>`_

* Add sublime text project/workspace extensions to pants .gitignore.
  `RB #3409 <https://rbcommons.com/s/twitter/r/3409>`_

* Refactor IvyTaskMixin's ivy_resolve and functions it depends on
  `RB #3371 <https://rbcommons.com/s/twitter/r/3371>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Implement BUILD file parsing inside the engine
  `RB #3377 <https://rbcommons.com/s/twitter/r/3377>`_


0.0.70 (01/29/2016)
-------------------

This release contains a few big steps towards 1.0.0! The last known issues with build
caching are fixed, so this release enables using a local build cache by default. The
release also includes 'task implementation versioning', so that cached artifacts will
automatically be invalidated as the implementations of Tasks change between pants releases.

API Changes
~~~~~~~~~~~

* Improve deprecated option handling to allow options hinting beyond deprecation version.
  `RB #3369 <https://rbcommons.com/s/twitter/r/3369>`_

* Remove the need to specify scalastyle in BUILD.tools
  `RB #3355 <https://rbcommons.com/s/twitter/r/3355>`_

* Bumping Node to 5.5.0
  `RB #3366 <https://rbcommons.com/s/twitter/r/3366>`_

Bugfixes
~~~~~~~~

* Don't error in export when a target does not have an alias
  `RB #3379 <https://rbcommons.com/s/twitter/r/3379>`_
  `RB #3383 <https://rbcommons.com/s/twitter/r/3383>`_

* Permits creation of StatsDB in a directory that does not yet exist.
  `RB #3384 <https://rbcommons.com/s/twitter/r/3384>`_

* Don't skip writing <artifact>s to ivy.xml even if there's only one.
  `RB #3388 <https://rbcommons.com/s/twitter/r/3388>`_

* Add and use an invalidation-local use_cache setting in IvyTaskMixin
  `RB #3386 <https://rbcommons.com/s/twitter/r/3386>`_

New Features
~~~~~~~~~~~~

* Enable releasing the scalajs plugin
  `RB #3340 <https://rbcommons.com/s/twitter/r/3340>`_

* Allow failover for remote cache
  `RB #3374 <https://rbcommons.com/s/twitter/r/3374>`_

* Enable local caching by default, but disable within pantsbuild/pants.
  `RB #3391 <https://rbcommons.com/s/twitter/r/3391>`_

* Improved task implementation version
  `RB #3331 <https://rbcommons.com/s/twitter/r/3331>`_
  `RB #3381 <https://rbcommons.com/s/twitter/r/3381>`_

* Multiple dependency_managements with multiple ivy resolves.
  `RB #3336 <https://rbcommons.com/s/twitter/r/3336>`_
  `RB #3367 <https://rbcommons.com/s/twitter/r/3367>`_

* A managed_jar_libraries factory to reduce 3rdparty duplication.
  `RB #3372 <https://rbcommons.com/s/twitter/r/3372>`_

* Add support for go_thrift_library().
  `RB #3353 <https://rbcommons.com/s/twitter/r/3353>`_
  `RB #3365 <https://rbcommons.com/s/twitter/r/3365>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add a command line option to turn off prompting before publishing
  `RB #3387 <https://rbcommons.com/s/twitter/r/3387>`_

* Update help message for failed publishing
  `RB #3385 <https://rbcommons.com/s/twitter/r/3385>`_

* Add is_synthetic in pants export
  `RB #3239 <https://rbcommons.com/s/twitter/r/3239>`_

* BuildFile refactoring: rename scan_project_tree_build_files to scan_build_files, get_project_tree_build_files_family to get_build_files_family
  `RB #3382 <https://rbcommons.com/s/twitter/r/3382>`_

* BuildFile refactoring: add more constraints to BuildFile constructor
  `RB #3376 <https://rbcommons.com/s/twitter/r/3376>`_

* BuildFile refactoring: remove usages and deprecate of BuildFile's family, ancestors, siblings and descendants methods
  `RB #3368 <https://rbcommons.com/s/twitter/r/3368>`_

* build_file_alias Perf Improvement: Move class declaration out of method target_macro
  `RB #3361 <https://rbcommons.com/s/twitter/r/3361>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Eager execution and fully declarative dependencies
  `RB #3339 <https://rbcommons.com/s/twitter/r/3339>`_


0.0.69 (01/22/2016)
-------------------

Release Notes
~~~~~~~~~~~~~

This release contains the new `managed_dependencies()` target which
allows you to pin the versions of transitive dependencies on jvm
artifacts.  This is equivalent to the `<dependencyManagement>`
feature in Maven.

Bugfixes
~~~~~~~~

* Revert "Add RecursiveVersion and tests"
  `RB #3331 <https://rbcommons.com/s/twitter/r/3331>`_
  `RB #3351 <https://rbcommons.com/s/twitter/r/3351>`_

New Features
~~~~~~~~~~~~

* First pass at dependency management implementation.
  `RB #3336 <https://rbcommons.com/s/twitter/r/3336>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* SimpleCodegenTask: Add copy_target_attributes
  `RB #3352 <https://rbcommons.com/s/twitter/r/3352>`_

* Make more glob usages lazy; Pass FilesetWithSpec through source field validation, Make BundleProps.filemap lazy
  `RB #3344 <https://rbcommons.com/s/twitter/r/3344>`_

* Update the docs for the ./pants bash-completion script
  `RB #3349 <https://rbcommons.com/s/twitter/r/3349>`_

New Engine Work
~~~~~~~~~~~~~~~

* [engine] Move dependencies onto configuration
  `RB #3316 <https://rbcommons.com/s/twitter/r/3316>`_

0.0.68 (01/15/2016)
-------------------

Release Notes
~~~~~~~~~~~~~

This release concludes the deprecation cycle for backend/core,
which has been removed.  It also simplifies the output directories
for internal and external jars when creating jvm bundles.

API Changes
~~~~~~~~~~~

* bundle_create cleanup: merge internal-libs and libs
  `RB #3261 <https://rbcommons.com/s/twitter/r/3261>`_
  `RB #3329 <https://rbcommons.com/s/twitter/r/3329>`_

* Get rid of backend/authentication.
  `RB #3335 <https://rbcommons.com/s/twitter/r/3335>`_

* Kill the build.manual annotation and the old source_roots.py.
  `RB #3333 <https://rbcommons.com/s/twitter/r/3333>`_

* Remove backend core.
  `RB #3324 <https://rbcommons.com/s/twitter/r/3324>`_

* Add a method call to allow adding a new goal to jvm_prep_command in a custom plugin
  `RB #3325 <https://rbcommons.com/s/twitter/r/3325>`_

* add --jvm-distributions-{min,max}imum-version options
  `Issue #2396 <https://github.com/pantsbuild/pants/issues/2396>`_
  `RB #3310 <https://rbcommons.com/s/twitter/r/3310>`_

Bugfixes
~~~~~~~~

* Bug fix: use target.id as bundle prefix to avoid conflict from basenames
  `RB #3119 <https://rbcommons.com/s/twitter/r/3119>`_
  `RB #3250 <https://rbcommons.com/s/twitter/r/3250>`_
  `RB #3272 <https://rbcommons.com/s/twitter/r/3272>`_

New Features
~~~~~~~~~~~~

* Support `go test` blackbox tests.
  `RB #3327 <https://rbcommons.com/s/twitter/r/3327>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Group classpath products by their targets
  `RB #3329 <https://rbcommons.com/s/twitter/r/3329>`_
  `RB #3338 <https://rbcommons.com/s/twitter/r/3338>`_

* Improve test.pytest failure when coverage is enabled.
  `RB #3334 <https://rbcommons.com/s/twitter/r/3334>`_

* Add RecursiveVersion and tests
  `RB #3331 <https://rbcommons.com/s/twitter/r/3331>`_

* Bump the default Go distribution to 1.5.3.
  `RB #3337 <https://rbcommons.com/s/twitter/r/3337>`_

* Fixup links in `Test{Parallel,Serial}`.
  `RB #3326 <https://rbcommons.com/s/twitter/r/3326>`_

* Follow-up options/documentation changes after scala removed from BUILD.tools
  `RB #3302 <https://rbcommons.com/s/twitter/r/3302>`_

0.0.67 (01/08/2016)
-------------------

Release Notes
~~~~~~~~~~~~~

This release brings an upgrade to pex 1.1.2 for faster python chroot
generation as well as bug fixes that get `./pants repl` working for
scala 2.11 and `./pants test` now handling exceptions in junit
`@BeforeClass` methods.

There is also a glimpse into the future where a pants daemon awaits.
Try it out by adding `--enable-pantsd` to your command line - run times
are 100ms or so faster for many operations.

API Changes
~~~~~~~~~~~

* Bump pex version pinning to 1.1.2.
  `RB #3319 <https://rbcommons.com/s/twitter/r/3319>`_

* extend --use-old-naming-style deprecation
  `RB #3300 <https://rbcommons.com/s/twitter/r/3300>`_
  `RB #3309 <https://rbcommons.com/s/twitter/r/3309>`_

* Add target id to export
  `RB #3291 <https://rbcommons.com/s/twitter/r/3291>`_

* Bump junit-runner version
  `RB #3295 <https://rbcommons.com/s/twitter/r/3295>`_

* Flatten stable classpath for bundle
  `RB #3261 <https://rbcommons.com/s/twitter/r/3261>`_

Bugfixes
~~~~~~~~

* Turn on redirects when retrieving a URL in the fetcher API
  `RB #3275 <https://rbcommons.com/s/twitter/r/3275>`_
  `RB #3317 <https://rbcommons.com/s/twitter/r/3317>`_

* Remove jline dep for scala 2.11 repl
  `RB #3318 <https://rbcommons.com/s/twitter/r/3318>`_

* Start the timeout *after* the process is spawned, drop the mutable process handler variable
  `RB #3202 <https://rbcommons.com/s/twitter/r/3202>`_

* Fix exception in test mechanism in case of exception in @BeforeClass method.
  `RB #3293 <https://rbcommons.com/s/twitter/r/3293>`_

New Features
~~~~~~~~~~~~

* New implementation of builddict/reference generation.
  `RB #3315 <https://rbcommons.com/s/twitter/r/3315>`_

* Save details on exceptions encountered to a file
  `RB #3289 <https://rbcommons.com/s/twitter/r/3289>`_

* [pantsd] Implement PantsRunner->[LocalPantsRunner,RemotePantsRunner] et al.
  `RB #3286 <https://rbcommons.com/s/twitter/r/3286>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Logs the SUCCESS/FAILURE/ABORTED status of each workunit with stats in run_tracker.
  `RB #3307 <https://rbcommons.com/s/twitter/r/3307>`_

* Simplify build dict/reference information extraction.
  `RB #3301 <https://rbcommons.com/s/twitter/r/3301>`_

* Move Sources to a target's configurations, and add subclasses for each language
  `RB #3274 <https://rbcommons.com/s/twitter/r/3274>`_

* Convert loose directories in bundle classpath into jars
  `RB #3297 <https://rbcommons.com/s/twitter/r/3297>`_

* Update pinger timeout in test_pinger_timeout_config and test_global_pinger_memo.
  `RB #3292 <https://rbcommons.com/s/twitter/r/3292>`_

* Add sanity check to test_cache_read_from
  `RB #3284 <https://rbcommons.com/s/twitter/r/3284>`_
  `RB #3299 <https://rbcommons.com/s/twitter/r/3299>`_

* Adding sanity check for locale setting
  `RB #3296 <https://rbcommons.com/s/twitter/r/3296>`_

* Create a complete product graph for the experimentation engine, and use it to validate inputs
  `Issue #2525 <https://github.com/pantsbuild/pants/issues/2525>`_
  `RB #3245 <https://rbcommons.com/s/twitter/r/3245>`_

* Add Unit Test for artifact caching to replace test_scalastyle_cached in test_scalastyle_integration.py, and test_checkstyle_cached in test_checkstyle_integration.py.
  `RB #3284 <https://rbcommons.com/s/twitter/r/3284>`_

0.0.66 (01/02/2016)
-------------------

Release Notes
~~~~~~~~~~~~~

This release comes after a long and relatively quiet holiday break, but it represents a significant
milestone towards pants 1.0.0: it is no longer necessary to explicitly configure any tool versions
(as was usually done with BUILD.tools); all tools, including scalac, have default classpaths.

This release also includes beta support for scala.js via the scalajs contrib module.

Happy Holidays!


API Changes
~~~~~~~~~~~

* Have SourcesField handle the calculation of SourceRoots
  `RB #3230 <https://rbcommons.com/s/twitter/r/3230>`_

* Remove the need to specify scala tools in BUILD.tools
  `RB #3225 <https://rbcommons.com/s/twitter/r/3225>`_

* Explicitly track when synthetic targets are injected.
  `RB #3225 <https://rbcommons.com/s/twitter/r/3225>`_
  `RB #3277 <https://rbcommons.com/s/twitter/r/3277>`_

Bugfixes
~~~~~~~~

* Fix declaration of source scalac-plugins
  `RB #3285 <https://rbcommons.com/s/twitter/r/3285>`_

* Work around the fact that antlr3 is not currently available on pypi
  `RB #3282 <https://rbcommons.com/s/twitter/r/3282>`_

* Avoid ValueError exception from a reporting thread on shutdown
  `RB #3278 <https://rbcommons.com/s/twitter/r/3278>`_

New Features
~~~~~~~~~~~~

* Preliminary support for scala.js
  `RB #2453 <https://rbcommons.com/s/twitter/r/2453>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Convert binary_util to use fetcher like the ivy bootstrapper
  `RB #3275 <https://rbcommons.com/s/twitter/r/3275>`_


0.0.65 (12/18/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release concludes the deprecation cycle of the following items, now removed:

* `--excludes` to `DuplicateDetector`.  Use `--exclude-files`, `--exclude-patterns`,
  or `--exclude-dirs` instead.

* `timeout=0` on test targets.  To use the default timeout, remove the `timeout`
  parameter from your test target.


API Changes
~~~~~~~~~~~

* prefer explicit jvm locations over internal heuristics
  `RB #3231 <https://rbcommons.com/s/twitter/r/3231>`_

* A graph_info backend.
  `RB #3256 <https://rbcommons.com/s/twitter/r/3256>`_

* Move registration of basic build file constructs.
  `RB #3246 <https://rbcommons.com/s/twitter/r/3246>`_

Bugfixes
~~~~~~~~

* Fixup `GoFetch` to respect transitive injections.
  `RB #3270 <https://rbcommons.com/s/twitter/r/3270>`_

* Make jvm_compile's subsystem dependencies global to fix ignored options
  `Issue #2739 <https://github.com/pantsbuild/pants/issues/2739>`_
  `RB #3238 <https://rbcommons.com/s/twitter/r/3238>`_

New Features
~~~~~~~~~~~~

* Go Checkstyle: run checkstyle, add tests, fix examples
  `RB #3223 <https://rbcommons.com/s/twitter/r/3223>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Go: Allow users to specify known import prefixes for import paths.
  `RB #3120 <https://rbcommons.com/s/twitter/r/3120>`_

* Explains how append-style arguments work in pants
  `RB #3268 <https://rbcommons.com/s/twitter/r/3268>`_

* Allow specification of extra env vars for junit_tests runs.
  `RB #3140 <https://rbcommons.com/s/twitter/r/3140>`_
  `RB #3267 <https://rbcommons.com/s/twitter/r/3267>`_

* Refactor help scope computation logic.
  `RB #3264 <https://rbcommons.com/s/twitter/r/3264>`_

* Make it easy for tests to use the "real" python interpreter cache.
  `RB #3257 <https://rbcommons.com/s/twitter/r/3257>`_

* Pass `--confcutdir` to py.test invocation to restrict `conftest.py` scanning to paths in the pants buildroot.
  `RB #3258 <https://rbcommons.com/s/twitter/r/3258>`_

* Remove stale `:all` alias used by plugin integration test
  `RB #3254 <https://rbcommons.com/s/twitter/r/3254>`_

* Move conflicting python test targets to testprojects.
  `RB #3252 <https://rbcommons.com/s/twitter/r/3252>`_

* Add convenience script for running unit tests, update docs
  `RB #3233 <https://rbcommons.com/s/twitter/r/3233>`_
  `RB #3248 <https://rbcommons.com/s/twitter/r/3248>`_

0.0.64 (12/11/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release concludes the deprecation cycle of the following items, now removed:

* `dependencies` and `python_test_suite` target aliases
  BUILD file authors should use `target` instead.

* `pants.backend.core.tasks.{Task,ConsoleTask,ReplTaskMixin}`
  Custom task authors can update imports to the new homes in `pants.task`

* The `test.junit` `--no-suppress-output` option
  You now specify `--output-mode=ALL` in the `test.junit` scope instead.

This release also fixes issues using the Scala REPL via `./pants repl` for very
large classpaths.

API Changes
~~~~~~~~~~~

* Upgrade to junit-runner 1.0.0.
  `RB #3232 <https://rbcommons.com/s/twitter/r/3232>`_

* Remove deprecated `-suppress-output` flag.
  `RB #3229 <https://rbcommons.com/s/twitter/r/3229>`_

* Kill `dependencies`, `python_test_suite` and old task base class aliases.
  `RB #3228 <https://rbcommons.com/s/twitter/r/3228>`_

Bugfixes
~~~~~~~~

* Fixup the `NodePreinstalledModuleResolver`.
  `RB #3240 <https://rbcommons.com/s/twitter/r/3240>`_

* Prepend '//' to Address.spec when the spec_path is empty.
  `RB #3234 <https://rbcommons.com/s/twitter/r/3234>`_

* Fix problem with too long classpath while starting scala repl: python part
  `RB #3195 <https://rbcommons.com/s/twitter/r/3195>`_

* Fix problem with too long classpath while starting scala repl: java part
  `RB #3194 <https://rbcommons.com/s/twitter/r/3194>`_

* Fixing instrumentation classpath mutation to support multiple targets and entries.
  `RB #3108 <https://rbcommons.com/s/twitter/r/3108>`_

* Use target.id to create the stable classpath for bundle and export-classpath
  `RB #3211 <https://rbcommons.com/s/twitter/r/3211>`_

New Features
~~~~~~~~~~~~

* Add an option to write build stats into a local json file.
  `RB #3218 <https://rbcommons.com/s/twitter/r/3218>`_

* Make incremental compile optional for zinc
  `RB #3226 <https://rbcommons.com/s/twitter/r/3226>`_

* Create a test timeout_maximum flag so that we can prevent people from setting an insanely huge timeout
  `RB #3219 <https://rbcommons.com/s/twitter/r/3219>`_

* Add a jvm_prep_command that can work in compile, test, and binary goals
  `RB #3209 <https://rbcommons.com/s/twitter/r/3209>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* A docgen backend.
  `RB #3242 <https://rbcommons.com/s/twitter/r/3242>`_

* Add formatting of choices to help output
  `RB #3241 <https://rbcommons.com/s/twitter/r/3241>`_

* Remove test target aliases for pants' tests
  `RB #3233 <https://rbcommons.com/s/twitter/r/3233>`_

* Move resources() and prep_command() out of backend/core.
  `RB #3235 <https://rbcommons.com/s/twitter/r/3235>`_

* [pantsd] Implement PantsDaemon et al.
  `RB #3224 <https://rbcommons.com/s/twitter/r/3224>`_

* New implementation of `./pants targets`.
  `RB #3214 <https://rbcommons.com/s/twitter/r/3214>`_

* Allow alternate_target_roots to specify an empty collection
  `RB #3216 <https://rbcommons.com/s/twitter/r/3216>`_

* Remove group task and register zinc_compile directly
  `RB #3215 <https://rbcommons.com/s/twitter/r/3215>`_

* Bump the default Go distribution to 1.5.2.
  `RB #3208 <https://rbcommons.com/s/twitter/r/3208>`_

0.0.63 (12/04/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release contains a few deprecations and refactorings to help prepare for 1.0.0. It
also includes the first release of the new Haskell module contributed by Gabriel Gonzalez.
Thanks Gabriel!

API Changes
~~~~~~~~~~~

* Deprecate calling with_description() when registering a task.
  `RB #3207 <https://rbcommons.com/s/twitter/r/3207>`_

* Create a core_tasks top-level dir.
  `RB #3197 <https://rbcommons.com/s/twitter/r/3197>`_

* Move more tasks to core_tasks.
  `RB #3199 <https://rbcommons.com/s/twitter/r/3199>`_

* Move remaining core tasks to core_tasks.
  `RB #3204 <https://rbcommons.com/s/twitter/r/3204>`_

* Upgrade PEX to 1.1.1
  `RB #3200 <https://rbcommons.com/s/twitter/r/3200>`_

* Properly deprecate the Dependencies alias.
  `RB #3196 <https://rbcommons.com/s/twitter/r/3196>`_

* Move the rwbuf code under util/.
  `RB #3193 <https://rbcommons.com/s/twitter/r/3193>`_

Bugfixes
~~~~~~~~

* Fix cache_setup.py so build doesn't fail if configured cache is empty.
  `RB #3142 <https://rbcommons.com/s/twitter/r/3142>`_

New Features
~~~~~~~~~~~~

* Add Haskell plugin to `contrib/release_packages.sh`; now included in the release!
  `RB #3198 <https://rbcommons.com/s/twitter/r/3198>`_

* Refine cache stats: distinguish legit misses from miss errors
  `RB #3190 <https://rbcommons.com/s/twitter/r/3190>`_

* [pantsd] Initial implementation of the pants nailgun service.
  `RB #3171 <https://rbcommons.com/s/twitter/r/3171>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove references to jmake
  `RB #3210 <https://rbcommons.com/s/twitter/r/3210>`_

* Deprecate exception.message usages
  `RB #3201 <https://rbcommons.com/s/twitter/r/3201>`_

* Make monolithic jars produced by bundle/binary slimmer
  `RB #3133 <https://rbcommons.com/s/twitter/r/3133>`_


0.0.62 (11/30/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release is primarily small bug fixes and minor improvements.

The following modules have been moved, with their old locations now deprecated:

* `MutexTaskMixin` and `ReplTaskMixin` from `pants.backend.core` -> `pants.task`

API Changes
~~~~~~~~~~~

* Move the test runner task mixin out of backend/core.
  `RB #3181 <https://rbcommons.com/s/twitter/r/3181>`_

* Move two generic task mixins out of backend/core.
  `RB #3176 <https://rbcommons.com/s/twitter/r/3176>`_

Bugfixes
~~~~~~~~

* Jvm compile counter should increment for double check cache hits
  `RB #3188 <https://rbcommons.com/s/twitter/r/3188>`_

* Exit with non-zero status when help fails
  `RB #3184 <https://rbcommons.com/s/twitter/r/3184>`_

* When a pytest errors rather than failures, make that target also show up in TestTaskFailedError
  `Issue #2623 <https://github.com/pantsbuild/pants/issues/2623>`_
  `RB #3175 <https://rbcommons.com/s/twitter/r/3175>`_

* Add the -no-header argument to jaxb generator to give deterministic output
  `RB #3179 <https://rbcommons.com/s/twitter/r/3179>`_

* Fix bug that recognized "C" as a remote package.
  `RB #3170 <https://rbcommons.com/s/twitter/r/3170>`_

* Fix jvm_compile product publishing for cached builds
  `RB #3161 <https://rbcommons.com/s/twitter/r/3161>`_

New Features
~~~~~~~~~~~~

* Minimal Haskell plugin for `pants`
  `RB #2975 <https://rbcommons.com/s/twitter/r/2975>`_

* Option to specify stdout from tests to ALL, NONE or FAILURE_ONLY: python part
  `RB #3165 <https://rbcommons.com/s/twitter/r/3165>`_
  `RB #3145 <https://rbcommons.com/s/twitter/r/3145>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Update the dependencies returned from ivy to be in a stable (sorted) order.
  `RB #3168 <https://rbcommons.com/s/twitter/r/3168>`_

* Refactor detect_duplicates with some user friendly features
  `RB #3178 <https://rbcommons.com/s/twitter/r/3178>`_

* Updating some documentation for pants.ini Update some settings in pants.ini which used `=` instead of `:`
  `RB #3189 <https://rbcommons.com/s/twitter/r/3189>`_

* Add the compile.zinc options to the options reference
  `RB #3186 <https://rbcommons.com/s/twitter/r/3186>`_

* include_dependees no longer an optional argument.
  `RB #1997 <https://rbcommons.com/s/twitter/r/1997>`_

* Relocate task tests from tests/python/pants_test/task/ to the appropriate backend
  `RB #3183 <https://rbcommons.com/s/twitter/r/3183>`_

* Move tests corresponding to pants/task code.
  `RB #3182 <https://rbcommons.com/s/twitter/r/3182>`_

* Add error message when a JDK is not installed, add minimum requirements to documentation.
  `RB #3136 <https://rbcommons.com/s/twitter/r/3136>`_

0.0.61 (11/23/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This is a hotfix release to fix two regressions in 0.0.60.  It also happens to
include a small UX improvement for the console output of isolated compiles.

Bugfixes
~~~~~~~~

* Make sure the deprecated pants.backend.core.tasks.task module is bundled.
  `RB #3164 <https://rbcommons.com/s/twitter/r/3164>`_

* Revert "Isolate .pex dir"
  `Issue #2610 <https://github.com/pantsbuild/pants/issues/2610>`_
  `RB #3135 <https://rbcommons.com/s/twitter/r/3135>`_
  `RB #3163 <https://rbcommons.com/s/twitter/r/3163>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* During a jvm compile, include a running count in the printed log.
  `RB #3153 <https://rbcommons.com/s/twitter/r/3153>`_

0.0.60 (11/21/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release is primarily small bug fixes and minor improvements.  It also
removes several deprecated options and methods:

* `ReverseDepmap.type`.
* `pants.backend.maven_layout`.
* `Depmap.path_to`.
* `SourceRoot.find`.
* `SourceRoot.find_by_path`.
* `pants.bin.goal_runner.SourceRootBootstrapper` and its option `[goals] bootstrap_buildfiles`.
* `pants.build_graph.target._set_no_cache`.

The following modules have been moved, with their old locations now deprecated:

* `pants.backend.core.tasks.console_task` -> `pants.task.console_task`.
* `pants.backend.core.tasks.task` -> `pants.task.task`.


API Changes
~~~~~~~~~~~

* Move ConsoleTask to pants/task.
  `RB #3157 <https://rbcommons.com/s/twitter/r/3157>`_

* Move task.py out of backend/core.
  `RB #3130 <https://rbcommons.com/s/twitter/r/3130>`_


Bugfixes
~~~~~~~~

* Add a helper staticmethod `closure()` to `BuildGraph`.
  `RB #3160 <https://rbcommons.com/s/twitter/r/3160>`_

* Fix a bug preventing re-upload artifacts that encountered read-errors
  `RB #1361 <https://rbcommons.com/s/twitter/r/1361>`_
  `RB #3141 <https://rbcommons.com/s/twitter/r/3141>`_

* Fix `gopkg.in` fetcher to handle subpackages.
  `RB #3139 <https://rbcommons.com/s/twitter/r/3139>`_

* Update scalac_plugin_args call to the new option name.
  `RB #3132 <https://rbcommons.com/s/twitter/r/3132>`_

* Fix cases where transitivity is required despite strict_deps; enable within the repo for Java
  `RB #3125 <https://rbcommons.com/s/twitter/r/3125>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Isolate .pex dir
  `RB #3135 <https://rbcommons.com/s/twitter/r/3135>`_

* Group cache hits/misses by their task names
  `RB #3137 <https://rbcommons.com/s/twitter/r/3137>`_

* Add back the --[no-]color flag as deprecated.
  `RB #3150 <https://rbcommons.com/s/twitter/r/3150>`_

* Add support for extra_jvm_options to java_tests
  `Issue #2383 <https://github.com/pantsbuild/pants/issues/2383>`_
  `RB #3140 <https://rbcommons.com/s/twitter/r/3140>`_

* Removed Wire 2.0 support.  Update default Wire library to 1.8.0
  `RB #3124 <https://rbcommons.com/s/twitter/r/3124>`_

* Remove legacy code in wire_gen and protobuf_gen designed for global codegen strategy
  `RB #3123 <https://rbcommons.com/s/twitter/r/3123>`_

0.0.59 (11/15/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This is a hotfix release that pins an internal pants python requirement to prevent failures running
`./pants test` against `python_tests` targets.
See more details here: http://github.com/pantsbuild/pants/issues#issue/2566

Bugfixes
~~~~~~~~

* Fixup floating `pytest-timeout` dep.
  `RB #3126 <https://rbcommons.com/s/twitter/r/3126>`_

New Features
~~~~~~~~~~~~

* Allow bundle to run for all targets, rather than just target roots
  `RB #3119 <https://rbcommons.com/s/twitter/r/3119>`_

* Allow per-jvm-target configuration of fatal warnings
  `RB #3080 <https://rbcommons.com/s/twitter/r/3080>`_

* Add options to repro and expand user on output file
  `RB #3109 <https://rbcommons.com/s/twitter/r/3109>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove use of twitter.common.util.topological_sort in SortTargets
  `RB #3121 <https://rbcommons.com/s/twitter/r/3121>`_

* Delay many re.compile calls.
  `RB #3122 <https://rbcommons.com/s/twitter/r/3122>`_

0.0.58 (11/13/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release completes the deprecated cycle for two options and removes them:

* `--infer-test-from-siblings` for `eclipse` and `idea` goals
* `--strategy` for various code generation tasks like protoc

Two existing tasks not installed by default have been moved from `pantsbuild.pants` to
`pantsbuild.pants.contrib.python.checks`.  You can add `pantsbuild.pants.contrib.python.checks` to
your `plugins` list in `pants.ini` to get these tasks installed and start verifying your python
BUILD deps and to check that your python code conforms to pep8 and various other lints.

API Changes
~~~~~~~~~~~

* Remove `--strategy` `--infer-test-from-siblings`.
  `RB #3116 <https://rbcommons.com/s/twitter/r/3116>`_

* Extract `python-eval` and `pythonstyle` to plugin.
  `RB #3114 <https://rbcommons.com/s/twitter/r/3114>`_

Bugfixes
~~~~~~~~

* Do not invalidate jvm targets in zinc for resource dependencies change
  `RB #3106 <https://rbcommons.com/s/twitter/r/3106>`_

* Updated junit-runner to version 0.0.12
  `RB #3092 <https://rbcommons.com/s/twitter/r/3092>`_

* Fixing malformatted xml report names from junit runner.
  `RB #3090 <https://rbcommons.com/s/twitter/r/3090>`_
  `RB #3103 <https://rbcommons.com/s/twitter/r/3103>`_

* Clean up corrupted local cache for errors that are not retryable
  `RB #3045 <https://rbcommons.com/s/twitter/r/3045>`_

New Features
~~~~~~~~~~~~

* Add `pants_requirement()` for plugin authors.
  `RB #3112 <https://rbcommons.com/s/twitter/r/3112>`_

* Allow for zinc analysis portability with the workdir located either inside or outside of the buildroot
  `RB #3083 <https://rbcommons.com/s/twitter/r/3083>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fixup invoking.md to refer to `--config-override`.
  `RB #3115 <https://rbcommons.com/s/twitter/r/3115>`_

* docfix: pants.ini must exist with that name. Not some other name.
  `RB #3110 <https://rbcommons.com/s/twitter/r/3110>`_

* Inline twitter.common.config.Properties and remove t.c.config dep
  `RB #3113 <https://rbcommons.com/s/twitter/r/3113>`_

* Run coverage instrumentation once for each target, streamline command line parameters
  `RB #3107 <https://rbcommons.com/s/twitter/r/3107>`_

* Break out core runtime logic into a PantsRunner
  `RB #3054 <https://rbcommons.com/s/twitter/r/3054>`_

* Improve exception handling for bad option values, such as when PANTS_CONFIG_OVERRIDE="pants.ini" exists in the environment.
  `RB #3087 <https://rbcommons.com/s/twitter/r/3087>`_

0.0.57 (11/09/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This is a hotfix release that fixes a bug preventing repos using `plugins` in the `DEFAULT` section
of `pants.ini` from upgrading to `0.0.56`.

API Changes
~~~~~~~~~~~

* API Change: Move graph walking out of classpath_(util|products)
  `RB #3036 <https://rbcommons.com/s/twitter/r/3036>`_

Bugfixes
~~~~~~~~

* Fix bug when analysis file is corrupt or missing during an incremental compile
  `RB #3101 <https://rbcommons.com/s/twitter/r/3101>`_

* Update the option types for protobuf-gen to be list types, since they are all advanced.
  `RB #3098 <https://rbcommons.com/s/twitter/r/3098>`_
  `RB #3100 <https://rbcommons.com/s/twitter/r/3100>`_

* Fix plugin option references in leaves.
  `RB #3098 <https://rbcommons.com/s/twitter/r/3098>`_

New Features
~~~~~~~~~~~~

* Seed the haskell contrib with `StackDistribution`.
  `RB #2975 <https://rbcommons.com/s/twitter/r/2975>`_
  `RB #3095 <https://rbcommons.com/s/twitter/r/3095>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Better error message for classpath entries outside the working directory
  `RB #3099 <https://rbcommons.com/s/twitter/r/3099>`_

0.0.56 (11/06/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release squashes a bunch of bugs in various area of the codebase, and improves the performance
of both the options and reporting systems.

API Changes
~~~~~~~~~~~

* Remove support for `type_` in jar_dependency. It has been superceded by the 'ext' argument
  `Issue #2442 <https://github.com/pantsbuild/pants/issues/2442>`_
  `RB #3038 <https://rbcommons.com/s/twitter/r/3038>`_

* Prevent option shadowing, and deprecate/remove some shadowed options.
  `RB #3035 <https://rbcommons.com/s/twitter/r/3035>`_

* Synthetic jars always created when invoking the JVM (Argument list too long revisited)
  `RB #2672 <https://rbcommons.com/s/twitter/r/2672>`_
  `RB #3003 <https://rbcommons.com/s/twitter/r/3003>`_

New Features
~~~~~~~~~~~~

* The ./pants junit runner now works with Cucumber scenarios.
  `RB #3090 <https://rbcommons.com/s/twitter/r/3090>`_

* New compile task to publish symlinks to jars with class files to pants_distdir
  `RB #3059 <https://rbcommons.com/s/twitter/r/3059>`_

* Add new `--fail-floating` option to `GoBuildgen`.
  `RB #3073 <https://rbcommons.com/s/twitter/r/3073>`_

* Add `go` and `go-env` goals.
  `RB #3060 <https://rbcommons.com/s/twitter/r/3060>`_

* Adding NpmRun and NpmTest
  `RB #3048 <https://rbcommons.com/s/twitter/r/3048>`_

* Add --compile-zinc-debug-symbols option
  `RB #3013 <https://rbcommons.com/s/twitter/r/3013>`_

Bugfixes
~~~~~~~~

* Fix test_multiple_source_roots, ignore ordering.
  `RB #3089 <https://rbcommons.com/s/twitter/r/3089>`_

* Change JarPublish.fingerprint to JarPublish.entry_fingerprint to ensure task fingerprint can change
  `RB #3078 <https://rbcommons.com/s/twitter/r/3078>`_

* Deprecate/remove broken path-to option in depmap
  `RB #3079 <https://rbcommons.com/s/twitter/r/3079>`_

* Fix `buildgen.go` to be non-lossy for remote revs.
  `RB #3077 <https://rbcommons.com/s/twitter/r/3077>`_

* Fixup NailgunClient-related OSX CI break
  `RB #3069 <https://rbcommons.com/s/twitter/r/3069>`_

* Fix bench goal, include integration test
  `Issue #2303 <https://github.com/pantsbuild/pants/issues/2303>`_
  `RB #3072 <https://rbcommons.com/s/twitter/r/3072>`_

* Fix missing newline at end of pants output.
  `RB #3019 <https://rbcommons.com/s/twitter/r/3019>`_
  `RB #3063 <https://rbcommons.com/s/twitter/r/3063>`_

* For prepare.services, avoid empty classpath entries by only selecting jvm targets that have services defined
  `RB #3058 <https://rbcommons.com/s/twitter/r/3058>`_

* Safeguard against stale ProcessManager metadata re-use.
  `RB #3047 <https://rbcommons.com/s/twitter/r/3047>`_

* Fix test timeout implementation by adding abort handlers
  `RB #2979 <https://rbcommons.com/s/twitter/r/2979>`_

* Allow for sourceless codegen based purely on target parameters
  `RB #3044 <https://rbcommons.com/s/twitter/r/3044>`_

* Fix a copy-paste error in migrate_config.py.
  `RB #3039 <https://rbcommons.com/s/twitter/r/3039>`_

* Fix issue with trailing newlines in Python checkstyle
  `RB #3033 <https://rbcommons.com/s/twitter/r/3033>`_

* Make profiling cover the init sequence too.
  `RB #3022 <https://rbcommons.com/s/twitter/r/3022>`_

* Unshade org.pantsbuild.junit.annotation so that @TestParallel works
  `RB #3012 <https://rbcommons.com/s/twitter/r/3012>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove pytest helpers where unittest will do.
  `RB #3091 <https://rbcommons.com/s/twitter/r/3091>`_

* Remove a hack in IvyResolve.
  `Issue #2177 <https://github.com/pantsbuild/pants/issues/2177>`_
  `RB #3088 <https://rbcommons.com/s/twitter/r/3088>`_

* Get rid of argparse usage entirely.
  `RB #3074 <https://rbcommons.com/s/twitter/r/3074>`_

* Additional test case for changed goal
  `RB #2589 <https://rbcommons.com/s/twitter/r/2589>`_
  `RB #2660 <https://rbcommons.com/s/twitter/r/2660>`_

* Upgrade to RBTools 0.7.5.
  `RB #3076 <https://rbcommons.com/s/twitter/r/3076>`_

* Improve handling of -v, -V, --version and --pants-version.
  `RB #3071 <https://rbcommons.com/s/twitter/r/3071>`_

* Turn off ng under OSX-CI like we do for linux.
  `RB #3067 <https://rbcommons.com/s/twitter/r/3067>`_

* Cache npm resolves in CI.
  `RB #3065 <https://rbcommons.com/s/twitter/r/3065>`_

* Improve incremental caching tests
  `RB #3028 <https://rbcommons.com/s/twitter/r/3028>`_
  `RB #3034 <https://rbcommons.com/s/twitter/r/3034>`_

* Refactor the python checkstyle plugin system.
  `RB #3061 <https://rbcommons.com/s/twitter/r/3061>`_

* Better implementation of the reporting emitter thread.
  `RB #3057 <https://rbcommons.com/s/twitter/r/3057>`_

* Preparation to allow locating the workdir outside of the build root
  `RB #3050 <https://rbcommons.com/s/twitter/r/3050>`_
  `RB #3050 <https://rbcommons.com/s/twitter/r/3050>`_

* Create the argparse.ArgParser instance only on demand.
  `RB #3056 <https://rbcommons.com/s/twitter/r/3056>`_

* Fix implementation of shallow copy on OptionValueContainer.
  `RB #3041 <https://rbcommons.com/s/twitter/r/3041>`_

* Defer argparse registration to the last possible moment.
  `RB #3049 <https://rbcommons.com/s/twitter/r/3049>`_

* Pave the way for server-side python nailgun components
  `RB #3030 <https://rbcommons.com/s/twitter/r/3030>`_

* Don't resolve node_remote_module targets by themselves and modify how REPL works
  `RB #2997 <https://rbcommons.com/s/twitter/r/2997>`_

* Remove mustache use from the reporting system.
  `RB #3018 <https://rbcommons.com/s/twitter/r/3018>`_

New Engine Work
~~~~~~~~~~~~~~~

* Add an engine/exp README.
  `RB #3042 <https://rbcommons.com/s/twitter/r/3042>`_

* Simplify and robustify `LocalMultiprocessEngine`.
  `RB #3084 <https://rbcommons.com/s/twitter/r/3084>`_

* Example of an additional planner that produces a Classpath for targets
  `Issue #2484 <https://github.com/pantsbuild/pants/issues/2484>`_
  `RB #3075 <https://rbcommons.com/s/twitter/r/3075>`_

* Add fail-slow handling to `Engine`.
  `RB #3040 <https://rbcommons.com/s/twitter/r/3040>`_

* Cleanup a few scheduler warts.
  `RB #3032 <https://rbcommons.com/s/twitter/r/3032>`_


0.0.55 (10/23/2015)
-------------------

Release Notes
~~~~~~~~~~~~~
This release has many experimental engine features, as well as general bug fixes and performance improvements.


API Changes
~~~~~~~~~~~

* Remove the deprecated modules, `pants.base.address` and `pants.base.address_lookup_error`.

New Features
~~~~~~~~~~~~

* Add a --dependencies option to cloc.
  `RB #3008 <https://rbcommons.com/s/twitter/r/3008>`_

* Add native support for incremental caching, and use it in jvm_compile
  `RB #2991 <https://rbcommons.com/s/twitter/r/2991>`_

* A CountLinesOfCode task.
  `RB #3005 <https://rbcommons.com/s/twitter/r/3005>`_

Bugfixes
~~~~~~~~

* Include JarDependency.excludes when creating cache_key. Add unittest.
  `RB #3001 <https://rbcommons.com/s/twitter/r/3001>`_

* Added junit.framework to excludes for shading
  `RB #3017 <https://rbcommons.com/s/twitter/r/3017>`_

* fix failure in test_global_pinger_memo
  `RB #3007 <https://rbcommons.com/s/twitter/r/3007>`_

* Handle case where only transitive dependencies have changed during an incremental build
  `Issue #2446 <https://github.com/pantsbuild/pants/issues/2446>`_
  `RB #3028 <https://rbcommons.com/s/twitter/r/3028>`_

New Engine Work
~~~~~~~~~~~~~~~

* Add support for config selectors in dep addresses.
  `RB #3025 <https://rbcommons.com/s/twitter/r/3025>`_

* Support Configurations extending one, merging N.
  `RB #3023 <https://rbcommons.com/s/twitter/r/3023>`_

* Refactor engine experiment module organization.
  `RB #3004 <https://rbcommons.com/s/twitter/r/3004>`_

* Implement a custom pickle for Serializables.
  `RB #3002 <https://rbcommons.com/s/twitter/r/3002>`_

* Introduce the new engine and two implementations.
  `RB #3000 <https://rbcommons.com/s/twitter/r/3000>`_

* Introduce the 1st cut at the new engine frontend.
  `RB #2989 <https://rbcommons.com/s/twitter/r/2989>`_

* Prepare the 1st test for the new engine front end.
  `RB #2988 <https://rbcommons.com/s/twitter/r/2988>`_

* Add a visualization tool for execution plans.
  `RB #3010 <https://rbcommons.com/s/twitter/r/3010>`_


Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Overwrite timing stat report files less frequently.
  `RB #3021 <https://rbcommons.com/s/twitter/r/3021>`_

* Make sure we emit the timing/stats epilog even for quiet tasks.
  `RB #3019 <https://rbcommons.com/s/twitter/r/3019>`_

* Add a fixed source root for the go_remote dir in contrib/go.
  `RB #3027 <https://rbcommons.com/s/twitter/r/3027>`_

* Restore Sources custom types per extension.
  `RB #3010 <https://rbcommons.com/s/twitter/r/3010>`_
  `RB #3011 <https://rbcommons.com/s/twitter/r/3011>`_

* [coverage] Removing emma after its deprecation cycle.
  `RB #3009 <https://rbcommons.com/s/twitter/r/3009>`_

* Kill _JUnitRunner and move code to the JUnitRun task
  `RB #2994 <https://rbcommons.com/s/twitter/r/2994>`_

* Make 'list-owners' faster by not instantiating already injected targets
  `RB #2967 <https://rbcommons.com/s/twitter/r/2967>`_
  `RB #2968 <https://rbcommons.com/s/twitter/r/2968>`_

* Get rid of all bootstrap BUILD files in our repo.
  `RB #2996 <https://rbcommons.com/s/twitter/r/2996>`_

* Run python checkstyle only on invalidated targets.
  `RB #2995 <https://rbcommons.com/s/twitter/r/2995>`_

* Switch all internal code to use the new source roots mechanism.
  `RB #2987 <https://rbcommons.com/s/twitter/r/2987>`_

* Remove jmake and apt members from JvmCompile
  `RB #2990 <https://rbcommons.com/s/twitter/r/2990>`_

* Leverage fast_relpath in `BuildFileAddressMapper`.
  `RB #2981 <https://rbcommons.com/s/twitter/r/2981>`_

* Simplify fetcher regexes; doc the '^' assumption.
  `RB #2980 <https://rbcommons.com/s/twitter/r/2980>`_

* Remove the global codegen strategy from simple_codegen_task
  `RB #2985 <https://rbcommons.com/s/twitter/r/2985>`_

* Added an explanation to the docs re: who can be added to a review.
  `RB #2983 <https://rbcommons.com/s/twitter/r/2983>`_

0.0.54 (10/16/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

This release features several improvements to Go support and a refactored SourceRoot API, as well as several bug fixes and small refactors.

API Changes
~~~~~~~~~~~

* Move address.py/address_lookup_error.py from base to build_graph
  `RB #2954 <https://rbcommons.com/s/twitter/r/2954>`_

* Deprecate --infer-test-from-sibling argument to ide_gen.py.
  `RB #2966 <https://rbcommons.com/s/twitter/r/2966>`_

* Several deprecated methods and modules were removed:
  `src/python/pants/base/target.py`
  `src/python/pants/base/build_file_aliases.py`
  `JarDependency._maybe_set_ext`
  `JarDependency.exclude`
  The `Repository` build file alias

New Features
~~~~~~~~~~~~

* Add support for golang.org/x remote libs.
  `Issue #2378 <https://github.com/pantsbuild/pants/issues/2378>`_
  `Issue #2379 <https://github.com/pantsbuild/pants/issues/2379>`_
  `Issue #2378 <https://github.com/pantsbuild/pants/issues/2378>`_
  `Issue #2379 <https://github.com/pantsbuild/pants/issues/2379>`_
  `RB #2976 <https://rbcommons.com/s/twitter/r/2976>`_

Bugfixes
~~~~~~~~

* Fix `buildgen.go --materialize` to act globally.
  `RB #2977 <https://rbcommons.com/s/twitter/r/2977>`_

* Fix `BuildFileAddressMapper.scan_addresses`.
  `RB #2974 <https://rbcommons.com/s/twitter/r/2974>`_

* Fix catchall except statments
  `RB #2971 <https://rbcommons.com/s/twitter/r/2971>`_

* Fix pinger cache bug and add test.
  `RB #2948 <https://rbcommons.com/s/twitter/r/2948>`_

* Fix mixed classpaths where internal-only is needed.
  `Issue #2358 <https://github.com/pantsbuild/pants/issues/2358>`_
  `Issue #2359 <https://github.com/pantsbuild/pants/issues/2359>`_
  `RB #2964 <https://rbcommons.com/s/twitter/r/2964>`_

* Reproduces problem with deploy_excludes()
  `RB #2961 <https://rbcommons.com/s/twitter/r/2961>`_

* Add missing BUILD dep introduced by d724e2414.

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* A new implementation of SourceRoots.
  `RB #2970 <https://rbcommons.com/s/twitter/r/2970>`_

* Restructured the Export task to make the json blob reusable.
  `RB #2946 <https://rbcommons.com/s/twitter/r/2946>`_

* Make 'changed' faster by not instantiating already injected targets
  `RB #2967 <https://rbcommons.com/s/twitter/r/2967>`_

* Add some more badge bling.
  `RB #2965 <https://rbcommons.com/s/twitter/r/2965>`_

* Cleanup BaseTest.
  `RB #2963 <https://rbcommons.com/s/twitter/r/2963>`_

0.0.53 (10/9/2015)
------------------

Release Notes
~~~~~~~~~~~~~

Due to the hotfix release on Wednesday, this is a fairly light release. But because it addresses two potential correctness issues related to JVM tooling, it is well worth picking up!

API Changes
~~~~~~~~~~~

* Move address.py/address_lookup_error.py from base to build_graph
  `RB #2954 <https://rbcommons.com/s/twitter/r/2954>`_

New Features
~~~~~~~~~~~~

* Add native timeouts to python and junit tests
  `RB #2919 <https://rbcommons.com/s/twitter/r/2919>`_

* Be more conservative about caching incremental JVM compiles
  `RB #2940 <https://rbcommons.com/s/twitter/r/2940>`_

Bugfixes
~~~~~~~~

* Restore deep jvm-tool fingerprinting
  `RB #2955 <https://rbcommons.com/s/twitter/r/2955>`_

* Handle AccessDenied exception in more cases for daemon process scanning
  `RB #2951 <https://rbcommons.com/s/twitter/r/2951>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Upgrade to pex 1.1.0
  `RB #2956 <https://rbcommons.com/s/twitter/r/2956>`_

* [exp] Support for scanning addresses, implement `list`
  `RB #2952 <https://rbcommons.com/s/twitter/r/2952>`_

* [exp] Optimize python parsers
  `RB #2947 <https://rbcommons.com/s/twitter/r/2947>`_

* [exp] Switch from 'typename' to 'type_alias'.
  `RB #2945 <https://rbcommons.com/s/twitter/r/2945>`_

* [exp] Support a non-inlined lazy resolve mode in Graph.
  `RB #2944 <https://rbcommons.com/s/twitter/r/2944>`_

* Emit a nice error message if the compiler used to bootstrap pants isn't functional
  `RB #2949 <https://rbcommons.com/s/twitter/r/2949>`_

* Eliminate travis-ci cache thrash.
  `RB #2957 <https://rbcommons.com/s/twitter/r/2957>`_


0.0.52 (10/7/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This is a hotfix release that unpins pants own six requirement from '==1.9' to '>=1.9,<2' to allow
folks depending on pantsbuild sdists in their own pants built/tested code to successfully resolve
six.  The underlying issue is yet to be fixed, but is tracked
`here <https://github.com/pantsbuild/pex/issues/167>`_.

API Changes
~~~~~~~~~~~

* Bump the default ivy bootstrap jar to 2.4.0.
  `RB #2938 <https://rbcommons.com/s/twitter/r/2938>`_

* Remove the classes_by_target and resources_by_target products
  `RB #2928 <https://rbcommons.com/s/twitter/r/2928>`_

Bugfixes
~~~~~~~~

* Allow six to float a bit.
  `RB #2942 <https://rbcommons.com/s/twitter/r/2942>`_

* Add the include and exclude patterns to the payload so they will make it into the fingerprint
  `RB #2927 <https://rbcommons.com/s/twitter/r/2927>`_

* Ensure GOPATH is always controlled by pants.
  `RB #2933 <https://rbcommons.com/s/twitter/r/2933>`_

* Stopped ivy from failing if an artifact has a url specified.
  `RB #2905 <https://rbcommons.com/s/twitter/r/2905>`_

* Test-cases that passed are now properly omitted the junit summary.
  `RB #2916 <https://rbcommons.com/s/twitter/r/2916>`_
  `RB #2930 <https://rbcommons.com/s/twitter/r/2930>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Kill the checkstyle jvm tool override in pants.ini.
  `RB #2941 <https://rbcommons.com/s/twitter/r/2941>`_

* Only request the `classes_by_source` product if it is necessary
  `RB #2939 <https://rbcommons.com/s/twitter/r/2939>`_

* Fixup android local resolvers.
  `RB #2934 <https://rbcommons.com/s/twitter/r/2934>`_

* Simplify cobertura source paths for reporting
  `RB #2918 <https://rbcommons.com/s/twitter/r/2918>`_

* Upgrade the default Go distribution to 1.5.1.
  `RB #2936 <https://rbcommons.com/s/twitter/r/2936>`_

* Normalize AddressMapper paths for parse/forget.
  `RB #2935 <https://rbcommons.com/s/twitter/r/2935>`_

* Create test task mixin
  `RB #2902 <https://rbcommons.com/s/twitter/r/2902>`_

* Make sure tests/python/pants_test:all runs all the tests
  `RB #2932 <https://rbcommons.com/s/twitter/r/2932>`_

* Seperate out AddressMapper from Graph.
  `RB #2931 <https://rbcommons.com/s/twitter/r/2931>`_

* Add timeout configuration to Pinger and add unittest.
  `RB #2912 <https://rbcommons.com/s/twitter/r/2912>`_

* Adding Node examples
  `RB #2900 <https://rbcommons.com/s/twitter/r/2900>`_


0.0.51 (10/2/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This release moves some packages commonly used in plugins from `pants.base` to `pants.build_graph`.
The old packages still work, but have been deprecated and will be removed in 0.0.53.

API Changes
~~~~~~~~~~~

* Move various build graph-related files to new pkg: build_graph.
  `RB #2899 <https://rbcommons.com/s/twitter/r/2899>`_
  `RB #2908 <https://rbcommons.com/s/twitter/r/2908>`_
  `RB #2909 <https://rbcommons.com/s/twitter/r/2909>`_

Bugfixes
~~~~~~~~

* Ensure execution graph cancellation only happens once per job
  `RB #2910 <https://rbcommons.com/s/twitter/r/2910>`_

* Two performance hacks in build file parsing.
  `RB #2895 <https://rbcommons.com/s/twitter/r/2895>`_

* Performance fix for ./pants depmap --minimal
  `RB #2896 <https://rbcommons.com/s/twitter/r/2896>`_

New Features
~~~~~~~~~~~~

* Introduce instrument_classpath, and modify cobertura to use native class filtering
  `RB #2893 <https://rbcommons.com/s/twitter/r/2893>`_

* Implement deprecation messages for entire modules.
  `RB #2904 <https://rbcommons.com/s/twitter/r/2904>`_

* Upstream the scala_jar and scala_artifact helpers to suffix the scala platform version.
  `RB #2891 <https://rbcommons.com/s/twitter/r/2891>`_

* Adding the bootstrapped node/npm to the PATH when executing commands
  `RB #2883 <https://rbcommons.com/s/twitter/r/2883>`_

* Update path(s) tasks, add tests, extract pluralize to strutil
  `RB #2892 <https://rbcommons.com/s/twitter/r/2892>`_

* Fix duplicate changelog link.
  `RB #2890 <https://rbcommons.com/s/twitter/r/2890>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Extract Config as Configuration to its own module.
  `RB #2924 <https://rbcommons.com/s/twitter/r/2924>`_

* Define a lifecycle for Config objects.
  `RB #2920 <https://rbcommons.com/s/twitter/r/2920>`_

* Add baseline functionality for engine experiments.
  `RB #2914 <https://rbcommons.com/s/twitter/r/2914>`_

* Reformatting the junit output to be consistent with pants.
  `RB #2917 <https://rbcommons.com/s/twitter/r/2917>`_
  `RB #2925 <https://rbcommons.com/s/twitter/r/2925>`_

* Allow junit tests to have empty sources
  `RB #2923 <https://rbcommons.com/s/twitter/r/2923>`_

* Adding a summary list of failing testcases to junit_run.
  `RB #2916 <https://rbcommons.com/s/twitter/r/2916>`_

* Adding the java language level to the IdeaGen module output.
  `RB #2911 <https://rbcommons.com/s/twitter/r/2911>`_

* Make a nicer diagnostic on parse error in pants.ini
  `RB #2907 <https://rbcommons.com/s/twitter/r/2907>`_

* Shorten long target ids by replacing superfluous characters with a hash
  `RB #2894 <https://rbcommons.com/s/twitter/r/2894>`_

* Migrate scrooge to SimpleCodegenTask
  `RB #2808 <https://rbcommons.com/s/twitter/r/2808>`_

0.0.50 (9/25/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This release removes the 'global' jvm compile strategy in favor of the 'isolated' strategy and
switches the default java incremental compilation frontend from jmake to zinc.  If you were using
'global' and/or jmake you'll have some pants.ini cleanup to do.  You can run the migration tool
from the `pantsbuild/pants repository <https://github.com/pantsbuild/pants>`_ by cloning the repo
and running the following command from there against your own repo's pants.ini::

    pantsbuild/pants $ ./pants run migrations/options/src/python:migrate_config -- [path to your repo's pants.ini]

There have been several additional deprecated APIs removed in this release, please review the
API Changes section below.

API Changes
~~~~~~~~~~~

* Remove artifacts from JarDependency; Kill IvyArtifact.
  `RB #2858 <https://rbcommons.com/s/twitter/r/2858>`_

* Kill deprecated `BuildFileAliases.create` method.
  `RB #2888 <https://rbcommons.com/s/twitter/r/2888>`_

* Remove the deprecated `SyntheticAddress` class.
  `RB #2886 <https://rbcommons.com/s/twitter/r/2886>`_

* Slim down the API of the Config class and move it to options/.
  `RB #2865 <https://rbcommons.com/s/twitter/r/2865>`_

* Remove the JVM global compile strategy, switch default java compiler to zinc
  `RB #2852 <https://rbcommons.com/s/twitter/r/2852>`_

* Support arbitrary expressions in option values.
  `RB #2860 <https://rbcommons.com/s/twitter/r/2860>`_

Bugfixes
~~~~~~~~

* Change jar-tool to use CONCAT_TEXT by default for handling duplicates under META-INF/services
  `RB #2881 <https://rbcommons.com/s/twitter/r/2881>`_

* Upgrade to jarjar 1.6.0.
  `RB #2880 <https://rbcommons.com/s/twitter/r/2880>`_

* Improve error handling for nailgun client connection attempts
  `RB #2869 <https://rbcommons.com/s/twitter/r/2869>`_

* Fix Go targets to glob more than '.go' files.
  `RB #2873 <https://rbcommons.com/s/twitter/r/2873>`_

* Defend against concurrent bootstrap of the zinc compiler interface
  `RB #2872 <https://rbcommons.com/s/twitter/r/2872>`_
  `RB #2867 <https://rbcommons.com/s/twitter/r/2867>`_
  `RB #2866 <https://rbcommons.com/s/twitter/r/2866>`_

* Fix missing underscore, add simple unit test
  `RB #2805 <https://rbcommons.com/s/twitter/r/2805>`_
  `RB #2862 <https://rbcommons.com/s/twitter/r/2862>`_

* Fix a protocol bug in `GopkgInFetcher` for v0's.
  `RB #2857 <https://rbcommons.com/s/twitter/r/2857>`_

New Features
~~~~~~~~~~~~

* Allow resolving buildcache hosts via a REST service
  `RB #2815 <https://rbcommons.com/s/twitter/r/2815>`_

* Implement profiling inside pants.
  `RB #2885 <https://rbcommons.com/s/twitter/r/2885>`_

* Adds a new CONCAT_TEXT rule to jar tool to handle text files that might be missing the last newline.
  `RB #2875 <https://rbcommons.com/s/twitter/r/2875>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Enable Future compatibility style checks
  `RB #2884 <https://rbcommons.com/s/twitter/r/2884>`_

* Fix another scoped option issue in the test harnesses
  `RB #2850 <https://rbcommons.com/s/twitter/r/2850>`_
  `RB #2870 <https://rbcommons.com/s/twitter/r/2870>`_

* Fix go_local_source_test_base.py for OSX.
  `RB #2882 <https://rbcommons.com/s/twitter/r/2882>`_

* Fix javadocs and add jvm doc gen to CI.
  `Issue #65 <https://github.com/pantsbuild/pants/issues/65>`_
  `RB #2877 <https://rbcommons.com/s/twitter/r/2877>`_

* Fixup release dry runs; use isolated plugin cache.
  `RB #2874 <https://rbcommons.com/s/twitter/r/2874>`_

* Fix scoped options initialization in test
  `RB #2815 <https://rbcommons.com/s/twitter/r/2815>`_
  `RB #2850 <https://rbcommons.com/s/twitter/r/2850>`_

0.0.49 (9/21/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This is a hotfix release that includes a fix for resolving remote go libraries
that use relative imports.

Bugfixes
~~~~~~~~

* Include resolved jar versions in compile fingerprints; ensure coordinates match artifacts.
  `RB #2853 <https://rbcommons.com/s/twitter/r/2853>`_

* Fixup GoFetch to handle relative imports.
  `RB #2854 <https://rbcommons.com/s/twitter/r/2854>`_

New Features
~~~~~~~~~~~~

* Enhancements to the dep-usage goal
  `RB #2851 <https://rbcommons.com/s/twitter/r/2851>`_

0.0.48 (9/18/2015)
------------------

Release Notes
~~~~~~~~~~~~~

There is a new UI in the `./pants server` web interface that shows 'Timing Stats' graphs.  These
graphs show where time is spent on a daily-aggregation basis in various tasks.  You can drill down
into a task to see which sub-steps are most expensive.  Try it out!

We also have a few new metadata goals to help figure out what's going on with file ownership and
options.

If you want to find out where options are coming from, the `options` goal can help you out::

    $ ./pants -q options --only-overridden --scope=compile
    compile.apt.jvm_options = ['-Xmx1g', '-XX:MaxPermSize=256m'] (from CONFIG in pants.ini)
    compile.java.jvm_options = ['-Xmx2G'] (from CONFIG in pants.ini)
    compile.java.partition_size_hint = 1000000000 (from CONFIG in pants.ini)
    compile.zinc.jvm_options = ['-Xmx2g', '-XX:MaxPermSize=256m', '-Dzinc.analysis.cache.limit=0'] (from CONFIG in pants.ini)

If you're not sure which target(s) own a given file::

    $ ./pants -q list-owners -- src/python/pants/base/target.py
    src/python/pants/build_graph

The latter comes from new contributor Tansy Arron-Walker.

API Changes
~~~~~~~~~~~

* Kill 'ivy_jar_products'.
  `RB #2823 <https://rbcommons.com/s/twitter/r/2823>`_

* Kill 'ivy_resolve_symlink_map' and 'ivy_cache_dir' products.
  `RB #2819 <https://rbcommons.com/s/twitter/r/2819>`_

Bugfixes
~~~~~~~~

* Upgrade to jarjar 1.5.2.
  `RB #2847 <https://rbcommons.com/s/twitter/r/2847>`_

* Don't modify globs excludes argument value.
  `RB #2841 <https://rbcommons.com/s/twitter/r/2841>`_

* Whitelist the appropriate filter option name for zinc
  `RB #2839 <https://rbcommons.com/s/twitter/r/2839>`_

* Ensure stale classes are removed during isolated compile by cleaning classes directory prior to handling invalid targets
  `RB #2805 <https://rbcommons.com/s/twitter/r/2805>`_

* Fix `linecount` estimator for `dep-usage` goal
  `RB #2828 <https://rbcommons.com/s/twitter/r/2828>`_

* Fix resource handling for the python backend.
  `RB #2817 <https://rbcommons.com/s/twitter/r/2817>`_

* Fix coordinates of resolved jars in IvyInfo.
  `RB #2818 <https://rbcommons.com/s/twitter/r/2818>`_

* Fix `NailgunExecutor` to support more than one connect attempt
  `RB #2822 <https://rbcommons.com/s/twitter/r/2822>`_

* Fixup AndroidIntegrationTest broken by Distribution refactor.
  `RB #2811 <https://rbcommons.com/s/twitter/r/2811>`_

* Backport sbt java output fixes into zinc
  `RB #2810 <https://rbcommons.com/s/twitter/r/2810>`_

* Align ivy excludes and ClasspathProducts excludes.
  `RB #2807 <https://rbcommons.com/s/twitter/r/2807>`_

New Features
~~~~~~~~~~~~

* A nice timing stats report.
  `RB #2825 <https://rbcommons.com/s/twitter/r/2825>`_

* Add new console task ListOwners to determine the targets that own a source
  `RB #2755 <https://rbcommons.com/s/twitter/r/2755>`_

* Adding a console task to explain where options came from.
  `RB #2816 <https://rbcommons.com/s/twitter/r/2816>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Deprecate 'Repository' alias in favor of 'repo'.
  `RB #2845 <https://rbcommons.com/s/twitter/r/2845>`_

* Fix indents (checkstyle)
  `RB #2844 <https://rbcommons.com/s/twitter/r/2844>`_

* Use list comprehension in jvm_compile to calculate valid targets
  `RB #2843 <https://rbcommons.com/s/twitter/r/2843>`_

* Transition `IvyImports` to 'compile_classpath'.
  `RB #2840 <https://rbcommons.com/s/twitter/r/2840>`_

* Migrate `JvmBinaryTask` to 'compile_classpath'.
  `RB #2832 <https://rbcommons.com/s/twitter/r/2832>`_

* Add support for snapshotting `ClasspathProducts`.
  `RB #2837 <https://rbcommons.com/s/twitter/r/2837>`_

* Bump to zinc 1.0.11
  `RB #2827 <https://rbcommons.com/s/twitter/r/2827>`_
  `RB #2836 <https://rbcommons.com/s/twitter/r/2836>`_
  `RB #2812 <https://rbcommons.com/s/twitter/r/2812>`_

* Lazily load zinc analysis
  `RB #2827 <https://rbcommons.com/s/twitter/r/2827>`_

* Add support for whitelisting of zinc options
  `RB #2835 <https://rbcommons.com/s/twitter/r/2835>`_

* Kill the unused `JvmTarget.configurations` field.
  `RB #2834 <https://rbcommons.com/s/twitter/r/2834>`_

* Kill 'jvm_build_tools_classpath_callbacks' deps.
  `RB #2831 <https://rbcommons.com/s/twitter/r/2831>`_

* Add `:scalastyle_integration` test to `:integration` test target
  `RB #2830 <https://rbcommons.com/s/twitter/r/2830>`_

* Use fast_relpath in JvmCompileIsolatedStrategy.compute_classes_by_source
  `RB #2826 <https://rbcommons.com/s/twitter/r/2826>`_

* Enable New Style class check
  `RB #2820 <https://rbcommons.com/s/twitter/r/2820>`_

* Remove `--quiet` flag from `pip`
  `RB #2809 <https://rbcommons.com/s/twitter/r/2809>`_

* Move AptCompile to zinc
  `RB #2806 <https://rbcommons.com/s/twitter/r/2806>`_

* Add a just-in-time check of the artifact cache to the isolated compile strategy
  `RB #2690 <https://rbcommons.com/s/twitter/r/2690>`_

0.0.47 (9/11/2015)
------------------

Release Notes
~~~~~~~~~~~~~

By defaulting the versions of most built-in tools, this release makes pants significantly easier to configure! Tools like antlr, jmake, nailgun, etc, will use default classpaths unless override targets are provided.

Additionally, this release adds native support for shading JVM binaries, which helps to isolate them from their deployment environment.

Thanks to all contributors!

API Changes
~~~~~~~~~~~

* Add JVM distributions and platforms to the export format.
  `RB #2784 <https://rbcommons.com/s/twitter/r/2784>`_

* Added Python setup to export goal to consume in the Pants Plugin for IntelliJ.
  `RB #2785 <https://rbcommons.com/s/twitter/r/2785>`_
  `RB #2786 <https://rbcommons.com/s/twitter/r/2786>`_

* Introduce anonymous targets built by macros.
  `RB #2759 <https://rbcommons.com/s/twitter/r/2759>`_

* Upgrade to the re-merged Node.js/io.js as the default.
  `RB #2800 <https://rbcommons.com/s/twitter/r/2800>`_

Bugfixes
~~~~~~~~

* Don't create directory entries in the isolated compile context jar
  `RB #2775 <https://rbcommons.com/s/twitter/r/2775>`_

* Bump jar-tool release version to 0.0.7 to pick up double-slashed directory fixes
  `RB #2763 <https://rbcommons.com/s/twitter/r/2763>`_
  `RB #2779 <https://rbcommons.com/s/twitter/r/2779>`_

* junit_run now parses errors (in addition to failures) to correctly set failing target
  `RB #2782 <https://rbcommons.com/s/twitter/r/2782>`_

* Fix the zinc name-hashing flag for unicode symbols
  `RB #2776 <https://rbcommons.com/s/twitter/r/2776>`_

New Features
~~~~~~~~~~~~

* Support for shading rules for jvm_binary.
  `RB #2754 <https://rbcommons.com/s/twitter/r/2754>`_

* Add support for @fromfile option values.
  `RB #2783 <https://rbcommons.com/s/twitter/r/2783>`_
  `RB #2794 <https://rbcommons.com/s/twitter/r/2794>`_

* --config-override made appendable, to support multiple pants.ini files.
  `RB #2774 <https://rbcommons.com/s/twitter/r/2774>`_

* JVM tools can now carry their own classpath, meaning that most don't need to be configured
  `RB #2778 <https://rbcommons.com/s/twitter/r/2778>`_
  `RB #2795 <https://rbcommons.com/s/twitter/r/2795>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Added migration of --jvm-jdk-paths to --jvm-distributions-paths
  `RB #2677 <https://rbcommons.com/s/twitter/r/2677>`_
  `RB #2781 <https://rbcommons.com/s/twitter/r/2781>`_

* Example of problem with annotation processors that reference external dependencies.
  `RB #2777 <https://rbcommons.com/s/twitter/r/2777>`_

* Replace eval use with a parse_literal util.
  `RB #2787 <https://rbcommons.com/s/twitter/r/2787>`_

* Move Shader from pants.java to the jvm backend.
  `RB #2788 <https://rbcommons.com/s/twitter/r/2788>`_

* Move BuildFileAliases validation to BuildFileAliases.
  `RB #2790 <https://rbcommons.com/s/twitter/r/2790>`_

* Centralize finding target types for an alias.
  `RB #2796 <https://rbcommons.com/s/twitter/r/2796>`_

* Store timing stats in a structured way, instead of as json.
  `RB #2797 <https://rbcommons.com/s/twitter/r/2797>`_

Documentation
~~~~~~~~~~~~~

* Added a step to publish RELEASE HISTORY back to the public website [DOC]
  `RB #2780 <https://rbcommons.com/s/twitter/r/2780>`_

* Fix buildcache doc typos, use err param rather than ignoring it in UnreadableArtifact
  `RB #2801 <https://rbcommons.com/s/twitter/r/2801>`_

0.0.46 (9/4/2015)
-----------------

Release Notes
~~~~~~~~~~~~~

This release includes more support for Node.js!

Support for the environment variables `PANTS_VERBOSE` and `PANTS_BUILD_ROOT` have been removed in
this release.  Instead, use `--level` to turn on debugging in pants.  Pants recursively searches from
the current directory to the root directory until it finds the `pants.ini` file in order to find
the build root.

The `pants()` syntax in BUILD files has been removed (deprecated since 0.0.29).

API Changes
~~~~~~~~~~~

* Kill PANTS_VERBOSE and PANTS_BUILD_ROOT.
  `RB #2760 <https://rbcommons.com/s/twitter/r/2760>`_

* [classpath products] introduce ResolvedJar and M2Coordinate and use them for improved exclude handling
  `RB #2654 <https://rbcommons.com/s/twitter/r/2654>`_

* Kill the `pants()` pointer, per discussion in Slack: https://pantsbuild.slack.com/archives/general/p1440451305004760
  `RB #2650 <https://rbcommons.com/s/twitter/r/2650>`_

* Make Globs classes and Bundle stand on their own.
  `RB #2740 <https://rbcommons.com/s/twitter/r/2740>`_

* Rid all targets of sources_rel_path parameters.
  `RB #2738 <https://rbcommons.com/s/twitter/r/2738>`_

* Collapse SyntheticAddress up into Address. [API]
  `RB #2730 <https://rbcommons.com/s/twitter/r/2730>`_

Bugfixes
~~~~~~~~

* Fix + test 3rd party missing dep for zinc
  `RB #2764 <https://rbcommons.com/s/twitter/r/2764>`_

* Implement a synthetic jar that sets Class-Path to bypass ARG_MAX limit
  `RB #2672 <https://rbcommons.com/s/twitter/r/2672>`_

* Fixed changed goal for BUILD files in build root
  `RB #2749 <https://rbcommons.com/s/twitter/r/2749>`_

* Refactor / bug-fix for checking jars during dep check
  `RB #2739 <https://rbcommons.com/s/twitter/r/2739>`_

* PytestRun test failures parsing is broken for tests in a class
  `RB #2714 <https://rbcommons.com/s/twitter/r/2714>`_

* Make nailgun_client error when the client socket is closed.
  `RB #2727 <https://rbcommons.com/s/twitter/r/2727>`_

New Features
~~~~~~~~~~~~

* Initial support for `resolve.npm`.
  `RB #2723 <https://rbcommons.com/s/twitter/r/2723>`_

* Add support for `repl.node`.
  `RB #2766 <https://rbcommons.com/s/twitter/r/2766>`_

* Setup the node contrib for release.
  `RB #2768 <https://rbcommons.com/s/twitter/r/2768>`_

* Add annotation processor settings to goal idea
  `RB #2753 <https://rbcommons.com/s/twitter/r/2753>`_

* Introduce job prioritization to ExecutionGraph
  `RB #2601 <https://rbcommons.com/s/twitter/r/2601>`_

* Provide include paths to thrift-linter to allow for more complex checks
  `RB #2712 <https://rbcommons.com/s/twitter/r/2712>`_

* JVM dependency usage task
  `RB #2757 <https://rbcommons.com/s/twitter/r/2757>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Re-work REPL mutual exclusion.
  `RB #2765 <https://rbcommons.com/s/twitter/r/2765>`_

* Return cached_chroots instead of yielding them.
  `RB #2762 <https://rbcommons.com/s/twitter/r/2762>`_

* Normalize and decompose GoalRunner initialization and setup
  `RB #2715 <https://rbcommons.com/s/twitter/r/2715>`_

* Fixed pre-commit hook for CI
  `RB #2758 <https://rbcommons.com/s/twitter/r/2758>`_

* Code added check valid arguments for glob, test added as well
  `RB #2750 <https://rbcommons.com/s/twitter/r/2750>`_

* Fix newline style nits and enable newline check in pants.ini
  `RB #2756 <https://rbcommons.com/s/twitter/r/2756>`_

* Add the class name and scope name to the uninitialized subsystem error message
  `RB #2698 <https://rbcommons.com/s/twitter/r/2698>`_

* Make nailgun killing faster.
  `RB #2685 <https://rbcommons.com/s/twitter/r/2685>`_

* Switch JVM missing dep detection to use compile_classpath
  `RB #2729 <https://rbcommons.com/s/twitter/r/2729>`_

* Add transitive flag to ClasspathProduct.get_for_target[s]
  `RB #2744 <https://rbcommons.com/s/twitter/r/2744>`_

* Add transitive parameter to UnionProducts.get_for_target[s]
  `RB #2741 <https://rbcommons.com/s/twitter/r/2741>`_

* Tighten up the node target hierarchy.
  `RB #2736 <https://rbcommons.com/s/twitter/r/2736>`_

* Ensure pipeline failuires fail CI.
  `RB #2731 <https://rbcommons.com/s/twitter/r/2731>`_

* Record the BUILD target alias in BuildFileAddress.
  `RB #2726 <https://rbcommons.com/s/twitter/r/2726>`_

* Use BaseCompileIT to double-check missing dep failure and whitelist success.
  `RB #2732 <https://rbcommons.com/s/twitter/r/2732>`_

* Use Target.subsystems to expose UnknownArguments.
  `RB #2725 <https://rbcommons.com/s/twitter/r/2725>`_

* Populate classes_by_target using the context jar for the isolated strategy
  `RB #2720 <https://rbcommons.com/s/twitter/r/2720>`_

* Push OSX CI's over to pantsbuild-osx.
  `RB #2724 <https://rbcommons.com/s/twitter/r/2724>`_

Documentation
~~~~~~~~~~~~~

* Update a few references to options moved to the jvm subsystem in docs and comments
  `RB #2751 <https://rbcommons.com/s/twitter/r/2751>`_

* Update developer docs mention new testing idioms
  `RB #2743 <https://rbcommons.com/s/twitter/r/2743>`_

* Clarify the RBCommons/pants-reviews setup step.
  `RB #2733 <https://rbcommons.com/s/twitter/r/2733>`_

0.0.45 (8/28/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

In this release, the methods `with_sources()`, `with_docs()` and `with_artifact()`
were removed from the jar() syntax in BUILD files.   They have been deprecated since
Pants version 0.0.29.

API Changes
~~~~~~~~~~~

* Remove with_artifact(), with_sources(), and with_docs() from JarDependency
  `RB #2687 <https://rbcommons.com/s/twitter/r/2687>`_

Bugfixes
~~~~~~~~

* Upgrade zincutils to 0.3.1 for parse_deps bug fix
  `RB #2705 <https://rbcommons.com/s/twitter/r/2705>`_

* Fix PythonThriftBuilder to operate on 1 target.
  `RB #2696 <https://rbcommons.com/s/twitter/r/2696>`_

* Ensure stdlib check uses normalized paths.
  `RB #2693 <https://rbcommons.com/s/twitter/r/2693>`_

* Hack around a few Distribution issues in py tests.
  `RB #2692 <https://rbcommons.com/s/twitter/r/2692>`_

* Fix GoBuildgen classname and a comment typo.
  `RB #2689 <https://rbcommons.com/s/twitter/r/2689>`_

* Making --coverage-open work for cobertura.
  `RB #2670 <https://rbcommons.com/s/twitter/r/2670>`_

New Features
~~~~~~~~~~~~

* Implementing support for Wire 2.0 multiple proto paths.
  `RB #2717 <https://rbcommons.com/s/twitter/r/2717>`_

* [pantsd] PantsService, FSEventService & WatchmanLauncher
  `RB #2686 <https://rbcommons.com/s/twitter/r/2686>`_

* Add NodeDistribution to seed a node backend.
  `RB #2703 <https://rbcommons.com/s/twitter/r/2703>`_

* Created DistributionLocator subsystem with jvm-distributions option-space.
  `RB #2677 <https://rbcommons.com/s/twitter/r/2677>`_

* Added support for wire 2.0 arguments and beefed up tests
  `RB #2688 <https://rbcommons.com/s/twitter/r/2688>`_

* Initial commit of checkstyle
  `RB #2593 <https://rbcommons.com/s/twitter/r/2593>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Removed scan workunit; mapping workunits now debug
  `RB #2721 <https://rbcommons.com/s/twitter/r/2721>`_

* Implement caching for the thrift linter.
  `RB #2718 <https://rbcommons.com/s/twitter/r/2718>`_

* Refactor JvmDependencyAnalyzer into a task
  `RB #2668 <https://rbcommons.com/s/twitter/r/2668>`_

* Refactor plugin system to allow for easier extension by others
  `RB #2706 <https://rbcommons.com/s/twitter/r/2706>`_

* Indented code which prints warnings for unrecognized os's.
  `RB #2713 <https://rbcommons.com/s/twitter/r/2713>`_

* Fixup existing docs and add missing docs.
  `RB #2708 <https://rbcommons.com/s/twitter/r/2708>`_

* Requiring explicit dependency on the DistributionLocator subsystem.
  `RB #2707 <https://rbcommons.com/s/twitter/r/2707>`_

* Reorganize option help.
  `RB #2695 <https://rbcommons.com/s/twitter/r/2695>`_

* Set 'pants-reviews' as the default group.
  `RB #2702 <https://rbcommons.com/s/twitter/r/2702>`_

* Update to zinc 1.0.9 and sbt 0.13.9
  `RB #2658 <https://rbcommons.com/s/twitter/r/2658>`_

* Test the individual style checks and only disable the check that is currently failing CI
  `RB #2697 <https://rbcommons.com/s/twitter/r/2697>`_

0.0.44 (8/21/2015)
------------------

Release Notes
~~~~~~~~~~~~~

In this release Go support should be considered beta.  Most features you'd expect are implemented
including a `buildgen.go` task that can maintain your Go BUILD files as inferred from just
`go_binary` target definitions.  Yet to come is `doc` goal integration and an option to wire
in-memory `buildgen.go` as an implicit bootstrap task in any pants run that includes Go targets.

Also in this release is improved control over the tools pants uses, in particular JVM selection
control.

API Changes
~~~~~~~~~~~

* Remove deprecated `[compile.java]` options.
  `RB #2678 <https://rbcommons.com/s/twitter/r/2678>`_

Bugfixes
~~~~~~~~

* Better caching for Python interpreters and requirements.
  `RB #2679 <https://rbcommons.com/s/twitter/r/2679>`_

* Fixup use of removed flag `compile.java --target` in integration tests.
  `RB #2680 <https://rbcommons.com/s/twitter/r/2680>`_

* Add support for fetching Go test deps.
  `RB #2671 <https://rbcommons.com/s/twitter/r/2671>`_

New Features
~~~~~~~~~~~~

* Integrate Go with the binary goal.
  `RB #2681 <https://rbcommons.com/s/twitter/r/2681>`_

* Initial support for Go BUILD gen.
  `RB #2676 <https://rbcommons.com/s/twitter/r/2676>`_

* Adding jdk_paths option to jvm subsystem.
  `RB #2657 <https://rbcommons.com/s/twitter/r/2657>`_

* Allow specification of kwargs that are not currently known.
  `RB #2662 <https://rbcommons.com/s/twitter/r/2662>`_

* Allow os name map in binary_util to be configured externally
  `RB #2663 <https://rbcommons.com/s/twitter/r/2663>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [pantsd] Watchman & StreamableWatchmanClient
  `RB #2649 <https://rbcommons.com/s/twitter/r/2649>`_

* Upgrade the default Go distribution to 1.5.
  `RB #2669 <https://rbcommons.com/s/twitter/r/2669>`_

* Align JmakeCompile error messages with reality.
  `RB #2682 <https://rbcommons.com/s/twitter/r/2682>`_

* Fixing BUILD files which had integration tests running in :all.
  `RB #2664 <https://rbcommons.com/s/twitter/r/2664>`_

* Remove log options from the zinc Setup to fix performance issue
  `RB #2666 <https://rbcommons.com/s/twitter/r/2666>`_

0.0.43 (8/19/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This release makes the isolated jvm compile strategy viable out-of-the-box for use with large
dependency graphs. Without it, `test.junit` and `run.jvm` performance slows down significantly
due to the large number of loose classfile directories.

Please try it out in your repo by grabbing a copy of `pants.ini.isolated
<https://github.com/pantsbuild/pants/blob/master/pants.ini.isolated>`_ and using a command like::

    ./pants --config-override=pants.ini.isolated test examples/{src,tests}/{scala,java}/::

You'll like the results.  Just update your own `pants.ini` with the pants.ini.isolated settings to
use it by default!

In the medium term, we're interested in making the isolated strategy the default jvm compilation
strategy, so your assistance and feedback is appreciated!

Special thanks to Stu Hood and Nick Howard for lots of work over the past months to get this point.

API Changes
~~~~~~~~~~~

* A uniform way of expressing Task and Subsystem dependencies.
  `Issue #1957 <https://github.com/pantsbuild/pants/issues/1957>`_
  `RB #2653 <https://rbcommons.com/s/twitter/r/2653>`_

* Remove some coverage-related options from test.junit.
  `RB #2639 <https://rbcommons.com/s/twitter/r/2639>`_

* Bump mock and six 3rdparty versions to latest
  `RB #2633 <https://rbcommons.com/s/twitter/r/2633>`_

* Re-implement suppression of output from compiler workunits
  `RB #2590 <https://rbcommons.com/s/twitter/r/2590>`_

Bugfixes
~~~~~~~~

* Improved go remote library support.
  `RB #2655 <https://rbcommons.com/s/twitter/r/2655>`_

* Shorten isolation generated jar paths
  `RB #2647 <https://rbcommons.com/s/twitter/r/2647>`_

* Fix duplicate login options when publishing.
  `RB #2560 <https://rbcommons.com/s/twitter/r/2560>`_

* Fixed no attribute exception in changed goal.
  `RB #2645 <https://rbcommons.com/s/twitter/r/2645>`_

* Fix goal idea issues with mistakenly identifying a test folder as regular code, missing resources
  folders, and resources folders overriding code folders.
  `RB #2046 <https://rbcommons.com/s/twitter/r/2046>`_
  `RB #2642 <https://rbcommons.com/s/twitter/r/2642>`_

New Features
~~~~~~~~~~~~

* Support for running junit tests with different jvm versions.
  `RB #2651 <https://rbcommons.com/s/twitter/r/2651>`_

* Add support for jar'ing compile outputs in the isolated strategy.
  `RB #2643 <https://rbcommons.com/s/twitter/r/2643>`_

* Tests for 'java-resoures' and 'java-test-resources' in idea
  `RB #2046 <https://rbcommons.com/s/twitter/r/2046>`_
  `RB #2634 <https://rbcommons.com/s/twitter/r/2634>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Filter zinc compilation warnings at the Reporter level
  `RB #2656 <https://rbcommons.com/s/twitter/r/2656>`_

* Update to sbt 0.13.9.
  `RB #2629 <https://rbcommons.com/s/twitter/r/2629>`_

* Speeding up jvm-platform-validate step.
  `Issue #1972 <https://github.com/pantsbuild/pants/issues/1972>`_
  `RB #2626 <https://rbcommons.com/s/twitter/r/2626>`_

* Added test that failed HTTP responses do not raise exceptions in artifact cache
  `RB #2624 <https://rbcommons.com/s/twitter/r/2624>`_
  `RB #2644 <https://rbcommons.com/s/twitter/r/2644>`_

* Tweak to option default extraction for help display.
  `RB #2640 <https://rbcommons.com/s/twitter/r/2640>`_

* A few small install doc fixes.
  `RB #2638 <https://rbcommons.com/s/twitter/r/2638>`_

* Detect new package when doing ownership checks.
  `RB #2637 <https://rbcommons.com/s/twitter/r/2637>`_

* Use os.path.realpath on test tmp dirs to appease OSX.
  `RB #2635 <https://rbcommons.com/s/twitter/r/2635>`_

* Update the pants install documentation. #docfixit
  `RB #2631 <https://rbcommons.com/s/twitter/r/2631>`_

0.0.42 (8/14/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This was #docfixit week, so the release contains more doc and help improvements than usual.
Thanks in particular to Benjy for continued `./pants help` polish!

This release also add support for golang in the `contrib/go` package. Thanks to Cody Gibb and
John Sirois for that work.

API Changes
~~~~~~~~~~~

* Elevate the pants version to a first class option
  `RB #2627 <https://rbcommons.com/s/twitter/r/2627>`_

* Support pants plugin resolution for easier inclusion of published plugins
  `RB #2615 <https://rbcommons.com/s/twitter/r/2615>`_
  `RB #2622 <https://rbcommons.com/s/twitter/r/2622>`_

* Pin pex==1.0.3, alpha-sort & remove line breaks
  `RB #2598 <https://rbcommons.com/s/twitter/r/2598>`_
  `RB #2596 <https://rbcommons.com/s/twitter/r/2596>`_

* Moved classifier from IvyArtifact to IvyModuleRef
  `RB #2579 <https://rbcommons.com/s/twitter/r/2579>`_

Bugfixes
~~~~~~~~

* Ignore 'NonfatalArtifactCacheError' when calling the artifact cache in the background
  `RB #2624 <https://rbcommons.com/s/twitter/r/2624>`_

* Re-Add debug option to benchmark run task, complain on no jvm targets, add test
  `RB #2619 <https://rbcommons.com/s/twitter/r/2619>`_

* Fixed what_changed for removed files
  `RB #2589 <https://rbcommons.com/s/twitter/r/2589>`_

* Disable jvm-platform-analysis by default
  `Issue #1972 <https://github.com/pantsbuild/pants/issues/1972>`_
  `RB #2618 <https://rbcommons.com/s/twitter/r/2618>`_

* Fix ./pants help_advanced
  `RB #2616 <https://rbcommons.com/s/twitter/r/2616>`_

* Fix some more missing globs in build-file-rev mode.
  `RB #2591 <https://rbcommons.com/s/twitter/r/2591>`_

* Make jvm bundles output globs in filedeps with --globs.
  `RB #2583 <https://rbcommons.com/s/twitter/r/2583>`_

* Fix more realpath issues
  `Issue #1933 <https://github.com/pantsbuild/pants/issues/1933>`_
  `RB #2582 <https://rbcommons.com/s/twitter/r/2582>`_

New Features
~~~~~~~~~~~~

* Allow plaintext-reporter to be able to respect a task's --level and --colors options.
  `RB #2580 <https://rbcommons.com/s/twitter/r/2580>`_
  `RB #2614 <https://rbcommons.com/s/twitter/r/2614>`_

* contrib/go: Support for Go
  `RB #2544 <https://rbcommons.com/s/twitter/r/2544>`_

* contrib/go: Setup a release sdist
  `RB #2609 <https://rbcommons.com/s/twitter/r/2609>`_

* contrib/go: Remote library support
  `RB #2611 <https://rbcommons.com/s/twitter/r/2611>`_
  `RB #2623 <https://rbcommons.com/s/twitter/r/2623>`_

* contrib/go: Introduce GoDistribution
  `RB #2595 <https://rbcommons.com/s/twitter/r/2595>`_

* contrib/go: Integrate GoDistribution with GoTask
  `RB #2600 <https://rbcommons.com/s/twitter/r/2600>`_

* Add support for android compilation with contrib/scrooge
  `RB #2553 <https://rbcommons.com/s/twitter/r/2553>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Added more testimonials to the Powered By page. #docfixit
  `RB #2625 <https://rbcommons.com/s/twitter/r/2625>`_

* Fingerprint more task options; particularly scalastyle configs
  `RB #2628 <https://rbcommons.com/s/twitter/r/2628>`_

* Fingerprint jvm tools task options by default
  `RB #2620 <https://rbcommons.com/s/twitter/r/2620>`_

* Make most compile-related options advanced. #docfixit
  `RB #2617 <https://rbcommons.com/s/twitter/r/2617>`_

* Make almost all global options advanced. #docfixit
  `RB #2602 <https://rbcommons.com/s/twitter/r/2602>`_

* Improve cmd-line help output. #docfixit
  `RB #2599 <https://rbcommons.com/s/twitter/r/2599>`_

* Default `-Dscala.usejavacp=true` for ScalaRepl.
  `RB #2613 <https://rbcommons.com/s/twitter/r/2613>`_

* Additional Option details for the Task developers guide. #docfixit
  `RB #2594 <https://rbcommons.com/s/twitter/r/2594>`_
  `RB #2612 <https://rbcommons.com/s/twitter/r/2612>`_

* Improve subsystem testing support in subsystem_util.
  `RB #2603 <https://rbcommons.com/s/twitter/r/2603>`_

* Cleanups to the tasks developer's guide #docfixit
  `RB #2594 <https://rbcommons.com/s/twitter/r/2594>`_

* Add the optionable class to ScopeInfo. #docfixit
  `RB #2588 <https://rbcommons.com/s/twitter/r/2588>`_

* Add `pants_plugin` and `contrib_plugin` targets.
  `RB #2615 <https://rbcommons.com/s/twitter/r/2615>`_

0.0.41 (8/7/2015)
-----------------

Release Notes
~~~~~~~~~~~~~

Configuration for specifying scala/java compilation using zinc has
changed in this release.

You may need to combine `[compile.zinc-java]` and `[compile.scala]`
into the new section `[compile.zinc]`

The `migrate_config` tool will help you migrate your pants.ini settings
for this new release.  Download the pants source code and run:

.. code::

  ./pants run migrations/options/src/python:migrate_config --  <path to your pants.ini>


API Changes
~~~~~~~~~~~

* Upgrade pex to 1.0.2.
  `RB #2571 <https://rbcommons.com/s/twitter/r/2571>`_


Bugfixes
~~~~~~~~

* Fix ApacheThriftGen chroot normalization scope.
  `RB #2568 <https://rbcommons.com/s/twitter/r/2568>`_

* Fix crasher when no jvm_options are set
  `RB #2578 <https://rbcommons.com/s/twitter/r/2578>`_

* Handle recursive globs with build-file-rev
  `RB #2572 <https://rbcommons.com/s/twitter/r/2572>`_

* Fixup PythonTask chroot caching.
  `RB #2567 <https://rbcommons.com/s/twitter/r/2567>`_

New Features
~~~~~~~~~~~~

* Add "omnivorous" ZincCompile to consume both java and scala sources
  `RB #2561 <https://rbcommons.com/s/twitter/r/2561>`_


Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Do fewer classpath calculations in `junit_run`.
  `RB #2576 <https://rbcommons.com/s/twitter/r/2576>`_

* fix misc ws issues
  `RB #2564 <https://rbcommons.com/s/twitter/r/2564>`_
  `RB #2557 <https://rbcommons.com/s/twitter/r/2557>`_

* Resurrect the --[no-]lock global flag
  `RB #2563 <https://rbcommons.com/s/twitter/r/2563>`_

* Avoid caching volatile ~/.cache/pants/stats dir.
  `RB #2574 <https://rbcommons.com/s/twitter/r/2574>`_

* remove unused imports
  `RB #2556 <https://rbcommons.com/s/twitter/r/2556>`_

* Moved logic which validates jvm platform dependencies.
  `RB #2565 <https://rbcommons.com/s/twitter/r/2565>`_

* Bypass the pip cache when testing released sdists.
  `RB #2555 <https://rbcommons.com/s/twitter/r/2555>`_

* Add an affordance for 1 flag implying another.
  `RB #2562 <https://rbcommons.com/s/twitter/r/2562>`_

* Make artifact cache `max-entries-per-target` option name match its behaviour
  `RB #2550 <https://rbcommons.com/s/twitter/r/2550>`_

* Improve stats upload.
  `RB #2554 <https://rbcommons.com/s/twitter/r/2554>`_


0.0.40 (7/31/2015)
-------------------

Release Notes
~~~~~~~~~~~~~

The apache thrift gen for java code now runs in `-strict` mode by default, requiring
all struct fields declare a field id.  You can use the following configuration in
pants.ini to retain the old default behavior and turn strict checking off:

.. code::

  [gen.thrift]
  strict: False

The psutil dependency used by pants has been upgraded to 3.1.1. Supporting eggs have been uploaded
to https://github.com/pantsbuild/cheeseshop/tree/gh-pages/third_party/python/dist. *Please note*
that beyond this update, no further binary dependency updates will be provided at this location.

API Changes
~~~~~~~~~~~

* Integrate the Android SDK, android-library
  `RB #2528 <https://rbcommons.com/s/twitter/r/2528>`_

Bugfixes
~~~~~~~~

* Guard against NoSuchProcess in the public API.
  `RB #2551 <https://rbcommons.com/s/twitter/r/2551>`_

* Fixup psutil.Process attribute accesses.
  `RB #2549 <https://rbcommons.com/s/twitter/r/2549>`_

* Removes type=Option.list from --compile-jvm-args option and --compile-scala-plugins
  `RB #2536 <https://rbcommons.com/s/twitter/r/2536>`_
  `RB #2547 <https://rbcommons.com/s/twitter/r/2547>`_

* Prevent nailgun on nailgun violence when using symlinked java paths
  `RB #2538 <https://rbcommons.com/s/twitter/r/2538>`_

* Declaring product_types for simple_codegen_task.
  `RB #2540 <https://rbcommons.com/s/twitter/r/2540>`_

* Fix straggler usage of legacy psutil form
  `RB #2546 <https://rbcommons.com/s/twitter/r/2546>`_

New Features
~~~~~~~~~~~~

* Added JvmPlatform subsystem and added platform arg to JvmTarget.
  `RB #2494 <https://rbcommons.com/s/twitter/r/2494>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Resolve targets before creating PayloadField
  `RB #2496 <https://rbcommons.com/s/twitter/r/2496>`_
  `RB #2536 <https://rbcommons.com/s/twitter/r/2536>`_

* Upgrade psutil to 3.1.1
  `RB #2543 <https://rbcommons.com/s/twitter/r/2543>`_

* Move thrift utils only used by scrooge to contrib/scrooge.
  `RB #2535 <https://rbcommons.com/s/twitter/r/2535>`_

* docs: add link to slackin self-invite
  `RB #2537 <https://rbcommons.com/s/twitter/r/2537>`_

* Add Clover Health to the Powered By page
  `RB #2539 <https://rbcommons.com/s/twitter/r/2539>`_

* Add Powered By page
  `RB #2532 <https://rbcommons.com/s/twitter/r/2532>`_

* Create test for java_antlr_library
  `RB #2504 <https://rbcommons.com/s/twitter/r/2504>`_

* Migrate ApacheThriftGen to SimpleCodegenTask.
  `RB #2534 <https://rbcommons.com/s/twitter/r/2534>`_

* Covert RagelGen to SimpleCodeGen.
  `RB #2531 <https://rbcommons.com/s/twitter/r/2531>`_

* Shade the Checkstyle task tool jar.
  `RB #2533 <https://rbcommons.com/s/twitter/r/2533>`_

* Support eggs for setuptools and wheel.
  `RB #2529 <https://rbcommons.com/s/twitter/r/2529>`_

0.0.39 (7/23/2015)
------------------

API Changes
~~~~~~~~~~~

* Disallow jar_library targets without jars
  `RB #2519 <https://rbcommons.com/s/twitter/r/2519>`_

Bugfixes
~~~~~~~~

* Fixup PythonChroot to ignore synthetic targets.
  `RB #2523 <https://rbcommons.com/s/twitter/r/2523>`_

* Exclude provides clauses regardless of soft_excludes
  `RB #2524 <https://rbcommons.com/s/twitter/r/2524>`_

* Fixed exclude id when name is None + added a test for excludes by just an org #1857
  `RB #2518 <https://rbcommons.com/s/twitter/r/2518>`_

* Fixup SourceRoot to handle the buildroot.
  `RB #2514 <https://rbcommons.com/s/twitter/r/2514>`_

* Fixup SetupPy handling of exported thrift.
  `RB #2511 <https://rbcommons.com/s/twitter/r/2511>`_

New Features
~~~~~~~~~~~~

* Invalidate tasks based on BinaryUtil.version.
  `RB #2516 <https://rbcommons.com/s/twitter/r/2516>`_

* Remove local cache files
  `Issue #1762 <https://github.com/pantsbuild/pants/issues/1762>`_
  `RB #2506 <https://rbcommons.com/s/twitter/r/2506>`_

* Option to expose intransitive target dependencies for the dependencies goal
  `RB #2503 <https://rbcommons.com/s/twitter/r/2503>`_

* Introduce Subsystem dependencies.
  `RB #2509 <https://rbcommons.com/s/twitter/r/2509>`_
  `RB #2515 <https://rbcommons.com/s/twitter/r/2515>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Increase robustness of ProcessManager.terminate() in the face of zombies.
  `RB #2513 <https://rbcommons.com/s/twitter/r/2513>`_

* A global isort fix.
  `RB #2510 <https://rbcommons.com/s/twitter/r/2510>`_

0.0.38 (7/21/2015)
------------------

Release Notes
~~~~~~~~~~~~~

A quick hotfix release to pick up a fix related to incorrectly specified scala targets.

API Changes
~~~~~~~~~~~

* Remove the with_description method from target.
  `RB #2507 <https://rbcommons.com/s/twitter/r/2507>`_

Bugfixes
~~~~~~~~

* Handle the case where there are no classes for a target.
  `RB #2489 <https://rbcommons.com/s/twitter/r/2489>`_

New Features
~~~~~~~~~~~~

None.

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Refactor AntlrGen to use SimpleCodeGen.
  `RB #2487 <https://rbcommons.com/s/twitter/r/2487>`_

0.0.37 (7/20/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This is the regularly scheduled release for 7/17/2015 (slightly behind schedule!)

API Changes
~~~~~~~~~~~

* Unified support for process management, to prepare for a new daemon.
  `RB #2490 <https://rbcommons.com/s/twitter/r/2490>`_

* An iterator over Option registration args.
  `RB #2478 <https://rbcommons.com/s/twitter/r/2478>`_

* An iterator over OptionValueContainer keys.
  `RB #2472 <https://rbcommons.com/s/twitter/r/2472>`_

Bugfixes
~~~~~~~~

* Correctly classify files as resources or classes
  `RB #2488 <https://rbcommons.com/s/twitter/r/2488>`_

* Fix test bugs introduced during the target cache refactor.
  `RB #2483 <https://rbcommons.com/s/twitter/r/2483>`_

* Don't explicitly enumerate goal scopes: makes life easier for the IntelliJ pants plugin.
  `RB #2500 <https://rbcommons.com/s/twitter/r/2500>`_

New Features
~~~~~~~~~~~~

* Switch almost all python tasks over to use cached chroots.
  `RB #2486 <https://rbcommons.com/s/twitter/r/2486>`_

* Add invalidation report flag to reporting subsystem.
  `RB #2448 <https://rbcommons.com/s/twitter/r/2448>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add a note about the pantsbuild slack team.
  `RB #2491 <https://rbcommons.com/s/twitter/r/2491>`_

* Upgrade pantsbuild/pants to apache thrift 0.9.2.
  `RB #2484 <https://rbcommons.com/s/twitter/r/2484>`_

* Remove unused --lang option from protobuf_gen.py
  `RB #2485 <https://rbcommons.com/s/twitter/r/2485>`_

* Update release docs to recommend both server-login and pypi sections.
  `RB #2481 <https://rbcommons.com/s/twitter/r/2481>`_

0.0.36 (7/14/2015)
------------------

Release Notes
~~~~~~~~~~~~~

This is a quick release following up on 0.0.35 to make available internal API changes made during options refactoring.

API Changes
~~~~~~~~~~~

* Improved artifact cache usability by allowing tasks to opt-in to a mode that generates and then caches a directory for each target.
  `RB #2449 <https://rbcommons.com/s/twitter/r/2449>`_
  `RB #2471 <https://rbcommons.com/s/twitter/r/2471>`_

* Re-compute the classpath for each batch of junit tests.
  `RB #2454 <https://rbcommons.com/s/twitter/r/2454>`_

Bugfixes
~~~~~~~~

* Stops unit tests in test_simple_codegen_task.py in master from failing.
  `RB #2469 <https://rbcommons.com/s/twitter/r/2469>`_

* Helpful error message when 'sources' is specified for jvm_binary.
  `Issue #871 <https://github.com/pantsbuild/pants/issues/871>`_
  `RB #2455 <https://rbcommons.com/s/twitter/r/2455>`_

* Fix failure in test_execute_fail under python>=2.7.10 for test_simple_codegen_task.py.
  `RB #2461 <https://rbcommons.com/s/twitter/r/2461>`_

New Features
~~~~~~~~~~~~

* Support short-form task subsystem flags.
  `RB #2466 <https://rbcommons.com/s/twitter/r/2466>`_

* Reimplement help formatting to improve clarity of both the code and output.
  `RB #2458 <https://rbcommons.com/s/twitter/r/2458>`_
  `RB #2464 <https://rbcommons.com/s/twitter/r/2464>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Visual docsite changes
  `RB #2463 <https://rbcommons.com/s/twitter/r/2463>`_

* Fix migrate_config to detect explicit [DEFAULT]s.
  `RB #2465 <https://rbcommons.com/s/twitter/r/2465>`_

0.0.35 (7/10/2015)
------------------

Release Notes
~~~~~~~~~~~~~

With this release, if you use the
`isolated jvm compile strategy <https://github.com/pantsbuild/pants/blob/0acdf8d8ab49a0a6bdf5084a99e0c1bca0231cf6/pants.ini.isolated>`_,
java annotation processers that emit java sourcefiles or classfiles will be
handled correctly and the generated code will be bundled appropriately in jars.
In particular, this makes libraries like Google's AutoValue useable in a pants
build. See: `RB #2451 <https://rbcommons.com/s/twitter/r/2451>`_.

API Changes
~~~~~~~~~~~

* Deprecate with_description.
  `RB #2444 <https://rbcommons.com/s/twitter/r/2444>`_

Bugfixes
~~~~~~~~

* Fixup BuildFile must_exist logic.
  `RB #2441 <https://rbcommons.com/s/twitter/r/2441>`_

* Upgrade to pex 1.0.1.
  `Issue #1658 <https://github.com/pantsbuild/pants/issues/1658>`_
  `RB #2438 <https://rbcommons.com/s/twitter/r/2438>`_

New Features
~~~~~~~~~~~~

* Add an option --main to the run.jvm task to override the specification of 'main' on a jvm_binary() target.
  `RB #2442 <https://rbcommons.com/s/twitter/r/2442>`_

* Add jvm_options for thrift-linter.
  `RB #2445 <https://rbcommons.com/s/twitter/r/2445>`_

* Added cwd argument to allow JavaTest targets to require particular working directories.
  `RB #2440 <https://rbcommons.com/s/twitter/r/2440>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Record all output classes for the jvm isolated compile strategy.
  `RB #2451 <https://rbcommons.com/s/twitter/r/2451>`_

* Robustify the pants ivy configuration.
  `Issue #1779 <https://github.com/pantsbuild/pants/issues/1779>`_
  `RB #2450 <https://rbcommons.com/s/twitter/r/2450>`_

* Some refactoring of global options.
  `RB #2446 <https://rbcommons.com/s/twitter/r/2446>`_

* Improved error messaging for unknown Target kwargs.
  `RB #2443 <https://rbcommons.com/s/twitter/r/2443>`_

* Remove Nailgun specific classes from zinc, since pants invokes Main directly.
  `RB #2439 <https://rbcommons.com/s/twitter/r/2439>`_

0.0.34 (7/6/2015)
-----------------

Release Notes
~~~~~~~~~~~~~

Configuration for specifying cache settings and jvm options for some
tools have changed in this release.

The `migrate_config` tool will help you migrate your pants.ini settings
for this new release.  Download the pants source code and run:

.. code::

  ./pants run migrations/options/src/python:migrate_config --  <path
  to your pants.ini>

API Changes
~~~~~~~~~~~

* Added flags for jar sources and javadocs to export goal because Foursquare got rid of ivy goal.
  `RB #2432 <https://rbcommons.com/s/twitter/r/2432>`_

* A JVM subsystem.
  `RB #2423 <https://rbcommons.com/s/twitter/r/2423>`_

* An artifact cache subsystem.
  `RB #2405 <https://rbcommons.com/s/twitter/r/2405>`_

Bugfixes
~~~~~~~~

* Change the xml report to use the fingerprint of the targets, not just their names.
  `RB #2435 <https://rbcommons.com/s/twitter/r/2435>`_

* Using linear-time BFS to sort targets topologically and group them
  by the type.
  `RB #2413 <https://rbcommons.com/s/twitter/r/2413>`_

* Fix isort in git hook context.
  `RB #2430 <https://rbcommons.com/s/twitter/r/2430>`_

* When using soft-excludes, ignore all target defined excludes
  `RB #2340 <https://rbcommons.com/s/twitter/r/2340>`_

* Fix bash-completion goal when run from sdist/pex. Also add tests, and beef up ci.sh & release.sh.
  `RB #2403 <https://rbcommons.com/s/twitter/r/2403>`_

* [junit tool] fix suppress output emits jibberish on console.
  `Issue #1657 <https://github.com/pantsbuild/pants/issues/1657>`_
  `RB #2183 <https://rbcommons.com/s/twitter/r/2183>`_

* In junit-runner, fix an NPE in testFailure() for different scenarios
  `RB #2385 <https://rbcommons.com/s/twitter/r/2385>`_
  `RB #2398 <https://rbcommons.com/s/twitter/r/2398>`_
  `RB #2396 <https://rbcommons.com/s/twitter/r/2396>`_

* Scrub timestamp from antlr generated files to have stable fp for cache
  `RB #2382 <https://rbcommons.com/s/twitter/r/2382>`_

* JVM checkstyle should obey jvm_options
  `RB #2391 <https://rbcommons.com/s/twitter/r/2391>`_

* Fix bad logger.debug call in artifact_cache.py
  `RB #2386 <https://rbcommons.com/s/twitter/r/2386>`_

* Fixed a bug where codegen would crash due to a missing flag.
  `RB #2368 <https://rbcommons.com/s/twitter/r/2368>`_

* Fixup the Git Scm detection of server_url.
  `RB #2379 <https://rbcommons.com/s/twitter/r/2379>`_

* Repair depmap --graph
  `RB #2345 <https://rbcommons.com/s/twitter/r/2345>`_

Documentation
~~~~~~~~~~~~~

* Documented how to enable caching for tasks.
  `RB #2420 <https://rbcommons.com/s/twitter/r/2420>`_

* Remove comments that said these classes returned something.
  `RB #2419 <https://rbcommons.com/s/twitter/r/2419>`_

* Publishing doc fixes
  `RB #2407 <https://rbcommons.com/s/twitter/r/2407>`_

* Bad rst now fails the MarkdownToHtml task.
  `RB #2394 <https://rbcommons.com/s/twitter/r/2394>`_

* Add a CONTRIBUTORS maintenance script.
  `RB #2377 <https://rbcommons.com/s/twitter/r/2377>`_
  `RB #2378 <https://rbcommons.com/s/twitter/r/2378>`_

* typo in the changelog for 0.0.33 release,  fixed formatting of globs and rglobs
  `RB #2376 <https://rbcommons.com/s/twitter/r/2376>`_

* Documentation update for debugging a JVM tool
  `RB #2365 <https://rbcommons.com/s/twitter/r/2365>`_

New Features
~~~~~~~~~~~~
* Add log capture to isolated zinc compiles
  `RB #2404 <https://rbcommons.com/s/twitter/r/2404>`_
  `RB #2415 <https://rbcommons.com/s/twitter/r/2415>`_

* Add support for restricting push remotes.
  `RB #2383 <https://rbcommons.com/s/twitter/r/2383>`_

* Ensure caliper is shaded in bench, add bench desc, use RUN so that output is printed
  `RB #2353 <https://rbcommons.com/s/twitter/r/2353>`_


Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Enhance the error output in simple_codegen_task.py when unable to generate target(s)
  `RB #2427 <https://rbcommons.com/s/twitter/r/2427>`_

* Add a get_rank() method to OptionValueContainer.
  `RB #2431 <https://rbcommons.com/s/twitter/r/2431>`_

* Pass jvm_options to scalastyle
  `RB #2428 <https://rbcommons.com/s/twitter/r/2428>`_

* Kill custom repos and cross-platform pex setup.
  `RB #2402 <https://rbcommons.com/s/twitter/r/2402>`_

* Add debugging for problem with invalidation and using stale report file in ivy resolve.
  `Issue #1747 <https://github.com/pantsbuild/pants/issues/1747>`_
  `RB #2424 <https://rbcommons.com/s/twitter/r/2424>`_

* Enabled caching for scalastyle and checkstyle
  `RB #2416 <https://rbcommons.com/s/twitter/r/2416>`_
  `RB #2414 <https://rbcommons.com/s/twitter/r/2414>`_

* Make sure all Task mixins are on the left.
  `RB #2421 <https://rbcommons.com/s/twitter/r/2421>`_

* Adds a more verbose description of tests when running
  the -per-test-timer command. (Junit)
  `RB #2418 <https://rbcommons.com/s/twitter/r/2418>`_
  `RB #2408 <https://rbcommons.com/s/twitter/r/2408>`_

* Re-add support for reading from a local .m2 directory
  `RB #2409 <https://rbcommons.com/s/twitter/r/2409>`_

* Replace a few references to basestring with six.
  `RB #2410 <https://rbcommons.com/s/twitter/r/2410>`_

* Promote PANTS_DEV=1 to the only ./pants mode.
  `RB #2401 <https://rbcommons.com/s/twitter/r/2401>`_

* Add task meter to protoc step in codegen
  `RB #2392 <https://rbcommons.com/s/twitter/r/2392>`_

* Simplify known scopes computation.
  `RB #2389 <https://rbcommons.com/s/twitter/r/2389>`_

* Robustify the release process.
  `RB #2388 <https://rbcommons.com/s/twitter/r/2388>`_

* A common base class for things that can register options.
  `RB #2387 <https://rbcommons.com/s/twitter/r/2387>`_

* Fixed the error messages in assert_list().
  `RB #2370 <https://rbcommons.com/s/twitter/r/2370>`_

* Simplify subsystem option scoping.
  `RB #2380 <https://rbcommons.com/s/twitter/r/2380>`_

0.0.33 (6/13/2015)
------------------

Release Notes
~~~~~~~~~~~~~

The migrate config tool will help you migrate your pants.ini settings
for this new release.  Download the pants source code and run:

.. code::

  ./pants run migrations/options/src/python:migrate_config --  <path
  to your pants.ini>


Folks who use a custom ivysettings.xml but have no ivy.ivy_settings
option defined in pants.ini pointing to it must now add one like so:

.. code::

  [ivy]
  ivy_settings: %(pants_supportdir)s/ivy/ivysettings.xml

API Changes
~~~~~~~~~~~

* Removed --project-info flag from depmap goal
  `RB #2363 <https://rbcommons.com/s/twitter/r/2363>`_

* Deprecate PytestRun env vars.
  `RB #2299 <https://rbcommons.com/s/twitter/r/2299>`_

* Add Subsystems for options that live outside a single task, use them
  to replace config settings in pants.ini
  `RB #2288 <https://rbcommons.com/s/twitter/r/2288>`_
  `RB #2276 <https://rbcommons.com/s/twitter/r/2276>`_
  `RB #2226 <https://rbcommons.com/s/twitter/r/2226>`_
  `RB #2176 <https://rbcommons.com/s/twitter/r/2176>`_
  `RB #2174 <https://rbcommons.com/s/twitter/r/2174>`_
  `RB #2139 <https://rbcommons.com/s/twitter/r/2139>`_
  `RB #2122 <https://rbcommons.com/s/twitter/r/2122>`_
  `RB #2100 <https://rbcommons.com/s/twitter/r/2100>`_
  `RB #2081 <https://rbcommons.com/s/twitter/r/2081>`_
  `RB #2063 <https://rbcommons.com/s/twitter/r/2063>`_

* Read backend and bootstrap BUILD file settings from options instead of config.
  `RB #2229 <https://rbcommons.com/s/twitter/r/2229>`_

* Migrating internal tools into the pants repo and renaming to org.pantsbuild
  `RB #2278 <https://rbcommons.com/s/twitter/r/2278>`_
  `RB #2211 <https://rbcommons.com/s/twitter/r/2211>`_
  `RB #2207 <https://rbcommons.com/s/twitter/r/2207>`_
  `RB #2205 <https://rbcommons.com/s/twitter/r/2205>`_
  `RB #2186 <https://rbcommons.com/s/twitter/r/2186>`_
  `RB #2195 <https://rbcommons.com/s/twitter/r/2195>`_
  `RB #2193 <https://rbcommons.com/s/twitter/r/2193>`_
  `RB #2192 <https://rbcommons.com/s/twitter/r/2192>`_
  `RB #2191 <https://rbcommons.com/s/twitter/r/2191>`_
  `RB #2191 <https://rbcommons.com/s/twitter/r/2191>`_
  `RB #2137 <https://rbcommons.com/s/twitter/r/2137>`_
  `RB #2071 <https://rbcommons.com/s/twitter/r/2071>`_
  `RB #2043 <https://rbcommons.com/s/twitter/r/2043>`_

* Kill scala specs support.
  `RB #2208 <https://rbcommons.com/s/twitter/r/2208>`_

* Use the default ivysettings.xml provided by ivy.
  `RB #2204 <https://rbcommons.com/s/twitter/r/2204>`_

* Eliminate the globs.__sub__ use in option package.
  `RB #2082 <https://rbcommons.com/s/twitter/r/2082>`_
  `RB #2197 <https://rbcommons.com/s/twitter/r/2197>`_

* Kill obsolete global publish.properties file.
  `RB #994 <https://rbcommons.com/s/twitter/r/994>`_
  `RB #2069 <https://rbcommons.com/s/twitter/r/2069>`_

* Upgrade zinc to latest for perf wins.
  `RB #2355 <https://rbcommons.com/s/twitter/r/2355>`_
  `RB #2194 <https://rbcommons.com/s/twitter/r/2194>`_
  `RB #2168 <https://rbcommons.com/s/twitter/r/2168>`_
  `RB #2154 <https://rbcommons.com/s/twitter/r/2154>`_
  `RB #2154 <https://rbcommons.com/s/twitter/r/2154>`_
  `RB #2149 <https://rbcommons.com/s/twitter/r/2149>`_
  `RB #2125 <https://rbcommons.com/s/twitter/r/2125>`_

* Migrate jar_publish config scope.
  `RB #2175 <https://rbcommons.com/s/twitter/r/2175>`_

* Add a version number to the export format and a page with some documentation.
  `RB #2162 <https://rbcommons.com/s/twitter/r/2162>`_

* Make exclude_target_regexp option recursive
  `RB #2136 <https://rbcommons.com/s/twitter/r/2136>`_

* Kill pantsbuild dependence on maven.twttr.com.
  `RB #2019 <https://rbcommons.com/s/twitter/r/2019>`_

* Fold PythonTestBuilder into the PytestRun task.
  `RB #1993 <https://rbcommons.com/s/twitter/r/1993>`_

Bugfixes
~~~~~~~~

* Fixed errors in how arguments are passed to wire_gen.
  `RB #2354 <https://rbcommons.com/s/twitter/r/2354>`_

* Compute exclude_patterns first when unpacking jars
  `RB #2352 <https://rbcommons.com/s/twitter/r/2352>`_

* Add INDEX.LIST to as a Skip JarRule when creating a fat jar
  `RB #2342 <https://rbcommons.com/s/twitter/r/2342>`_

* wrapped-globs: make rglobs output git-compatible
  `RB #2332 <https://rbcommons.com/s/twitter/r/2332>`_

* Add a coherent error message when scrooge has no sources.
  `RB #2329 <https://rbcommons.com/s/twitter/r/2329>`_

* Only run junit when there are junit_test targets in the graph.
  `RB #2291 <https://rbcommons.com/s/twitter/r/2291>`_

* Fix bootstrap local cache.
  `RB #2336 <https://rbcommons.com/s/twitter/r/2336>`_

* Added a hash to a jar name for a bootstrapped jvm tool
  `RB #2334 <https://rbcommons.com/s/twitter/r/2334>`_

* Raise TaskError to exit non-zero if jar-tool fails
  `RB #2150 <https://rbcommons.com/s/twitter/r/2150>`_

* Fix java zinc isolated compile analysis corruption described github issue #1626
  `RB #2325 <https://rbcommons.com/s/twitter/r/2325>`_

* Upstream analysis fix
  `RB #2312 <https://rbcommons.com/s/twitter/r/2312>`_

* Two changes that affect invalidation and artifact caching.
  `RB #2269 <https://rbcommons.com/s/twitter/r/2269>`_

* Add java_thrift_library fingerprint strategy
  `RB #2265 <https://rbcommons.com/s/twitter/r/2265>`_

* Moved creation of per test data to testStarted method.
  `RB #2257 <https://rbcommons.com/s/twitter/r/2257>`_

* Updated zinc to use sbt 0.13.8 and new java compilers that provide a proper log level with their output.
  `RB #2248 <https://rbcommons.com/s/twitter/r/2248>`_

* Apply excludes consistently across classpaths
  `RB #2247 <https://rbcommons.com/s/twitter/r/2247>`_

* Put all extra classpath elements (e.g., plugins) at the end (scala compile)
  `RB #2210 <https://rbcommons.com/s/twitter/r/2210>`_

* Fix missing import in git.py
  `RB #2202 <https://rbcommons.com/s/twitter/r/2202>`_

* Move a comment to work around a pytest bug.
  `RB #2201 <https://rbcommons.com/s/twitter/r/2201>`_

* More fixes for working with classifiers on jars.
  `Issue #1489 <https://github.com/pantsbuild/pants/issues/1489>`_
  `RB #2163 <https://rbcommons.com/s/twitter/r/2163>`_

* Have ConsoleRunner halt(1) on exit(x)
  `RB #2180 <https://rbcommons.com/s/twitter/r/2180>`_

* Fix scm_build_file in symlinked directories
  `RB #2152 <https://rbcommons.com/s/twitter/r/2152>`_
  `RB #2157 <https://rbcommons.com/s/twitter/r/2157>`_

* Added support for the ivy cache being under a symlink'ed dir
  `RB #2085 <https://rbcommons.com/s/twitter/r/2085>`_
  `RB #2129 <https://rbcommons.com/s/twitter/r/2129>`_
  `RB #2148 <https://rbcommons.com/s/twitter/r/2148>`_

* Make subclasses of ChangedTargetTask respect spec_excludes
  `RB #2146 <https://rbcommons.com/s/twitter/r/2146>`_

* propagate keyboard interrupts from worker threads
  `RB #2143 <https://rbcommons.com/s/twitter/r/2143>`_

* Only add resources to the relevant target
  `RB #2103 <https://rbcommons.com/s/twitter/r/2103>`_
  `RB #2130 <https://rbcommons.com/s/twitter/r/2130>`_

* Cleanup analysis left behind from failed isolation compiles
  `RB #2127 <https://rbcommons.com/s/twitter/r/2127>`_

* test glob operators, fix glob + error
  `RB #2104 <https://rbcommons.com/s/twitter/r/2104>`_

* Wrap lock around nailgun spawning to protect against worker threads racing to spawn servers
  `RB #2102 <https://rbcommons.com/s/twitter/r/2102>`_

* Force some files to be treated as binary.
  `RB #2099 <https://rbcommons.com/s/twitter/r/2099>`_

* Convert JarRule and JarRules to use Payload to help fingerprint its configuration
  `RB #2096 <https://rbcommons.com/s/twitter/r/2096>`_

* Fix `./pants server` output
  `RB #2067 <https://rbcommons.com/s/twitter/r/2067>`_

* Fix issue with isolated strategy and sources owned by multiple targets
  `RB #2061 <https://rbcommons.com/s/twitter/r/2061>`_

* Handle broken resource mapping files (by throwing exceptions).
  `RB #2038 <https://rbcommons.com/s/twitter/r/2038>`_

* Change subproc sigint handler to exit more cleanly
  `RB #2024 <https://rbcommons.com/s/twitter/r/2024>`_

* Include classifier in JarDependency equality / hashing
  `RB #2029 <https://rbcommons.com/s/twitter/r/2029>`_

* Migrating more data to payload fields in jvm_app and jvm_binary targets
  `RB #2011 <https://rbcommons.com/s/twitter/r/2011>`_

* Fix ivy_resolve message: Missing expected ivy output file .../.ivy2/pants/internal-...-default.xml
  `RB #2015 <https://rbcommons.com/s/twitter/r/2015>`_

* Fix ignored invalidation data in ScalaCompile
  `RB #2018 <https://rbcommons.com/s/twitter/r/2018>`_

* Don't specify the jmake depfile if it doesn't exist
  `RB #2009 <https://rbcommons.com/s/twitter/r/2009>`_
  `RB #2012 <https://rbcommons.com/s/twitter/r/2012>`_

* Force java generation on for protobuf_gen, get rid of spurious warning
  `RB #1994 <https://rbcommons.com/s/twitter/r/1994>`_

* Fix typo in ragel-gen entries (migrate-config)
  `RB #1995 <https://rbcommons.com/s/twitter/r/1995>`_

* Fix include dependees options.
  `RB #1760 <https://rbcommons.com/s/twitter/r/1760>`_


Documentation
~~~~~~~~~~~~~

* Be explicit that pants requires python 2.7.x to run.
  `RB #2343 <https://rbcommons.com/s/twitter/r/2343>`_

* Update documentation on how to develop and document a JVM tool used by Pants
  `RB #2318 <https://rbcommons.com/s/twitter/r/2318>`_

* Updates to changelog since 0.0.32 in preparation for next release.
  `RB #2294 <https://rbcommons.com/s/twitter/r/2294>`_

* Document the pantsbuild jvm tool release process.
  `RB #2289 <https://rbcommons.com/s/twitter/r/2289>`_

* Fix publishing docs for new 'publish.jar' syntax
  `RB #2255 <https://rbcommons.com/s/twitter/r/2255>`_

* Example configuration for the isolated strategy.
  `RB #2185 <https://rbcommons.com/s/twitter/r/2185>`_

* doc: uploading timing stats
  `RB #1700 <https://rbcommons.com/s/twitter/r/1700>`_

* Add robots.txt to exclude crawlers from walking a 'staging' test publishing dir
  `RB #2072 <https://rbcommons.com/s/twitter/r/2072>`_

* Add a note indicating that pants bootstrap requires a compiler
  `RB #2057 <https://rbcommons.com/s/twitter/r/2057>`_

* Fix docs to mention automatic excludes.
  `RB #2014 <https://rbcommons.com/s/twitter/r/2014>`_

New Features
~~~~~~~~~~~~

* Add a global --tag option to filter targets based on their tags.
  `RB #2362 <https://rbcommons.com/s/twitter/r/2362/>`_

* Add support for ServiceLoader service providers.
  `RB #2331 <https://rbcommons.com/s/twitter/r/2331>`_

* Implemented isolated code-generation strategy for simple_codegen_task.
  `RB #2322 <https://rbcommons.com/s/twitter/r/2322>`_

* Add options for specifying python cache dirs.
  `RB #2320 <https://rbcommons.com/s/twitter/r/2320>`_

* bash autocompletion support
  `RB #2307 <https://rbcommons.com/s/twitter/r/2307>`_
  `RB #2326 <https://rbcommons.com/s/twitter/r/2326>`_

* Invoke jvm doc tools via java.
  `RB #2313 <https://rbcommons.com/s/twitter/r/2313>`_

* Add -log-filter option to the zinc task
  `RB #2315 <https://rbcommons.com/s/twitter/r/2315>`_

* Adds a product to bundle_create
  `RB #2254 <https://rbcommons.com/s/twitter/r/2254>`_

* Add flag to disable automatic excludes
  `RB #2252 <https://rbcommons.com/s/twitter/r/2252>`_

* Find java distributions in well known locations.
  `RB #2242 <https://rbcommons.com/s/twitter/r/2242>`_

* Added information about excludes to export goal
  `RB #2238 <https://rbcommons.com/s/twitter/r/2238>`_

* In process java compilation in Zinc #1555
  `RB #2206 <https://rbcommons.com/s/twitter/r/2206>`_

* Add support for extra publication metadata.
  `RB #2184 <https://rbcommons.com/s/twitter/r/2184>`_
  `RB #2240 <https://rbcommons.com/s/twitter/r/2240>`_

* Extract the android plugin as an sdist.
  `RB #2249 <https://rbcommons.com/s/twitter/r/2249>`_

* Adds optional output during zinc compilation.
  `RB #2233 <https://rbcommons.com/s/twitter/r/2233>`_

* Jvm Tools release process
  `RB #2292 <https://rbcommons.com/s/twitter/r/2292>`_

* Make it possible to create xml reports and output to console at the same time from ConsoleRunner.
  `RB #2183 <https://rbcommons.com/s/twitter/r/2183>`_

* Adding a product to binary_create so that we can depend on it in an external plugin.
  `RB #2172 <https://rbcommons.com/s/twitter/r/2172>`_

* Publishing to Maven Central
  `RB #2068 <https://rbcommons.com/s/twitter/r/2068>`_
  `RB #2188 <https://rbcommons.com/s/twitter/r/2188>`_

* Provide global option to look up BUILD files in git history
  `RB #2121 <https://rbcommons.com/s/twitter/r/2121>`_
  `RB #2164 <https://rbcommons.com/s/twitter/r/2164>`_

* Compile Java with Zinc
  `RB #2156 <https://rbcommons.com/s/twitter/r/2156>`_

* Add BuildFileManipulator implementation and tests to contrib
  `RB #977 <https://rbcommons.com/s/twitter/r/977>`_

* Add option to suppress printing the changelog during publishing
  `RB #2140 <https://rbcommons.com/s/twitter/r/2140>`_

* Filtering by targets' tags
  `RB #2106 <https://rbcommons.com/s/twitter/r/2106>`_

* Adds the ability to specify explicit fields in MANIFEST.MF in a jvm_binary target.
  `RB #2199 <https://rbcommons.com/s/twitter/r/2199>`_
  `RB #2084 <https://rbcommons.com/s/twitter/r/2084>`_
  `RB #2119 <https://rbcommons.com/s/twitter/r/2119>`_
  `RB #2005 <https://rbcommons.com/s/twitter/r/2005>`_

* Parallelize isolated jvm compile strategy's chunk execution.
  `RB #2109 <https://rbcommons.com/s/twitter/r/2109>`_

* Make test tasks specify which target failed in exception.
  `RB #2090 <https://rbcommons.com/s/twitter/r/2090>`_
  `RB #2113 <https://rbcommons.com/s/twitter/r/2113>`_
  `RB #2112 <https://rbcommons.com/s/twitter/r/2112>`_

* Support glob output in filedeps.
  `RB #2092 <https://rbcommons.com/s/twitter/r/2092>`_

* Export: support export of sources and globs
  `RB #2082 <https://rbcommons.com/s/twitter/r/2082>`_
  `RB #2094 <https://rbcommons.com/s/twitter/r/2094>`_

* Classpath isolation: make ivy resolution locally accurate.
  `RB #2064 <https://rbcommons.com/s/twitter/r/2064>`_

* Add support for a postscript to jar_publish commit messages.
  `RB #2070 <https://rbcommons.com/s/twitter/r/2070>`_

* Add optional support for auto-shading jvm tools.
  `RB #2052 <https://rbcommons.com/s/twitter/r/2052>`_
  `RB #2073 <https://rbcommons.com/s/twitter/r/2073>`_

* Introduce a jvm binary shader.
  `RB #2050 <https://rbcommons.com/s/twitter/r/2050>`_

* Open source the spindle plugin for pants into contrib.
  `RB #2306 <https://rbcommons.com/s/twitter/r/2306>`_
  `RB #2301 <https://rbcommons.com/s/twitter/r/2301>`_
  `RB #2304 <https://rbcommons.com/s/twitter/r/2304>`_
  `RB #2282 <https://rbcommons.com/s/twitter/r/2282>`_
  `RB #2033 <https://rbcommons.com/s/twitter/r/2033>`_

* Implement an exported ownership model.
  `RB #2010 <https://rbcommons.com/s/twitter/r/2010>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Support caching chroots for reuse across pants runs.
  `RB #2349 <https://rbcommons.com/s/twitter/r/2349>`_

* Upgrade RBT to the latest release
  `RB #2360 <https://rbcommons.com/s/twitter/r/2360>`_

* Make sure arg to logRaw and log are only eval'ed once. (zinc)
  `RB #2338 <https://rbcommons.com/s/twitter/r/2338>`_

* Clean up unnecessary code
  `RB #2339 <https://rbcommons.com/s/twitter/r/2339>`_

* Exclude the com.example org from travis ivy cache.
  `RB #2344 <https://rbcommons.com/s/twitter/r/2344>`_

* Avoid ivy cache thrash due to ivydata updates.
  `RB #2333 <https://rbcommons.com/s/twitter/r/2333>`_

* Various refactoring of PythonChroot and related code.
  `RB #2327 <https://rbcommons.com/s/twitter/r/2327>`_

* Have pytest_run create its chroots via its base class.
  `RB #2314 <https://rbcommons.com/s/twitter/r/2314>`_

* Add a set of memoization decorators for functions.
  `RB #2308 <https://rbcommons.com/s/twitter/r/2308>`_
  `RB #2317 <https://rbcommons.com/s/twitter/r/2317>`_

* Allow jvm tool tests to bootstrap from the artifact cache.
  `RB #2311 <https://rbcommons.com/s/twitter/r/2311>`_

* Fixed 'has no attribute' exception + better tests for export goal
  `RB #2305 <https://rbcommons.com/s/twitter/r/2305>`_

* Refactoring ProtobufGen to use SimpleCodeGen.
  `RB #2302 <https://rbcommons.com/s/twitter/r/2302>`_

* Refactoring JaxbGen to use SimpleCodeGen.
  `RB #2303 <https://rbcommons.com/s/twitter/r/2303>`_

* Add pants header to assorted python files
  `RB #2298 <https://rbcommons.com/s/twitter/r/2298>`_

* Remove unused imports from python files
  `RB #2295 <https://rbcommons.com/s/twitter/r/2295>`_

* Integrating Patrick's SimpleCodegenTask base class with WireGen.
  `RB #2274 <https://rbcommons.com/s/twitter/r/2274>`_

* Fix bad log statement in junit_run.py.
  `RB #2290 <https://rbcommons.com/s/twitter/r/2290>`_

* Provide more specific value parsing errors
  `RB #2283 <https://rbcommons.com/s/twitter/r/2283>`_

* Dry up incremental-compiler dep on sbt-interface.
  `RB #2279 <https://rbcommons.com/s/twitter/r/2279>`_

* Use BufferedOutputStream in jar-tool
  `RB #2270 <https://rbcommons.com/s/twitter/r/2270>`_

* Add relative_symlink to dirutil for latest run report
  `RB #2271 <https://rbcommons.com/s/twitter/r/2271>`_

* Shade zinc.
  `RB #2268 <https://rbcommons.com/s/twitter/r/2268>`_

* rm Exception.message calls
  `RB #2245 <https://rbcommons.com/s/twitter/r/2245>`_

* sanity check on generated cobertura xml report
  `RB #2231 <https://rbcommons.com/s/twitter/r/2231>`_

* [pants/jar] Fix a typo
  `RB #2230 <https://rbcommons.com/s/twitter/r/2230>`_

* Convert validation.assert_list isinstance checking to be lazy
  `RB #2228 <https://rbcommons.com/s/twitter/r/2228>`_

* use workunit output for cpp command running
  `RB #2223 <https://rbcommons.com/s/twitter/r/2223>`_

* Remove all global config state.
  `RB #2222 <https://rbcommons.com/s/twitter/r/2222>`_
  `RB #2181 <https://rbncommons.com/s/twitter/r/2181>`_
  `RB #2160 <https://rbcommons.com/s/twitter/r/2160>`_
  `RB #2159 <https://rbcommons.com/s/twitter/r/2159>`_
  `RB #2151 <https://rbcommons.com/s/twitter/r/2151>`_
  `RB #2142 <https://rbcommons.com/s/twitter/r/2142>`_
  `RB #2141 <https://rbcommons.com/s/twitter/r/2141>`_

* Make the version of specs in BUILD.tools match the one in 3rdparty/BUILD.
  `RB #2203 <https://rbcommons.com/s/twitter/r/2203>`_

* Handle warnings in BUILD file context.
  `RB #2198 <https://rbcommons.com/s/twitter/r/2198>`_

* Replace custom softreference cache with a guava cache.  (zinc)
  `RB #2190 <https://rbcommons.com/s/twitter/r/2190>`_

* Establish a source_root for pants scala code.
  `RB #2189 <https://rbcommons.com/s/twitter/r/2189>`_

* Zinc patches to improve roundtrip time
  `RB #2178 <https://rbcommons.com/s/twitter/r/2178>`_

* cache parsed mustache templates as they are requested
  `RB #2171 <https://rbcommons.com/s/twitter/r/2171>`_

* memoize linkify to reduce reporting file stat calls
  `RB #2170 <https://rbcommons.com/s/twitter/r/2170>`_

* Refactor BuildFile and BuildFileAdressMapper
  `RB #2110 <https://rbcommons.com/s/twitter/r/2110>`_

* fix whitespace in workerpool test, rm unused import
  `RB #2144 <https://rbcommons.com/s/twitter/r/2144>`_

* Use jvm-compilers as the parent of isolation workunits instead of 'isolation', add workunits for analysis
  `RB #2134 <https://rbcommons.com/s/twitter/r/2134>`_

* Improve the error message when a tool fails to bootstrap.
  `RB #2135 <https://rbcommons.com/s/twitter/r/2135>`_

* Fix rglobs-to-filespec code.
  `RB #2133 <https://rbcommons.com/s/twitter/r/2133>`_

* Send workunit output to stderr during tests
  `RB #2108 <https://rbcommons.com/s/twitter/r/2108>`_

* Changes to zinc analysis split/merge test data generation:
  `RB #2095 <https://rbcommons.com/s/twitter/r/2095>`_

* Add a dummy workunit to the end of the run to print out a timestamp that includes the time spent in the last task.
  `RB #2054 <https://rbcommons.com/s/twitter/r/2054>`_

* Add 'java-resource' and 'java-test-resource' content type for Resources Roots.
  `RB #2046 <https://rbcommons.com/s/twitter/r/2046>`_

* Upgrade virtualenv from 12.0.7 to 12.1.1.
  `RB #2047 <https://rbcommons.com/s/twitter/r/2047>`_

* convert all % formatted strings under src/ to str.format format
  `RB #2042 <https://rbcommons.com/s/twitter/r/2042>`_

* Move overrides for registrations to debug.
  `RB #2023 <https://rbcommons.com/s/twitter/r/2023>`_

* Split jvm_binary.py into jvm_binary.py and jvm_app.py.
  `RB #2006 <https://rbcommons.com/s/twitter/r/2006>`_

* Validate analysis earlier, and handle it explicitly
  `RB #1999 <https://rbcommons.com/s/twitter/r/1999>`_

* Switch to importlib
  `RB #2003 <https://rbcommons.com/s/twitter/r/2003>`_

* Some refactoring and tidying-up in workunit.
  `RB #1981 <https://rbcommons.com/s/twitter/r/1981>`_

* Remove virtualenv tarball from CI cache.
  `RB #2281 <https://rbcommons.com/s/twitter/r/2281>`_

* Moved testing of examples and testprojects to tests
  `RB #2158 <https://rbcommons.com/s/twitter/r/2158>`_

* Share the python interpreter/egg caches between tests.
  `RB #2256 <https://rbcommons.com/s/twitter/r/2256>`_

* Add support for python test sharding.
  `RB #2243 <https://rbcommons.com/s/twitter/r/2243>`_

* Fixup OSX CI breaks.
  `RB #2241 <https://rbcommons.com/s/twitter/r/2241>`_

* fix test class name c&p error
  `RB #2227 <https://rbcommons.com/s/twitter/r/2227>`_

* Remove the pytest skip tag for scala publish integration test as it uses --doc-scaladoc-skip
  `RB #2225 <https://rbcommons.com/s/twitter/r/2225>`_

* integration test for classifiers
  `RB #2216 <https://rbcommons.com/s/twitter/r/2216>`_
  `RB #2218 <https://rbcommons.com/s/twitter/r/2218>`_
  `RB #2232 <https://rbcommons.com/s/twitter/r/2232>`_

* Use 2 IT shards to avoid OSX CI timeouts.
  `RB #2217 <https://rbcommons.com/s/twitter/r/2217>`_

* Don't have JvmToolTaskTestBase require access to "real" option values.
  `RB #2213 <https://rbcommons.com/s/twitter/r/2213>`_

* There were two test_export_integration.py tests.
  `RB #2215 <https://rbcommons.com/s/twitter/r/2215>`_

* Do not include integration tests in non-integration tests.
  `RB #2173 <https://rbcommons.com/s/twitter/r/2173>`_

* Streamline some test setup.
  `RB #2167 <https://rbcommons.com/s/twitter/r/2167>`_

* Ensure that certain test cleanup always happens, even if setUp fails.
  `RB #2166 <https://rbcommons.com/s/twitter/r/2166>`_

* Added a test of the bootstrapper logic with no cached bootstrap.jar
  `RB #2126 <https://rbcommons.com/s/twitter/r/2126>`_

* Remove integration tests from default targets in test BUILD files
  `RB #2086 <https://rbcommons.com/s/twitter/r/2086>`_

* Cap BootstrapJvmTools mem in JvmToolTaskTestBase.
  `RB #2077 <https://rbcommons.com/s/twitter/r/2077>`_

* Re-establish no nailguns under TravisCI.
  `RB #1852 <https://rbcommons.com/s/twitter/r/1852>`_
  `RB #2065 <https://rbcommons.com/s/twitter/r/2065>`_

* Further cleanup of test context setup.
  `RB #2053 <https://rbcommons.com/s/twitter/r/2053>`_

* Remove plumbing for custom test config.
  `RB #2051 <https://rbcommons.com/s/twitter/r/2051>`_

* Use a fake context when testing.
  `RB #2049 <https://rbcommons.com/s/twitter/r/2049>`_

* Remove old TaskTest base class.
  `RB #2039 <https://rbcommons.com/s/twitter/r/2039>`_
  `RB #2031 <https://rbcommons.com/s/twitter/r/2031>`_
  `RB #2027 <https://rbcommons.com/s/twitter/r/2027>`_
  `RB #2022 <https://rbcommons.com/s/twitter/r/2022>`_
  `RB #2017 <https://rbcommons.com/s/twitter/r/2017>`_
  `RB #2016 <https://rbcommons.com/s/twitter/r/2016>`_

* Refactor com.pants package to org.pantsbuild in examples and testprojects
  `RB #2037 <https://rbcommons.com/s/twitter/r/2037>`_

* Added a simple 'HelloWorld' java example.
  `RB #2028 <https://rbcommons.com/s/twitter/r/2028>`_

* Place the workdir below the pants_workdir
  `RB #2007 <https://rbcommons.com/s/twitter/r/2007>`_

0.0.32 (3/26/2015)
------------------

Bugfixes
~~~~~~~~

* Fixup minified_dependencies
  `Issue #1329 <https://github.com/pantsbuild/pants/issues/1329>`_
  `RB #1986 <https://rbcommons.com/s/twitter/r/1986>`_

* Don`t mutate options in the linter
  `RB #1978 <https://rbcommons.com/s/twitter/r/1978>`_

* Fix a bad logic bug in zinc analysis split code
  `RB #1969 <https://rbcommons.com/s/twitter/r/1969>`_

* always use relpath on --test file args
  `RB #1976 <https://rbcommons.com/s/twitter/r/1976>`_

* Fixup resources drift in the sdist package
  `RB #1974 <https://rbcommons.com/s/twitter/r/1974>`_

* Fix publish override flag
  `Issue #1277 <https://github.com/pantsbuild/pants/issues/1277>`_
  `RB #1959 <https://rbcommons.com/s/twitter/r/1959>`_

API Changes
~~~~~~~~~~~

* Remove open_zip64 in favor of supporting zip64 everywhere
  `RB #1984 <https://rbcommons.com/s/twitter/r/1984>`_

Documentation
~~~~~~~~~~~~~

* rm python_old, an old document
  `RB #1973 <https://rbcommons.com/s/twitter/r/1973>`_

* Updated ivysettings.xml with comments and commented out local repos
  `RB #1979 <https://rbcommons.com/s/twitter/r/1979>`_

* Update how to setup proxies in ivy
  `RB #1975 <https://rbcommons.com/s/twitter/r/1975>`_

New Features
~~~~~~~~~~~~

* Ignore blank lines and comments in scalastyle excludes file
  `RB #1971 <https://rbcommons.com/s/twitter/r/1971>`_

* Adding a --test-junit-coverage-jvm-options flag
  `RB #1968 <https://rbcommons.com/s/twitter/r/1968>`_

* --soft-excludes flag for resolve-ivy
  `RB #1961 <https://rbcommons.com/s/twitter/r/1961>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Rid pantsbuild.pants of an un-needed antlr dep
  `RB #1989 <https://rbcommons.com/s/twitter/r/1989>`_

* Kill the BUILD.transitional targets
  `Issue #1126 <https://github.com/pantsbuild/pants/issues/1126>`_
  `RB #1983 <https://rbcommons.com/s/twitter/r/1983>`_

* Convert ragel-gen.py to use new options and expunge config from BinaryUtil
  `RB #1970 <https://rbcommons.com/s/twitter/r/1970>`_

* Add the JvmCompileIsolatedStrategy
  `RB #1898 <https://rbcommons.com/s/twitter/r/1898>`_

* Move construction of PythonChroot to PythonTask base class
  `RB #1965 <https://rbcommons.com/s/twitter/r/1965>`_

* Delete the PythonBinaryBuilder class
  `RB #1964 <https://rbcommons.com/s/twitter/r/1964>`_

* Removing dead code
  `RB #1960 <https://rbcommons.com/s/twitter/r/1960>`_

* Make the test check that the return code is propagated
  `RB #1966 <https://rbcommons.com/s/twitter/r/1966>`_

* Cleanup
  `RB #1962 <https://rbcommons.com/s/twitter/r/1962>`_

* Get rid of almost all direct config access in python-building code
  `RB #1954 <https://rbcommons.com/s/twitter/r/1954>`_

0.0.31 (3/20/2015)
------------------

Bugfixes
~~~~~~~~

* Make JavaProtobufLibrary not exportable to fix publish.
  `RB #1952 <https://rbcommons.com/s/twitter/r/1952>`_

* Pass compression option along to temp local artifact caches.
  `RB #1955 <https://rbcommons.com/s/twitter/r/1955>`_

* Fix a missing symbol in ScalaCompile
  `RB #1885 <https://rbcommons.com/s/twitter/r/1885>`_
  `RB #1945 <https://rbcommons.com/s/twitter/r/1945>`_

* die only when invoked directly
  `RB #1953 <https://rbcommons.com/s/twitter/r/1953>`_

* add import for traceback, and add test to exercise that code path, rm unsed kwargs
  `RB #1868 <https://rbcommons.com/s/twitter/r/1868>`_
  `RB #1943 <https://rbcommons.com/s/twitter/r/1943>`_

API Changes
~~~~~~~~~~~

* Use the publically released 2.1.1 version of Cobertura
  `RB #1933 <https://rbcommons.com/s/twitter/r/1933>`_

Documentation
~~~~~~~~~~~~~

* Update docs for 'prep_command()'
  `RB #1940 <https://rbcommons.com/s/twitter/r/1940>`_

New Features
~~~~~~~~~~~~

* added sources and javadocs to export goal output
  `RB #1936 <https://rbcommons.com/s/twitter/r/1936>`_

* Add flags to idea and eclipse goals to exclude pulling in sources and javadoc via ivy
  `RB #1939 <https://rbcommons.com/s/twitter/r/1939>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove a spurious import in test_antlr_builder
  `RB #1951 <https://rbcommons.com/s/twitter/r/1951>`_

* Refactor ZincUtils
  `RB #1946 <https://rbcommons.com/s/twitter/r/1946>`_

* change set([]) / OrderedSet([]) to set() / OrderedSet()
  `RB #1947 <https://rbcommons.com/s/twitter/r/1947>`_

* Rename TestPythonSetup to TestSetupPy
  `RB #1950 <https://rbcommons.com/s/twitter/r/1950>`_

* Rename the PythonSetup task to SetupPy
  `RB #1942 <https://rbcommons.com/s/twitter/r/1942>`_

0.0.30 (3/18/2015)
------------------

Bugfixes
~~~~~~~~

* Fix missing deps from global switch to six range
  `RB #1931 <https://rbcommons.com/s/twitter/r/1931>`_
  `RB #1937 <https://rbcommons.com/s/twitter/r/1937>`_

* Fix python_repl to work for python_requirement_libraries
  `RB #1934 <https://rbcommons.com/s/twitter/r/1934>`_

* Move count variable outside loop
  `RB #1926 <https://rbcommons.com/s/twitter/r/1926>`_

* Fix regression in synthetic target context handling
  `RB #1921 <https://rbcommons.com/s/twitter/r/1921>`_

* Try to fix the .rst render of the CHANGELOG on pypi
  `RB #1911 <https://rbcommons.com/s/twitter/r/1911>`_

* To add android.jar to the classpath, create a copy under task's workdir
  `RB #1902 <https://rbcommons.com/s/twitter/r/1902>`_

* walk synthetic targets dependencies when constructing context.target()
  `RB #1863 <https://rbcommons.com/s/twitter/r/1863>`_
  `RB #1914 <https://rbcommons.com/s/twitter/r/1914>`_

* Mix the value of the zinc name-hashing flag into cache keys
  `RB #1912 <https://rbcommons.com/s/twitter/r/1912>`_

* Allow multiple ivy artifacts distinguished only by classifier
  `RB #1905 <https://rbcommons.com/s/twitter/r/1905>`_

* Fix `Git.detect_worktree` to fail gracefully
  `RB #1903 <https://rbcommons.com/s/twitter/r/1903>`_

* Avoid reparsing analysis repeatedly
  `RB #1938 <https://rbcommons.com/s/twitter/r/1938>`_

API Changes
~~~~~~~~~~~

* Remove the now-superfluous "parallel resource directories" hack
  `RB #1907 <https://rbcommons.com/s/twitter/r/1907>`_

* Make rglobs follow symlinked directories by default
  `RB #1881 <https://rbcommons.com/s/twitter/r/1881>`_

Documentation
~~~~~~~~~~~~~

* Trying to clarify how to contribute docs
  `RB #1922 <https://rbcommons.com/s/twitter/r/1922>`_

* Add documentation on how to turn on extra ivy debugging
  `RB #1906 <https://rbcommons.com/s/twitter/r/1906>`_

* Adds documentation to setup_repo.md with tips for how to configure Pants to work behind a firewall
  `RB #1899 <https://rbcommons.com/s/twitter/r/1899>`_

New Features
~~~~~~~~~~~~

* Support spec_excludes in what_changed. Prior art: https://rbcommons.com/s/twitter/r/1795/
  `RB #1930 <https://rbcommons.com/s/twitter/r/1930>`_

* Add a new 'export' goal for use by IDE integration
  `RB #1917 <https://rbcommons.com/s/twitter/r/1917>`_
  `RB #1929 <https://rbcommons.com/s/twitter/r/1929>`_

* Add ability to detect HTTP_PROXY or HTTPS_PROXY in environment and pass it along to ivy
  `RB #1877 <https://rbcommons.com/s/twitter/r/1877>`_

* Pants publish to support publishing extra publish artifacts as individual artifacts with classifier attached
  `RB #1879 <https://rbcommons.com/s/twitter/r/1879>`_
  `RB #1889 <https://rbcommons.com/s/twitter/r/1889>`_

Small improvements, Refactoring and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Deleting dead abbreviate_target_ids code.
  `RB #1918 <https://rbcommons.com/s/twitter/r/1918>`_
  `RB #1944 <https://rbcommons.com/s/twitter/r/1944>`_

* Move AptCompile to its own file
  `RB #1935 <https://rbcommons.com/s/twitter/r/1935>`_

* use six.moves.range everywhere
  `RB #1931 <https://rbcommons.com/s/twitter/r/1931>`_

* Port scrooge/linter config to the options system
  `RB #1927 <https://rbcommons.com/s/twitter/r/1927>`_

* Fixes for import issues in JvmCompileStrategy post https://rbcommons.com/s/twitter/r/1885/
  `RB #1900 <https://rbcommons.com/s/twitter/r/1900>`_

* Moving stuff out of jvm and into project info backend
  `RB #1917 <https://rbcommons.com/s/twitter/r/1917>`_

* Provides is meant to have been deprecated a long time ago
  `RB #1915 <https://rbcommons.com/s/twitter/r/1915>`_

* Move JVM debug config functionality to the new options system
  `RB #1924 <https://rbcommons.com/s/twitter/r/1924>`_

* Remove the --color option from specs_run.  See https://rbcommons.com/s/twitter/r/1814/
  `RB #1916 <https://rbcommons.com/s/twitter/r/1916>`_

* Remove superfluous 'self.conf' argument to self.classpath
  `RB #1913 <https://rbcommons.com/s/twitter/r/1913>`_

* Update ivy_utils error messages: include classifier and switch interpolation from % to format
  `RB #1908 <https://rbcommons.com/s/twitter/r/1908>`_

* Added a python helper for check_header.sh in git pre-commit script
  `RB #1910 <https://rbcommons.com/s/twitter/r/1910>`_

* Remove direct config access in scalastyle.py
  `RB #1897 <https://rbcommons.com/s/twitter/r/1897>`_

* Replace all instances of xrange with range, as xrange is deprecated in Python 3
  `RB #1901 <https://rbcommons.com/s/twitter/r/1901>`_

* Raise a better exception on truncated Zinc analysis files
  `RB #1896 <https://rbcommons.com/s/twitter/r/1896>`_

* Fail fast for OSX CI runs
  `RB #1894 <https://rbcommons.com/s/twitter/r/1894>`_

* Upgrade to the latest rbt release
  `RB #1893 <https://rbcommons.com/s/twitter/r/1893>`_

* Use cmp instead of a file hash
  `RB #1892 <https://rbcommons.com/s/twitter/r/1892>`_

* Split out a JvmCompileStrategy interface
  `RB #1885 <https://rbcommons.com/s/twitter/r/1885>`_

* Decouple WorkUnit from RunTracker
  `RB #1928 <https://rbcommons.com/s/twitter/r/1928>`_

* Add Scm.add, change publish to add pushdb explicitly, move scm publish around
  `RB #1868 <https://rbcommons.com/s/twitter/r/1868>`_

0.0.29 (3/9/2015)
-----------------

CI
~~

* Support local pre-commit checks
  `RB #1883 <https://rbcommons.com/s/twitter/r/1883>`_

* Fix newline to fix broken master build
  `RB #1888 <https://rbcommons.com/s/twitter/r/1888>`_

* Shard out OSX CI
  `RB #1873 <https://rbcommons.com/s/twitter/r/1873>`_

* Update travis's pants cache settings
  `RB #1875 <https://rbcommons.com/s/twitter/r/1875>`_

* Fixup contrib tests on osx CI
  `RB #1867 <https://rbcommons.com/s/twitter/r/1867>`_

* Reduce number of test shards from 8 to 6 on Travis-ci
  `RB #1804 <https://rbcommons.com/s/twitter/r/1804>`_

* Cache the isort venv for ci runs
  `RB #1740 <https://rbcommons.com/s/twitter/r/1740>`_

* Fixup ci isort check
  `RB #1728 <https://rbcommons.com/s/twitter/r/1728>`_

Tests
~~~~~

* Add jar Publish integration tests to test the generated pom and ivy.xml files
  `RB #1879 <https://rbcommons.com/s/twitter/r/1879>`_

* Added test that shows that nested scope inherits properly from cmdline, config, and env
  `RB #1851 <https://rbcommons.com/s/twitter/r/1851>`_
  `RB #1865 <https://rbcommons.com/s/twitter/r/1865>`_

* Improve AndroidDistribution coverage
  `RB #1861 <https://rbcommons.com/s/twitter/r/1861>`_

* Modernize the protobuf and wire task tests
  `RB #1854 <https://rbcommons.com/s/twitter/r/1854>`_

* Replace python_test_suite with target
  `RB #1821 <https://rbcommons.com/s/twitter/r/1821>`_

* Switch test_jvm_run.py to the new TaskTestBase instead of the old TaskTest
  `RB #1829 <https://rbcommons.com/s/twitter/r/1829>`_

* Remove two non-useful tests
  `RB #1828 <https://rbcommons.com/s/twitter/r/1828>`_

* Fix a python run integration test
  `RB #1810 <https://rbcommons.com/s/twitter/r/1810>`_

* Work around py test_runner issue with ns packages
  `RB #1813 <https://rbcommons.com/s/twitter/r/1813>`_

* Add a test for the Git changelog
  `RB #1792 <https://rbcommons.com/s/twitter/r/1792>`_

* Create a directory with no write perms for TestAndroidConfigUtil
  `RB #1796 <https://rbcommons.com/s/twitter/r/1796>`_

* Relocated some tests (no code changes) from tests/python/pants_test/tasks into
  tests/python/pants_test/backend/codegen/tasks to mirror the source location
  `RB #1746 <https://rbcommons.com/s/twitter/r/1746>`_

Docs
~~~~

* Add some documentation about using the pants reporting server for troubleshooting
  `RB #1887 <https://rbcommons.com/s/twitter/r/1887>`_

* Docstring reformatting for Task and InvalidationCheck
  `RB #1769 <https://rbcommons.com/s/twitter/r/1769>`_

* docs: Show correct pictures for intellij.html
  `RB #1716 <https://rbcommons.com/s/twitter/r/1716>`_

* doc += how to turn on cache
  `RB #1668 <https://rbcommons.com/s/twitter/r/1668>`_

New language: C++
~~~~~~~~~~~~~~~~~

* Separate compile step for C++ to just compile objects
  `RB #1855 <https://rbcommons.com/s/twitter/r/1855>`_

* Fixup CppToolchain to be lazy and actually cache
  `RB #1850 <https://rbcommons.com/s/twitter/r/1850>`_

* C++ support in contrib
  `RB #1818 <https://rbcommons.com/s/twitter/r/1818>`_

API Changes
~~~~~~~~~~~

* Kill the global `--ng-daemons` flag
  `RB #1852 <https://rbcommons.com/s/twitter/r/1852>`_

* Removed parallel_test_paths setting from pants.ini.  It isn't needed in the pants repo any more
  `RB #1846 <https://rbcommons.com/s/twitter/r/1846>`_

* BUILD file format cleanup:

  - Deprecate bundle().add in favor of bundle(files=)
    `RB #1788 <https://rbcommons.com/s/twitter/r/1788>`_
  - Deprecate .intransitive() in favor of argument
    `RB #1797 <https://rbcommons.com/s/twitter/r/1797>`_
  - Deprecate target.with_description in favor of target(description=)
    `RB #1790 <https://rbcommons.com/s/twitter/r/1790>`_
  - Allow exclude in globs
    `RB #1762 <https://rbcommons.com/s/twitter/r/1762>`_
  - Move with_artifacts to an artifacts argument
    `RB #1672 <https://rbcommons.com/s/twitter/r/1672>`_

* An attempt to deprecate some old methods
  `RB #1720 <https://rbcommons.com/s/twitter/r/1720>`_

* Options refactor work

  - Make option registration recursion optional
    `RB #1870 <https://rbcommons.com/s/twitter/r/1870>`_
  - Remove all direct config uses from jar_publish.py
    `RB #1844 <https://rbcommons.com/s/twitter/r/1844>`_
  - Read pants_distdir from options instead of config
    `RB #1842 <https://rbcommons.com/s/twitter/r/1842>`_
  - Remove direct config references in thrift gen code
    `RB #1839 <https://rbcommons.com/s/twitter/r/1839>`_
  - Android backend now exclusively uses the new option system
    `RB #1819 <https://rbcommons.com/s/twitter/r/1819>`_
  - Replace config use in RunTracker with options
    `RB #1823 <https://rbcommons.com/s/twitter/r/1823>`_
  - Add pants_bootstradir and pants_configdir to options bootstrapper
    `RB #1835 <https://rbcommons.com/s/twitter/r/1835>`_
  - Remove all direct config access in task.py
    `RB #1827 <https://rbcommons.com/s/twitter/r/1827>`_
  - Convert config-only options in goal idea and eclipse to use new options format
    `RB #1805 <https://rbcommons.com/s/twitter/r/1805>`_
  - Remove config_section from some tasks
    `RB #1806 <https://rbcommons.com/s/twitter/r/1806>`_
  - Disallow --no- on the name of boolean flags, refactor existing ones
    `Issue #34 <https://github.com/pantsbuild/intellij-pants-plugin/issues/34>`_
    `RB #1799 <https://rbcommons.com/s/twitter/r/1799>`_
  - Migrating pants.ini config values for protobuf-gen to advanced registered options under gen.protobuf
    `RB #1741 <https://rbcommons.com/s/twitter/r/1741>`_

* Add a way to deprecate options with 'deprecated_version' and 'deprecated_hint' kwargs to register()
  `RB #1799 <https://rbcommons.com/s/twitter/r/1799>`_
  `RB #1814 <https://rbcommons.com/s/twitter/r/1814>`_

* Implement compile_classpath using UnionProducts
  `RB #1761 <https://rbcommons.com/s/twitter/r/1761>`_

* Introduce a @deprecated decorator
  `RB #1725 <https://rbcommons.com/s/twitter/r/1725>`_

* Update jar-tool to 0.1.9 and switch to use @argfile calling convention
  `RB #1798 <https://rbcommons.com/s/twitter/r/1798>`_

* Pants to respect XDB spec for global storage on unix systems
  `RB #1817 <https://rbcommons.com/s/twitter/r/1817>`_

* Adds a mixin (ImportJarsMixin) for the IvyImports task
  `RB #1783 <https://rbcommons.com/s/twitter/r/1783>`_

* Added invalidation check to UnpackJars task
  `RB #1776 <https://rbcommons.com/s/twitter/r/1776>`_

* Enable python-eval for pants source code
  `RB #1773 <https://rbcommons.com/s/twitter/r/1773>`_

* adding xml output for python coverage
  `Issue #1105 <https://github.com/pantsbuild/pants/issues/1105>`_
  `RB #1770 <https://rbcommons.com/s/twitter/r/1770>`_

* Optionally adds a path value onto protoc's PATH befor launching it
  `RB #1756 <https://rbcommons.com/s/twitter/r/1756>`_

* Add progress information to partition reporting
  `RB #1749 <https://rbcommons.com/s/twitter/r/1749>`_

* Add SignApk product and Zipalign task
  `RB #1737 <https://rbcommons.com/s/twitter/r/1737>`_

* Add an 'advanced' parameter to registering options
  `RB #1739 <https://rbcommons.com/s/twitter/r/1739>`_

* Add an env var for enabling the profiler
  `RB #1305 <https://rbcommons.com/s/twitter/r/1305>`_

Bugfixes and features
~~~~~~~~~~~~~~~~~~~~~

* Kill the .saplings split
  `RB #1886 <https://rbcommons.com/s/twitter/r/1886>`_

* Update our requests library to something more recent
  `RB #1884 <https://rbcommons.com/s/twitter/r/1884>`_

* Make a nicer looking name for workunit output
  `RB #1876 <https://rbcommons.com/s/twitter/r/1876>`_

* Fixup DxCompile jvm_options to be a list
  `RB #1878 <https://rbcommons.com/s/twitter/r/1878>`_

* Make sure <?xml starts at the beginning of the file when creating an empty xml report
  `RB #1856 <https://rbcommons.com/s/twitter/r/1856>`_

* Set print_exception_stacktrace in pants.ini
  `RB #1872 <https://rbcommons.com/s/twitter/r/1872>`_

* Handle --print-exception-stacktrace and --version more elegantly
  `RB #1871 <https://rbcommons.com/s/twitter/r/1871>`_

* Improve AndroidDistribution caching
  `RB #1861 <https://rbcommons.com/s/twitter/r/1861>`_

* Add zinc to the platform_tools for zinc_utils
  `RB #1779 <https://rbcommons.com/s/twitter/r/1779>`_
  `RB #1858 <https://rbcommons.com/s/twitter/r/1858>`_

* Fix WARN/WARNING confusion
  `RB #1866 <https://rbcommons.com/s/twitter/r/1866>`_

* Fixup Config to find DEFAULT values for missing sections
  `RB #1851 <https://rbcommons.com/s/twitter/r/1851>`_

* Get published artifact classfier from config
  `RB #1857 <https://rbcommons.com/s/twitter/r/1857>`_

* Make Context.targets() include synthetic targets
  `RB #1840 <https://rbcommons.com/s/twitter/r/1840>`_
  `RB #1863 <https://rbcommons.com/s/twitter/r/1863>`_

* Fix micros to be left 0 padded to 6 digits
  `RB #1849 <https://rbcommons.com/s/twitter/r/1849>`_

* Setup logging before plugins are loaded
  `RB #1820 <https://rbcommons.com/s/twitter/r/1820>`_

* Introduce pants_setup_py and contrib_setup_py helpers
  `RB #1822 <https://rbcommons.com/s/twitter/r/1822>`_

* Support zinc name hashing
  `RB #1779 <https://rbcommons.com/s/twitter/r/1779>`_

* Actually generate a depfile from t.c.tools.compiler and use it in jmake
  `RB #1824 <https://rbcommons.com/s/twitter/r/1824>`_
  `RB #1825 <https://rbcommons.com/s/twitter/r/1825>`_

* Ivy Imports now has a cache
  `RB #1785 <https://rbcommons.com/s/twitter/r/1785>`_

* Get rid of some direct config uses in python_repl.py
  `RB #1826 <https://rbcommons.com/s/twitter/r/1826>`_

* Add check if jars exists before registering products
  `RB #1808 <https://rbcommons.com/s/twitter/r/1808>`_

* shlex the python run args
  `RB #1782 <https://rbcommons.com/s/twitter/r/1782>`_

* Convert t.c.log usages to logging
  `RB #1815 <https://rbcommons.com/s/twitter/r/1815>`_

* Kill unused twitter.common reqs and deps
  `RB #1816 <https://rbcommons.com/s/twitter/r/1816>`_

* Check import sorting before checking headers
  `RB #1812 <https://rbcommons.com/s/twitter/r/1812>`_

* Fixup typo accessing debug_port option
  `RB #1811 <https://rbcommons.com/s/twitter/r/1811>`_

* Allow the dependees goal and idea to respect the --spec_excludes option
  `RB #1795 <https://rbcommons.com/s/twitter/r/1795>`_

* Copy t.c.lang.{AbstractClass,Singleton} to pants
  `RB #1803 <https://rbcommons.com/s/twitter/r/1803>`_

* Replace all t.c.lang.Compatibility uses with six
  `RB #1801 <https://rbcommons.com/s/twitter/r/1801>`_

* Fix sp in java example readme.md
  `RB #1800 <https://rbcommons.com/s/twitter/r/1800>`_

* Add util.XmlParser and AndroidManifestParser
  `RB #1757 <https://rbcommons.com/s/twitter/r/1757>`_

* Replace Compatibility.exec_function with `six.exec_`
  `RB #1742 <https://rbcommons.com/s/twitter/r/1742>`_
  `RB #1794 <https://rbcommons.com/s/twitter/r/1794>`_

* Take care of stale pidfiles for pants server
  `RB #1791 <https://rbcommons.com/s/twitter/r/1791>`_

* Fixup the scrooge release
  `RB #1793 <https://rbcommons.com/s/twitter/r/1793>`_

* Extract scrooge tasks to contrib/
  `RB #1780 <https://rbcommons.com/s/twitter/r/1780>`_

* Fixup JarPublish changelog rendering
  `RB #1787 <https://rbcommons.com/s/twitter/r/1787>`_

* Preserve dictionary order in the anonymizer
  `RB #1779 <https://rbcommons.com/s/twitter/r/1779>`_
  `RB #1781 <https://rbcommons.com/s/twitter/r/1781>`_

* Fix a test file leak to the build root
  `RB #1771 <https://rbcommons.com/s/twitter/r/1771>`_

* Replace all instances of compatibility.string
  `RB #1764 <https://rbcommons.com/s/twitter/r/1764>`_

* Improve the python run error message
  `RB #1773 <https://rbcommons.com/s/twitter/r/1773>`_
  `RB #1777 <https://rbcommons.com/s/twitter/r/1777>`_

* Upgrade pex to 0.8.6
  `RB #1778 <https://rbcommons.com/s/twitter/r/1778>`_

* Introduce a PythonEval task
  `RB #1772 <https://rbcommons.com/s/twitter/r/1772>`_

* Add an elapsed timestamp to the banner for CI
  `RB #1775 <https://rbcommons.com/s/twitter/r/1775>`_

* Trying to clean up a TODO in IvyTaskMixin
  `RB #1753 <https://rbcommons.com/s/twitter/r/1753>`_

* rm double_dag
  `RB #1711 <https://rbcommons.com/s/twitter/r/1711>`_

* Add skip / target invalidation to thrift linting
  `RB #1755 <https://rbcommons.com/s/twitter/r/1755>`_

* Fixup `Task.invalidated` UI
  `RB #1758 <https://rbcommons.com/s/twitter/r/1758>`_

* Improve the implementation of help printing
  `RB #1739 <https://rbcommons.com/s/twitter/r/1739>`_
  `RB #1744 <https://rbcommons.com/s/twitter/r/1744>`_

* Fix TestAndroidBase task_type override miss
  `RB #1751 <https://rbcommons.com/s/twitter/r/1751>`_

* Pass the BUILD file path to compile
  `RB #1742 <https://rbcommons.com/s/twitter/r/1742>`_

* Bandaid leaks of global Config state in tests
  `RB #1750 <https://rbcommons.com/s/twitter/r/1750>`_

* Fixing cobertura coverage so that it actually works
  `RB #1704 <https://rbcommons.com/s/twitter/r/1704>`_

* Restore the ability to bootstrap Ivy with a custom configuration file
  `RB #1709 <https://rbcommons.com/s/twitter/r/1709>`_

* Kill BUILD file bytecode compilation
  `RB #1736 <https://rbcommons.com/s/twitter/r/1736>`_

* Kill 'goal' usage in the pants script
  `RB #1738 <https://rbcommons.com/s/twitter/r/1738>`_

* Fixup ivy report generation and opening
  `RB #1735 <https://rbcommons.com/s/twitter/r/1735>`_

* Fixup pants sys.excepthook for pex context
  `RB #1733 <https://rbcommons.com/s/twitter/r/1733>`_
  `RB #1734 <https://rbcommons.com/s/twitter/r/1734>`_

* Adding long form of help arguments to the help output
  `RB #1732 <https://rbcommons.com/s/twitter/r/1732>`_

* Simplify isort config
  `RB #1731 <https://rbcommons.com/s/twitter/r/1731>`_

* Expand scope of python file format checks
  `RB #1729 <https://rbcommons.com/s/twitter/r/1729>`_

* Add path-to option to depmap
  `RB #1545 <https://rbcommons.com/s/twitter/r/1545>`_

* Fix a stragler `.is_apt` usage
  `RB #1724 <https://rbcommons.com/s/twitter/r/1724>`_

* Introduce isort to check `*.py` import ordering
  `RB #1726 <https://rbcommons.com/s/twitter/r/1726>`_

* Upgrade to pex 0.8.5
  `RB #1721 <https://rbcommons.com/s/twitter/r/1721>`_

* cleanup is_xxx checks: is_jar_library
  `RB #1719 <https://rbcommons.com/s/twitter/r/1719>`_

* Avoid redundant traversal in classpath calculation
  `RB #1714 <https://rbcommons.com/s/twitter/r/1714>`_

* Upgrade to the latest virtualenv
  `RB #1715 <https://rbcommons.com/s/twitter/r/1715>`_
  `RB #1718 <https://rbcommons.com/s/twitter/r/1718>`_

* Fixup the release script
  `RB #1715 <https://rbcommons.com/s/twitter/r/1715>`_

* './pants goal' -> './pants'
  `RB #1617 <https://rbcommons.com/s/twitter/r/1617>`_

* Add new function open_zip64 which defaults allowZip64=True for Zip files
  `RB #1708 <https://rbcommons.com/s/twitter/r/1708>`_

* Fix a bug that --bundle-archive=tar generates .tar.gz instead of a .tar
  `RB #1707 <https://rbcommons.com/s/twitter/r/1707>`_

* Remove 3rdparty debug.keystore
  `RB #1703 <https://rbcommons.com/s/twitter/r/1703>`_

* Keystore no longer a target, apks signed with SignApkTask
  `RB #1690 <https://rbcommons.com/s/twitter/r/1690>`_

* remove this jar_rule I accidentally added
  `RB #1701 <https://rbcommons.com/s/twitter/r/1701>`_

* Require pushdb migration to specify a destination directory
  `RB #1684 <https://rbcommons.com/s/twitter/r/1684>`_

0.0.28 (2/1/2015)
-----------------

Bugfixes
~~~~~~~~

* Numerous doc improvements & generation fixes

  - Steal some info from options docstring
  - Document `--config-override` & `PANTS_` environment vars
  - Document JDK_HOME & JAVA_HOME use when choosing a java distribution
  - Rename "Goals Reference" page -> "Options Reference"
  - Document when to use isrequired
  - Fix Google indexing to ignore test sites
  - Update the code layout section of Pants Internals
  - Show changelog & for that support `page(source='something.rst')`
  - Add a reminder that you can do set-like math on FileSets
  - Hacking on Pants itself, update `--pdb` doc
  - Start of a "Why Choose Pants?" section
  - Highlight plugin examples from twitter/commons
  - Add a blurb about deploy_jar_rules to the JVM docs
  - Show how to pass `-s` to pytest
  - When to use java_sources, when not to
  - Start of a Pants-with-scala page
  - Publish page now shows `provides=` example
  - Add a flag to omit "internal" things
  - Slide tweaks based on class feedback
  - Document argument splitting for options

  `Issue #897 <https://github.com/pantsbuild/pants/issues/897>`_
  `RB #1092 <https://rbcommons.com/s/twitter/r/1092>`_
  `RB #1490 <https://rbcommons.com/s/twitter/r/1490>`_
  `RB #1532 <https://rbcommons.com/s/twitter/r/1532>`_
  `RB #1544 <https://rbcommons.com/s/twitter/r/1544>`_
  `RB #1546 <https://rbcommons.com/s/twitter/r/1546>`_
  `RB #1548 <https://rbcommons.com/s/twitter/r/1548>`_
  `RB #1549 <https://rbcommons.com/s/twitter/r/1549>`_
  `RB #1550 <https://rbcommons.com/s/twitter/r/1550>`_
  `RB #1554 <https://rbcommons.com/s/twitter/r/1554>`_
  `RB #1555 <https://rbcommons.com/s/twitter/r/1555>`_
  `RB #1559 <https://rbcommons.com/s/twitter/r/1559>`_
  `RB #1560 <https://rbcommons.com/s/twitter/r/1560>`_
  `RB #1565 <https://rbcommons.com/s/twitter/r/1565>`_
  `RB #1575 <https://rbcommons.com/s/twitter/r/1575>`_
  `RB #1580 <https://rbcommons.com/s/twitter/r/1580>`_
  `RB #1583 <https://rbcommons.com/s/twitter/r/1583>`_
  `RB #1584 <https://rbcommons.com/s/twitter/r/1584>`_
  `RB #1593 <https://rbcommons.com/s/twitter/r/1593>`_
  `RB #1607 <https://rbcommons.com/s/twitter/r/1607>`_
  `RB #1608 <https://rbcommons.com/s/twitter/r/1608>`_
  `RB #1609 <https://rbcommons.com/s/twitter/r/1609>`_
  `RB #1618 <https://rbcommons.com/s/twitter/r/1618>`_
  `RB #1622 <https://rbcommons.com/s/twitter/r/1622>`_
  `RB #1633 <https://rbcommons.com/s/twitter/r/1633>`_
  `RB #1640 <https://rbcommons.com/s/twitter/r/1640>`_
  `RB #1657 <https://rbcommons.com/s/twitter/r/1657>`_
  `RB #1658 <https://rbcommons.com/s/twitter/r/1658>`_
  `RB #1563 <https://rbcommons.com/s/twitter/r/1563>`_
  `RB #1564 <https://rbcommons.com/s/twitter/r/1564>`_
  `RB #1677 <https://rbcommons.com/s/twitter/r/1677>`_
  `RB #1678 <https://rbcommons.com/s/twitter/r/1678>`_
  `RB #1694 <https://rbcommons.com/s/twitter/r/1694>`_
  `RB #1695 <https://rbcommons.com/s/twitter/r/1695>`_

* Add calls to relpath so that we don't generate overlong filenames on mesos
  `RB #1528 <https://rbcommons.com/s/twitter/r/1528>`_
  `RB #1612 <https://rbcommons.com/s/twitter/r/1612>`_
  `RB #1644 <https://rbcommons.com/s/twitter/r/1644>`_

* Regularize headers
  `RB #1691 <https://rbcommons.com/s/twitter/r/1691>`_

* Pants itself uses python2.7, kill unittest2 imports
  `RB #1689 <https://rbcommons.com/s/twitter/r/1689>`_

* Make 'setup-py' show up in './pants goal goals'
  `RB #1466 <https://rbcommons.com/s/twitter/r/1466>`_

* Test that CycleException happens for cycles (instead of a stack overflow)
  `RB #1686 <https://rbcommons.com/s/twitter/r/1686>`_

* Replace t.c.collection.OrderedDict with 2.7+ stdlib
  `RB #1687 <https://rbcommons.com/s/twitter/r/1687>`_

* Make ide_gen a subclass of Task to avoid depending on compile and resources tasks
  `Issue #997 <https://github.com/pantsbuild/pants/issues/997>`_
  `RB #1679 <https://rbcommons.com/s/twitter/r/1679>`_

* Remove with_sources() from 3rdparty/BUILD
  `RB #1674 <https://rbcommons.com/s/twitter/r/1674>`_

* Handle thrift inclusion for python in apache_thrift_gen
  `RB #1656 <https://rbcommons.com/s/twitter/r/1656>`_
  `RB #1675 <https://rbcommons.com/s/twitter/r/1675>`_

* Make beautifulsoup4 dep fixed rather than floating
  `RB #1670 <https://rbcommons.com/s/twitter/r/1670>`_

* Fixes for unpacked_jars
  `RB #1624 <https://rbcommons.com/s/twitter/r/1624>`_

* Fix spurious Products requirements
  `RB #1662 <https://rbcommons.com/s/twitter/r/1662>`_

* Fixup the options bootstrapper to support boolean flags
  `RB #1660 <https://rbcommons.com/s/twitter/r/1660>`_
  `RB #1664 <https://rbcommons.com/s/twitter/r/1664>`_

* Change `Distribution.cached` to compare using Revision objects
  `RB #1653 <https://rbcommons.com/s/twitter/r/1653>`_

* Map linux i686 arch to i386
  `Issue #962 <https://github.com/pantsbuild/pants/issues/962>`_
  `RB #1659 <https://rbcommons.com/s/twitter/r/1659>`_

* bump virtualenv version to 12.0.5
  `RB #1621 <https://rbcommons.com/s/twitter/r/1621>`_

* Bugfixes in calling super methods in traversable_specs and traversable_dependency_specs
  `RB #1611 <https://rbcommons.com/s/twitter/r/1611>`_

* Raise TaskError on python antlr generation failure
  `RB #1604 <https://rbcommons.com/s/twitter/r/1604>`_

* Fix topological ordering + chunking bug in jvm_compile
  `RB #1598 <https://rbcommons.com/s/twitter/r/1598>`_

* Fix CI from RB 1604 (and change a test name as suggested by nhoward)
  `RB #1606 <https://rbcommons.com/s/twitter/r/1606>`_

* Mark some missing-deps testprojects as expected to fail
  `RB #1601 <https://rbcommons.com/s/twitter/r/1601>`_

* Fix scalac plugin support broken in a refactor
  `RB #1596 <https://rbcommons.com/s/twitter/r/1596>`_

* Do not insert an error message as the "main" class in jvm_binary_task
  `RB #1590 <https://rbcommons.com/s/twitter/r/1590>`_

* Remove variable shadowing from method in archive.py
  `RB #1589 <https://rbcommons.com/s/twitter/r/1589>`_

* Don't realpath jars on the classpath
  `RB #1588 <https://rbcommons.com/s/twitter/r/1588>`_
  `RB #1591 <https://rbcommons.com/s/twitter/r/1591>`_

* Cache ivy report dependency traversals consistently
  `RB #1557 <https://rbcommons.com/s/twitter/r/1557>`_

* Print the traceback when there is a problem loading or calling a backend module
  `RB #1582 <https://rbcommons.com/s/twitter/r/1582>`_

* Kill unused Engine.execution_order method and test
  `RB #1576 <https://rbcommons.com/s/twitter/r/1576>`_

* Support use of pytest's --pdb mode
  `RB #1570 <https://rbcommons.com/s/twitter/r/1570>`_

* fix missing dep. allows running this test on its own
  `RB #1561 <https://rbcommons.com/s/twitter/r/1561>`_

* Remove dead code and no longer needed topo sort from cache_manager
  `RB #1553 <https://rbcommons.com/s/twitter/r/1553>`_

* Use Travis CIs new container based builds and caching
  `RB #1523 <https://rbcommons.com/s/twitter/r/1523>`_
  `RB #1537 <https://rbcommons.com/s/twitter/r/1537>`_
  `RB #1538 <https://rbcommons.com/s/twitter/r/1538>`_

API Changes
~~~~~~~~~~~

* Improvements and extensions of `WhatChanged` functionality

  - Skip loading graph if no changed targets
  - Filter targets from changed using exclude_target_regexp
  - Compile/Test "changed" targets
  - Optionally include direct or transitive dependees of changed targets
  - Add changes-in-diffspec option to what-changed
  - Refactor WhatChanged into base class, use LazySourceMapper
  - Introduce LazySourceMapper and test

  `RB #1526 <https://rbcommons.com/s/twitter/r/1526>`_
  `RB #1534 <https://rbcommons.com/s/twitter/r/1534>`_
  `RB #1535 <https://rbcommons.com/s/twitter/r/1535>`_
  `RB #1542 <https://rbcommons.com/s/twitter/r/1542>`_
  `RB #1543 <https://rbcommons.com/s/twitter/r/1543>`_
  `RB #1567 <https://rbcommons.com/s/twitter/r/1567>`_
  `RB #1572 <https://rbcommons.com/s/twitter/r/1572>`_
  `RB #1595 <https://rbcommons.com/s/twitter/r/1595>`_
  `RB #1600 <https://rbcommons.com/s/twitter/r/1600>`_

* More options migration, improvements and bugfixes

  - Centralize invertible arg logic
  - Support loading boolean flags from pants.ini
  - Add a clarifying note in migrate_config
  - Some refactoring of IvyUtils
  - Rename the few remaining "jvm_args" variables to "jvm_options"
  - `./pants --help-all` lists all options
  - Add missing stanza in the migration script
  - Switch artifact cache setup from config to new options
  - Migrate jvm_compile's direct config accesses to the options system
  - Added some formatting to parse errors for dicts and lists in options
  - `s/new_options/options/g`
  - Re-implement the jvm tool registration mechanism via the options system
  - Make JvmRun support passthru args

  `RB #1347 <https://rbcommons.com/s/twitter/r/1347>`_
  `RB #1495 <https://rbcommons.com/s/twitter/r/1495>`_
  `RB #1521 <https://rbcommons.com/s/twitter/r/1521>`_
  `RB #1527 <https://rbcommons.com/s/twitter/r/1527>`_
  `RB #1552 <https://rbcommons.com/s/twitter/r/1552>`_
  `RB #1569 <https://rbcommons.com/s/twitter/r/1569>`_
  `RB #1585 <https://rbcommons.com/s/twitter/r/1585>`_
  `RB #1599 <https://rbcommons.com/s/twitter/r/1599>`_
  `RB #1626 <https://rbcommons.com/s/twitter/r/1626>`_
  `RB #1630 <https://rbcommons.com/s/twitter/r/1630>`_
  `RB #1631 <https://rbcommons.com/s/twitter/r/1631>`_
  `RB #1646 <https://rbcommons.com/s/twitter/r/1646>`_
  `RB #1680 <https://rbcommons.com/s/twitter/r/1680>`_
  `RB #1681 <https://rbcommons.com/s/twitter/r/1681>`_
  `RB #1696 <https://rbcommons.com/s/twitter/r/1696>`_

* Upgrade pex dependency to 0.8.4

  - Pick up several perf wins
  - Pick up fix that allows pex to read older pexes

  `RB #1648 <https://rbcommons.com/s/twitter/r/1648>`_
  `RB #1693 <https://rbcommons.com/s/twitter/r/1693>`_

* Upgrade jmake to org.pantsbuild releases

  - Upgrade jmake to version with isPackagePrivateClass fix
  - Upgrade jmake to version that works with java 1.5+

  `Issue #13 <https://github.com/pantsbuild/jmake/issues/13>`_
  `RB #1594 <https://rbcommons.com/s/twitter/r/1594>`_
  `RB #1628 <https://rbcommons.com/s/twitter/r/1628>`_
  `RB #1650 <https://rbcommons.com/s/twitter/r/1650>`_

* Fix ivy resolve args + added ability to provide custom ivy configurations
  `RB #1671 <https://rbcommons.com/s/twitter/r/1671>`_

* Allow target specs to come from files
  `RB #1669 <https://rbcommons.com/s/twitter/r/1669>`_

* Remove obsolete twitter-specific hack 'is_classpath_artifact'
  `RB #1676 <https://rbcommons.com/s/twitter/r/1676>`_

* Improve RoundEngine lifecycle
  `RB #1665 <https://rbcommons.com/s/twitter/r/1665>`_

* Changed Scala version from 2.9.3 to 2.10.3 because zinc was using 2.10.3 already
  `RB #1610 <https://rbcommons.com/s/twitter/r/1610>`_

* Prevent "round trip" dependencies
  `RB #1603 <https://rbcommons.com/s/twitter/r/1603>`_

* Edit `Config.get_required` so as to raise error for any blank options
  `RB #1638 <https://rbcommons.com/s/twitter/r/1638>`_

* Don't plumb an executor through when bootstrapping tools
  `RB #1634 <https://rbcommons.com/s/twitter/r/1634>`_

* Print jar_dependency deprecations to stderr
  `RB #1632 <https://rbcommons.com/s/twitter/r/1632>`_

* Add configuration parameter to control the requirements cache ttl
  `RB #1627 <https://rbcommons.com/s/twitter/r/1627>`_

* Got ivy to map in javadoc and source jars for pants goal idea
  `RB #1613 <https://rbcommons.com/s/twitter/r/1613>`_
  `RB #1639 <https://rbcommons.com/s/twitter/r/1639>`_

* Remove the '^' syntax for the command line spec parsing
  `RB #1616 <https://rbcommons.com/s/twitter/r/1616>`_

* Kill leftover imports handling from early efforts
  `RB #592 <https://rbcommons.com/s/twitter/r/592>`_
  `RB #1614 <https://rbcommons.com/s/twitter/r/1614>`_

* Adding the ability to pull in a Maven artifact and extract its contents
  `RB #1210 <https://rbcommons.com/s/twitter/r/1210>`_

* Allow FingerprintStrategy to opt out of fingerprinting
  `RB #1602 <https://rbcommons.com/s/twitter/r/1602>`_

* Remove the ivy_home property from context
  `RB #1592 <https://rbcommons.com/s/twitter/r/1592>`_

* Refactor setting of PYTHONPATH in pants.ini
  `RB #1586 <https://rbcommons.com/s/twitter/r/1586>`_

* Relocate 'to_jar_dependencies' method back to jar_library
  `RB #1574 <https://rbcommons.com/s/twitter/r/1574>`_

* Update protobuf_gen to be able to reference sources outside of the subdirectory of the BUILD file
  `RB #1573 <https://rbcommons.com/s/twitter/r/1573>`_

* Kill goal dependencies
  `RB #1577 <https://rbcommons.com/s/twitter/r/1577>`_

* Move excludes logic into cmd_line_spec_parser so it can filter out broken build targets
  `RB #930 <https://rbcommons.com/s/twitter/r/930>`_
  `RB #1566 <https://rbcommons.com/s/twitter/r/1566>`_

* Replace exclusives_groups with a compile_classpath product
  `RB #1539 <https://rbcommons.com/s/twitter/r/1539>`_

* Allow adding to pythonpath via pant.ini
  `RB #1457 <https://rbcommons.com/s/twitter/r/1457>`_

0.0.27 (12/19/2014)
-------------------

Bugfixes
~~~~~~~~

* Fix python doc: "repl" and "setup-py" are goals now, don't use "py"
  `RB #1302 <https://rbcommons.com/s/twitter/r/1302>`_

* Fix python thrift generation
  `RB #1517 <https://rbcommons.com/s/twitter/r/1517>`_

* Fixup migrate_config to use new Config API
  `RB #1514 <https://rbcommons.com/s/twitter/r/1514>`_

0.0.26 (12/17/2014)
-------------------

Bugfixes
~~~~~~~~

* Fix the `ScroogeGen` target selection predicate
  `RB #1497 <https://rbcommons.com/s/twitter/r/1497>`_

0.0.25 (12/17/2014)
-------------------

API Changes
~~~~~~~~~~~

* Flesh out and convert to the new options system introduced in `pantsbuild.pants` 0.0.24

  - Support loading config from multiple files
  - Support option reads via indexing
  - Add a `migrate_config` tool
  - Migrate tasks to the option registration system
  - Get rid of the old config registration mechanism
  - Add passthru arg support in the new options system
  - Support passthru args in tasks
  - Allow a task type know its own options scope
  - Support old-style flags even in the new flag system

  `RB #1093 <https://rbcommons.com/s/twitter/r/1093>`_
  `RB #1094 <https://rbcommons.com/s/twitter/r/1094>`_
  `RB #1095 <https://rbcommons.com/s/twitter/r/1095>`_
  `RB #1096 <https://rbcommons.com/s/twitter/r/1096>`_
  `RB #1097 <https://rbcommons.com/s/twitter/r/1097>`_
  `RB #1102 <https://rbcommons.com/s/twitter/r/1102>`_
  `RB #1109 <https://rbcommons.com/s/twitter/r/1109>`_
  `RB #1114 <https://rbcommons.com/s/twitter/r/1114>`_
  `RB #1124 <https://rbcommons.com/s/twitter/r/1124>`_
  `RB #1125 <https://rbcommons.com/s/twitter/r/1125>`_
  `RB #1127 <https://rbcommons.com/s/twitter/r/1127>`_
  `RB #1129 <https://rbcommons.com/s/twitter/r/1129>`_
  `RB #1131 <https://rbcommons.com/s/twitter/r/1131>`_
  `RB #1135 <https://rbcommons.com/s/twitter/r/1135>`_
  `RB #1138 <https://rbcommons.com/s/twitter/r/1138>`_
  `RB #1140 <https://rbcommons.com/s/twitter/r/1140>`_
  `RB #1146 <https://rbcommons.com/s/twitter/r/1146>`_
  `RB #1147 <https://rbcommons.com/s/twitter/r/1147>`_
  `RB #1170 <https://rbcommons.com/s/twitter/r/1170>`_
  `RB #1175 <https://rbcommons.com/s/twitter/r/1175>`_
  `RB #1183 <https://rbcommons.com/s/twitter/r/1183>`_
  `RB #1186 <https://rbcommons.com/s/twitter/r/1186>`_
  `RB #1192 <https://rbcommons.com/s/twitter/r/1192>`_
  `RB #1195 <https://rbcommons.com/s/twitter/r/1195>`_
  `RB #1203 <https://rbcommons.com/s/twitter/r/1203>`_
  `RB #1211 <https://rbcommons.com/s/twitter/r/1211>`_
  `RB #1212 <https://rbcommons.com/s/twitter/r/1212>`_
  `RB #1214 <https://rbcommons.com/s/twitter/r/1214>`_
  `RB #1218 <https://rbcommons.com/s/twitter/r/1218>`_
  `RB #1223 <https://rbcommons.com/s/twitter/r/1223>`_
  `RB #1225 <https://rbcommons.com/s/twitter/r/1225>`_
  `RB #1229 <https://rbcommons.com/s/twitter/r/1229>`_
  `RB #1230 <https://rbcommons.com/s/twitter/r/1230>`_
  `RB #1231 <https://rbcommons.com/s/twitter/r/1231>`_
  `RB #1232 <https://rbcommons.com/s/twitter/r/1232>`_
  `RB #1234 <https://rbcommons.com/s/twitter/r/1234>`_
  `RB #1236 <https://rbcommons.com/s/twitter/r/1236>`_
  `RB #1244 <https://rbcommons.com/s/twitter/r/1244>`_
  `RB #1248 <https://rbcommons.com/s/twitter/r/1248>`_
  `RB #1251 <https://rbcommons.com/s/twitter/r/1251>`_
  `RB #1258 <https://rbcommons.com/s/twitter/r/1258>`_
  `RB #1269 <https://rbcommons.com/s/twitter/r/1269>`_
  `RB #1270 <https://rbcommons.com/s/twitter/r/1270>`_
  `RB #1276 <https://rbcommons.com/s/twitter/r/1276>`_
  `RB #1281 <https://rbcommons.com/s/twitter/r/1281>`_
  `RB #1286 <https://rbcommons.com/s/twitter/r/1286>`_
  `RB #1289 <https://rbcommons.com/s/twitter/r/1289>`_
  `RB #1297 <https://rbcommons.com/s/twitter/r/1297>`_
  `RB #1300 <https://rbcommons.com/s/twitter/r/1300>`_
  `RB #1308 <https://rbcommons.com/s/twitter/r/1308>`_
  `RB #1309 <https://rbcommons.com/s/twitter/r/1309>`_
  `RB #1317 <https://rbcommons.com/s/twitter/r/1317>`_
  `RB #1320 <https://rbcommons.com/s/twitter/r/1320>`_
  `RB #1323 <https://rbcommons.com/s/twitter/r/1323>`_
  `RB #1328 <https://rbcommons.com/s/twitter/r/1328>`_
  `RB #1341 <https://rbcommons.com/s/twitter/r/1341>`_
  `RB #1343 <https://rbcommons.com/s/twitter/r/1343>`_
  `RB #1351 <https://rbcommons.com/s/twitter/r/1351>`_
  `RB #1357 <https://rbcommons.com/s/twitter/r/1357>`_
  `RB #1373 <https://rbcommons.com/s/twitter/r/1373>`_
  `RB #1375 <https://rbcommons.com/s/twitter/r/1375>`_
  `RB #1385 <https://rbcommons.com/s/twitter/r/1385>`_
  `RB #1389 <https://rbcommons.com/s/twitter/r/1389>`_
  `RB #1399 <https://rbcommons.com/s/twitter/r/1399>`_
  `RB #1409 <https://rbcommons.com/s/twitter/r/1409>`_
  `RB #1435 <https://rbcommons.com/s/twitter/r/1435>`_
  `RB #1441 <https://rbcommons.com/s/twitter/r/1441>`_
  `RB #1442 <https://rbcommons.com/s/twitter/r/1442>`_
  `RB #1443 <https://rbcommons.com/s/twitter/r/1443>`_
  `RB #1451 <https://rbcommons.com/s/twitter/r/1451>`_

* Kill `Commands` and move all actions to `Tasks` in the goal infrastructure

  - Kill pants own use of the deprecated goal command
  - Restore the deprecation warning for specifying 'goal' on the cmdline
  - Get rid of the Command class completely
  - Enable passthru args for python run

  `RB #1321 <https://rbcommons.com/s/twitter/r/1321>`_
  `RB #1327 <https://rbcommons.com/s/twitter/r/1327>`_
  `RB #1394 <https://rbcommons.com/s/twitter/r/1394>`_
  `RB #1402 <https://rbcommons.com/s/twitter/r/1402>`_
  `RB #1448 <https://rbcommons.com/s/twitter/r/1448>`_
  `RB #1453 <https://rbcommons.com/s/twitter/r/1453>`_
  `RB #1465 <https://rbcommons.com/s/twitter/r/1465>`_
  `RB #1471 <https://rbcommons.com/s/twitter/r/1471>`_
  `RB #1476 <https://rbcommons.com/s/twitter/r/1476>`_
  `RB #1479 <https://rbcommons.com/s/twitter/r/1479>`_

* Add support for loading plugins via standard the pkg_resources entry points mechanism
  `RB #1429 <https://rbcommons.com/s/twitter/r/1429>`_
  `RB #1444 <https://rbcommons.com/s/twitter/r/1444>`_

* Many performance improvements and bugfixes to the artifact caching subsystem

  - Use a requests `Session` to enable connection pooling
  - Make CacheKey hash and pickle friendly
  - Multiprocessing Cache Check and Write
  - Skip compressing/writing artifacts that are already in the cache
  - Add the ability for JVM targets to refuse to allow themselves to be cached in the artifact cache
  - Fix name of non-fatal cache exception
  - Fix the issue of seeing "Error while writing to artifact cache: an integer is required"
    during [cache check]
  - Fix all uncompressed artifacts stored as just `.tar`

  `RB #981 <https://rbcommons.com/s/twitter/r/981>`_
  `RB #986 <https://rbcommons.com/s/twitter/r/986>`_
  `RB #1022 <https://rbcommons.com/s/twitter/r/1022>`_
  `RB #1197 <https://rbcommons.com/s/twitter/r/1197>`_
  `RB #1206 <https://rbcommons.com/s/twitter/r/1206>`_
  `RB #1233 <https://rbcommons.com/s/twitter/r/1233>`_
  `RB #1261 <https://rbcommons.com/s/twitter/r/1261>`_
  `RB #1264 <https://rbcommons.com/s/twitter/r/1264>`_
  `RB #1265 <https://rbcommons.com/s/twitter/r/1265>`_
  `RB #1272 <https://rbcommons.com/s/twitter/r/1272>`_
  `RB #1274 <https://rbcommons.com/s/twitter/r/1274>`_
  `RB #1249 <https://rbcommons.com/s/twitter/r/1249>`_
  `RB #1310 <https://rbcommons.com/s/twitter/r/1310>`_

* More enhancements to the `depmap` goal to support IDE plugins:

  - Add Pants Target Type to `depmap` to identify scala target VS java target
  - Add java_sources to the `depmap` info
  - Add transitive jar dependencies to `depmap` project info goal for intellij plugin

  `RB #1366 <https://rbcommons.com/s/twitter/r/1366>`_
  `RB #1324 <https://rbcommons.com/s/twitter/r/1324>`_
  `RB #1047 <https://rbcommons.com/s/twitter/r/1047>`_

* Port pants to pex 0.8.x
  `Issue #10 <https://github.com/pantsbuild/pex/issues/10>`_
  `Issue #19 <https://github.com/pantsbuild/pex/issues/19>`_
  `Issue #21 <https://github.com/pantsbuild/pex/issues/21>`_
  `Issue #22 <https://github.com/pantsbuild/pex/issues/22>`_
  `RB #778 <https://rbcommons.com/s/twitter/r/778>`_
  `RB #785 <https://rbcommons.com/s/twitter/r/785>`_
  `RB #1303 <https://rbcommons.com/s/twitter/r/1303>`_
  `RB #1378 <https://rbcommons.com/s/twitter/r/1378>`_
  `RB #1421 <https://rbcommons.com/s/twitter/r/1421>`_

* Remove support for __file__ in BUILDs
  `RB #1419 <https://rbcommons.com/s/twitter/r/1419>`_

* Allow setting the cwd for goals `run.jvm` and `test.junit`
  `RB #1344 <https://rbcommons.com/s/twitter/r/1344>`_

* Subclasses of `Exception` have strange deserialization
  `RB #1395 <https://rbcommons.com/s/twitter/r/1395>`_

* Remove outer (pants_exe) lock and serialized cmd
  `RB #1388 <https://rbcommons.com/s/twitter/r/1388>`_

* Make all access to `Context`'s lock via helpers
  `RB #1391 <https://rbcommons.com/s/twitter/r/1391>`_

* Allow adding entries to `source_roots`
  `RB #1359 <https://rbcommons.com/s/twitter/r/1359>`_

* Re-upload artifacts that encountered read-errors
  `RB #1361 <https://rbcommons.com/s/twitter/r/1361>`_

* Cache files created by (specially designed) annotation processors
  `RB #1250 <https://rbcommons.com/s/twitter/r/1250>`_

* Turn dependency dupes into errors
  `RB #1332 <https://rbcommons.com/s/twitter/r/1332>`_

* Add support for the Wire protobuf library
  `RB #1275 <https://rbcommons.com/s/twitter/r/1275>`_

* Pin pants support down to python2.7 - dropping 2.6
  `RB #1278 <https://rbcommons.com/s/twitter/r/1278>`_

* Add a new param for page target, links, a list of hyperlinked-to targets
  `RB #1242 <https://rbcommons.com/s/twitter/r/1242>`_

* Add git root calculation for idea goal
  `RB #1189 <https://rbcommons.com/s/twitter/r/1189>`_

* Minimal target "tags" support
  `RB #1227 <https://rbcommons.com/s/twitter/r/1227>`_

* Include traceback with failures (even without fail-fast)
  `RB #1226 <https://rbcommons.com/s/twitter/r/1226>`_

* Add support for updating the environment from prep_commands
  `RB #1222 <https://rbcommons.com/s/twitter/r/1222>`_

* Read arguments for thrift-linter from `pants.ini`
  `RB #1215 <https://rbcommons.com/s/twitter/r/1215>`_

* Configurable Compression Level for Cache Artifacts
  `RB #1194 <https://rbcommons.com/s/twitter/r/1194>`_

* Add a flexible directory re-mapper for the bundle
  `RB #1181 <https://rbcommons.com/s/twitter/r/1181>`_

* Adds the ability to pass a filter method for ZIP extraction
  `RB #1199 <https://rbcommons.com/s/twitter/r/1199>`_

* Print a diagnostic if a BUILD file references a source file that does not exist
  `RB #1198 <https://rbcommons.com/s/twitter/r/1198>`_

* Add support for running a command before tests
  `RB #1179 <https://rbcommons.com/s/twitter/r/1179>`_
  `RB #1177 <https://rbcommons.com/s/twitter/r/1177>`_

* Add `PantsRunIntegrationTest` into `pantsbuild.pants.testinfra` package
  `RB #1185 <https://rbcommons.com/s/twitter/r/1185>`_

* Refactor `jar_library` to be able to unwrap its list of jar_dependency objects
  `RB #1165 <https://rbcommons.com/s/twitter/r/1165>`_

* When resolving a tool dep, report back the `pants.ini` section with a reference that is failing
  `RB #1162 <https://rbcommons.com/s/twitter/r/1162>`_

* Add a list assertion for `python_requirement_library`'s requirements
  `RB #1142 <https://rbcommons.com/s/twitter/r/1142>`_

* Adding a list of dirs to exclude from the '::' scan in the `CmdLineSpecParser`
  `RB #1091 <https://rbcommons.com/s/twitter/r/1091>`_

* Protobuf and payload cleanups
  `RB #1099 <https://rbcommons.com/s/twitter/r/1099>`_

* Coalesce errors when parsing BUILDS in a spec
  `RB #1061 <https://rbcommons.com/s/twitter/r/1061>`_

* Refactor Payload
  `RB #1063 <https://rbcommons.com/s/twitter/r/1063>`_

* Add support for publishing plugins to pants
  `RB #1021 <https://rbcommons.com/s/twitter/r/1021>`_

Bugfixes
~~~~~~~~

* Numerous doc improvements & generation fixes

  - Updates to the pants essentials tech talk based on another dry-run
  - On skinny displays, don't show navigation UI by default
  - Handy rbt status tip from RBCommons newsletter
  - Document how to create a simple plugin
  - Update many bash examples that used old-style flags
  - Update Pants+IntelliJ docs to say the Plugin's the new hotness, link to plugin's README
  - Publish docs the new way
  - Update the "Pants Essentials" tech talk slides
  - Convert `.rst` files -> `.md` files
  - For included code snippets, don't just slap in a pre, provide syntax highlighting
  - Add notes about JDK versions supported
  - Dust off the Task Developer's Guide and `rm` the "pagerank" example
  - Add a `sitegen` task, create site with better navigation
  - For 'goal builddict', generate `.rst` and `.html`, not just `.rst`
  - Narrow setup 'Operating System' classfiers to known-good

  `Issue #16 <https://github.com/pantsbuild/pex/issues/16>`_
  `Issue #461 <https://github.com/pantsbuild/pants/issues/461>`_
  `Issue #739 <https://github.com/pantsbuild/pants/issues/739>`_
  `RB #891 <https://rbcommons.com/s/twitter/r/891>`_
  `RB #1074 <https://rbcommons.com/s/twitter/r/1074>`_
  `RB #1075 <https://rbcommons.com/s/twitter/r/1075>`_
  `RB #1079 <https://rbcommons.com/s/twitter/r/1079>`_
  `RB #1084 <https://rbcommons.com/s/twitter/r/1084>`_
  `RB #1086 <https://rbcommons.com/s/twitter/r/1086>`_
  `RB #1088 <https://rbcommons.com/s/twitter/r/1088>`_
  `RB #1090 <https://rbcommons.com/s/twitter/r/1090>`_
  `RB #1101 <https://rbcommons.com/s/twitter/r/1101>`_
  `RB #1126 <https://rbcommons.com/s/twitter/r/1126>`_
  `RB #1128 <https://rbcommons.com/s/twitter/r/1128>`_
  `RB #1134 <https://rbcommons.com/s/twitter/r/1134>`_
  `RB #1136 <https://rbcommons.com/s/twitter/r/1136>`_
  `RB #1154 <https://rbcommons.com/s/twitter/r/1154>`_
  `RB #1155 <https://rbcommons.com/s/twitter/r/1155>`_
  `RB #1164 <https://rbcommons.com/s/twitter/r/1164>`_
  `RB #1166 <https://rbcommons.com/s/twitter/r/1166>`_
  `RB #1176 <https://rbcommons.com/s/twitter/r/1176>`_
  `RB #1178 <https://rbcommons.com/s/twitter/r/1178>`_
  `RB #1182 <https://rbcommons.com/s/twitter/r/1182>`_
  `RB #1191 <https://rbcommons.com/s/twitter/r/1191>`_
  `RB #1196 <https://rbcommons.com/s/twitter/r/1196>`_
  `RB #1205 <https://rbcommons.com/s/twitter/r/1205>`_
  `RB #1241 <https://rbcommons.com/s/twitter/r/1241>`_
  `RB #1263 <https://rbcommons.com/s/twitter/r/1263>`_
  `RB #1277 <https://rbcommons.com/s/twitter/r/1277>`_
  `RB #1284 <https://rbcommons.com/s/twitter/r/1284>`_
  `RB #1292 <https://rbcommons.com/s/twitter/r/1292>`_
  `RB #1295 <https://rbcommons.com/s/twitter/r/1295>`_
  `RB #1296 <https://rbcommons.com/s/twitter/r/1296>`_
  `RB #1298 <https://rbcommons.com/s/twitter/r/1298>`_
  `RB #1299 <https://rbcommons.com/s/twitter/r/1299>`_
  `RB #1301 <https://rbcommons.com/s/twitter/r/1301>`_
  `RB #1314 <https://rbcommons.com/s/twitter/r/1314>`_
  `RB #1315 <https://rbcommons.com/s/twitter/r/1315>`_
  `RB #1326 <https://rbcommons.com/s/twitter/r/1326>`_
  `RB #1348 <https://rbcommons.com/s/twitter/r/1348>`_
  `RB #1355 <https://rbcommons.com/s/twitter/r/1355>`_
  `RB #1356 <https://rbcommons.com/s/twitter/r/1356>`_
  `RB #1358 <https://rbcommons.com/s/twitter/r/1358>`_
  `RB #1363 <https://rbcommons.com/s/twitter/r/1363>`_
  `RB #1370 <https://rbcommons.com/s/twitter/r/1370>`_
  `RB #1377 <https://rbcommons.com/s/twitter/r/1377>`_
  `RB #1386 <https://rbcommons.com/s/twitter/r/1386>`_
  `RB #1387 <https://rbcommons.com/s/twitter/r/1387>`_
  `RB #1401 <https://rbcommons.com/s/twitter/r/1401>`_
  `RB #1407 <https://rbcommons.com/s/twitter/r/1407>`_
  `RB #1427 <https://rbcommons.com/s/twitter/r/1427>`_
  `RB #1430 <https://rbcommons.com/s/twitter/r/1430>`_
  `RB #1434 <https://rbcommons.com/s/twitter/r/1434>`_
  `RB #1440 <https://rbcommons.com/s/twitter/r/1440>`_
  `RB #1446 <https://rbcommons.com/s/twitter/r/1446>`_
  `RB #1464 <https://rbcommons.com/s/twitter/r/1464>`_
  `RB #1484 <https://rbcommons.com/s/twitter/r/1484>`_
  `RB #1491 <https://rbcommons.com/s/twitter/r/1491>`_

* CmdLineProcessor uses `binary class name
  <http://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.2.1>`_
  `RB #1489 <https://rbcommons.com/s/twitter/r/1489>`_

* Use subscripting for looking up targets in resources_by_products
  `RB #1380 <https://rbcommons.com/s/twitter/r/1380>`_

* Fix/refactor checkstyle
  `RB #1432 <https://rbcommons.com/s/twitter/r/1432>`_

* Fix missing import
  `RB #1483 <https://rbcommons.com/s/twitter/r/1483>`_

* Make `./pants help` and `./pants help <goal>` work properly
  `Issue #839 <https://github.com/pantsbuild/pants/issues/839>`_
  `RB #1482 <https://rbcommons.com/s/twitter/r/1482>`_

* Cleanup after custom options bootstrapping in reflect
  `RB #1468 <https://rbcommons.com/s/twitter/r/1468>`_

* Handle UTF-8 in thrift files for python
  `RB #1459 <https://rbcommons.com/s/twitter/r/1459>`_

* Optimize goal changed
  `RB #1470 <https://rbcommons.com/s/twitter/r/1470>`_

* Fix a bug where a request for help wasn't detected
  `RB #1467 <https://rbcommons.com/s/twitter/r/1467>`_

* Always relativize the classpath where possible
  `RB #1455 <https://rbcommons.com/s/twitter/r/1455>`_

* Gracefully handle another run creating latest link
  `RB #1396 <https://rbcommons.com/s/twitter/r/1396>`_

* Properly detect existence of a symlink
  `RB #1437 <https://rbcommons.com/s/twitter/r/1437>`_

* Avoid throwing in `ApacheThriftGen.__init__`
  `RB #1428 <https://rbcommons.com/s/twitter/r/1428>`_

* Fix error message in scrooge_gen
  `RB #1426 <https://rbcommons.com/s/twitter/r/1426>`_

* Fixup `BuildGraph` to handle mixes of synthetic and BUILD targets
  `RB #1420 <https://rbcommons.com/s/twitter/r/1420>`_

* Fix antlr package derivation
  `RB #1410 <https://rbcommons.com/s/twitter/r/1410>`_

* Exit workers on sigint rather than ignore
  `RB #1405 <https://rbcommons.com/s/twitter/r/1405>`_

* Fix error in string formatting
  `RB #1416 <https://rbcommons.com/s/twitter/r/1416>`_

* Add missing class
  `RB #1414 <https://rbcommons.com/s/twitter/r/1414>`_

* Add missing import for dedent in `resource_mapping.py`
  `RB #1403 <https://rbcommons.com/s/twitter/r/1403>`_

* Replace twitter commons dirutil Lock with lockfile wrapper
  `RB #1390 <https://rbcommons.com/s/twitter/r/1390>`_

* Make `interpreter_cache` a property, acquire lock in accessor
  `Issue #819 <https://github.com/pantsbuild/pants/issues/819>`_
  `RB #1392 <https://rbcommons.com/s/twitter/r/1392>`_

* Fix `.proto` files with unicode characters in the comments
  `RB #1330 <https://rbcommons.com/s/twitter/r/1330>`_

* Make `pants goal run` for Python exit with error code 1 if the python program exits non-zero
  `RB #1374 <https://rbcommons.com/s/twitter/r/1374>`_

* Fix a bug related to adding sibling resource bases
  `RB #1367 <https://rbcommons.com/s/twitter/r/1367>`_

* Support for the `--kill-nailguns` option was inadvertently removed, this puts it back
  `RB #1352 <https://rbcommons.com/s/twitter/r/1352>`_

* fix string formatting so `test -h` does not crash
  `RB #1353 <https://rbcommons.com/s/twitter/r/1353>`_

* Fix java_sources missing dep detection
  `RB #1336 <https://rbcommons.com/s/twitter/r/1336>`_

* Fix a nasty bug when injecting target closures in BuildGraph
  `RB #1337 <https://rbcommons.com/s/twitter/r/1337>`_

* Switch `src/*` usages of `Config.load` to use `Config.from_cache` instead
  `RB #1319 <https://rbcommons.com/s/twitter/r/1319>`_

* Optimize `what_changed`, remove un-needed extra sort
  `RB #1291 <https://rbcommons.com/s/twitter/r/1291>`_

* Fix `DetectDuplicate`'s handling of an `append`-type flag
  `RB #1282 <https://rbcommons.com/s/twitter/r/1282>`_

* Deeper selection of internal targets during publishing
  `RB #1213 <https://rbcommons.com/s/twitter/r/1213>`_

* Correctly parse named_is_latest entries from the pushdb
  `RB #1245 <https://rbcommons.com/s/twitter/r/1245>`_

* Fix error message: add missing space
  `RB #1266 <https://rbcommons.com/s/twitter/r/1266>`_

* WikiArtifact instances also have provides; limit ivy to jvm
  `RB #1259 <https://rbcommons.com/s/twitter/r/1259>`_

* Fix `[run.junit]` -> `[test.junit]`
  `RB #1256 <https://rbcommons.com/s/twitter/r/1256>`_

* Fix signature in `goal targets` and BUILD dictionary
  `RB #1253 <https://rbcommons.com/s/twitter/r/1253>`_

* Fix the regression introduced in https://rbcommons.com/s/twitter/r/1186
  `RB #1254 <https://rbcommons.com/s/twitter/r/1254>`_

* Temporarily change `stderr` log level to silence `log.init` if `--quiet`
  `RB #1243 <https://rbcommons.com/s/twitter/r/1243>`_

* Add the environment's `PYTHONPATH` to `sys.path` when running dev pants
  `RB #1237 <https://rbcommons.com/s/twitter/r/1237>`_

* Remove `java_sources` as target roots for scala library in `depmap` project info
  `Issue #670 <https://github.com/pantsbuild/pants/issues/670>`_
  `RB #1190 <https://rbcommons.com/s/twitter/r/1190>`_

* Allow UTF-8 characters in changelog
  `RB #1228 <https://rbcommons.com/s/twitter/r/1228>`_

* Ensure proper semantics when replacing all tasks in a goal
  `RB #1220 <https://rbcommons.com/s/twitter/r/1220>`_
  `RB #1221 <https://rbcommons.com/s/twitter/r/1221>`_

* Fix reading of `scalac` plugin info from config
  `RB #1217 <https://rbcommons.com/s/twitter/r/1217>`_

* Dogfood bintray for pants support binaries
  `RB #1208 <https://rbcommons.com/s/twitter/r/1208>`_

* Do not crash on unicode filenames
  `RB #1193 <https://rbcommons.com/s/twitter/r/1193>`_
  `RB #1209 <https://rbcommons.com/s/twitter/r/1209>`_

* In the event of an exception in `jvmdoc_gen`, call `get()` on the remaining futures
  `RB #1202 <https://rbcommons.com/s/twitter/r/1202>`_

* Move `workdirs` creation from `__init__` to `pre_execute` in jvm_compile & Remove
  `QuietTaskMixin` from several tasks
  `RB #1173 <https://rbcommons.com/s/twitter/r/1173>`_

* Switch from `os.rename` to `shutil.move` to support cross-fs renames when needed
  `RB #1157 <https://rbcommons.com/s/twitter/r/1157>`_

* Fix scalastyle task, wire it up, make configs optional
  `RB #1145 <https://rbcommons.com/s/twitter/r/1145>`_

* Fix issue 668: make `release.sh` execute packaged pants without loading internal backends
  during testing
  `Issue #668 <https://github.com/pantsbuild/pants/issues/668>`_
  `RB #1158 <https://rbcommons.com/s/twitter/r/1158>`_

* Add `payload.get_field_value()` to fix KeyError from `pants goal idea testprojects::`
  `RB #1150 <https://rbcommons.com/s/twitter/r/1150>`_

* Remove `debug_args` from `pants.ini`
  `Issue #650 <https://github.com/pantsbuild/pants/issues/650>`_
  `RB #1137 <https://rbcommons.com/s/twitter/r/1137>`_

* When a jvm doc tool (e.g. scaladoc) fails in combined mode, throw an exception
  `RB #1116 <https://rbcommons.com/s/twitter/r/1116>`_

* Remove hack to add java_sources in context
  `RB #1130 <https://rbcommons.com/s/twitter/r/1130>`_

* Memoize `Address.__hash__` computation
  `RB #1118 <https://rbcommons.com/s/twitter/r/1118>`_

* Add missing coverage deps
  `RB #1117 <https://rbcommons.com/s/twitter/r/1117>`_

* get `goal targets` using similar codepath to `goal builddict`
  `RB #1112 <https://rbcommons.com/s/twitter/r/1112>`_

* Memoize fingerprints by the FPStrategy hash
  `RB #1119 <https://rbcommons.com/s/twitter/r/1119>`_

* Factor in the jvm version string into the nailgun executor fingerprint
  `RB #1122 <https://rbcommons.com/s/twitter/r/1122>`_

* Fix some error reporting issues
  `RB #1113 <https://rbcommons.com/s/twitter/r/1113>`_

* Retry on failed scm push; also, pull with rebase to increase the odds of success
  `RB #1083 <https://rbcommons.com/s/twitter/r/1083>`_

* Make sure that 'option java_package' always overrides 'package' in protobuf_gen
  `RB #1108 <https://rbcommons.com/s/twitter/r/1108>`_

* Fix order-dependent force handling: if a version is forced in one place, it is forced everywhere
  `RB #1085 <https://rbcommons.com/s/twitter/r/1085>`_

* Survive targets without derivations
  `RB #1066 <https://rbcommons.com/s/twitter/r/1066>`_

* Make `internal_backend` plugins 1st class local pants plugins
  `RB #1073 <https://rbcommons.com/s/twitter/r/1073>`_

0.0.24 (9/23/2014)
------------------

API Changes
~~~~~~~~~~~

* Add a whitelist to jvm dependency analyzer
  `RB #888 <https://rbcommons.com/s/twitter/r/888>`_

* Refactor exceptions in build_file.py and build_file_parser.py to derive from a common baseclass
  and eliminate throwing `IOError`.
  `RB #954 <https://rbcommons.com/s/twitter/r/954>`_

* Support absolute paths on the command line when they start with the build root
  `RB #867 <https://rbcommons.com/s/twitter/r/867>`_

* Make `::` fail for an invalid dir much like `:` does for a dir with no BUILD file
  `Issue #484 <https://github.com/pantsbuild/pants/issues/484>`_
  `RB #907 <https://rbcommons.com/s/twitter/r/907>`_

* Deprecate `pants` & `dependencies` aliases and remove `config`, `goal`, `phase`,
  `get_scm` & `set_scm` aliases
  `RB #899 <https://rbcommons.com/s/twitter/r/899>`_
  `RB #903 <https://rbcommons.com/s/twitter/r/903>`_
  `RB #912 <https://rbcommons.com/s/twitter/r/912>`_

* Export test infrastructure for plugin writers to use in `pantsbuild.pants.testinfra` sdist
  `Issue #539 <https://github.com/pantsbuild/pants/issues/539>`_
  `RB #997 <https://rbcommons.com/s/twitter/r/997>`_
  `RB #1004 <https://rbcommons.com/s/twitter/r/1004>`_

* Publishing improvements:

  - Add support for doing remote publishes with an explicit snapshot name
  - One publish/push db file per artifact

  `RB #923 <https://rbcommons.com/s/twitter/r/923>`_
  `RB #994 <https://rbcommons.com/s/twitter/r/994>`_

* Several improvements to `IdeGen` derived goals:

  - Adds the `--<goal>-use-source-root` for IDE project generation tasks
  - Added `--idea-exclude-maven-target` to keep IntelliJ from indexing 'target' directories
  - Changes the behavior of goal idea to create a subdirectory named for the project name
  - Added `exclude-folders` option in pants.ini, defaulted to excluding a few dirs in `.pants.d`

  `Issue #564 <https://github.com/pantsbuild/pants/issues/564>`_
  `RB #1006 <https://rbcommons.com/s/twitter/r/1006>`_
  `RB #1017 <https://rbcommons.com/s/twitter/r/1017>`_
  `RB #1019 <https://rbcommons.com/s/twitter/r/1019>`_
  `RB #1023 <https://rbcommons.com/s/twitter/r/1023>`_

* Enhancements to the `depmap` goal to support IDE plugins:

  - Add flag to dump project info output to file
  - Add missing resources to targets
  - Add content type to project Info

  `Issue #5 <https://github.com/pantsbuild/intellij-pants-plugin/issues/5>`_
  `RB #964 <https://rbcommons.com/s/twitter/r/964>`_
  `RB #987 <https://rbcommons.com/s/twitter/r/987>`_
  `RB #998 <https://rbcommons.com/s/twitter/r/998>`_

* Make `SourceRoot` fundamentally understand a rel_path
  `RB #1036 <https://rbcommons.com/s/twitter/r/1036>`_

* Added thrift-linter to pants
  `RB #1044 <https://rbcommons.com/s/twitter/r/1044>`_

* Support limiting coverage measurements globally by module or path
  `Issue #328 <https://github.com/pantsbuild/pants/issues/328>`_
  `Issue #369 <https://github.com/pantsbuild/pants/issues/369>`_
  `RB #1034 <https://rbcommons.com/s/twitter/r/1034>`_

* Update interpreter_cache.py to support a repo-wide interpreter requirement
  `RB #1025 <https://rbcommons.com/s/twitter/r/1025>`_

* Changed goal markdown:

  - Writes output to `./dist/markdown/`
  - Pages can include snippets from source files
    `<http://pantsbuild.github.io/page.html#include-a-file-snippet>`_

  `Issue #535 <https://github.com/pantsbuild/pants/issues/535>`_
  `RB #949 <https://rbcommons.com/s/twitter/r/949>`_
  `RB #961 <https://rbcommons.com/s/twitter/r/961>`_

* Rename `Phase` -> `Goal`
  `RB #856 <https://rbcommons.com/s/twitter/r/856>`_
  `RB #879 <https://rbcommons.com/s/twitter/r/879>`_
  `RB #880 <https://rbcommons.com/s/twitter/r/880>`_
  `RB #887 <https://rbcommons.com/s/twitter/r/887>`_
  `RB #890 <https://rbcommons.com/s/twitter/r/890>`_
  `RB #910 <https://rbcommons.com/s/twitter/r/910>`_
  `RB #913 <https://rbcommons.com/s/twitter/r/913>`_
  `RB #915 <https://rbcommons.com/s/twitter/r/915>`_
  `RB #931 <https://rbcommons.com/s/twitter/r/931>`_

* Android support additions:

  - Add `AaptBuild` task
  - Add `JarsignerTask` and `Keystore` target

  `RB #859 <https://rbcommons.com/s/twitter/r/859>`_
  `RB #883 <https://rbcommons.com/s/twitter/r/883>`_

* Git/Scm enhancements:

  - Allow the buildroot to be a subdirectory of the git worktree
  - Support getting the commit date of refs
  - Add merge-base and origin url properties to git

  `Issue #405 <https://github.com/pantsbuild/pants/issues/405>`_
  `RB #834 <https://rbcommons.com/s/twitter/r/834>`_
  `RB #871 <https://rbcommons.com/s/twitter/r/871>`_
  `RB #884 <https://rbcommons.com/s/twitter/r/884>`_
  `RB #886 <https://rbcommons.com/s/twitter/r/886>`_

Bugfixes
~~~~~~~~

* Numerous doc improvements & generation fixes
  `Issue #397 <https://github.com/pantsbuild/pants/issues/397>`_
  `Issue #451 <https://github.com/pantsbuild/pants/issues/451>`_
  `Issue #475 <https://github.com/pantsbuild/pants/issues/475>`_
  `RB #863 <https://rbcommons.com/s/twitter/r/863>`_
  `RB #865 <https://rbcommons.com/s/twitter/r/865>`_
  `RB #873 <https://rbcommons.com/s/twitter/r/873>`_
  `RB #876 <https://rbcommons.com/s/twitter/r/876>`_
  `RB #885 <https://rbcommons.com/s/twitter/r/885>`_
  `RB #938 <https://rbcommons.com/s/twitter/r/938>`_
  `RB #953 <https://rbcommons.com/s/twitter/r/953>`_
  `RB #960 <https://rbcommons.com/s/twitter/r/960>`_
  `RB #965 <https://rbcommons.com/s/twitter/r/965>`_
  `RB #992 <https://rbcommons.com/s/twitter/r/992>`_
  `RB #995 <https://rbcommons.com/s/twitter/r/995>`_
  `RB #1007 <https://rbcommons.com/s/twitter/r/1007>`_
  `RB #1008 <https://rbcommons.com/s/twitter/r/1008>`_
  `RB #1018 <https://rbcommons.com/s/twitter/r/1018>`_
  `RB #1020 <https://rbcommons.com/s/twitter/r/1020>`_
  `RB #1048 <https://rbcommons.com/s/twitter/r/1048>`_

* Fixup missing 'page.mustache' resource for `markdown` goal
  `Issue #498 <https://github.com/pantsbuild/pants/issues/498>`_
  `RB #918 <https://rbcommons.com/s/twitter/r/918>`_

* Publishing fixes:

  - Fix credentials fetching during publishing
  - Skipping a doc phase should result in transitive deps being skipped as well

  `RB #901 <https://rbcommons.com/s/twitter/r/901>`_
  `RB #1011 <https://rbcommons.com/s/twitter/r/1011>`_

* Several `IdeGen` derived task fixes:

  - Fix eclipse_gen & idea_gen for targets with both java and scala
  - Fixup EclipseGen resources globs to include prefs.
  - When a directory contains both `java_library` and `junit_tests` targets, make sure the IDE
    understands this is a test path, not a lib path

  `RB #857 <https://rbcommons.com/s/twitter/r/857>`_
  `RB #916 <https://rbcommons.com/s/twitter/r/916>`_
  `RB #996 <https://rbcommons.com/s/twitter/r/996>`_

* Fixes to the `depmap` goal to support IDE plugins:

  - Fixed source roots in project info in case of `ScalaLibrary` with `java_sources`
  - Fix `--depmap-project-info` for scala sources with the same package_prefix
  - Fix depmap KeyError

  `RB #955 <https://rbcommons.com/s/twitter/r/955>`_
  `RB #990 <https://rbcommons.com/s/twitter/r/990>`_
  `RB #1015 <https://rbcommons.com/s/twitter/r/1015>`_

* Make a better error message when os.symlink fails during bundle
  `RB #1037 <https://rbcommons.com/s/twitter/r/1037>`_

* Faster source root operations - update the internal data structure to include a tree
  `RB #1003 <https://rbcommons.com/s/twitter/r/1003>`_

* The goal filter's --filter-ancestor parameter works better now
  `Issue #506 <https://github.com/pantsbuild/pants/issues/506>`_
  `RB #925 <https://rbcommons.com/s/twitter/r/925/>`_

* Fix: goal markdown failed to load page.mustache
  `Issue #498 <https://github.com/pantsbuild/pants/issues/498>`_
  `RB #918 <https://rbcommons.com/s/twitter/r/918>`_

* Fix the `changed` goal so it can be run in a repo with a directory called 'build'
  `RB #872 <https://rbcommons.com/s/twitter/r/872>`_

* Patch `JvmRun` to accept `JvmApp`s
  `RB #893 <https://rbcommons.com/s/twitter/r/893>`_

* Add python as default codegen product
  `RB #894 <https://rbcommons.com/s/twitter/r/894>`_

* Fix the `filedeps` goal - it was using a now-gone .expand_files() API
  `Issue #437 <https://github.com/pantsbuild/pants/issues/437>`_,
  `RB #939 <https://rbcommons.com/s/twitter/r/939>`_

* Put back error message that shows path to missing BUILD files
  `RB #929 <https://rbcommons.com/s/twitter/r/929>`_

* Make sure the `junit_run` task only runs on targets that are junit compatible
  `Issue #508 <https://github.com/pantsbuild/pants/issues/508>`_
  `RB #924 <https://rbcommons.com/s/twitter/r/924>`_

* Fix `./pants goal targets`
  `Issue #333 <https://github.com/pantsbuild/pants/issues/333>`_
  `RB #796 <https://rbcommons.com/s/twitter/r/796>`_
  `RB #914 <https://rbcommons.com/s/twitter/r/914>`_

* Add `derived_from` to `ScroogeGen` synthetic targets
  `RB #926 <https://rbcommons.com/s/twitter/r/926>`_

* Properly order resources for pants goal test and pants goal run
  `RB #845 <https://rbcommons.com/s/twitter/r/845>`_

* Fixup Dependencies to be mainly target-type agnostic
  `Issue #499 <https://github.com/pantsbuild/pants/issues/499>`_
  `RB #920 <https://rbcommons.com/s/twitter/r/920>`_

* Fixup JvmRun only-write-cmd-line flag to accept relative paths
  `Issue #494 <https://github.com/pantsbuild/pants/issues/494>`_
  `RB #908 <https://rbcommons.com/s/twitter/r/908>`_
  `RB #911 <https://rbcommons.com/s/twitter/r/911>`_

* Fix the `--ivy-report` option and add integration test
  `RB #976 <https://rbcommons.com/s/twitter/r/976>`_

* Fix a regression in Emma/Cobertura and add tests
  `Issue #508 <https://github.com/pantsbuild/pants/issues/508>`_
  `RB #935 <https://rbcommons.com/s/twitter/r/935>`_

0.0.23 (8/11/2014)
------------------

API Changes
~~~~~~~~~~~

* Remove unused Task.invalidate_for method and unused extra_data variable
  `RB #849 <https://rbcommons.com/s/twitter/r/849>`_

* Add DxCompile task to android backend
  `RB #840 <https://rbcommons.com/s/twitter/r/840>`_

* Change all Task subclass constructor args to (\*args, \**kwargs)
  `RB #846 <https://rbcommons.com/s/twitter/r/846>`_

* The public API for the new options system
  `Issue #425 <https://github.com/pantsbuild/pants/pull/425>`_
  `RB #831 <https://rbcommons.com/s/twitter/r/831>`_
  `RB #819 <https://rbcommons.com/s/twitter/r/819>`_

* Rename pants.goal.goal.Goal to pants.goal.task_registrar.TaskRegistrar
  `Issue #345 <https://github.com/pantsbuild/pants/pull/345>`_
  `RB #843 <https://rbcommons.com/s/twitter/r/843>`_

Bugfixes
~~~~~~~~

* Better validation for AndroidTarget manifest field
  `RB #860 <https://rbcommons.com/s/twitter/r/860>`_

* Remove more references to /BUILD:target notation in docs
  `RB #855 <https://rbcommons.com/s/twitter/r/855>`_
  `RB #853 <https://rbcommons.com/s/twitter/r/853>`_

* Fix up the error message when attempting to publish without any configured repos
  `RB #850 <https://rbcommons.com/s/twitter/r/850>`_

* Miscellaneous fixes to protobuf codegen including handling collisions deterministically
  `RB #720 <https://rbcommons.com/s/twitter/r/720>`_

* Migrate some reasonable default values from pants.ini into 'defaults' in the pants source
  `Issue #455 <https://github.com/pantsbuild/pants/pull/455>`_
  `Issue #456 <https://github.com/pantsbuild/pants/pull/456>`_
  `Issue #458 <https://github.com/pantsbuild/pants/pull/458>`_
  `RB #852 <https://rbcommons.com/s/twitter/r/852>`_

* Updated the basename and name of some targets to prevent colliding bundles in dist/
  `RB #847 <https://rbcommons.com/s/twitter/r/847>`_

* Provide a better error message when referencing the wrong path to a BUILD file
  `RB #841 <https://rbcommons.com/s/twitter/r/841>`_

* Add assert_list to ensure an argument is a list - use this to better validate many targets
  `RB #811 <https://rbcommons.com/s/twitter/r/811>`_

* Update front-facing help and error messages for Android targets/tasks
  `RB #837 <https://rbcommons.com/s/twitter/r/837>`_

* Use JvmFingerprintStrategy in cache manager
  `RB #835 <https://rbcommons.com/s/twitter/r/835>`_

0.0.22 (8/4/2014)
-----------------

API Changes
~~~~~~~~~~~

* Upgrade pex dependency from twitter.common.python 0.6.0 to pex 0.7.0
  `RB #825 <https://rbcommons.com/s/twitter/r/825>`_

* Added a --spec-exclude command line flag to exclude specs by regular expression
  `RB #747 <https://rbcommons.com/s/twitter/r/747>`_

* Upgrade requests, flip to a ranged requirement to help plugins
  `RB #771 <https://rbcommons.com/s/twitter/r/771>`_

* New goal ``ensime`` to generate Ensime projects for Emacs users
  `RB #753 <https://rbcommons.com/s/twitter/r/753>`_

Bugfixes
~~~~~~~~

* `goal repl` consumes targets transitively
  `RB #781 <https://rbcommons.com/s/twitter/r/781>`_

* Fixup JvmCompile to always deliver non-None products that were required by downstream
  `RB #794 <https://rbcommons.com/s/twitter/r/794>`_

* Relativize classpath for non-ng java execution
  `RB #804 <https://rbcommons.com/s/twitter/r/804>`_

* Added some docs and a bugfix on debugging a JVM tool (like jar-tool or checkstyle) locally
  `RB #791 <https://rbcommons.com/s/twitter/r/791>`_

* Added an excludes attribute that is set to an empty set for all SourcePayload subclasses
  `Issue #414 <https://github.com/pantsbuild/pants/pull/414>`_
  `RB #793 <https://rbcommons.com/s/twitter/r/793>`_

* Add binary fetching support for OSX 10.10 and populate thrift and protoc binaries
  `RB #789 <https://rbcommons.com/s/twitter/r/789>`_

* Fix the pants script exit status when bootstrapping fails
  `RB #779 <https://rbcommons.com/s/twitter/r/779>`_

* Added benchmark target to maven_layout()
  `RB #780 <https://rbcommons.com/s/twitter/r/780>`_

* Fixup a hole in external dependency listing wrt encoding
  `RB #776 <https://rbcommons.com/s/twitter/r/776>`_

* Force parsing for filtering specs
  `RB #775 <https://rbcommons.com/s/twitter/r/775>`_

* Fix a scope bug for java agent manifest writing
  `RB #768 <https://rbcommons.com/s/twitter/r/768>`_
  `RB #770 <https://rbcommons.com/s/twitter/r/770>`_

* Plumb ivysettings.xml location to the publish template
  `RB #764 <https://rbcommons.com/s/twitter/r/764>`_

* Fix goal markdown: README.html pages clobbered each other
  `RB #750 <https://rbcommons.com/s/twitter/r/750>`_

0.0.21 (7/25/2014)
------------------

Bugfixes
~~~~~~~~

* Fixup NailgunTasks with missing config_section overrides
  `RB # 762 <https://rbcommons.com/s/twitter/r/762>`_

0.0.20 (7/25/2014)
------------------

API Changes
~~~~~~~~~~~

* Hide stack traces by default
  `Issue #326 <https://github.com/pantsbuild/pants/issues/326>`_
  `RB #655 <https://rbcommons.com/s/twitter/r/655>`_

* Upgrade to ``twitter.common.python`` 0.6.0 and adjust to api change
  `RB #746 <https://rbcommons.com/s/twitter/r/746>`_

* Add support for `Cobertura <http://cobertura.github.io/cobertura>`_ coverage
  `Issue #70 <https://github.com/pantsbuild/pants/issues/70>`_
  `RB #637 <https://rbcommons.com/s/twitter/r/637>`_

* Validate that ``junit_tests`` targets have non-empty sources
  `RB #619 <https://rbcommons.com/s/twitter/r/619>`_

* Add support for the `Ragel <http://www.complang.org/ragel>`_ state-machine generator
  `Issue #353 <https://github.com/pantsbuild/pants/issues/353>`_
  `RB #678 <https://rbcommons.com/s/twitter/r/678>`_

* Add ``AndroidTask`` and ``AaptGen`` tasks
  `RB #672 <https://rbcommons.com/s/twitter/r/672>`_
  `RB #676 <https://rbcommons.com/s/twitter/r/676>`_
  `RB #700 <https://rbcommons.com/s/twitter/r/700>`_

Bugfixes
~~~~~~~~

* Numerous doc fixes
  `Issue #385 <https://github.com/pantsbuild/pants/issues/385>`_
  `Issue #387 <https://github.com/pantsbuild/pants/issues/387>`_
  `Issue #395 <https://github.com/pantsbuild/pants/issues/395>`_
  `RB #728 <https://rbcommons.com/s/twitter/r/728>`_
  `RB #729 <https://rbcommons.com/s/twitter/r/729>`_
  `RB #730 <https://rbcommons.com/s/twitter/r/730>`_
  `RB #738 <https://rbcommons.com/s/twitter/r/738>`_

* Expose types needed to specify ``jvm_binary.deploy_jar_rules``
  `Issue #383 <https://github.com/pantsbuild/pants/issues/383>`_
  `RB #727 <https://rbcommons.com/s/twitter/r/727>`_

* Require information about jars in ``depmap`` with ``--depmap-project-info``
  `RB #721 <https://rbcommons.com/s/twitter/r/721>`_

0.0.19 (7/23/2014)
------------------

API Changes
~~~~~~~~~~~

* Enable Nailgun Per Task
  `RB #687 <https://rbcommons.com/s/twitter/r/687>`_

Bugfixes
~~~~~~~~

* Numerous doc fixes
  `RB #699 <https://rbcommons.com/s/twitter/r/699>`_
  `RB #703 <https://rbcommons.com/s/twitter/r/703>`_
  `RB #704 <https://rbcommons.com/s/twitter/r/704>`_

* Fixup broken ``bundle`` alias
  `Issue #375 <https://github.com/pantsbuild/pants/issues/375>`_
  `RB #722 <https://rbcommons.com/s/twitter/r/722>`_

* Remove dependencies on ``twitter.common.{dirutil,contextutils}``
  `RB #710 <https://rbcommons.com/s/twitter/r/710>`_
  `RB #713 <https://rbcommons.com/s/twitter/r/713>`_
  `RB #717 <https://rbcommons.com/s/twitter/r/717>`_
  `RB #718 <https://rbcommons.com/s/twitter/r/718>`_
  `RB #719 <https://rbcommons.com/s/twitter/r/719>`_
  `RB #726 <https://rbcommons.com/s/twitter/r/726>`_

* Fixup missing ``JunitRun`` resources requirement
  `RB #709 <https://rbcommons.com/s/twitter/r/709>`_

* Fix transitive dependencies for ``GroupIterator``/``GroupTask``
  `RB #706 <https://rbcommons.com/s/twitter/r/706>`_

* Ensure resources are prepared after compile
  `Issue #373 <http://github.com/pantsbuild/pants/issues/373>`_
  `RB #708 <https://rbcommons.com/s/twitter/r/708>`_

* Upgrade to ``twitter.common.python`` 0.5.10 to brings in the following bugfix::

    Update the mtime on retranslation of existing distributions.

    1bff97e stopped existing distributions from being overwritten, to
    prevent subtle errors. However without updating the mtime these
    distributions will appear to be permanently expired wrt the ttl.

  `RB #707 <https://rbcommons.com/s/twitter/r/707>`_

* Resurrected pants goal idea with work remaining on source and javadoc jar mapping
  `RB #695 <https://rbcommons.com/s/twitter/r/695>`_

* Fix BinaryUtil raise of BinaryNotFound
  `Issue #367 <https://github.com/pantsbuild/pants/issues/367>`_
  `RB #705 <https://rbcommons.com/s/twitter/r/705>`_

0.0.18 (7/16/2014)
------------------

API Changes
~~~~~~~~~~~

* Lock globs into ``rootdir`` and below
  `Issue #348 <https://github.com/pantsbuild/pants/issues/348>`_
  `RB #686 <https://rbcommons.com/s/twitter/r/686>`_

Bugfixes
~~~~~~~~

* Several doc fixes
  `RB #654 <https://rbcommons.com/s/twitter/r/654>`_
  `RB #693 <https://rbcommons.com/s/twitter/r/693>`_

* Fix relativity of antlr sources
  `RB #679 <https://rbcommons.com/s/twitter/r/679>`_

0.0.17 (7/15/2014)
------------------

* Initial published version of ``pantsbuild.pants``
