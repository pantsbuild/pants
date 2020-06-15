// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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

use std::env;
use std::io;
use std::ops::Deref;
use std::path::PathBuf;

pub struct BuildRoot(PathBuf);

impl Deref for BuildRoot {
  type Target = PathBuf;

  fn deref(&self) -> &PathBuf {
    &self.0
  }
}

impl BuildRoot {
  /// Finds the Pants build root containing the current working directory.
  ///
  /// # Errors
  ///
  /// If finding the current working directory fails or the search for the Pants build root finds
  /// none.
  ///
  /// # Examples
  ///
  /// ```
  /// use build_utils::BuildRoot;
  ///
  /// let build_root = BuildRoot::find().unwrap();
  ///
  /// // Deref's to a PathBuf
  /// let pants = build_root.join("pants");
  /// assert!(pants.exists());
  /// ```
  pub fn find() -> io::Result<BuildRoot> {
    let current_dir = env::current_dir()?;
    let mut here = current_dir.as_path();
    loop {
      if here.join("pants").exists() {
        return Ok(BuildRoot(here.to_path_buf()));
      } else if let Some(parent) = here.parent() {
        here = parent;
      } else {
        return Err(io::Error::new(
          io::ErrorKind::NotFound,
          format!("Failed to find build root starting from {:?}", current_dir),
        ));
      }
    }
  }
}

#[cfg(test)]
mod tests;
