---
title: "Developing Rust"
slug: "contributions-rust"
excerpt: "Hacking on the Pants engine in Rust."
hidden: false
createdAt: "2020-05-16T23:11:31.121Z"
---
We welcome contributions to Rust! We use Rust to implement the Pants engine in a performant, safe, and ergonomic way.

> 📘 Still learning Rust? Ask to get added to reviews
> 
> We'd be happy to ping you on Rust changes we make for you to see how Rust is used in the wild. Please message us on the #engine channel in [Slack](doc:the-pants-community) to let us know your interest.

> 🚧 Recommendation: share your plan first
> 
> Because changes to Rust deeply impact how Pants runs, it is especially helpful to share any plans to work on Rust before making changes. Please message us on [Slack](doc:the-pants-community) in the #engine channel or open a [GitHub issue](https://github.com/pantsbuild/pants/issues).

Code organization
-----------------

The code for the top-level Pants Rust crate lives in `src/rust/engine`. The top-level `Cargo.toml` file at `src/rust/engine/Cargo.toml` defines a cargo workspace containing a number of other subcrates, which live in subdirectories of `src/rust/engine`. Defining multiple subcrates in this way allows changes affecting one subcrate to avoid affecting other subcrates and triggering more recompilation than is necessary.

Several of the particularly important subcrates are:

- `graph`: the core of Pants's rule graph implementation.
- `ui`: the dynamic UI.
- `sharded_lmdb`: custom wrappers around the `crates.io` `lmdb` crate, which provides bindings to [lmdb](https://en.wikipedia.org/wiki/Lightning_Memory-Mapped_Database).
- `fs`: manipulating the filesystem.
- `process_execution`: running local and remote processes.

Rust \<-> Python interaction
----------------------------

Pants is best conceptualized as a Python program that makes frequent foreign function interface (FFI) calls into Rust code. 

The top-level `engine` Rust crate gets compiled into a library named `native_engine.so`, which Python code knows how to interact with. We use the Rust [PyO3](https://pyo3.rs/) crate to manage foreign function interaction.

The C FFI functions that Rust code exposes as a public interface live in `src/rust/engine/src/externs/interface.rs`. On the Python side, `src/python/pants/engine/internals/native_engine.pyi` provides type hints for the functions and classes provided by Rust.

Rust can also invoke Python functions and object constructors thanks to [PyO3](https://pyo3.rs) crate.

We are planning to port additional functionality from Python to Rust, generally for performance reasons.

Common commands
---------------

Rather than using a global installation of Cargo, use the `./cargo` script.

### Compile

To check that the Rust code is valid, use `./cargo check`. To check that it integrates correctly with Pants' Python code, use `MODE=debug pants ...` as usual (which will `compile` first, and is slower than `check`).

> 🚧 Set `MODE=debug` when iterating on Rust
> 
> As described in [Setting up Pants](doc:contributor-setup), we default to compiling Rust in release mode, rather than debug mode.
> 
> When working on Rust, you typically should set the environment variable `MODE=debug` for substantially faster compiles.

### Run tests

To run tests for all crates, run:

```bash
./cargo test
```

To run for a specific crate, such as the `fs` create, run:

```bash
./cargo test -p fs
```

To run for a specific test, use Cargo's filtering mechanism, e.g.:

```bash
./cargo test -p fs read_file_missing
```

> 📘 Tip: enabling logging in tests
> 
> When debugging, it can be helpful to capture logs with [`env_logger`](https://docs.rs/env_logger/0.6.1/env_logger/).
> 
> To enable logging:
> 
> 1. Add `env_logger = "..."` to `dev-dependencies` in the crate's `Cargo.toml`, replacing the `...` with the relevant version. Search for the version used in other crates.
> 2. At the start of your test, add `let _logger = env_logger::try_init();`.
> 3. Add log statements wherever you'd like using `log::info!()` et al.
> 4. Run your test with `RUST_LOG=trace ./cargo test -p $crate test_name -- --nocapture`, using one of `error`, `warn`, `info`, `debug`, or `trace`.

### Autoformat

```bash
./cargo fmt
```

To run in lint mode, add `--check`.

### Run Clippy

```bash
./cargo clippy
```

The `fs_util` tool
------------------

`fs_util` is a utility that enables you to interact with `Snapshot`s from the command line. You can use it to help debug issues with snapshotted files.

To build it, run this from the root of the repository:

```bash
$ ./cargo build -p fs_util
```

That will produce `src/rust/engine/target/debug/fs_util`.

To inspect a particular snapshot, you'll need to tell `fs_util` where the storage is and the digest and length of the snapshot to inspect. You can use the `--local-store-path` flag for that.

For example, this command pretty prints the recursive file list of a directory through the directory subcommand.

```bash
$ src/rust/engine/target/debug/fs_util --local-store-path=${HOME}/.cache/pants/lmdb_store directory cat-proto --output-format=recursive-file-list <digesh> <len>
```

Pass the `--help` flag to see other ways of using `fs_util`, along with its subcommands. Each subcommand can be passed the `--help` flag.
