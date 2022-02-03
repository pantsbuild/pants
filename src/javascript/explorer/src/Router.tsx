import * as React from 'react';
import { Navigate, useRoutes } from "react-router-dom";
import ExplorerLayout from "./layouts/explorer";
import ExplorerHome from "./pages/ExplorerHome";
import ExplorerTargets from "./pages/ExplorerTargets";
import ReferenceTargets from "./pages/ReferenceTargets";


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
    {
      path: "/reference",
      element: <ExplorerLayout />,
      children: [
        { path: "targets", element: <ReferenceTargets /> },
      ],
    },
    { path: "/", element: <Navigate to="/explorer/home" /> },
  ]);
}
