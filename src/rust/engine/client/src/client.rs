// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io;
use std::os::unix::io::AsRawFd;
use std::path::PathBuf;
use std::time::{Duration, SystemTime};

use futures::channel::mpsc;
use futures::StreamExt;
use futures::{future, SinkExt, Stream, TryFutureExt};
use log::debug;
use nails::execution::{child_channel, send_to_io, stream_for, ChildInput, ChildOutput, Command};
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;

pub struct ConnectionSettings {
  pub port: u16,
  pub timeout_limit: f64,
  pub dynamic_ui: bool,
}

impl ConnectionSettings {
  pub fn default(port: u16) -> ConnectionSettings {
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
  working_dir: &PathBuf,
) -> Result<i32, String> {
  env.push((
    "PANTSD_RUNTRACKER_CLIENT_START_TIME".to_owned(),
    start
      .duration_since(SystemTime::UNIX_EPOCH)
      .map_err(|e| format!("Failed to determine current unix time: {err}", err = e))?
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

  let cmd = Command {
    command: argv
      .get(0)
      .ok_or_else(|| "Failed to determine current process argv0".to_owned())?
      .clone(),
    args: argv.iter().skip(1).cloned().collect(),
    env,
    working_dir: working_dir.into(),
  };

  // TODO: This aligns with the C client. Possible that the default client and server configs
  // should be different in order to be maximally lenient.
  let config = nails::Config::default().heartbeat_frequency(Duration::from_millis(500));

  debug!(
    "Connecting to server at {address:?}...",
    address = &connection_settings.port
  );
  let stream = TcpStream::connect(("0.0.0.0", connection_settings.port))
    .await
    .map_err(|e| format!("Error connecting to pantsd: {err}", err = e))?;
  let mut child = nails::client::handle_connection(config, stream, cmd, async {
    let (stdin_write, stdin_read) = child_channel::<ChildInput>();
    let _join = tokio::spawn(handle_stdin(stdin_write));
    stdin_read
  })
  .map_err(|e| format!("Error starting process: {err}", err = e))
  .await?;

  let output_stream = child.output_stream.take().unwrap();
  let stdio_printer = async move { tokio::spawn(handle_stdio(output_stream)).await.unwrap() };

  future::try_join(stdio_printer, child.wait())
    .await
    .map(|(_, exit_code)| exit_code.0)
    .map_err(|e| format!("Error executing process: {err}", err = e))
}

async fn handle_stdio(
  mut stdio_read: impl Stream<Item = ChildOutput> + Unpin,
) -> Result<(), io::Error> {
  let mut stdout = tokio::io::stdout();
  let mut stderr = tokio::io::stderr();
  while let Some(output) = stdio_read.next().await {
    match output {
      ChildOutput::Stdout(bytes) => stdout.write_all(&bytes).await?,
      ChildOutput::Stderr(bytes) => stderr.write_all(&bytes).await?,
    }
  }
  Ok(())
}

async fn handle_stdin(mut stdin_write: mpsc::Sender<ChildInput>) -> Result<(), io::Error> {
  let mut stdin = stream_for(tokio::io::stdin());
  while let Some(input_bytes) = stdin.next().await {
    stdin_write
      .send(ChildInput::Stdin(input_bytes?))
      .await
      .map_err(send_to_io)?;
  }
  Ok(())
}
