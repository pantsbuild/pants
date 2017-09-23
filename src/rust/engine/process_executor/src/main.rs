extern crate process_executor;

use std::env;
use std::process::exit;
use std::collections::BTreeMap;

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
fn main() {
  let (argv, env) = {
    let mut flags: Vec<String> = env::args().skip(1).collect();
    let splitter = flags.iter().position(|x| x == "--");
    let command = {
      if let Some(index) =splitter {
        flags.split_off(index + 1)
      } else {
        flags.drain(..).collect()
      }
    };
    if flags.is_empty() && command.first().unwrap_or(&"".to_string()).starts_with("--") {
      panic!("Must specify -- between flags and command to run");
    }
    flags.pop(); // --

    let mut env = BTreeMap::new();

    for flag in flags {
      if flag.starts_with("--env=") {
        let mut parts = flag["--env=".len()..].splitn(2, "=");
        env.insert(parts.next().unwrap().to_string(), parts.next().unwrap_or_default().to_string());
      } else {
        panic!("Didn't know how to interpret flag {}", flag);
      }
    }
    (command, env)
  };

  let result = process_executor::run_command(process_executor::ExecuteProcessRequest { argv, env }).unwrap();
  print!("{}", String::from_utf8(result.stdout).unwrap());
  eprint!("{}", String::from_utf8(result.stderr).unwrap());
  exit(result.exit_code);
}
