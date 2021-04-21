// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs;
use std::net::TcpStream;
use std::process::{Command, Stdio};
use std::str::from_utf8;

use tempdir::TempDir;

use crate::build_root::BuildRoot;
use crate::pantsd;

fn launch_pantsd() -> (BuildRoot, TempDir) {
  let build_root = BuildRoot::find()
    .expect("Expected test to be run inside the Pants repo but no build root was detected.");
  let pants_subprocessdir = TempDir::new("pants_subproccessdir").unwrap();
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
    .map_err(|e| {
      format!(
        "Problem running command {command:?}: {err}",
        command = cmd,
        err = e
      )
    })
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

fn assert_connect(port: u16) {
  assert!(
    port >= 1024,
    "Pantsd should never be running on a privileged port."
  );

  let stream = TcpStream::connect(("0.0.0.0", port)).unwrap();
  assert_eq!(port, stream.peer_addr().unwrap().port());
}

#[test]
fn test_address_integration() {
  let (_, pants_subprocessdir) = launch_pantsd();

  let pantsd_metadata = pantsd::Metadata::mount(&pants_subprocessdir).unwrap();
  let port = pantsd_metadata.port().unwrap();
  assert_connect(port);
}

#[test]
fn test_probe() {
  let (build_root, pants_subprocessdir) = launch_pantsd();

  let port = pantsd::probe(&build_root, pants_subprocessdir.path()).unwrap();
  assert_connect(port);
}
