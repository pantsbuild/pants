// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.timeout;

import org.junit.Test;

public class SleeperTestLong {
    @Test
    public void testSleep() throws InterruptedException {
        Thread.sleep(120000);
    }
}
