// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use process_execution::sandboxer::SandboxerService;
use std::path::PathBuf;
use std::{env, process};

// The entry point for the sandboxer process.

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::init();

    let mut args_iter = env::args();
    let bin_name = args_iter.next().unwrap();
    let args: Vec<String> = args_iter.collect();
    if args.len() != 1 {
        eprintln!("Usage: {} <socket path>", bin_name);
        process::exit(1);
    }
    let socket_path = PathBuf::from(args[0].to_string());

    SandboxerService::new(socket_path).serve().await
}
