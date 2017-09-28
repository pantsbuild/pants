use std::io::Error;
use std::collections::BTreeMap;
use std::process::Command;

///
/// A process to be executed.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ExecuteProcessRequest {
  ///
  /// The arguments to execute.
  ///
  /// The first argument should be an absolute or relative path to the binary to execute.
  ///
  /// No PATH lookup will be performed unless a PATH environment variable is specified.
  ///
  /// No shell expansion will take place.
  ///
  pub argv: Vec<String>,
  ///
  /// The environment variables to set for the execution.
  ///
  /// No other environment variables will be set (except possibly for an empty PATH variable).
  ///
  pub env: BTreeMap<String, String>,
}

///
/// The result of running a process.
///
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecuteProcessResult {
  pub stdout: Vec<u8>,
  pub stderr: Vec<u8>,
  pub exit_code: i32,
}

///
/// Runs a command.
///
pub fn run_command(req: ExecuteProcessRequest) -> Result<ExecuteProcessResult, Error> {
  Command::new(&req.argv[0])
    .args(&req.argv[1..])
    .env_clear()
    // It would be really nice not to have to manually set PATH but this is sadly the only way
    // to stop automatic PATH searching.
    .env("PATH", "")
    .envs(req.env)
    .output()
    .map(|output| ExecuteProcessResult {
      stdout: output.stdout,
      stderr: output.stderr,
      exit_code: output.status.code().unwrap(),
    })
}

#[cfg(test)]
mod tests {
  use super::{ExecuteProcessRequest, ExecuteProcessResult, run_command};
  use std::collections::BTreeMap;

  #[test]
  #[cfg(unix)]
  fn stdout() {
    let result = run_command(ExecuteProcessRequest {
      argv: make_argv(&["/bin/echo", "-n", "foo"]),
      env: BTreeMap::new(),
    });

    assert_eq!(result.unwrap(), ExecuteProcessResult {
      stdout: make_byte_vec("foo"),
      stderr: make_byte_vec(""),
      exit_code: 0,
    })
  }

  #[test]
  #[cfg(unix)]
  fn stdout_and_stderr_and_exit_code() {
    let result = run_command(ExecuteProcessRequest {
      argv: make_argv(&["/bin/bash", "-c", "echo -n foo ; echo >&2 -n bar ; exit 1"]),
      env: BTreeMap::new(),
    });

    assert_eq!(result.unwrap(), ExecuteProcessResult {
      stdout: make_byte_vec("foo"),
      stderr: make_byte_vec("bar"),
      exit_code: 1,
    })
  }

  #[test]
  #[cfg(unix)]
  fn env() {
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());

    let result = run_command(ExecuteProcessRequest {
      argv: make_argv(&["/usr/bin/env"]),
      env: env.clone(),
    });

    let stdout = String::from_utf8(result.unwrap().stdout).unwrap();
    let got_env: BTreeMap<String, String> = stdout.split("\n")
      .filter(|line| !line.is_empty())
      .map(|line| line.splitn(2, "="))
      .map(|mut parts| (parts.next().unwrap().to_string(), parts.next().unwrap_or("").to_string()))
      .filter(|x| x.0 != "PATH")
      .collect();

    assert_eq!(env, got_env);
  }

  #[test]
  #[cfg(unix)]
  fn env_is_deterministic() {
    fn make_request() -> ExecuteProcessRequest {
      let mut env = BTreeMap::new();
      env.insert("FOO".to_string(), "foo".to_string());
      env.insert("BAR".to_string(), "not foo".to_string());

      ExecuteProcessRequest {
        argv: make_argv(&["/usr/bin/env"]),
        env: env,
      }
    }

    let result1 = run_command(make_request());
    let result2 = run_command(make_request());

    assert_eq!(result1.unwrap(), result2.unwrap());
  }

  #[test]
  fn binary_not_found() {
    run_command(ExecuteProcessRequest {
      argv: make_argv(&["echo", "-n", "foo"]),
      env: BTreeMap::new(),
    }).expect_err("Want Err");
  }

  fn make_argv(args: &[&str]) -> Vec<String> {
    args.into_iter().map(|s| s.to_string()).collect()
  }

  fn make_byte_vec(str: &str) -> Vec<u8> {
    Vec::from(str.as_bytes())
  }
}
