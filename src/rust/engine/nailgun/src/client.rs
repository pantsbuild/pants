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

use std::io;
use std::net::Ipv4Addr;
use tokio::io::AsyncWriteExt;

use futures::channel::{mpsc, oneshot};
use futures::{future, FutureExt, SinkExt, Stream, StreamExt};
use log::debug;

pub enum NailgunClientError {
  PreConnect(String),
  PostConnect(String),
  ExplicitQuit,
}

async fn handle_client_output(
  mut stdio_read: impl Stream<Item = ChildOutput> + Unpin,
) -> Result<(), io::Error> {
  let mut stdout = tokio::io::stdout();
  let mut stderr = tokio::io::stderr();
  while let Some(output) = stdio_read.next().await {
    match output {
      ChildOutput::Stdout(bytes) => stdout.write_all(&bytes).await?,
      ChildOutput::Stderr(bytes) => stderr.write_all(&bytes).await?,
      ChildOutput::Exit(_) => {
        // NB: We ignore exit here and allow the main thread to handle exiting.
        break;
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

async fn client_execute_helper(
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

  let localhost = Ipv4Addr::new(127, 0, 0, 1);
  let addr = (localhost, port);

  let socket = TcpStream::connect(addr).await.map_err(|err| {
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

  tokio::spawn(handle_client_output(child.output_stream.take().unwrap()))
    .await
    .map_err(|join_error| {
      NailgunClientError::PostConnect(format!("Error joining nailgun client task: {}", join_error))
    })?
    .map_err(|err| {
      NailgunClientError::PostConnect(format!("Nailgun client output error: {}", err))
    })?;

  let exit_code: ExitCode = child
    .wait()
    .await
    .map_err(|err| NailgunClientError::PostConnect(format!("Nailgun client error: {}", err)))?;

  Ok(exit_code.0)
}

pub async fn client_execute(
  port: u16,
  command: String,
  args: Vec<String>,
  env: Vec<(String, String)>,
  exit_receiver: oneshot::Receiver<()>,
) -> Result<i32, NailgunClientError> {
  use future::Either;

  let execution_future = client_execute_helper(port, command, args, env).boxed();

  match future::select(execution_future, exit_receiver).await {
    Either::Left((execution_result, _exit_receiver_fut)) => {
      debug!("Nailgun client future finished");
      execution_result
    }
    Either::Right((_exited, _execution_result_future)) => Err(NailgunClientError::ExplicitQuit),
  }
}
