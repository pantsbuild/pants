Master Pre-Releases
===================

This document describes ``dev`` releases which occur weekly from master, and which do
not undergo the vetting associated with ``stable`` releases.


1.14.0.dev2 (1/11/2019)
----------------------

New Features
~~~~~~~~~~~~
* Rerun proto compilation when protos change (#7029)
  `PR #7029 <https://github.com/pantsbuild/pants/pull/7029>`_

Version updates
~~~~~~~~~~~~~~~
* Upgrade several dependencies to fix Py3 deprecations (#7053)
  `PR #7053 <https://github.com/pantsbuild/pants/pull/7053>`_

* Update pantsbuild/pants to scala 2.12, and bump the default patch version for 2.12 (#7035)
  `PR #7035 <https://github.com/pantsbuild/pants/pull/7035>`_

Bugfixes
~~~~~~~~
* [compile.rsc] fix key error; ensure java compiles get necessary zinc scala deps (#7038)
  `PR #7038 <https://github.com/pantsbuild/pants/pull/7038>`_

* Fix jvm compile unicode issues when using Python 3 (#6987)
  `PR #6987 <https://github.com/pantsbuild/pants/pull/6987>`_

* Revert "set PEX_PYTHON_PATH when invoking the checkstyle pex for pexrc to work (#7013)" (#7028)
  `PR #7013 <https://github.com/pantsbuild/pants/pull/7013>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Use homebrew addon feature in CI (#7062)
  `PR #7062 <https://github.com/pantsbuild/pants/pull/7062>`_

* Add `collections.abc` backport to fix deprecation warning (#7055)
  `PR #7055 <https://github.com/pantsbuild/pants/pull/7055>`_

* Improve symlink errors (#7054)
  `PR #7054 <https://github.com/pantsbuild/pants/pull/7054>`_

* Fix invalid escape sequence problems (#7056)
  `PR #7056 <https://github.com/pantsbuild/pants/pull/7056>`_

* Build rust code only once per platform in a CI run (#7047)
  `PR #7047 <https://github.com/pantsbuild/pants/pull/7047>`_

* Remote execution uses tower-grpc to start executions (#7049)
  `PR #7049 <https://github.com/pantsbuild/pants/pull/7049>`_

* Workaround for homebrew bug with osx shard (#7050)
  `PR #7050 <https://github.com/pantsbuild/pants/pull/7050>`_
  `Issue #5513 <https://github.com/Homebrew/brew/issues/5513>`_

* Support some conversions for prost protos (#7040)
  `PR #7040 <https://github.com/pantsbuild/pants/pull/7040>`_

* Expose 1.13.x in the docsite notes dropdown. (#7045)
  `PR #7045 <https://github.com/pantsbuild/pants/pull/7045>`_

* Reqwest uses rustls not openssl (#7002)
  `PR #7002 <https://github.com/pantsbuild/pants/pull/7002>`_

* Fix awscli install to be language agnostic. (#7033)
  `PR #7033 <https://github.com/pantsbuild/pants/pull/7033>`_

* Improve readability of integration test logging. (#7036)
  `PR #7036 <https://github.com/pantsbuild/pants/pull/7036>`_

* Generate protos for tower as well as grpcio (#7030)
  `PR #7030 <https://github.com/pantsbuild/pants/pull/7030>`_

* Ensure all rust crates have common prefix (#7031)
  `PR #7031 <https://github.com/pantsbuild/pants/pull/7031>`_

* Eliminate bs4 warning. (#7027)
  `PR #7027 <https://github.com/pantsbuild/pants/pull/7027>`_


1.14.0.dev1 (1/4/2019)
----------------------

New Features
~~~~~~~~~~~~

* Validate yield statements in rule bodies to remove ambiguity about returning (#7019)
  `PR #7019 <https://github.com/pantsbuild/pants/pull/7019>`_

* Add support for consuming Subsystems from @rules (#6993)
  `PR #6993 <https://github.com/pantsbuild/pants/pull/6993>`_

* add rules to plugins and add some integration tests, maybe (#6892)
  `PR #6892 <https://github.com/pantsbuild/pants/pull/6892>`_

Version updates
~~~~~~~~~~~~~~~

* Update to rust 2018 (#6867)
  `PR #6867 <https://github.com/pantsbuild/pants/pull/6867>`_

Bugfixes
~~~~~~~~

* set PEX_PYTHON_PATH when invoking the checkstyle pex for pexrc to work (#7013)
  `PR #7013 <https://github.com/pantsbuild/pants/pull/7013>`_

* fix binary_util.py main method, add unit test, and kill integration test (#7010)
  `PR #7010 <https://github.com/pantsbuild/pants/pull/7010>`_

* Markdown writer errors are written properly (#6975)
  `PR #6975 <https://github.com/pantsbuild/pants/pull/6975>`_

* Fix unused_must_use, error in the futrue (#6999)
  `PR #6999 <https://github.com/pantsbuild/pants/pull/6999>`_

* Add python version to the native cache key (#6991)
  `PR #6991 <https://github.com/pantsbuild/pants/pull/6991>`_

* Fix invalid escape sequence & regex expression deprecations (#6984)
  `PR #6984 <https://github.com/pantsbuild/pants/pull/6984>`_

* Fix test_checkstyle.py interpreter constraint  (#6983)
  `PR #6983 <https://github.com/pantsbuild/pants/pull/6983>`_
  `PR #6959 <https://github.com/pantsbuild/pants/pull/6959>`_

* Fix native.py unicode issue leading to compile error with Python 3 (#6982)
  `PR #6982 <https://github.com/pantsbuild/pants/pull/6982>`_

* Fix python_artifact fingerprint unicode issue for Python 3 (#6971)
  `PR #6971 <https://github.com/pantsbuild/pants/pull/6971>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Eliminate dead code warnings. (#7018)
  `PR #7018 <https://github.com/pantsbuild/pants/pull/7018>`_

* Retrofit the Conan tool using PythonToolBase. (#6992)
  `PR #6992 <https://github.com/pantsbuild/pants/pull/6992>`_

* A preliminary bootstrapping CI stage, to prevent repeated work in each CI shard. (#7012)
  `PR #7012 <https://github.com/pantsbuild/pants/pull/7012>`_

* add unit testing for requesting transitively available products (#7015)
  `PR #7015 <https://github.com/pantsbuild/pants/pull/7015>`_

* When compiling with rsc, metacp java libraries in a separate execution graph node. (#6940)
  `PR #6940 <https://github.com/pantsbuild/pants/pull/6940>`_

* digest returns hashing::Digest (#7006)
  `PR #7006 <https://github.com/pantsbuild/pants/pull/7006>`_

* Fix all rust clippy warnings (#7001)
  `PR #7001 <https://github.com/pantsbuild/pants/pull/7001>`_

* Engine can store dict (#6996)
  `PR #6996 <https://github.com/pantsbuild/pants/pull/6996>`_

* Programatically add rust config to vendored protos (#7000)
  `PR #7000 <https://github.com/pantsbuild/pants/pull/7000>`_

* Engine can store bools (#6994)
  `PR #6994 <https://github.com/pantsbuild/pants/pull/6994>`_

* Clarify which files should be edited when releasing from branch (#6988)
  `PR #6988 <https://github.com/pantsbuild/pants/pull/6988>`_

* Core has a PathBuf for build root (#6995)
  `PR #6995 <https://github.com/pantsbuild/pants/pull/6995>`_

* Don't explicitly use TaskRule (#6980)
  `PR #6980 <https://github.com/pantsbuild/pants/pull/6980>`_

* Make UI Per-session instead of per-request (#6827)
  `PR #6827 <https://github.com/pantsbuild/pants/pull/6827>`_

* Replace deprecated cgi.escape() with html.escape() (#6986)
  `PR #6986 <https://github.com/pantsbuild/pants/pull/6986>`_

* Allow remote store RPC attempts to be configured (#6978)
  `PR #6978 <https://github.com/pantsbuild/pants/pull/6978>`_

* Prep for 1.13.0 (#6977)
  `PR #6977 <https://github.com/pantsbuild/pants/pull/6977>`_

* Allow fs_util thread count to be configured (#6976)
  `PR #6976 <https://github.com/pantsbuild/pants/pull/6976>`_

* Convert Native into a singleton (#6979)
  `PR #6979 <https://github.com/pantsbuild/pants/pull/6979>`_

1.14.0.dev0 (12/21/2018)
------------------------

New Features
~~~~~~~~~~~~

* Add support for deprecating scoped SubsystemDependencies (#6961)
  `PR #6961 <https://github.com/pantsbuild/pants/pull/6961>`_

* Add a flag to filedeps v1 to output abs or rel paths (#6960)
  `PR #6960 <https://github.com/pantsbuild/pants/pull/6960>`_

* Add serverset (#6921)
  `PR #6921 <https://github.com/pantsbuild/pants/pull/6921>`_

* Use serverset for Store (#6931)
  `PR #6931 <https://github.com/pantsbuild/pants/pull/6931>`_

* Add Python 3 support to C and C++ module initialization (#6930)
  `PR #6930 <https://github.com/pantsbuild/pants/pull/6930>`_

* Support source and 3rdparty dependencies in v2 python test running (#6915)
  `PR #6915 <https://github.com/pantsbuild/pants/pull/6915>`_

* Add tool classpath for ./pants scalafix (#6926)
  `PR #6926 <https://github.com/pantsbuild/pants/pull/6926>`_

* Log aggregate statistics for remote executions (#6812)
  `PR #6812 <https://github.com/pantsbuild/pants/pull/6812>`_

Version updates
~~~~~~~~~~~~~~~

* Upgrade Scrooge, Finagle, and Thrift for unified Thrift library and Py3 support (#6945)
  `PR #6945 <https://github.com/pantsbuild/pants/pull/6945>`_

* Bump zinc bootstrapper to 0.0.4 (#6967)
  `PR #6967 <https://github.com/pantsbuild/pants/pull/6967>`_

* Set CI's minimum Python 3 version to 3.6 (#6954)
  `PR #6954 <https://github.com/pantsbuild/pants/pull/6954>`_

* Bump scalafix version and use os.pathsep (#6938)
  `PR #6938 <https://github.com/pantsbuild/pants/pull/6938>`_

Bugfixes
~~~~~~~~

* Handle ValueError when child wants to reset stderr but it is closed. (#6932)
  `PR #6932 <https://github.com/pantsbuild/pants/pull/6932>`_

* Manually manage Delay's timer thread (#6950)
  `PR #6950 <https://github.com/pantsbuild/pants/pull/6950>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Ensure digests are uploaded before attempting execution (#6965)
  `PR #6965 <https://github.com/pantsbuild/pants/pull/6965>`_

* Fix tokenize encoding issue engine parser on Python 3 (#6962)
  `PR #6962 <https://github.com/pantsbuild/pants/pull/6962>`_

* Fix scheduler.metrics() returning bytes instead of unicode (#6969)
  `PR #6969 <https://github.com/pantsbuild/pants/pull/6969>`_

* Use stdout with bytes for task context (#6968)
  `PR #6968 <https://github.com/pantsbuild/pants/pull/6968>`_

* Fix plaintext_recorder sometimes being passed TextIO (#6963)
  `PR #6963 <https://github.com/pantsbuild/pants/pull/6963>`_

* Switch daytime CI to Python 3 only (#6952)
  `PR #6952 <https://github.com/pantsbuild/pants/pull/6952>`_

* Renamespace and publish the buck zip utils (#6955)
  `PR #6955 <https://github.com/pantsbuild/pants/pull/6955>`_

* Add filedeps goal and tests for v2 (#6933)
  `PR #6933 <https://github.com/pantsbuild/pants/pull/6933>`_

* serverset: Add ability to retry a function (#6953)
  `PR #6953 <https://github.com/pantsbuild/pants/pull/6953>`_

* Only build fs_util when releasing (#6951)
  `PR #6951 <https://github.com/pantsbuild/pants/pull/6951>`_

* Exclude Antlr test from testprojects to avoid interpreter conflict (#6944)
  `PR #6944 <https://github.com/pantsbuild/pants/pull/6944>`_

* Fix failing lint with TEST_BUILD pattern (#6943)
  `PR #6943 <https://github.com/pantsbuild/pants/pull/6943>`_

* Fix relative import for testprojects dummy test on Python 3 (#6942)
  `PR #6942 <https://github.com/pantsbuild/pants/pull/6942>`_

* Fix relative import for conftest test on Python 3 (#6941)
  `PR #6941 <https://github.com/pantsbuild/pants/pull/6941>`_

* Fix Travis environment variable overriding interpreter_selection test's config (#6939)
  `PR #6939 <https://github.com/pantsbuild/pants/pull/6939>`_

* PythonToolPrepBase now sets up its interpreter. (#6928)
  `PR #6928 <https://github.com/pantsbuild/pants/pull/6928>`_

* Remove remaining unnecessary __future__ imports (#6925)
  `PR #6925 <https://github.com/pantsbuild/pants/pull/6925>`_

* Construct clients on demand (#6920)
  `PR #6920 <https://github.com/pantsbuild/pants/pull/6920>`_

* Enforce interpreter constraints for antlr3 python code. (#6924)
  `PR #6924 <https://github.com/pantsbuild/pants/pull/6924>`_

1.13.0rc1 (12/18/2018)
------------------------

New Features
~~~~~~~~~~~~

* Add tool classpath for ./pants scalafix (#6926)
  `PR #6926 <https://github.com/pantsbuild/pants/pull/6926>`_

Bugfixes
~~~~~~~~

* Bump scalafix version and use os.pathsep (#6938)
  `PR #6938 <https://github.com/pantsbuild/pants/pull/6938>`_

1.13.0rc0 (12/13/2018)
------------------------

New Features
~~~~~~~~~~~~

* add a --toolchain-variant option to select the compiler for C/C++ (#6800)
  `PR #6800 <https://github.com/pantsbuild/pants/pull/6800>`_

* A contrib package for building AWS Lambdas from python code. (#6881)
  `PR #6881 <https://github.com/pantsbuild/pants/pull/6881>`_

Bugfixes
~~~~~~~~

* Fix Task fingerprinting. (#6894)
  `PR #6894 <https://github.com/pantsbuild/pants/pull/6894>`_

* [Bug fix] Fix test_interpreter_selection_integration unicode issues for Python 3 (#6887)
  `PR #6887 <https://github.com/pantsbuild/pants/pull/6887>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Ensure pants is running in exception sink tests. (#6912)
  `PR #6912 <https://github.com/pantsbuild/pants/pull/6912>`_

* Unblacklist JVM check_style Python 3 integration test thanks to using Python 3.5+ (#6882)
  `PR #6882 <https://github.com/pantsbuild/pants/pull/6882>`_

* Upgrade Travis to Xenial (Ubuntu 16.04) (#6885)
  `PR #6885 <https://github.com/pantsbuild/pants/pull/6885>`_

* Make PexBuilderWrapper a Subsystem. (#6897)
  `PR #6897 <https://github.com/pantsbuild/pants/pull/6897>`_

* Make graph traces stable. (#6909)
  `PR #6909 <https://github.com/pantsbuild/pants/pull/6909>`_

* Fix `build-support/bin/release.sh -p`. (#6908)
  `PR #6908 <https://github.com/pantsbuild/pants/pull/6908>`_

* Re-skip flaky test_mixed_python_tests. (#6904)
  `PR #6904 <https://github.com/pantsbuild/pants/pull/6904>`_

* Skip EngineTest#test_trace_multi. (#6899)
  `PR #6899 <https://github.com/pantsbuild/pants/pull/6899>`_

* Fix flaky `test_process_request_*`. (#6895)
  `PR #6895 <https://github.com/pantsbuild/pants/pull/6895>`_

* Convert some of release.sh to python, batch pants invocations (#6843)
  `PR #6843 <https://github.com/pantsbuild/pants/pull/6843>`_

* [Bug fix] Fix test_interpreter_selection_integration unicode issues for Python 3 (#6887)
  `PR #6887 <https://github.com/pantsbuild/pants/pull/6887>`_

1.13.0.dev2 (12/07/2018)
------------------------

New Features
~~~~~~~~~~~~

* Base classes for configuring and resolving python tools. (#6870)
  `PR #6870 <https://github.com/pantsbuild/pants/pull/6870>`_

* Add the ability to consume scoped Options from @rules (#6872)
  `PR #6872 <https://github.com/pantsbuild/pants/pull/6872>`_

* Expose an API to pass multiple Params to an engine request (#6871)
  `PR #6871 <https://github.com/pantsbuild/pants/pull/6871>`_

* Respect 3rdparty resolver setting in BootstrapJvmTools (#6789)
  `PR #6789 <https://github.com/pantsbuild/pants/pull/6789>`_

Bugfixes
~~~~~~~~

* Flush the console after all @console_rules have completed (#6878)
  `PR #6878 <https://github.com/pantsbuild/pants/pull/6878>`_

* Straighten out interpreter search path configuration (#6849)
  `PR #6849 <https://github.com/pantsbuild/pants/pull/6849>`_

* Make TestPinger more robust. (#6844)
  `PR #6844 <https://github.com/pantsbuild/pants/pull/6844>`_

* Fix clippy pre-commit check when used as a commit hook. (#6859)
  `PR #6859 <https://github.com/pantsbuild/pants/pull/6859>`_

* Don't copy over the os environment to avoid an encoding error (#6846)
  `PR #6846 <https://github.com/pantsbuild/pants/pull/6846>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* use the cbindgen crate and some decorators to DRY out the rust/python ffi (#6869)
  `PR #6869 <https://github.com/pantsbuild/pants/pull/6869>`_

* Use __iter__ instead of .dependencies in v2 rules (#6873)
  `PR #6873 <https://github.com/pantsbuild/pants/pull/6873>`_

* Improve error message for locale check (#6821)
  `PR #6821 <https://github.com/pantsbuild/pants/pull/6821>`_

* Port remaining tests to new TestBase base class. (#6864)
  `PR #6864 <https://github.com/pantsbuild/pants/pull/6864>`_

* Replace try! with ? (#6868)
  `PR #6868 <https://github.com/pantsbuild/pants/pull/6868>`_

* Remove some deprecated pex-related functions. (#6865)
  `PR #6865 <https://github.com/pantsbuild/pants/pull/6865>`_

* add `scala_jar` to the docsite (#6857)
  `PR #6857 <https://github.com/pantsbuild/pants/pull/6857>`_

* Port a few tests over to the new TestBase. (#6854)
  `PR #6854 <https://github.com/pantsbuild/pants/pull/6854>`_

* Use github release version of coursier instead of dropbox link (#6853)
  `PR #6853 <https://github.com/pantsbuild/pants/pull/6853>`_


1.13.0.dev1 (11/30/2018)
------------------------

New features
~~~~~~~~~~~~

* Add --remote-execution-process-cache-namespace (#6809)
  `PR #6809 <https://github.com/pantsbuild/pants/pull/6809>`_

Bugfixes
~~~~~~~~

* Fix unused error value. (#6834)
  `PR #6834 <https://github.com/pantsbuild/pants/pull/6834>`_

* [deferred-sources] fix glob expansion issue in deferred sources mappe… (#6824)
  `PR #6824 <https://github.com/pantsbuild/pants/pull/6824>`_

* Fix a bug when selecting interpreters with no constraints at all. (#6822)
  `PR #6822 <https://github.com/pantsbuild/pants/pull/6822>`_

* Pin a conan dep that was floating to a version that was not compatible with python 2. (#6825)
  `PR #6825 <https://github.com/pantsbuild/pants/pull/6825>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [docs] add language about flaky tests / issues for them (#6837)
  `PR #6837 <https://github.com/pantsbuild/pants/pull/6837>`_

* Include uname in rust cache key (#6842)
  `PR #6842 <https://github.com/pantsbuild/pants/pull/6842>`_

* Only build fs_util as part of dryrun (#6835)
  `PR #6835 <https://github.com/pantsbuild/pants/pull/6835>`_

* ci.sh can run cargo-audit (#6549)
  `PR #6549 <https://github.com/pantsbuild/pants/pull/6549>`_

* Run cargo clippy in pre-commit (#6833)
  `PR #6833 <https://github.com/pantsbuild/pants/pull/6833>`_

* Statically link openssl for reqwest (#6816)
  `PR #6816 <https://github.com/pantsbuild/pants/pull/6816>`_

* Use pantsbuild.org not example.com (#6826)
  `PR #6826 <https://github.com/pantsbuild/pants/pull/6826>`_

* Leverage default target globs. (#6819)
  `PR #6819 <https://github.com/pantsbuild/pants/pull/6819>`_

* Make PythonInterpreterCache into a subsystem. (#6765)
  `PR #6765 <https://github.com/pantsbuild/pants/pull/6765>`_


1.13.0.dev0 (11/26/2018)
------------------------

New features
~~~~~~~~~~~~
* Header file extensions as options for C/C++ targets (#6802)
  `PR #6802 <https://github.com/pantsbuild/pants/pull/6802>`_

API Changes
~~~~~~~~~~~
* Use both the deprecated and new locations of fatal_warnings args (#6798)
  `PR #6798 <https://github.com/pantsbuild/pants/pull/6798>`_

Bugfixes
~~~~~~~~
* Fix disappearing cursor (#6811)
  `PR #6811 <https://github.com/pantsbuild/pants/pull/6811>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Add nailgun-specific main which uses paths in calling process (#6792)
  `PR #6792 <https://github.com/pantsbuild/pants/pull/6792>`_

* Move file owners computation into the engine and make lighter (#6790)
  `PR #6790 <https://github.com/pantsbuild/pants/pull/6790>`_

* Bump Conan to 1.9.2 (#6797)
  `PR #6797 <https://github.com/pantsbuild/pants/pull/6797>`_

* Make bootstrap jar reproducible (#6796)
  `PR #6796 <https://github.com/pantsbuild/pants/pull/6796>`_

* Remove unused CompilerCacheKey (#6805)
  `PR #6805 <https://github.com/pantsbuild/pants/pull/6805>`_

* Fix documentation example for using scalac_plugins (#6807)
  `PR #6807 <https://github.com/pantsbuild/pants/pull/6807>`_

* Remove Params::expect_single compatibility API (#6766)
  `PR #6766 <https://github.com/pantsbuild/pants/pull/6766>`_

* add integration test for invalidation of ctypes c++ sources (#6801)
  `PR #6801 <https://github.com/pantsbuild/pants/pull/6801>`_


1.12.0rc0 (11/19/2018)
----------------------

New features
~~~~~~~~~~~~

* Add prelude and epilogue (#6784)
  `PR #6784 <https://github.com/pantsbuild/pants/pull/6784>`_

Bugfixes
~~~~~~~~

* Use ThreadPool for cache fetching and rust tar for artifact extraction (#6748)
  `PR #6748 <https://github.com/pantsbuild/pants/pull/6748>`_

1.12.0.dev1 (11/16/2018)
------------------------

API Changes
~~~~~~~~~~~

* bump pex version to 1.5.3 (#6776)
  `PR #6776 <https://github.com/pantsbuild/pants/pull/6776>`_

New Features
~~~~~~~~~~~~

* Make it easy to get a logger from a RunTracker instance. (#6771)
  `PR #6771 <https://github.com/pantsbuild/pants/pull/6771>`_

* fs_util can output recursive file list with digests (#6770)
  `PR #6770 <https://github.com/pantsbuild/pants/pull/6770>`_

* Jacoco report target filtering. (#6736)
  `PR #6736 <https://github.com/pantsbuild/pants/pull/6736>`_

Bugfixes
~~~~~~~~

* [rsc-compile] use digests from output files and include them in classpath products (#6772)
  `PR #6772 <https://github.com/pantsbuild/pants/pull/6772>`_

* [exec-graph] catch BaseException; improve inprogress debug logging (#6773)
  `PR #6773 <https://github.com/pantsbuild/pants/pull/6773>`_

* Stabilize V2 engine UI (#6761)
  `PR #6761 <https://github.com/pantsbuild/pants/pull/6761>`_

* [rsc-compile] further fixes (#6745)
  `PR #6745 <https://github.com/pantsbuild/pants/pull/6745>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* notes for 1.11.0rc2 (#6777)
  `PR #6777 <https://github.com/pantsbuild/pants/pull/6777>`_

* Skip another flaky test. (#6781)
  `PR #6781 <https://github.com/pantsbuild/pants/pull/6781>`_

* Make cargo as relative symlink not absolute (#6780)
  `PR #6780 <https://github.com/pantsbuild/pants/pull/6780>`_

* Skip broken test_pantsd_parent_runner_killed (#6779)
  `Issue #6778 <https://github.com/pantsbuild/pants/issues/6778>`_
  `PR #6779 <https://github.com/pantsbuild/pants/pull/6779>`_

* Skip a flaky test. (#6775)
  `PR #6775 <https://github.com/pantsbuild/pants/pull/6775>`_

* Set TERM=dumb in tests/python/pants_test/rules:test_integration (#6774)
  `PR #6774 <https://github.com/pantsbuild/pants/pull/6774>`_

* [zinc compile] Use default for rebase-map in zinc wrapper: part 2 (#6569)
  `PR #6569 <https://github.com/pantsbuild/pants/pull/6569>`_

* Add OSX 10.12 and 10.13 (#6760)
  `PR #6760 <https://github.com/pantsbuild/pants/pull/6760>`_

* Log digests, not fingerprints, when uploads fail (#6769)
  `PR #6769 <https://github.com/pantsbuild/pants/pull/6769>`_

* Force consistent stty size on travis (#6768)
  `PR #6768 <https://github.com/pantsbuild/pants/pull/6768>`_

* Python test runner uses pytest (#6661)
  `PR #6661 <https://github.com/pantsbuild/pants/pull/6661>`_

* Unblacklist some others which are flakily failing in both 2 and 3 (#6763)
  `PR #6763 <https://github.com/pantsbuild/pants/pull/6763>`_

* Fix bad usage of `future.moves.collections` (#6747)
  `PR #6747 <https://github.com/pantsbuild/pants/pull/6747>`_

* Update rust deps (#6759)
  `PR #6759 <https://github.com/pantsbuild/pants/pull/6759>`_

* Switch from enum_primitive to num_enum (#6756)
  `PR #6756 <https://github.com/pantsbuild/pants/pull/6756>`_

* Buffer downloads in memory not on disk (#6746)
  `PR #6746 <https://github.com/pantsbuild/pants/pull/6746>`_

* [rsc-compile] use already captured target sources snapshot instead of re-capturing (#6700)
  `PR #6700 <https://github.com/pantsbuild/pants/pull/6700>`_

* DownloadFile: Async and share an http Client (#6751)
  `PR #6751 <https://github.com/pantsbuild/pants/pull/6751>`_

* Fix Python 3 option integration test issue with unicode (#6755)
  `PR #6755 <https://github.com/pantsbuild/pants/pull/6755>`_

* Ignore paths more deeply to avoid graph impact when ignored files are added/removed (#6752)
  `PR #6752 <https://github.com/pantsbuild/pants/pull/6752>`_

* Run integration test against Python 3 (#6732)
  `PR #6732 <https://github.com/pantsbuild/pants/pull/6732>`_

* Cache file downloads in the Store (#6749)
  `PR #6749 <https://github.com/pantsbuild/pants/pull/6749>`_

* Allow tests to run with isolated stores (#6743)
  `PR #6743 <https://github.com/pantsbuild/pants/pull/6743>`_

* Update to rust 1.30 (#6741)
  `PR #6741 <https://github.com/pantsbuild/pants/pull/6741>`_

* Fix unit test http server threading (#6744)
  `PR #6744 <https://github.com/pantsbuild/pants/pull/6744>`_

* Add intrinsic to download a file (#6660)
  `PR #6660 <https://github.com/pantsbuild/pants/pull/6660>`_

* Rename DirectoryDigest to Digest (#6740)
  `PR #6740 <https://github.com/pantsbuild/pants/pull/6740>`_

* Allow multiple intrinsics to supply the same product type (#6739)
  `PR #6739 <https://github.com/pantsbuild/pants/pull/6739>`_

* WriterHasher returns a Digest not a Fingerprint (#6738)
  `PR #6738 <https://github.com/pantsbuild/pants/pull/6738>`_

* Minor cleanups to integration tests (#6734)
  `PR #6734 <https://github.com/pantsbuild/pants/pull/6734>`_

1.12.0.dev0 (11/06/2018)
------------------------

New Features
~~~~~~~~~~~~

* Compiler option sets for Native targets (#6665)
  `PR #6665 <https://github.com/pantsbuild/pants/pull/6665>`_

* Add UI to engine execution (#6647)
  `PR #6647 <https://github.com/pantsbuild/pants/pull/6647>`_

* Add support for un-cacheable rules, and stop caching console_rules (#6516)
  `PR #6516 <https://github.com/pantsbuild/pants/pull/6516>`_

* test console_task which aggregates test results (#6646)
  `PR #6646 <https://github.com/pantsbuild/pants/pull/6646>`_

* console_rules can exit with exit codes (#6654)
  `PR #6654 <https://github.com/pantsbuild/pants/pull/6654>`_

* Allow v2-only goals to be implicitly registered (#6653)
  `PR #6653 <https://github.com/pantsbuild/pants/pull/6653>`_

* Collection is iterable (#6649)
  `PR #6649 <https://github.com/pantsbuild/pants/pull/6649>`_

* fall back to most recent known osx version for bootstrap binaries (#6681)
  `PR #6681 <https://github.com/pantsbuild/pants/pull/6681>`_

Bugfixes
~~~~~~~~

* Fail build when setup-py run failed (#6693)
  `PR #6693 <https://github.com/pantsbuild/pants/pull/6693>`_

* Move ivy/coursier link farms under versioned task directories (#6686)
  `PR #6686 <https://github.com/pantsbuild/pants/pull/6686>`_

* Fix bugs in the parent/child relationship in ProcessManager (#6670)
  `PR #6670 <https://github.com/pantsbuild/pants/pull/6670>`_

* Ensure that changing platforms invalidates pex binary creation (#6202)
  `PR #6202 <https://github.com/pantsbuild/pants/pull/6202>`_

* Fix python lint dependency on pyprep goal (#6606)
  `Issue #5764 <https://github.com/pantsbuild/pants/issues/5764>`_
  `PR #6606 <https://github.com/pantsbuild/pants/pull/6606>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Upgrade to pex 1.5.2. (#6725)
  `PR #6725 <https://github.com/pantsbuild/pants/pull/6725>`_

* Bump to jarjar 1.7.2 to pull in several fixes. (#6695)
  `PR #6695 <https://github.com/pantsbuild/pants/pull/6695>`_

* Add test to assert that type validation works for Get (#6731)
  `PR #6731 <https://github.com/pantsbuild/pants/pull/6731>`_

* Add a better error message for missing RootRules (#6712)
  `PR #6712 <https://github.com/pantsbuild/pants/pull/6712>`_

* Fix Python 3 renaming assertRegexpMatches to assertRegex (#6723)
  `PR #6723 <https://github.com/pantsbuild/pants/pull/6723>`_

* De-flake JarPublishTest. (#6726)
  `PR #6726 <https://github.com/pantsbuild/pants/pull/6726>`_

* Fix Python 3 binary vs unicode integration test issues (#6724)
  `PR #6724 <https://github.com/pantsbuild/pants/pull/6724>`_

* Remove unneeded allow(dead_code) (#6717)
  `PR #6717 <https://github.com/pantsbuild/pants/pull/6717>`_

* Fix test get subprocess output interleaved py3k (#6713)
  `PR #6713 <https://github.com/pantsbuild/pants/pull/6713>`_

* Disable deploy shard for PR (#6709)
  `PR #6709 <https://github.com/pantsbuild/pants/pull/6709>`_

* Fixup `Checkstyle` local resolves. (#6707)
  `PR #6707 <https://github.com/pantsbuild/pants/pull/6707>`_

* Update Node.js README file (#6664)
  `PR #6664 <https://github.com/pantsbuild/pants/pull/6664>`_

* Match `stage` for `Deploy Pants Pex Unstable` (#6704)
  `PR #6704 <https://github.com/pantsbuild/pants/pull/6704>`_

* [rsc-compile] Bump rsc and scala meta versions in rsc compile (#6683)
  `PR #6683 <https://github.com/pantsbuild/pants/pull/6683>`_

* Revert "Convert release.sh from bash to python [part 1] (#6674)" (#6699)
  `PR #6674 <https://github.com/pantsbuild/pants/pull/6674>`_

* Pause all PantsService threads before forking a pantsd-runner (#6671)
  `PR #6671 <https://github.com/pantsbuild/pants/pull/6671>`_

* Python3 unit test fixes pt1 (#6698)
  `PR #6698 <https://github.com/pantsbuild/pants/pull/6698>`_

* Deploy pex every commit on master and branch (#6694)
  `PR #6694 <https://github.com/pantsbuild/pants/pull/6694>`_

* Fix flaky list comparison test (#6688)
  `PR #6688 <https://github.com/pantsbuild/pants/pull/6688>`_

* Do not compile native targets if they contain just header files (#6692)
  `PR #6692 <https://github.com/pantsbuild/pants/pull/6692>`_

* Update PyPI default URL to pypi.org (#6691)
  `PR #6691 <https://github.com/pantsbuild/pants/pull/6691>`_

* Re-add used-but-removed futures dep, which (due to a PR race) had a new usage added in 01c807ef, but its declaration removed in faeaf078. (#6680)
  `PR #6680 <https://github.com/pantsbuild/pants/pull/6680>`_

* Remove the FSEventService pool in favor of execution on the dedicated service thread. (#6667)
  `PR #6667 <https://github.com/pantsbuild/pants/pull/6667>`_

* Convert release.sh from bash to python [part 1] (#6674)
  `PR #6674 <https://github.com/pantsbuild/pants/pull/6674>`_

* Make PailgunServer multithreaded in order to avoid blocking the PailgunService thread. (#6669)
  `PR #6669 <https://github.com/pantsbuild/pants/pull/6669>`_

* add some more context to errors locating the native engine binary (#6575)
  `PR #6575 <https://github.com/pantsbuild/pants/pull/6575>`_

* Remove broken pants_dev broken image (#6655)
  `PR #6655 <https://github.com/pantsbuild/pants/pull/6655>`_

1.11.0rc0 (10/16/2018)
----------------------

New features
~~~~~~~~~~~~

* Add a node_scope option to node_module targets to support package-scopes (#6616)
  `PR #6616 <https://github.com/pantsbuild/pants/pull/6616>`_

* Split conan resolve by native_external_library targets (takeover). (#6630)
  `PR #6630 <https://github.com/pantsbuild/pants/pull/6630>`_

* Add intrinsic task to merge DirectoryDigests (#6635)
  `Issue #5502 <https://github.com/pantsbuild/pants/issues/5502>`_
  `PR #6635 <https://github.com/pantsbuild/pants/pull/6635>`_

Bugfixes
~~~~~~~~

* Tighten up checkstyle plugin subsystem option passing. (#6648)
  `PR #6648 <https://github.com/pantsbuild/pants/pull/6648>`_

* [dep-usage] when no summary, ensure json output is unicode (#6641)
  `PR #6641 <https://github.com/pantsbuild/pants/pull/6641>`_

* Fix console_rule generators, and add a test to coverage running them under run_rule. (#6644)
  `PR #6644 <https://github.com/pantsbuild/pants/pull/6644>`_

* Add bounds checking to Entry::current_running_duration (#6643)
  `PR #6643 <https://github.com/pantsbuild/pants/pull/6643>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Create exactly one associated subsystem per checkstyle plugin (#6634)
  `PR #6634 <https://github.com/pantsbuild/pants/pull/6634>`_

* Add some jdk tests for execution modes (#6631)
  `PR #6631 <https://github.com/pantsbuild/pants/pull/6631>`_

* Fix the release script. (#6629)
  `PR #6629 <https://github.com/pantsbuild/pants/pull/6629>`_

* Support resolving `Checker` from `sys.path`. (#6642)
  `PR #6642 <https://github.com/pantsbuild/pants/pull/6642>`_

1.11.0.dev3 (10/13/2018)
------------------------

API Changes
~~~~~~~~~~~

* Upgrade to pex 1.4.8 and eliminate workarounds. (#6594)
  `PR #6594 <https://github.com/pantsbuild/pants/pull/6594>`_

* Upgrade to pex 1.5.1; ~kill --resolver-blacklist. (#6619)
  `PR #6619 <https://github.com/pantsbuild/pants/pull/6619>`_

New features
~~~~~~~~~~~~

* Pants should manage local dependencies defined in package.json for node_module targets (#6524)
  `PR #6524 <https://github.com/pantsbuild/pants/pull/6524>`_

* Introduce factory_dict. (#6622)
  `PR #6622 <https://github.com/pantsbuild/pants/pull/6622>`_

Bugfixes
~~~~~~~~

* Fixup relative addresses for subprojects. (#6624)
  `PR #6624 <https://github.com/pantsbuild/pants/pull/6624>`_

* Run pythonstyle under the appropriate interpreter. (#6618)
  `PR #6618 <https://github.com/pantsbuild/pants/pull/6618>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Leverage factory_dict. (#6623)
  `PR #6623 <https://github.com/pantsbuild/pants/pull/6623>`_

* [rsc-compile] only metacp the jdk/scala synthetics one time per run (#6614)
  `PR #6614 <https://github.com/pantsbuild/pants/pull/6614>`_

* Clarify factory method terminal constructor calls. (#6625)
  `PR #6625 <https://github.com/pantsbuild/pants/pull/6625>`_

* Simplify pants.pex creation, leverage -c. (#6620)
  `PR #6620 <https://github.com/pantsbuild/pants/pull/6620>`_

* Add fs_util gc (#6612)
  `PR #6612 <https://github.com/pantsbuild/pants/pull/6612>`_

* add release notes for 1.10.0rc2 (#6615)
  `PR #6615 <https://github.com/pantsbuild/pants/pull/6615>`_

* Fatal error logging followup fixes (#6610)
  `PR #6610 <https://github.com/pantsbuild/pants/pull/6610>`_

* Fix typo (#6611)
  `PR #6611 <https://github.com/pantsbuild/pants/pull/6611>`_

* Consolidate Resettable instances (#6604)
  `PR #6604 <https://github.com/pantsbuild/pants/pull/6604>`_

* Update lmdb to 0.8 (#6607)
  `PR #6607 <https://github.com/pantsbuild/pants/pull/6607>`_

* first attempt at centralizing more global error logging state in ExceptionSink (#6552)
  `PR #6552 <https://github.com/pantsbuild/pants/pull/6552>`_

* [rsc-compile] update jdk dist lookup and usage to work remotely (#6593)
  `PR #6593 <https://github.com/pantsbuild/pants/pull/6593>`_


1.11.0.dev2 (10/05/2018)
------------------------

API Changes
~~~~~~~~~~~
* Support uploading stats to multiple endpoints. (#6599)
  `PR #6599 <https://github.com/pantsbuild/pants/pull/6599>`_

* Improve Noop resolution performance (#6577)
  `PR #6577 <https://github.com/pantsbuild/pants/pull/6577>`_

New features
~~~~~~~~~~~~
* Allow authentication to grpc APIs with oauth bearer tokens (#6581)
  `PR #6581 <https://github.com/pantsbuild/pants/pull/6581>`_

* Support secure grpc connections (#6584)
  `PR #6584 <https://github.com/pantsbuild/pants/pull/6584>`_

* Allow instance name to be set for remote executions (#6580)
  `PR #6580 <https://github.com/pantsbuild/pants/pull/6580>`_

Bugfixes
~~~~~~~~
* Store verifies digest lengths internally (#6588)
  `PR #6588 <https://github.com/pantsbuild/pants/pull/6588>`_

* Fix extra_jvm_options for `jvm_app` targets (#6572)
  `PR #6572 <https://github.com/pantsbuild/pants/pull/6572>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Update the "hello world" plugin doc. (#6601)
  `PR #6601 <https://github.com/pantsbuild/pants/pull/6601>`_

* More pinning to fix jupyter floats. (#6600)
  `PR #6600 <https://github.com/pantsbuild/pants/pull/6600>`_

* Handle RPC errors as well as message-inline errors (#6589)
  `PR #6589 <https://github.com/pantsbuild/pants/pull/6589>`_

* Add hello world plugin to documentation (#6587)
  `PR #6587 <https://github.com/pantsbuild/pants/pull/6587>`_

* Don't immediately fail after a MacOS upgrade. (#6591)
  `PR #6591 <https://github.com/pantsbuild/pants/pull/6591>`_

* Enhance the login task. (#6586)
  `PR #6586 <https://github.com/pantsbuild/pants/pull/6586>`_

* StubCAS is built with a builder (#6582)
  `PR #6582 <https://github.com/pantsbuild/pants/pull/6582>`_

* Use uuid v4 in field which is specified to be a uuid v4 (#6576)
  `PR #6576 <https://github.com/pantsbuild/pants/pull/6576>`_


1.11.0.dev1 (09/28/2018)
------------------------

API Changes
~~~~~~~~~~~

* Store and populate DirectoryDigests for cached targets (#6504)
  `PR #6504 <https://github.com/pantsbuild/pants/pull/6504>`_

New features
~~~~~~~~~~~~

* pantsd client logs exceptions from server processes (#6539)
  `PR #6539 <https://github.com/pantsbuild/pants/pull/6539>`_

* create singleton ExceptionSink object to centralize logging of fatal errors (#6533)
  `PR #6533 <https://github.com/pantsbuild/pants/pull/6533>`_

Bugfixes
~~~~~~~~

* refactor encoding for multiple nailgun messages, refactor logging on exit (#6388)
  `PR #6388 <https://github.com/pantsbuild/pants/pull/6388>`_

* [zinc-compile][hermetic] raise failure on compile failures (#6563)
  `PR #6563 <https://github.com/pantsbuild/pants/pull/6563>`_

* ExecuteProcessRequest works with overlapping output files and dirs (#6559)
  `Issue #6558 <https://github.com/pantsbuild/pants/issues/6558>`_
  `PR #6559 <https://github.com/pantsbuild/pants/pull/6559>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add forbidden imports check to ban std::sync primitives. (#6566)
  `PR #6566 <https://github.com/pantsbuild/pants/pull/6566>`_

* Pin jupyter transitive deps in integration tests (#6568)
  `PR #6568 <https://github.com/pantsbuild/pants/pull/6568>`_
  `Pex Issue #561 <https://github.com/pantsbuild/pex/issues/561>`_
  `Pex PR #562 <https://github.com/pantsbuild/pex/pull/562>`_

* Switch synchronization primitive usage to parking_lot (#6564)
  `PR #6564 <https://github.com/pantsbuild/pants/pull/6564>`_

* [rules-graph] ensure params in messages are sorted alphabetically (#6562)
  `PR #6562 <https://github.com/pantsbuild/pants/pull/6562>`_

* [rsc] break out metacp-ing jars into a separate job in RscCompile (#6538)
  `PR #6538 <https://github.com/pantsbuild/pants/pull/6538>`_

* Relativise paths (#6553)
  `PR #6558 <https://github.com/pantsbuild/pants/issues/6558>`_
  `PR #6553 <https://github.com/pantsbuild/pants/pull/6553>`_

* Ensure consistent performance for instance memos. (#6554)
  `PR #6554 <https://github.com/pantsbuild/pants/pull/6554>`_

* Refactor pantsd integration test framework (#6508)
  `PR #6508 <https://github.com/pantsbuild/pants/pull/6508>`_

* Ensure JarLibrary classpath entries have directory digests (#6544)
  `PR #6544 <https://github.com/pantsbuild/pants/pull/6544>`_

* Remove usage of @memoized_property on MappedSpecs. (#6551)
  `PR #6551 <https://github.com/pantsbuild/pants/pull/6551>`_

* Update rust to 1.29 (#6527)
  `PR #6527 <https://github.com/pantsbuild/pants/pull/6527>`_

* Use .jdk dir for hermetic execution (#6502)
  `PR #6502 <https://github.com/pantsbuild/pants/pull/6502>`_

* Relativise path to compiler bridge (#6546)
  `PR #6546 <https://github.com/pantsbuild/pants/pull/6546>`_

* Make the sizes of the members of `enum Node` more uniform (#6545)
  `PR #6545 <https://github.com/pantsbuild/pants/pull/6545>`_

* Explicitly use backports.configparser (#6542)
  `PR #6542 <https://github.com/pantsbuild/pants/pull/6542>`_

* Merge subjects and variants into Params, and remove Noop (#6170)
  `PR #6170 <https://github.com/pantsbuild/pants/pull/6170>`_

* custom scalac version test - bump fixture to 2.12.4 (#6532)
  `PR #6532 <https://github.com/pantsbuild/pants/pull/6532>`_


1.11.0.dev0 (09/14/2018)
------------------------

API Changes
~~~~~~~~~~~

* Upgrade Node.js to 8.11.3 and Yarn to 1.6.0 (#6512)
  `PR #6512 <https://github.com/pantsbuild/pants/pull/6512>`_

New features
~~~~~~~~~~~~

* Add extra_jvm_options to jvm_binary targets (#6310)
  `PR #6310 <https://github.com/pantsbuild/pants/pull/6310>`_

* [compile.rsc] Add strategy for compiling with Rsc and Zinc (#6408)
  `PR #6408 <https://github.com/pantsbuild/pants/pull/6408>`_

* Add support for HTTP basic auth. (#6495)
  `PR #6495 <https://github.com/pantsbuild/pants/pull/6495>`_

* gRPC support for golang protobufs. (#6507)
  `PR #6507 <https://github.com/pantsbuild/pants/pull/6507>`_

Bugfixes
~~~~~~~~

* make fatal_warnings_enabled_args a tuple instead of just parens (#6497)
  `PR #6497 <https://github.com/pantsbuild/pants/pull/6497>`_

* pass through `compatibility` to synthetic python thrift targets (#6499)
  `PR #6499 <https://github.com/pantsbuild/pants/pull/6499>`_

* Apply  workaround similer to #6409 to bootstrapper (#6498)
  `PR #6498 <https://github.com/pantsbuild/pants/pull/6498>`_

* Fix encoding of workunits under pantsd (#6505)
  `PR #6505 <https://github.com/pantsbuild/pants/pull/6505>`_

* refactor command line target spec resolution and check that all target roots exist (#6480)
  `PR #6480 <https://github.com/pantsbuild/pants/pull/6480>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* delete unnecessary testproject and broken test (#6494)
  `PR #6494 <https://github.com/pantsbuild/pants/pull/6494>`_

* skip integration test with pants_requirement() (#6493)
  `PR #6493 <https://github.com/pantsbuild/pants/pull/6493>`_

* Add bootstrapper jar to compile the compile-bridge. (#6462)
  `PR #6462 <https://github.com/pantsbuild/pants/pull/6462>`_

* [Hermetic zinc compile] Memoize scalac classpath snapshots (#6491)
  `PR #6491 <https://github.com/pantsbuild/pants/pull/6491>`_

* remove FIXME and (cosmicexplorer) comments (#6479)
  `PR #6479 <https://github.com/pantsbuild/pants/pull/6479>`_

* Consume the bootstrapper and modify zinc to allow remote exec (#6463)
  `PR #6463 <https://github.com/pantsbuild/pants/pull/6463>`_

1.10.0rc0 (09/10/2018)
----------------------

New features
~~~~~~~~~~~~

* Allow process_executor to make a JDK present (#6443)
  `PR #6443 <https://github.com/pantsbuild/pants/pull/6443>`_

* Zinc compiles can execute hermetically (#6351)
  `PR #6351 <https://github.com/pantsbuild/pants/pull/6351>`_

* Add a node-install goal to Pants for installing node_modules (#6367)
  `PR #6367 <https://github.com/pantsbuild/pants/pull/6367>`_

Bugfixes
~~~~~~~~

* Fixup `JsonEncoderTest` encoding tests. (#6457)
  `PR #6457 <https://github.com/pantsbuild/pants/pull/6457>`_

* Switch back to forked grpc-rs (#6418)
  `PR #6418 <https://github.com/pantsbuild/pants/pull/6418>`_

* Fix pants_requirement environment markers. (#6451)
  `PR #6451 <https://github.com/pantsbuild/pants/pull/6451>`_

* Fix CI failures introduced by #6275 (#6454)
  `PR #6454 <https://github.com/pantsbuild/pants/pull/6454>`_

* Make sure directory digest is defined for cache hits (#6442)
  `PR #6442 <https://github.com/pantsbuild/pants/pull/6442>`_

* Cancel running work when entering the fork context (#6464)
  `PR #6464 <https://github.com/pantsbuild/pants/pull/6464>`_

* Fix setup.py rendering. (#6439)
  `PR #6439 <https://github.com/pantsbuild/pants/pull/6439>`_

* Detect ns packages using correct interpreter. (#6428)
  `PR #6428 <https://github.com/pantsbuild/pants/pull/6428>`_

* Fixup tests involving pexrc. (#6446)
  `PR #6446 <https://github.com/pantsbuild/pants/pull/6446>`_

* [fix] Pass full path to isdir rather than just basename. (#6453)
  `PR #6453 <https://github.com/pantsbuild/pants/pull/6453>`_

* Add missing call to super. (#6477)
  `PR #6477 <https://github.com/pantsbuild/pants/pull/6477>`_

* Remove broken pyenv shims from the PATH. (#6469)
  `PR #6469 <https://github.com/pantsbuild/pants/pull/6469>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* fs_util and process_executor: Use default --local-store-path (#6444)
  `PR #6444 <https://github.com/pantsbuild/pants/pull/6444>`_

* satisfy python_dist setup_requires with a pex to resolve transitive deps, and some other unrelated native toolchain changes (#6275)
  `PR #6275 <https://github.com/pantsbuild/pants/pull/6275>`_

* Work around production `coverage` float. (#6452)
  `PR #6452 <https://github.com/pantsbuild/pants/pull/6452>`_

* Get clippy from the beta channel. (#6441)
  `PR #6441 <https://github.com/pantsbuild/pants/pull/6441>`_

* Tighten travis matrix and python activation. (#6440)
  `Issue #8315 <https://github.com/travis-ci/travis-ci/issues/8315>`_
  `PR #6440 <https://github.com/pantsbuild/pants/pull/6440>`_

* Ensure unstable pants dists can never conflict. (#6460)
  `PR #6460 <https://github.com/pantsbuild/pants/pull/6460>`_

* Extend fs_util deadline to 30 minutes (#6471)
  `PR #6471 <https://github.com/pantsbuild/pants/pull/6471>`_
  `PR #6433 <https://github.com/pantsbuild/pants/pull/6433>`_

* remove clean-all from pants invocations in python_dist() integration testing + some other refactoring (#6474)
  `PR #6474 <https://github.com/pantsbuild/pants/pull/6474>`_

* Re-enable pants_setup_requires:bin IT. (#6466)
  `PR #6466 <https://github.com/pantsbuild/pants/pull/6466>`_

Documentation
~~~~~~~~~~~~~

* Minor tweak on blogpost (#6438)
  `PR #6438 <https://github.com/pantsbuild/pants/pull/6438>`_


1.10.0.dev5 (08/31/2018)
------------------------

New features
~~~~~~~~~~~~

* Support HEAD redirects in RESTfulArtifactCache. (#6412)
  `PR #6412 <https://github.com/pantsbuild/pants/pull/6412>`_

* Add json upload summary to `fs_util` (#6318) (#6389)
  `PR #6318 <https://github.com/pantsbuild/pants/pull/6318>`_

* Override interpreter constraints if global option is passed down (#6387)
  `PR #6387 <https://github.com/pantsbuild/pants/pull/6387>`_
  `PR #6250 <https://github.com/pantsbuild/pants/pull/6250>`_

Bugfixes
~~~~~~~~

* Fix --binaries-path-by-id fingerprinting error (#6413)
  `PR #6413 <https://github.com/pantsbuild/pants/pull/6413>`_

* Remove false positive glob expansion failure warnings (#6278)
  `PR #6278 <https://github.com/pantsbuild/pants/pull/6278>`_

* Change zinc logging so it doesn't error out (#6409)
  `PR #6409 <https://github.com/pantsbuild/pants/pull/6409>`_

* Move fork context management to rust (#5521)
  `PR #5521 <https://github.com/pantsbuild/pants/pull/5521>`_

* Link requirements targets to their source. (#6405)
  `PR #6405 <https://github.com/pantsbuild/pants/pull/6405>`_

* Fix pants_requirement by allowing Python 3 (#6391)
  `PR #6391 <https://github.com/pantsbuild/pants/pull/6391>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix clippy errors (#6420)
  `PR #6420 <https://github.com/pantsbuild/pants/pull/6420>`_

* Re-enable rust clippy on its own shard (#6419)
  `PR #6419 <https://github.com/pantsbuild/pants/pull/6419>`_

* Set JDK properties for remote execution (#6417)
  `PR #6417 <https://github.com/pantsbuild/pants/pull/6417>`_
  `PR #391 <https://github.com/twitter/scoot/pull/391>`_

* s/size/size_bytes/ for consistency (#6410)
  `PR #6410 <https://github.com/pantsbuild/pants/pull/6410>`_

* Update rust deps (#6399)
  `PR #6399 <https://github.com/pantsbuild/pants/pull/6399>`_

* Update scalafmt to 1.5.1 (#6403)
  `PR #6403 <https://github.com/pantsbuild/pants/pull/6403>`_

Migration to Python3 compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python 3 - fixes to get most of src unit tests green (#6372)
  `PR #6372 <https://github.com/pantsbuild/pants/pull/6372>`_

Documentation
~~~~~~~~~~~~~

* Clarify release docs for stable branches. (#6427)
  `PR #6427 <https://github.com/pantsbuild/pants/pull/6427>`_

* Coursier Migration Blogpost (#6400)
  `PR #6400 <https://github.com/pantsbuild/pants/pull/6400>`_

* add 1.9.0rc2 notes (#6425)
  `PR #6425 <https://github.com/pantsbuild/pants/pull/6425>`_


1.10.0.dev4 (08/24/2018)
------------------------

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fix CI (#6402)
  `PR #6402 <https://github.com/pantsbuild/pants/pull/6402>`_

* Requirements on language-specific sources should be optional. (#6375)
  `PR #6375 <https://github.com/pantsbuild/pants/pull/6375>`_

* Deprecate --quiet recursive option (#6156)
  `PR #6156 <https://github.com/pantsbuild/pants/pull/6156>`_

* Decode python_eval template resource as utf-8. (#6379)
  `PR #6379 <https://github.com/pantsbuild/pants/pull/6379>`_

* Use set literals & set comprehensions where possible (#6376)
  `PR #6376 <https://github.com/pantsbuild/pants/pull/6376>`_

* Stabilize test case sorting in suites. (#6371)
  `PR #6371 <https://github.com/pantsbuild/pants/pull/6371>`_

Migration to Python3 compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* No longer expect failure from test_pinger (#6373)
  `PR #6373 <https://github.com/pantsbuild/pants/pull/6373>`_

* Pin interpreter <3.7 in ci. (#6364)
  `PR #6364 <https://github.com/pantsbuild/pants/pull/6364>`_

Documentation
~~~~~~~~~~~~~

* [engine] Add note to readme about fs_util (#6377)
  `PR #6377 <https://github.com/pantsbuild/pants/pull/6377>`_


1.10.0.dev3 (08/20/2018)
------------------------

New features
~~~~~~~~~~~~

* Add contrib dist support to pants_requirement. (#6365)
  `PR #6365 <https://github.com/pantsbuild/pants/pull/6365>`_

* Allow pex download path to be overridden (#6348)
  `PR #6348 <https://github.com/pantsbuild/pants/pull/6348>`_

Bugfixes
~~~~~~~~

* Fix Single Address Exclude (#6366)
  `PR #6366 <https://github.com/pantsbuild/pants/pull/6366>`_

* Add an environment marker to `pants_requirement`. (#6361)
  `PR #6361 <https://github.com/pantsbuild/pants/pull/6361>`_

* Make requirements on codegen products optional. (#6357)
  `PR #6357 <https://github.com/pantsbuild/pants/pull/6357>`_

* Use --entry-point not -c when building pex (#6349)
  `PR #6349 <https://github.com/pantsbuild/pants/pull/6349>`_
  `PR #6267 <https://github.com/pantsbuild/pants/pull/6267>`_

* Recover from cancelled remote execution RPCs (#6188)
  `PR #6188 <https://github.com/pantsbuild/pants/pull/6188>`_

* Use forked version of grpcio (#6344)
  `PR #6344 <https://github.com/pantsbuild/pants/pull/6344>`_
  `PR #211 <https://github.com/pingcap/grpc-rs/pull/211>`_

* added fullpath to fix path concat issue with files when not in git root (#6331)
  `PR #6331 <https://github.com/pantsbuild/pants/pull/6331>`_

* Log test targets that failed to run. (#6335)
  `PR #6335 <https://github.com/pantsbuild/pants/pull/6335>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Run clippy with nightly rust on CI (#6347)
  `PR #6347 <https://github.com/pantsbuild/pants/pull/6347>`_

* Fix formatting of store.rs (#6350)
  `PR #6350 <https://github.com/pantsbuild/pants/pull/6350>`_
  `PR #6336 <https://github.com/pantsbuild/pants/pull/6336>`_

* Download Directory recursively from remote CAS  (#6336)
  `PR #6336 <https://github.com/pantsbuild/pants/pull/6336>`_

* Process execution: Create symlink to JDK on demand (#6346)
  `PR #6346 <https://github.com/pantsbuild/pants/pull/6346>`_

* Simplify ExecuteProcessRequest construction (#6345)
  `PR #6345 <https://github.com/pantsbuild/pants/pull/6345>`_

* ci.sh uses positive rather than negative flags (#6342)
  `PR #6342 <https://github.com/pantsbuild/pants/pull/6342>`_

* Merge directories with identical files (#6343)
  `PR #6343 <https://github.com/pantsbuild/pants/pull/6343>`_

* Set chunk size in process_executor (#6337)
  `PR #6337 <https://github.com/pantsbuild/pants/pull/6337>`_

Migration to Python3 compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python 3 - fixes to get backend mostly green (#6360)
  `PR #6360 <https://github.com/pantsbuild/pants/pull/6360>`_

* Python 3 - fixes to get green contrib (#6340)
  `PR #6340 <https://github.com/pantsbuild/pants/pull/6340>`_

1.10.0.dev2 (08/10/2018)
------------------------

New features
~~~~~~~~~~~~

* Add a `--loop` flag, to allow for running continuously (#6270)
  `PR #6270 <https://github.com/pantsbuild/pants/pull/6270>`_

Bugfixes
~~~~~~~~

* pantsrc file paths are always unicode (#6316)
  `PR #6316 <https://github.com/pantsbuild/pants/pull/6316>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Relativize most paths in the zinc compile command line (#6322)
  `PR #6322 <https://github.com/pantsbuild/pants/pull/6322>`_

* A few misc cleanups (#6324)
  `PR #6324 <https://github.com/pantsbuild/pants/pull/6324>`_

* Use dependency ClasspathEntries, not merged strings (#6317)
  `PR #6317 <https://github.com/pantsbuild/pants/pull/6317>`_

* Register products when compilation finishes (#6315)
  `PR #6315 <https://github.com/pantsbuild/pants/pull/6315>`_

* ClasspathEntry optionally takes a DirectoryDigest (#6297)
  `PR #6297 <https://github.com/pantsbuild/pants/pull/6297>`_

* Cache more of rust. (#6309)
  `PR #6309 <https://github.com/pantsbuild/pants/pull/6309>`_

* Tighten up local process streaming. (#6307)
  `PR #6307 <https://github.com/pantsbuild/pants/pull/6307>`_

* Bump rust to 1.28 (#6306)
  `PR #6306 <https://github.com/pantsbuild/pants/pull/6306>`_

* Remove unused Task._build_invalidator root param. (#6308)
  `PR #6308 <https://github.com/pantsbuild/pants/pull/6308>`_

* Reinstate possibility of local process streaming. (#6300)
  `PR #6300 <https://github.com/pantsbuild/pants/pull/6300>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Document Pants features for Organizations (#5673)
  `PR #5673 <https://github.com/pantsbuild/pants/pull/5673>`_

* Add Sigma to "Powered by Pants" page (#6314)
  `PR #6314 <https://github.com/pantsbuild/pants/pull/6314>`_

* Add contributor (#6312)
  `PR #6312 <https://github.com/pantsbuild/pants/pull/6312>`_

Migration to Python3 compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Skip known to fail tests in py3 (#6323)
  `PR #6323 <https://github.com/pantsbuild/pants/pull/6323>`_

* Strings are correctly returned from rust code (#6325)
  `PR #6325 <https://github.com/pantsbuild/pants/pull/6325>`_

* Switch to Py2 and Py3 shards. (#6289)
  `PR #6289 <https://github.com/pantsbuild/pants/pull/6289>`_

* Python 3 fixes - various bytes vs unicode issues (#6311)
  `PR #6311 <https://github.com/pantsbuild/pants/pull/6311>`_

* Always return unicode with hexdigest() (#6313)
  `PR #6313 <https://github.com/pantsbuild/pants/pull/6313>`_

* Specify unicode vs bytes for Path and FileContent types (#6303)
  `PR #6303 <https://github.com/pantsbuild/pants/pull/6303>`_

* Python 3 fixes - add open backport to contrib (#6295)
  `PR #6295 <https://github.com/pantsbuild/pants/pull/6295>`_

* Python 3 fixes - add open() backport to safe_open() (#6304)
  `PR #6304 <https://github.com/pantsbuild/pants/pull/6304>`_
  `PR #6290 <https://github.com/pantsbuild/pants/pull/6290>`_

* Require the system encoding to be UTF-8 (#6305)
  `PR #6305 <https://github.com/pantsbuild/pants/pull/6305>`_

* Python 3 fixes - add open() backport stage 2 (#6291)
  `PR #6291 <https://github.com/pantsbuild/pants/pull/6291>`_
  `PR #6290 <https://github.com/pantsbuild/pants/pull/6290>`_

* drop self from __init__ and __new__ (#6299)
  `PR #6299 <https://github.com/pantsbuild/pants/pull/6299>`_

1.10.0.dev1 (08/03/2018)
------------------------

New features
~~~~~~~~~~~~

* Add --output-dir flag to ScalaFmt task (#6134)
  `PR #6134 <https://github.com/pantsbuild/pants/pull/6134>`_

Bugfixes
~~~~~~~~

* Fix a deadlock in local process execution. (#6292)
  `PR #6292 <https://github.com/pantsbuild/pants/pull/6292>`_

* When python target compatibility is not set, use interpreter constraints. (#6284)
  `PR #6284 <https://github.com/pantsbuild/pants/pull/6284>`_

* Bound pytest below 3.7 to avoid a ZipImportError (#6285)
  `PR #6285 <https://github.com/pantsbuild/pants/pull/6285>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Kill WrappedPEX. (#6280)
  `PR #6280 <https://github.com/pantsbuild/pants/pull/6280>`_

* Add copy() method to datatype (#6269)
  `PR #6269 <https://github.com/pantsbuild/pants/pull/6269>`_

* Upgrade to pex 1.4.5. (#6267)
  `PR #6267 <https://github.com/pantsbuild/pants/pull/6267>`_

* Hard link or copy ivy and coursier cache (#6246)
  `PR #6246 <https://github.com/pantsbuild/pants/pull/6246>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Modify the `alias` page to actually reference the `alias` target (#6277)
  `PR #6277 <https://github.com/pantsbuild/pants/pull/6277>`_

Migration to Python3 compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python 3 fixes - add open() backport stage 1 (#6290)
  `PR #6290 <https://github.com/pantsbuild/pants/pull/6290>`_

* Python 3 fixes - fix issues with binaries, option, pantsd, java, and build graph (#6287)
  `PR #6287 <https://github.com/pantsbuild/pants/pull/6287>`_

* Python 3 fixes - fix issues with engine (#6279)
  `PR #6279 <https://github.com/pantsbuild/pants/pull/6279>`_

* Rename deprecated assertions (#6286)
  `PR #6286 <https://github.com/pantsbuild/pants/pull/6286>`_

* Python 3 fixes - fix contrib folders problems (#6272)
  `PR #6272 <https://github.com/pantsbuild/pants/pull/6272>`_

* Python 3 fixes - fix contrib/python checkstyle (#6274)
  `PR #6274 <https://github.com/pantsbuild/pants/pull/6274>`_

1.10.0.dev0 (07/27/2018)
------------------------

* Remove 1.10.x deprecations (#6268)
  `PR #6268 <https://github.com/pantsbuild/pants/pull/6268>`_

New Features
~~~~~~~~~~~~

* Add a debug dump flag to the zinc analysis extractor. (#6241)
  `PR #6241 <https://github.com/pantsbuild/pants/pull/6241>`_

* Add functionality to create jars in zinc wrapper (#6094)
  `PR #6094 <https://github.com/pantsbuild/pants/pull/6094>`_

* Allow user to specify chunk size (#6173)
  `PR #6173 <https://github.com/pantsbuild/pants/pull/6173>`_

Bugfixes
~~~~~~~~

* Fix spurious deprecation warning for fatal_warnings (#6237)
  `PR #6237 <https://github.com/pantsbuild/pants/pull/6237>`_

* Associate cli arguments with executables and refactor llvm/gcc c/c++ toolchain selection (#6217)
  `PR #6217 <https://github.com/pantsbuild/pants/pull/6217>`_

* Fix pydist native sources selection (#6205)
  `PR #6205 <https://github.com/pantsbuild/pants/pull/6205>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Convert `fmt.isort` to bootstrapping isort. (#6182)
  `PR #6182 <https://github.com/pantsbuild/pants/pull/6182>`_

* Fix env construction on ExecuteProcessRequest (#6220)
  `PR #6220 <https://github.com/pantsbuild/pants/pull/6220>`_

* Ci deduplication (#6186)
  `PR #6186 <https://github.com/pantsbuild/pants/pull/6186>`_

* [missing-deps-suggest] move buildozer cli to a new line (#6190)
  `PR #6190 <https://github.com/pantsbuild/pants/pull/6190>`_

* Print stack trace on ExecutionGraph task failures (#6177)
  `PR #6177 <https://github.com/pantsbuild/pants/pull/6177>`_

* Add basic native task unit tests. (#6179)
  `PR #6179 <https://github.com/pantsbuild/pants/pull/6179>`_

* Start migrating away from SchedulerTestBase (#5929)
  `PR #5929 <https://github.com/pantsbuild/pants/pull/5929>`_

* Only clone taken Strings, not all Strings (#6240)
  `PR #6240 <https://github.com/pantsbuild/pants/pull/6240>`_

* Remove unused custom `working_set` parameters. (#6221)
  `PR #6221 <https://github.com/pantsbuild/pants/pull/6221>`_

* Update protobuf and grpcio deps (#6248)
  `PR #6248 <https://github.com/pantsbuild/pants/pull/6248>`_

Migration to Python3 compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python 3 fixes - fix backend/docgen test issues with bytes vs unicode (#6265)
  `PR #6265 <https://github.com/pantsbuild/pants/pull/6265>`_

* Python 3 fixes - fix scm bytes vs unicode issues (#6257)
  `PR #6257 <https://github.com/pantsbuild/pants/pull/6257>`_

* Python 3 fixes - fix net/http issues with bytes vs unicode (#6258)
  `PR #6258 <https://github.com/pantsbuild/pants/pull/6258>`_

* Python 3 fixes - fix test_base.create_files() unicode issue (#6266)
  `PR #6266 <https://github.com/pantsbuild/pants/pull/6266>`_

* Fix invalidation unicode vs bytes issues (#6262)
  `PR #6262 <https://github.com/pantsbuild/pants/pull/6262>`_

* Fix fake options unicode vs bytes issues (#6263)
  `PR #6263 <https://github.com/pantsbuild/pants/pull/6263>`_

* Python 3 fixes - fix ivy issues with unicode vs bytes (#6264)
  `PR #6264 <https://github.com/pantsbuild/pants/pull/6264>`_

* Bump beautifulsoup4 to 4.6 to fix Python 3 issue. (#6260)
  `PR #6260 <https://github.com/pantsbuild/pants/pull/6260>`_

* Python 3 fixes - fix unicode and __hash__ issues with release folder (#6261)
  `PR #6261 <https://github.com/pantsbuild/pants/pull/6261>`_

* Python 3 fixes - fix syntax issue in reporting test (#6259)
  `PR #6259 <https://github.com/pantsbuild/pants/pull/6259>`_

* Python 3 fixes - fix process test byte issue (#6256)
  `PR #6256 <https://github.com/pantsbuild/pants/pull/6256>`_

* Split file set by line instead of spaces to resolve errors (#6247)
  `PR #6247 <https://github.com/pantsbuild/pants/pull/6247>`_

* Python 3 fixes - test root unicode vs bytes (#6253)
  `PR #6253 <https://github.com/pantsbuild/pants/pull/6253>`_

* Port test/tasks to Python 3 (#6255)
  `PR #6255 <https://github.com/pantsbuild/pants/pull/6255>`_

* Python 3 fixes - fix base folder (#6252)
  `PR #6252 <https://github.com/pantsbuild/pants/pull/6252>`_

* Python 3 fixes - fix invalid ABCMeta comparison (#6251)
  `PR #6251 <https://github.com/pantsbuild/pants/pull/6251>`_

* Fix syntax issue with raising error (#6245)
  `PR #6245 <https://github.com/pantsbuild/pants/pull/6245>`_

* Exclude faulthandler and futures if Python 3 (#6244)
  `PR #6244 <https://github.com/pantsbuild/pants/pull/6244>`_

* Python 3 fixes - fix tarutil and contextutil_test (#6243)
  `PR #6243 <https://github.com/pantsbuild/pants/pull/6243>`_

* Python 3 fixes - use unicode with temporary_directory() file path (#6233)
  `PR #6233 <https://github.com/pantsbuild/pants/pull/6233>`_

* Python 3 fixes - fix netrc.py, retry.py, and test_objects.py (#6235)
  `PR #6235 <https://github.com/pantsbuild/pants/pull/6235>`_

* Python 3 fixes - fix dirutil, fileutil, and xml_parser tests (#6229)
  `PR #6229 <https://github.com/pantsbuild/pants/pull/6229>`_
  `PR #6228 <https://github.com/pantsbuild/pants/pull/6228>`_

* Fix issue of os.environ expecting bytes vs unicode in Py2 vs Py3 (#6222)
  `PR #6222 <https://github.com/pantsbuild/pants/pull/6222>`_

* Python 3 fixes - specify binary vs unicode behavior of temporary_file() (#6226)
  `PR #6226 <https://github.com/pantsbuild/pants/pull/6226>`_

* Python 3 fixes - fix process_handler timing out (#6232)
  `PR #6232 <https://github.com/pantsbuild/pants/pull/6232>`_

* Port bin to Python 3 (#6126)
  `PR #6126 <https://github.com/pantsbuild/pants/pull/6126>`_

* Python 3 fixes - fix various TestBase issues (#6228)
  `PR #6228 <https://github.com/pantsbuild/pants/pull/6228>`_

* An initial engine terminal UI and demo. (#6223)
  `PR #6223 <https://github.com/pantsbuild/pants/pull/6223>`_

* Python 3 - fix cffi resolver issues  (#6225)
  `PR #6225 <https://github.com/pantsbuild/pants/pull/6225>`_

* Exclude subprocess32 if Python 3 (#6212)
  `PR #6212 <https://github.com/pantsbuild/pants/pull/6212>`_

* Fix imports of future.utils (#6213)
  `PR #6213 <https://github.com/pantsbuild/pants/pull/6213>`_

* Port test's root folder (#6207)
  `PR #6207 <https://github.com/pantsbuild/pants/pull/6207>`_

* Port task (#6200)
  `PR #6200 <https://github.com/pantsbuild/pants/pull/6200>`_

* Port backend/jvm (#6092)
  `PR #6092 <https://github.com/pantsbuild/pants/pull/6092>`_

* Port net (#6162)
  `PR #6162 <https://github.com/pantsbuild/pants/pull/6162>`_

* Port pantsd/ to python3 (#6136)
  `PR #6136 <https://github.com/pantsbuild/pants/pull/6136>`_

* futurize confluence (#6115)
  `PR #6115 <https://github.com/pantsbuild/pants/pull/6115>`_

* Port testutils to Python 3 (#6211)
  `PR #6211 <https://github.com/pantsbuild/pants/pull/6211>`_

* Port examples to Python 3 (#6210)
  `PR #6210 <https://github.com/pantsbuild/pants/pull/6210>`_

* Port pants-plugins to Python 3 (#6209)
  `PR #6209 <https://github.com/pantsbuild/pants/pull/6209>`_

* Port cache to Python 3 (#6129)
  `PR #6129 <https://github.com/pantsbuild/pants/pull/6129>`_

* Port stats to Python 3 (#6198)
  `PR #6198 <https://github.com/pantsbuild/pants/pull/6198>`_

* Port subsystem to Python 3 (#6199)
  `PR #6199 <https://github.com/pantsbuild/pants/pull/6199>`_

* Port source to Python 3 (#6197)
  `PR #6197 <https://github.com/pantsbuild/pants/pull/6197>`_

* Port scm to Python 3 (#6196)
  `PR #6196 <https://github.com/pantsbuild/pants/pull/6196>`_

* Port releases to Python 3 (#6194)
  `PR #6194 <https://github.com/pantsbuild/pants/pull/6194>`_

* Port process package to Python 3 (#6193)
  `PR #6193 <https://github.com/pantsbuild/pants/pull/6193>`_

* Prepare a noop release for 1.9.0rc1. (#6204)
  `PR #6204 <https://github.com/pantsbuild/pants/pull/6204>`_

* Port reporting to Python 3 (#6195)
  `PR #6195 <https://github.com/pantsbuild/pants/pull/6195>`_

* Port build graph to Python 3 (#6128)
  `PR #6128 <https://github.com/pantsbuild/pants/pull/6128>`_

* Port contrib/node to py3 (#6158)
  `PR #6158 <https://github.com/pantsbuild/pants/pull/6158>`_

* update contrib/python with py3 compat (#6184)
  `PR #6184 <https://github.com/pantsbuild/pants/pull/6184>`_

1.9.0rc0 (07/19/2018)
---------------------

New features
~~~~~~~~~~~~

* Conan (third party) support for ctypes native libraries (#5998)
  `PR #5998 <https://github.com/pantsbuild/pants/pull/5998>`_
  `PR #5815 <https://github.com/pantsbuild/pants/pull/5815>`_

* Early support for @console_rule. (#6088)
  `PR #6088 <https://github.com/pantsbuild/pants/pull/6088>`_

Bugfixes
~~~~~~~~

* Fix incorrect use of bytes() when invoking the daemon in a tty (#6181)
  `PR #6181 <https://github.com/pantsbuild/pants/pull/6181>`_

* rustfmt check more reliably works (#6172)
  `PR #6172 <https://github.com/pantsbuild/pants/pull/6172>`_

* Fix isort issues (#6174)
  `PR #6174 <https://github.com/pantsbuild/pants/pull/6174>`_

* add the target fingerprint to the version of each local dist so that we don't use the first cached one (#6022)
  `PR #6022 <https://github.com/pantsbuild/pants/pull/6022>`_

* Eliminate obsolete PANTS_ARGS from ci. (#6141)
  `PR #6141 <https://github.com/pantsbuild/pants/pull/6141>`_

* Preserve output directories if process execution failed (#6152)
  `PR #6152 <https://github.com/pantsbuild/pants/pull/6152>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Upgrade to isort 4.3.4. (#6166)
  `PR #6166 <https://github.com/pantsbuild/pants/pull/6166>`_

* fs_util can list the recursive files in a Directory (#6153)
  `PR #6153 <https://github.com/pantsbuild/pants/pull/6153>`_

* Support output directory saving in remote execution (#6167)
  `PR #6167 <https://github.com/pantsbuild/pants/pull/6167>`_

* Move each EntryState in the graph under its own Mutex (#6095)
  `PR #6095 <https://github.com/pantsbuild/pants/pull/6095>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Impose a consistent sort on CONTRIBUTORS.md. (#6125)
  `PR #6125 <https://github.com/pantsbuild/pants/pull/6125>`_

Python 3 porting (#6062)
~~~~~~~~~~~~~~~~~~~~~~~~

* Port engine to Python 3 (#6133)
  `PR #6133 <https://github.com/pantsbuild/pants/pull/6133>`_

* Port go to py3 (#6139)
  `PR #6139 <https://github.com/pantsbuild/pants/pull/6139>`_

* Port init package to Python 3 (#6145)
  `PR #6145 <https://github.com/pantsbuild/pants/pull/6145>`_

* Port help package to Python 3 (#6144)
  `PR #6144 <https://github.com/pantsbuild/pants/pull/6144>`_

* Port invalidation to Python 3 (#6147)
  `PR #6147 <https://github.com/pantsbuild/pants/pull/6147>`_

* port cpp to py3 (#6116)
  `PR #6116 <https://github.com/pantsbuild/pants/pull/6116>`_

* Port ivy to Python 3 (#6154)
  `PR #6154 <https://github.com/pantsbuild/pants/pull/6154>`_

* Port java to Python 3 (#6159)
  `PR #6159 <https://github.com/pantsbuild/pants/pull/6159>`_

* Port contrib/scalajs to py3 (#6164)
  `PR #6164 <https://github.com/pantsbuild/pants/pull/6164>`_

* port scrooge to py3 (#6165)
  `PR #6165 <https://github.com/pantsbuild/pants/pull/6165>`_

* Add missing future dependency to BUILD (#6135)
  `PR #6135 <https://github.com/pantsbuild/pants/pull/6135>`_

* Port binaries package to Python 3 (#6127)
  `PR #6127 <https://github.com/pantsbuild/pants/pull/6127>`_

* Port option package to python3 (#6117)
  `PR #6117 <https://github.com/pantsbuild/pants/pull/6117>`_

* Port to mypy to py3 (#6140)
  `PR #6140 <https://github.com/pantsbuild/pants/pull/6140>`_

* Port goal package to Python 3 (#6138)
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_
  `PR #6138 <https://github.com/pantsbuild/pants/pull/6138>`_

* Port findbugs to py3 (#6137)
  `PR #6137 <https://github.com/pantsbuild/pants/pull/6137>`_

* Port backend project info to Python 3 (#6132)
  `PR #6132 <https://github.com/pantsbuild/pants/pull/6132>`_

* Port backend graph info to Python 3 (#6131)
  `PR #6131 <https://github.com/pantsbuild/pants/pull/6131>`_

* Port core tasks to Python 3 (#6130)
  `PR #6130 <https://github.com/pantsbuild/pants/pull/6130>`_

1.9.0.dev1 (07/14/2018)
-----------------------

New features
~~~~~~~~~~~~

* Add support for reusing Graph node values if their inputs haven't changed (#6059)
  `PR #6059 <https://github.com/pantsbuild/pants/pull/6059>`_

* Compile a VERY simple java source remotely (no dependencies or inner classes) (#5999)
  `PR #5999 <https://github.com/pantsbuild/pants/pull/5999>`_

* Expose materialize_directory as an intrinsic function on the scheduler (#6028)
  `PR #6028 <https://github.com/pantsbuild/pants/pull/6028>`_

* Targets always have a Snapshot (#5994)
  `PR #5994 <https://github.com/pantsbuild/pants/pull/5994>`_

* Add an execution strategy flag (#5981)
  `PR #5981 <https://github.com/pantsbuild/pants/pull/5981>`_

* Enable passing option sets to the compiler and deprecate fatal_warnings (#6065)
  `PR #6065 <https://github.com/pantsbuild/pants/pull/6065>`_

API Changes
~~~~~~~~~~~

* Upgrade to v2 of bazel protobuf (#6027)
  `PR #6027 <https://github.com/pantsbuild/pants/pull/6027>`_

* Add PrimitivesSetField and deprecate SetOfPrimitivesField (#6087)
  `PR #6087 <https://github.com/pantsbuild/pants/pull/6087>`_

* Update to rust 1.27, implicitly requiring OSX 10.11 (#6035)
  `PR #6035 <https://github.com/pantsbuild/pants/pull/6035>`_

Bugfixes
~~~~~~~~

* Fix local execution of hermetic integration tests (#6101)
  `PR #6101 <https://github.com/pantsbuild/pants/pull/6101>`_

* Use PrimitivesSetField in ScalaJs target and minor help text fixup (#6113)
  `PR #6113 <https://github.com/pantsbuild/pants/pull/6113>`_

* Fix 'current' platform handling. (#6104)
  `PR #6104 <https://github.com/pantsbuild/pants/pull/6104>`_

* Make RUST_BACKTRACE sniffing less specific (#6107)
  `PR #6107 <https://github.com/pantsbuild/pants/pull/6107>`_

* Improve source field deprecations (#6097)
  `PR #6097 <https://github.com/pantsbuild/pants/pull/6097>`_

* Remove and prevent inaccurate __eq__ implementations on datatype (#6061)
  `PR #6061 <https://github.com/pantsbuild/pants/pull/6061>`_

* Ensure correct toolchain per clone. (#6054)
  `PR #6054 <https://github.com/pantsbuild/pants/pull/6054>`_

* Have pantsbuild-ci-bot do deploys. (#6053)
  `PR #6053 <https://github.com/pantsbuild/pants/pull/6053>`_

* Fix go-import meta tag ends with /> #6036 (#6037)
  `PR #6037 <https://github.com/pantsbuild/pants/pull/6037>`_

* Fix bad exclusion introduced during rushed change. (#6034)
  `PR #6034 <https://github.com/pantsbuild/pants/pull/6034>`_

* Fix unicode handling in Exiters (#6032)
  `PR #6032 <https://github.com/pantsbuild/pants/pull/6032>`_

* [pantsd] Improve environment unicode handling. (#6031)
  `PR #6031 <https://github.com/pantsbuild/pants/pull/6031>`_

* Actually return execution options (#6019)
  `PR #6019 <https://github.com/pantsbuild/pants/pull/6019>`_

* Ignore the `logs/` dir. (#6021)
  `PR #6021 <https://github.com/pantsbuild/pants/pull/6021>`_

* Fix edge removal in Graph that could make invalidation inaccurate (#6123)
  `PR #6123 <https://github.com/pantsbuild/pants/pull/6123>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Port errorprone to py3 (#6118)
  `PR #6118 <https://github.com/pantsbuild/pants/pull/6118>`_

* Port console to Python 3 (#6121)
  `PR #6121 <https://github.com/pantsbuild/pants/pull/6121>`_

* Port buildgen to py3 (#6110)
  `PR #6110 <https://github.com/pantsbuild/pants/pull/6110>`_

* Add release metadata to boxfuture (#6106)
  `PR #6106 <https://github.com/pantsbuild/pants/pull/6106>`_

* Port engine/fs.py datatype() instances (#6103)
  `PR #6103 <https://github.com/pantsbuild/pants/pull/6103>`_
  `PR #6098 <https://github.com/pantsbuild/pants/pull/6098>`_
  `PR #6092 <https://github.com/pantsbuild/pants/pull/6092>`_

* Port findbugs to py3. (#6120)
  `PR #6120 <https://github.com/pantsbuild/pants/pull/6120>`_

* Port codeanalysis to py3. (#6111)
  `PR #6111 <https://github.com/pantsbuild/pants/pull/6111>`_

* Port buildrefactor to py3. (#6109)
  `PR #6109 <https://github.com/pantsbuild/pants/pull/6109>`_

* Switch from output_async to spawn_async, and buffer output. (#6105)
  `PR #6105 <https://github.com/pantsbuild/pants/pull/6105>`_

* Allow Rust to store `unicode` as well as `bytes` (#6108)
  `PR #6108 <https://github.com/pantsbuild/pants/pull/6108>`_
  `PR #6103 <https://github.com/pantsbuild/pants/pull/6103>`_

* Remove unnecessary __future__ imports  (#6096)
  `PR #6096 <https://github.com/pantsbuild/pants/pull/6096>`_

* Port fs to python 3 compatibility (#6091)
  `PR #6091 <https://github.com/pantsbuild/pants/pull/6091>`_

* Nodes output cheaply-cloneable values (#6078)
  `PR #6078 <https://github.com/pantsbuild/pants/pull/6078>`_

* execution_strategy is a memoized_property (#6052)
  `PR #6052 <https://github.com/pantsbuild/pants/pull/6052>`_

* Port backend/python to Python 3 (#6086)
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_
  `PR #6086 <https://github.com/pantsbuild/pants/pull/6086>`_

* Port backend/native to Python 3 (#6084)
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_
  `PR #6084 <https://github.com/pantsbuild/pants/pull/6084>`_

* Port majority of pants/util to Python 3 (#6073)
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_
  `PR #6073 <https://github.com/pantsbuild/pants/pull/6073>`_

* Port backend/codegen and backend/docgen to Python 3 (#6083)
  `PR #6083 <https://github.com/pantsbuild/pants/pull/6083>`_

* Port util/process_handler.py and util/tarutil.py to Python 3 (#6082)
  `PR #6082 <https://github.com/pantsbuild/pants/pull/6082>`_
  `PR #6073 <https://github.com/pantsbuild/pants/pull/6073>`_

* Add `-ltrace` and requests debug logging. (#6070)
  `PR #6070 <https://github.com/pantsbuild/pants/pull/6070>`_

* Port util metaprogramming files to Python3 (#6072)
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_
  `PR #6072 <https://github.com/pantsbuild/pants/pull/6072>`_

* Add future lib and port src/base to Python3 (#6067)
  `Issue #6062), <https://github.com/pantsbuild/pants/issues/6062),>`_
  `PR #6067 <https://github.com/pantsbuild/pants/pull/6067>`_

* Run `futurize --stage1` to make safe changes for python 3 compatibility. (#6063)
  `PR #6063 <https://github.com/pantsbuild/pants/pull/6063>`_
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_

* Switch to a per-entry state machine in Graph (#6013)
  `PR #6013 <https://github.com/pantsbuild/pants/pull/6013>`_

* Log more in rust tests (#6060)
  `PR #6060 <https://github.com/pantsbuild/pants/pull/6060>`_

* Introduce libc subsystem to find crti.o on linux hosts and unskip the native backend subsystem tests (#5943)
  `PR #5943 <https://github.com/pantsbuild/pants/pull/5943>`_

* Clean up process execution python API (#6051)
  `PR #6051 <https://github.com/pantsbuild/pants/pull/6051>`_

* Skip pyprep and pytest-prep if there are no python targest (#6039)
  `PR #6039 <https://github.com/pantsbuild/pants/pull/6039>`_

* Simplify rust code (#6043)
  `PR #6043 <https://github.com/pantsbuild/pants/pull/6043>`_

* [remoting] Move local process execution tempdirs into the workdir, add option to not delete them (#6023)
  `PR #6023 <https://github.com/pantsbuild/pants/pull/6023>`_

* Many rust lints (#5982)
  `PR #5982 <https://github.com/pantsbuild/pants/pull/5982>`_

* Include type name in TypedDataType construction errors (#6015)
  `PR #6015 <https://github.com/pantsbuild/pants/pull/6015>`_

* Consolidate `src/python/pants/python` -> `src/python/pants/backend/python` (#6025)
  `PR #6025 <https://github.com/pantsbuild/pants/pull/6025>`_

* Extract and genericize Graph for easier testing (#6010)
  `PR #6010 <https://github.com/pantsbuild/pants/pull/6010>`_

* Add libc search noop option (#6122)
  `PR #6122 <https://github.com/pantsbuild/pants/pull/6122>`_

* Fix test_objects handling of dataclass() py2-py3 compatibility (#6098)
  `PR #6098 <https://github.com/pantsbuild/pants/pull/6098>`_
  `Issue #6062 <https://github.com/pantsbuild/pants/issues/6062>`_

1.9.0.dev0 (06/25/2018)
-----------------------

New features
~~~~~~~~~~~~

* Release Pants as a pex. (#6014)
  `PR #6014 <https://github.com/pantsbuild/pants/pull/6014>`_

* C/C++ targets which can be compiled/linked and used in python_dist() with ctypes (#5815)
  `PR #5815 <https://github.com/pantsbuild/pants/pull/5815>`_

API Changes
~~~~~~~~~~~

* Deprecate sources except EagerFilesetWithSpec (#5993)
  `PR #5993 <https://github.com/pantsbuild/pants/pull/5993>`_

* source attribute is automatically promoted to sources (#5908)
  `PR #5908 <https://github.com/pantsbuild/pants/pull/5908>`_

Bugfixes
~~~~~~~~

* Run scalafix before scalafmt (#6011)
  `PR #6011 <https://github.com/pantsbuild/pants/pull/6011>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add .vscode/ folder to .gitignore (#6020)
  `PR #6020 <https://github.com/pantsbuild/pants/pull/6020>`_

* [engine] Selecting for ExecuteProcessResult will Throw on non-zero exit (#6000)
  `PR #6000 <https://github.com/pantsbuild/pants/pull/6000>`_

* Context always has a scheduler in tests (#5997)
  `PR #5997 <https://github.com/pantsbuild/pants/pull/5997>`_

* Engine looks up default sources when parsing (#5989)
  `PR #5989 <https://github.com/pantsbuild/pants/pull/5989>`_

* Fix TestSetupPyInterpreter.test_setuptools_version (#5988)
  `PR #5988 <https://github.com/pantsbuild/pants/pull/5988>`_

* Caching tests are parsed through the engine (#5985)
  `PR #5985 <https://github.com/pantsbuild/pants/pull/5985>`_

* Override get_sources for pants plugins (#5984)
  `PR #5984 <https://github.com/pantsbuild/pants/pull/5984>`_

* make_target upgrades sources to EagerFilesetWithSpec (#5974)
  `PR #5974 <https://github.com/pantsbuild/pants/pull/5974>`_

* Robustify test_namespace_effective PYTHONPATH. (#5976)
  `PR #5976 <https://github.com/pantsbuild/pants/pull/5976>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* 1.7.0 release notes (#5983)
  `PR #5983 <https://github.com/pantsbuild/pants/pull/5983>`_

1.8.0rc0 (06/18/2018)
---------------------

Bugfixes
~~~~~~~~

* Shorten safe filenames further, and combine codepaths to make them readable. (#5971)
  `PR #5971 <https://github.com/pantsbuild/pants/pull/5971>`_

* Whitelist the --owner-of option to not restart the daemon. (#5979)
  `PR #5979 <https://github.com/pantsbuild/pants/pull/5979>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove DeprecatedPythonTaskTestBase (#5973)
  `Issue #5870 <https://github.com/pantsbuild/pants/issues/5870>`_
  `PR #5973 <https://github.com/pantsbuild/pants/pull/5973>`_

* Mark a few options that should not show up in `./pants help`. (#5968)
  `PR #5968 <https://github.com/pantsbuild/pants/pull/5968>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* adding more documentation for python_app (#5965)
  `PR #5965 <https://github.com/pantsbuild/pants/pull/5965>`_

1.8.0.dev4 (06/15/2018)
-----------------------

New features
~~~~~~~~~~~~

* Allow manylinux wheels when resolving plugins. (#5959)
  `PR #5959 <https://github.com/pantsbuild/pants/pull/5959>`_

* Separate the resolution cache and repository cache in Ivy (#5844)
  `PR #5844 <https://github.com/pantsbuild/pants/pull/5844>`_

* Allow pants to select targets by file(s) (#5930)
  `PR #5930 <https://github.com/pantsbuild/pants/pull/5930>`_

Bugfixes
~~~~~~~~

* Cobertura coverage: Include the full target closure's classpath entries for instrumentation (#5879)
  `PR #5879 <https://github.com/pantsbuild/pants/pull/5879>`_

* `exclude-patterns` and `tag` should apply only to roots (#5786)
  `PR #5786 <https://github.com/pantsbuild/pants/pull/5786>`_

* Fixup macosx platform version. (#5938)
  `PR #5938 <https://github.com/pantsbuild/pants/pull/5938>`_

* Ban bad `readonly` shell pattern (#5924)
  `PR #5924 <https://github.com/pantsbuild/pants/pull/5924>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Record start times per graph node and expose a method to summarize them. (#5964)
  `PR #5964 <https://github.com/pantsbuild/pants/pull/5964>`_

* Remove value wrapper on the python side of ffi. (#5961)
  `PR #5961 <https://github.com/pantsbuild/pants/pull/5961>`_

* Construct rule_graph recursively (#5955)
  `PR #5955 <https://github.com/pantsbuild/pants/pull/5955>`_

* Support output directory saving for local process execution. (#5944)
  `PR #5944 <https://github.com/pantsbuild/pants/pull/5944>`_

* use liblzma.dylib for xz on osx and add platform-specific testing to the rust osx shard (#5936)
  `PR #5936 <https://github.com/pantsbuild/pants/pull/5936>`_

* Improve PythonInterpreterCache logging (#5954)
  `PR #5954 <https://github.com/pantsbuild/pants/pull/5954>`_

* Re-shade zinc to avoid classpath collisions with annotation processors. (#5953)
  `PR #5953 <https://github.com/pantsbuild/pants/pull/5953>`_

* [pantsd] Robustify client connection logic. (#5952)
  `PR #5952 <https://github.com/pantsbuild/pants/pull/5952>`_

* Enable fromfile support for --owner-of and increase test coverage (#5948)
  `PR #5948 <https://github.com/pantsbuild/pants/pull/5948>`_

* move glob matching into its own file (#5945)
  `PR #5945 <https://github.com/pantsbuild/pants/pull/5945>`_

* Add new remote execution options (#5932)
  `PR #5932 <https://github.com/pantsbuild/pants/pull/5932>`_

* Use target not make_target in some tests (#5939)
  `PR #5939 <https://github.com/pantsbuild/pants/pull/5939>`_

* [jvm-compile] template-methodify JvmCompile further; add compiler choices (#5923)
  `PR #5923 <https://github.com/pantsbuild/pants/pull/5923>`_

* Add script to get a list of failing pants from travis (#5946)
  `PR #5946 <https://github.com/pantsbuild/pants/pull/5946>`_

* Integration test for daemon environment scrubbing (#5893)
  `PR #5893 <https://github.com/pantsbuild/pants/pull/5893>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* release notes for 1.7.0.rc1 (#5942)
  `PR #5942 <https://github.com/pantsbuild/pants/pull/5942>`_

* Add the --owner-of= usage on Target Address documentation (#5931)
  `PR #5931 <https://github.com/pantsbuild/pants/pull/5931>`_

1.8.0.dev3 (06/08/2018)
-----------------------

New features
~~~~~~~~~~~~

* Initial @rules for Options computation via the engine. (#5889)
  `PR #5889 <https://github.com/pantsbuild/pants/pull/5889>`_

* Pantsd terminates if its pidfile changes (#5877)
  `PR #5877 <https://github.com/pantsbuild/pants/pull/5877>`_

* Populate output_directory in ExecuteProcessResponse (#5896)
  `PR #5896 <https://github.com/pantsbuild/pants/pull/5896>`_

* Add support for passing an incremental_import option via idea-plugin (#5886)
  `PR #5886 <https://github.com/pantsbuild/pants/pull/5886>`_

Bugfixes
~~~~~~~~

* Fix `SelectInterpreter` read of `interpreter.path` (#5925)
  `PR #5925 <https://github.com/pantsbuild/pants/pull/5925>`_

* Fix rust log level comparison (#5918)
  `PR #5918 <https://github.com/pantsbuild/pants/pull/5918>`_

* Fix a trivial bug in error reporting in the kythe indexing task. (#5913)
  `PR #5913 <https://github.com/pantsbuild/pants/pull/5913>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Put the ChangeCalculator implementation next to TargetRootsCalculator (#5917)
  `PR #5917 <https://github.com/pantsbuild/pants/pull/5917>`_

* Remove sdist publishing hack. (#5926)
  `PR #5926 <https://github.com/pantsbuild/pants/pull/5926>`_

* Upgrade to pex 1.4.3. (#5910)
  `PR #5910 <https://github.com/pantsbuild/pants/pull/5910>`_

* Kill unused legacy code. (#5921)
  `PR #5921 <https://github.com/pantsbuild/pants/pull/5921>`_

* Add @classproperty (#5901)
  `PR #5901 <https://github.com/pantsbuild/pants/pull/5901>`_

* Simplify PathGlobs python datatype (#5915)
  `PR #5915 <https://github.com/pantsbuild/pants/pull/5915>`_

* Split short-form from long-form of setup_legacy_graph (#5911)
  `PR #5911 <https://github.com/pantsbuild/pants/pull/5911>`_

* Add Daniel McClanahan & Dorothy Ordogh to committers (#5909)
  `PR #5909 <https://github.com/pantsbuild/pants/pull/5909>`_

* Merge Root/Inner Entry cases into an EntryWithDeps case. (#5914)
  `PR #5914 <https://github.com/pantsbuild/pants/pull/5914>`_

* Make mock test server emit timing data (#5891)
  `PR #5891 <https://github.com/pantsbuild/pants/pull/5891>`_

* Update release jvm docs to have notes about gpg 2.1 (#5907)
  `PR #5907 <https://github.com/pantsbuild/pants/pull/5907>`_

* Set output_files field on remote Action (#5902)
  `PR #5902 <https://github.com/pantsbuild/pants/pull/5902>`_

* From<Digest> no longer panics (#5832)
  `PR #5832 <https://github.com/pantsbuild/pants/pull/5832>`_

* Use tempfile crate not tempdir crate (#5900)
  `PR #5900 <https://github.com/pantsbuild/pants/pull/5900>`_

1.8.0.dev2 (06/02/2018)
-----------------------

Bugfixes
~~~~~~~~

* Fix using classpath jars with compiler plugins (#5890)
  `PR #5890 <https://github.com/pantsbuild/pants/pull/5890>`_

* Fix visualize-to option post addition of Sessions (#5885)
  `PR #5885 <https://github.com/pantsbuild/pants/pull/5885>`_

* Robustify go_protobuf_library (#5887)
  `PR #5887 <https://github.com/pantsbuild/pants/pull/5887>`_

* Repair hermetic_environment_as for C-level environment variable access. (#5898)
  `PR #5898 <https://github.com/pantsbuild/pants/pull/5898>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add deprecation warning for pep8 'plugin' in pythonstyle suppress file (#5888)
  `PR #5888 <https://github.com/pantsbuild/pants/pull/5888>`_

* warn or error on matching source globs (#5769)
  `PR #5769 <https://github.com/pantsbuild/pants/pull/5769>`_

* Mark things which generate cffi for change detection (#5883)
  `PR #5883 <https://github.com/pantsbuild/pants/pull/5883>`_

* Sort list goal output (#5872)
  `PR #5872 <https://github.com/pantsbuild/pants/pull/5872>`_

* Output stdout and stderr when nailgun fails to connect (#5892)
  `PR #5892 <https://github.com/pantsbuild/pants/pull/5892>`_

New features
~~~~~~~~~~~~

* Remote execution can be enabled by flags (#5881)
  `PR #5881 <https://github.com/pantsbuild/pants/pull/5881>`_

1.8.0.dev1 (05/25/2018)
-----------------------

Bugfixes
~~~~~~~~

* Fix Go distribution SYSTEM_ID key (#5861)
  `PR #5861 <https://github.com/pantsbuild/pants/pull/5861>`_

* Improve logging/handling of signaled, killed, and terminated tests (#5859)
  `PR #5859 <https://github.com/pantsbuild/pants/pull/5859>`_

* Use write_all not write (#5852)
  `PR #5852 <https://github.com/pantsbuild/pants/pull/5852>`_

New features
~~~~~~~~~~~~

* Add go_protobuf_library (#5838)
  `PR #5838 <https://github.com/pantsbuild/pants/pull/5838>`_

* setup_requires argument for python_dist targets (#5825)
  `PR #5825 <https://github.com/pantsbuild/pants/pull/5825>`_

API Changes
~~~~~~~~~~~

* Update pep8 to pycodestyle (#5867)
  `PR #5867 <https://github.com/pantsbuild/pants/pull/5867>`_

* Update pyflakes to 2.0.0 (#5866)
  `PR #5866 <https://github.com/pantsbuild/pants/pull/5866>`_

* Port BaseTest to v2 engine as TestBase (#5611)
  `PR #5611 <https://github.com/pantsbuild/pants/pull/5611>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [remoting] Store raw bytes for stdout and stderr if received inline. (#5855)
  `PR #5855 <https://github.com/pantsbuild/pants/pull/5855>`_

* [rust/engine] add timeout \ description for grpc process requests (#5632)
  `PR #5632 <https://github.com/pantsbuild/pants/pull/5632>`_

* Use tokio for scheduler requests and local process execution (#5846)
  `PR #5846 <https://github.com/pantsbuild/pants/pull/5846>`_

* Rust compilation is more robust and fast (#5857)
  `PR #5857 <https://github.com/pantsbuild/pants/pull/5857>`_

* Core has a CommandRunner (#5850)
  `PR #5850 <https://github.com/pantsbuild/pants/pull/5850>`_

* Only depend on subprocess32 in python2. (#5847)
  `PR #5847 <https://github.com/pantsbuild/pants/pull/5847>`_

* Hermeticize cargo build. (#5742)
  `PR #5742 <https://github.com/pantsbuild/pants/pull/5742>`_

* A utility to aggregate s3 access logs. (#5777)
  `PR #5777 <https://github.com/pantsbuild/pants/pull/5777>`_

* Update all rust dependencies (ie, ran `cargo update`). (#5845)
  `PR #5845 <https://github.com/pantsbuild/pants/pull/5845>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Document how to select a Python interpreter (#5843)
  `PR #5843 <https://github.com/pantsbuild/pants/pull/5843>`_

1.8.0.dev0 (05/18/2018)
-----------------------

Bugfixes
~~~~~~~~

* Invalidate all tasks on source root changes. (#5821)
  `PR #5821 <https://github.com/pantsbuild/pants/pull/5821>`_

New features
~~~~~~~~~~~~

* Allow alternate binaries download urls generation and convert GoDistribution and LLVM subsystems to use it (#5780)
  `PR #5780 <https://github.com/pantsbuild/pants/pull/5780>`_

API Changes
~~~~~~~~~~~

* Remove SelectDependencies. (#5800)
  `PR #5800 <https://github.com/pantsbuild/pants/pull/5800>`_

* Zinc 1.0.0 upgrade: Python portion (#4729)
  `PR #4729 <https://github.com/pantsbuild/pants/pull/4729>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Revert to non-forked grpcio-compiler (#5842)
  `PR #5842 <https://github.com/pantsbuild/pants/pull/5842>`_

* cloc uses v2 process execution (#5840)
  `PR #5840 <https://github.com/pantsbuild/pants/pull/5840>`_

* Remove extra workunit from coursier resolve (#5837)
  `PR #5837 <https://github.com/pantsbuild/pants/pull/5837>`_

* Remove stale comment (#5839)
  `PR #5839 <https://github.com/pantsbuild/pants/pull/5839>`_

* Script BinaryUtils can be captured as snapshots (#5835)
  `PR #5835 <https://github.com/pantsbuild/pants/pull/5835>`_

* CommandRunners implement a single trait (#5836)
  `PR #5836 <https://github.com/pantsbuild/pants/pull/5836>`_

* Directories can be merged synchronously (#5834)
  `PR #5834 <https://github.com/pantsbuild/pants/pull/5834>`_

* Allow arbitrary directories to be Snapshotted (#5801)
  `PR #5801 <https://github.com/pantsbuild/pants/pull/5801>`_

* Regression test for #4596 (#4608)
  `PR #4608 <https://github.com/pantsbuild/pants/pull/4608>`_

* Empty digest is always known (#5829)
  `PR #5829 <https://github.com/pantsbuild/pants/pull/5829>`_

* Local process execution can fetch output files (#5784)
  `PR #5784 <https://github.com/pantsbuild/pants/pull/5784>`_

* Fetch native stack traces if any cores were dumped (#5828)
  `PR #5828 <https://github.com/pantsbuild/pants/pull/5828>`_

* FileContents is gotten from DirectoryDigest not Snapshot (#5820)
  `PR #5820 <https://github.com/pantsbuild/pants/pull/5820>`_

* [release.sh] Use git configured gpg binary if one is set (#5826)
  `PR #5826 <https://github.com/pantsbuild/pants/pull/5826>`_

* [release-doc] rm explicit owner list in favor of just using -o (#5823)
  `PR #5823 <https://github.com/pantsbuild/pants/pull/5823>`_

* brfs: Sleep a bit after mounting the filesystem (#5819)
  `PR #5819 <https://github.com/pantsbuild/pants/pull/5819>`_

* Snapshot contains a DirectoryDigest (#5811)
  `PR #5811 <https://github.com/pantsbuild/pants/pull/5811>`_

* Add a facility for exposing metrics from the native engine (#5808)
  `PR #5808 <https://github.com/pantsbuild/pants/pull/5808>`_

* Expand engine readme (#5759)
  `PR #5759 <https://github.com/pantsbuild/pants/pull/5759>`_

* Document python_app target in Python readme. (#5816)
  `PR #5816 <https://github.com/pantsbuild/pants/pull/5816>`_

* [release-docs] Update step 0, linkify links (#5806)
  `PR #5806 <https://github.com/pantsbuild/pants/pull/5806>`_

1.7.0.rc0 (05/11/2018)
----------------------

Bugfixes
~~~~~~~~

* Fix a broken 3rdparty example. (#5797)
  `PR #5797 <https://github.com/pantsbuild/pants/pull/5797>`_

* Adding compile scopes, because thats expected from doc gen (#5789)
  `PR #5789 <https://github.com/pantsbuild/pants/pull/5789>`_

* Copy locally build .whl files to dist dir when 'binary' goal is invoked. (#5749)
  `PR #5749 <https://github.com/pantsbuild/pants/pull/5749>`_

* [pytest runner] re-add --options flag as a shlexed list of strings (#5790)
  `PR #5790 <https://github.com/pantsbuild/pants/pull/5790>`_
  `PR #) <https://github.com/pantsbuild/pants/pull/5594/)>`_

New features
~~~~~~~~~~~~

* add --frozen-lockfile option as default for yarn install (#5758)
  `PR #5758 <https://github.com/pantsbuild/pants/pull/5758>`_

* Remove jvm compile subsystem (#5805)
  `PR #5805 <https://github.com/pantsbuild/pants/pull/5805>`_

* Add Javac compile option as an alternative to Zinc (#5743)
  `PR #5743 <https://github.com/pantsbuild/pants/pull/5743>`_

* Add python_app support (#5704)
  `PR #5704 <https://github.com/pantsbuild/pants/pull/5704>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Bump to scala 2.11.12 by default. (#5804)
  `PR #5804 <https://github.com/pantsbuild/pants/pull/5804>`_

* Review feedback from #5792. (#5796)
  `PR #5796 <https://github.com/pantsbuild/pants/pull/5796>`_

* Skip commit hooks during publishing (#5795)
  `PR #5795 <https://github.com/pantsbuild/pants/pull/5795>`_

* Improve support for intrinsic tasks (#5792)
  `PR #5792 <https://github.com/pantsbuild/pants/pull/5792>`_

* Remote CommandRunner has reset_prefork method (#5791)
  `PR #5791 <https://github.com/pantsbuild/pants/pull/5791>`_

* PosixFS can get PathStats for a set of PathBufs (#5783)
  `PR #5783 <https://github.com/pantsbuild/pants/pull/5783>`_

* Bump to zinc 1.1.7 (#5794)
  `PR #5794 <https://github.com/pantsbuild/pants/pull/5794>`_

* Add configurable timeouts for reading/writing to the cache. (#5793)
  `PR #5793 <https://github.com/pantsbuild/pants/pull/5793>`_

* Improve clarity of the "why use pants" page (#5778)
  `PR #5778 <https://github.com/pantsbuild/pants/pull/5778>`_

* Repair PyPI user checking in release scripts. (#5787)
  `PR #5787 <https://github.com/pantsbuild/pants/pull/5787>`_

1.7.0.dev2 (05/04/2018)
-----------------------

New features
~~~~~~~~~~~~

* Wrap ShardedLmdb in a Resettable (#5775)
  `PR #5775 <https://github.com/pantsbuild/pants/pull/5775>`_

* Expand type constraints allowed in datatype() (#5774)
  `PR #5774 <https://github.com/pantsbuild/pants/pull/5774>`_

* Introduce Resettable (#5770)
  `PR #5770 <https://github.com/pantsbuild/pants/pull/5770>`_

* Add support for merging Snapshots (#5746)
  `PR #5746 <https://github.com/pantsbuild/pants/pull/5746>`_

* Remodel of node subsystem (#5698)
  `PR #5698 <https://github.com/pantsbuild/pants/pull/5698>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Extract OneOffStoreFileByDigest (#5782)
  `PR #5782 <https://github.com/pantsbuild/pants/pull/5782>`_

* Introduce a backdoor around PYTHONPATH scrubbing in pytest runs. (#5767)
  `PR #5767 <https://github.com/pantsbuild/pants/pull/5767>`_

* Address @jsirois final comments that were not addressed on PR #5765 (#5773)
  `PR #5773 <https://github.com/pantsbuild/pants/pull/5773>`_

* Extract AppBase base class (#5772)
  `PR #5772 <https://github.com/pantsbuild/pants/pull/5772>`_

* Bump ordermap to indexmap 1 (#5771)
  `PR #5771 <https://github.com/pantsbuild/pants/pull/5771>`_

* Disable lint for Python 3 targets (#5765)
  `PR #5765 <https://github.com/pantsbuild/pants/pull/5765>`_

* Nav menu change with drop-downs (#5750)
  `PR #5750 <https://github.com/pantsbuild/pants/pull/5750>`_

* Expose rules from language backends with an application to python_dist() creation (#5747)
  `PR #5747 <https://github.com/pantsbuild/pants/pull/5747>`_

* Move From impls from hashing to bazel_protos (#5706)
  `PR #5706 <https://github.com/pantsbuild/pants/pull/5706>`_

* Reformat bazel_protos/build.rs (#5760)
  `PR #5760 <https://github.com/pantsbuild/pants/pull/5760>`_

* Add test that pantsd can be used twice in parallel (#5757)
  `PR #5757 <https://github.com/pantsbuild/pants/pull/5757>`_

* type-check specific datatype fields concisely and remove the class name argument (#5723)
  `PR #5723 <https://github.com/pantsbuild/pants/pull/5723>`_

* expand doc publish script, use products for sitegen tasks, and clarify the publish site subdir option (#5702)
  `PR #5702 <https://github.com/pantsbuild/pants/pull/5702>`_

* Prepare 1.6.0rc3 (#5756)
  `PR #5756 <https://github.com/pantsbuild/pants/pull/5756>`_

* Save noop time on codegen (#5748)
  `PR #5748 <https://github.com/pantsbuild/pants/pull/5748>`_

* Rename and simplify store_list. (#5751)
  `PR #5751 <https://github.com/pantsbuild/pants/pull/5751>`_

* Boxable::to_boxed returns BoxFuture not Box<Self> (#5754)
  `PR #5754 <https://github.com/pantsbuild/pants/pull/5754>`_

* Misc rust fixups (#5753)
  `PR #5753 <https://github.com/pantsbuild/pants/pull/5753>`_

* eagerly fetch stderr in remote process execution (#5735)
  `PR #5735 <https://github.com/pantsbuild/pants/pull/5735>`_

* Looping request with backoff period (#5714)
  `PR #5714 <https://github.com/pantsbuild/pants/pull/5714>`_

* Fixup dev-dependencies in brfs. (#5745)
  `PR #5745 <https://github.com/pantsbuild/pants/pull/5745>`_

* brfs: FUSE filesystem exposing the Store and remote CAS (#5705)
  `PR #5705 <https://github.com/pantsbuild/pants/pull/5705>`_

* Update errorprone to 2.3.1 and findbugs to spotbugs 3.1.3 (#5725)
  `PR #5725 <https://github.com/pantsbuild/pants/pull/5725>`_

* Dedupe parsed Gets (#5700)
  `PR #5700 <https://github.com/pantsbuild/pants/pull/5700>`_

* Update my name to the right one (#5741)
  `PR #5741 <https://github.com/pantsbuild/pants/pull/5741>`_

* Stop using tools.jar for JAXB xjc tool since tools.jar has been removed from Java 9+ (#5740)
  `PR #5740 <https://github.com/pantsbuild/pants/pull/5740>`_

* Update running from sources docs (#5731)
  `PR #5731 <https://github.com/pantsbuild/pants/pull/5731>`_

* Use Scala 2.12.4 for --scala-platform-version=2.12 (#5738)
  `PR #5738 <https://github.com/pantsbuild/pants/pull/5738>`_

* Extract reusable test data (#5737)
  `PR #5737 <https://github.com/pantsbuild/pants/pull/5737>`_

* Only upload digests missing from CAS (#5713)
  `PR #5713 <https://github.com/pantsbuild/pants/pull/5713>`_

* Prepare 1.5.1rc2 (#5734)
  `PR #5734 <https://github.com/pantsbuild/pants/pull/5734>`_

* Break a Core / Node cycle  (#5733)
  `PR #5733 <https://github.com/pantsbuild/pants/pull/5733>`_

* [rm-deprecation] remove leveled_predicate kwarg from buildgraph walk fns (#5730)
  `PR #5730 <https://github.com/pantsbuild/pants/pull/5730>`_

* Bump max local store size (#5728)
  `PR #5728 <https://github.com/pantsbuild/pants/pull/5728>`_

1.7.0.dev1 (04/20/2018)
-----------------------

New features
~~~~~~~~~~~~

* Plumb requirement blacklist through to the pex resolver (#5697)
  `PR #5697 <https://github.com/pantsbuild/pants/pull/5697>`_

* Add interpreter identity check for non-blacklisted interpreters (#5724)
  `PR #5724 <https://github.com/pantsbuild/pants/pull/5724>`_

* Eagerly fetch stdout on remote execution response (#5712)
  `PR #5712 <https://github.com/pantsbuild/pants/pull/5712>`_

Bugfixes
~~~~~~~~

* java_agent gets added to manifest for java_binary targets (#5722)
  `PR #5722 <https://github.com/pantsbuild/pants/pull/5722>`_

* Ensure test goal implicitly targets current platform when using python_dist targets (#5720)
  `PR #5720 <https://github.com/pantsbuild/pants/pull/5720>`_
  `PR #5618 <https://github.com/pantsbuild/pants/pull/5618>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Update junit-runner to 1.0.24 and use junit-runner-annotations 0.0.21 in tests (#5721)
  `PR #5721 <https://github.com/pantsbuild/pants/pull/5721>`_

* convert usages of the ExecuteProcess helper into simple @rules to simplify snapshot consumption for process execution (#5703)
  `PR #5703 <https://github.com/pantsbuild/pants/pull/5703>`_

* Fix some errorprone warnings and remove duplicates from findbugs targets (#5711)
  `PR #5711 <https://github.com/pantsbuild/pants/pull/5711>`_

1.7.0.dev0 (04/13/2018)
-----------------------

New Features
~~~~~~~~~~~~

* @rules as coroutines (#5580)
  `PR #5580 <https://github.com/pantsbuild/pants/pull/5580>`_

API Changes
~~~~~~~~~~~
* Delete deprecated android backend (#5695)
  `PR #5695 <https://github.com/pantsbuild/pants/pull/5695>`_

* 1.7.0 deprecations (#5681)
  `PR #5681 <https://github.com/pantsbuild/pants/pull/5681>`_

* Remove SelectProjection. (#5672)
  `PR #5672 <https://github.com/pantsbuild/pants/pull/5672>`_

Bugfixes
~~~~~~~~

* Fixup RST parsing error. (#5687)
  `PR #5687 <https://github.com/pantsbuild/pants/pull/5687>`_

* Fix shader to not shade .class files under META-INF directory (#5671)
  `PR #5671 <https://github.com/pantsbuild/pants/pull/5671>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Use absolute path to check_rust_formatting (#5694)
  `PR #5694 <https://github.com/pantsbuild/pants/pull/5694>`_

* Remove unnecessary parens (#5693)
  `PR #5693 <https://github.com/pantsbuild/pants/pull/5693>`_

* Don't rename process_execution to process_executor (#5692)
  `PR #5692 <https://github.com/pantsbuild/pants/pull/5692>`_

* Run process execution Nodes on a CpuPool (#5691)
  `PR #5691 <https://github.com/pantsbuild/pants/pull/5691>`_

* add docs about how to run rust in IntelliJ (#5688)
  `PR #5688 <https://github.com/pantsbuild/pants/pull/5688>`_

* Prepare 1.6.0rc2 (#5690)
  `PR #5690 <https://github.com/pantsbuild/pants/pull/5690>`_

* Reset LMDB Environments when forking (#5689)
  `PR #5689 <https://github.com/pantsbuild/pants/pull/5689>`_

* Part 1: Add ability to check what CAS blobs are missing (#5686)
  `PR #5686 <https://github.com/pantsbuild/pants/pull/5686>`_

* Improve pypi package expected releasers pre-check. (#5669)
  `PR #5669 <https://github.com/pantsbuild/pants/pull/5669>`_

* Prepare 1.6.0rc1 (#5685)
  `PR #5685 <https://github.com/pantsbuild/pants/pull/5685>`_

* Make coursier resolve more friendly (#5675)
  `PR #5675 <https://github.com/pantsbuild/pants/pull/5675>`_

* Upgrade virtualenv. (#5679)
  `PR #5679 <https://github.com/pantsbuild/pants/pull/5679>`_

* Cleanup `unused_parens` warning for cast. (#5677)
  `PR #5677 <https://github.com/pantsbuild/pants/pull/5677>`_

* Add build_flags per go_binary (#5658)
  `PR #5658 <https://github.com/pantsbuild/pants/pull/5658>`_

* Bump to rust 1.25 (#5670)
  `PR #5670 <https://github.com/pantsbuild/pants/pull/5670>`_

* Add explicit JAXB dependencies in the junit-runner so it works in Java 9+ without --add-modules=java.xml.bind (#5667)
  `PR #5667 <https://github.com/pantsbuild/pants/pull/5667>`_

* [junit-runner] cache localhost lookups to ease OSX/JDK DNS issues (#5660)
  `PR #5660 <https://github.com/pantsbuild/pants/pull/5660>`_

* Narrow down BuildLocalPythonDistributions target type (#5659)
  `PR #5659 <https://github.com/pantsbuild/pants/pull/5659>`_

* Run `lint` in commit hooks. (#5666)
  `PR #5666 <https://github.com/pantsbuild/pants/pull/5666>`_

* Ban testprojects/pants-plugins from TestProjectsIntegrationTest. (#5665)
  `PR #5665 <https://github.com/pantsbuild/pants/pull/5665>`_

1.6.0rc0 (04/04/2018)
---------------------

Bugfixes
~~~~~~~~

* Memoize stable task creation (#5654)
  `PR #5654 <https://github.com/pantsbuild/pants/pull/5654>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Merge TargetRoots subclasses (#5648)
  `PR #5648 <https://github.com/pantsbuild/pants/pull/5648>`_

* Handle `native_engine.so` resources without headers. (#5653)
  `PR #5653 <https://github.com/pantsbuild/pants/pull/5653>`_

* Per-run metrics for target roots, transitive target counts. (#5651)
  `PR #5651 <https://github.com/pantsbuild/pants/pull/5651>`_

* Release script cleanups. (#5650)
  `PR #5650 <https://github.com/pantsbuild/pants/pull/5650>`_

* Only create native engine resource when needed. (#5649)
  `PR #5649 <https://github.com/pantsbuild/pants/pull/5649>`_

* Include rust stdlib sources in bootstrap. (#5645)
  `PR #5645 <https://github.com/pantsbuild/pants/pull/5645>`_

1.6.0.dev2 (04/01/2018)
-----------------------

Bugfixes
~~~~~~~~

* Resolve for current platform only if resolving a local python dist with native extensions (#5618)
  `PR #5618 <https://github.com/pantsbuild/pants/pull/5618>`_

* Fail for deleted-but-depended-on targets in changed (#5636)
  `PR #5636 <https://github.com/pantsbuild/pants/pull/5636>`_

* Restore and modernize `--changed` tests (#5635)
  `PR #5635 <https://github.com/pantsbuild/pants/pull/5635>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* missing-deps-suggest outputs buildozer commands if path to buildozer is set (#5638)
  `PR #5638 <https://github.com/pantsbuild/pants/pull/5638>`_

* Rewrite package listing and ownership parts of release.sh in python (#5629)
  `PR #5629 <https://github.com/pantsbuild/pants/pull/5629>`_

* Add dependency on six (#5633)
  `PR #5633 <https://github.com/pantsbuild/pants/pull/5633>`_

* [pantsd] Don't initialize a scheduler for pantsd lifecycle checks. (#5624)
  `PR #5624 <https://github.com/pantsbuild/pants/pull/5624>`_

* Make build_dictionary.html easier to read (#5631)
  `PR #5631 <https://github.com/pantsbuild/pants/pull/5631>`_

1.6.0.dev1 (03/25/2018)
-----------------------

New Features
~~~~~~~~~~~~
* Record critical path timings of goals (#5609)
  `PR #5609 <https://github.com/pantsbuild/pants/pull/5609>`_

API Changes
~~~~~~~~~~~
* Disable google java format by default (#5623)
  `PR #5623 <https://github.com/pantsbuild/pants/pull/5623>`_

Bugfixes
~~~~~~~~
* [export] use same artifact cache override with VersionedTargetSet (#5620)
  `PR #5620 <https://github.com/pantsbuild/pants/pull/5620>`_

* Memoize org.scalatest.Suite class loading (#5614)
  `PR #5614 <https://github.com/pantsbuild/pants/pull/5614>`_

* Batch execution of address Specs and remove SelectTransitive (#5605)
  `PR #5605 <https://github.com/pantsbuild/pants/pull/5605>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Bump coursier version to 1.1.0.cf365ea27a710d5f09db1f0a6feee129aa1fc417 (#5625)
  `PR #5625 <https://github.com/pantsbuild/pants/pull/5625>`_

* Drop a golang dep that no longer appears to be used transitively... and yet somehow still seems to be failing. (#5619)
  `PR #5619 <https://github.com/pantsbuild/pants/pull/5619>`_


1.6.0.dev0 (03/17/2018)
-----------------------

New Features
~~~~~~~~~~~~

* Add google-java-format fmt/lint support (#5596)
  `PR #5596 <https://github.com/pantsbuild/pants/pull/5596>`_

API Changes
~~~~~~~~~~~

* Deprecate BinaryUtil as public API. (#5601)
  `PR #5601 <https://github.com/pantsbuild/pants/pull/5601>`_

Bugfixes
~~~~~~~~

* Fix `PytestRun` passthru arg handling. (#5594)
  `PR #5594 <https://github.com/pantsbuild/pants/pull/5594>`_

* [pantsd] Repair stale sources invalidation case. (#5589)
  `PR #5589 <https://github.com/pantsbuild/pants/pull/5589>`_

* [coursier/m2-coords] update coursier json parsing; use maven's coords (#5475)
  `PR #5475 <https://github.com/pantsbuild/pants/pull/5475>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Robustify `SetupPyIntegrationTest`. #5610
  `PR #5610 <https://github.com/pantsbuild/pants/pull/5610>`_

* Prepare 1.5.0rc1 (#5603)
  `PR #5603 <https://github.com/pantsbuild/pants/pull/5603>`_

* Use readable errno descriptions for lmdb errors (#5604)
  `PR #5604 <https://github.com/pantsbuild/pants/pull/5604>`_

* Convert scalafmt test to a unit test. (#5599)
  `PR #5599 <https://github.com/pantsbuild/pants/pull/5599>`_

* Materialized files have the executable bit set correctly (#5593)
  `PR #5593 <https://github.com/pantsbuild/pants/pull/5593>`_

* Render a warning rather than failing `list` when no targets are matched (#5598)
  `PR #5598 <https://github.com/pantsbuild/pants/pull/5598>`_

* New BinaryTool subsystems for node and yarnpkg. (#5584)
  `PR #5584 <https://github.com/pantsbuild/pants/pull/5584>`_

* Further --changed optimization (#5579)
  `PR #5579 <https://github.com/pantsbuild/pants/pull/5579>`_

* Yet more rustfmt (#5597)
  `PR #5597 <https://github.com/pantsbuild/pants/pull/5597>`_
  `PR #5592 <https://github.com/pantsbuild/pants/pull/5592>`_

* [pantsd] Don't compute TargetRoots twice. (#5595)
  `PR #5595 <https://github.com/pantsbuild/pants/pull/5595>`_

* Use pre-compiled rustfmt instead of compiling it ourselves (#5592)
  `PR #5592 <https://github.com/pantsbuild/pants/pull/5592>`_

* [coursier] use same artifact cache override as ivy (#5586)
  `PR #5586 <https://github.com/pantsbuild/pants/pull/5586>`_

* Log when we try to upload files (#5591)
  `PR #5591 <https://github.com/pantsbuild/pants/pull/5591>`_

* Revert "Port BaseTest to v2 engine" (#5590)
  `PR #5590 <https://github.com/pantsbuild/pants/pull/5590>`_

* Update buildozer to 0.6.0-80c7f0d45d7e40fa1f7362852697d4a03df557b3 (#5581)
  `PR #5581 <https://github.com/pantsbuild/pants/pull/5581>`_

* Rust logging uses Python logging levels (#5528)
  `PR #5528 <https://github.com/pantsbuild/pants/pull/5528>`_

* Port BaseTest to v2 engine (#4867)
  `PR #4867 <https://github.com/pantsbuild/pants/pull/4867>`_

* Prepare 1.4.0! (#5583)
  `PR #5583 <https://github.com/pantsbuild/pants/pull/5583>`_

* Uniform handling of subsystem discovery (#5575)
  `PR #5575 <https://github.com/pantsbuild/pants/pull/5575>`_

* Send an empty WriteRequest for an empty file (#5578)
  `PR #5578 <https://github.com/pantsbuild/pants/pull/5578>`_

* Don't force fsync on every lmdb write transaction

* Shard lmdb by top 4 bits of fingerprint

* Revert "Revert a bunch of remoting PRs (#5543)"
  `PR #5543 <https://github.com/pantsbuild/pants/pull/5543>`_

* release.sh -q builds single-platform pexes locally (#5563)
  `PR #5563 <https://github.com/pantsbuild/pants/pull/5563>`_

1.5.0rc0 (03/07/2018)
---------------------

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Cleanup v1 changed code. (#5572)
  `PR #5572 <https://github.com/pantsbuild/pants/pull/5572>`_

* Improve the performance of v2 changed. (#5571)
  `PR #5571 <https://github.com/pantsbuild/pants/pull/5571>`_

* Delete obsolete README. (#5573)
  `PR #5573 <https://github.com/pantsbuild/pants/pull/5573>`_

* Improve interpreter constraint tests and docs. (#5566)
  `PR #5566 <https://github.com/pantsbuild/pants/pull/5566>`_

* Engine is a workspace (#5555)
  `PR #5555 <https://github.com/pantsbuild/pants/pull/5555>`_

* Native engine is a stripped cdylib (#5557)
  `PR #5557 <https://github.com/pantsbuild/pants/pull/5557>`_

* Don't overwrite cffi files if they haven't changed (#5553)
  `PR #5553 <https://github.com/pantsbuild/pants/pull/5553>`_

* Don't install panic handler when RUST_BACKTRACE=1 (#5561)
  `PR #5561 <https://github.com/pantsbuild/pants/pull/5561>`_

* Only shift once, not twice (#5552)
  `Issue #5551 <https://github.com/pantsbuild/pants/issues/5551>`_
  `PR #5552 <https://github.com/pantsbuild/pants/pull/5552>`_

* Prepare 1.4.0rc4 (#5569)
  `PR #5569 <https://github.com/pantsbuild/pants/pull/5569>`_

* [pantsd] Daemon lifecycle invalidation on configurable glob watches. (#5550)
  `PR #5550 <https://github.com/pantsbuild/pants/pull/5550>`_

* Set thrifty build_file_aliases (#5559)
  `PR #5559 <https://github.com/pantsbuild/pants/pull/5559>`_

* Better `PantsRunIntegrationTest` invalidation. (#5547)
  `PR #5547 <https://github.com/pantsbuild/pants/pull/5547>`_

* Support coverage of pants coverage tests. (#5544)
  `PR #5544 <https://github.com/pantsbuild/pants/pull/5544>`_

* Tighten `PytestRun` coverage plugin. (#5542)
  `PR #5542 <https://github.com/pantsbuild/pants/pull/5542>`_

* One additional change for 1.4.0rc3. (#5549)
  `PR #5549 <https://github.com/pantsbuild/pants/pull/5549>`_

* Provide injectables functionality in a mixin. (#5548)
  `PR #5548 <https://github.com/pantsbuild/pants/pull/5548>`_

* Revert a bunch of remoting PRs (#5543)
  `PR #5543 <https://github.com/pantsbuild/pants/pull/5543>`_

* Prep 1.4.0rc3 (#5545)
  `PR #5545 <https://github.com/pantsbuild/pants/pull/5545>`_

* CLean up fake options creation in tests. (#5539)
  `PR #5539 <https://github.com/pantsbuild/pants/pull/5539>`_

* Don't cache lmdb_store directory (#5541)
  `PR #5541 <https://github.com/pantsbuild/pants/pull/5541>`_

New Features
~~~~~~~~~~~~

* Thrifty support for pants (#5531)
  `PR #5531 <https://github.com/pantsbuild/pants/pull/5531>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Fix documentation code blocks. (#5558)
  `PR #5558 <https://github.com/pantsbuild/pants/pull/5558>`_

1.5.0.dev5 (03/02/2018)
-----------------------

New Features
~~~~~~~~~~~~

* Add ability for pants to call coursier with the new url attribute (#5527)
  `PR #5527 <https://github.com/pantsbuild/pants/pull/5527>`_

* Don't force inherit_path to be a bool (#5482)
  `PR #5482 <https://github.com/pantsbuild/pants/pull/5482>`_
  `PR #444 <https://github.com/pantsbuild/pex/pull/444>`_

Bugfixes
~~~~~~~~

* [pantsd] Repair end to end runtracker timing for pantsd runs. (#5526)
  `PR #5526 <https://github.com/pantsbuild/pants/pull/5526>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Generate a single python source chroot. (#5535)
  `PR #5535 <https://github.com/pantsbuild/pants/pull/5535>`_

* Improve py.test covered paths reporting. (#5534)
  `PR #5534 <https://github.com/pantsbuild/pants/pull/5534>`_

* Improve test reporting in batched partitions. (#5420)
  `PR #5420 <https://github.com/pantsbuild/pants/pull/5420>`_

* Fix non-exportable library target subclasses (#5533)
  `PR #5533 <https://github.com/pantsbuild/pants/pull/5533>`_

* Cleanups for 3bdd5506dc3 that I forgot to push before merging. (#5529)
  `PR #5529 <https://github.com/pantsbuild/pants/pull/5529>`_

* New-style BinaryTool Subsystems for isort and go distribution. (#5523)
  `PR #5523 <https://github.com/pantsbuild/pants/pull/5523>`_

* Use rust logging API (#5525)
  `PR #5525 <https://github.com/pantsbuild/pants/pull/5525>`_

* Add comment about significance of unsorted-ness of sources (#5524)
  `PR #5524 <https://github.com/pantsbuild/pants/pull/5524>`_

* cloc never executes in the v2 engine (#5518)
  `PR #5518 <https://github.com/pantsbuild/pants/pull/5518>`_

* Robustify `PantsRequirementIntegrationTest`. (#5520)
  `PR #5520 <https://github.com/pantsbuild/pants/pull/5520>`_

* Subsystems for the ragel and cloc binaries (#5517)
  `PR #5517 <https://github.com/pantsbuild/pants/pull/5517>`_

* Move Key interning to rust (#5455)
  `PR #5455 <https://github.com/pantsbuild/pants/pull/5455>`_

* Don't reinstall plugin wheels on every invocation. (#5506)
  `PR #5506 <https://github.com/pantsbuild/pants/pull/5506>`_

* A new Thrift binary tool subsystem. (#5512)
  `PR #5512 <https://github.com/pantsbuild/pants/pull/5512>`_


1.5.0.dev4 (02/23/2018)
-----------------------

New Features
~~~~~~~~~~~~

* Fix up remote process execution (#5500)
  `PR #5500 <https://github.com/pantsbuild/pants/pull/5500>`_

* Remote execution uploads files from a Store (#5499)
  `PR #5499 <https://github.com/pantsbuild/pants/pull/5499>`_

Public API Changes
~~~~~~~~~~~~~~~~~~

* Redesign JavaScript Style Checker to use ESLint directly (#5265)
  `PR #5265 <https://github.com/pantsbuild/pants/pull/5265>`_

* A convenient mechanism for fetching binary tools via subsystems (#5443)
  `PR #5443 <https://github.com/pantsbuild/pants/pull/5443>`_

* Qualify kythe target names with 'java-'. (#5459)
  `PR #5459 <https://github.com/pantsbuild/pants/pull/5459>`_

Bugfixes
~~~~~~~~

* [pantsd] Set the remote environment for pantsd-runner and child processes. (#5508)
  `PR #5508 <https://github.com/pantsbuild/pants/pull/5508>`_

* Don't special-case python dists in resolve_requirements(). (#5483)
  `PR #5483 <https://github.com/pantsbuild/pants/pull/5483>`_

* Add a dependency on the pants source to the integration test base target (#5481)
  `PR #5481 <https://github.com/pantsbuild/pants/pull/5481>`_

* fix/integration test for pants_requirement() (#5457)
  `PR #5457 <https://github.com/pantsbuild/pants/pull/5457>`_

* Never allow the shader to rewrite the empty-string package. (#5461)
  `PR #5461 <https://github.com/pantsbuild/pants/pull/5461>`_

* Bump release.sh to pex 1.2.16. (#5460)
  `PR #5460 <https://github.com/pantsbuild/pants/pull/5460>`_

* fix/tests: subsystems can't declare dependencies on non-globally-scoped subsystems (#5456)
  `PR #5456 <https://github.com/pantsbuild/pants/pull/5456>`_

* Fix missing interpreter constraints bug when a Python target does not have sources (#5501)
  `PR #5501 <https://github.com/pantsbuild/pants/pull/5501>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Fix reference html/js: expand/collapse toggle in Firefox (#5507)
  `PR #5507 <https://github.com/pantsbuild/pants/pull/5507>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Delete unused old python pipeline classes. (#5509)
  `PR #5509 <https://github.com/pantsbuild/pants/pull/5509>`_

* Make the export task use new python pipeline constructs. (#5486)
  `PR #5486 <https://github.com/pantsbuild/pants/pull/5486>`_

* Remote command execution returns a Future (#5497)
  `PR #5497 <https://github.com/pantsbuild/pants/pull/5497>`_

* Snapshot is backed by LMDB not tar files (#5496)
  `PR #5496 <https://github.com/pantsbuild/pants/pull/5496>`_

* Local process execution happens in a directory (#5495)
  `PR #5495 <https://github.com/pantsbuild/pants/pull/5495>`_

* Snapshot can get FileContent (#5494)
  `PR #5494 <https://github.com/pantsbuild/pants/pull/5494>`_

* Move materialize_{file,directory} from fs_util to Store (#5493)
  `PR #5493 <https://github.com/pantsbuild/pants/pull/5493>`_

* Remove support dir overrides (#5489)
  `PR #5489 <https://github.com/pantsbuild/pants/pull/5489>`_

* Upgrade to rust 1.24 (#5477)
  `PR #5477 <https://github.com/pantsbuild/pants/pull/5477>`_

* Simplify python local dist handling code. (#5480)
  `PR #5480 <https://github.com/pantsbuild/pants/pull/5480>`_

* Remove some outdated test harness code that exists in the base class (#5472)
  `PR #5472 <https://github.com/pantsbuild/pants/pull/5472>`_

* Tweaks to the BinaryTool subsystem and use it to create an LLVM subsystem (#5471)
  `PR #5471 <https://github.com/pantsbuild/pants/pull/5471>`_

* Refactor python pipeline utilities (#5474)
  `PR #5474 <https://github.com/pantsbuild/pants/pull/5474>`_

* Fetch the buildozer binary using a subsystem. (#5462)
  `PR #5462 <https://github.com/pantsbuild/pants/pull/5462>`_

* Narrow the warnings we ignore when compiling our cffi (#5458)
  `PR #5458 <https://github.com/pantsbuild/pants/pull/5458>`_

1.5.0.dev3 (02/10/2018)
-----------------------

New Features
~~~~~~~~~~~~
* Python distribution task for user-defined setup.py + integration with ./pants {run/binary/test} (#5141)
  `PR #5141 <https://github.com/pantsbuild/pants/pull/5141>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Bundle all kythe entries, regardless of origin. (#5450)
  `PR #5450 <https://github.com/pantsbuild/pants/pull/5450>`_


1.5.0.dev2 (02/05/2018)
-----------------------

New Features
~~~~~~~~~~~~
* Allow intransitive unpacking of jars. (#5398)
  `PR #5398 <https://github.com/pantsbuild/pants/pull/5398>`_

API Changes
~~~~~~~~~~~
* [strict-deps][build-graph] add new predicate to build graph traversal; Update Target.strict_deps to use it (#5150)
  `PR #5150 <https://github.com/pantsbuild/pants/pull/5150>`_

* Deprecate IDE project generation tasks. (#5432)
  `PR #5432 <https://github.com/pantsbuild/pants/pull/5432>`_

* Enable workdir-max-build-entries by default. (#5423)
  `PR #5423 <https://github.com/pantsbuild/pants/pull/5423>`_

* Fix tasks2 deprecations to each have their own module. (#5421)
  `PR #5421 <https://github.com/pantsbuild/pants/pull/5421>`_

* Console tasks can output nothing without erroring (#5412)
  `PR #5412 <https://github.com/pantsbuild/pants/pull/5412>`_

* Remove a remaining old-python-pipeline task from contrib/python. (#5411)
  `PR #5411 <https://github.com/pantsbuild/pants/pull/5411>`_

* Make the thrift linter use the standard linter mixin. (#5394)
  `PR #5394 <https://github.com/pantsbuild/pants/pull/5394>`_

Bugfixes
~~~~~~~~
* Fix `PytestRun` to handle multiple source roots. (#5400)
  `PR #5400 <https://github.com/pantsbuild/pants/pull/5400>`_

* Fix a bug in task logging in tests. (#5404)
  `PR #5404 <https://github.com/pantsbuild/pants/pull/5404>`_

* [pantsd] Repair console interactivity in pantsd runs. (#5352)
  `PR #5352 <https://github.com/pantsbuild/pants/pull/5352>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~
* Document release reset of master. (#5397)
  `PR #5397 <https://github.com/pantsbuild/pants/pull/5397>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Make the Kythe Java indexer emit JVM nodes. (#5435)
  `PR #5435 <https://github.com/pantsbuild/pants/pull/5435>`_

* Release script allows wheel listing (#5431)
  `PR #5431 <https://github.com/pantsbuild/pants/pull/5431>`_

* Get version from version file not by running pants (#5428)
  `PR #5428 <https://github.com/pantsbuild/pants/pull/5428>`_

* Improve python/rust boundary error handling (#5414)
  `PR #5414 <https://github.com/pantsbuild/pants/pull/5414>`_

* Factor up shared test partitioning code. (#5416)
  `PR #5416 <https://github.com/pantsbuild/pants/pull/5416>`_

* Set the log level when capturing logs in tests. (#5418)
  `PR #5418 <https://github.com/pantsbuild/pants/pull/5418>`_

* Simplify `JUnitRun` internals. (#5410)
  `PR #5410 <https://github.com/pantsbuild/pants/pull/5410>`_

* [v2-engine errors] Sort suggestions for typo'd targets, unique them when trace is disabled (#5413)
  `PR #5413 <https://github.com/pantsbuild/pants/pull/5413>`_

* No-op ivy resolve is ~100ms cheaper (#5389)
  `PR #5389 <https://github.com/pantsbuild/pants/pull/5389>`_

* Process executor does not require env flag to be set (#5409)
  `PR #5409 <https://github.com/pantsbuild/pants/pull/5409>`_

* [pantsd] Don't invalidate on surface name changes to config/rc files. (#5408)
  `PR #5408 <https://github.com/pantsbuild/pants/pull/5408>`_

* [pantsd] Break out DPR._nailgunned_stdio() into multiple methods. (#5405)
  `PR #5405 <https://github.com/pantsbuild/pants/pull/5405>`_

* Sort the indexable targets consistently. (#5403)
  `PR #5403 <https://github.com/pantsbuild/pants/pull/5403>`_


1.5.0.dev1 (01/26/2018)
-----------------------

New Features
~~~~~~~~~~~~

* [pantsd] Add RunTracker stats. (#5374)
  `PR #5374 <https://github.com/pantsbuild/pants/pull/5374>`_

API Changes
~~~~~~~~~~~

* [pantsd] Bump to watchman 4.9.0-pants1. (#5386)
  `PR #5386 <https://github.com/pantsbuild/pants/pull/5386>`_

Bugfixes
~~~~~~~~

* Single resolve with coursier (#5362)
  `Issue #743 <https://github.com/coursier/coursier/issues/743>`_
  `PR #5362 <https://github.com/pantsbuild/pants/pull/5362>`_
  `PR #735 <https://github.com/coursier/coursier/pull/735>`_

* Repoint the 'current' symlink even for valid VTs. (#5375)
  `PR #5375 <https://github.com/pantsbuild/pants/pull/5375>`_

* Do not download node package multiple times (#5372)
  `PR #5372 <https://github.com/pantsbuild/pants/pull/5372>`_

* Fix calls to trace (#5366)
  `Issue #5365 <https://github.com/pantsbuild/pants/issues/5365>`_
  `PR #5366 <https://github.com/pantsbuild/pants/pull/5366>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Update the rust readme. (#5393)
  `PR #5393 <https://github.com/pantsbuild/pants/pull/5393>`_

* Update our JVM-related config and documentation. (#5370)
  `PR #5370 <https://github.com/pantsbuild/pants/pull/5370>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Apply goal-level skip/transitive options to lint/fmt tasks. (#5383)
  `PR #5383 <https://github.com/pantsbuild/pants/pull/5383>`_

* [pantsd] StoreGCService improvements. (#5391)
  `PR #5391 <https://github.com/pantsbuild/pants/pull/5391>`_

* Remove unused field (#5390)
  `PR #5390 <https://github.com/pantsbuild/pants/pull/5390>`_

* Extract CommandRunner struct (#5377)
  `PR #5377 <https://github.com/pantsbuild/pants/pull/5377>`_

* [pantsd] Repair pantsd integration tests for execution via pantsd. (#5387)
  `PR #5387 <https://github.com/pantsbuild/pants/pull/5387>`_

* fs_util writes to remote CAS if it's present (#5378)
  `PR #5378 <https://github.com/pantsbuild/pants/pull/5378>`_

* Add back isort tests (#5380)
  `PR #5380 <https://github.com/pantsbuild/pants/pull/5380>`_

* Fix fail-fast tests. (#5371)
  `PR #5371 <https://github.com/pantsbuild/pants/pull/5371>`_

* Store can copy Digests from local to remote (#5333)
  `PR #5333 <https://github.com/pantsbuild/pants/pull/5333>`_

1.5.0.dev0 (01/22/2018)
-----------------------

New Features
~~~~~~~~~~~~

* add avro/java contrib plugin to the release process (#5346)
  `PR #5346 <https://github.com/pantsbuild/pants/pull/5346>`_

* Add the mypy contrib module to pants release process (#5335)
  `PR #5335 <https://github.com/pantsbuild/pants/pull/5335>`_

* Publish the codeanalysis contrib plugin. (#5322)
  `PR #5322 <https://github.com/pantsbuild/pants/pull/5322>`_

API Changes
~~~~~~~~~~~

* Remove 1.5.0.dev0 deprecations (#5363)
  `PR #5363 <https://github.com/pantsbuild/pants/pull/5363>`_

* Deprecate the Android contrib backend. (#5343)
  `PR #5343 <https://github.com/pantsbuild/pants/pull/5343>`_

* [contrib/scrooge] Add exports support to scrooge (#5357)
  `PR #5357 <https://github.com/pantsbuild/pants/pull/5357>`_

* Remove superfluous --dist flag from kythe indexer task. (#5344)
  `PR #5344 <https://github.com/pantsbuild/pants/pull/5344>`_

* Delete deprecated modules removable in 1.5.0dev0. (#5337)
  `PR #5337 <https://github.com/pantsbuild/pants/pull/5337>`_

* An --eager option for BootstrapJvmTools. (#5336)
  `PR #5336 <https://github.com/pantsbuild/pants/pull/5336>`_

* Deprecate the v1 engine option. (#5338)
  `PR #5338 <https://github.com/pantsbuild/pants/pull/5338>`_

* Remove the target labels mechanism  (#5320)
  `PR #5320 <https://github.com/pantsbuild/pants/pull/5320>`_

* Remove wiki-related targets from contrib and back to docgen (#5319)
  `PR #5319 <https://github.com/pantsbuild/pants/pull/5319>`_

* Get rid of the is_thrift and is_test target properties. (#5318)
  `PR #5318 <https://github.com/pantsbuild/pants/pull/5318>`_

* First of a series of changes to get rid of target labels. (#5312)
  `PR #5312 <https://github.com/pantsbuild/pants/pull/5312>`_

Bugfixes
~~~~~~~~

* Fix a silly bug when computing indexable targets. (#5359)
  `PR #5359 <https://github.com/pantsbuild/pants/pull/5359>`_

* [pantsd] Repair daemon wedge on log rotation. (#5358)
  `PR #5358 <https://github.com/pantsbuild/pants/pull/5358>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* A lightweight mechanism for registering options at the goal level. (#5325)
  `PR #5325 <https://github.com/pantsbuild/pants/pull/5325>`_

* Ensure test report results are always exposed. (#5368)
  `PR #5368 <https://github.com/pantsbuild/pants/pull/5368>`_

* Add error_details proto (#5367)
  `PR #5367 <https://github.com/pantsbuild/pants/pull/5367>`_

* Store can expand directories into transitive fingerprints (#5331)
  `PR #5331 <https://github.com/pantsbuild/pants/pull/5331>`_

* Store can tell what the EntryType of a Fingerprint is (#5332)
  `PR #5332 <https://github.com/pantsbuild/pants/pull/5332>`_

* Protobuf implementation uses Bytes instead of Vec (#5329)
  `PR #5329 <https://github.com/pantsbuild/pants/pull/5329>`_

* Store and remote::ByteStore use Digests not Fingerprints (#5347)
  `PR #5347 <https://github.com/pantsbuild/pants/pull/5347>`_

* Garbage collect Store entries (#5345)
  `PR #5345 <https://github.com/pantsbuild/pants/pull/5345>`_

* Port IsolatedProcess implementation from Python to Rust - Split 1  (#5239)
  `PR #5239 <https://github.com/pantsbuild/pants/pull/5239>`_

* python2: do not resolve requirements if no python targets in targets closure (#5361)
  `PR #5361 <https://github.com/pantsbuild/pants/pull/5361>`_

* Store takes a reference, not an owned type (#5334)
  `PR #5334 <https://github.com/pantsbuild/pants/pull/5334>`_

* Bump to pex==1.2.16. (#5355)
  `PR #5355 <https://github.com/pantsbuild/pants/pull/5355>`_

* Reenable lighter contrib sanity checks (#5340)
  `PR #5340 <https://github.com/pantsbuild/pants/pull/5340>`_

* Use helper functions in tests (#5328)
  `PR #5328 <https://github.com/pantsbuild/pants/pull/5328>`_

* Add support for alternate packages in the pex that is built. (#5283)
  `PR #5283 <https://github.com/pantsbuild/pants/pull/5283>`_

* List failed crates when running all rust tests (#5327)
  `PR #5327 <https://github.com/pantsbuild/pants/pull/5327>`_

* More sharding to alleviate flaky timeout from integration tests (#5324)
  `PR #5324 <https://github.com/pantsbuild/pants/pull/5324>`_

* Update lockfile for fs_util (#5326)
  `PR #5326 <https://github.com/pantsbuild/pants/pull/5326>`_

* Implement From in both directions for Digests (#5330)
  `PR #5330 <https://github.com/pantsbuild/pants/pull/5330>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* add mypy to list of released plugins in docs (#5341)
  `PR #5341 <https://github.com/pantsbuild/pants/pull/5341>`_

* Incorporate the more-frequent-stable release proposal (#5311)
  `PR #5311 <https://github.com/pantsbuild/pants/pull/5311>`_

1.4.0rc0 (01/12/2018)
---------------------

The first release candidate for the ``1.4.x`` stable branch.

It's been many months since the ``1.3.x`` branch was cut: part of this was due to a decision
to tie "enabling pantsd by default" to the ``1.4.0`` release. It's taken longer to stabilize
pantsd than we initially anticipated, and while we're very nearly comfortable with enabling it
by default, we believe that we should be prioritizing frequent stable minor releases over
releases being tied to particular features. So let's do this thing!

New Features
~~~~~~~~~~~~

* Introduce a single-target mode to `JUnitRun`. (#5302)
  `PR #5302 <https://github.com/pantsbuild/pants/pull/5302>`_

* Remote ByteStore can write to a CAS (#5293)
  `PR #5293 <https://github.com/pantsbuild/pants/pull/5293>`_

* Improvements to the kythe extractor and indexer tasks. (#5297)
  `PR #5297 <https://github.com/pantsbuild/pants/pull/5297>`_

API Changes
~~~~~~~~~~~

* Rename the `kythe` package to `codeanalysis` (#5299)
  `PR #5299 <https://github.com/pantsbuild/pants/pull/5299>`_

Bugfixes
~~~~~~~~

* Fix junit code coverage to be off by default. (#5306)
  `PR #5306 <https://github.com/pantsbuild/pants/pull/5306>`_

* Actually use the merge and report tool classpaths. (#5308)
  `PR #5308 <https://github.com/pantsbuild/pants/pull/5308>`_

* url quote classpath in MANIFEST.MF (#5301)
  `PR #5301 <https://github.com/pantsbuild/pants/pull/5301>`_

* Fix coursier resolve missing excludes for classpath product (#5298)
  `PR #5298 <https://github.com/pantsbuild/pants/pull/5298>`_

* Fix junit caching under coverage. (#5289)
  `PR #5289 <https://github.com/pantsbuild/pants/pull/5289>`_

* mypy plugin: add support for a mypy config file (#5296)
  `PR #5296 <https://github.com/pantsbuild/pants/pull/5296>`_

* Make the ivy resolution confs participate in the fingerprint. (#5270)
  `PR #5270 <https://github.com/pantsbuild/pants/pull/5270>`_

* Check in fs_util lockfile (#5275)
  `PR #5275 <https://github.com/pantsbuild/pants/pull/5275>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [pantsd] Add debug logging utils. (#5313)
  `PR #5313 <https://github.com/pantsbuild/pants/pull/5313>`_

* Move grpc mocks to their own crate (#5305)
  `PR #5305 <https://github.com/pantsbuild/pants/pull/5305>`_

* Move hashing utilities into their own crate (#5304)
  `PR #5304 <https://github.com/pantsbuild/pants/pull/5304>`_

* Merge coverage per-batch. (#5286)
  `PR #5286 <https://github.com/pantsbuild/pants/pull/5286>`_

* Update cargo lockfiles (#5291)
  `PR #5291 <https://github.com/pantsbuild/pants/pull/5291>`_

* Install packages required to build a pants release (#5292)
  `PR #5292 <https://github.com/pantsbuild/pants/pull/5292>`_

* travis_ci Dockerfile actually works not on travis (#5278)
  `PR #5278 <https://github.com/pantsbuild/pants/pull/5278>`_

* Update grpcio to 0.2.0 (#5269)
  `PR #5269 <https://github.com/pantsbuild/pants/pull/5269>`_

1.4.0.dev27 (01/05/2018)
------------------------

New Features
~~~~~~~~~~~~

* Support for finding all the targets derived from a given target. (#5271)
  `PR #5271 <https://github.com/pantsbuild/pants/pull/5271>`_

* Support merging of junit xml in reports. (#5257)
  `PR #5257 <https://github.com/pantsbuild/pants/pull/5257>`_

Bugfixes
~~~~~~~~

* [pantsd] Scrub PANTS_ENTRYPOINT env var upon use. (#5262)
  `PR #5262 <https://github.com/pantsbuild/pants/pull/5262>`_

* Fix junit report data loss under batching. (#5259)
  `PR #5259 <https://github.com/pantsbuild/pants/pull/5259>`_

* add safe extract for archivers (#5248)
  `PR #5248 <https://github.com/pantsbuild/pants/pull/5248>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Bump rust version. (#5274)
  `PR #5274 <https://github.com/pantsbuild/pants/pull/5274>`_

* Deprecate legacy junit "public" workdir reports. (#5267)
  `PR #5267 <https://github.com/pantsbuild/pants/pull/5267>`_

* Upgrade to jacoco 0.8.0. (#5268)
  `PR #5268 <https://github.com/pantsbuild/pants/pull/5268>`_

* [pantsd] Kill dead method. (#5263)
  `PR #5263 <https://github.com/pantsbuild/pants/pull/5263>`_

* Give travis just the AWS permissions it needs. (#5261)
  `PR #5261 <https://github.com/pantsbuild/pants/pull/5261>`_

* Relocate stable_json_sha1 to hash_utils. (#5258)
  `PR #5258 <https://github.com/pantsbuild/pants/pull/5258>`_

1.4.0.dev26 (12/30/2017)
------------------------

New Features
~~~~~~~~~~~~

* Add [resolve.coursier] as an experimental task (#5133)
  `PR #5133 <https://github.com/pantsbuild/pants/pull/5133>`_

* mypy contrib plugin (#5172)
  `PR #5172 <https://github.com/pantsbuild/pants/pull/5172>`_

Bugfixes
~~~~~~~~

* Swap stdio file descriptors at the os level (#5247)
  `PR #5247 <https://github.com/pantsbuild/pants/pull/5247>`_

* Don't render cancelled nodes in trace (#5252)
  `PR #5252 <https://github.com/pantsbuild/pants/pull/5252>`_

* Correction on ensure_resolver (#5250)
  `PR #5250 <https://github.com/pantsbuild/pants/pull/5250>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Support fetching sources and javadoc in export using coursier (#5254)
  `PR #5254 <https://github.com/pantsbuild/pants/pull/5254>`_

1.4.0.dev25 (12/22/2017)
------------------------

New Features
~~~~~~~~~~~~
* Integrate PEX interpreter selection based on target-level interpreter compatibility constraints (#5160)
  `PR #5160 <https://github.com/pantsbuild/pants/pull/5160>`_

* Import statements can be banned in BUILD files (#5180)
  `PR #5180 <https://github.com/pantsbuild/pants/pull/5180>`_

Bugfixes
~~~~~~~~

* revert log statement edits from #5170 that break console logging (#5233)
  `PR #5233 <https://github.com/pantsbuild/pants/pull/5233>`_

* [pantsd] Repair daemon lifecycle options fingerprinting. (#5232)
  `PR #5232 <https://github.com/pantsbuild/pants/pull/5232>`_

* use task fingerprint for build invalidation to avoid `results_dir` clashes (#5170)
  `PR #5170 <https://github.com/pantsbuild/pants/pull/5170>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* [pantsd] Bump watchman version. (#5238)
  `PR #5238 <https://github.com/pantsbuild/pants/pull/5238>`_

* [pantsd] Improve stream latency by disabling Nagle's algorithm. (#5237)
  `PR #5237 <https://github.com/pantsbuild/pants/pull/5237>`_

* Log and increase pantsd startup timeout (#5231)
  `PR #5231 <https://github.com/pantsbuild/pants/pull/5231>`_

* [pantsd] Improve artifact cache progress output when daemon is enabled. (#5236)
  `PR #5236 <https://github.com/pantsbuild/pants/pull/5236>`_

* download_binary.sh takes hostname as a parameter (#5234)
  `PR #5234 <https://github.com/pantsbuild/pants/pull/5234>`_

* Kill noisy NodeModule.__init__() debug logging. (#5215)
  `PR #5215 <https://github.com/pantsbuild/pants/pull/5215>`_

* TargetRoots always requires options (#5217)
  `PR #5217 <https://github.com/pantsbuild/pants/pull/5217>`_


1.4.0.dev24 (12/16/2017)
------------------------

API Changes
~~~~~~~~~~~
* Add --ignore-optional commandline flag for yarn install process. (#5209)
  `PR #5209 <https://github.com/pantsbuild/pants/pull/5209>`_

New Features
~~~~~~~~~~~~
* contrib plugin for Avro/Java code generation (#5144)
  `PR #5144 <https://github.com/pantsbuild/pants/pull/5144>`_

* Release fs_util as part of the regular release (#5196)
  `PR #5196 <https://github.com/pantsbuild/pants/pull/5196>`_

Bugfixes
~~~~~~~~
* Cross-compiling Go binaries works (#5197)
  `PR #5197 <https://github.com/pantsbuild/pants/pull/5197>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Log if artifact downloads are slow (#5208)
  `PR #5208 <https://github.com/pantsbuild/pants/pull/5208>`_

* [pantsd] Improve service locking. (#5201)
  `PR #5201 <https://github.com/pantsbuild/pants/pull/5201>`_

* Fix RunTracker re-initialization with pantsd (#5211)
  `PR #5211 <https://github.com/pantsbuild/pants/pull/5211>`_

* [pantsd] Catch ESRCH on os.kill of pantsd-runner. (#5213)
  `PR #5213 <https://github.com/pantsbuild/pants/pull/5213>`_

* Update junit-runner to 1.0.23 (#5206)
  `PR #5206 <https://github.com/pantsbuild/pants/pull/5206>`_

* Reset swappable streams in JUnit runner before closing the TeeOutputStreams to the log files and close XML Files after use (#5204)
  `PR #5204 <https://github.com/pantsbuild/pants/pull/5204>`_

* Use centos6 in travis, and remove the wheezy image. (#5202)
  `PR #5202 <https://github.com/pantsbuild/pants/pull/5202>`_

* Add a centos6 Dockerfile (#5167)
  `PR #5167 <https://github.com/pantsbuild/pants/pull/5167>`_

* Add integration test to cover the fix for #5169. (#5192)
  `PR #5192 <https://github.com/pantsbuild/pants/pull/5192>`_

* [pantsd] Repair stdio truncation. (#5156)
  `PR #5156 <https://github.com/pantsbuild/pants/pull/5156>`_


1.4.0.dev23 (12/08/2017)
------------------------

API Changes
~~~~~~~~~~~

* Relativize the classpaths that are recorded during a JVM compile (#5139)
  `PR #5139 <https://github.com/pantsbuild/pants/pull/5139>`_

New Features
~~~~~~~~~~~~

* fs_util backfills from remote CAS if --server-address is set (#5179)
  `PR #5179 <https://github.com/pantsbuild/pants/pull/5179>`_

* Store backfills from a remote CAS (#5166)
  `PR #5166 <https://github.com/pantsbuild/pants/pull/5166>`_

* ByteStore impl for reading from the gRPC ContentAddressableStorage service (#5155)
  `PR #5155 <https://github.com/pantsbuild/pants/pull/5155>`_

* Add the ability to build a pex to the release script (#5159)
  `PR #5159 <https://github.com/pantsbuild/pants/pull/5159>`_

Bugfixes
~~~~~~~~

* Installing a duplicate task into a goal should not throw error if replace=True (#5188)
  `PR #5188 <https://github.com/pantsbuild/pants/pull/5188>`_

* Close suiteCaptures after all tests are finished instead of after each test (#5173)
  `PR #5173 <https://github.com/pantsbuild/pants/pull/5173>`_

* Fix thrift handling in the new python pipeline. (#5168)
  `PR #5168 <https://github.com/pantsbuild/pants/pull/5168>`_

* [pantsd] Improve SIGQUIT handling in the thin client. (#5177)
  `PR #5177 <https://github.com/pantsbuild/pants/pull/5177>`_

* Fix showing test output that happens after the tests are finished (#5165)
  `PR #5165 <https://github.com/pantsbuild/pants/pull/5165>`_

* Post suffixed-wheel release fixups (#5152)
  `PR #5152 <https://github.com/pantsbuild/pants/pull/5152>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove scheduler lock (#5178)
  `PR #5178 <https://github.com/pantsbuild/pants/pull/5178>`_

* Kill obsolete `ThritNamespacePackagesTest`. (#5183)
  `PR #5183 <https://github.com/pantsbuild/pants/pull/5183>`_

* Prefactor Store wrapper (#5154)
  `PR #5154 <https://github.com/pantsbuild/pants/pull/5154>`_

1.4.0.dev22 (12/01/2017)
------------------------

API Changes
~~~~~~~~~~~

* Refer to Buildozer 0.6.0.dce8b3c287652cbcaf43c8dd076b3f48c92ab44c (#5107)
  `PR #5107 <https://github.com/pantsbuild/pants/pull/5107>`_
  `PR #154 <https://github.com/bazelbuild/buildtools/pull/154>`_

New Features
~~~~~~~~~~~~

* go fetching handles multiple meta tags (#5119)
  `PR #5119 <https://github.com/pantsbuild/pants/pull/5119>`_

* Snapshots can be captured as store-backed Directories as well as tar files. (#5105)
  `PR #5105 <https://github.com/pantsbuild/pants/pull/5105>`_

Bugfixes
~~~~~~~~

* Re-generate protos if the proto compiler changes (#5138)
  `PR #5138 <https://github.com/pantsbuild/pants/pull/5138>`_

* Update gRPC to fix OSX compile issues (#5135)
  `Issue #4975 <https://github.com/pantsbuild/pants/issues/4975>`_
  `PR #5135 <https://github.com/pantsbuild/pants/pull/5135>`_

* Use a particular git SHA to stabilize binary fetching. (#5137)
  `PR #5137 <https://github.com/pantsbuild/pants/pull/5137>`_

* Remove requirement for root build file in `changed` (#5134)
  `PR #5134 <https://github.com/pantsbuild/pants/pull/5134>`_

* Kill background cargo fetch on ^C (#5128)
  `Issue #5125 <https://github.com/pantsbuild/pants/issues/5125>`_
  `PR #5128 <https://github.com/pantsbuild/pants/pull/5128>`_

* Expose `jax_ws_library` target in `jax_ws` plugin. (#5122)
  `PR #5122 <https://github.com/pantsbuild/pants/pull/5122>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Build suffixed pants wheels for non-releases (#5118)
  `PR #5118 <https://github.com/pantsbuild/pants/pull/5118>`_

* Change meta-rename options to non-advanced (#5124)
  `PR #5124 <https://github.com/pantsbuild/pants/pull/5124>`_

* Remove GetNode trait (#5123)
  `PR #5123 <https://github.com/pantsbuild/pants/pull/5123>`_

* Async Store (#5117)
  `PR #5117 <https://github.com/pantsbuild/pants/pull/5117>`_

* Fix references to missing content (copied from internal doc). (#5015)
  `PR #5015 <https://github.com/pantsbuild/pants/pull/5015>`_

1.4.0.dev21 (11/17/2017)
------------------------

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Extract resettable pool logic for reuse (#5110)
  `PR #5110 <https://github.com/pantsbuild/pants/pull/5110>`_

* Update rust to 1.21.0 (#5113)
  `PR #5113 <https://github.com/pantsbuild/pants/pull/5113>`_

* Make SelectTransitive a Node in the graph again.  (#5109)
  `PR #5109 <https://github.com/pantsbuild/pants/pull/5109>`_

* is_ignored takes a Stat, not a Path and bool (#5112)
  `PR #5112 <https://github.com/pantsbuild/pants/pull/5112>`_

* Allow file content digests to be computed and memoized in the graph (#5104)
  `PR #5104 <https://github.com/pantsbuild/pants/pull/5104>`_

* Remove inlining in favor of executing directly (#5095)
  `PR #5095 <https://github.com/pantsbuild/pants/pull/5095>`_

* Introduce a Digest type (#5103)
  `PR #5103 <https://github.com/pantsbuild/pants/pull/5103>`_

* Move snapshot to its own file (#5102)
  `PR #5102 <https://github.com/pantsbuild/pants/pull/5102>`_

* Use (git)ignore to implement excludes (#5097)
  `PR #5097 <https://github.com/pantsbuild/pants/pull/5097>`_

* Include mode in engine cache key (#5096)
  `PR #5096 <https://github.com/pantsbuild/pants/pull/5096>`_

* Update hex to 0.3.1 (#5094)
  `PR #5094 <https://github.com/pantsbuild/pants/pull/5094>`_

* Rename local_store_path arg to local-store-path (#5092)
  `PR #5092 <https://github.com/pantsbuild/pants/pull/5092>`_

* `fs_util directory save` takes root (#5074)
  `PR #5074 <https://github.com/pantsbuild/pants/pull/5074>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Update confluence deprecation warning (#5098)
  `PR #5098 <https://github.com/pantsbuild/pants/pull/5098>`_

* Add scalac strict_dep error regexes and update logic to compare partial classnames to target closure's classes (#5093)
  `PR #5093 <https://github.com/pantsbuild/pants/pull/5093>`_


1.4.0.dev20 (11/11/2017)
------------------------

New Features
~~~~~~~~~~~~

* Allow custom definition of Python PEX shebang (#3630) (#4514)
  `PR #3630 <https://github.com/pantsbuild/pants/pull/3630>`_

* Support running python tests in the pex chroot. (#5033)
  `PR #5033 <https://github.com/pantsbuild/pants/pull/5033>`_

API Changes
~~~~~~~~~~~

* Bump to jarjar 1.6.5 to pull in https://github.com/pantsbuild/jarjar/pull/30 (#5087)
  `PR #5087 <https://github.com/pantsbuild/pants/pull/5087>`_
  `PR #30 <https://github.com/pantsbuild/jarjar/pull/30>`_

* Update cmake to 3.9.5 (#5072)
  `Issue #4975#issuecomment-342562504 <https://github.com/pantsbuild/pants/issues/4975#issuecomment-342562504>`_
  `PR #5072 <https://github.com/pantsbuild/pants/pull/5072>`_

Bugfixes
~~~~~~~~

* Fix `PythonInterpreterCache`. (#5089)
  `PR #5089 <https://github.com/pantsbuild/pants/pull/5089>`_

* Call wsimport script instead of using tools.jar so jax-ws will work on java 9 (#5078)
  `PR #5078 <https://github.com/pantsbuild/pants/pull/5078>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Prepare the second release candidate. (#5088)
  `PR #5088 <https://github.com/pantsbuild/pants/pull/5088>`_

* Inline mis-documented `select_interpreter` method. (#5085)
  `PR #5085 <https://github.com/pantsbuild/pants/pull/5085>`_

* fs_util cat <fingerprint> (#5066)
  `PR #5066 <https://github.com/pantsbuild/pants/pull/5066>`_

* Add support for proxying stdin with pantsd (#5040)
  `PR #5040 <https://github.com/pantsbuild/pants/pull/5040>`_

* `fs_util directory cat-proto` supports text format output (#5083)
  `PR #5083 <https://github.com/pantsbuild/pants/pull/5083>`_

* Add a VFS impl for PosixFS. (#5079)
  `PR #5079 <https://github.com/pantsbuild/pants/pull/5079>`_

* `fs_util directory materialize` (#5075)
  `PR #5075 <https://github.com/pantsbuild/pants/pull/5075>`_

* Fix broken test due to changed git cmd line (#5076)
  `PR #5076 <https://github.com/pantsbuild/pants/pull/5076>`_

* Canonicalize path before taking its parent (#5052)
  `PR #5052 <https://github.com/pantsbuild/pants/pull/5052>`_

* Fix test compile (#5069)
  `PR #5069 <https://github.com/pantsbuild/pants/pull/5069>`_
  `PR #5065 <https://github.com/pantsbuild/pants/pull/5065>`_

* fs_util directory cat-proto <fingerprint> (#5065)
  `PR #5065 <https://github.com/pantsbuild/pants/pull/5065>`_

* fs_util exits 2 for ENOENT (#5064)
  `PR #5064 <https://github.com/pantsbuild/pants/pull/5064>`_

* Fixup sdist release. (#5067)
  `PR #5067 <https://github.com/pantsbuild/pants/pull/5067>`_

* Fixup `./build-support/bin/release.sh -t`. (#5062)
  `PR #5062 <https://github.com/pantsbuild/pants/pull/5062>`_


1.4.0.dev19 (11/04/2017)
------------------------

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Pass the `color` option through to the report factory. (#5055)
  `PR #5055 <https://github.com/pantsbuild/pants/pull/5055>`_

* Output size as well as fingerprint (#5053)
  `PR #5053 <https://github.com/pantsbuild/pants/pull/5053>`_

* [pantsd] Daemon lifecycle for options changes. (#5045)
  `PR #5045 <https://github.com/pantsbuild/pants/pull/5045>`_

* Convert fs_util to use futures (#5048)
  `PR #5048 <https://github.com/pantsbuild/pants/pull/5048>`_

* PosixFS can create a Stat from a Path (#5047)
  `PR #5047 <https://github.com/pantsbuild/pants/pull/5047>`_

* PosixFS can read file contents (#5043)
  `PR #5043 <https://github.com/pantsbuild/pants/pull/5043>`_

* Bump to zinc 1.0.3. (#5049)
  `Issue #389, <https://github.com/sbt/zinc/issues/389,>`_
  `PR #5049 <https://github.com/pantsbuild/pants/pull/5049>`_

* fs::Stat::File includes whether a file is executable (#5042)
  `PR #5042 <https://github.com/pantsbuild/pants/pull/5042>`_

* Add configurable message when missing-deps-suggest doesn't have suggestions (#5036)
  `PR #5036 <https://github.com/pantsbuild/pants/pull/5036>`_

* Use split_whitespace for parsing of cflags. (#5038)
  `PR #5038 <https://github.com/pantsbuild/pants/pull/5038>`_

Bugfixes
~~~~~~~~

* [pantsd] Set sys.argv correctly on pantsd-runner fork. (#5051)
  `PR #5051 <https://github.com/pantsbuild/pants/pull/5051>`_

* Fix JarCreate invalidation in the presence of changing resources. (#5030)
  `PR #5030 <https://github.com/pantsbuild/pants/pull/5030>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Minor improvement on dep-usage doc (#5041)
  `PR #5041 <https://github.com/pantsbuild/pants/pull/5041>`_

* Add documentation about strict deps (#5025)
  `PR #5025 <https://github.com/pantsbuild/pants/pull/5025>`_


1.4.0.dev18 (10/29/2017)
------------------------

New Features
~~~~~~~~~~~~
* Dedup dependencies output (#5029)
  `PR #5029 <https://github.com/pantsbuild/pants/pull/5029>`_

* [simple-code-gen] extension point for injecting extra exports (#4976)
  `PR #4976 <https://github.com/pantsbuild/pants/pull/4976>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Use the script verified identity when signing. (#5032)
  `PR #5032 <https://github.com/pantsbuild/pants/pull/5032>`_

* Have twine use the previously established pgp key during release. (#5031)
  `PR #5031 <https://github.com/pantsbuild/pants/pull/5031>`_

1.4.0.dev17 (10/27/2017)
------------------------

New Features
~~~~~~~~~~~~
* Move confluence related things to contrib (#4986)
  `PR #4986 <https://github.com/pantsbuild/pants/pull/4986>`_

* Add custom commands to the `buildozer` goal (#4998)
  `PR #4998 <https://github.com/pantsbuild/pants/pull/4998>`_
  `PR #4921 <https://github.com/pantsbuild/pants/pull/4921>`_
  `PR #4882 <https://github.com/pantsbuild/pants/pull/4882>`_

* Working implementation of jacoco. (#4978)
  `PR #4978 <https://github.com/pantsbuild/pants/pull/4978>`_

API Changes
~~~~~~~~~~~
* [pantsd] Launch the daemon via a subprocess call. (#5021)
  `PR #5021 <https://github.com/pantsbuild/pants/pull/5021>`_

* Fix support for custom javac definitions (#5024)
  `PR #5024 <https://github.com/pantsbuild/pants/pull/5024>`_

* Transform scopes in pants.ini that have been subsumed by global options. (#5007)
  `PR #5007 <https://github.com/pantsbuild/pants/pull/5007>`_

* Coverage isn't enabled by default (#5009)
  `PR #5009 <https://github.com/pantsbuild/pants/pull/5009>`_
  `PR #4881 <https://github.com/pantsbuild/pants/pull/4881>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Content-addressable {file,directory} store and utility (#5012)
  `PR #5012 <https://github.com/pantsbuild/pants/pull/5012>`_

* Use the service deps if the target declares an exception. (#5017)
  `PR #5017 <https://github.com/pantsbuild/pants/pull/5017>`_

* Pass references to Paths (#5022)
  `PR #5022 <https://github.com/pantsbuild/pants/pull/5022>`_

* Replace Blake2 with Sha256 (#5014)
  `PR #5014 <https://github.com/pantsbuild/pants/pull/5014>`_

* Revert pytest successful test caching in CI. (#5016)
  `PR #5016 <https://github.com/pantsbuild/pants/pull/5016>`_

* Fingerprint has from_hex_string, as_bytes, Display, and Debug (#5013)
  `PR #5013 <https://github.com/pantsbuild/pants/pull/5013>`_

* Fix memory leak in `./pants changed` (#5011)
  `PR #5011 <https://github.com/pantsbuild/pants/pull/5011>`_

* Prune travis cache (#5006)
  `PR #5006 <https://github.com/pantsbuild/pants/pull/5006>`_

* Utility to tee subprocess output to sys.std{out,err} and a buffer (#4967)
  `PR #4967 <https://github.com/pantsbuild/pants/pull/4967>`_


1.4.0.dev16 (10/20/2017)
------------------------

New Features
~~~~~~~~~~~~

* Add `buildrefactor` to `contrib` and buildozer goal (#4921)
  `PR #4921 <https://github.com/pantsbuild/pants/pull/4921>`_

* Allow in-repo scalac plugins to have in-repo deps. (#4987)
  `PR #4987 <https://github.com/pantsbuild/pants/pull/4987>`_

* Add plugin for scalafix (#4635)
  `PR #4635 <https://github.com/pantsbuild/pants/pull/4635>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Remove outdated doc (#4989)
  `PR #4989 <https://github.com/pantsbuild/pants/pull/4989>`_

Bugfixes
~~~~~~~~

* Invalidate parent directories (#5000)
  `PR #5000 <https://github.com/pantsbuild/pants/pull/5000>`_

* Enforce quiet option if not hardcoded (#4974)
  `PR #4974 <https://github.com/pantsbuild/pants/pull/4974>`_

* Refer to correct location of variable (#4994)
  `PR #4994 <https://github.com/pantsbuild/pants/pull/4994>`_

* Fix setting of PEX_PATH in ./pants run (v2 backend)  (#4969)
  `PR #4969 <https://github.com/pantsbuild/pants/pull/4969>`_

* Repair pytest timeout tests. (#4972)
  `PR #4972 <https://github.com/pantsbuild/pants/pull/4972>`_

* Add node_module .bin path to node / npm / yarnpkg execution path. (#4932)
  `Issue #18233 <https://github.com/npm/npm/issues/18233>`_
  `PR #4932 <https://github.com/pantsbuild/pants/pull/4932>`_
  `PR #15900 <https://github.com/npm/npm/pull/15900>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Reduce time/package requirements on binary-builder shards (#4992)
  `PR #4992 <https://github.com/pantsbuild/pants/pull/4992>`_

* [pantsd] Launch the daemon via the thin client. (#4931)
  `PR #4931 <https://github.com/pantsbuild/pants/pull/4931>`_

* Extract fs and boxfuture crates (#4985)
  `PR #4985 <https://github.com/pantsbuild/pants/pull/4985>`_

* process_executor binary can do remote execution (#4980)
  `PR #4980 <https://github.com/pantsbuild/pants/pull/4980>`_

* Fix some minor textual and shell nits (#4841)
  `PR #4841 <https://github.com/pantsbuild/pants/pull/4841>`_

* Use more generic portion of `requests` exception message in tests. (#4981)
  `PR #4981 <https://github.com/pantsbuild/pants/pull/4981>`_

* Include target addresses which trigger deprecation warnings (#4979)
  `PR #4979 <https://github.com/pantsbuild/pants/pull/4979>`_

* Remote process execution works more generally (#4937)
  `PR #4937 <https://github.com/pantsbuild/pants/pull/4937>`_

* Extend timeout for cargo fetching git repos (#4971)
  `PR #4971 <https://github.com/pantsbuild/pants/pull/4971>`_

* Ignore Cargo.lock files for libraries (#4968)
  `PR #4968 <https://github.com/pantsbuild/pants/pull/4968>`_

* rm unused strategy concept from simple code gen tests (#4964)
  `PR #4964 <https://github.com/pantsbuild/pants/pull/4964>`_

* Fetch go and cmake as part of bootstrap (#4962)
  `PR #4962 <https://github.com/pantsbuild/pants/pull/4962>`_
  `PR #45 <https://github.com/pantsbuild/binaries/pull/45>`_

* Make sure .cargo/config is respected for all cargo invocations (#4965)
  `PR #4965 <https://github.com/pantsbuild/pants/pull/4965>`_

* Restore to specifying /travis/home as a volume (#4960)
  `PR #4960 <https://github.com/pantsbuild/pants/pull/4960>`_

* Engine can request process execution via gRPC (#4929)
  `PR #4929 <https://github.com/pantsbuild/pants/pull/4929>`_

* Add back sdist generation and deployment. (#4957)
  `PR #4957 <https://github.com/pantsbuild/pants/pull/4957>`_

1.4.0.dev15 (10/7/2017)
-----------------------

New Features
~~~~~~~~~~~~

* Send timing/cache report to stderr (#4946)
  `PR #4946 <https://github.com/pantsbuild/pants/pull/4946>`_

* Allow users to tell pants where to look for python interpreters (#4930)
  `PR #4930 <https://github.com/pantsbuild/pants/pull/4930>`_

Bugfixes
~~~~~~~~

* Fix `BundleIntegrationTest`. (#4953)
  `PR #4953 <https://github.com/pantsbuild/pants/pull/4953>`_

* Pin Rust version to 1.20.0 (#4941)
  `PR #4941 <https://github.com/pantsbuild/pants/pull/4941>`_

* Remove bad string (#4942)
  `PR #4942 <https://github.com/pantsbuild/pants/pull/4942>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Load the native engine lib from a pkg_resource. (#4914)
  `PR #4914 <https://github.com/pantsbuild/pants/pull/4914>`_

* Switch from rust-crypto to sha2 (#4951)
  `PR #4951 <https://github.com/pantsbuild/pants/pull/4951>`_

* Exclude target directories from rustfmt (#4950)
  `PR #4950 <https://github.com/pantsbuild/pants/pull/4950>`_

* Update tar to a released version (#4949)
  `PR #4949 <https://github.com/pantsbuild/pants/pull/4949>`_

* Mention name of binary we can't find (#4947)
  `PR #4947 <https://github.com/pantsbuild/pants/pull/4947>`_

* Reformat rust files (#4948)
  `PR #4948 <https://github.com/pantsbuild/pants/pull/4948>`_

* Bump cffi dep to latest (1.11.1). (#4944)
  `PR #4944 <https://github.com/pantsbuild/pants/pull/4944>`_

* Upgrade gcc to cc 1.0 (#4945)
  `PR #4945 <https://github.com/pantsbuild/pants/pull/4945>`_

* Preserve soft excludes bug while removing duplicates (#4940)
  `PR #4940 <https://github.com/pantsbuild/pants/pull/4940>`_

* Move --open-with under idea-plugin to regular options (#4939)
  `PR #4939 <https://github.com/pantsbuild/pants/pull/4939>`_

* Memoize strict deps and exports (#4934)
  `PR #4934 <https://github.com/pantsbuild/pants/pull/4934>`_

* Use `uname` in place of `arch`. (#4928)
  `PR #4928 <https://github.com/pantsbuild/pants/pull/4928>`_

* Update futures to 0.1.16 and futures-cpupool to 0.1.6 (#4925)
  `PR #4925 <https://github.com/pantsbuild/pants/pull/4925>`_

1.4.0.dev14 (10/2/2017)
-----------------------

New Features
~~~~~~~~~~~~

* Engine can work with Bazel Remote Execution API (#4910)
  `PR #4910 <https://github.com/pantsbuild/pants/pull/4910>`_

* Add lint and fmt goal for javascript style rules checking (#4785)
  `PR #4785 <https://github.com/pantsbuild/pants/pull/4785>`_

API Changes
~~~~~~~~~~~

* managed_jar_dependencies: allow target()'s with jar_library dependencies (#4742)
  `PR #4742 <https://github.com/pantsbuild/pants/pull/4742>`_

Bugfixes
~~~~~~~~

* Error if the wrong subprocess is imported (#4922)
  `PR #4922 <https://github.com/pantsbuild/pants/pull/4922>`_

* Avoid os.fork() prior to stats upload. (#4919)
  `PR #4919 <https://github.com/pantsbuild/pants/pull/4919>`_

* Repair requests range pin to include higher versions. (#4916)
  `PR #4916 <https://github.com/pantsbuild/pants/pull/4916>`_

* Use Jessie not Weezy for docker image on travis (#4912)
  `PR #4912 <https://github.com/pantsbuild/pants/pull/4912>`_

* Fixup build script to rebuild only when needed. (#4908)
  `PR #4908 <https://github.com/pantsbuild/pants/pull/4908>`_

* Fix -Wstrict-prototypes warnings (#4902)
  `PR #4902 <https://github.com/pantsbuild/pants/pull/4902>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Install cmake on travis (#4923)
  `PR #4923 <https://github.com/pantsbuild/pants/pull/4923>`_

* Use newer protoc and older debian (#4918)
  `PR #4918 <https://github.com/pantsbuild/pants/pull/4918>`_
  `PR #40 <https://github.com/pantsbuild/binaries/pull/40>`_

* Refactor code coverage in preparation for adding a new coverage engine (jacoco) (#4881)
  `PR #4881 <https://github.com/pantsbuild/pants/pull/4881>`_

* Improve performance of simple codegen. (#4907)
  `PR #4907 <https://github.com/pantsbuild/pants/pull/4907>`_

* Implement local process execution in rust (#4901)
  `PR #4901 <https://github.com/pantsbuild/pants/pull/4901>`_

* Improve `--cache-ignore` performance. (#4905)
  `PR #4905 <https://github.com/pantsbuild/pants/pull/4905>`_

* Script to run sub-crate tests (#4900)
  `PR #4900 <https://github.com/pantsbuild/pants/pull/4900>`_

* Run rust tests on travis (#4899)
  `PR #4899 <https://github.com/pantsbuild/pants/pull/4899>`_

* Remove obsolete target-specific scripts (#4903)
  `PR #4903 <https://github.com/pantsbuild/pants/pull/4903>`_

* Re-build Bazel gRPC if the build script changes (#4924)
  `PR #4924 <https://github.com/pantsbuild/pants/pull/4924>`_

1.4.0.dev13 (9/25/2017)
-----------------------

New Features
~~~~~~~~~~~~

* Support wheels when loading plugins. (#4887)
  `PR #4887 <https://github.com/pantsbuild/pants/pull/4887>`_

API Changes
~~~~~~~~~~~

* Remove python 2.6 support completely. (#4871)
  `PR #4871 <https://github.com/pantsbuild/pants/pull/4871>`_

* Bump pyopenssl==17.3.0 (#4872)
  `PR #4872 <https://github.com/pantsbuild/pants/pull/4872>`_

* Error on task name reuse for a particular goal (#4863)
  `PR #4863 <https://github.com/pantsbuild/pants/pull/4863>`_

Bugfixes
~~~~~~~~

* Release native engine binaries for OSX 10.13. (#4898)
  `PR #4898 <https://github.com/pantsbuild/pants/pull/4898>`_

* Add default routing for OSX High Sierra binaries. (#4894)
  `PR #4894 <https://github.com/pantsbuild/pants/pull/4894>`_

* Reduce BUILD file parse pollution (#4892)
  `PR #4892 <https://github.com/pantsbuild/pants/pull/4892>`_

* Exit with error on error bootstrapping cffi (#4891)
  `PR #4891 <https://github.com/pantsbuild/pants/pull/4891>`_

* Only generate Android resource deps when needed. (#4888)
  `PR #4888 <https://github.com/pantsbuild/pants/pull/4888>`_

* Re-pin to 2017Q2 TravisCI image. (#4869)
  `PR #4869 <https://github.com/pantsbuild/pants/pull/4869>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Update the committer docs. (#4889)
  `PR #4889 <https://github.com/pantsbuild/pants/pull/4889>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Refactor test partitioning. (#4879)
  `PR #4879 <https://github.com/pantsbuild/pants/pull/4879>`_

* Leverage `subprocess32` subprocess backports. (#4851)
  `PR #4851 <https://github.com/pantsbuild/pants/pull/4851>`_

* Customize native engine build through code (#4876)
  `PR #4876 <https://github.com/pantsbuild/pants/pull/4876>`_

* Move to SymbolTable/Parser instances (#4864)
  `PR #4864 <https://github.com/pantsbuild/pants/pull/4864>`_

1.4.0.dev12 (9/13/2017) [UNRELEASED]
------------------------------------

NB: 1.4.0.dev12 was never released to pypi due to technical difficulties; its changes were rolled
up into 1.4.0.dev13 and released with it.

API Changes
~~~~~~~~~~~
* Use @files for javadoc so it runs with a longer command line and add doc exclude patterns option (#4842)
  `PR #4842 <https://github.com/pantsbuild/pants/pull/4842>`_

* Migrate BinaryUtil options to bootstrap options. (#4846)
  `PR #4846 <https://github.com/pantsbuild/pants/pull/4846>`_

Bugfixes
~~~~~~~~
* Clean up stray pantsd-runner processes (#4835)
  `PR #4835 <https://github.com/pantsbuild/pants/pull/4835>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Re-add requests[security] and pin pyOpenSSL==17.1.0 to avoid deprecation warning. (#4865)
  `PR #4865 <https://github.com/pantsbuild/pants/pull/4865>`_

* Repair `BinaryNotFound` due to `sslv3 alert handshake failure`. (#4853)
  `PR #4853 <https://github.com/pantsbuild/pants/pull/4853>`_

* [pantsd] Improve locking. (#4847)
  `PR #4847 <https://github.com/pantsbuild/pants/pull/4847>`_

* Upgrade pex to latest. (#4843)
  `PR #4843 <https://github.com/pantsbuild/pants/pull/4843>`_

1.4.0.dev11 (9/1/2017)
----------------------

Bugfixes
~~~~~~~~

* Centralize options tracking in the Parser. (#4832)
  `PR #4832 <https://github.com/pantsbuild/pants/pull/4832>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Bump petgraph to 0.4.5 (#4836)
  `PR #4836 <https://github.com/pantsbuild/pants/pull/4836>`_

1.4.0.dev10 (8/25/2017)
-----------------------

New Features
~~~~~~~~~~~~

* Add optional chrooting for junit tests. (#4823)
  `PR #4823 <https://github.com/pantsbuild/pants/pull/4823>`_

Bugfixes
~~~~~~~~

* Always return a bool from SetupPy.has_provides().
  `PR #4826 <https://github.com/pantsbuild/pants/pull/4826>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Point binary URLs off to CNAMES we own. (#4829)
  `PR #4829 <https://github.com/pantsbuild/pants/pull/4829>`_

* Stop dual-publishing the docsite. (#4828)
  `PR #4828 <https://github.com/pantsbuild/pants/pull/4828>`_

1.4.0.dev9 (8/18/2017)
----------------------

Bugfixes
~~~~~~~~

* Ensure setup-py runs with all interpreter extras. (#4822)
  `PR #4822 <https://github.com/pantsbuild/pants/pull/4822>`_

* Fixup erroneous `exc` attribute access. (#4818)
  `PR #4818 <https://github.com/pantsbuild/pants/pull/4818>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Turn on pytest successful test caching in CI. (#4819)
  `PR #4819 <https://github.com/pantsbuild/pants/pull/4819>`_

* Only attempt deploys on appropriate shards. (#4816)
  `PR #4816 <https://github.com/pantsbuild/pants/pull/4816>`_

* Fix s3 deploy to use copies instead of a symlink. (#4814)
  `PR #4814 <https://github.com/pantsbuild/pants/pull/4814>`_

* Fix the S3 upload in the travis deploy. (#4813)
  `PR #4813 <https://github.com/pantsbuild/pants/pull/4813>`_

1.4.0.dev8 (8/11/2017)
----------------------

New Features
~~~~~~~~~~~~

* Add support for junit (successful) test caching. (#4771)
  `PR #4771 <https://github.com/pantsbuild/pants/pull/4771>`_

API Changes
~~~~~~~~~~~

* Kill custom binaries.baseurls. (#4809)
  `PR #4809 <https://github.com/pantsbuild/pants/pull/4809>`_

* Partition and pass JVM options to scalafmt (#4774)
  `PR #4774 <https://github.com/pantsbuild/pants/pull/4774>`_

Bugfixes
~~~~~~~~

* [python-repl] pass env through to repl (#4808)
  `PR #4808 <https://github.com/pantsbuild/pants/pull/4808>`_

* Switch default binary-baseurls to s3 (#4806)
  `PR #4806 <https://github.com/pantsbuild/pants/pull/4806>`_

* Work around bintray outage. (#4801)
  `PR #4801 <https://github.com/pantsbuild/pants/pull/4801>`_

* Fix has_sources. (#4792)
  `PR #4792 <https://github.com/pantsbuild/pants/pull/4792>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Zinc 1.0.0-RC3 memory and output improvements (#4807)
  `PR #4807 <https://github.com/pantsbuild/pants/pull/4807>`_

* Improve performance by not re-fingerprinting codegen'd sources. (#4789)
  `PR #4789 <https://github.com/pantsbuild/pants/pull/4789>`_

* Add per-target zinc compile stats (#4790)
  `PR #4790 <https://github.com/pantsbuild/pants/pull/4790>`_

* Add support for publishing native-engine to s3. (#4804)
  `PR #4804 <https://github.com/pantsbuild/pants/pull/4804>`_

* Introduce a loose `Files` target. (#4798)
  `PR #4798 <https://github.com/pantsbuild/pants/pull/4798>`_

* Upgrade default go to 1.8.3. (#4799)
  `PR #4799 <https://github.com/pantsbuild/pants/pull/4799>`_

* Deprecate unused `go_thrift_library.import_path`. (#4794)
  `PR #4794 <https://github.com/pantsbuild/pants/pull/4794>`_

* Cleanup cpp targets. (#4793)
  `PR #4793 <https://github.com/pantsbuild/pants/pull/4793>`_

* Simplify `_validate_target_representation_args`. (#4791)
  `PR #4791 <https://github.com/pantsbuild/pants/pull/4791>`_

* Init the native engine from bootstrap options. (#4787)
  `PR #4787 <https://github.com/pantsbuild/pants/pull/4787>`_

* [pantsd] Add faulthandler support for stacktrace dumps. (#4784)
  `PR #4784 <https://github.com/pantsbuild/pants/pull/4784>`_

* Cleanup CI deprecation warnings. (#4781)
  `PR #4781 <https://github.com/pantsbuild/pants/pull/4781>`_

* Kill `-XX:-UseSplitVerifier`. (#4777)
  `PR #4777 <https://github.com/pantsbuild/pants/pull/4777>`_


1.4.0.dev7 (7/28/2017)
----------------------

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Update to zinc 1.0.0-RC3 (#4775)
  `Issue #355, <https://github.com/sbt/zinc/issues/355,>`_
  `Issue #355 <https://github.com/sbt/zinc/issues/355>`_
  `PR #4775 <https://github.com/pantsbuild/pants/pull/4775>`_

* Don't require an scm for local publishes. (#4773)
  `PR #4773 <https://github.com/pantsbuild/pants/pull/4773>`_

* Simplify `argutil::ensure_arg`. (#4768)
  `PR #4768 <https://github.com/pantsbuild/pants/pull/4768>`_

* Small cleanups in the `JunitRun` codebase. (#4767)
  `PR #4767 <https://github.com/pantsbuild/pants/pull/4767>`_

* Add support for compiling thrift split across multiple files in go. (#4766)
  `PR #4766 <https://github.com/pantsbuild/pants/pull/4766>`_


1.4.0.dev6 (7/21/2017)
----------------------

API Changes
~~~~~~~~~~~

* Conditionally support multiple thrift files for go_thrift_gen (#4759)
  `PR #4759 <https://github.com/pantsbuild/pants/pull/4759>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Introduce `dirutil.mergetree`. (#4757)
  `PR #4757 <https://github.com/pantsbuild/pants/pull/4757>`_

* Zinc 1.0.0-X20 upgrade: JVM portion (#4728)
  `Issue #355), <https://github.com/sbt/zinc/issues/355),>`_
  `PR #4728 <https://github.com/pantsbuild/pants/pull/4728>`_

* Ensure setuptools version when running setup.py. (#4753)
  `PR #4753 <https://github.com/pantsbuild/pants/pull/4753>`_

* Kill deprecated explicit register.
  `Commit 5583dd1 <https://github.com/pantsbuild/pants/commit/5583dd1>`_


1.4.0.dev5 (7/14/2017)
----------------------

API Changes
~~~~~~~~~~~

* ScroogeGen passes through fatal_warnings argument (#4739)
  `PR #4739 <https://github.com/pantsbuild/pants/pull/4739>`_

* Bump pex version to 1.2.8. (#4735)
  `PR #4735 <https://github.com/pantsbuild/pants/pull/4735>`_

* Deprecate the `--config-override` option. (#4715)
  `PR #4715 <https://github.com/pantsbuild/pants/pull/4715>`_

Bugfixes
~~~~~~~~

* Improve pytest result summaries. (#4747)
  `PR #4747 <https://github.com/pantsbuild/pants/pull/4747>`_

* Include passthru args in task option fingerprints. (#4745)
  `PR #4745 <https://github.com/pantsbuild/pants/pull/4745>`_

* Fingerprint a bunch of go options. (#4743)
  `PR #4743 <https://github.com/pantsbuild/pants/pull/4743>`_

* Fix rpc style in compiler_args check. (#4730)
  `PR #4730 <https://github.com/pantsbuild/pants/pull/4730>`_

* Revert "Alias `--pants-config-files` to `-c`." (#4718)
  `PR #4718 <https://github.com/pantsbuild/pants/pull/4718>`_

* Ensure that invalidation works correctly when state is reverted. (#4709)
  `PR #4709 <https://github.com/pantsbuild/pants/pull/4709>`_

* Fixup `PytestRun` error handling. (#4716)
  `PR #4716 <https://github.com/pantsbuild/pants/pull/4716>`_

* Fix option bootstrapping config application order. (#4714)
  `PR #4714 <https://github.com/pantsbuild/pants/pull/4714>`_

* Ensure that target root order is preserved (#4708)
  `PR #4708 <https://github.com/pantsbuild/pants/pull/4708>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Remove Download Stats (#4724)
  `Issue #716 <https://github.com/badges/shields/issues/716>`_
  `PR #4724 <https://github.com/pantsbuild/pants/pull/4724>`_

* Fix roundtrip example in JVM documentation (#4706)
  `PR #4706 <https://github.com/pantsbuild/pants/pull/4706>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Improve transitive resolve package checking in tests. (#4738)
  `PR #4738 <https://github.com/pantsbuild/pants/pull/4738>`_

* Extract a zinc subsystem to allow for more entrypoints (#4720)
  `PR #4720 <https://github.com/pantsbuild/pants/pull/4720>`_

* Format suggested deps for easy cut & paste into BUILD file (#4711)
  `PR #4711 <https://github.com/pantsbuild/pants/pull/4711>`_

* Re-enable lint checks in CI (#4704)
  `PR #4704 <https://github.com/pantsbuild/pants/pull/4704>`_


1.4.0.dev4 (6/23/2017)
----------------------

API Changes
~~~~~~~~~~~

* Replace the `invalidate` goal with `--cache-ignore`. (#4686)
  `PR #4686 <https://github.com/pantsbuild/pants/pull/4686>`_

Bugfixes
~~~~~~~~

* Fix pythonstyle warnings and some python-eval warnings (#4698)
  `PR #4698 <https://github.com/pantsbuild/pants/pull/4698>`_

* Add debug logging to prepare_resources and junit_run and fix payload asserts (#4694)
  `PR #4694 <https://github.com/pantsbuild/pants/pull/4694>`_

* Improve safe_concurrent_creation contextmanager. (#4690)
  `PR #4690 <https://github.com/pantsbuild/pants/pull/4690>`_

* Fix pytest result summary colors. (#4685)
  `PR #4685 <https://github.com/pantsbuild/pants/pull/4685>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Use ElementTree to parse JUnit XML files because it is much faster than minidom (#4693)
  `PR #4693 <https://github.com/pantsbuild/pants/pull/4693>`_

* Use link.checkstyle target for checkstyle integration (#4699)
  `PR #4699 <https://github.com/pantsbuild/pants/pull/4699>`_

* Stabilize sharding test. (#4687)
  `PR #4687 <https://github.com/pantsbuild/pants/pull/4687>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Fixup explain options json output. (#4696)
  `PR #4696 <https://github.com/pantsbuild/pants/pull/4696>`_


1.4.0.dev3 (6/16/2017)
----------------------

API Changes
~~~~~~~~~~~

* Add compiler_args property to JavaThriftLibrary target.  (#4669)
  `PR #4669 <https://github.com/pantsbuild/pants/pull/4669>`_

Bugfixes
~~~~~~~~

* Add classname to target data reported by pytest (#4675)
  `PR #4675 <https://github.com/pantsbuild/pants/pull/4675>`_

* Support options fingerprinting in `Task` tests. (#4666)
  `PR #4666 <https://github.com/pantsbuild/pants/pull/4666>`_

* Simplify `UnsetBool` fingerprint encoding. (#4667)
  `PR #4667 <https://github.com/pantsbuild/pants/pull/4667>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Remove engine.engine.Engine and add RootRule (#4679)
  `PR #4679 <https://github.com/pantsbuild/pants/pull/4679>`_

* Ensure `Task.workdir` is available when needed. (#4672)
  `PR #4672 <https://github.com/pantsbuild/pants/pull/4672>`_

* Add support for local test caching. (#4660)
  `PR #4660 <https://github.com/pantsbuild/pants/pull/4660>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Link the HTML report image in the docs to the page describing it. (#4671)
  `PR #4671 <https://github.com/pantsbuild/pants/pull/4671>`_

* Document that the release script now requires Bash 4. (#4670)
  `PR #4670 <https://github.com/pantsbuild/pants/pull/4670>`_


1.4.0.dev2 (6/10/2017)
----------------------

API Changes
~~~~~~~~~~~

* Enable implicit_sources by default, and improve its docs. (#4661)
  `PR #4661 <https://github.com/pantsbuild/pants/pull/4661>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Support registering product data from one task. (#4663)
  `PR #4663 <https://github.com/pantsbuild/pants/pull/4663>`_

* Expose pex invocation cmdlines. (#4659)
  `PR #4659 <https://github.com/pantsbuild/pants/pull/4659>`_

* Audit engine struct `repr` values. (#4658)
  `PR #4658 <https://github.com/pantsbuild/pants/pull/4658>`_

* Break `py.test` execution into two stages. (#4656)
  `PR #4656 <https://github.com/pantsbuild/pants/pull/4656>`_

* Skip a test that assumes the current version is a pre-release version. (#4654)
  `PR #4654 <https://github.com/pantsbuild/pants/pull/4654>`_

* Shard contrib tests. (#4650)
  `PR #4650 <https://github.com/pantsbuild/pants/pull/4650>`_

* Fix new `PytestRun` task deselction handling. (#4648)
  `PR #4648 <https://github.com/pantsbuild/pants/pull/4648>`_

* Simplify `TaskBase.invalidated`. (#4642)
  `PR #4642 <https://github.com/pantsbuild/pants/pull/4642>`_

* Eliminate obsolete OSX ci support. (#4636)
  `PR #4636 <https://github.com/pantsbuild/pants/pull/4636>`_

* Temporarily restore recursive behaviour for bundle filesets (#4630)
  `PR #4630 <https://github.com/pantsbuild/pants/pull/4630>`_

* Fix ownership check to be case-insensitive. (#4629)
  `PR #4629 <https://github.com/pantsbuild/pants/pull/4629>`_

Bugfixes
~~~~~~~~

* Support fingerprinting of `UnsetBool` options. (#4665)
  `PR #4665 <https://github.com/pantsbuild/pants/pull/4665>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Kill dead dangling num_sources docs. (#4655)
  `PR #4655 <https://github.com/pantsbuild/pants/pull/4655>`_

* Add notes for 1.3.0, and a section explaining the daemon. (#4651)
  `PR #4651 <https://github.com/pantsbuild/pants/pull/4651>`_

* Rename and expand usage of the needs-cherrypick label (#4652)
  `PR #4652 <https://github.com/pantsbuild/pants/pull/4652>`_

* Generalize fmt msg (#4649)
  `PR #4649 <https://github.com/pantsbuild/pants/pull/4649>`_

* Fixup VersionedTarget class doc. (#4643)
  `PR #4643 <https://github.com/pantsbuild/pants/pull/4643>`_

* Fixes docs around bundle-jvm-archive. (#4637)
  `PR #4637 <https://github.com/pantsbuild/pants/pull/4637>`_


1.4.0.dev1 (5/26/2017)
----------------------

API Changes
~~~~~~~~~~~

* Change method of reporting target data (#4593)
  `PR #4593 <https://github.com/pantsbuild/pants/pull/4593>`_

Bugfixes
~~~~~~~~

* Check that test case attribute exists in junit xml file before converting it (#4623)
  `Issue #4619 <https://github.com/pantsbuild/pants/issues/4619>`_
  `PR #4623 <https://github.com/pantsbuild/pants/pull/4623>`_

* [engine] Check for duplicate deps in v2 graph construction. (#4616)
  `PR #4616 <https://github.com/pantsbuild/pants/pull/4616>`_

* Improve Snapshot determinism (#4614)
  `PR #4614 <https://github.com/pantsbuild/pants/pull/4614>`_

* Revert "Enable --compile-zinc-use-classpath-jars by default" (#4607)
  `PR #4607 <https://github.com/pantsbuild/pants/pull/4607>`_

* Pass env vars through in ./pants run for python (#4606)
  `PR #4606 <https://github.com/pantsbuild/pants/pull/4606>`_

* Fix broken export-classpath (#4603)
  `PR #4603 <https://github.com/pantsbuild/pants/pull/4603>`_

* Switch to a conditional deprecation for the list-targets behaviour change. (#4600)
  `PR #4600 <https://github.com/pantsbuild/pants/pull/4600>`_

* Fix export-classpaths exclude behavior (#4592)
  `PR #4592 <https://github.com/pantsbuild/pants/pull/4592>`_

* Fix splitting of the build_flags. (#4580)
  `PR #4580 <https://github.com/pantsbuild/pants/pull/4580>`_

Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* [pantsd] Add an alternate entrypoint loader. (#4620)
  `PR #4620 <https://github.com/pantsbuild/pants/pull/4620>`_

* Remove Oracle Java6, which is now 404ing. (#4615)
  `PR #4615 <https://github.com/pantsbuild/pants/pull/4615>`_

* Don't register newpython tasks in the oldpython backend (#4602)
  `PR #4602 <https://github.com/pantsbuild/pants/pull/4602>`_

Documentation Updates
~~~~~~~~~~~~~~~~~~~~~

* Prepare notes for 1.3.0rc3 (#4617)
  `PR #4617 <https://github.com/pantsbuild/pants/pull/4617>`_

* Prepare the release notes for 1.3.0rc2 (#4609)
  `PR #4609 <https://github.com/pantsbuild/pants/pull/4609>`_

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
BUILD deps and to check that your python code conforms to pycodestyle and various other lints.

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

Special thanks to Stu Hood and Nora Howard for lots of work over the past months to get this point.

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
