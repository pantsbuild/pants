// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use cbindgen;
use cc;

/*
We use the `gcc` crate to compile the CFFI C sources (`native_engine.c`)
generated by `bootstrap.sh` into a (private) static lib (`libnative_engine_ffi.a`),
which then gets linked into the final `cargo build` product (the native engine binary).
This process mixes the Python module initialization function and other symbols into the
native engine binary, allowing us to address it both as an importable python module
(`from _native_engine import X`) as well as a C library (`ffi.dlopen(native_engine.so)`).

*/

use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::Path;
use std::process::{exit, Command};

use build_utils::BuildRoot;

#[derive(Debug)]
enum CffiBuildError {
  Io(io::Error),
  Env(env::VarError),
  Cbindgen(cbindgen::Error),
}

impl From<env::VarError> for CffiBuildError {
  fn from(err: env::VarError) -> Self {
    CffiBuildError::Env(err)
  }
}

impl From<io::Error> for CffiBuildError {
  fn from(err: io::Error) -> Self {
    CffiBuildError::Io(err)
  }
}

impl From<cbindgen::Error> for CffiBuildError {
  fn from(err: cbindgen::Error) -> Self {
    CffiBuildError::Cbindgen(err)
  }
}

// A message is printed to stderr, and the script fails, if main() results in a CffiBuildError.
fn main() -> Result<(), CffiBuildError> {
  // NB: When built with Python 3, `native_engine.so` only works with a Python 3 interpreter.
  // When built with Python 2, it works with both Python 2 and Python 3.
  // So, we check to see if the under-the-hood interpreter has changed and rebuild the native engine
  // when needed.
  println!("cargo:rerun-if-env-changed=PY");

  if cfg!(target_os = "linux") {
    // We depend on grpcio, which uses C++.
    // On Linux, with g++, some part of that compilation depends on
    // __gxx_personality_v0 which is present in the C++ standard library.
    // I don't know why. It shouldn't, and before grpcio 0.2.0, it didn't.
    println!("cargo:rustc-cdylib-link-arg=-lstdc++");
  }

  // Generate the scheduler.h bindings from the rust code in this crate.
  let bindings_config_path = Path::new("cbindgen.toml");
  mark_for_change_detection(&bindings_config_path);
  mark_for_change_detection(Path::new("src"));
  // Explicitly re-run if engine or logging is modified because they're hard-coded deps in cbindgen.toml.
  // Ideally we could just point at the engine crate here, but it's the workspace that contains all
  // code, and we don't want to re-run on _any_ code changes (even though we'll probably re-run for
  // them anyway), so we explicitly mark ../src and ../Cargo.toml for change-detection.
  //
  // This list should be kept in sync with the equivalent list of included crates in cbindgen.toml
  mark_for_change_detection(Path::new("../src"));
  mark_for_change_detection(Path::new("../Cargo.toml"));
  mark_for_change_detection(Path::new("../logging"));

  let scheduler_file_path = Path::new("src/cffi/scheduler.h");
  let crate_dir = env::var("CARGO_MANIFEST_DIR")?;
  cbindgen::generate(crate_dir)?.write_to_file(scheduler_file_path);

  // Generate the cffi c sources.
  let build_root = BuildRoot::find()?;
  let cffi_bootstrapper = build_root.join("build-support/bin/native/bootstrap_cffi.sh");
  mark_for_change_detection(&cffi_bootstrapper);

  // TODO: bootstrap_c_source() is used to generate C source code from @_extern_decl methods in
  // native.py. It would be very useful to be able to detect when those /declarations/ haven't
  // changed and avoid rebuilding the engine crate if we are just iterating on the implementations.
  mark_for_change_detection(&build_root.join("src/python/pants/engine/native.py"));

  let cffi_dir = Path::new("src/cffi");

  let result = Command::new(&cffi_bootstrapper)
    .arg(cffi_dir)
    .arg(scheduler_file_path)
    .status()?;
  if !result.success() {
    let exit_code = result.code();
    eprintln!(
      "Execution of {:?} failed with exit code {:?}",
      cffi_bootstrapper, exit_code
    );
    exit(exit_code.unwrap_or(1));
  }

  // N.B. The filename of this source code - at generation time - must line up 1:1 with the
  // python import name, as python keys the initialization function name off of the import name.
  let c_path = cffi_dir.join("native_engine.c");
  mark_for_change_detection(&c_path);
  let env_script_path = cffi_dir.join("native_engine.cflags");
  mark_for_change_detection(&env_script_path);

  // Now compile the cffi c sources.
  let mut config = cc::Build::new();

  let cfg_path = c_path.to_str().unwrap();
  config.file(cfg_path);
  for flag in make_flags(&env_script_path)? {
    config.flag(flag.as_str());
  }

  // cffi generates missing field initializers :(
  config.flag("-Wno-missing-field-initializers");

  config.compile("libnative_engine_ffi.a");

  if cfg!(target_os = "macos") {
    // N.B. On OSX, we force weak linking by passing the param `-undefined dynamic_lookup` to
    // the underlying linker. This avoids "missing symbol" errors for Python symbols
    // (e.g. `_PyImport_ImportModule`) at build time when bundling the CFFI C sources.
    // The missing symbols will instead by dynamically resolved in the address space of the parent
    // binary (e.g. `python`) at runtime. We do this to avoid needing to link to libpython
    // (which would constrain us to specific versions of Python).
    println!("cargo:rustc-cdylib-link-arg=-undefined");
    println!("cargo:rustc-cdylib-link-arg=dynamic_lookup");
  }

  Ok(())
}

fn mark_for_change_detection(path: &Path) {
  // Restrict re-compilation check to just our input files.
  // See: http://doc.crates.io/build-script.html#outputs-of-the-build-script
  if !path.exists() {
    panic!(
      "Cannot mark non-existing path for change detection: {}",
      path.display()
    );
  }
  for file in walkdir::WalkDir::new(path) {
    println!("cargo:rerun-if-changed={}", file.unwrap().path().display());
  }
}

fn make_flags(env_script_path: &Path) -> Result<Vec<String>, io::Error> {
  let mut contents = String::new();
  fs::File::open(env_script_path)?.read_to_string(&mut contents)?;
  // It would be a shame if someone were to include a space in an actual quoted value.
  // If they did that, I guess we'd need to implement shell tokenization or something.
  Ok(
    contents
      .trim()
      .split_whitespace()
      .map(str::to_owned)
      .collect(),
  )
}
