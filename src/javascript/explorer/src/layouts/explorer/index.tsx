import { useState } from 'react';
import { Outlet } from 'react-router-dom';

import ExplorerNavbar from './ExplorerNavbar';
import ExplorerSidebar from './ExplorerSidebar';

// ----------------------------------------------------------------------

export default function ExplorerLayout() {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <ExplorerNavbar onOpenSidebar={() => setOpen(true)} />
      <ExplorerSidebar isOpenSidebar={open} onCloseSidebar={() => setOpen(false)} />
      <div>
        <Outlet />
      </div>
    </div>
  );
}
