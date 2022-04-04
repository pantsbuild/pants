import * as React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { HelmetProvider } from 'react-helmet-async';
import CssBaseline from '@mui/material/CssBaseline';
import { createTheme, ThemeProvider } from '@mui/material/styles';
import Router from "./Router";

const theme = createTheme();

//const plug_a_url = "/plugins/plug-a/349.1d02178a.chunk.js";
//const PlugA = React.lazy(() => import(plug_a_url));

export default function Explorer() {
  return (
    <HelmetProvider>
      <CssBaseline />
      <BrowserRouter>
        <ThemeProvider theme={theme}>

          {/*<React.Suspense fallback={<div>Loading...</div>}>
            <PlugA />
          </React.Suspense>*/}

          <Router />
        </ThemeProvider>
      </BrowserRouter>
    </HelmetProvider>
  );
}
