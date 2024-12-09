# Dev Container for developping Pants

This project provides a *Development Container* (or [Dev Container](https://containers.dev/) for short) with a full-featured development environment containing all the tools, libraries, and runtimes needed to work with the [Pants] codebase. Here are some advantages of using dev containers:

- **Faster setup**: Dev containers can be pre-built with all the necessary tools, libraries and runtimes, making setting up a new development environment faster. This is especially useful for new team members joining a project who can quickly get started without spending time setting up their development environment.
- **Portability**: Dev containers provide portability between different platforms and clouds, allowing developers to write once and run anywhere. This ensures that developers can use the same development environment across different machines and platforms without compatibility issues.
- **Consistency**: Dev containers provide a consistent development environment for all developers working on a project. This ensures that everyone is using the same tools, libraries and runtimes, reducing the chances of compatibility issues and making it easier to collaborate and reproduce bugs.
- **Isolation**: Dev containers run in isolation from the host system, which improves security and reduces the chances of conflicts with other software installed on the host system.
- **Reproducibility**: Dev containers can be version-controlled, making it easy to reproduce the development environment at any point in time. It also allows developers to roll back to an earlier environment version if necessary.

## Features

- [Rust] engine and common [Rust] utilities
- [Python](https://www.python.org/) 3.11
- [Docker-in-Docker](https://github.com/devcontainers/features/tree/main/src/docker-in-docker) (DinD)
- [Shell History](https://github.com/stuartleeks/dev-container-features/tree/main/src/shell-history)
- [Local Git hooks](https://www.pantsbuild.org/stable/docs/contributions/development/setting-up-pants#step-3-set-up-a-pre-push-git-hook)
- Useful [VS Code] extensions like `Python`, `Pylance`, `Black Formatter`, `rust-analyser`, `Even Better TOML`, etc.
- Volumes for [Pants] [cache directories](https://www.pantsbuild.org/stable/docs/using-pants/using-pants-in-ci#directories-to-cache)
- `hyperfine`, `py-sy`, `memray` and `dbg` for [debugging and benchmarking](https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking)

## Getting started

You need three (3) things to get started with development containers:

- [VS Code]
- [Docker](https://www.docker.com/)
- [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension for [VS Code]

More on getting started can be found [here](https://code.visualstudio.com/docs/devcontainers/containers#_getting-started).

## Using the Dev Container

1. After cloning this repo, start [VS Code] and run the `Dev Containers: Open Folder in Container...` command from the *Command Palette...* (`F1`) and select the [Pants] project folder.
2. The [VS Code] window (instance) will reload and start building the dev container. A progress notification provides status updates.
3. After the build completes, [VS Code] will automatically connect to the container. You can now work with the repository source code in this independent environment.
    > [!NOTE]
    > Whenever you rebuild the dev container, you may have to execute the `Developer: Reload Window` command from the *Command Palette...* (`F1`) in order for the `Black Formatter` extension to be recognized by the settings. See: https://github.com/microsoft/vscode/issues/189839.
4. [Pants] sets up its development virtualenv at `~/.cache/pants/pants_dev_deps/<venv_fingerprint>.venv/`. Point [VS Code] to the `bin/python` file in this folder by running the `Python: Select Interpreter` command from the *Command Palette...* (`F1`), and then `Enter interpreter path...`. You may need to restart your *terminal*. See [Configure your IDE (optional)](https://www.pantsbuild.org/docs/contributor-setup#configure-your-ide-optional).

More on starting a dev container can be found [here](https://code.visualstudio.com/docs/devcontainers/containers#_picking-your-quick-start).

[pants]: https://github.com/pantsbuild/pants
[rust]: https://www.rust-lang.org/
[vs code]: https://code.visualstudio.com/
