// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use clap::Parser;
use fs::DirectoryDigest;
use hashing::{Digest, Fingerprint};
use sandboxer::SandboxerClient;
use std::io::Write;
use std::path::PathBuf;

// A cli client useful for debugging the sandboxer, but not used by production code.

#[derive(Parser)]
struct Opt {
    #[arg(long)]
    socket_path: PathBuf,

    #[arg(long)]
    destination: PathBuf,

    #[arg(long)]
    destination_root: PathBuf,

    #[arg(long)]
    digest: Fingerprint,

    #[arg(long)]
    digest_length: usize,

    #[arg(long)]
    mutable_paths: Vec<String>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::builder()
        .format(|buf, record| {
            writeln!(
                buf,
                "{} [{}] {}",
                buf.timestamp_millis(),
                record.level(),
                record.args()
            )
        })
        .init();

    let args = Opt::parse();
    let mut sandboxer = SandboxerClient::connect(&args.socket_path).await?;
    let digest = Digest::new(args.digest, args.digest_length);
    let dir_digest = DirectoryDigest::from_persisted_digest(digest);
    sandboxer
        .materialize_directory(
            &args.destination,
            &args.destination_root,
            &dir_digest,
            &args.mutable_paths,
        )
        .await?;
    Ok(())
}
