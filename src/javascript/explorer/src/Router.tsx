import * as React from 'react';
import { Navigate, useRoutes } from "react-router-dom";
import ExplorerLayout from "./layouts/explorer";
import ExplorerHome from "./pages/ExplorerHome";
import ExplorerTargets from "./pages/ExplorerTargets";


export default function Router() {
  return useRoutes([
    {
      path: "/explorer",
      element: <ExplorerLayout />,
      children: [
        { element: <Navigate to="/explorer/home" replace /> },
        { path: "home", element: <ExplorerHome /> },
        { path: "targets", element: <ExplorerTargets /> },
      ],
    },
    { path: "/", element: <Navigate to="/explorer/home" /> },
  ]);
}
