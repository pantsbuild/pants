extern crate bazel_protos;
extern crate bytes;
extern crate digest;
extern crate hashing;
extern crate protobuf;
extern crate sha2;

use bytes::Bytes;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub mod data;
pub mod file;

pub fn owned_string_vec(args: &[&str]) -> Vec<String> {
  args.into_iter().map(|s| s.to_string()).collect()
}

pub fn as_byte_owned_vec(str: &str) -> Vec<u8> {
  Vec::from(str.as_bytes())
}

pub fn as_bytes(str: &str) -> Bytes {
  Bytes::from(str.as_bytes())
}

pub fn make_file(path: &Path, contents: &[u8], mode: u32) {
  let mut file = std::fs::File::create(&path).unwrap();
  file.write(contents).unwrap();
  let mut permissions = std::fs::metadata(path).unwrap().permissions();
  permissions.set_mode(mode);
  file.set_permissions(permissions).unwrap();
}
