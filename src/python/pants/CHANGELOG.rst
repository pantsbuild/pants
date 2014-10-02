RELEASE HISTORY
===============

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

* Make `::` fail for an invalid dir much like `:` does for a dir with no BUILD file.
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

* Fixup Dependencies to be mainly target-type agnostic.
  `Issue #499 <https://github.com/pantsbuild/pants/issues/499>`_
  `RB #920 <https://rbcommons.com/s/twitter/r/920>`_

* Fixup JvmRun only-write-cmd-line flag to accept relative paths.
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

* New goal ``ensime`` to generate Ensime projects for Emacs users.
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

* Initial published version of ``pantsbuild.pants``.

