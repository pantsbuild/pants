// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use clap::{Parser, command};
use log::info;
use sandboxer::SandboxerService;
use std::io::Write;
use std::path::PathBuf;
use store::StoreCliOpt;

#[derive(Debug, Parser)]
#[command(name = "sandboxer")]
struct Opt {
    #[arg(long)]
    socket_path: PathBuf,

    #[command(flatten)]
    store_options: StoreCliOpt,
}

// The entry point for the sandboxer process.
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Add the PID to each log line, to make it clear when a sandboxer process has restarted.
    env_logger::builder()
        .format(|buf, record| {
            writeln!(
                buf,
                "{} {} [{}] {}",
                std::process::id(),
                buf.timestamp_millis(),
                record.level(),
                record.args()
            )
        })
        .init();

    let args = Opt::parse();
    info!(
        "Starting up sandboxer with RUST_LOG={} and these options: {:#?}",
        std::env::var("RUST_LOG").unwrap_or("".into()),
        args
    );
    SandboxerService::new(args.socket_path, args.store_options)
        .serve()
        .await
}
