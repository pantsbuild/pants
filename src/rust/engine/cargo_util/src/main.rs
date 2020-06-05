// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]
// We only use unsafe pointer dereferences in our no_mangle exposed API, but it is nicer to list
// just the one minor call as unsafe, than to mark the whole function as unsafe which may hide
// other unsafeness.
#![allow(clippy::not_unsafe_ptr_arg_deref)]

pub mod cargo_fetcher;
#[cfg(test)]
mod cargo_fetcher_tests;

use sharded_lmdb::ShardedLmdb;
use store::Store;

use clap::{App, Arg, SubCommand};
use tokio::runtime::Handle;

use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const MEGABYTES: usize = 1024 * 1024;
const GIGABYTES: usize = MEGABYTES * 1024;
const LEASE_DURATION: Duration = Duration::from_secs(100000);

#[tokio::main]
async fn main() -> Result<(), cargo_fetcher::CargoFetcherError> {
  env_logger::init();

  let default_store_path = format!("{}", Store::default_path().display());

  let arg_match = App::new("cargo_fetcher")
    .arg(
      Arg::with_name("local_store_dir")
        .required(false)
        .takes_value(true)
        .default_value(&default_store_path)
        .help("???"),
    )
    .subcommand(
      SubCommand::with_name("fetch").about("???").arg(
        Arg::with_name("cargo_lockfile")
          .required(true)
          .takes_value(true)
          .help("???"),
      ),
    )
    .get_matches();

  let local_store_dir = arg_match
    .value_of("local_store_dir")
    .map(PathBuf::from)
    .unwrap();

  let runtime = task_executor::Executor::new(Handle::current());
  let store = Store::local_only(runtime.clone(), &local_store_dir)?;

  match arg_match.subcommand() {
    ("fetch", Some(arg_match)) => {
      let cargo_lockfile = arg_match
        .value_of("cargo_lockfile")
        .map(PathBuf::from)
        .unwrap();

      let cargo_krate_dir = local_store_dir.join("cargo_crate_data");
      fs::create_dir_all(&cargo_krate_dir)?;
      let cargo_krate_lookup = ShardedLmdb::new(
        cargo_krate_dir,
        5 * MEGABYTES,
        runtime.clone(),
        LEASE_DURATION,
      )
      .map_err(|err| {
        format!(
          "Could not initialize store for cargo krate lookup: {:?}",
          err
        )
      })?;

      let cargo_packages_dir = local_store_dir.join("cargo_packages");
      fs::create_dir_all(&cargo_packages_dir)?;
      let cargo_krate_data = ShardedLmdb::new(
        cargo_packages_dir,
        5 * GIGABYTES,
        runtime.clone(),
        LEASE_DURATION,
      )
      .map_err(|err| format!("Could not initialize store for cargo krate data: {:?}", err))?;

      let cargo_krate_digest_dir = local_store_dir.join("cargo_krate_digest_mapping");
      fs::create_dir_all(&cargo_krate_digest_dir)?;
      let cargo_krate_digest_mapping = ShardedLmdb::new(
        cargo_krate_digest_dir,
        5 * MEGABYTES,
        runtime.clone(),
        LEASE_DURATION,
      )
      .map_err(|err| {
        format!(
          "Could not initialize store for cargo krate digest mapping: {:?}",
          err
        )
      })?;

      let cargo_fetch_dir = local_store_dir.join("cargo_fetch_cache");
      fs::create_dir_all(&cargo_fetch_dir)?;
      let cargo_fetch_cache = ShardedLmdb::new(
        cargo_fetch_dir,
        5 * GIGABYTES,
        runtime.clone(),
        LEASE_DURATION,
      )
      .map_err(|err| {
        format!(
          "Could not initialize store for cargo fetch cache: {:?}",
          err
        )
      })?;

      let cargo_download_dir = local_store_dir.join("cargo_download_dir");
      fs::create_dir_all(&cargo_download_dir)?;
      let cargo_fetcher = cargo_fetcher::CargoPackageFetcher {
        krate_lookup: cargo_krate_lookup,
        krate_data: cargo_krate_data,
        krate_digest_mapping: cargo_krate_digest_mapping,
        fetch_cache: cargo_fetch_cache,
        store: store.clone(),
        executor: runtime.clone(),
        download_dir: cargo_download_dir,
        timeout: Duration::from_secs(10),
      };

      let metadata_contents = fs::read_to_string(&cargo_lockfile).map_err(|err| {
        format!(
          "failed to read cargo lockfile {:?}: {:?}",
          &cargo_lockfile, err
        )
      })?;

      let fetch_result = cargo_fetcher
        .fetch_packages_from_lockfile(&metadata_contents)
        .await?;
      println!("{}", fetch_result.to_json()?);
    }
    x => unimplemented!("unrecognized command {:?}", x),
  }
  Ok(())
}
