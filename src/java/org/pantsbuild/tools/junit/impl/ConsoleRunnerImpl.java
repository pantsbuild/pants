// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.annotations.VisibleForTesting;
import com.google.common.base.Charsets;
import com.google.common.base.Preconditions;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.google.common.collect.Sets;
import com.google.common.io.Closeables;
import com.google.common.io.Files;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.commons.io.output.TeeOutputStream;
import org.junit.runner.Computer;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.Runner;
import org.junit.runner.manipulation.Filter;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;
import org.junit.runner.notification.RunNotifier;
import org.junit.runners.model.InitializationError;
import org.kohsuke.args4j.Argument;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.spi.StringArrayOptionHandler;
import org.pantsbuild.args4j.InvalidCmdLineArgumentException;
import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestSerial;
import org.pantsbuild.tools.junit.impl.experimental.ConcurrentComputer;

/**
 * An alternative to {@link JUnitCore} with stream capture and junit-report xml output capabilities.
 */
public class ConsoleRunnerImpl {
  /** Should be set to false for unit testing via {@link #setCallSystemExitOnFinish} */
  private static boolean callSystemExitOnFinish = true;
  /** Intended to be used in unit testing this class */
  private static RunListener testListener = null;

  /**
   * A stream that allows its underlying output to be swapped.
   */
  static class SwappableStream<T extends OutputStream> extends FilterOutputStream {
    private final T original;

    SwappableStream(T out) {
      super(out);
      this.original = out;
    }

    OutputStream swap(OutputStream out) {
      OutputStream old = this.out;
      this.out = out;
      return old;
    }

    /**
     * Returns the original stream this swappable stream was created with.
     */
    public T getOriginal() {
      return original;
    }
  }

  /**
   * Holder for a tests stderr and stdout streams.
   */
  static class StreamCapture {
    private final File out;
    private OutputStream outstream;

    private final File err;
    private OutputStream errstream;

    private int useCount;
    private boolean closed;

    StreamCapture(File out, File err) throws IOException {
      this.out = out;
      this.err = err;
    }

    void incrementUseCount() {
      this.useCount++;
    }

    OutputStream getOutputStream() throws FileNotFoundException {
      if (outstream == null) {
        outstream = new FileOutputStream(out);
      }
      return outstream;
    }

    OutputStream getErrorStream() throws FileNotFoundException {
      if (errstream == null) {
        errstream = new FileOutputStream(err);
      }
      return errstream;
    }

    void close() throws IOException {
      if (--useCount <= 0 && !closed) {
        if (outstream != null) {
          Closeables.close(outstream, /* swallowIOException */ true);
        }
        if (errstream != null) {
          Closeables.close(errstream, /* swallowIOException */ true);
        }
        closed = true;
      }
    }

    void dispose() throws IOException {
      useCount = 0;
      close();
    }

    byte[] readOut() throws IOException {
      return read(out);
    }

    byte[] readErr() throws IOException {
      return read(err);
    }

    private byte[] read(File file) throws IOException {
      Preconditions.checkState(closed, "Capture must be closed by all users before it can be read");
      return Files.toByteArray(file);
    }
  }

  static class InMemoryStreamCapture {
    private ByteArrayOutputStream outstream;
    private ByteArrayOutputStream errstream;

    private boolean closed;

    OutputStream getOutputStream() {
      if (outstream == null) {
        outstream = new ByteArrayOutputStream();
      }
      return outstream;
    }

    OutputStream getErrorStream() {
      if (errstream == null) {
        errstream = new ByteArrayOutputStream();
      }
      return errstream;
    }

    void close() throws IOException {
      if (!closed) {
        if (outstream != null) {
          Closeables.close(outstream, /* swallowIOException */ true);
        }
        if (errstream != null) {
          Closeables.close(errstream, /* swallowIOException */ true);
        }
        closed = true;
      }
    }

    byte[] readOut() throws IOException {
      return read(outstream);
    }

    byte[] readErr() throws IOException {
      return read(errstream);
    }

    private byte[] read(ByteArrayOutputStream stream) throws IOException {
      Preconditions.checkState(closed, "Capture must be closed by all users before it can be read");
      return stream.toByteArray();
    }
  }

  /**
   * A run listener that suiteCaptures the output and error streams for each test class
   * and makes the content of these available.
   */
  static class StreamCapturingListener extends RunListener implements StreamSource {
    private final Map<Class<?>, StreamCapture> suiteCaptures = Maps.newHashMap();
    private final Map<Description, InMemoryStreamCapture> caseCaptures = Maps.newHashMap();

    private final File outdir;
    private final OutputMode outputMode;
    private final SwappableStream<PrintStream> swappableOut;
    private final SwappableStream<PrintStream> swappableErr;

    StreamCapturingListener(File outdir, OutputMode outputMode,
        SwappableStream<PrintStream> swappableOut,
        SwappableStream<PrintStream> swappableErr) {
      this.outdir = outdir;
      this.outputMode = outputMode;
      this.swappableOut = swappableOut;
      this.swappableErr = swappableErr;
    }

    @Override
    public void testRunStarted(Description description) throws Exception {
      registerTests(description.getChildren());
      super.testRunStarted(description);
    }

    private void registerTests(Iterable<Description> tests) throws IOException {
      for (Description test : tests) {
        registerTests(test.getChildren());
        if (Util.isRunnable(test)) {
          StreamCapture suiteCapture = suiteCaptures.get(test.getTestClass());
          if (suiteCapture == null) {
            String prefix = test.getClassName();

            File out = new File(outdir, prefix + ".out.txt");
            Files.createParentDirs(out);

            File err = new File(outdir, prefix + ".err.txt");
            Files.createParentDirs(err);
            suiteCapture = new StreamCapture(out, err);
            suiteCaptures.put(test.getTestClass(), suiteCapture);
          }
          suiteCapture.incrementUseCount();
        }
      }
    }

    @Override
    public void testRunFinished(Result result) throws Exception {
      for (StreamCapture capture : suiteCaptures.values()) {
        capture.dispose();
      }
      caseCaptures.clear();
      super.testRunFinished(result);
    }

    @Override
    public void testStarted(Description description) throws Exception {
      StreamCapture suiteCapture = suiteCaptures.get(description.getTestClass());
      OutputStream suiteOut = suiteCapture.getOutputStream();
      OutputStream suiteErr = suiteCapture.getErrorStream();

      switch (outputMode) {
        case ALL:
          swappableOut.swap(new TeeOutputStream(swappableOut.getOriginal(), suiteOut));
          swappableErr.swap(new TeeOutputStream(swappableErr.getOriginal(), suiteErr));
          break;
        case FAILURE_ONLY:
          InMemoryStreamCapture caseCapture = new InMemoryStreamCapture();
          caseCaptures.put(description, caseCapture);
          swappableOut.swap(new TeeOutputStream(caseCapture.getOutputStream(), suiteOut));
          swappableErr.swap(new TeeOutputStream(caseCapture.getErrorStream(), suiteErr));
          break;
        case NONE:
          swappableOut.swap(suiteOut);
          swappableErr.swap(suiteErr);
          break;
        default:
          throw new IllegalStateException();
      }

      super.testStarted(description);
    }

    @Override
    public void testFailure(Failure failure) throws Exception {
      if (outputMode == OutputMode.FAILURE_ONLY) {
        if (caseCaptures.containsKey(failure.getDescription())) {
          InMemoryStreamCapture capture = caseCaptures.remove(failure.getDescription());
          capture.close();
          swappableOut.getOriginal().append(new String(capture.readOut()));
          swappableErr.getOriginal().append(new String(capture.readErr()));
        } else {
          // Do nothing.
          // In case of exception in @BeforeClass method testFailure executes without testStarted.
        }
      }
      super.testFailure(failure);
    }

    @Override
    public void testFinished(Description description) throws Exception {
      suiteCaptures.get(description.getTestClass()).close();
      if (caseCaptures.containsKey(description)) {
        caseCaptures.remove(description).close();
      }
      super.testFinished(description);
    }

    @Override
    public byte[] readOut(Class<?> testClass) throws IOException {
      return suiteCaptures.get(testClass).readOut();
    }

    @Override
    public byte[] readErr(Class<?> testClass) throws IOException {
      return suiteCaptures.get(testClass).readErr();
    }
  }

  /**
   * A run listener that will stop the test run after the first test failure.
   */
  public class FailFastListener extends RunListener {
    private final RunNotifier runNotifier;
    private final Result result = new Result();

    public FailFastListener(RunNotifier runNotifier) {
      this.runNotifier = runNotifier;
      this.runNotifier.addListener(result.createListener());
    }

    @Override
    public void testFailure(Failure failure) throws Exception {
      runNotifier.fireTestFinished(failure.getDescription());
      runNotifier.fireTestRunFinished(result);
      runNotifier.pleaseStop();
    }
  }

  /**
   * A runner that wraps the original test runner so we can add a listener
   * to stop the tests after the first test failure.
   */
  public class FailFastRunner extends Runner {
    private final Runner wrappedRunner;

    public FailFastRunner(Runner wrappedRunner) {
      this.wrappedRunner = wrappedRunner;
    }

    @Override public Description getDescription() {
      return wrappedRunner.getDescription();
    }

    @Override public void run(RunNotifier notifier) {
      notifier.addListener(new FailFastListener(notifier));
      wrappedRunner.run(notifier);
    }
  }

  enum OutputMode {
    ALL, FAILURE_ONLY, NONE
  }

  private final boolean failFast;
  private final OutputMode outputMode;
  private final boolean xmlReport;
  private final File outdir;
  private final boolean perTestTimer;
  private final Concurrency defaultConcurrency;
  private final int parallelThreads;
  private final int testShard;
  private final int numTestShards;
  private final int numRetries;
  private final boolean useExperimentalRunner;
  private final SwappableStream<PrintStream> swappableOut;
  private final SwappableStream<PrintStream> swappableErr;

  ConsoleRunnerImpl(
      boolean failFast,
      OutputMode outputMode,
      boolean xmlReport,
      boolean perTestTimer,
      File outdir,
      Concurrency defaultConcurrency,
      int parallelThreads,
      int testShard,
      int numTestShards,
      int numRetries,
      boolean useExperimentalRunner,
      PrintStream out,
      PrintStream err) {

    Preconditions.checkNotNull(outputMode);
    Preconditions.checkNotNull(defaultConcurrency);
    Preconditions.checkNotNull(out);
    Preconditions.checkNotNull(err);

    this.failFast = failFast;
    this.outputMode = outputMode;
    this.xmlReport = xmlReport;
    this.perTestTimer = perTestTimer;
    this.outdir = outdir;
    this.defaultConcurrency = defaultConcurrency;
    this.parallelThreads = parallelThreads;
    this.testShard = testShard;
    this.numTestShards = numTestShards;
    this.numRetries = numRetries;
    this.swappableOut = new SwappableStream<PrintStream>(out);
    this.swappableErr = new SwappableStream<PrintStream>(err);
    this.useExperimentalRunner = useExperimentalRunner;
  }

  void run(Collection<String> tests) {
    System.setOut(new PrintStream(swappableOut));
    System.setErr(new PrintStream(swappableErr));

    JUnitCore core = new JUnitCore();

    if (testListener != null) {
      core.addListener(testListener);
    }

    if (!outdir.exists() && !outdir.mkdirs()) {
      throw new IllegalStateException("Failed to create output directory: " + outdir);
    }

    StreamCapturingListener streamCapturingListener =
        new StreamCapturingListener(outdir, outputMode, swappableOut, swappableErr);
    core.addListener(streamCapturingListener);

    if (xmlReport) {
      core.addListener(new AntJunitXmlReportListener(outdir, streamCapturingListener));
    }

    if (perTestTimer) {
      core.addListener(new PerTestConsoleListener(swappableOut.getOriginal()));
    } else {
      core.addListener(new ConsoleListener(swappableOut.getOriginal()));
    }

    ShutdownListener shutdownListener = new ShutdownListener(swappableOut.getOriginal());
    core.addListener(shutdownListener);
    // Wrap test execution with registration of a shutdown hook that will ensure we
    // never exit silently if the VM does.
    final Thread unexpectedExitHook =
        createUnexpectedExitHook(shutdownListener, swappableOut.getOriginal());
    Runtime.getRuntime().addShutdownHook(unexpectedExitHook);

    int failures = 0;
    try {
      Collection<Spec> parsedTests = new SpecParser(tests).parse();
      if (useExperimentalRunner) {
        failures = runExperimental(parsedTests, core);
      } else {
        failures = runLegacy(parsedTests, core);
      }
    } catch (SpecException e) {
      failures = 1;
      swappableErr.getOriginal().println("Error parsing specs: " + e.getMessage());
    } catch (InitializationError e) {
      failures = 1;
      swappableErr.getOriginal().println("Error initializing JUnit: " + e.getMessage());
    } finally {
      // If we're exiting via a thrown exception, we'll get a better message by letting it
      // propagate than by halt()ing.
      Runtime.getRuntime().removeShutdownHook(unexpectedExitHook);
    }
    exit(failures);
  }

  /**
   * Returns a thread that records a system exit to the listener, and then halts(1).
   */
  private Thread createUnexpectedExitHook(final ShutdownListener listener, final PrintStream out) {
    return new Thread() {
      @Override public void run() {
        try {
          listener.unexpectedShutdown();
          // We want to trap and log no matter why abort failed for a better end user message.
        } catch (Exception e) {
          out.println(e);
          e.printStackTrace(out);
        }
        // This error might be a call to `System.exit(0)` in a test, which we definitely do
        // not want to go unnoticed.
        out.println("FATAL: VM exiting unexpectedly.");
        out.flush();
        Runtime.getRuntime().halt(1);
      }
    };
  }

  private int runExperimental(Collection<Spec> parsedTests, JUnitCore core)
      throws InitializationError {
    Preconditions.checkNotNull(core);

    int failures = 0;
    SpecSet filter = new SpecSet(parsedTests, defaultConcurrency);

    // TODO(zundel): Test sharding currently isn't compatible with the parallel computer runner
    // since the Computer only accepts Class objects.
    if (numTestShards == 0) {
      // Run all of the parallel tests using the ConcurrentComputer
      // NB(zundel): This runs these test of each concurrency setting together and waits for them
      // to finish.  This introduces a bottleneck after each class of test.
      failures += runConcurrentTests(core, filter, Concurrency.PARALLEL_CLASSES_AND_METHODS);
      failures += runConcurrentTests(core, filter, Concurrency.PARALLEL_CLASSES);
      failures += runConcurrentTests(core, filter, Concurrency.PARALLEL_METHODS);
    }

    // Everything else has to run serially or with the legacy runner
    // TODO(zundel): Attempt to refactor so we can dump runLegacy all together.
    List<Spec> legacySpecs = ImmutableList.copyOf(filter.specs());
    failures += runLegacy(legacySpecs, core);

    return failures;
  }

  private int runConcurrentTests(JUnitCore core, SpecSet specSet, Concurrency concurrency)
      throws InitializationError {
    Computer junitComputer = new ConcurrentComputer(concurrency, parallelThreads);
    Class<?>[] classes = specSet.extract(concurrency).classes();
    CustomAnnotationBuilder builder =
        new CustomAnnotationBuilder(numRetries, swappableErr.getOriginal());
    Runner suite = junitComputer.getSuite(builder, classes);
    return core.run(Request.runner(suite)).getFailureCount();
  }

  private int runLegacy(Collection<Spec> parsedTests, JUnitCore core) throws InitializationError {
    List<Request> requests = legacyParseRequests(swappableErr.getOriginal(), parsedTests);
    if (numTestShards > 0) {
      requests = setFilterForTestShard(requests);
    }

    if (this.parallelThreads > 1) {
      ConcurrentCompositeRequestRunner concurrentRunner = new ConcurrentCompositeRequestRunner(
          requests, this.defaultConcurrency, this.parallelThreads);
      if (failFast) {
        return core.run(new FailFastRunner(concurrentRunner)).getFailureCount();
      } else {
        return core.run(concurrentRunner).getFailureCount();
      }
    }

    int failures = 0;
    Result result;
    for (Request request : requests) {
      if (failFast) {
        result = core.run(new FailFastRunner(request.getRunner()));
      } else {
        result = core.run(request);
      }
      failures += result.getFailureCount();
    }
    return failures;
  }

  private List<Request> legacyParseRequests(PrintStream err, Collection<Spec> specs) {
    Set<TestMethod> testMethods = Sets.newLinkedHashSet();
    Set<Class<?>> classes = Sets.newLinkedHashSet();
    for (Spec spec: specs) {
      if (spec.getMethods().isEmpty()) {
        classes.add(spec.getSpecClass());
      } else {
        for (String method : spec.getMethods()) {
          testMethods.add(new TestMethod(spec.getSpecClass(), method));
        }
      }
    }

    List<Request> requests = Lists.newArrayList();
    if (!classes.isEmpty()) {
      if (this.perTestTimer || this.parallelThreads > 1) {
        for (Class<?> clazz : classes) {
          if (legacyShouldRunParallelMethods(clazz)) {
            if (ScalaTestUtil.isScalaTestTest(clazz)) {
              // legacy and scala doesn't work easily.  just adding the class
              requests.add(new AnnotatedClassRequest(clazz, numRetries, err));
            } else {
              testMethods.addAll(TestMethod.fromClass(clazz));
            }
          } else {
            requests.add(new AnnotatedClassRequest(clazz, numRetries, err));
          }
        }
      } else {
        // The code below does what the original call
        // requests.add(Request.classes(classes.toArray(new Class<?>[classes.size()])));
        // does, except that it instantiates our own builder, needed to support retries.
        try {
          CustomAnnotationBuilder builder =
              new CustomAnnotationBuilder(numRetries, err);
          Runner suite = new Computer().getSuite(
              builder, classes.toArray(new Class<?>[classes.size()]));
          requests.add(Request.runner(suite));
        } catch (InitializationError e) {
          throw new RuntimeException(
              "Internal error: Suite constructor, called as above, should always complete");
        }
      }
    }
    for (TestMethod testMethod : testMethods) {
      requests.add(new AnnotatedClassRequest(testMethod.clazz, numRetries, err)
          .filterWith(Description.createTestDescription(testMethod.clazz, testMethod.name)));
    }
    return requests;
  }

  private boolean legacyShouldRunParallelMethods(Class<?> clazz) {
    if (!Util.isRunnable(clazz)) {
      return false;
    }
    // The legacy runner makes Requests out of each individual method in a class. This isn't
    // designed to work for JUnit3 and isn't appropriate for custom runners.
    if (Util.isJunit3Test(clazz) || Util.isUsingCustomRunner(clazz)) {
      return false;
    }

    // TestSerial and TestParallel take precedence over the default concurrency command
    // line parameter
    if (clazz.isAnnotationPresent(TestSerial.class)
        || clazz.isAnnotationPresent(TestParallel.class)) {
      return false;
    }

    return this.defaultConcurrency.shouldRunMethodsParallel();
  }

  /**
   * Using JUnit4 test filtering mechanism, replaces the provided list of requests with
   * the one where each request has a filter attached. The filters are used to run only
   * one test shard, i.e. every Mth test out of N (testShard and numTestShards fields).
   */
  private List<Request> setFilterForTestShard(List<Request> requests) {
    // The filter below can be called multiple times for the same test, at least
    // when parallelThreads is true. To maintain the stable "run - not run" test status,
    // we determine it once, when the test is seen for the first time (always in serial
    // order), and save it in testToRunStatus table.
    class TestFilter extends Filter {
      private int testIdx;
      private Map<String, Boolean> testToRunStatus = Maps.newHashMap();

      @Override
      public boolean shouldRun(Description desc) {
        if (desc.isSuite()) {
          return true;
        }
        String descString = Util.getPantsFriendlyDisplayName(desc);
        // Note that currently even when parallelThreads is true, the first time this
        // is called in serial order, by our own iterator below.
        synchronized (this) {
          Boolean shouldRun = testToRunStatus.get(descString);
          if (shouldRun != null) {
            return shouldRun;
          } else {
            shouldRun = testIdx % numTestShards == testShard;
            testIdx++;
            testToRunStatus.put(descString, shouldRun);
            return shouldRun;
          }
        }
      }

      @Override
      public String describe() {
        return "Filters a static subset of test methods";
      }
    }

    class AlphabeticComparator implements Comparator<Description> {
      @Override
      public int compare(Description o1, Description o2) {
        return Util.getPantsFriendlyDisplayName(o1).compareTo(Util.getPantsFriendlyDisplayName(o2));
      }
    }

    TestFilter testFilter = new TestFilter();
    AlphabeticComparator alphaComp = new AlphabeticComparator();
    ArrayList<Request> filteredRequests = new ArrayList<Request>(requests.size());
    for (Request request : requests) {
      filteredRequests.add(request.sortWith(alphaComp).filterWith(testFilter));
    }
    // This will iterate over all of the test serially, calling shouldRun() above.
    // It's needed to guarantee stable sharding in all situations.
    for (Request request : filteredRequests) {
      request.getRunner().getDescription();
    }
    return filteredRequests;
  }

  /**
   * Launcher for JUnitConsoleRunner.
   *
   * @param args options from the command line
   */
  public static void main(String[] args) {
    /**
     * Command line option bean.
     */
    class Options {
      @Option(name = "-fail-fast", usage = "Causes the test suite run to fail fast.")
      private boolean failFast;

      @Option(name = "-output-mode", usage = "Specify what part of output should be passed " +
          "to stdout. In case of FAILURE_ONLY and parallel tests execution " +
          "output can be partial or even wrong. (default: ALL)")
      private OutputMode outputMode = OutputMode.ALL;

      @Option(name = "-xmlreport",
              usage = "Create ant compatible junit xml report files in -outdir.")
      private boolean xmlReport;

      @Option(name = "-outdir",
              usage = "Directory to output test captures too.")
      private File outdir = new File(System.getProperty("java.io.tmpdir"));

      @Option(name = "-per-test-timer",
          usage = "Show a description of each test and timer for each test class.")
      private boolean perTestTimer;

      // TODO(zundel): This argument is deprecated, remove in a future release
      @Option(name = "-default-parallel",
          usage = "DEPRECATED: use -default-concurrency instead.\n"
              + "Whether to run test classes without @TestParallel or @TestSerial in parallel.")
      private boolean defaultParallel;

      @Option(name = "-default-concurrency",
          usage = "Specify how to parallelize running tests.\n"
          + "Use -use-experimental-runner for PARALLEL_METHODS and PARALLEL_CLASSES_AND_METHODS")
      private Concurrency defaultConcurrency;

      private int parallelThreads = 0;

      @Option(name = "-parallel-threads",
          usage = "Number of threads to execute tests in parallel. Must be positive, "
              + "or 0 to set automatically.")
      public void setParallelThreads(int parallelThreads) {
        if (parallelThreads < 0) {
          throw new InvalidCmdLineArgumentException(
              "-parallel-threads", parallelThreads, "-parallel-threads cannot be negative");
        }
        this.parallelThreads = parallelThreads;
        if (parallelThreads == 0) {
          int availableProcessors = Runtime.getRuntime().availableProcessors();
          this.parallelThreads = availableProcessors;
          System.err.printf("Auto-detected %d processors, using -parallel-threads=%d\n",
              availableProcessors, this.parallelThreads);
        }
      }

      private int testShard;
      private int numTestShards;

      @Option(name = "-test-shard",
          usage = "Subset of tests to run, in the form M/N, 0 <= M < N. For example, 1/3 means "
                  + "run tests number 2, 5, 8, 11, ...")
      public void setTestShard(String shard) {
        String errorMsg = "-test-shard should be in the form M/N";
        int slashIdx = shard.indexOf('/');
        if (slashIdx < 0) {
          throw new InvalidCmdLineArgumentException("-test-shard", shard, errorMsg);
        }
        try {
          this.testShard = Integer.parseInt(shard.substring(0, slashIdx));
          this.numTestShards = Integer.parseInt(shard.substring(slashIdx + 1));
        } catch (NumberFormatException ex) {
          throw new InvalidCmdLineArgumentException("-test-shard", shard, errorMsg);
        }
        if (testShard < 0 || numTestShards <= 0 || testShard >= numTestShards) {
          throw new InvalidCmdLineArgumentException(
              "-test-shard", shard, "0 <= M < N is required in -test-shard M/N");
        }
      }

      private int numRetries;

      @Option(name = "-num-retries",
          usage = "Number of attempts to retry each failing test, 0 by default")
      public void setNumRetries(int numRetries) {
        if (numRetries < 0) {
          throw new InvalidCmdLineArgumentException(
              "-num-retries", numRetries, "-num-retries cannot be negative");
        }
        this.numRetries = numRetries;
      }

      @Argument(usage = "Names of junit test classes or test methods to run.  Names prefixed "
                        + "with @ are considered arg file paths and these will be loaded and the "
                        + "whitespace delimited arguments found inside added to the list",
                required = true,
                metaVar = "TESTS",
                handler = StringArrayOptionHandler.class)
      private String[] tests = {};

      @Option(name="-use-experimental-runner",
          usage="Use the experimental runner that has support for parallel methods")
      private boolean useExperimentalRunner = false;
    }

    Options options = new Options();
    CmdLineParser parser = new CmdLineParser(options);
    try {
      parser.parseArgument(args);
    } catch (CmdLineException e) {
      parser.printUsage(System.err);
      exit(1);
    } catch (InvalidCmdLineArgumentException e) {
      parser.printUsage(System.err);
      exit(1);
    }

    options.defaultConcurrency = computeConcurrencyOption(options.defaultConcurrency,
        options.defaultParallel);

    ConsoleRunnerImpl runner =
        new ConsoleRunnerImpl(options.failFast,
            options.outputMode,
            options.xmlReport,
            options.perTestTimer,
            options.outdir,
            options.defaultConcurrency,
            options.parallelThreads,
            options.testShard,
            options.numTestShards,
            options.numRetries,
            options.useExperimentalRunner,
            // NB: Buffering helps speedup output-heavy tests.
            new PrintStream(new BufferedOutputStream(System.out), true),
            new PrintStream(new BufferedOutputStream(System.err), true));

    List<String> tests = Lists.newArrayList();
    for (String test : options.tests) {
      if (test.startsWith("@")) {
        try {
          String argFileContents = Files.toString(new File(test.substring(1)), Charsets.UTF_8);
          tests.addAll(Arrays.asList(argFileContents.split("\\s+")));
        } catch (IOException e) {
          System.err.printf("Failed to load args from arg file %s: %s\n", test, e.getMessage());
          exit(1);
        }
      } else {
        tests.add(test);
      }
    }
    runner.run(tests);
  }

  /**
   * Used to convert the legacy -default-parallel option to the new
   * style -default-concurrency values
   */
  @VisibleForTesting
  static Concurrency computeConcurrencyOption(Concurrency defaultConcurrency,
      boolean defaultParallel) {

    if (defaultConcurrency != null) {
      // -default-concurrency option present - use it.
      return defaultConcurrency;
    }

    // Fall Back to using -default-parallel
    if (!defaultParallel) {
      return Concurrency.SERIAL;
    }
    return Concurrency.PARALLEL_CLASSES;
  }

  private static void exit(int code) {
    if (callSystemExitOnFinish) {
      // We're a main - its fine to exit.
      System.exit(code);
    } else {
      if (code != 0) {
        throw new RuntimeException("ConsoleRunner exited with status " + code);
      }
    }
  }

  // ---------------------------- For testing only ---------------------------------

  public static void setCallSystemExitOnFinish(boolean exitOnFinish) {
    callSystemExitOnFinish = exitOnFinish;
  }

  public static void addTestListener(RunListener listener) {
    testListener = listener;
  }
}
