---
title: "lint"
slug: "python-lint-goal"
excerpt: "Lint source code."
hidden: false
createdAt: "2020-03-16T16:19:55.704Z"
updatedAt: "2022-03-05T01:09:54.477Z"
---
The `lint` goal runs both dedicated linters and any formatters in check-only mode:

- Autoflake
- Bandit
- Black
- Docformatter
- Flake8
- isort
- Pylint
- Pyupgrade
- yapf

See [here](doc:python-linters-and-formatters) for how to opt in to specific formatters and linters, along with how to configure them.

> 👍 Benefit of Pants: runs linters in parallel
> 
> Pants will run all activated linters at the same time for improved performance. As explained at [Python linters and formatters](doc:python-linters-and-formatters), Pants also uses some other techniques to improve concurrency, such as dynamically setting the `--jobs` option for linters that have it.

> 👍 Benefit of Pants: lint Python 2-only and Python 3-only code at the same time
> 
> Bandit, Flake8, and Pylint depend on which Python interpreter the tool is run with. Normally, if your project has some Python 2-only files and some Python 3-only files, you would not be able to run the linter in a single command because it would fail to parse your code.
> 
> Instead, Pants will do the right thing when you run `./pants lint ::`. Pants will group your targets based on their [interpreter constraints](doc:python-interpreter-compatibility), and run all the Python 2 targets together and all the Python 3 targets together.
