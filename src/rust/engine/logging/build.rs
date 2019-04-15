// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
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
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn main() {
  let manifest_path = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
    .parent()
    .unwrap()
    .join("Cargo.toml");
  println!("cargo:rerun-if-changed={}", manifest_path.display());
  let config = cargo::util::config::Config::default().unwrap();
  let workspace = cargo::core::Workspace::new(&manifest_path, &config).unwrap();
  let packages: Vec<_> = workspace
    .members()
    .map(|package| package.name().to_string())
    .collect();
  let mut out_file =
    File::create(PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("packages.rs")).unwrap();
  writeln!(out_file, "pub const PANTS_PACKAGE_NAMES: &[&str] = &[").unwrap();
  for package in packages {
    writeln!(out_file, "  \"{}\",", package).unwrap();
  }
  writeln!(out_file, "];").unwrap();
}
