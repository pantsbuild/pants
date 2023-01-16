---
title: "Prerequisites"
slug: "prerequisites"
hidden: false
createdAt: "2021-10-17T18:21:38.905Z"
updatedAt: "2022-04-11T21:13:21.965Z"
---
To run Pants, you need:

- One of: 
  - Linux (x86_64)
  - macOS (Intel or Apple Silicon, 10.15 Catalina or newer)
  - Microsoft Windows 10 with WSL 2
- Python 3.7, 3.8, or 3.9 discoverable on your `PATH`
- Internet access (so that Pants can fully bootstrap itself)

> 📘 Python 2 and 3.10+ compatibility
> 
> Pants requires Python 3.7, 3.8, or 3.9 to run itself, but it can build your Python 2 and Python 3.6 or earlier code, along with 3.10+.

> 📘 Restricted Internet access?
> 
> See [Restricted Internet access](doc:restricted-internet-access) for instructions.

System-specific notes
---------------------

### Linux

> 🚧 Some Linux distributions may need additional packages
> 
> On Ubuntu you may need to run:  
> `apt install -y python3-dev python3-distutils`.

> 🚧 Alpine Linux is not yet supported
> 
> Pants for Linux is currently distributed as a manylinux wheel. Alpine Linux is not covered by manylinux (it uses MUSL libc while manylinux requires glibc), so at present Pants will not run on Alpine Linux. 
> 
> If you need to run Pants on Alpine, [let us know](doc:community), so we can prioritize this work. Meanwhile, you can try [building Pants yourself](doc:manual-installation#building-pants-from-sources) on Alpine.

> 🚧 Linux on ARM is not yet supported
> 
> Pants for Linux is currently only distributed as an x86_64 wheel.
> 
> If you need to run Pants on ARM, please [upvote or comment on this issue](https://github.com/pantsbuild/pants/issues/12183) so we can prioritize this work. Meanwhile, you can try [building Pants yourself](doc:manual-installation#building-pants-from-sources) on ARM.

### macOS

> 📘 Apple Silicon (M1) support
> 
> We publish a macOS `arm64` wheel for Python 3.9. Make sure you have Python 3.9 discoverable on your `$PATH`, e.g. via Homebrew or Pyenv, and an updated version of the `./pants` runner script.
> 
> Given the lack of CI infrastructure for Apple Silicon, this support is best-effort and there may a delay in publishing this wheel compared to our normal releases.
> 
> If you have Python code, you may need to [set your interpreter constraints](doc:python-interpreter-compatibility) to Python 3.9+, as many tools like Black will not install correctly when using earlier Python versions.
> 
> Some users have also had success with earlier versions using Rosetta by running `arch -x86_64 pants`.
> 
> When using Docker from your M1, you will need to use `--no-watch-filesystem --no-pantsd`. (Although we don't recommend permanently setting this, as these options are crucial for performance when iterating.)

### Microsoft Windows

> 📘 Windows 10 support
> 
> Pants runs on Windows 10 under the Windows Subsystem for Linux (WSL):
> 
> - Follow [these instructions](https://docs.microsoft.com/en-us/windows/wsl/install-win10) to install WSL 2. 
> - Install a recent Linux distribution under WSL 2 (we have tested with Ubuntu 20.04 LTS).
> - Run `sudo apt install unzip python3-dev python3-distutils python3-venv gcc` in the distribution.
> - You can then run Pants commands in a Linux shell, or in a Windows shell by prefixing with `wsl `.
> 
> Projects using Pants must be contained within the Linux virtual machine:
> 
> - Navigating a Linux shell to a Windows directory via the `/mnt` directory, or using the `wsl` prefix with a Windows shell in a Windows directory, and executing Pants may result in unexpected behavior.
