// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.ivy;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.io.UnsupportedEncodingException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.CoreMatchers.not;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.junit.Assert.fail;

public class DependencyUpdateCheckerTest {
  private static final String SETTINGS_FILE_FLAG = "-settings";
  private static final String IVY_FILE_FLAG = "-ivy";
  private static final String SHOW_TRANSITIVE_FLAG = "-show-transitive";
  private static final String CONFS_FLAG = "-confs";

  private final List<String> testArgs = new ArrayList<>();

  @Before
  public void setUp() throws Exception {
    DependencyUpdateChecker.setCallSystemExitOnFinish(false);

    testArgs.clear();
    testArgs.add(SETTINGS_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivysettings.xml");
  }

  @After
  public void tearDown() throws Exception {
    DependencyUpdateChecker.setCallSystemExitOnFinish(true);
  }

  private String runDependencyUpdateChecker(List<String> args) throws Exception {
    ByteArrayOutputStream outContent = new ByteArrayOutputStream();
    PrintStream outputStream = new PrintStream(outContent);
    DependencyUpdateChecker.setLogStream(outputStream);

    DependencyUpdateChecker.main(args.toArray(new String[args.size()]));

    try {
      return outContent.toString(StandardCharsets.UTF_8.toString());
    } catch (UnsupportedEncodingException e) {
      throw new RuntimeException(e);
    }
  }

  @Test
  public void testResolve() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy.xml");

    String output = runDependencyUpdateChecker(testArgs);

    assertThat(output, containsString("Dependency updates available:"));
    assertThat(output, containsString("org#example1  1.0 -> 2.0"));
    assertThat(output, not(containsString("org#example2 (transitive)  2.0 -> 2.1")));
  }

  @Test
  public void testTransitiveDependencies() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy.xml");
    testArgs.add(SHOW_TRANSITIVE_FLAG);

    String output = runDependencyUpdateChecker(testArgs);

    assertThat(output, containsString("Dependency updates available:"));
    assertThat(output, containsString("org#example1  1.0 -> 2.0"));
    assertThat(output, containsString("org#example2 (transitive)  2.0 -> 2.1"));
  }

  @Test
  public void testDependencyThatIsMissingIvyFile() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy-dep-missing-ivy-file.xml");

    String output = runDependencyUpdateChecker(testArgs);

    assertThat(output, containsString("Dependency updates available:"));
    assertThat(output, containsString("org#example2  2.0 -> 2.1"));
  }

  @Test
  public void testExcludedConf() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy.xml");
    testArgs.add(CONFS_FLAG);
    testArgs.add("*,!default");

    String output = runDependencyUpdateChecker(testArgs);

    assertThat(output, containsString("Dependency updates available:"));
    assertThat(output, containsString("All dependencies are up to date"));
  }

  @Test
  public void testUnknownDependency() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy-unknown-dep.xml");

    try {
      runDependencyUpdateChecker(testArgs);
      fail("Expected RuntimeException");
    } catch (RuntimeException e) {
      assertThat(e.toString(), containsString("DependencyUpdateChecker exited with status"));
    }
  }

  @Test
  public void testUnknownConfigurations() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy.xml");
    testArgs.add(CONFS_FLAG);
    testArgs.add("default,unknown");

    try {
      runDependencyUpdateChecker(testArgs);
      fail("Expected IllegalArgumentException");
    } catch (IllegalArgumentException e) {
      assertThat(e.toString(), containsString("requested configuration not found"));
    }
  }

  @Test
  public void testDependencyWithInvalidIvyFile() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy-dep-with-invalid-ivy.xml");

    try {
      runDependencyUpdateChecker(testArgs);
      fail("Expected RuntimeException");
    } catch (RuntimeException e) {
      assertThat(e.toString(), containsString("DependencyUpdateChecker exited with status"));
    }
  }

  @Test
  public void testDependencyWithInvalidIvyStatus() throws Exception {
    testArgs.add(IVY_FILE_FLAG);
    testArgs.add("tests/resources/org/pantsbuild/tools/ivy/ivy-dep-with-invalid-status.xml");

    try {
      runDependencyUpdateChecker(testArgs);
      fail("Expected RuntimeException");
    } catch (RuntimeException e) {
      assertThat(e.toString(), containsString("DependencyUpdateChecker exited with status"));
    }
  }
}
