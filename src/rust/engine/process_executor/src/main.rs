extern crate boxfuture;
extern crate clap;
extern crate fs;
extern crate hashing;
extern crate futures;
extern crate process_execution;
extern crate tempdir;

use boxfuture::{BoxFuture, Boxable};
use clap::{App, AppSettings, Arg};
use fs::{StoreFileByDigest, VFS};
use futures::future::Future;
use tempdir::TempDir;
use std::collections::BTreeMap;
use std::iter::Iterator;
use std::process::exit;
use std::sync::Arc;
use std::time::Duration;

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
fn main() {
  let args = App::new("process_executor")
    .arg(
      Arg::with_name("local-store-path")
        .long("local-store-path")
        .takes_value(true)
        .required(true)
        .help("TODO"),
    )
    .arg(
      Arg::with_name("globs")
        .long("globs")
        .takes_value(true)
        .multiple(true)
        .help("TODO"),
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
      Arg::with_name("env")
        .long("env")
        .takes_value(true)
        .multiple(true)
        .help(
          "Environment variables with which the process should be run.",
        ),
    )
    .setting(AppSettings::TrailingVarArg)
    .arg(Arg::with_name("argv").multiple(true).last(true).required(
      true,
    ))
    .get_matches();

  let argv: Vec<String> = args
    .values_of("argv")
    .unwrap()
    .map(|v| v.to_string())
    .collect();
  let env: BTreeMap<String, String> = match args.values_of("env") {
    Some(values) => {
      values
        .map(|v| {
          let mut parts = v.splitn(2, "=");
          (
            parts.next().unwrap().to_string(),
            parts.next().unwrap_or_default().to_string(),
          )
        })
        .collect()
    }
    None => BTreeMap::new(),
  };
  let local_store_path = args.value_of("local-store-path").unwrap();
  let pool = Arc::new(fs::ResettablePool::new("process-executor-".to_owned()));
  let server_arg = args.value_of("server");
  let store = match (server_arg, args.value_of("cas-server")) {
    (Some(_server), Some(cas_server)) => {
      fs::Store::with_remote(
        local_store_path,
        pool.clone(),
        cas_server,
        1,
        10 * 1024 * 1024,
        Duration::from_secs(30),
      )
    }
    (None, None) => fs::Store::local_only(local_store_path, pool.clone()),
    _ => panic!("Must specify either both --server and --cas-server or neither."),
  }.expect("Error making store");

  let posix_fs = Arc::new(fs::PosixFS::new(".", pool, vec![]).unwrap());
  let store_copy = store.clone();
  let input_files = posix_fs
    .expand(
      fs::PathGlobs::create(
        &args
          .values_of("globs")
          .expect("Bad globs")
          .map(|s| s.to_string())
          .collect::<Vec<String>>(),
        &[],
      ).expect("Error creating globs"),
    )
    .map_err(|err| format!("Error expanding globs: {}", err))
    .and_then(move |paths| {
      fs::Snapshot::from_path_stats(
        store_copy.clone(),
        FileSaver {
          store: store_copy,
          posix_fs: posix_fs,
        },
        paths,
      )
    })
    .map(|snapshot| snapshot.digest)
    .wait()
    .expect("Error reading input files");

  let request = process_execution::ExecuteProcessRequest {
    argv,
    env,
    input_files,
  };

  let result = match server_arg {
    Some(address) => {
      process_execution::remote::CommandRunner::new(address, 1, store)
        .run_command_remote(request)
        .wait()
        .expect("Error executing remotely")
    }
    None => {
      let dir = TempDir::new("process-execution").expect("Error making temporary directory");
      store
        .materialize_directory(dir.path().to_owned(), request.input_files)
        .wait()
        .expect("Error materializing directory");
      process_execution::local::run_command_locally(request, dir.path())
        .expect("Error executing locally")
    }
  };
  print!("{}", String::from_utf8(result.stdout).unwrap());
  eprint!("{}", String::from_utf8(result.stderr).unwrap());
  exit(result.exit_code);
}

#[derive(Clone)]
struct FileSaver {
  store: fs::Store,
  posix_fs: Arc<fs::PosixFS>,
}

impl StoreFileByDigest<String> for FileSaver {
  fn store_by_digest(&self, file: &fs::File) -> BoxFuture<hashing::Digest, String> {
    let file_copy = file.clone();
    let store = self.store.clone();
    self
      .posix_fs
      .read_file(&file)
      .map_err(move |err| {
        format!("Error reading file {:?}: {:?}", file_copy, err)
      })
      .and_then(move |content| store.store_file_bytes(content.content, true))
      .to_boxed()
  }
}
