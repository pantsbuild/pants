// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit;

import java.io.*;

public class MultiOutputStream extends PrintStream {
  private OutputStream outputStream;

  public MultiOutputStream(OutputStream out, OutputStream outputStream) {
    super(out, false);
    this.outputStream = outputStream;
  }

  @Override
  public void write(int b) {
    super.write(b);
    try {
      outputStream.write(b);
    } catch (IOException e) {
      setError();
    }
  }

  @Override
  public void write(byte[] b) throws IOException{
    super.write(b);
    outputStream.write(b);
  }

  @Override
  public void write(byte[] b, int off, int len){
    super.write(b, off, len);
    try {
      outputStream.write(b);
    } catch (IOException e){
      setError();
    }
  }

  @Override
  public void flush() {
    super.flush();
    try {
      outputStream.flush();;
    } catch (IOException e){
      setError();
    }
  }

  @Override
  public void close(){
    super.close();
    try {
      outputStream.close();
    } catch (IOException e){
      setError();
    }
  }
}
