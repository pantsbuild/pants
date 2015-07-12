// coding=utf-8
// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.examples.hello;

import android.app.Activity;
import android.content.res.Resources;
import android.os.Bundle;
import android.widget.TextView;

public class HelloWorld extends Activity {

  @Override
  public void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    TextView textView = new TextView(this);

    String text = getResources().getString(R.string.hello);
    textView.setText(text);

    setContentView(textView);
  }
}
