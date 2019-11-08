use crate::BuildRoot;

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
