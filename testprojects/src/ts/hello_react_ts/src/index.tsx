import React from "react";
import Server from "react-dom/server";
import App from "@app/App";

console.log(Server.renderToString(<App />));
