// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::time::SystemTime;

use pantsd::pantsd_testing::launch_pantsd;

use crate::execute_command;

#[tokio::test]
async fn test_client() {
  let (build_root, options_parser, _tmpdir) = launch_pantsd();

  let connection_settings = pantsd::find_pantsd(&build_root, &options_parser).unwrap();
  let exit_code = execute_command(
    SystemTime::now(),
    connection_settings,
    std::env::vars().collect(),
    ["pants", "-V"].iter().map(ToString::to_string).collect(),
  )
  .await
  .unwrap();
  assert_eq!(0, exit_code)
}
