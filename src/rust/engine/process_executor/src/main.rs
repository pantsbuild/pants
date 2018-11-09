// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

extern crate clap;
extern crate env_logger;
extern crate fs;
extern crate futures;
extern crate hashing;
extern crate process_execution;

use clap::{value_t, App, AppSettings, Arg};
use futures::future::Future;
use hashing::{Digest, Fingerprint};
use std::collections::{BTreeMap, BTreeSet};
use std::iter::Iterator;
use std::path::PathBuf;
use std::process::exit;
use std::sync::Arc;
use std::time::Duration;

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value --input-digest=abc123 --input-digest-length=80
///    -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
fn main() {
  env_logger::init();

  let args = App::new("process_executor")
    .arg(
      Arg::with_name("work-dir")
        .long("work-dir")
        .takes_value(true)
        .help("Path to workdir"),
    )
    .arg(
      Arg::with_name("local-store-path")
        .long("local-store-path")
        .takes_value(true)
        .help("Path to lmdb directory used for local file storage"),
    )
    .arg(
      Arg::with_name("input-digest")
        .long("input-digest")
        .takes_value(true)
        .required(true)
        .help("Fingerprint (hex string) of the digest to use as the input file tree."),
    )
    .arg(
      Arg::with_name("input-digest-length")
        .long("input-digest-length")
        .takes_value(true)
        .required(true)
        .help("Length of the proto-bytes whose digest to use as the input file tree."),
    )
    .arg(
      Arg::with_name("server")
        .long("server")
        .takes_value(true)
        .help(
          "The host:port of the gRPC server to connect to. Forces remote execution. \
           If unspecified, local execution will be performed.",
        ),
    )
      .arg(
        Arg::with_name("execution-root-ca-cert-file")
            .help("Path to file containing root certificate authority certificates for the execution server. If not set, TLS will not be used when connecting to the execution server.")
            .takes_value(true)
            .long("execution-root-ca-cert-file")
            .required(false)
      )
      .arg(
        Arg::with_name("execution-oauth-bearer-token-path")
            .help("Path to file containing oauth bearer token for communication with the execution server. If not set, no authorization will be provided to remote servers.")
            .takes_value(true)
            .long("execution-oauth-bearer-token-path")
            .required(false)
      )
      .arg(
      Arg::with_name("cas-server")
        .long("cas-server")
        .takes_value(true)
        .help("The host:port of the gRPC CAS server to connect to."),
    )
      .arg(
        Arg::with_name("cas-root-ca-cert-file")
            .help("Path to file containing root certificate authority certificates for the CAS server. If not set, TLS will not be used when connecting to the CAS server.")
            .takes_value(true)
            .long("cas-root-ca-cert-file")
            .required(false)
      )
      .arg(
        Arg::with_name("cas-oauth-bearer-token-path")
            .help("Path to file containing oauth bearer token for communication with the CAS server. If not set, no authorization will be provided to remote servers.")
            .takes_value(true)
            .long("cas-oauth-bearer-token-path")
            .required(false)
      )
      .arg(Arg::with_name("remote-instance-name")
          .takes_value(true)
          .long("remote-instance-name")
          .required(false))
      .arg(
        Arg::with_name("upload-chunk-bytes")
            .help("Number of bytes to include per-chunk when uploading bytes. grpc imposes a hard message-size limit of around 4MB.")
            .takes_value(true)
            .long("chunk-bytes")
            .required(false)
            .default_value("3145728") // 3MB
      )
    .arg(
      Arg::with_name("env")
        .long("env")
        .takes_value(true)
        .multiple(true)
        .help("Environment variables with which the process should be run."),
    )
      .arg(
        Arg::with_name("jdk")
            .long("jdk")
            .takes_value(true)
            .required(false)
            .help("Symlink a JDK from .jdk in the working directory. For local execution, symlinks to the value of this flag. For remote execution, just requests that some JDK is symlinked if this flag has any value. https://github.com/pantsbuild/pants/issues/6416 will make this less weird in the future.")
      )
    .setting(AppSettings::TrailingVarArg)
    .arg(
      Arg::with_name("argv")
        .multiple(true)
        .last(true)
        .required(true),
    )
    .get_matches();

  let argv: Vec<String> = args
    .values_of("argv")
    .unwrap()
    .map(|v| v.to_string())
    .collect();
  let env: BTreeMap<String, String> = match args.values_of("env") {
    Some(values) => values
      .map(|v| {
        let mut parts = v.splitn(2, '=');
        (
          parts.next().unwrap().to_string(),
          parts.next().unwrap_or_default().to_string(),
        )
      }).collect(),
    None => BTreeMap::new(),
  };
  let work_dir = args
    .value_of("work-dir")
    .map(PathBuf::from)
    .unwrap_or_else(std::env::temp_dir);
  let local_store_path = args
    .value_of("local-store-path")
    .map(PathBuf::from)
    .unwrap_or_else(fs::Store::default_path);
  let pool = Arc::new(fs::ResettablePool::new("process-executor-".to_owned()));
  let server_arg = args.value_of("server");
  let remote_instance_arg = args.value_of("remote-instance-name").map(str::to_owned);
  let store = match (server_arg, args.value_of("cas-server")) {
    (Some(_server), Some(cas_server)) => {
      let chunk_size =
        value_t!(args.value_of("upload-chunk-bytes"), usize).expect("Bad upload-chunk-bytes flag");

      let root_ca_certs = if let Some(path) = args.value_of("cas-root-ca-cert-file") {
        Some(std::fs::read(path).expect("Error reading root CA certs file"))
      } else {
        None
      };

      let oauth_bearer_token = if let Some(path) = args.value_of("cas-oauth-bearer-token-path") {
        Some(std::fs::read_to_string(path).expect("Error reading oauth bearer token file"))
      } else {
        None
      };

      fs::Store::with_remote(
        local_store_path,
        pool.clone(),
        cas_server,
        remote_instance_arg.clone(),
        root_ca_certs,
        oauth_bearer_token,
        1,
        chunk_size,
        Duration::from_secs(30),
      )
    }
    (None, None) => fs::Store::local_only(local_store_path, pool.clone()),
    _ => panic!("Must specify either both --server and --cas-server or neither."),
  }.expect("Error making store");

  let input_files = {
    let fingerprint = Fingerprint::from_hex_string(args.value_of("input-digest").unwrap())
      .expect("Bad input-digest");
    let length = args
      .value_of("input-digest-length")
      .unwrap()
      .parse::<usize>()
      .expect("input-digest-length must be a non-negative number");
    Digest(fingerprint, length)
  };

  let request = process_execution::ExecuteProcessRequest {
    argv,
    env,
    input_files,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Duration::new(15 * 60, 0),
    description: "process_executor".to_string(),
    jdk_home: args.value_of("jdk").map(PathBuf::from),
  };

  let runner: Box<process_execution::CommandRunner> = match server_arg {
    Some(address) => {
      let root_ca_certs = if let Some(path) = args.value_of("execution-root-ca-cert-file") {
        Some(std::fs::read(path).expect("Error reading root CA certs file"))
      } else {
        None
      };

      let oauth_bearer_token =
        if let Some(path) = args.value_of("execution-oauth-bearer-token-path") {
          Some(std::fs::read_to_string(path).expect("Error reading oauth bearer token file"))
        } else {
          None
        };

      Box::new(process_execution::remote::CommandRunner::new(
        address,
        remote_instance_arg,
        root_ca_certs,
        oauth_bearer_token,
        1,
        store,
      ))
    }
    None => Box::new(process_execution::local::CommandRunner::new(
      store, pool, work_dir, true,
    )),
  };

  let result = runner.run(request).wait().expect("Error executing");

  print!("{}", String::from_utf8(result.stdout.to_vec()).unwrap());
  eprint!("{}", String::from_utf8(result.stderr.to_vec()).unwrap());
  exit(result.exit_code);
}
