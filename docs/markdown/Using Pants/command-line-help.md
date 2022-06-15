---
title: "Command line help"
slug: "command-line-help"
excerpt: "How to dynamically get more information on Pants's internals."
hidden: false
createdAt: "2020-02-27T01:32:45.818Z"
updatedAt: "2021-11-09T20:48:14.737Z"
---
Run `./pants help` to get basic help, including a list of commands you can run to get more specific help:
[block:code]
{
  "codes": [
    {
      "code": "❯ ./pants help\n\nPants 2.8.0\n\nUsage:\n\n  ./pants [option ...] [goal ...] [file/target ...]   Attempt the specified goals on the specified files/targets.\n  ./pants help                                        Display this usage message.\n  ./pants help goals                                  List all installed goals.\n  ./pants help targets                                List all installed target types.\n  ./pants help subsystems                             List all configurable subsystems.\n  ./pants help tools                                  List all external tools.\n  ./pants help global                                 Help for global options.\n  ./pants help-advanced global                        Help for global advanced options.\n  ./pants help [target_type/goal/subsystem]           Help for a target type, goal or subsystem.\n  ./pants help-advanced [goal/subsystem]              Help for a goal or subsystem's advanced options.\n  ./pants help-all                                    Print a JSON object containing all help info.\n\n  [file] can be:\n     path/to/file.ext\n     A path glob, such as '**/*.ext', in quotes to prevent premature shell expansion.\n\n  [target] can be:\n    path/to/dir:target_name.\n    path/to/dir for a target whose name is the same as the directory name.\n    path/to/dir:  to include all targets in the specified directory.\n    path/to/dir:: to include all targets found recursively under the directory.\n\nDocumentation at https://www.pantsbuild.org\nDownload at https://pypi.org/pypi/pantsbuild.pants/2.8.0",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
For example, to get help on the `test` goal:
[block:code]
{
  "codes": [
    {
      "code": "$ ./pants help test\n\n`test` goal options\n-------------------\n\nRun tests.\n\nConfig section: [test]\n\n  --[no-]test-debug\n  PANTS_TEST_DEBUG\n  debug\n      default: False\n      current value: False\n      Run tests sequentially in an interactive process. This is necessary, for example, when you add\n      breakpoints to your code.\n\n  --[no-]test-force\n  PANTS_TEST_FORCE\n  force\n      default: False\n      current value: False\n      Force the tests to run, even if they could be satisfied from cache.\n...\n\nRelated subsystems: coverage-py, download-pex-bin, pants-releases, pex, pex-binary-defaults, pytest, python-infer, python-native-code, python-repos, python-setup, setup-py-generation, setuptools, source, subprocess-environment",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
Note that when you run `./pants help <goal>`, it outputs all related subsystems, such as `pytest`. You can then run `./pants help pytest` to get more information.

You can also run `./pants help goals` and `./pants help subsystems` to get a list of all activated options scopes.

To get help on the `python_tests` target:
[block:code]
{
  "codes": [
    {
      "code": "❯ ./pants help python_test\n\n`python_test` target\n--------------------\n\nA single Python test file, written in either Pytest style or unittest style.\n\nAll test util code, including `conftest.py`, should go into a dedicated `python_source` target and then be included in the\n`dependencies` field. (You can use the `python_test_utils` target to generate these `python_source` targets.)\n\nSee https://www.pantsbuild.org/v2.8/docs/python-test-goal\n\nValid fields:\n\ntimeout\n    type: int | None\n    default: None\n    A timeout (in seconds) used by each test file belonging to this target.\n\n    This only applies if the option `--pytest-timeouts` is set to True.\n\n...",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
## Advanced Help

Many options are classified as _advanced_, meaning they are primarily intended to be used by admins, not by regular users.  

Use `help-advanced`, e.g. `./pants help-advanced global` or `./pants help-advanced pytest`.