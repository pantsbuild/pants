import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Box from '@mui/material/Box';

import ExplorerNavbar from './ExplorerNavbar';
import ExplorerSidebar from './ExplorerSidebar';

// ----------------------------------------------------------------------

const drawerWidth: number = 240;

export default function ExplorerLayout() {
  const [open, setOpen] = useState(false);

  return (
    <Box sx={{ display: "flex" }}>
      <ExplorerNavbar isOpenSidebar={open} onOpenSidebar={() => setOpen(true)} drawerWidth={drawerWidth} />
      <ExplorerSidebar isOpenSidebar={open} onCloseSidebar={() => setOpen(false)} drawerWidth={drawerWidth} />
      <Outlet />
    </Box>
  );
}
