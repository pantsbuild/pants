// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap, HashSet};
use std::convert::TryInto;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};

use crate::context::{Context, Core};
use crate::core::{Failure, Params, TypeId, Value};
use crate::nodes::{Select, Visualizer};
use crate::session::{ObservedValueResult, Root, Session};

use futures::{future, FutureExt};
use graph::LastObserved;
use hashing::{Digest, EMPTY_DIGEST};
use log::{debug, warn};
use stdio::TryCloneAsFile;
use tempfile::TempDir;
use tokio::process;
use tokio::time;
use ui::ConsoleUI;
use watch::Invalidatable;

pub enum ExecutionTermination {
  // Raised as a vanilla keyboard interrupt on the python side.
  KeyboardInterrupt,
  // An execute-method specific timeout: raised as PollTimeout.
  PollTimeout,
  // No clear reason: possibly a panic on a background thread.
  Fatal(String),
}

#[derive(Default)]
pub struct ExecutionRequest {
  // Set of roots for an execution, in the order they were declared.
  pub roots: Vec<Root>,
  // An ExecutionRequest with `poll` set will wait for _all_ of the given roots to have changed
  // since their previous observed value in this Session before returning them.
  //
  // Example: if an ExecutionRequest is made twice in a row for roots within the same Session,
  // and this value is set, the first run will request the roots and return immediately when they
  // complete. The second request will check whether the roots have changed, and if they haven't
  // changed, will wait until they have (or until the timeout elapses) before re-requesting them.
  //
  // TODO: The `poll`, `poll_delay`, and `timeout` parameters exist to support a coarse-grained API
  // for synchronous Node-watching to Python. Rather than further expanding this `execute` API, we
  // should likely port those usecases to rust.
  pub poll: bool,
  // If poll is set, a delay to apply after having noticed that Nodes have changed and before
  // requesting them.
  pub poll_delay: Option<Duration>,
  // A timeout applied globally to the request. When a request times out, work is _not_ cancelled,
  // and will continue to completion in the background.
  pub timeout: Option<Duration>,
}

///
/// Represents the state of an execution of a Graph.
///
pub struct Scheduler {
  pub core: Arc<Core>,
}

impl Scheduler {
  pub fn new(core: Core) -> Scheduler {
    Scheduler {
      core: Arc::new(core),
    }
  }

  pub fn visualize(&self, session: &Session, path: &Path) -> io::Result<()> {
    let context = Context::new(self.core.clone(), session.clone());
    self.core.graph.visualize(
      Visualizer::default(),
      &session.roots_nodes(),
      path,
      &context,
    )
  }

  pub fn add_root_select(
    &self,
    request: &mut ExecutionRequest,
    params: Params,
    product: TypeId,
  ) -> Result<(), String> {
    let edges = self
      .core
      .rule_graph
      .find_root_edges(params.type_ids(), product)?;
    request
      .roots
      .push(Select::new_from_edges(params, product, &edges));
    Ok(())
  }

  ///
  /// Invalidate the invalidation roots represented by the given Paths.
  ///
  pub fn invalidate(&self, paths: &HashSet<PathBuf>) -> usize {
    self.core.graph.invalidate(paths, "external")
  }

  ///
  /// Invalidate all filesystem dependencies in the graph.
  ///
  pub fn invalidate_all_paths(&self) -> usize {
    self.core.graph.invalidate_all("external")
  }

  ///
  /// Return Scheduler and per-Session metrics.
  ///
  pub fn metrics(&self, session: &Session) -> HashMap<&str, i64> {
    let context = Context::new(self.core.clone(), session.clone());
    let mut m = HashMap::new();
    m.insert("affected_file_count", {
      let mut count = 0;
      self
        .core
        .graph
        .visit_live_reachable(&session.roots_nodes(), &context, |n, _| {
          if n.fs_subject().is_some() {
            count += 1;
          }
        });
      count
    });
    m.insert(
      "preceding_graph_size",
      session.preceding_graph_size() as i64,
    );
    m.insert("resulting_graph_size", self.core.graph.len() as i64);
    m
  }

  ///
  /// Return unit if the Scheduler is still valid, or an error string if something has invalidated
  /// the Scheduler, indicating that it should re-initialize. See InvalidationWatcher.
  ///
  pub fn is_valid(&self) -> Result<(), String> {
    let core = self.core.clone();
    self.core.executor.block_on(async move {
      // Confirm that our InvalidationWatcher is still alive.
      core.watcher.is_valid().await
    })
  }

  ///
  /// Return all Digests currently in memory in this Scheduler.
  ///
  pub fn all_digests(&self, session: &Session) -> HashSet<hashing::Digest> {
    let context = Context::new(self.core.clone(), session.clone());
    let mut digests = HashSet::new();
    self
      .core
      .graph
      .visit_live(&context, |_, v| digests.extend(v.digests()));
    digests
  }

  pub async fn run_local_interactive_process(
    &self,
    session: &Session,
    input_digest: Digest,
    argv: Vec<String>,
    env: BTreeMap<String, String>,
    run_in_workspace: bool,
  ) -> Result<i32, String> {
    let maybe_tempdir = if run_in_workspace {
      None
    } else {
      Some(TempDir::new().map_err(|err| format!("Error creating tempdir: {}", err))?)
    };

    if input_digest != EMPTY_DIGEST {
      if run_in_workspace {
        warn!(
          "Local interactive process should not attempt to materialize files when run in workspace"
        );
      } else {
        let destination = match maybe_tempdir {
          Some(ref dir) => dir.path().to_path_buf(),
          None => unreachable!(),
        };

        self
          .core
          .store()
          .materialize_directory(destination, input_digest)
          .await?;
      }
    }

    let p = Path::new(&argv[0]);
    let program_name = match maybe_tempdir {
      Some(ref tempdir) if p.is_relative() => {
        let mut buf = PathBuf::new();
        buf.push(tempdir);
        buf.push(p);
        buf
      }
      _ => p.to_path_buf(),
    };

    let mut command = process::Command::new(program_name);
    for arg in argv[1..].iter() {
      command.arg(arg);
    }

    if let Some(ref tempdir) = maybe_tempdir {
      command.current_dir(tempdir.path());
    }

    command.env_clear();
    command.envs(env);

    command.kill_on_drop(true);

    let exit_status = session
      .with_console_ui_disabled(async move {
        // Once any UI is torn down, grab exclusive access to the console.
        let (term_stdin, term_stdout, term_stderr) =
          stdio::get_destination().exclusive_start(Box::new(|_| {
            // A stdio handler that will immediately trigger logging.
            Err(())
          }))?;
        // NB: Command's stdio methods take ownership of a file-like to use, so we use
        // `TryCloneAsFile` here to `dup` our thread-local stdio.
        command
          .stdin(Stdio::from(
            term_stdin
              .try_clone_as_file()
              .map_err(|e| format!("Couldn't clone stdin: {}", e))?,
          ))
          .stdout(Stdio::from(
            term_stdout
              .try_clone_as_file()
              .map_err(|e| format!("Couldn't clone stdout: {}", e))?,
          ))
          .stderr(Stdio::from(
            term_stderr
              .try_clone_as_file()
              .map_err(|e| format!("Couldn't clone stderr: {}", e))?,
          ));
        let mut subprocess = command
          .spawn()
          .map_err(|e| format!("Error executing interactive process: {}", e))?;
        tokio::select! {
          _ = session.cancelled() => {
            // The Session was cancelled: kill the process, and then wait for it to exit (to avoid
            // zombies).
            subprocess.kill().map_err(|e| format!("Failed to interrupt child process: {}", e))?;
            subprocess.await.map_err(|e| e.to_string())
          }
          exit_status = &mut subprocess => {
            // The process exited.
            exit_status.map_err(|e| e.to_string())
          }
        }
      })
      .await?;

    Ok(exit_status.code().unwrap_or(-1))
  }

  async fn poll_or_create(
    context: &Context,
    root: Root,
    last_observed: Option<LastObserved>,
    poll: bool,
    poll_delay: Option<Duration>,
  ) -> ObservedValueResult {
    let (result, last_observed) = if poll {
      let (result, last_observed) = context
        .core
        .graph
        .poll(root.into(), last_observed, poll_delay, &context)
        .await?;
      (result, Some(last_observed))
    } else {
      let result = context.core.graph.create(root.into(), &context).await?;
      (result, None)
    };

    Ok((
      result
        .try_into()
        .unwrap_or_else(|e| panic!("A Node implementation was ambiguous: {:?}", e)),
      last_observed,
    ))
  }

  ///
  /// Attempts to complete all of the given roots.
  ///
  async fn execute_helper(
    &self,
    request: &ExecutionRequest,
    session: &Session,
  ) -> Vec<ObservedValueResult> {
    let context = Context::new(self.core.clone(), session.clone());
    let roots = session.roots_zip_last_observed(&request.roots);
    let poll = request.poll;
    let poll_delay = request.poll_delay;
    future::join_all(
      roots
        .into_iter()
        .map(|(root, last_observed)| {
          Self::poll_or_create(&context, root, last_observed, poll, poll_delay)
        })
        .collect::<Vec<_>>(),
    )
    .await
  }

  fn execute_record_results(
    roots: &[Root],
    session: &Session,
    results: Vec<ObservedValueResult>,
  ) -> Vec<Result<Value, Failure>> {
    // Store the roots that were operated on and their LastObserved values.
    session.roots_extend(
      results
        .iter()
        .zip(roots.iter())
        .map(|(result, root)| {
          let last_observed = result
            .as_ref()
            .ok()
            .and_then(|(_value, last_observed)| *last_observed);
          (root.clone(), last_observed)
        })
        .collect::<Vec<_>>(),
    );

    results
      .into_iter()
      .map(|res| res.map(|(value, _last_observed)| value))
      .collect()
  }

  ///
  /// Compute the results for roots in the given request.
  ///
  pub fn execute(
    &self,
    request: &ExecutionRequest,
    session: &Session,
  ) -> Result<Vec<Result<Value, Failure>>, ExecutionTermination> {
    debug!(
      "Launching {} roots (poll={}).",
      request.roots.len(),
      request.poll
    );

    let interval = ConsoleUI::render_interval();
    let deadline = request.timeout.map(|timeout| Instant::now() + timeout);

    // Spawn and wait for all roots to complete.
    session.maybe_display_initialize(&self.core.executor);
    let mut execution_task = self.execute_helper(request, session).boxed();

    self.core.executor.block_on(async move {
      let mut refresh_delay = time::delay_for(Self::refresh_delay(interval, deadline));
      let result = loop {
        tokio::select! {
          _ = session.cancelled() => {
            // The Session was cancelled.
            break Err(ExecutionTermination::KeyboardInterrupt)
          }
          _ = &mut refresh_delay => {
            // It's time to render a new frame (or maybe to time out entirely if the deadline has
            // elapsed).
            if deadline.map(|d| d < Instant::now()).unwrap_or(false) {
              // The timeout on the request has been exceeded.
              break Err(ExecutionTermination::PollTimeout);
            } else {
              // Just a receive timeout. render and continue.
              session.maybe_display_render();
            }
            refresh_delay = time::delay_for(Self::refresh_delay(interval, deadline));
          }
          res = &mut execution_task => {
            // Completed successfully.
            break Ok(Self::execute_record_results(&request.roots, &session, res));
          }
        }
      };
      session.maybe_display_teardown().await;
      result
    })
  }

  fn refresh_delay(refresh_interval: Duration, deadline: Option<Instant>) -> Duration {
    deadline
      .and_then(|deadline| deadline.checked_duration_since(Instant::now()))
      .map(|duration_till_deadline| std::cmp::min(refresh_interval, duration_till_deadline))
      .unwrap_or(refresh_interval)
  }
}

impl Drop for Scheduler {
  fn drop(&mut self) {
    // Because Nodes may hold references to the Core in their closure, this is intended to
    // break cycles between Nodes and the Core.
    self.core.graph.clear();
  }
}
