extern crate build_utils;
extern crate protoc_grpcio;

use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

use build_utils::BuildRoot;

fn main() {
  let build_root = BuildRoot::find().unwrap();
  let thirdpartyprotobuf = build_root.join("3rdparty/protobuf");
  println!(
    "cargo:rerun-if-changed={}",
    thirdpartyprotobuf.to_str().unwrap()
  );

  let gen_dir = PathBuf::from("src/gen");

  // Re-gen if, say, someone does a git clean on the gen dir but not the target dir. This ensures
  // generated sources are available for reading by programmers and tools like rustfmt alike.
  println!("cargo:rerun-if-changed={}", gen_dir.to_str().unwrap());

  protoc_grpcio::compile_grpc_protos(
    &[
      "google/devtools/remoteexecution/v1test/remote_execution.proto",
      "google/bytestream/bytestream.proto",
      "google/rpc/code.proto",
      "google/rpc/error_details.proto",
      "google/rpc/status.proto",
      "google/longrunning/operations.proto",
      "google/protobuf/empty.proto",
    ],
    &[
      thirdpartyprotobuf.join("googleapis"),
      thirdpartyprotobuf.join("standard"),
      thirdpartyprotobuf.join("rust-protobuf"),
    ],
    &gen_dir,
  ).expect("Failed to compile protos!");

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
