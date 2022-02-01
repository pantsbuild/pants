import MenuOpenIcon from '@mui/icons-material/MenuOpen';
import { Box, Stack, AppBar, Toolbar, IconButton } from '@mui/material';

// ----------------------------------------------------------------------

type Props = {
  onOpenSidebar: () => void;
};

export default function ExplorerNavbar({ onOpenSidebar }: Props) {
  return (
    <div>
      <IconButton onClick={onOpenSidebar} sx={{ mr: 1, color: 'text.primary' }}>
        <MenuOpenIcon />
      </IconButton>

      <Box sx={{ flexGrow: 1 }} />
      <Stack direction="row" alignItems="center" spacing={{ xs: 0.5, sm: 1.5 }}>
          {/*
              <LanguagePopover />
              <NotificationsPopover />
              <AccountPopover />
            */}
      </Stack>
    </div>
  );
}
