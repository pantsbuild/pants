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

use std::fs::File;
use std::io::Write;
use std::path::Path;

use bytes::Bytes;

use fs::RelativePath;

pub mod data;
pub mod file;
pub mod path;

pub fn owned_string_vec(args: &[&str]) -> Vec<String> {
    args.iter().map(<&str>::to_string).collect()
}

pub fn relative_paths<'a>(paths: &'a [&str]) -> impl Iterator<Item = RelativePath> + 'a {
    paths.iter().map(|p| RelativePath::new(p).unwrap())
}

pub fn as_byte_owned_vec(str: &str) -> Vec<u8> {
    Vec::from(str.as_bytes())
}

pub fn as_bytes(str: &str) -> Bytes {
    Bytes::copy_from_slice(str.as_bytes())
}

pub fn make_file(path: &Path, contents: &[u8], mode: u32) {
    let mut file = File::create(path).unwrap();
    file.write_all(contents).unwrap();

    #[cfg(not(target_os = "windows"))]
    {
        use std::os::unix::fs::PermissionsExt;

        let mut permissions = std::fs::metadata(path).unwrap().permissions();
        permissions.set_mode(mode);
        file.set_permissions(permissions).unwrap();
    }
}

pub fn append_to_existing_file(path: &Path, contents: &[u8]) {
    let mut file = std::fs::OpenOptions::new().write(true).open(path).unwrap();
    file.write_all(contents).unwrap();
}
