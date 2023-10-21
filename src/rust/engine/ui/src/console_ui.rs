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
    clippy::used_underscore_binding
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

use futures::future::{self, BoxFuture, FutureExt};
use indexmap::IndexSet;
use indicatif::{MultiProgress, ProgressBar, ProgressDrawTarget, ProgressStyle, WeakProgressBar};
use parking_lot::Mutex;
use std::cmp;
use std::collections::HashMap;
use std::collections::HashSet;
use std::fmt;
use std::future::Future;
use std::sync::mpsc;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use terminal_size::terminal_size_using_fd;

use prodash::progress::Step;
use prodash::render::line;
use prodash::{Root, TreeOptions};

use logging::fatal_log;
use task_executor::Executor;
use workunit_store::{format_workunit_duration_ms, SpanId, WorkunitStore};

pub struct ConsoleUI {
    workunit_store: WorkunitStore,
    local_parallelism: usize,
    ui_use_prodash: bool,
    // While the UI is running, there will be an Instance present.
    instance: Option<Instance>,
}

impl ConsoleUI {
    pub fn new(
        workunit_store: WorkunitStore,
        local_parallelism: usize,
        ui_use_prodash: bool,
    ) -> ConsoleUI {
        ConsoleUI {
            workunit_store,
            local_parallelism,
            ui_use_prodash,
            instance: None,
        }
    }

    ///
    /// The number of times per-second that `Self::render` should be called.
    ///
    pub fn render_rate_hz() -> u8 {
        10
    }

    pub fn render_interval() -> Duration {
        Duration::from_millis(1000 / (Self::render_rate_hz() as u64))
    }

    pub async fn with_console_ui_disabled<T>(&mut self, f: impl Future<Output = T>) -> T {
        if self.instance.is_some() {
            self.teardown().await;
            f.await
        } else {
            f.await
        }
    }

    ///
    /// Updates all of items with new data from the WorkunitStore. For this
    /// method to have any effect, the `initialize` method must have been called first.
    ///
    /// *Technically this method does not do the "render"ing: rather, the background thread
    /// drives rendering, while this method feeds it new data.
    ///
    pub fn render(&mut self) {
        let instance = if let Some(i) = &mut self.instance {
            i
        } else {
            return;
        };

        let heavy_hitters = self.workunit_store.heavy_hitters(self.local_parallelism);
        instance.render(&heavy_hitters)
    }

    ///
    /// If the ConsoleUI is not already running, starts it.
    ///
    /// Errors if a ConsoleUI is already running (which would likely indicate concurrent usage of a
    /// Session attached to a console).
    ///
    pub fn initialize(&mut self, executor: Executor) -> Result<(), String> {
        if self.instance.is_some() {
            return Err("A ConsoleUI cannot render multiple UIs concurrently.".to_string());
        }

        self.instance = Some(Instance::new(
            self.ui_use_prodash,
            self.local_parallelism,
            executor,
        )?);

        Ok(())
    }

    ///
    /// If the ConsoleUI is running, completes it.
    ///
    /// NB: This method returns a Future which will await teardown of the UI, which should be awaited
    /// outside of any UI locks.
    ///
    pub fn teardown(&mut self) -> BoxFuture<'static, ()> {
        if let Some(instance) = self.instance.take() {
            instance.teardown()
        } else {
            futures::future::ready(()).boxed()
        }
    }
}

struct IndicatifInstance {
    tasks_to_display: IndexSet<SpanId>,
    // NB: Kept for Drop.
    _multi_progress: MultiProgress,
    bars: Vec<ProgressBar>,
}

struct ProdashInstance {
    tasks_to_display: HashMap<SpanId, prodash::tree::Item>,
    tree: prodash::Tree,
    handle: line::JoinHandle,
    terminal_width: u16,
    executor: Executor,
}

/// The state for one run of the ConsoleUI.
enum Instance {
    Indicatif(IndicatifInstance),
    Prodash(ProdashInstance),
}

enum TaskState {
    New,
    Update,
    Remove,
}

impl Instance {
    ///
    /// Setup an Instance of the UI renderer.
    ///
    /// NB: This method must be very careful to avoid logging. Between the point where we have taken
    /// exclusive access to the Console and when the UI has actually been initialized, attempts to
    /// log from this method would deadlock (by causing the method to wait for _itself_ to finish).
    ///
    pub fn new(
        ui_use_prodash: bool,
        local_parallelism: usize,
        executor: Executor,
    ) -> Result<Instance, String> {
        let stderr_fd = stdio::get_destination().stderr_as_raw_fd()?;
        let (terminal_width, terminal_height) = terminal_size_using_fd(stderr_fd)
            .map(|terminal_dimensions| (terminal_dimensions.0 .0, terminal_dimensions.1 .0 - 1))
            .unwrap_or((50, local_parallelism.try_into().unwrap()));

        return if ui_use_prodash {
            // Stderr is propagated across a channel to remove lock interleavings between stdio and the UI.
            // TODO: Apply a fix similar to #14093 before landing.
            let (stderr_sender, stderr_receiver) = mpsc::sync_channel(0);
            let (_term_read, _term_stdout_write, term_stderr_write) = stdio::get_destination()
                .exclusive_start(Box::new(move |msg: &str| {
                    // If we fail to send, it's because the UI has shut down: we fail the callback to
                    // have the logging module directly log to stderr at that point.
                    stderr_sender.send(msg.to_owned()).map_err(|_| ())
                }))?;

            let colored = term_stderr_write.use_color;
            let tree = TreeOptions {
                initial_capacity: 1024,
                // This is the capacity in terms of lines that will be buffered between frames: writing more
                // than this amount per frame will drop some on the floor.
                message_buffer_capacity: 65536,
            }
            .create();
            // NB: We render more frequently than we receive new data in order to minimize aliasing where a
            // render might barely miss a data refresh.
            let handle = line::render(
                term_stderr_write,
                tree.clone(),
                line::Options {
                    colored,
                    // This is confirmed before creating a UI.
                    output_is_terminal: true,
                    hide_cursor: true,
                    // TODO: Adjust this.
                    frames_per_second: ConsoleUI::render_rate_hz() as f32,
                    throughput: false,
                    terminal_dimensions: (terminal_width, terminal_height),
                    ..prodash::render::line::Options::default()
                },
            );

            // Spawn a task to propagate stderr, which will exit automatically when the channel closes.
            // TODO: There is a shutdown race here, where if the UI is torn down before exclusive access is
            // dropped, we might drop stderr on the floor. That likely causes:
            //   https://github.com/pantsbuild/pants/issues/13276
            let _stderr_task = executor.native_spawn_blocking({
                let mut tree = tree.clone();
                move || {
                    while let Ok(stderr) = stderr_receiver.recv() {
                        tree.message_raw(stderr);
                    }
                }
            });

            Ok(Instance::Prodash(ProdashInstance {
                tasks_to_display: HashMap::new(),
                tree,
                handle,
                terminal_width,
                executor,
            }))
        } else {
            // We take exclusive access to stdio by registering a callback that is used to render stderr
            // while we're holding access. See the method doc.
            // TODO: `MultiProgress` now supports `println` directly.
            let stderr_dest_bar: Arc<Mutex<Option<WeakProgressBar>>> = Arc::new(Mutex::new(None));
            // We acquire the lock before taking exclusive access, and don't release it until after
            // initialization. That way, the exclusive callback can always assume that the destination
            // is initialized (i.e., can `unwrap` it).
            let mut stderr_dest_bar_guard = stderr_dest_bar.lock();
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
            // NB: We render more frequently than we receive new data in order to minimize aliasing where a
            // render might barely miss a data refresh.
            let draw_target = ProgressDrawTarget::term(term, ConsoleUI::render_rate_hz() * 2);
            let multi_progress = MultiProgress::with_draw_target(draw_target);
            let bars = (0..cmp::min(local_parallelism, terminal_height.into()))
                .map(|_n| {
                    let style = ProgressStyle::default_bar()
                        .template("{spinner} {wide_msg}")
                        .expect("Valid template.");
                    multi_progress.add(ProgressBar::new(terminal_width.into()).with_style(style))
                })
                .collect::<Vec<_>>();
            *stderr_dest_bar_guard = Some(bars[0].downgrade());

            Ok(Instance::Indicatif(IndicatifInstance {
                tasks_to_display: IndexSet::new(),
                _multi_progress: multi_progress,
                bars,
            }))
        };
    }

    pub fn render(&mut self, heavy_hitters: &HashMap<SpanId, (String, SystemTime)>) {
        let classify_tasks =
            |mut current_ids: HashSet<SpanId>, handler: &mut dyn FnMut(SpanId, TaskState)| {
                for span_id in heavy_hitters.keys() {
                    let update = current_ids.remove(span_id);
                    handler(
                        *span_id,
                        if update {
                            TaskState::Update
                        } else {
                            TaskState::New
                        },
                    )
                }
                for span_id in current_ids {
                    handler(span_id, TaskState::Remove);
                }
            };

        match self {
            Instance::Indicatif(indicatif) => {
                let tasks_to_display = &mut indicatif.tasks_to_display;
                classify_tasks(
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
                for (n, pbar) in indicatif.bars.iter().enumerate() {
                    let maybe_label = tasks_to_display.get_index(n).map(|span_id| {
                        let (label, start_time) = heavy_hitters.get(span_id).unwrap();
                        let duration_label = match now.duration_since(*start_time).ok() {
                            None => "(Waiting)".to_string(),
                            Some(duration) => {
                                format_workunit_duration_ms!((duration).as_millis()).to_string()
                            }
                        };
                        format!("{duration_label} {label}")
                    });

                    match maybe_label {
                        Some(label) => pbar.set_message(label),
                        None => pbar.set_message(""),
                    }
                    // TODO: See https://github.com/console-rs/indicatif/pull/417#issuecomment-1202773191
                    // Can be removed once we upgrade past `0.17.0`.
                    pbar.tick();
                }
            }
            Instance::Prodash(prodash) => {
                let tasks_to_display = &mut prodash.tasks_to_display;
                classify_tasks(
                    tasks_to_display.keys().cloned().collect(),
                    &mut |span_id, task_state: TaskState| match task_state {
                        TaskState::Remove => {
                            tasks_to_display.remove(&span_id);
                        }
                        TaskState::Update => {
                            // NB: `inc` moves the "worms" to help show ongoing progress.
                            tasks_to_display.get_mut(&span_id).unwrap().inc();
                        }
                        TaskState::New => {
                            let (desc, start_time) = heavy_hitters.get(&span_id).unwrap();
                            // NB: Allow a 8 char "buffer" to allow for timing and spaces.
                            let max_len = (prodash.terminal_width as usize) - 8;
                            let description: String = if desc.len() < max_len {
                                desc.to_string()
                            } else {
                                desc.chars()
                                    .take(max_len - 3)
                                    .chain(std::iter::repeat('.').take(3))
                                    .collect()
                            };
                            let mut item = prodash.tree.add_child(description);
                            item.init(
                                None,
                                Some(prodash::unit::dynamic(MillisAsFloatingPointSecs)),
                            );
                            item.set(MillisAsFloatingPointSecs::start_time_to_step(start_time));
                            tasks_to_display.insert(span_id, item);
                        }
                    },
                )
            }
        };
    }

    pub fn teardown(self) -> BoxFuture<'static, ()> {
        match self {
            Instance::Indicatif(indicatif) => {
                // When the MultiProgress completes, the Term(Destination) is dropped, which will restore
                // direct access to the Console.
                std::mem::drop(indicatif);
                future::ready(()).boxed()
            }
            Instance::Prodash(mut prodash) => {
                // Drop all tasks to clear the Tree. The call to shutdown will render a final "Tick" with the
                // empty Tree, which will clear the screen.
                prodash.tasks_to_display.clear();
                prodash
                    .executor
                    .clone()
                    .spawn_blocking(
                        move || prodash.handle.shutdown_and_wait(),
                        |e| fatal_log!("Failed to teardown UI: {e}"),
                    )
                    .boxed()
            }
        }
    }
}

/// Renders a millis-since-epoch unit as floating point seconds.
#[derive(Copy, Clone, Default, Eq, PartialEq, Ord, PartialOrd, Debug)]
struct MillisAsFloatingPointSecs;

impl MillisAsFloatingPointSecs {
    /// Computes a static Step from the given start time by converting it to "millis-since-epoch".
    fn start_time_to_step(start_time: &SystemTime) -> Step {
        start_time.duration_since(UNIX_EPOCH).unwrap().as_millis() as usize
    }
}

impl prodash::unit::DisplayValue for MillisAsFloatingPointSecs {
    fn display_current_value(
        &self,
        w: &mut dyn fmt::Write,
        value: Step,
        _upper: Option<Step>,
    ) -> fmt::Result {
        // Convert back from millis-since-epoch to millis elapsed.
        let start_time = UNIX_EPOCH + Duration::from_millis(value as u64);
        let elapsed_ms = start_time.elapsed().map(|d| d.as_millis()).unwrap_or(0);
        w.write_fmt(format_workunit_duration_ms!(elapsed_ms))
    }
    fn display_unit(&self, _w: &mut dyn fmt::Write, _value: Step) -> fmt::Result {
        Ok(())
    }
}
