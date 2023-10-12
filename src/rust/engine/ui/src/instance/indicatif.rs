// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp;
use std::collections::HashMap;
use std::future;
use std::sync::Arc;
use std::time::SystemTime;

use futures::future::BoxFuture;
use futures::FutureExt;
use indexmap::IndexSet;
use indicatif::MultiProgress;
use indicatif::ProgressBar;
use indicatif::ProgressDrawTarget;
use indicatif::ProgressStyle;
use indicatif::WeakProgressBar;
use parking_lot::Mutex;

use workunit_store::format_workunit_duration_ms;
use workunit_store::SpanId;

use super::TaskState;
use crate::ConsoleUI;

pub struct IndicatifInstance {
  tasks_to_display: IndexSet<SpanId>,
  // NB: Kept for Drop.
  _multi_progress: MultiProgress,
  bars: Vec<ProgressBar>,
}

impl IndicatifInstance {
  pub fn new(
    local_parallelism: usize,
    terminal_width: u16,
    terminal_height: u16,
  ) -> Result<IndicatifInstance, String> {
    // We take exclusive access to stdio by registering a callback that is used to render stderr
    // while we're holding access. See the method doc.
    // TODO: `MultiProgress` now supports `println` directly. However, it doesn't support
    // `downgrade`.
    let stderr_dest_bar: Arc<Mutex<Option<WeakProgressBar>>> = Arc::new(Mutex::new(None));

    // We acquire the lock before taking exclusive access, and don't release it until after
    // initialization. That way, the exclusive callback can always assume that the destination
    // is initialized (i.e., can `unwrap` it).
    let mut stderr_dest_bar_guard = stderr_dest_bar.lock();
    let multi_progress = setup_bar_outputs(stderr_dest_bar.clone())?;

    let bars = (0..cmp::min(local_parallelism, terminal_height.into()))
      .map(|_n| {
        let style = ProgressStyle::default_bar()
          .template("{spinner} {wide_msg}")
          .expect("Valid template.");

        multi_progress.add(ProgressBar::new(terminal_width.into()).with_style(style))
      })
      .collect::<Vec<_>>();

    *stderr_dest_bar_guard = Some(bars[0].downgrade());

    Ok(IndicatifInstance {
      tasks_to_display: IndexSet::new(),
      _multi_progress: multi_progress,
      bars,
    })
  }

  pub fn teardown(self) -> BoxFuture<'static, ()> {
    // When the MultiProgress completes, the Term(Destination) is dropped, which will restore
    // direct access to the Console.
    std::mem::drop(self);
    future::ready(()).boxed()
  }

  pub fn render(&mut self, heavy_hitters: &HashMap<SpanId, (String, SystemTime)>) {
    let tasks_to_display = &mut self.tasks_to_display;
    super::classify_tasks(
      heavy_hitters,
      tasks_to_display.iter().cloned().collect(),
      &mut |span_id, task_state| match task_state {
        TaskState::Remove => {
          tasks_to_display.swap_remove(&span_id);
        }
        TaskState::Update => {
          tasks_to_display.insert(span_id);
        }
        TaskState::New => {
          tasks_to_display.insert(span_id);
        }
      },
    );

    let now = SystemTime::now();
    for (n, pbar) in self.bars.iter().enumerate() {
      let maybe_label = tasks_to_display.get_index(n).map(|span_id| {
        let (label, start_time) = heavy_hitters.get(span_id).unwrap();
        let duration_label = match now.duration_since(*start_time).ok() {
          None => "(Waiting)".to_string(),
          Some(duration) => format_workunit_duration_ms!((duration).as_millis()).to_string(),
        };
        format!("{duration_label} {label}")
      });

      match maybe_label {
        Some(label) => pbar.set_message(label),
        None => pbar.set_message(""),
      }

      pbar.tick();
    }
  }
}

fn setup_bar_outputs(
  stderr_dest_bar: Arc<Mutex<Option<WeakProgressBar>>>,
) -> Result<MultiProgress, String> {
  let (term_read, _, term_stderr_write) = {
    let stderr_dest_bar = stderr_dest_bar.clone();
    stdio::get_destination().exclusive_start(Box::new(move |msg: &str| {
      // Acquire a handle to the destination bar in the UI. If we fail to upgrade, it's because
      // the UI has shut down: we fail the callback to have the logging module directly log to
      // stderr at that point.
      let dest_bar = {
        let stderr_dest_bar = stderr_dest_bar.lock();
        // We can safely unwrap here because the Mutex is held until the bar is initialized.
        stderr_dest_bar.as_ref().unwrap().upgrade().ok_or(())?
      };
      dest_bar.println(msg);
      Ok(())
    }))?
  };
  let stderr_use_color = term_stderr_write.use_color;
  let term = console::Term::read_write_pair_with_style(
    term_read,
    term_stderr_write,
    console::Style::new().force_styling(stderr_use_color),
  );
  let draw_target = ProgressDrawTarget::term(term, ConsoleUI::render_rate_hz() * 2);
  let multi_progress = MultiProgress::with_draw_target(draw_target);
  Ok(multi_progress)
}
