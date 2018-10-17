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


## Building fs_util

`fs_util` is a utility that enables you to interact with snapshots from the commandline. You can use it to help debug issues with snapshotted files.

To build it run the following from root of the pants repository.

    cd src/rust/engine && ../../../build-support/bin/native/cargo build -p fs_util

That will produce `src/rust/engine/target/debug/fs_util`. You can then use that binary to inspect snapshots.

To inspect a particular snapshot, you'll need to tell fs_util where the storage is and the digest and length of the snapshot to inspect. You can use the `--local-store-path` flag for that.


For example, this command pretty prints the recursive file list of a directory through the directory subcommand.

    src/rust/engine/target/debug/fs_util --local-store-path=${HOME}/.cache/pants/lmdb_store directory cat-proto --output-format=recursive-file-list <digesh> <len>

There are a number of ways to use `fs_util` and its subcommands to inspect snapshots. To see more about them pass the `--help` flag.

Each of the subcommands may also have subcommands. You can also pass `--help` to each subcommand.
