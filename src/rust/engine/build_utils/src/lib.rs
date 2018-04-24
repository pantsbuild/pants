use std::env;
use std::ffi::OsStr;
use std::io;
use std::ops::Deref;
use std::path::PathBuf;
use std::process::{Command, Output};

#[derive(Clone, Debug)]
pub struct ExecutionError {
  status: Option<i32>,
  stdout: String,
  stderr: String,
}

fn to_string(data: Vec<u8>) -> String {
  String::from_utf8(data).unwrap()
}

impl ExecutionError {
  fn from(output: Output) -> ExecutionError {
    ExecutionError {
      status: output.status.code(),
      stdout: to_string(output.stdout),
      stderr: to_string(output.stderr),
    }
  }
}

pub type ExecutionResult<T> = Result<T, ExecutionError>;

/// Executes a command returning its trimmed standard output.
///
/// # Errors
///
/// If command execution fails, execution succeeds but the underlying command has a non-successful
/// exit status or conversion of successful command output to a UTF-8 string fails then an error is
/// returned.
///
/// # Examples
///
/// ```
/// use build_utils::execute;
/// use std::path::PathBuf;
///
/// let root_dir: PathBuf = execute("git", &["rev-parse", "--show-toplevel"]).unwrap();
/// ```
pub fn execute<C, A, R>(command: C, args: A) -> ExecutionResult<R>
where
  C: AsRef<OsStr>,
  A: IntoIterator,
  A::Item: AsRef<OsStr>,
  R: From<String>,
{
  let output = Command::new(command).args(args).output().unwrap();
  if output.status.success() {
    Ok(R::from(to_string(output.stdout).trim().to_owned()))
  } else {
    Err(ExecutionError::from(output))
  }
}

/// Executes a command with optional arguments returning its trimmed standard output as a `String`.
///
/// # Panics
///
/// Panics if the command execution fails or has a non-successful exit status.
///
/// # Examples
///
/// ```
/// # #[macro_use(execute)]
/// # extern crate build_utils;
/// #
/// # fn main() {
/// execute!("ls");
/// execute!("ls", "-l", "--all");
/// # }
#[macro_export]
macro_rules! execute {
  ($c: expr) => { $crate::execute::<_, Vec<String>, String>($c, vec![]).unwrap() };
  ($c: expr, $($a: expr),*) => { $crate::execute::<_, _, String>($c, vec![$($a),*]).unwrap() };
}

pub struct BuildRoot(PathBuf);

impl Deref for BuildRoot {
  type Target = PathBuf;

  fn deref(&self) -> &PathBuf {
    &self.0
  }
}

impl BuildRoot {
  /// Finds the Pants build root containing the current working directory.
  ///
  /// # Errors
  ///
  /// If finding the current working directory fails or the search for the Pants build root finds
  /// none.
  ///
  /// # Examples
  ///
  /// ```
  /// use build_utils::BuildRoot;
  ///
  /// let build_root = BuildRoot::find().unwrap();
  ///
  /// // Deref's to a PathBuf
  /// let pants = build_root.join("pants");
  /// assert!(pants.exists());
  /// ```
  pub fn find() -> io::Result<BuildRoot> {
    let current_dir = env::current_dir()?;
    let mut here = current_dir.as_path();
    loop {
      if here.join("pants").exists() {
        return Ok(BuildRoot(here.to_path_buf()));
      } else if let Some(parent) = here.parent() {
        here = parent;
      } else {
        return Err(io::Error::new(
          io::ErrorKind::NotFound,
          format!("Failed to find build root starting from {:?}", current_dir),
        ));
      }
    }
  }
}

#[cfg(test)]
mod build_utils_test {
  use super::{execute, BuildRoot};

  use std::path::PathBuf;

  #[test]
  fn find() {
    let root_dir: PathBuf = execute("git", &["rev-parse", "--show-toplevel"]).unwrap();
    assert_eq!(*BuildRoot::find().unwrap(), root_dir)
  }
}
