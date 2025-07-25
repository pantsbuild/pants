// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use cargo_metadata::MetadataCommand;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn main() {
    let manifest_path = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
        .parent()
        .unwrap()
        .join("Cargo.toml");
    println!("cargo:rerun-if-changed={}", manifest_path.display());

    let metadata = MetadataCommand::new()
        .manifest_path(manifest_path)
        .no_deps()
        .exec()
        .expect("Error accessing cargo metadata");

    let mut packages: Vec<_> = metadata
        .workspace_members
        .iter()
        .map(|package_id| metadata[package_id].name.clone())
        .collect();
    packages.sort();

    let mut out_file =
        File::create(PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("packages.rs")).unwrap();
    writeln!(out_file, "pub const PANTS_PACKAGE_NAMES: &[&str] = &[").unwrap();
    for package in packages {
        writeln!(out_file, "  \"{package}\",").unwrap();
    }
    writeln!(out_file, "];").unwrap();
}
