// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs;
use std::process::{Command, Stdio};
use std::str::from_utf8;

use tempfile::TempDir;

use options::BuildRoot;

pub(crate) fn launch_pantsd() -> (BuildRoot, TempDir) {
  let build_root = BuildRoot::find()
    .expect("Expected test to be run inside the Pants repo but no build root was detected.");
  let pants_subprocessdir = TempDir::new().unwrap();
  let mut cmd = Command::new(build_root.join("pants"));
  cmd
    .current_dir(build_root.as_path())
    .arg("--pants-config-files=[]")
    .arg("--no-pantsrc")
    .arg("--pantsd")
    .arg(format!(
      "--pants-subprocessdir={}",
      pants_subprocessdir.path().display()
    ))
    .arg("-V")
    .stderr(Stdio::inherit());
  let result = cmd
    .output()
    .map_err(|e| format!("Problem running command {cmd:?}: {e}"))
    .unwrap();
  assert_eq!(Some(0), result.status.code());
  assert_eq!(
    fs::read_to_string(
      build_root
        .join("src")
        .join("python")
        .join("pants")
        .join("VERSION")
    )
    .unwrap(),
    from_utf8(result.stdout.as_slice()).unwrap()
  );
  (build_root, pants_subprocessdir)
}
