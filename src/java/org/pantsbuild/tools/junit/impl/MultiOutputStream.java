// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.IOException;
import java.io.OutputStream;

public class MultiOutputStream extends OutputStream {
  private final OutputStream[] streams;

  public MultiOutputStream(OutputStream... streams) {
    this.streams = streams;
  }

  @Override
  public void write(int b) throws IOException {
    for (OutputStream stream : streams) {
      stream.write(b);
    }
  }

  @Override
  public void write(byte[] b) throws IOException {
    for (OutputStream stream : streams) {
      stream.write(b);
    }
  }

  @Override
  public void write(byte[] b, int off, int len) throws IOException {
    for (OutputStream stream : streams) {
      stream.write(b, off, len);
    }
  }

  @Override
  public void flush() throws IOException {
    for (OutputStream stream : streams) {
      stream.flush();
    }
  }

  @Override
  public void close() throws IOException {
    for (OutputStream stream : streams) {
      stream.close();
    }
  }
}
