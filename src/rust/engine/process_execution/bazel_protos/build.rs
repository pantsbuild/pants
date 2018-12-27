use protoc_grpcio;

use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};

use build_utils::BuildRoot;

fn main() {
  let build_root = BuildRoot::find().unwrap();
  let thirdpartyprotobuf = build_root.join("3rdparty/protobuf");
  println!(
    "cargo:rerun-if-changed={}",
    thirdpartyprotobuf.to_str().unwrap()
  );

  let amended_proto_root =
    add_rustproto_header(&thirdpartyprotobuf).expect("Error adding proto bytes header");

  let gen_dir = PathBuf::from("src/gen");

  // Re-gen if, say, someone does a git clean on the gen dir but not the target dir. This ensures
  // generated sources are available for reading by programmers and tools like rustfmt alike.
  println!("cargo:rerun-if-changed={}", gen_dir.to_str().unwrap());

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

  // Ignore clippy for generated code.
  // protoc_grpcio generates its own clippy config, but it's for an out of date version of clippy,
  // so strip that out.
  for file in walkdir::WalkDir::new(&gen_dir)
    .into_iter()
    .filter_map(|entry| entry.ok())
    .filter(|entry| {
      entry.file_type().is_file() && entry.file_name().to_string_lossy().ends_with(".rs")
    })
  {
    let lines: Vec<_> = std::fs::read_to_string(file.path())
      .expect(&format!(
        "Error reading generated protobuf at {}",
        file.path().display()
      ))
      .lines()
      .filter(|line| !line.contains("clippy"))
      .map(str::to_owned)
      .collect();
    let content = String::from("#![allow(clippy::all)]\n") + &lines.join("\n");
    std::fs::write(file.path(), content).expect(&format!(
      "Error re-writing generated protobuf at {}",
      file.path().display()
    ));
  }

  let listing = gen_dir.read_dir().unwrap();
  let mut pub_mod_stmts = listing
    .filter_map(|d| {
      let dirent = d.unwrap();
      let file_name = dirent.file_name().into_string().unwrap();
      match file_name.trim_right_matches(".rs") {
        "mod" | ".gitignore" => None,
        module_name => Some(format!("pub mod {};", module_name)),
      }
    })
    .collect::<Vec<_>>();
  pub_mod_stmts.sort();
  let contents = format!(
    "\
// This file is generated. Do not edit.
{}
",
    pub_mod_stmts.join("\n")
  );

  File::create(gen_dir.join("mod.rs"))
    .and_then(|mut f| f.write_all(contents.as_bytes()))
    .expect("Failed to write mod.rs")
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
