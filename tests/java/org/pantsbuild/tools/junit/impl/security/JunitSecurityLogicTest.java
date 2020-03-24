package org.pantsbuild.tools.junit.impl.security;

import org.junit.Test;

import static org.hamcrest.CoreMatchers.is;
import static org.junit.Assert.assertThat;

public class JunitSecurityLogicTest {

  @Test
  public void disallowsDanglingThreadsForSuiteIfSuiteDisallowed() {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        JunitSecurityManagerConfig.SystemExitHandling.disallow,
        JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads,
        JunitSecurityManagerConfig.NetworkHandling.allowAll);
    JunitSecurityManagerLogic logic;
    logic = new JunitSecurityManagerLogic(config,
        new JunitSecurityContextLookupAndErrorCollection(config));
    assertThat(
        logic.disallowsThreadsFor(TestSecurityContext.newSuiteContext("foo")),
        is(true));
  }

  @Test
  public void allowAllIncludesSuites() {
    JunitSecurityManagerConfig config = new JunitSecurityManagerConfig(
        JunitSecurityManagerConfig.SystemExitHandling.disallow,
        JunitSecurityManagerConfig.ThreadHandling.allowAll,
        JunitSecurityManagerConfig.NetworkHandling.allowAll);
    JunitSecurityManagerLogic logic;
    logic = new JunitSecurityManagerLogic(config,
        new JunitSecurityContextLookupAndErrorCollection(config));
    assertThat(
        logic.disallowsThreadsFor(TestSecurityContext.newSuiteContext("foo")),
        is(false));
  }
}
