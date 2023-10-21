// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::pantsd_testing::launch_pantsd;
use crate::{execute_command, pantsd, ConnectionSettings};
use std::time::SystemTime;

#[tokio::test]
async fn test_client() {
    let (build_root, pants_subprocessdir) = launch_pantsd();

    let port = pantsd::probe(&build_root, pants_subprocessdir.path()).unwrap();
    let exit_code = execute_command(
        SystemTime::now(),
        ConnectionSettings::new(port),
        std::env::vars().collect(),
        ["pants", "-V"].iter().map(ToString::to_string).collect(),
    )
    .await
    .unwrap();
    assert_eq!(0, exit_code)
}
