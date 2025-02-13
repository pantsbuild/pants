// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use process_execution::sandboxer::SandboxerClient;
use std::env;
use std::path::PathBuf;
use std::process;

// A cli client useful for debugging the sandboxer, but not used by production code.

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args_iter = env::args();
    let bin_name = args_iter.next().unwrap();
    let args: Vec<String> = args_iter.collect();
    if args.len() != 3 {
        eprintln!("Usage: {} <socket_path> <src> <dst>", bin_name);
        process::exit(1);
    }

    let socket_path = PathBuf::from(args[0].to_string());
    let src = PathBuf::from(args[1].to_string());
    let dst = PathBuf::from(args[2].to_string());

    let mut sandboxer = SandboxerClient::connect(&socket_path).await?;
    let response = sandboxer.copy_local_file(&src, &dst).await?;
    println!("{}", response);
    Ok(())
}
