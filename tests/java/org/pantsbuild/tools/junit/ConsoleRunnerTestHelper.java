package org.pantsbuild.tools.junit;

import org.hamcrest.CoreMatchers;
import org.junit.After;
import org.junit.Assert;
import org.junit.Before;

public class ConsoleRunnerTestHelper {

  @Before
  public void setUp() {
    ConsoleRunner.setCallSystemExitOnFinish(false);
    ConsoleRunner.setExitStatus(0);
    TestRegistry.reset();
  }

  @After
  public void tearDown() {
    ConsoleRunner.setCallSystemExitOnFinish(true);
    ConsoleRunner.setExitStatus(0);
  }

  protected void assertContainsTestOutput(String output) {
    Assert.assertThat(output, CoreMatchers.containsString("test41"));
    Assert.assertThat(output, CoreMatchers.containsString("start test42"));
    Assert.assertThat(output, CoreMatchers.containsString("end test42"));
  }

  protected String[] asArgsArray(String cmdLine) {
    String[] args = cmdLine.split(" ");
    for (int i = 0; i < args.length; i++) {
      if (args[i].contains("Test")) {
        args[i] = getClass().getPackage().getName() + '.' + args[i];
      }
    }
    return args;
  }
}
