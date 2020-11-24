// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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
// TODO: Falsely triggers for async/await:
//   see https://github.com/rust-lang/rust-clippy/issues/5360
// clippy::used_underscore_binding
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

use nails::execution::{stream_for, ChildInput, ChildOutput, ExitCode};
use nails::Config;
use tokio::net::TcpStream;
use tokio::signal::unix::{signal, Signal, SignalKind};

use std::io;
use std::net::Ipv4Addr;
use tokio::io::AsyncWriteExt;

use futures::channel::mpsc;
use futures::{SinkExt, Stream, StreamExt};

pub enum NailgunClientError {
  PreConnect(String),
  PostConnect(String),
  KeyboardInterrupt,
}

async fn handle_client_output(
  mut stdio_read: impl Stream<Item = ChildOutput> + Unpin,
  mut signal_stream: Signal,
  child: &mut nails::client::Child,
) -> Result<(), NailgunClientError> {
  let mut stdout = tokio::io::stdout();
  let mut stderr = tokio::io::stderr();
  let mut is_exiting = false;
  loop {
    tokio::select! {
      output = stdio_read.next() => {
        let io_result = match output {
          Some(ChildOutput::Stdout(bytes)) => stdout.write_all(&bytes).await,
          Some(ChildOutput::Stderr(bytes)) => stderr.write_all(&bytes).await,
          Some(ChildOutput::Exit(_)) | None => {
            // NB: We ignore exit here and allow the main thread to handle exiting.
            break;
          }
        };
        io_result.map_err(|err| {
          NailgunClientError::PostConnect(format!("Failed to flush stdio: {}", err))
        })?;
      }
      _ = signal_stream.recv() => {
          if is_exiting {
              // This is the second signal: exit uncleanly to drop the child rather than waiting
              // further.
              return Err(NailgunClientError::KeyboardInterrupt);
          } else {
              // This is the first signal: trigger shutdown of the Child, which will request that
              // the server interrupt the run.
              child.shutdown().await;
              is_exiting = true;
          }
      }
    }
  }
  Ok(())
}

async fn handle_client_input(mut stdin_write: mpsc::Sender<ChildInput>) -> Result<(), io::Error> {
  use nails::execution::send_to_io;
  let mut stdin = stream_for(tokio::io::stdin());
  while let Some(input_bytes) = stdin.next().await {
    stdin_write
      .send(ChildInput::Stdin(input_bytes?))
      .await
      .map_err(send_to_io)?;
  }
  stdin_write
    .send(ChildInput::StdinEOF)
    .await
    .map_err(send_to_io)?;
  Ok(())
}

///
/// Execute the given command on the given localhost port.
///
/// This method installs (global!: see below) signal handling such that:
///   1. the first SIGINT will cause the client to attempt to exit gracefully.
///   2. the second SIGINT will eagerly exit the client without waiting for the server.
///
/// NB: This method installs a signal handler that will affect signal handling throughout the
/// entire process. Because of this, it should only be used in a process that is relatively
/// dedicated to the task of connecting to a nailgun server.
///
pub async fn client_execute(
  port: u16,
  command: String,
  args: Vec<String>,
  env: Vec<(String, String)>,
) -> Result<i32, NailgunClientError> {
  use nails::execution::{child_channel, Command};

  let working_dir =
    std::env::current_dir().map_err(|e| NailgunClientError::PreConnect(e.to_string()))?;

  let config = Config::default();
  let command = Command {
    command,
    args,
    env,
    working_dir,
  };

  let signal_stream = signal(SignalKind::interrupt()).map_err(|err| {
    NailgunClientError::PreConnect(format!("Failed to install interrupt handler: {}", err))
  })?;
  let socket = TcpStream::connect((Ipv4Addr::new(127, 0, 0, 1), port))
    .await
    .map_err(|err| {
      NailgunClientError::PreConnect(format!(
        "Nailgun client error connecting to localhost: {}",
        err
      ))
    })?;

  let mut child = nails::client::handle_connection(config, socket, command, async {
    let (stdin_write, stdin_read) = child_channel::<ChildInput>();
    let _input_handler = tokio::spawn(handle_client_input(stdin_write));
    stdin_read
  })
  .await
  .map_err(|err| NailgunClientError::PreConnect(format!("Failed to start remote task: {}", err)))?;

  handle_client_output(
    child.output_stream.take().unwrap(),
    signal_stream,
    &mut child,
  )
  .await?;

  let exit_code: ExitCode = child
    .wait()
    .await
    .map_err(|err| NailgunClientError::PostConnect(format!("Nailgun client error: {}", err)))?;

  Ok(exit_code.0)
}
