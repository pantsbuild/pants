// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap, HashSet};
use std::convert::TryInto;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant};

use futures::future;

use crate::context::{Context, Core};
use crate::core::{Failure, Params, TypeId, Value};
use crate::externs;
use crate::nodes::{Select, Visualizer};
use crate::session::{ExecutionEvent, ObservedValueResult, Root, Session};

use cpython::Python;
use futures::compat::Future01CompatExt;
use graph::{InvalidationResult, LastObserved};
use hashing::{Digest, EMPTY_DIGEST};
use log::{debug, info, warn};
use tempfile::TempDir;
use tokio::process;
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

impl ExecutionRequest {
  pub fn new() -> ExecutionRequest {
    ExecutionRequest {
      roots: Vec::new(),
      poll: false,
      poll_delay: None,
      timeout: None,
    }
  }
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
    let InvalidationResult { cleared, dirtied } = self
      .core
      .graph
      .invalidate_from_roots(|node| node.fs_subject().is_some());
    info!(
      "invalidation: cleared {} and dirtied {} nodes for all paths",
      cleared, dirtied
    );
    cleared + dirtied
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
    hermetic_env: bool,
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
          .compat()
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

    if hermetic_env {
      command.env_clear();
    }
    command.envs(env);

    session
      .with_console_ui_disabled(async move {
        let subprocess = command
          .spawn()
          .map_err(|e| format!("Error executing interactive process: {}", e.to_string()))?;
        let exit_status = subprocess.await.map_err(|e| e.to_string())?;
        Ok(exit_status.code().unwrap_or(-1))
      })
      .await
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
  /// Attempts to complete all of the given roots, and send a FinalResult on the given mpsc Sender,
  /// which allows the caller to poll a channel for the result without blocking uninterruptibly
  /// on a Future.
  ///
  fn execute_helper(
    &self,
    request: &ExecutionRequest,
    session: &Session,
    sender: mpsc::Sender<ExecutionEvent>,
  ) {
    let context = Context::new(self.core.clone(), session.clone());
    let roots = session.roots_zip_last_observed(&request.roots);
    let poll = request.poll;
    let poll_delay = request.poll_delay;
    let core = context.core.clone();
    let _join = core.executor.spawn(async move {
      let res = future::join_all(
        roots
          .into_iter()
          .map(|(root, last_observed)| {
            Self::poll_or_create(&context, root, last_observed, poll, poll_delay)
          })
          .collect::<Vec<_>>(),
      )
      .await;

      // The receiver may have gone away due to timeout.
      let _ = sender.send(ExecutionEvent::Completed(res));
    });
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
    python_signal_fn: Value,
  ) -> Result<Vec<Result<Value, Failure>>, ExecutionTermination> {
    debug!(
      "Launching {} roots (poll={}).",
      request.roots.len(),
      request.poll
    );

    let interval = ConsoleUI::render_interval();
    let deadline = request.timeout.map(|timeout| Instant::now() + timeout);

    // Spawn and wait for all roots to complete.
    let (sender, receiver) = mpsc::channel();
    session.maybe_display_initialize(&self.core.executor, &sender);
    self.execute_helper(request, session, sender);
    let result = loop {
      let execution_event = receiver.recv_timeout(Self::refresh_delay(interval, deadline));

      if let Some(termination) = maybe_break_execution_loop(&python_signal_fn) {
        return Err(termination);
      }

      match execution_event {
        Ok(ExecutionEvent::Completed(res)) => {
          // Completed successfully.
          break Ok(Self::execute_record_results(&request.roots, &session, res));
        }
        Ok(ExecutionEvent::Stderr(stderr)) => {
          session.write_stderr(&stderr);
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
          if deadline.map(|d| d < Instant::now()).unwrap_or(false) {
            // The timeout on the request has been exceeded.
            break Err(ExecutionTermination::PollTimeout);
          } else {
            // Just a receive timeout. render and continue.
            session.maybe_display_render();
          }
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
          break Err(ExecutionTermination::Fatal(
            "Execution threads exited early.".to_owned(),
          ));
        }
      }
    };
    self
      .core
      .executor
      .block_on(session.maybe_display_teardown());
    result
  }

  fn refresh_delay(refresh_interval: Duration, deadline: Option<Instant>) -> Duration {
    deadline
      .and_then(|deadline| deadline.checked_duration_since(Instant::now()))
      .map(|duration_till_deadline| std::cmp::min(refresh_interval, duration_till_deadline))
      .unwrap_or(refresh_interval)
  }
}

pub fn maybe_break_execution_loop(python_signal_fn: &Value) -> Option<ExecutionTermination> {
  match externs::call_function(&python_signal_fn, &[]) {
    Ok(value) => {
      if externs::is_truthy(&value) {
        Some(ExecutionTermination::KeyboardInterrupt)
      } else {
        None
      }
    }
    Err(mut e) => {
      let gil = Python::acquire_gil();
      let py = gil.python();
      if e
        .instance(py)
        .cast_as::<cpython::exc::KeyboardInterrupt>(py)
        .is_ok()
      {
        Some(ExecutionTermination::KeyboardInterrupt)
      } else {
        let failure = Failure::from_py_err_with_gil(py, e);
        std::mem::drop(gil);
        Some(ExecutionTermination::Fatal(format!(
          "Error when checking Python signal state: {}",
          failure
        )))
      }
    }
  }
}

impl Drop for Scheduler {
  fn drop(&mut self) {
    // Because Nodes may hold references to the Core in their closure, this is intended to
    // break cycles between Nodes and the Core.
    self.core.graph.clear();
  }
}
