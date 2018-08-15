#[macro_use]
extern crate clap;
extern crate env_logger;
extern crate fs;
extern crate futures;
extern crate hashing;
extern crate process_execution;

use clap::{App, AppSettings, Arg};
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
        .required(true)
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
      Arg::with_name("cas-server")
        .long("cas-server")
        .takes_value(true)
        .help("The host:port of the gRPC CAS server to connect to."),
    )
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
      })
      .collect(),
    None => BTreeMap::new(),
  };
  let work_dir = args
    .value_of("work-dir")
    .map(PathBuf::from)
    .unwrap_or_else(std::env::temp_dir);
  let local_store_path = args.value_of("local-store-path").unwrap();
  let pool = Arc::new(fs::ResettablePool::new("process-executor-".to_owned()));
  let server_arg = args.value_of("server");
  let store = match (server_arg, args.value_of("cas-server")) {
    (Some(_server), Some(cas_server)) => {
      let chunk_size =
        value_t!(args.value_of("upload-chunk-bytes"), usize).expect("Bad upload-chunk-bytes flag");

      fs::Store::with_remote(
        local_store_path,
        pool.clone(),
        cas_server.to_owned(),
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
    jdk_home: None,
  };

  let runner: Box<process_execution::CommandRunner> = match server_arg {
    Some(address) => Box::new(process_execution::remote::CommandRunner::new(
      address.to_owned(),
      1,
      store,
    )),
    None => Box::new(process_execution::local::CommandRunner::new(
      store, pool, work_dir, true,
    )),
  };

  let result = runner.run(request).wait().expect("Error executing");

  print!("{}", String::from_utf8(result.stdout.to_vec()).unwrap());
  eprint!("{}", String::from_utf8(result.stderr.to_vec()).unwrap());
  exit(result.exit_code);
}
