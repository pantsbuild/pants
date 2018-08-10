A native-code implementation of the pants v2 engine. See:

    https://docs.google.com/document/d/1C64MreDeVoZAl3HrqtWUVE-qnj3MyWW0NQ52xejjaWw/edit?usp=sharing

To build for development, simply run pants from the root of the repo:

    ./pants list 3rdparty::

If you plan to iterate on changes to the rust code, it is recommended to set `MODE=debug`, which
will compile the engine more quickly, but result in a much slower binary:

    MODE=debug ./pants list 3rdparty::

To run tests for all crates, run:

    ./build-support/bin/native/cargo test --manifest-path src/rust/engine/Cargo.toml --all

### Configuring IntelliJ to work with Rust

You will first need to bootstrap Pants' Rust toolchain and `./build-support/bin/native/cargo -V` or
`./pants -V` is enough to do this.

Now in your IntelliJ Preferences, install the Rust plugin and set Rust's `Toolchain location` to:

    build-support/bin/native

and set the `Standard library` to:

    build-support/bin/native/src

You should now be able to compile and run Rust code and tests using IntelliJ.
