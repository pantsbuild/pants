// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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
#![type_length_limit = "1257309"]

use std::collections::{BTreeMap, BTreeSet};
use std::iter::{FromIterator, Iterator};
use std::path::PathBuf;
use std::process::exit;
use std::time::Duration;

use fs::RelativePath;
use futures::compat::Future01CompatExt;
use hashing::{Digest, Fingerprint};
use process_execution::{Context, NamedCaches, Platform, ProcessMetadata};
use store::{BackoffConfig, Store};
use structopt::StructOpt;
use workunit_store::WorkunitStore;

#[derive(StructOpt)]
#[structopt(
  name = "process_executor",
  raw(setting = "structopt::clap::AppSettings::TrailingVarArg")
)]
struct Opt {
  /// Fingerprint (hex string) of the digest to use as the input file tree.
  #[structopt(long)]
  input_digest: Fingerprint,

  /// Length of the proto-bytes whose digest to use as the input file tree.
  #[structopt(long)]
  input_digest_length: usize,

  /// Extra platform properties to set on the execution request.
  #[structopt(long)]
  extra_platform_property: Vec<String>,

  /// Extra header to pass on remote execution request.
  #[structopt(long)]
  header: Vec<String>,

  /// Environment variables with which the process should be run.
  #[structopt(long)]
  env: Vec<String>,

  /// Symlink a JDK from .jdk in the working directory.
  /// For local execution, symlinks to the value of this flag.
  /// For remote execution, just requests that some JDK is symlinked if this flag has any value.
  /// https://github.com/pantsbuild/pants/issues/6416 will make this less weird in the future.
  #[structopt(long)]
  jdk: Option<PathBuf>,

  /// Path to file that is considered to be output.
  #[structopt(long)]
  output_file_path: Vec<PathBuf>,

  /// Path to directory that is considered to be output.
  #[structopt(long)]
  output_directory_path: Vec<PathBuf>,

  /// The name of a directory (which may or may not exist), where the output tree will be materialized.
  #[structopt(long)]
  materialize_output_to: Option<PathBuf>,

  /// Path to workdir.
  #[structopt(long)]
  work_dir: Option<PathBuf>,

  ///Path to lmdb directory used for local file storage.
  #[structopt(long)]
  local_store_path: Option<PathBuf>,

  /// Path to a directory to be used for named caches.
  #[structopt(long)]
  named_cache_path: Option<PathBuf>,

  /// Path to execute the binary at relative to its input digest root.
  #[structopt(long)]
  working_directory: Option<PathBuf>,

  #[structopt(long)]
  remote_instance_name: Option<String>,
  #[structopt(long)]
  cache_key_gen_version: Option<String>,

  /// The host:port of the gRPC server to connect to. Forces remote execution.
  /// If unspecified, local execution will be performed.
  #[structopt(long)]
  server: Option<String>,

  /// Path to file containing root certificate authority certificates for the execution server.
  /// If not set, TLS will not be used when connecting to the execution server.
  #[structopt(long)]
  execution_root_ca_cert_file: Option<PathBuf>,

  /// Path to file containing oauth bearer token for communication with the execution server.
  /// If not set, no authorization will be provided to remote servers.
  #[structopt(long)]
  execution_oauth_bearer_token_path: Option<PathBuf>,

  /// The host:port of the gRPC CAS server to connect to.
  #[structopt(long)]
  cas_server: Option<String>,

  /// Path to file containing root certificate authority certificates for the CAS server.
  /// If not set, TLS will not be used when connecting to the CAS server.
  #[structopt(long)]
  cas_root_ca_cert_file: Option<PathBuf>,

  /// Path to file containing oauth bearer token for communication with the CAS server.
  /// If not set, no authorization will be provided to remote servers.
  #[structopt(long)]
  cas_oauth_bearer_token_path: Option<PathBuf>,

  /// Number of bytes to include per-chunk when uploading bytes.
  /// grpc imposes a hard message-size limit of around 4MB.
  #[structopt(long, default_value = "3145728")]
  upload_chunk_bytes: usize,

  /// Number of concurrent servers to allow connections to.
  #[structopt(long, default_value = "3")]
  store_connection_limit: usize,

  /// Whether or not to enable running the process through a Nailgun server.
  /// This will likely start a new Nailgun server as a side effect.
  #[structopt(long)]
  use_nailgun: bool,

  /// Overall timeout in seconds for each request from time of submission.
  #[structopt(long, default_value = "600")]
  overall_deadline_secs: u64,

  #[structopt(last = true)]
  argv: Vec<String>,
}

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value --input-digest=abc123 --input-digest-length=80
///    -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
#[tokio::main]
async fn main() {
  env_logger::init();
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let args = Opt::from_args();

  let output_files = args
    .output_file_path
    .iter()
    .map(RelativePath::new)
    .collect::<Result<BTreeSet<_>, _>>()
    .unwrap();
  let output_directories = args
    .output_directory_path
    .iter()
    .map(RelativePath::new)
    .collect::<Result<BTreeSet<_>, _>>()
    .unwrap();
  let headers: BTreeMap<String, String> = collection_from_keyvalues(args.header.iter());

  let executor = task_executor::Executor::new();

  let local_store_path = args.local_store_path.unwrap_or_else(Store::default_path);

  let store = match (args.server.as_ref(), args.cas_server) {
    (Some(_server), Some(cas_server)) => {
      let root_ca_certs = if let Some(path) = args.cas_root_ca_cert_file {
        Some(std::fs::read(path).expect("Error reading root CA certs file"))
      } else {
        None
      };

      let oauth_bearer_token = if let Some(path) = args.cas_oauth_bearer_token_path {
        Some(std::fs::read_to_string(path).expect("Error reading oauth bearer token file"))
      } else {
        None
      };

      Store::with_remote(
        executor.clone(),
        local_store_path,
        vec![cas_server],
        args.remote_instance_name.clone(),
        root_ca_certs,
        oauth_bearer_token,
        1,
        args.upload_chunk_bytes,
        Duration::from_secs(30),
        // TODO: Take a command line arg.
        BackoffConfig::new(Duration::from_secs(1), 1.2, Duration::from_secs(20)).unwrap(),
        3,
        args.store_connection_limit,
      )
    }
    (None, None) => Store::local_only(executor.clone(), local_store_path),
    _ => panic!("Must specify either both --server and --cas-server or neither."),
  }
  .expect("Error making store");

  let input_files = Digest(args.input_digest, args.input_digest_length);

  let working_directory = args
    .working_directory
    .map(|path| RelativePath::new(path).expect("working-directory must be a relative path"));

  let request = process_execution::Process {
    argv: args.argv,
    env: collection_from_keyvalues(args.env.iter()),
    working_directory,
    input_files,
    output_files,
    output_directories,
    timeout: Some(Duration::new(15 * 60, 0)),
    description: "process_executor".to_string(),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: args.jdk,
    platform_constraint: None,
    is_nailgunnable: args.use_nailgun,
    execution_slot_variable: None,
    cache_failures: false,
  };

  let runner: Box<dyn process_execution::CommandRunner> = match args.server {
    Some(address) => {
      let root_ca_certs = if let Some(path) = args.execution_root_ca_cert_file {
        Some(std::fs::read(path).expect("Error reading root CA certs file"))
      } else {
        None
      };

      let oauth_bearer_token = if let Some(path) = args.execution_oauth_bearer_token_path {
        Some(std::fs::read_to_string(path).expect("Error reading oauth bearer token file"))
      } else {
        None
      };

      let command_runner_box: Box<dyn process_execution::CommandRunner> = {
        Box::new(
          process_execution::remote::CommandRunner::new(
            &address,
            vec![address.to_owned()],
            ProcessMetadata {
              instance_name: args.remote_instance_name,
              cache_key_gen_version: args.cache_key_gen_version,
              platform_properties: collection_from_keyvalues(args.extra_platform_property.iter()),
            },
            root_ca_certs,
            oauth_bearer_token,
            headers,
            store.clone(),
            Platform::Linux,
            Duration::from_secs(args.overall_deadline_secs),
            Duration::from_millis(100),
          )
          .expect("Failed to make command runner"),
        )
      };

      command_runner_box
    }
    None => Box::new(process_execution::local::CommandRunner::new(
      store.clone(),
      executor,
      args.work_dir.unwrap_or_else(std::env::temp_dir),
      NamedCaches::new(
        args
          .named_cache_path
          .unwrap_or_else(NamedCaches::default_path),
      ),
      true,
    )) as Box<dyn process_execution::CommandRunner>,
  };

  let result = runner
    .run(request.into(), Context::default())
    .await
    .expect("Error executing");

  if let Some(output) = args.materialize_output_to {
    store
      .materialize_directory(output, result.output_directory)
      .compat()
      .await
      .unwrap();
  }

  let stdout: Vec<u8> = store
    .load_file_bytes_with(result.stdout_digest, |bytes| bytes.to_vec())
    .await
    .unwrap()
    .unwrap()
    .0;

  let stderr: Vec<u8> = store
    .load_file_bytes_with(result.stderr_digest, |bytes| bytes.to_vec())
    .await
    .unwrap()
    .unwrap()
    .0;

  print!("{}", String::from_utf8(stdout).unwrap());
  eprint!("{}", String::from_utf8(stderr).unwrap());
  exit(result.exit_code);
}

fn collection_from_keyvalues<Str, It, Col>(keyvalues: It) -> Col
where
  Str: AsRef<str>,
  It: Iterator<Item = Str>,
  Col: FromIterator<(String, String)>,
{
  keyvalues
    .map(|kv| {
      let mut parts = kv.as_ref().splitn(2, '=');
      (
        parts.next().unwrap().to_string(),
        parts.next().unwrap_or_default().to_string(),
      )
    })
    .collect()
}
