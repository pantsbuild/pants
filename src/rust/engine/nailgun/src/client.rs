// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io;
use std::net::Ipv4Addr;

use futures::channel::mpsc;
use futures::{try_join, SinkExt, Stream, StreamExt};
use nails::execution::{stream_for, ChildInput, ChildOutput, ExitCode};
use nails::Config;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use tokio::signal::unix::{signal, Signal, SignalKind};

pub enum NailgunClientError {
    PreConnect(String),
    PostConnect(String),
    BrokenPipe,
    KeyboardInterrupt,
}

fn handle_postconnect_stdio(err: io::Error, msg: &str) -> NailgunClientError {
    if err.kind() == io::ErrorKind::BrokenPipe {
        // A BrokenPipe error is a semi-expected error caused when stdout/stderr closes, and which
        // the Python runtime has a special error type and handling for.
        NailgunClientError::BrokenPipe
    } else {
        NailgunClientError::PostConnect(format!("{}: {}", msg, err))
    }
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
            match output {
              Some(ChildOutput::Stdout(bytes)) => {
                stdout.write_all(&bytes).await.map_err(|err| handle_postconnect_stdio(err, "Failed to write to stdout"))?
              },
              Some(ChildOutput::Stderr(bytes)) => {
                stderr.write_all(&bytes).await.map_err(|err| handle_postconnect_stdio(err, "Failed to write to stderr"))?
              },
              None => break,
            }
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
    try_join!(stdout.flush(), stderr.flush())
        .map_err(|err| handle_postconnect_stdio(err, "Failed to flush stdio"))?;
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
            NailgunClientError::PreConnect(format!("Failed to connect to localhost: {}", err))
        })?;

    let mut child = nails::client::handle_connection(config, socket, command, async {
        let (stdin_write, stdin_read) = child_channel::<ChildInput>();
        let _input_handler = tokio::spawn(handle_client_input(stdin_write));
        stdin_read
    })
    .await
    .map_err(|err| NailgunClientError::PreConnect(format!("Failed to start: {}", err)))?;

    handle_client_output(
        child.output_stream.take().unwrap(),
        signal_stream,
        &mut child,
    )
    .await?;

    let exit_code: ExitCode = child.wait().await.map_err(|err| {
    let err_str = match err.to_string().as_str() {
      "Client exited before the server's result could be returned." => {
        "The pantsd process was killed during the run.\n\nIf this was not intentionally done by you, \
          Pants may have been killed by the operating system due to memory overconsumption \
          (i.e. OOM-killed). You can set the global option `--pantsd-max-memory-usage` to reduce \
          Pantsd's memory consumption by retaining less in its in-memory cache \
          (run `./pants help-advanced global`). You can also disable pantsd with the global \
          option `--no-pantsd` to avoid persisting memory across Pants runs, although you will miss \
          out on additional caching.\n\nIf neither of those help, please consider filing a \
          GitHub issue or reaching out on Slack so that we can investigate the possible memory \
          overconsumption (https://www.pantsbuild.org/docs/getting-help)."
          .to_owned()
      }
      _ => format!("Failed during execution: {}", err),
    };
    NailgunClientError::PostConnect(err_str)
  })?;

    Ok(exit_code.0)
}
