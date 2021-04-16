// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use nailgun::NailgunClientError;
use std::os::unix::io::AsRawFd;
use std::time::SystemTime;

pub struct ConnectionSettings {
  pub port: u16,
  pub timeout_limit: f64,
  pub dynamic_ui: bool,
}

impl ConnectionSettings {
  pub fn new(port: u16) -> ConnectionSettings {
    ConnectionSettings {
      port,
      timeout_limit: 60.0,
      dynamic_ui: true,
    }
  }
}

pub async fn execute_command(
  start: SystemTime,
  connection_settings: ConnectionSettings,
  mut env: Vec<(String, String)>,
  argv: Vec<String>,
) -> Result<i32, String> {
  env.push((
    "PANTSD_RUNTRACKER_CLIENT_START_TIME".to_owned(),
    start
      .duration_since(SystemTime::UNIX_EPOCH)
      .map_err(|e| format!("Failed to determine current time: {err}", err = e))?
      .as_secs_f64()
      .to_string(),
  ));

  env.push((
    "PANTSD_REQUEST_TIMEOUT_LIMIT".to_owned(),
    connection_settings.timeout_limit.to_string(),
  ));

  if connection_settings.dynamic_ui {
    for raw_fd in &[
      std::io::stdin().as_raw_fd(),
      std::io::stdout().as_raw_fd(),
      std::io::stderr().as_raw_fd(),
    ] {
      if let Ok(path) = nix::unistd::ttyname(*raw_fd) {
        env.push((
          format!("NAILGUN_TTY_PATH_{fd}", fd = raw_fd),
          path.display().to_string(),
        ));
      }
    }
  }

  let command = argv
    .get(0)
    .ok_or_else(|| "Failed to determine current process argv0".to_owned())?
    .clone();

  let args = argv.iter().skip(1).cloned().collect();

  nailgun::client_execute(connection_settings.port, command, args, env)
    .await
    .map_err(|error| match error {
      NailgunClientError::PreConnect(err) => format!(
        "Problem connecting to pantsd at {port}: {err}",
        port = connection_settings.port,
        err = err
      ),
      NailgunClientError::PostConnect(err) => format!(
        "Problem communicating with pantsd at {port}: {err}",
        port = connection_settings.port,
        err = err
      ),
      NailgunClientError::BrokenPipe => format!(
        "Broken pipe communicating with pantsd at {port}.",
        port = connection_settings.port
      ),
      NailgunClientError::KeyboardInterrupt => "User interrupt.".to_owned(),
    })
}
