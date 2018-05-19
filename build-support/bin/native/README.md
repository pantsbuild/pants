This directory houses shell scripts that bootstrap a rust toolchain for building and testing Pants
native engine code.

Besides the checked-in bootstrap scripts, this directory also houses symlinks generated on the fly
to support third-party development environments (e.g. IDEA) that need access to an appropriate
`$CARGO_HOME/bin` and rust toolchain sources (`src/`).

The structure, then is:
```
build-support/bin/native/
  *.sh                 - checked-in bootstrap scripts
  cargo                - checked-in symlink to a wrapped cargo appropriate for Pants development
  src/                 - rust stdlib sources (generated)
  <remaining symlinks> - symlinks to the remaining $CARGO_HOME/bin tools (generated)
```
Some explanation of the checked-in bootstrap scripts is in order:

+ `bootstrap_code.sh`

  This generates a native engine binary resource with embedded provenance headers for use by pants
  as a cffi target to access the native engine facilities via. It relies upon the `cargo` binary in
  this directory.

+ `cargo.sh`

  This serves as a replacement for a vanilla cargo, wrapping execution of an underlying pristine
  cargo with environment setup required by Pants rust code, generated code and dependencies. It
  relies on `bootstrap_rust.sh`.

+ `bootstrap_rust.sh`

  This bootstraps a pristine, controlled, rust environment for building and testing Pants rust
  code. It generates symlinks to the various cargo tools in the controlled environment for
  convenience as well as a `src/` symlink that points to the appropriate rust stdlib code. For
  example, to use an appropriate debugger for the Pants native engine code, you can use the
  `build-support/bin/native/rust-gdb` symlink it generates. These symlinks depend on
  `rust_toolchain.sh` for re-direction to the appropriate underlying pristine cargo tools.

+ `rust_toolchain.sh`

  A symlink re-director that ensures the cargo binary symlinks in this directory can be used
  directly and will self-bootstrap as-needed. It relies on `bootstrap_rust.sh` for toolchain
  bootstrapping.
