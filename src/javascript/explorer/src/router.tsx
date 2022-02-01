import React from 'react';
import { Navigate, useRoutes } from "react-router-dom";
import ExplorerLayout from "./layouts/explorer";
import ExplorerHome from "./pages/ExplorerHome";


export default function Router() {
  return useRoutes([
    {
      path: "/explorer",
      element: <ExplorerLayout />,
      children: [
        { element: <Navigate to="/explorer/home" replace /> },
        { path: "home", element: <ExplorerHome /> },
      ],
    },
    { path: "/", element: <Navigate to="/explorer/home" /> },
  ]);
}
