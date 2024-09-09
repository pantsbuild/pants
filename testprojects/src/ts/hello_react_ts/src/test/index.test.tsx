// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
/**
 * @jest-environment jsdom
 */

import React from "react";
import Server from "react-dom/server";

import App from "@app/App";

it("page to greet you", () => {
  const rendered = Server.renderToString(<App />);

  expect(rendered).toBe("<h1>Hello</h1><p>Hello World!</p>");
});
