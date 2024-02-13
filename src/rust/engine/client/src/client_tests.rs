// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::time::SystemTime;

use options::{Args, Env, OptionParser};
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

#[tokio::test]
async fn test_client_fingerprint_mismatch() {
    // Launch `pantsd` with one fingerprint.
    let (build_root, _options_parser, tmpdir) = launch_pantsd();

    // Then connect with a different set of options (but with a matching `pants_subprocessdir`, so
    // that we find the relevant `.pants.d/pids` directory).
    let options_parser = OptionParser::new(
        Args::new(vec![format!(
            "--pants-subprocessdir={}",
            tmpdir.path().display()
        )]),
        Env::new(HashMap::new()),
        None,
        true,
        false,
    )
    .unwrap();
    let error = pantsd::find_pantsd(&build_root, &options_parser)
        .err()
        .unwrap();

    assert!(
        error.contains("Fingerprint mismatched:"),
        "Error was: {error}"
    )
}
