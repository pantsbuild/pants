// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::net::TcpStream;

use crate::pantsd_testing::launch_pantsd;

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
  let (_, _, pants_subprocessdir) = launch_pantsd();

  let pantsd_metadata = crate::Metadata::mount(&pants_subprocessdir).unwrap();
  let port = pantsd_metadata.port().unwrap();
  assert_connect(port);
}

#[test]
fn test_find_pantsd() {
  let (build_root, options_parser, _tmpdir) = launch_pantsd();

  let connection_settings = crate::find_pantsd(&build_root, &options_parser).unwrap();
  assert_connect(connection_settings.port);
}
