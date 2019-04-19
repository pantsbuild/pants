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

use bytes::Bytes;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub mod data;
pub mod file;

pub fn owned_string_vec(args: &[&str]) -> Vec<String> {
  args.iter().map(<&str>::to_string).collect()
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
