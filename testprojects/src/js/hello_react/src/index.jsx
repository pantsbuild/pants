import React from "react";
import Server from "react-dom/server";
import HelloPage from "@app/App";

console.log(Server.renderToString(<HelloPage />));
