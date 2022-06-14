---
title: "Setting up Pants"
slug: "contributor-setup"
excerpt: "How to set up Pants for local development."
hidden: false
createdAt: "2020-05-16T22:54:22.684Z"
updatedAt: "2022-04-26T23:55:48.923Z"
---
[block:api-header]
{
  "title": "Step 1: Fork and clone `pantsbuild/pants`"
}
[/block]
We use the popular forking workflow typically used by open source projects. See https://guides.github.com/activities/forking/ for a guide on how to fork [pantsbuild/pants](https://github.com/pantsbuild/pants), then clone it to your local machine.
[block:callout]
{
  "type": "warning",
  "title": "macOS users: install a newer `openssl`",
  "body": "Pants requires a more modern OpenSSL version than the one that comes with macOS. To get all dependencies to resolve correctly, run the below commands. If you are using Zsh, use `.zshrc` rather than `.bashrc`.\n\n```bash\n$ brew install openssl\n$ echo 'export PATH=\"/usr/local/opt/openssl/bin:$PATH\"' >> ~/.bashrc\n$ echo 'export LDFLAGS=\"-L/usr/local/opt/openssl/lib\"' >> ~/.bashrc\n$ echo 'export CPPFLAGS=\"-I/usr/local/opt/openssl/include\"' >> ~/.bashrc\n```\n\n(If you don't have `brew` installed, see https://brew.sh.)"
}
[/block]

[block:api-header]
{
  "title": "Step 2: Set up Git hooks"
}
[/block]
We use two [Git hooks](https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks):

1. If you didn't touch any Rust code, we add `[ci skip-rust]` to your commit message. If you didn't touch any of our release-related code, we add `[ci skip-build-wheels]` to your commit message.
2. Every time you run `git commit`, we run some checks and lints.

To install these, run:

```bash
$ build-support/bin/setup.sh
```

You can manually run the pre-commit check by running:

```bash
$ build-support/githooks/pre-commit
```

The [Rust-compilation](doc:contributions-rust) affecting `MODE` flag is passed through to the hooks, so to run the commit hooks in "debug" mode, you can do something like:

```bash
$ MODE=debug git commit ...
```
[block:callout]
{
  "type": "info",
  "title": "How to temporarily skip the pre-commit checks",
  "body": "Use `git commit --no-verify` or `git commit -n` to skip the checks."
}
[/block]

[block:api-header]
{
  "title": "Step 3: Bootstrap the Rust engine"
}
[/block]
Pants uses Rustup to install Rust. Run the command from https://rustup.rs to install Rustup; ensure that `rustup` is on your `$PATH`.

Then, run `./pants` to set up the Python virtual environment and compile the engine.
[block:callout]
{
  "type": "warning",
  "title": "This will take several minutes",
  "body": "Rust compilation is really slow. Fortunately, this step gets cached, so you will only need to wait the first time."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Want a faster compile?",
  "body": "We default to compiling with Rust's `release` mode, instead of its `debug` mode, because this makes Pants substantially faster.  However, this results in the compile taking 5-10x longer.\n\nIf you are okay with Pants running much slower when iterating, set the environment variable `MODE=debug` and rerun `./pants` to compile in debug mode."
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "Rust compilation can use lots of storage",
  "body": "Compiling the engine typically results in several gigabytes of storage over time. We have not yet implemented automated garbage collection for building the engine because contributors are the only ones to need to compile Rust, not every-day users.\n\nTo free up space, run `rm -rf src/rust/engine/target`.\n\nWarning: this will cause Rust to recompile everything."
}
[/block]

[block:api-header]
{
  "title": "Configure your IDE (optional)"
}
[/block]
### Hooking up the Python virtual environment

Most IDEs allow you to configure a Python [virtual environment](https://docs.python.org/3/tutorial/venv.html) so that the editor understands your Python import statements. 

Pants sets up its development virtualenv at `~/.cache/pants/pants_dev_deps/<arch>.<version>.venv/`. Point your editor to the `bin/python` file in this folder, e.g. `~/.cache/pants/pants_dev_deps/Darwin.py37.venv/bin/python`.

### PyCharm guide

1. Use "New project" and click the option "Existing interpreter". Point the interpreter to the virtual environment location described above.
2. In your project tree (the list of folders and files), secondary-click the folder `src/python`. Click "Mark directory as" and choose "Sources". 

### VSCode guide

Add this to your `settings.json` file inside the build root's `.vscode` folder:
[block:code]
{
  "codes": [
    {
      "code": "{\n  \"python.analysis.extraPaths\": [\"src/python\"],\n  \"python.formatting.provider\": \"black\",\n  \"python.linting.enabled\": true,  \n  \"python.linting.flake8Enabled\": true,\n  \"python.linting.flake8Args\": [\n    \"--config=build-support/flake8/.flake8\"\n  ],\n}",
      "language": "json",
      "name": "settings.json"
    }
  ]
}
[/block]
`python.analysis.extraPaths` lets VSCode know where to find Pants's source root. The other config enables `black` and `flake8`.