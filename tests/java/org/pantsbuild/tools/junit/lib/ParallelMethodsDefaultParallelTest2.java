package org.pantsbuild.tools.junit.lib;

import org.junit.Test;

/**
 * See {@link ParallelMethodsDefaultParallelTest1}
 */
public class ParallelMethodsDefaultParallelTest2 {

  @Test
  public void pmdptest21() throws Exception {
    ParallelMethodsDefaultParallelTest1.awaitLatch("pmdptest21");
  }

  @Test
  public void pmdptest22() throws Exception {
    ParallelMethodsDefaultParallelTest1.awaitLatch("pmdptest22");
  }
}
