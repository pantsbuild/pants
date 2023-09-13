// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
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

#[cfg(test)]
mod pantsd_testing;
#[cfg(test)]
mod pantsd_tests;

use std::path::{Path, PathBuf};
use std::{fmt, fs};

use libc::pid_t;
use log::debug;
use options::{option_id, BuildRoot, OptionId, OptionType};
use sha2::digest::Update;
use sha2::{Digest, Sha256};
use sysinfo::{ProcessExt, ProcessStatus, System, SystemExt};

pub(crate) struct Metadata {
  metadata_dir: PathBuf,
}

impl Metadata {
  pub(crate) fn mount<P: AsRef<Path>>(directory: P) -> Result<Metadata, String> {
    let info = uname::uname().map_err(|e| format!("{e}"))?;
    let host_hash = Sha256::new()
      .chain(&info.sysname)
      .chain(&info.nodename)
      .chain(&info.release)
      .chain(&info.version)
      .chain(&info.machine)
      .finalize();

    const HOST_FINGERPRINT_LENGTH: usize = 12;
    let mut hex_digest = String::with_capacity(HOST_FINGERPRINT_LENGTH);
    for byte in host_hash {
      fmt::Write::write_fmt(&mut hex_digest, format_args!("{byte:02x}")).unwrap();
      if hex_digest.len() >= HOST_FINGERPRINT_LENGTH {
        break;
      }
    }

    let metadata_dir = directory
      .as_ref()
      .join(&hex_digest[..HOST_FINGERPRINT_LENGTH])
      .join("pantsd");
    if metadata_dir.is_dir() {
      Ok(Metadata { metadata_dir })
    } else {
      Err(format!(
        "There is no pantsd metadata at {metadata_dir}.",
        metadata_dir = metadata_dir.display()
      ))
    }
  }

  fn pid(&self) -> Result<pid_t, String> {
    self
      .read_metadata("pid")
      .and_then(|(pid_metadata_path, value)| {
        value
          .parse()
          .map(|pid| {
            debug!(
              "Parsed pid {pid} from {pid_metadata_path}.",
              pid = pid,
              pid_metadata_path = pid_metadata_path.display()
            );
            pid
          })
          .map_err(|e| {
            format!(
              "Failed to parse pantsd pid from {pid_metadata_path}: {err}",
              pid_metadata_path = pid_metadata_path.display(),
              err = e
            )
          })
      })
  }

  fn process_name(&self) -> Result<String, String> {
    self.read_metadata("process_name").map(|(_, value)| value)
  }

  pub(crate) fn port(&self) -> Result<u16, String> {
    self
      .read_metadata("socket")
      .and_then(|(socket_metadata_path, value)| {
        value
          .parse()
          .map(|port| {
            debug!(
              "Parsed port {port} from {socket_metadata_path}.",
              port = port,
              socket_metadata_path = socket_metadata_path.display()
            );
            port
          })
          .map_err(|e| {
            format!(
              "Failed to parse pantsd port from {socket_metadata_path}: {err}",
              socket_metadata_path = &socket_metadata_path.display(),
              err = e
            )
          })
      })
  }

  fn read_metadata(&self, name: &str) -> Result<(PathBuf, String), String> {
    let metadata_path = self.metadata_dir.join(name);
    fs::read_to_string(&metadata_path)
      .map_err(|e| {
        format!(
          "Failed to read {name} from {metadata_path}: {err}",
          name = name,
          metadata_path = &metadata_path.display(),
          err = e
        )
      })
      .map(|value| (metadata_path, value))
  }
}

pub struct FingerprintedOption {
  _id: OptionId,
  _option_type: OptionType,
}

impl FingerprintedOption {
  pub fn new(id: OptionId, option_type: impl Into<OptionType>) -> Self {
    Self {
      _id: id,
      _option_type: option_type.into(),
    }
  }
}

/// If there is a live `pantsd` process for a valid fingerprint in the given directory, return the
/// port to use to connect to it.
pub fn probe(working_dir: &Path, metadata_dir: &Path) -> Result<u16, String> {
  let pantsd_metadata = Metadata::mount(metadata_dir)?;

  // Grab the purported port early. If we can't get that, then none of the following checks
  // are useful.
  let port = pantsd_metadata.port()?;

  let pid = pantsd_metadata.pid()?;
  let mut system = System::new();
  system.refresh_process(pid);
  // Check that the recorded pid is a live process.
  match system.process(pid) {
    None => Err(format!(
      "\
        The last pid for the pantsd controlling {working_dir} was {pid} but it no longer appears \
        to be running.\
        ",
      working_dir = working_dir.display(),
      pid = pid,
    )),
    Some(process) => {
      // Check that the live process is in fact the expected pantsd process (i.e.: pids have not
      // wrapped).
      if std::mem::discriminant(&ProcessStatus::Zombie) == std::mem::discriminant(&process.status())
      {
        return Err(format!("The pantsd at pid {pid} is a zombie."));
      }
      let expected_process_name_prefix = pantsd_metadata.process_name()?;
      let actual_argv0 = {
        let actual_command_line = process.cmd();
        if actual_command_line.is_empty() {
          process.name()
        } else {
          &actual_command_line[0]
        }
      };
      // It appears the the daemon only records a prefix of the process name, so we just check that.
      if actual_argv0.starts_with(&expected_process_name_prefix) {
        Ok(port)
      } else {
        Err(format!(
          "\
          The process with pid {pid} is not pantsd. Expected a process name matching \
          {expected_process_name_prefix} but is {actual_argv0}.\
          "
        ))
      }
    }
  }
}

/// The options which are fingerprinted to decide when to restart `pantsd`.
///
/// These options are a subset of the bootstrap options which are consumed during `pantsd` startup,
/// but _before_ creating a Scheduler. The options used to create a Scheduler are fingerprinted
/// using a different mechanism in `PantsDaemonCore`, to decide when to create new Schedulers
/// (without restarting `pantsd`).
pub fn fingerprinted_options(build_root: &BuildRoot) -> Result<Vec<FingerprintedOption>, String> {
  Ok(vec![
    FingerprintedOption::new(option_id!(-'l', "level"), "info"),
    FingerprintedOption::new(option_id!("show_log_target"), false),
    // TODO: No support for parsing dictionaries, so not fingerprinted. But should be.
    // FingerprintedOption::new(option_id!("log_levels_by_target"), ...),
    FingerprintedOption::new(option_id!("log_show_rust_3rdparty"), false),
    FingerprintedOption::new(option_id!("pants_version"), include_str!("../../VERSION")),
    FingerprintedOption::new(
      option_id!("pants_workdir"),
      build_root
        .join(".pants.d")
        .into_os_string()
        .into_string()
        .map_err(|e| format!("Build root was not UTF8: {e:?}"))?,
    ),
    FingerprintedOption::new(option_id!("pants_physical_workdir_base"), None),
    FingerprintedOption::new(option_id!("logdir"), None),
    FingerprintedOption::new(option_id!("pantsd"), true),
    FingerprintedOption::new(option_id!("pantsd_pailgun_port"), 0),
    FingerprintedOption::new(option_id!("pantsd_invalidation_globs"), vec![]),
  ])
}
