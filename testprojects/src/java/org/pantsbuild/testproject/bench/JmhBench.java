package org.pantsbuild.testproject.bench;

import org.openjdk.jmh.annotations.Benchmark;
import org.openjdk.jmh.runner.Runner;
import org.openjdk.jmh.runner.RunnerException;
import org.openjdk.jmh.runner.options.Options;
import org.openjdk.jmh.runner.options.OptionsBuilder;

/**
 * This is modified from the helloworld example from
 * http://hg.openjdk.java.net/code-tools/jmh/file/cb9aa824b55a/jmh-samples
 */
public class JmhBench {
  @Benchmark
  public void wellHelloThere() {
    // this method was intentionally left blank.
  }

  public static void main(String[] args) throws RunnerException {
    Options opt = new OptionsBuilder()
        .include(JmhBench.class.getSimpleName())
        .forks(1)
        .build();
    new Runner(opt).run();
  }
}