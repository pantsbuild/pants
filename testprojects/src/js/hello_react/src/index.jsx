import React from "react";
import Server from "react-dom/server";
import HelloPage from "./App.jsx";

console.log(Server.renderToString(<HelloPage />));
