---
title: "Contribution overview"
slug: "contributor-overview"
excerpt: "The flow for making changes to Pants."
hidden: false
createdAt: "2020-05-16T22:54:21.867Z"
---
We welcome contributions of all types: from fixing typos to bug fixes to new features. For further questions about any of the below, please refer to the [community overview](doc:the-pants-community).

> 👍 Help wanted: identifying bad error messages
> 
> We strive—but sometimes fail—to make every error message easy to understand and to give insight into what went wrong and how to fix it.
> 
> If you ever encounter a confusing or mediocre error message, we would love your help to identify the error message. Please open a [GitHub issue](https://github.com/pantsbuild/pants/issues) with the original Pants command, the error message, and what you found confusing or think could be improved.
> 
> (If you'd be interested in then changing the code, we'd be happy to point you in the right direction!)

Documentation Fixes
-------------------

To suggest edits to Pants documentation, fork the [Pants repository](https://github.com/pantsbuild/pants), make changes to files in the `docs/` directory, and submit a PR against the `main` branch. Address feedback from maintainers and, once approved, your changes will be incorporated into the official documentation.

Pants's tech stack
------------------

Most of Pants is written in Python 3. The majority of contributions touch this Python codebase.

We rely on several Python features that you will want to acquaint yourself with:

- [Type hints and MyPy](https://mypy.readthedocs.io/en/stable/)
- [Dataclasses](https://realpython.com/python-data-classes/)
- [`async`/`await` coroutines](https://www.python.org/dev/peps/pep-0492)
  - We do _not_ use `asyncio`. The scheduler is implemented in Rust. We only use `async` coroutines.
- [Decorators](https://realpython.com/primer-on-python-decorators/)
- [Comprehensions](https://www.geeksforgeeks.org/comprehensions-in-python/)

Pants's engine is written in Rust. See [Developing Rust](doc:contributions-rust) for a guide on making changes to the internals of Pants's engine.

First, share your plan
----------------------

Before investing your time into a code change, it helps to share your interest. This will allow us to give you initial feedback that will save you time, such as pointing you to related code.

To share your plan, please either open a [GitHub issue](https://github.com/pantsbuild/pants/issues) or message us on [Slack](doc:getting-help#slack) (you can start with the #general channel). Briefly describe the change you'd like to make, including a motivation for the change.

If we do not respond within 24 business hours, please gently ping us by commenting "ping" on your GitHub issue or messaging on Slack asking if someone could please take a look.

> 📘 Tip: Can you split out any "prework"?
> 
> If your change is big, such as adding a new feature, it can help to split it up into multiple pull requests. This makes it easier for us to review and to get passing CI.
> 
> This is a reason we encourage you to share your plan with us - we can help you to scope out if it would make sense to split into multiple PRs.

Design docs
-----------

Changes that substantially impact the user experience, APIs, design or implementation, may benefit from a design doc that serves as a basis for discussion. 

We store our design docs in [this Google Drive folder](https://drive.google.com/drive/folders/1LtA1EVPvalmfQ5AIDOqGRR3LV86_qCRZ). If you want to write a design doc, [let us know](https://www.pantsbuild.org/docs/getting-help) and if necessary we can give you write access to that folder.

We don't currently have any guidelines on the structure or format of design docs, so write those as you see fit.

Developing your change
----------------------

To begin, [set up Pants on your local machine](doc:contributor-setup).

To run a test, run:

```bash
$ pants test src/python/pants/util/frozendict_test.py
```

Periodically, you will want to run MyPy and the autoformatters and linters:

```bash
# Format un-committed changes
$ pants --changed-since=HEAD fmt

# Run the pre-commit checks, including `check` and `lint`
$ build-support/githooks/pre-commit
```

See our [Style guide](doc:style-guide) for some Python conventions we follow.

> 📘 You can share works in progress!
> 
> You do not need to fully finish your change before asking for feedback. We'd be eager to help you while iterating.
> 
> If doing this, please open your pull request as a "Draft" and prefix your PR title with "WIP". Then, comment on the PR asking for feedback and/or post a link to the PR in [Slack](doc:the-pants-community).

Opening a pull request
----------------------

When opening a pull request, start by providing a concise and descriptive title. It's okay if you aren't sure what to put - we can help you to reword it. 

Good titles:

- Fix typo in `strutil.py`
- Add Thrift code generator for Python
- Fix crash when running `test` with Python 3.9

Bad titles:

- Fix bug
- Fix #8313
- Add support for Thrift code generation by first adding the file `codegen.py`, then hooking it up, and finally adding tests

Then, include a description. You can use the default template if you'd like, or use a normal description instead. Link to any corresponding GitHub issues.

Finally—if you have the permissions—add exactly one of the following labels to your PR. Otherwise, a maintainer will do this for you:

- `category:new feature` for new features
- `category:user api change` for changes that affect how end-users interact with Pants
- `category:plugin api change` for changes that affect how plugin authors interact with Pants internals
- `category:performance` for changes focused on improving performance
- `category:bugfix` for bugfixes
- `category:documentation` for documentation changes, including logging and help messages
- `category:internal` for miscellaneous, internal-facing changes

Pick the first of these that applies to your change. I.e., if you have modified the user API in a change that also improves performance, use `category:user api change`.

These labels are used to generate the changelist for each release.

> 📘 Tip: Review your own PR
> 
> It is often helpful to other reviewers if you proactively review your own code. Specifically, add comments to parts where you want extra attention.
> 
> For example:
> 
> - "Do you know of a better way to do this? This felt clunky to write."
> - "This was really tricky to figure out because there are so many edge cases. I'd appreciate extra attention here, please."
> - "Note that I did not use a dataclass here because I do not want any of the methods like `__eq__` to be generated."

> 📘 FYI: we squash merge
> 
> This means that the final commit message will come from your PR description, rather than your commit messages. 
> 
> Good commit messages are still very helpful for people reviewing your code; but, your PR description is what will show up in the changelog.

### CI

We use GitHub Actions for CI. Look at the "Checks" tab of your PR.

> 📘 Flaky tests?
> 
> We unfortunately have some flaky tests. If CI fails and you believe it is not related to your change, please comment about the failure so that a maintainer may investigate and restart CI for you.
> 
> Alternatively, you can push an empty commit with `git commit --allow-empty` to force CI to restart. Although we encourage you to still point out the flake to us.

### Review feedback

One or more reviewers will leave feedback. If you are confused by any of the feedback, please do not be afraid to ask for clarification!

If we do not respond within 24 business hours, please gently ping us by commenting "ping" on your pull request or messaging on Slack asking if someone could please take a look.

Once one or more reviewers have approved—and CI goes green—a reviewer will merge your change.

> 📘 When will your change be released?
> 
> Your change will be included in the next weekly dev release, which usually happens every Friday or Monday. If you fixed a bug, your change may also be cherry-picked into a release candidate from the prior release series.
> 
> See [Release strategy](doc:release-strategy).
