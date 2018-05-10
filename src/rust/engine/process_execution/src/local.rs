extern crate tempdir;

use std::io::Error;
use std::path::Path;
use std::process::Command;

use super::{ExecuteProcessRequest, ExecuteProcessResult};

use bytes::Bytes;
///
/// Runs a command on this machine in the pwd.
///
pub fn run_command_locally(
  req: ExecuteProcessRequest,
  workdir: &Path,
) -> Result<ExecuteProcessResult, Error> {
  Command::new(&req.argv[0])
    .args(&req.argv[1..])
    .current_dir(workdir)
    .env_clear()
    // It would be really nice not to have to manually set PATH but this is sadly the only way
    // to stop automatic PATH searching.
    .env("PATH", "")
    .envs(req.env)
    .output()
    .map(|output| ExecuteProcessResult {
      stdout: Bytes::from(output.stdout),
      stderr: Bytes::from(output.stderr),
      exit_code: output.status.code().unwrap(),
    })
}

#[cfg(test)]
mod tests {
  extern crate testutil;

  use self::testutil::{as_bytes, owned_string_vec};
  use super::{run_command_locally, ExecuteProcessRequest, ExecuteProcessResult};
  use fs;
  use std::collections::BTreeMap;
  use std::path::PathBuf;

  #[test]
  #[cfg(unix)]
  fn stdout() {
    let result = run_command_locally(
      ExecuteProcessRequest {
        argv: owned_string_vec(&["/bin/echo", "-n", "foo"]),
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
      },
      &PathBuf::from("/"),
    );

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes(""),
        exit_code: 0,
      }
    )
  }

  #[test]
  #[cfg(unix)]
  fn stdout_and_stderr_and_exit_code() {
    let result = run_command_locally(
      ExecuteProcessRequest {
        argv: owned_string_vec(&["/bin/bash", "-c", "echo -n foo ; echo >&2 -n bar ; exit 1"]),
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
      },
      &PathBuf::from("/"),
    );

    assert_eq!(
      result.unwrap(),
      ExecuteProcessResult {
        stdout: as_bytes("foo"),
        stderr: as_bytes("bar"),
        exit_code: 1,
      }
    )
  }

  #[test]
  #[cfg(unix)]
  fn env() {
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    env.insert("FOO".to_string(), "foo".to_string());
    env.insert("BAR".to_string(), "not foo".to_string());

    let result = run_command_locally(
      ExecuteProcessRequest {
        argv: owned_string_vec(&["/usr/bin/env"]),
        env: env.clone(),
        input_files: fs::EMPTY_DIGEST,
      },
      &PathBuf::from("/"),
    );

    let stdout = String::from_utf8(result.unwrap().stdout.to_vec()).unwrap();
    let got_env: BTreeMap<String, String> = stdout
      .split("\n")
      .filter(|line| !line.is_empty())
      .map(|line| line.splitn(2, "="))
      .map(|mut parts| {
        (
          parts.next().unwrap().to_string(),
          parts.next().unwrap_or("").to_string(),
        )
      })
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
        argv: owned_string_vec(&["/usr/bin/env"]),
        env: env,
        input_files: fs::EMPTY_DIGEST,
      }
    }

    let result1 = run_command_locally(make_request(), &PathBuf::from("/"));
    let result2 = run_command_locally(make_request(), &PathBuf::from("/"));

    assert_eq!(result1.unwrap(), result2.unwrap());
  }

  #[test]
  fn binary_not_found() {
    run_command_locally(
      ExecuteProcessRequest {
        argv: owned_string_vec(&["echo", "-n", "foo"]),
        env: BTreeMap::new(),
        input_files: fs::EMPTY_DIGEST,
      },
      &PathBuf::from("/"),
    ).expect_err("Want Err");
  }
}
