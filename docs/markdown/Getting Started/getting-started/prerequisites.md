---
title: "Prerequisites"
slug: "prerequisites"
hidden: false
createdAt: "2021-10-17T18:21:38.905Z"
updatedAt: "2022-04-11T21:13:21.965Z"
---
To run Pants, you need:

- One of: 
  - Linux (x86_64 or ARM64)
  - macOS (Intel or Apple Silicon, 10.15 Catalina or newer)
  - Microsoft Windows 10 with WSL 2
- Internet access (so that Pants can fully bootstrap itself)

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

> 🚧 Linux on ARM will be supported from Pants 2.16
> 
> Pants 2.16 will be distributed for Linux x86_64 and ARM64. Earlier versions are only distributed for Linux x86_64.
> 
> If you need to run an earlier version of Pants on ARM, you can try [building Pants yourself](doc:manual-installation#building-pants-from-sources) on that platform.

### macOS

> 📘 Apple Silicon (M1/M2) support
>
> If you have Python code, you may need to [set your interpreter constraints](doc:python-interpreter-compatibility) to Python 3.9+, as many tools, such as Black, will not install correctly when using earlier Python versions.
>
> When running in Docker you will need to set `--no-watch-filesystem --no-pantsd`. (Although we don't recommend permanently setting this, as these options are crucial for performance when iterating.)

### Microsoft Windows

> 📘 Windows 10 support
> 
> Pants runs on Windows 10 under the Windows Subsystem for Linux (WSL):
> 
> - Follow [these instructions](https://docs.microsoft.com/en-us/windows/wsl/install-win10) to install WSL 2. 
> - Install a recent Linux distribution under WSL 2 (we have tested with Ubuntu 20.04 LTS).
> - Run `sudo apt install unzip python3-dev python3-distutils python3-venv gcc` in the distribution.
> - You can then run Pants commands in a Linux shell, or in a Windows shell by prefixing with `wsl `.
