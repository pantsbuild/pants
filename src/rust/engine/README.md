A native-code implementation of the pants v2 engine. See:

    https://docs.google.com/document/d/1C64MreDeVoZAl3HrqtWUVE-qnj3MyWW0NQ52xejjaWw/edit?usp=sharing

To build for development, simply run pants from the root of the repo:

    ./pants list 3rdparty::

If you plan to iterate on changes to the rust code, it is recommended to set `MODE=debug`, which
will compile the engine more quickly, but result in a much slower binary:

    MODE=debug ./pants list 3rdparty::

To run tests for all crates, run:

    ./run-all-tests.sh

### Configuring IntelliJ to work with Rust

You will first need to set these environment variables:

    export CARGO_HOME="${HOME}/.cache/pants/rust/cargo"
    export RUSTUP_HOME="${HOME}/.cache/pants/rust/rustup"
    export GOROOT="${HOME}/.cache/pants/bin/go/mac/10.13/1.7.3/go"
    export PATH="${PATH}:${GOROOT}/bin"

Now in your IntelliJ Preferences, install the Rust plugin and set Rust's `Toolchain location` to:

    ~/.cache/pants/rust/cargo/bin

and set the `Standard library` to:

    ~/.cache/pants/rust/rustup/toolchains/1.25.0-x86_64-apple-darwin/lib/rustlib/src/rust/src

You should now be able to compile and run Rust code and tests using IntelliJ.
