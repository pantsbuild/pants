extern crate clap;
extern crate process_execution;

use clap::{App, AppSettings, Arg};
use std::process::exit;
use std::collections::BTreeMap;

use std::iter::Iterator;

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
fn main() {
  let args = App::new("process_executor")
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
  let env: BTreeMap<String, String> = args
    .values_of("env")
    .unwrap()
    .map(|v| {
      let mut parts = v.splitn(2, "=");
      (
        parts.next().unwrap().to_string(),
        parts.next().unwrap_or_default().to_string(),
      )
    })
    .collect();
  let server = args.value_of("server");

  let request = process_execution::ExecuteProcessRequest { argv, env };
  let result = match server {
    Some(addr) => process_execution::remote::run_command_remote(addr, request).unwrap(),
    None => process_execution::local::run_command_locally(request).unwrap(),
  };
  print!("{}", String::from_utf8(result.stdout).unwrap());
  eprint!("{}", String::from_utf8(result.stderr).unwrap());
  exit(result.exit_code);
}
