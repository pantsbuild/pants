extern crate build_utils;
extern crate protoc_grpcio;

use std::env;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

use build_utils::{BuildRoot, ExecutionResult};

struct BinarySpec<'a> {
  util_name: &'a str,
  version: &'a str,
  filename: &'a str,
}

struct DownloadBinary<'a> {
  download_binary: PathBuf,
  host: &'a str,
}

impl<'a> DownloadBinary<'a> {
  fn from<'f>(build_root: BuildRoot, host: &'f str) -> DownloadBinary<'f> {
    DownloadBinary {
      download_binary: build_root.join("build-support/bin/download_binary.sh"),
      host,
    }
  }

  fn fetch(&self, binary: &BinarySpec) -> ExecutionResult<PathBuf> {
    let binary_path: PathBuf = build_utils::execute(
      &self.download_binary,
      &[self.host, binary.util_name, binary.version, binary.filename],
    )?;
    Ok(binary_path)
  }
}

static PROTOC: BinarySpec = BinarySpec {
  util_name: "protobuf",
  version: "3.4.1",
  filename: "protoc",
};

fn main() {
  let build_root = BuildRoot::find().unwrap();
  let thirdpartyprotobuf = build_root.join("3rdparty/protobuf");
  println!(
    "cargo:rerun-if-changed={}",
    thirdpartyprotobuf.to_str().unwrap()
  );

  let gen_dir = PathBuf::from("src/gen");

  let download_binary = DownloadBinary::from(build_root, "binaries.pantsbuild.org");
  let protoc = download_binary.fetch(&PROTOC).unwrap();
  env::set_var("PATH", protoc.parent().unwrap());

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

  let mut module = File::create(gen_dir.join("mod.rs")).unwrap();
  module.write_all(contents.as_bytes()).unwrap();
}
