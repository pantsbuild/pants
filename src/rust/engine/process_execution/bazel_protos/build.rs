// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use protoc_grpcio;

use std::path::{Path, PathBuf};

use build_utils::BuildRoot;
use std::collections::HashSet;

fn main() {
  let build_root = BuildRoot::find().unwrap();
  let thirdpartyprotobuf = build_root.join("3rdparty/protobuf");
  mark_dir_as_rerun_trigger(&thirdpartyprotobuf);

  let grpcio_output_dir = PathBuf::from("src/gen");
  make_clean_dir(&grpcio_output_dir);
  generate_for_grpcio(&thirdpartyprotobuf, &grpcio_output_dir);

  let tower_output_dir = PathBuf::from("src/gen_for_tower");
  make_clean_dir(&tower_output_dir);
  generate_for_tower(&thirdpartyprotobuf, tower_output_dir.clone());

  let success = std::process::Command::new(env!("CARGO"))
    .arg("fmt")
    .arg("--package=bazel_protos")
    .status()
    .unwrap()
    .success();
  if !success {
    panic!("Cargo formatting failed for generated protos. Output should be above.");
  }

  // Re-gen if, say, someone does a git clean on the gen dir but not the target dir. This ensures
  // generated sources are available for reading by programmers and tools like rustfmt alike.
  mark_dir_as_rerun_trigger(&grpcio_output_dir);
  mark_dir_as_rerun_trigger(&tower_output_dir);
}

fn generate_for_grpcio(thirdpartyprotobuf: &Path, gen_dir: &Path) {
  let amended_proto_root =
    add_rustproto_header(&thirdpartyprotobuf).expect("Error adding proto bytes header");

  protoc_grpcio::compile_grpc_protos(
    &[
      "build/bazel/remote/execution/v2/remote_execution.proto",
      "google/bytestream/bytestream.proto",
      "google/rpc/code.proto",
      "google/rpc/error_details.proto",
      "google/rpc/status.proto",
      "google/longrunning/operations.proto",
      "google/protobuf/empty.proto",
    ],
    &[
      amended_proto_root.path().to_owned(),
      thirdpartyprotobuf.join("standard"),
      thirdpartyprotobuf.join("rust-protobuf"),
    ],
    &gen_dir,
  )
  .expect("Failed to compile protos!");

  disable_clippy_in_generated_code(&gen_dir).expect("Failed to strip clippy from generated code");

  generate_mod_rs(&gen_dir).expect("Failed to generate mod.rs");
}

fn mark_dir_as_rerun_trigger(dir: &Path) {
  for file in walkdir::WalkDir::new(dir) {
    let file = file.unwrap();
    if file.file_type().is_file() {
      println!("cargo:rerun-if-changed={}", file.path().display());
    }
  }
}

const EXTRA_HEADER: &'static str = r#"import "rustproto.proto";
option (rustproto.carllerche_bytes_for_bytes_all) = true;
"#;

///
/// Copies protos from thirdpartyprotobuf, adds a header to make protoc_grpcio uses Bytes instead
/// of Vec<u8>s, and rewrites them into a temporary directory
///
fn add_rustproto_header(thirdpartyprotobuf: &Path) -> Result<tempfile::TempDir, String> {
  let amended_proto_root = tempfile::TempDir::new().unwrap();
  for f in &["bazelbuild_remote-apis", "googleapis"] {
    let src_root = thirdpartyprotobuf.join(f);
    for entry in walkdir::WalkDir::new(&src_root)
      .into_iter()
      .filter_map(|entry| entry.ok())
      .filter(|entry| entry.file_type().is_file())
      .filter(|entry| entry.file_name().to_string_lossy().ends_with(".proto"))
    {
      let dst = amended_proto_root
        .path()
        .join(entry.path().strip_prefix(&src_root).unwrap());
      std::fs::create_dir_all(dst.parent().unwrap())
        .map_err(|err| format!("Error making dir in temp proto root: {}", err))?;
      let original = std::fs::read_to_string(entry.path())
        .map_err(|err| format!("Error reading proto {}: {}", entry.path().display(), err))?;
      let mut copy = String::with_capacity(original.len() + EXTRA_HEADER.len());
      for line in original.lines() {
        copy += line;
        copy += "\n";
        if line.starts_with("package ") {
          copy += EXTRA_HEADER
        }
      }
      std::fs::write(&dst, copy.as_bytes())
        .map_err(|err| format!("Error writing {}: {}", dst.display(), err))?;
    }
  }
  Ok(amended_proto_root)
}

///
/// protoc_grpcio generates its own clippy config, but it's for an out of date version of clippy,
/// so strip that out so we don't get warnings about it.
///
/// Add our own #![allow(clippy::all)] heading to each generated file so that we don't get any
/// warnings/errors from generated code not meeting our standards.
///
fn disable_clippy_in_generated_code(dir: &Path) -> Result<(), String> {
  for file in walkdir::WalkDir::new(&dir)
    .into_iter()
    .filter_map(|entry| entry.ok())
    .filter(|entry| {
      entry.file_type().is_file() && entry.file_name().to_string_lossy().ends_with(".rs")
    })
  {
    let lines: Vec<_> = std::fs::read_to_string(file.path())
      .map_err(|err| {
        format!(
          "Error reading generated protobuf at {}: {}",
          file.path().display(),
          err
        )
      })?
      .lines()
      .filter(|line| !line.contains("clippy"))
      .map(str::to_owned)
      .collect();
    let content = String::from("#![allow(clippy::all)]\n") + &lines.join("\n");
    std::fs::write(file.path(), content).map_err(|err| {
      format!(
        "Error re-writing generated protobuf at {}: {}",
        file.path().display(),
        err
      )
    })?;
  }
  Ok(())
}

fn generate_mod_rs(dir: &Path) -> Result<(), String> {
  let listing = dir.read_dir().unwrap();
  let mut pub_mod_stmts = listing
    .filter_map(|d| d.ok())
    .map(|d| d.file_name().to_string_lossy().into_owned())
    .filter(|name| &name != &"mod.rs" && &name != &".gitignore")
    .map(|name| format!("pub mod {};", name.trim_end_matches(".rs")))
    .collect::<Vec<_>>();
  pub_mod_stmts.sort();
  let contents = format!(
    "\
// This file is generated. Do not edit.
{}
",
    pub_mod_stmts.join("\n")
  );

  std::fs::write(dir.join("mod.rs"), contents)
    .map_err(|err| format!("Failed to write mod.rs: {}", err))
}

fn generate_for_tower(thirdpartyprotobuf: &Path, out_dir: PathBuf) {
  tower_grpc_build::Config::new()
    .enable_server(true)
    .enable_client(true)
    .build(
      &[PathBuf::from(
        "build/bazel/remote/execution/v2/remote_execution.proto",
      )],
      &std::fs::read_dir(&thirdpartyprotobuf)
        .unwrap()
        .into_iter()
        .map(|d| d.unwrap().path())
        .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|e| panic!("protobuf compilation failed: {}", e));

  let mut dirs_needing_mod_rs = HashSet::new();
  dirs_needing_mod_rs.insert(out_dir.clone());

  for f in walkdir::WalkDir::new(std::env::var("OUT_DIR").unwrap())
    .into_iter()
    .filter_map(|f| f.ok())
    .filter(|f| f.path().extension() == Some("rs".as_ref()))
  {
    let mut parts: Vec<_> = f
      .path()
      .file_name()
      .unwrap()
      .to_str()
      .unwrap()
      .split('.')
      .collect();
    // pop .rs
    parts.pop();

    let mut dst = out_dir.clone();
    for part in parts {
      dst.push(part);
      dirs_needing_mod_rs.insert(dst.clone());
      if !dst.exists() {
        std::fs::create_dir_all(&dst).unwrap();
      }
    }
    dirs_needing_mod_rs.remove(&dst);
    dst = dst.join("mod.rs");

    std::fs::copy(f.path(), dst).unwrap();
  }

  disable_clippy_in_generated_code(&out_dir).expect("Failed to strip clippy from generated code");

  for dir in &dirs_needing_mod_rs {
    generate_mod_rs(dir).expect("Failed to write mod.rs");
  }
}

fn make_clean_dir(path: &Path) {
  if path.exists() {
    std::fs::remove_dir_all(path).unwrap();
  }
  std::fs::create_dir_all(path).unwrap();
}
