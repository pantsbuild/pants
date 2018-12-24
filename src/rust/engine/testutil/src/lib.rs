// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(len_without_is_empty, redundant_field_names)
)]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

use bazel_protos;
use bytes;

use hashing;

use sha2;

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
  file.write_all(contents).unwrap();
  let mut permissions = std::fs::metadata(path).unwrap().permissions();
  permissions.set_mode(mode);
  file.set_permissions(permissions).unwrap();
}
