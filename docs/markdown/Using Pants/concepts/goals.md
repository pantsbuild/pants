---
title: "Goals"
slug: "goals"
excerpt: "The commands Pants runs."
hidden: false
createdAt: "2020-02-21T17:44:52.605Z"
updatedAt: "2022-04-11T21:31:11.557Z"
---
Pants commands are known as _goals_, such as `test` and `lint`.

To see the current list of goals, run:

```bash
❯ ./pants help goals
```

You'll see more goals activated as you activate more [backends](doc:enabling-backends).

Running goals
=============

For example:

```bash
❯ ./pants test project/app_test.py
15:40:37.89 [INFO] Completed: test - project/app_test.py:tests succeeded.

✓ project/app_test.py:tests succeeded.
```

You can also run multiple goals in a single run of Pants, in which case they will run sequentially:

```bash
# Format all code, and then lint it:
❯ ./pants fmt lint ::
```

Finally, Pants supports running goals in a `--loop`: in this mode, all goals specified will run sequentially, and then Pants will wait until a relevant file has changed to try running them again.

```bash
# Re-run typechecking and testing continuously as files or their dependencies change:
❯ ./pants --loop check test project/app_test.py
```

Use `Ctrl+C` to exit the `--loop`.

Goal arguments
==============

Some simple goals—such as the `roots` goal—do not require arguments. But most goals require some arguments to work on. 

For example, to run the `count-loc` goal, which counts lines of code in your repository, you need to provide a set of files and/or targets to run on:

```text Shell
$ ./pants count-loc '**'
───────────────────────────────────────────────────────────────────────────────
Language                 Files     Lines   Blanks  Comments     Code Complexity
───────────────────────────────────────────────────────────────────────────────
Python                      13       155       50        22       83          5
BASH                         2       261       29        22      210         10
JSON                         2        25        0         0       25          0
Plain Text                   2        43        1         0       42          0
TOML                         2        65       14        18       33          0
...
```

> 📘 Quoting file patterns
> 
> Note the single-quotes around the file pattern `'**'`. This is so that your shell doesn't attempt to expand the pattern, but instead passes it unaltered to Pants.

File arguments vs. target arguments
-----------------------------------

Goal arguments can be of one of two types:

- _File arguments_: file paths and/or globs.
- _Target arguments_: addresses and/or address globs of [targets](doc:targets).

Typically you can just use file arguments, and not worry about targets.

Any goal can take either type of argument: 

- If a target argument is given, the goal acts on all the files in the matching targets.
- If a file argument is given, Pants will map the file back to its containing target to read any necessary metadata. 

> 📘 File/target globs
> 
> For file arguments, use `'*'` and `'**'`, with the same semantics as the shell. Reminder: quote the argument if you want Pants to evaluate the glob, rather than your shell.
> 
> For target arguments, you can use:
> 
> - `dir::`, where `::` means every target in the current directory and recursively in subdirectories.
> - `dir:`, where `:` means every target in that directory, but not subdirectories.
> 
> For example, `./pants list ::` will find every target in your project.

> 📘 Tip: advanced target selection, such as running over changed files
> 
> See [Advanced target selection](doc:advanced-target-selection) for alternative techniques to specify which files/targets to run on.

Goal options
------------

Many goals also have [options](doc:options) to change how they behave. Every option in Pants can be set via an environment variable, config file, and the command line.

To see if a goal has any options, run `./pants help $goal` or `./pants help-advanced $goal`. See [Command Line Help](doc:getting-help) for more information.

For example:

```
❯ ./pants help test
17:20:14.24 [INFO] Remote cache/execution options updated: reinitializing scheduler...
17:20:15.36 [INFO] Scheduler initialized.

`test` goal options
-------------------

Run tests.

Config section: [test]

  --[no-]test-debug
  PANTS_TEST_DEBUG
  debug
      default: False
      current value: False
      Run tests sequentially in an interactive process. This is necessary, for example, when you
      add breakpoints to your code.

...
```

You can then use the option by prefixing it with the goal name:

```bash
./pants --test-debug test project/app_test.py
```

You can also put the option after the file/target arguments:

```bash
./pants test project/app_test.py --test-debug
```

As a shorthand, if you put the option after the goal and before the file/target arguments, you can leave off the goal name in the flag:

```bash
./pants test --debug project/app_test.py
```
