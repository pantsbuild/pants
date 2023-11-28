// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

fn main() -> Result<(), Box<dyn std::error::Error>> {
    use prost_build::Config;

    let config = Config::new();

    tonic_build::configure()
        .build_client(true)
        .build_server(true)
        .compile_with_config(config, &["protos/test.proto"], &["protos"])?;

    Ok(())
}
