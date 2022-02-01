import { useEffect } from 'react';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { Box, Link, Button, Drawer, Typography, Avatar, Stack } from '@mui/material';

import Logo from '../../components/Logo';
import NavSection from '../../components/NavSection';

import sidebarConfig from './SidebarConfig';

// ----------------------------------------------------------------------

type Props = {
  isOpenSidebar: boolean;
  onCloseSidebar: () => void;
}

export default function ExplorerSidebar({ isOpenSidebar, onCloseSidebar }: Props) {
  const { pathname } = useLocation();

  useEffect(() => {
    if (isOpenSidebar) {
      onCloseSidebar();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const renderContent = (
    <div>
      <Box sx={{ px: 2.5, py: 3 }}>
        <Box component={RouterLink} to="/" sx={{ display: 'inline-flex' }}>
          <Logo />
        </Box>
      </Box>

      <NavSection navConfig={sidebarConfig} />

      <Box sx={{ flexGrow: 1 }} />

    </div>
  );

  return (
    <div>
      <Drawer
        open={isOpenSidebar}
        onClose={onCloseSidebar}
        PaperProps={{
          //sx: { width: DRAWER_WIDTH }
        }}
      >
        {renderContent}
      </Drawer>
    </div>
  );
}
