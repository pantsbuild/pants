---
title: "Setting up Pants"
slug: "contributor-setup"
excerpt: "How to set up Pants for local development."
hidden: false
createdAt: "2020-05-16T22:54:22.684Z"
---
Step 1: Fork and clone `pantsbuild/pants`
-----------------------------------------

We use the popular forking workflow typically used by open source projects. See <https://guides.github.com/activities/forking/> for a guide on how to fork [pantsbuild/pants](https://github.com/pantsbuild/pants), then clone it to your local machine.

> 🚧 macOS users: install a newer `openssl`
> 
> Pants requires a more modern OpenSSL version than the one that comes with macOS. To get all dependencies to resolve correctly, run the below commands. If you are using Zsh, use `.zshrc` rather than `.bashrc`.
> 
> ```bash
> $ brew install openssl
> $ echo 'export PATH="/usr/local/opt/openssl/bin:$PATH"' >> ~/.bashrc
> $ echo 'export LDFLAGS="-L/usr/local/opt/openssl/lib"' >> ~/.bashrc
> $ echo 'export CPPFLAGS="-I/usr/local/opt/openssl/include"' >> ~/.bashrc
> ```
> 
> (If you don't have `brew` installed, see <https://brew.sh.>)

Step 2: Bootstrap the Rust engine
---------------------------------

Pants requires several dependencies to be installed: a Python 3.9 interpreter, Rust, the protobuf compiler, clang and others. There is experimental support for the Nix package manager that makes it easy to set up a dev environment. Follow the instructions on the [Nix website](https://nixos.org/download.html) to install Nix. Then `cd` into the directory where you cloned the Pants repo and type `nix-shell`. This will download all the necessary dependencies and start a shell with a suitably configured PATH variable to make them available for use.

Alternatively, you can install the dependencies manually as follows:

Pants uses Rustup to install Rust. Run the command from <https://rustup.rs> to install Rustup; ensure that `rustup` is on your `$PATH`.

If your system Python is not the version Pants expects (currently Python 3.9), you'll need to provide one.  Python interpreters from Linux or Mac distributions sometimes have quirks that can cause headaches with bootstrapping the dev venv.  Some examples of Pythons that work well with Pants are those provided by:
- [Fedora](https://packages.fedoraproject.org/pkgs/python3.9/python3.9/)
- [ASDF](https://github.com/asdf-community/asdf-python)
- [PyEnv](https://github.com/pyenv/pyenv)
Providers that sometimes cause issues include:
- Ubuntu Deadsnakes
You also need to have the protobuf compiler and LLVM clang installed. On Debian derivatives, these can be installed using `apt install clang protobuf-compiler`.

Then, run `pants` to set up the Python virtual environment and compile the engine.

> 🚧 This will take several minutes
> 
> Rust compilation is really slow. Fortunately, this step gets cached, so you will only need to wait the first time.

> 📘 Want a faster compile?
> 
> We default to compiling with Rust's `release` mode, instead of its `debug` mode, because this makes Pants substantially faster.  However, this results in the compile taking 5-10x longer.
> 
> If you are okay with Pants running much slower when iterating, set the environment variable `MODE=debug` and rerun `pants` to compile in debug mode.

> 🚧 Rust compilation can use lots of storage
> 
> Compiling the engine typically results in several gigabytes of storage over time. We have not yet implemented automated garbage collection for building the engine because contributors are the only ones to need to compile Rust, not every-day users.
> 
> To free up space, run `rm -rf src/rust/engine/target`.
> 
> Warning: this will cause Rust to recompile everything.


Step 3: (Optional) Set up a Git hook
------------------------------------

We have a [Git hook](https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks) that runs some useful checks and lints when you `git commit`.

To install this, run:

```bash
$ build-support/bin/setup.sh
```

If you commit frequently as part of your workflow you may find it annoying to have these run every time, so installing this hook is not required.

You can manually run the pre-commit check with:

```bash
$ build-support/githooks/pre-commit
```

The [Rust-compilation](doc:contributions-rust) affecting `MODE` flag is passed through to the hooks, so to run the commit hooks in "debug" mode, you can do something like:

```bash
$ MODE=debug git commit ...
```

> 📘 How to temporarily skip the pre-commit checks
> 
> Use `git commit --no-verify` or `git commit -n` to skip the checks.

Configure your IDE (optional)
-----------------------------

### Hooking up the Python virtual environment

Most IDEs allow you to configure a Python [virtual environment](https://docs.python.org/3/tutorial/venv.html) so that the editor understands your Python import statements. 

Pants sets up its development virtualenv at `~/.cache/pants/pants_dev_deps/<arch>.<version>.venv/`. Point your editor to the `bin/python` file in this folder, e.g. `~/.cache/pants/pants_dev_deps/Darwin.py37.venv/bin/python`.

### PyCharm guide

1. Use "New project" and click the option "Existing interpreter". Point the interpreter to the virtual environment location described above.
2. In your project tree (the list of folders and files), secondary-click the folder `src/python`. Click "Mark directory as" and choose "Sources". 

### VSCode guide

Add this to your `settings.json` file inside the build root's `.vscode` folder:

```json settings.json
{
  "python.analysis.extraPaths": ["src/python"],
  "python.formatting.provider": "black",
  "python.linting.enabled": true,  
  "python.linting.flake8Enabled": true,
  "python.linting.flake8Args": [
    "--config=build-support/flake8/.flake8"
  ],
}
```

`python.analysis.extraPaths` lets VSCode know where to find Pants's source root. The other config enables `black` and `flake8`.
