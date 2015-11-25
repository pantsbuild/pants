// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.io.ByteArrayOutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.google.common.base.Charsets;
import com.google.common.base.Preconditions;
import com.google.common.base.Predicate;
import com.google.common.collect.Iterables;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.google.common.collect.Sets;
import com.google.common.io.Closeables;
import com.google.common.io.Files;

import org.apache.commons.io.output.TeeOutputStream;
import org.junit.runner.Computer;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.RunWith;
import org.junit.runner.Runner;
import org.junit.runner.manipulation.Filter;
import org.junit.runner.notification.Failure;
import org.junit.runners.model.InitializationError;
import org.kohsuke.args4j.Argument;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.spi.StringArrayOptionHandler;

import org.pantsbuild.args4j.InvalidCmdLineArgumentException;
import org.pantsbuild.tools.junit.withretry.AllDefaultPossibilitiesBuilderWithRetry;

/**
 * An alternative to {@link JUnitCore} with stream capture and junit-report xml output capabilities.
 */
public class ConsoleRunnerImpl {
  private static final SwappableStream<PrintStream> SWAPPABLE_OUT =
      new SwappableStream<PrintStream>(System.out);

  private static final SwappableStream<PrintStream> SWAPPABLE_ERR =
      new SwappableStream<PrintStream>(System.err);

  /** Should be set to false for unit testing via {@link #setCallSystemExitOnFinish} */
  private static boolean callSystemExitOnFinish = true;
  /** Intended to be used in unit testing this class */
  private static int exitStatus;

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
  static class StreamCapturingListener extends ForwardingListener implements StreamSource {
    private final Map<Class<?>, StreamCapture> suiteCaptures = Maps.newHashMap();
    private final Map<Description, InMemoryStreamCapture> caseCaptures = Maps.newHashMap();

    private final File outdir;
    private final OutputMode outputMode;

    StreamCapturingListener(File outdir, OutputMode outputMode) {
      this.outdir = outdir;
      this.outputMode = outputMode;
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
          SWAPPABLE_OUT.swap(new TeeOutputStream(SWAPPABLE_OUT.getOriginal(), suiteOut));
          SWAPPABLE_ERR.swap(new TeeOutputStream(SWAPPABLE_ERR.getOriginal(), suiteErr));
          break;
        case FAILURE_ONLY:
          InMemoryStreamCapture caseCapture = new InMemoryStreamCapture();
          caseCaptures.put(description, caseCapture);
          SWAPPABLE_OUT.swap(new TeeOutputStream(caseCapture.getOutputStream(), suiteOut));
          SWAPPABLE_ERR.swap(new TeeOutputStream(caseCapture.getErrorStream(), suiteErr));
          break;
        case NONE:
          SWAPPABLE_OUT.swap(suiteOut);
          SWAPPABLE_ERR.swap(suiteErr);
          break;
        default:
          throw new IllegalStateException();
      }

      super.testStarted(description);
    }

    @Override
    public void testFailure(Failure failure) throws Exception {
      if (outputMode == OutputMode.FAILURE_ONLY) {
        InMemoryStreamCapture capture = caseCaptures.remove(failure.getDescription());
        capture.close();
        SWAPPABLE_OUT.getOriginal().append(new String(capture.readOut()));
        SWAPPABLE_ERR.getOriginal().append(new String(capture.readErr()));
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

  enum OutputMode {
    ALL, FAILURE_ONLY, NONE
  }

  private static final Pattern METHOD_PARSER = Pattern.compile("^([^#]+)#([^#]+)$");

  private final boolean failFast;
  private final OutputMode outputMode;
  private final boolean xmlReport;
  private final File outdir;
  private final boolean perTestTimer;
  private final boolean defaultParallel;
  private final int parallelThreads;
  private final int testShard;
  private final int numTestShards;
  private final int numRetries;

  ConsoleRunnerImpl(
      boolean failFast,
      OutputMode outputMode,
      boolean xmlReport,
      boolean perTestTimer,
      File outdir,
      boolean defaultParallel,
      int parallelThreads,
      int testShard,
      int numTestShards,
      int numRetries) {

    this.failFast = failFast;
    this.outputMode = outputMode;
    this.xmlReport = xmlReport;
    this.perTestTimer = perTestTimer;
    this.outdir = outdir;
    this.defaultParallel = defaultParallel;
    this.parallelThreads = parallelThreads;
    this.testShard = testShard;
    this.numTestShards = numTestShards;
    this.numRetries = numRetries;
  }

  void run(Iterable<String> tests) {
    System.setOut(new PrintStream(SWAPPABLE_OUT));
    System.setErr(new PrintStream(SWAPPABLE_ERR));

    List<Request> requests =
        parseRequests(SWAPPABLE_OUT.getOriginal(), SWAPPABLE_ERR.getOriginal(), tests);

    if (numTestShards > 0) {
      requests = setFilterForTestShard(requests);
    }

    JUnitCore core = new JUnitCore();
    final AbortableListener abortableListener = new AbortableListener(failFast) {
      @Override protected void abort(Result failureResult) {
        exit(failureResult.getFailureCount());
      }
    };
    core.addListener(abortableListener);

    if (xmlReport) {
      if (!outdir.exists()) {
        if (!outdir.mkdirs()) {
          throw new IllegalStateException("Failed to create output directory: " + outdir);
        }
      }
      StreamCapturingListener streamCapturingListener =
        new StreamCapturingListener(outdir, outputMode);
      abortableListener.addListener(streamCapturingListener);

      AntJunitXmlReportListener xmlReportListener =
          new AntJunitXmlReportListener(outdir, streamCapturingListener);
      abortableListener.addListener(xmlReportListener);
    }

    // TODO: Register all listeners to core instead of to abortableListener because
    // abortableListener gets removed when one of the listener throws exceptions in
    // RunNotifier.java. Other listeners should not get removed.
    if (perTestTimer) {
      abortableListener.addListener(new PerTestConsoleListener(SWAPPABLE_OUT.getOriginal()));
    } else {
      core.addListener(new ConsoleListener(SWAPPABLE_OUT.getOriginal()));
    }

    // Wrap test execution with registration of a shutdown hook that will ensure we
    // never exit silently if the VM does.
    final Thread abnormalExitHook =
        createAbnormalExitHook(abortableListener, SWAPPABLE_OUT.getOriginal());
    Runtime.getRuntime().addShutdownHook(abnormalExitHook);
    int failures = 0;
    try {
      if (this.parallelThreads > 1) {
        ConcurrentCompositeRequest request = new ConcurrentCompositeRequest(
            requests, this.defaultParallel, this.parallelThreads);
        failures = core.run(request).getFailureCount();
      } else {
        for (Request request : requests) {
          Result result = core.run(request);
          failures += result.getFailureCount();
        }
      }
    } catch (InitializationError initializationError) {
      failures = 1;
    } finally {
      // If we're exiting via a thrown exception, we'll get a better message by letting it
      // propagate than by halt()ing.
      Runtime.getRuntime().removeShutdownHook(abnormalExitHook);
    }
    exit(failures);
  }


  /**
   * Returns a thread that records a system exit to the listener, and then halts(1).
   */
  private Thread createAbnormalExitHook(final AbortableListener listener, final PrintStream out) {
    Thread abnormalExitHook = new Thread() {
      @Override public void run() {
        try {
          listener.abort(new UnknownError("Abnormal VM exit - test crashed."));
        // We want to trap and log no matter why abort failed for a better end user message.
        // SUPPRESS CHECKSTYLE RegexpSinglelineJava
        } catch (Exception e) {
          out.println(e);
          e.printStackTrace(out);
        }
        // This error might be a call to `System.exit(0)`, which we definitely do
        // not want to go unnoticed.
        out.println("FATAL: VM exiting uncleanly.");
        out.flush();
        Runtime.getRuntime().halt(1);
      }
    };
    return abnormalExitHook;
  }

  private List<Request> parseRequests(PrintStream out, PrintStream err, Iterable<String> specs) {
    /**
     * Datatype representing an individual test method.
     */
    class TestMethod {
      private final Class<?> clazz;
      private final String name;
      TestMethod(Class<?> clazz, String name) {
        this.clazz = clazz;
        this.name = name;
      }
    }
    Set<TestMethod> testMethods = Sets.newLinkedHashSet();
    Set<Class<?>> classes = Sets.newLinkedHashSet();
    for (String spec : specs) {
      Matcher matcher = METHOD_PARSER.matcher(spec);
      try {
        if (matcher.matches()) {
          Class<?> testClass = loadClass(matcher.group(1));
          if (isTest(testClass)) {
            String method = matcher.group(2);
            testMethods.add(new TestMethod(testClass, method));
          }
        } else {
          Class<?> testClass = loadClass(spec);
          if (isTest(testClass)) {
            classes.add(testClass);
          }
        }
      } catch (NoClassDefFoundError e) {
        notFoundError(spec, out, e);
      } catch (ClassNotFoundException e) {
        notFoundError(spec, out, e);
      } catch (LinkageError e) {
        // Any of a number of runtime linking errors can occur when trying to load a class,
        // fail with the test spec so the class failing to link is known.
        notFoundError(spec, out, e);
      // See the comment below for justification.
      // SUPPRESS CHECKSTYLE RegexpSinglelineJava
      } catch (RuntimeException e) {
        // The class may fail with some variant of RTE in its static initializers, trap these
        // and dump the bad spec in question to help narrow down issue.
        notFoundError(spec, out, e);
      }
    }
    List<Request> requests = Lists.newArrayList();

    if (!classes.isEmpty()) {
      if (this.perTestTimer || this.parallelThreads > 1) {
        for (Class<?> clazz : classes) {
          requests.add(new AnnotatedClassRequest(clazz, numRetries, err));
        }
      } else {
        // The code below does what the original call
        // requests.add(Request.classes(classes.toArray(new Class<?>[classes.size()])));
        // does, except that it instantiates our own builder, needed to support retries
        try {
          AllDefaultPossibilitiesBuilderWithRetry builder =
              new AllDefaultPossibilitiesBuilderWithRetry(numRetries, err);
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

  // Loads classes without initializing them.  We just need the type, annotations and method
  // signatures, none of which requires initialization.
  private Class<?> loadClass(String name) throws ClassNotFoundException {
    return Class.forName(name, /* initialize = */ false, getClass().getClassLoader());
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
      private HashMap<String, Boolean> testToRunStatus = new HashMap<String, Boolean>();

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
    for (Request request: requests) {
      filteredRequests.add(request.sortWith(alphaComp).filterWith(testFilter));
    }
    // This will iterate over all of the test serially, calling shouldRun() above.
    // It's needed to guarantee stable sharding in all situations.
    for (Request request: filteredRequests) {
      request.getRunner().getDescription();
    }
    return filteredRequests;
  }

  private void notFoundError(String spec, PrintStream out, Throwable t) {
    out.printf("FATAL: Error during test discovery for %s: %s\n", spec, t);
    throw new RuntimeException("Classloading error during test discovery for " + spec, t);
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

      // TODO: make -output-mode required after removing -suppress-output option
      @Option(name = "-suppress-output", usage = "Deprecated, will be removed after 0.6.4 " +
          "release, use -output-mode instead. Suppresses test output.")
      private boolean suppressOutput;

      @Option(name = "-output-mode", usage = "Specify what part of output should be passed " +
          "to stdout. In case of FAILURE_ONLY and parallel tests execution " +
          "output can be partial or even wrong. (default: ALL)")
      private OutputMode outputMode;

      @Option(name = "-xmlreport",
              usage = "Create ant compatible junit xml report files in -outdir.")
      private boolean xmlReport;

      @Option(name = "-outdir",
              usage = "Directory to output test captures too.")
      private File outdir = new File(System.getProperty("java.io.tmpdir"));

      @Option(name = "-per-test-timer",
          usage = "Show a description of each test and timer for each test class.")
      private boolean perTestTimer;

      @Option(name = "-default-parallel",
          usage = "Whether to run test classes without @TestParallel or @TestSerial in parallel.")
      private boolean defaultParallel;

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

    OutputMode outputMode;
    if (options.outputMode != null) {
      outputMode = options.outputMode;
    } else {
      outputMode = options.suppressOutput ? OutputMode.NONE : OutputMode.ALL;
    }

    ConsoleRunnerImpl runner =
        new ConsoleRunnerImpl(options.failFast,
            outputMode,
            options.xmlReport,
            options.perTestTimer,
            options.outdir,
            options.defaultParallel,
            options.parallelThreads,
            options.testShard,
            options.numTestShards,
            options.numRetries);

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

  public static final Predicate<Constructor<?>> IS_PUBLIC_CONSTRUCTOR =
      new Predicate<Constructor<?>>() {
        @Override public boolean apply(Constructor<?> constructor) {
          return Modifier.isPublic(constructor.getModifiers());
        }
      };

  private static final Predicate<Method> IS_ANNOTATED_TEST_METHOD = new Predicate<Method>() {
    @Override public boolean apply(Method method) {
      return Modifier.isPublic(method.getModifiers())
          && method.isAnnotationPresent(org.junit.Test.class);
    }
  };

  private static boolean isTest(final Class<?> clazz) {
    // Must be a public concrete class to be a runnable junit Test.
    if (clazz.isInterface()
        || Modifier.isAbstract(clazz.getModifiers())
        || !Modifier.isPublic(clazz.getModifiers())) {
      return false;
    }

    // The class must have some public constructor to be instantiated by the runner being used
    if (!Iterables.any(Arrays.asList(clazz.getConstructors()), IS_PUBLIC_CONSTRUCTOR)) {
      return false;
    }

    // Support junit 3.x Test hierarchy.
    if (junit.framework.Test.class.isAssignableFrom(clazz)) {
      return true;
    }

    // Support classes using junit 4.x custom runners.
    if (clazz.isAnnotationPresent(RunWith.class)) {
      return true;
    }

    // Support junit 4.x @Test annotated methods.
    return Iterables.any(Arrays.asList(clazz.getMethods()), IS_ANNOTATED_TEST_METHOD);
  }

  private static void exit(int code) {
    exitStatus = code;
    if (callSystemExitOnFinish) {
      // We're a main - its fine to exit.
      // SUPPRESS CHECKSTYLE RegexpSinglelineJava
      System.exit(code);
    } else {
      if (code != 0) {
        throw new RuntimeException("ConsoleRunner exited with status " + code);
      }
    }
  }

  // ---------------------------- For testing only ---------------------------------

  static void setCallSystemExitOnFinish(boolean v) {
    callSystemExitOnFinish = v;
  }

  static int getExitStatus() {
    return exitStatus;
  }

  static void setExitStatus(int v) {
    exitStatus = v;
  }
}
