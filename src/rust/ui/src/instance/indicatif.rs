// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp;
use std::collections::HashMap;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, SystemTime};

use futures::FutureExt;
use futures::future::BoxFuture;
use indexmap::IndexSet;
use indicatif::MultiProgress;
use indicatif::ProgressBar;
use indicatif::ProgressDrawTarget;
use indicatif::ProgressStyle;
use indicatif::WeakProgressBar;
use parking_lot::{Condvar, Mutex};

use logging::fatal_log;
use task_executor::Executor;
use workunit_store::SpanId;
use workunit_store::format_workunit_duration_ms;

use super::TaskState;
use crate::ConsoleUI;

#[derive(Clone)]
struct Task {
    label: String,
    start_time: SystemTime,
}

pub struct IndicatifInstance {
    tasks_to_display: IndexSet<SpanId>,
    executor: Executor,
    snapshot: Arc<Mutex<Vec<Option<Task>>>>,
    stopping: Arc<(Mutex<bool>, Condvar)>,
    join_handle: Option<thread::JoinHandle<()>>,
}

impl IndicatifInstance {
    pub fn new(
        executor: Executor,
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
        drop(stderr_dest_bar_guard);

        let snapshot = Arc::new(Mutex::new((0..bars.len()).map(|_| None).collect()));
        let stopping = Arc::new((Mutex::new(false), Condvar::new()));

        let render_loop = RenderLoop {
            _multi_progress: multi_progress,
            bars,
            snapshot: snapshot.clone(),
            stopping: stopping.clone(),
            interval: ConsoleUI::render_interval(),
        };
        let join_handle = thread::Builder::new()
            .name("pants-indicatif-render".into())
            .spawn(move || render_loop.run())
            .map_err(|e| format!("Failed to spawn indicatif render thread: {e}"))?;

        Ok(IndicatifInstance {
            tasks_to_display: IndexSet::new(),
            executor,
            snapshot,
            stopping,
            join_handle: Some(join_handle),
        })
    }

    pub fn teardown(self) -> BoxFuture<'static, ()> {
        // Eagerly signal the render thread to stop, so that it winds down concurrently with
        // acquiring a thread from the blocking pool below.
        {
            let (lock, cv) = &*self.stopping;
            *lock.lock() = true;
            cv.notify_all();
        }
        // Drop joins the render thread, which restores direct access to the Console as it exits:
        // move the drop to the blocking pool so that the join cannot stall an async thread (or
        // whoever holds the Session's display lock). The returned Future completes only once the
        // Console has been restored; if it is instead dropped, teardown still completes in the
        // background.
        let executor = self.executor.clone();
        let teardown = executor.spawn_blocking(move || std::mem::drop(self));
        async move {
            if let Err(e) = teardown.await {
                fatal_log!("Failed to teardown UI: {e}");
            }
        }
        .boxed()
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

        let mut snap = self.snapshot.lock();
        for slot in snap.iter_mut() {
            *slot = None;
        }
        for (n, span_id) in tasks_to_display.iter().enumerate() {
            if n >= snap.len() {
                break;
            }
            let (label, start_time) = heavy_hitters.get(span_id).unwrap();
            snap[n] = Some(Task {
                label: label.clone(),
                start_time: *start_time,
            });
        }
    }
}

impl Drop for IndicatifInstance {
    fn drop(&mut self) {
        {
            let (lock, cv) = &*self.stopping;
            *lock.lock() = true;
            cv.notify_all();
        }
        if let Some(h) = self.join_handle.take() {
            // NB: The panic itself is reported by the global panic hook when it occurs; this
            // only explains the consequence.
            if h.join().is_err() {
                log::warn!(
                    "The UI render thread panicked (see error above); the dynamic UI was disabled for the remainder of the run."
                );
            }
        }
    }
}

struct RenderLoop {
    // NB: Kept for Drop so the terminal is restored when the render thread exits.
    _multi_progress: MultiProgress,
    bars: Vec<ProgressBar>,
    snapshot: Arc<Mutex<Vec<Option<Task>>>>,
    stopping: Arc<(Mutex<bool>, Condvar)>,
    interval: Duration,
}

impl RenderLoop {
    fn run(self) {
        loop {
            // Clone the current snapshot out quickly so we don't hold the caller's lock
            // while writing to the terminal.
            let snap = self.snapshot.lock().clone();
            let now = SystemTime::now();
            for (n, pbar) in self.bars.iter().enumerate() {
                match snap.get(n).and_then(|e| e.as_ref()) {
                    Some(task) => {
                        let duration_label = match now.duration_since(task.start_time).ok() {
                            None => "(Waiting)".to_string(),
                            Some(duration) => format_workunit_duration_ms(duration),
                        };
                        pbar.set_message(format!("{duration_label} {}", task.label));
                    }
                    None => pbar.set_message(""),
                }
                pbar.tick();
            }

            let (lock, cv) = &*self.stopping;
            let mut stopping = lock.lock();
            if *stopping {
                break;
            }
            cv.wait_for(&mut stopping, self.interval);
            if *stopping {
                break;
            }
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
