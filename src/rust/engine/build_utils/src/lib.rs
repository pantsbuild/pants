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
mod build_utils_test {
  use super::BuildRoot;

  use std::path::PathBuf;
  use std::process::Command;

  #[test]
  fn find() {
    let result = Command::new("git")
      .args(&["rev-parse", "--show-toplevel"])
      .output()
      .expect("Expected `git` to be on the `PATH` and this test to be run in a git repository.");

    let root_dir: PathBuf = String::from_utf8(result.stdout)
      .expect("The Pants build root is not a valid UTF-8 path.")
      .trim()
      .into();

    assert_eq!(*BuildRoot::find().unwrap(), root_dir)
  }
}
