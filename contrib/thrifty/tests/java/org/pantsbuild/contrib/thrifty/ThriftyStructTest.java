// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.thrifty;

import org.junit.Test;
import org.pantsbuild.contrib.thrifty.common.ClientLog;
import org.pantsbuild.contrib.thrifty.common.Common;

import static org.junit.Assert.assertEquals;

public class ThriftyStructTest {

    @Test
    public void testThriftyStruct() {
        Common common = new Common.Builder()
                .timestamp(1L)
                .hostname("fake")
                .build();
        ClientLog clientLog = new ClientLog.Builder()
                .common(common)
                .message("fake_message")
                .build();
        assertEquals(clientLog.toString(),
                "ClientLog{common=Common{timestamp=1, hostname=fake}, message=fake_message}");
    }
}
