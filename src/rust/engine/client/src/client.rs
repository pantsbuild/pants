// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::os::unix::io::AsRawFd;
use std::time::SystemTime;

use log::debug;

use nailgun::NailgunClientError;
use pantsd::ConnectionSettings;

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
            .map_err(|e| format!("Failed to determine current time: {e}"))?
            .as_secs_f64()
            .to_string(),
    ));

    env.push((
        "PANTSD_REQUEST_TIMEOUT_LIMIT".to_owned(),
        connection_settings.timeout_limit.to_string(),
    ));

    let raw_io_fds = [
        std::io::stdin().as_raw_fd(),
        std::io::stdout().as_raw_fd(),
        std::io::stderr().as_raw_fd(),
    ];
    let mut tty_settings = Vec::with_capacity(raw_io_fds.len());
    for raw_fd in &raw_io_fds {
        match nix::sys::termios::tcgetattr(*raw_fd) {
            Ok(termios) => tty_settings.push((raw_fd, termios)),
            Err(err) => debug!(
                "Failed to save terminal attributes for file descriptor {fd}: {err}",
                fd = raw_fd,
                err = err
            ),
        }
        if connection_settings.dynamic_ui {
            if let Ok(path) = nix::unistd::ttyname(*raw_fd) {
                env.push((
                    format!("NAILGUN_TTY_PATH_{raw_fd}"),
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

    let nailgun_result =
        nailgun::client_execute(connection_settings.port, command, args, env).await;
    for (raw_fd, termios) in tty_settings {
        if let Err(err) =
            nix::sys::termios::tcsetattr(*raw_fd, nix::sys::termios::SetArg::TCSADRAIN, &termios)
        {
            debug!(
                "Failed to restore terminal attributes for file descriptor {fd}: {err}",
                fd = raw_fd,
                err = err
            );
        }
    }
    nailgun_result.map_err(|error| match error {
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
