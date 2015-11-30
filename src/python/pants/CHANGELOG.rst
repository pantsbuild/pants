RELEASE HISTORY
===============

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
  `RB #, <https://rbcommons.com/s/twitter/r/1898/,>`_
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
