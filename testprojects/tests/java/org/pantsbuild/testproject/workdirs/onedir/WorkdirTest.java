// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.workdirs.onedir;

import org.junit.Test;
import java.io.File;

import static org.junit.Assert.assertTrue;

/**
 * Ensure cwd works correctly.
 *
 * This test depends on the contents of org/pantsbuild/testproject/workdirs/twodir.
 * */
public class WorkdirTest {
    @Test
    public void testPlaceholderExists() {
        assertTrue("Could not find placeholder.txt, working directory must be wrong!",
                   new File("placeholder.txt").exists());
    }
}
