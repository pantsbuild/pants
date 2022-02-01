import { useState } from 'react';
import { NavLink as RouterLink, matchPath, useLocation } from 'react-router-dom';
import { Box, List, Collapse, ListItemText, ListItemIcon, ListItemButton } from '@mui/material';

// ----------------------------------------------------------------------

export interface NavConfig {
  title: string;
  path: string;
  icon: React.ReactNode;
  info?: React.ReactNode;
  children?: NavConfig[];
};

// ----------------------------------------------------------------------

type NavItemProps = {
  active: (path: string) => boolean;
  item: NavConfig;
};

function NavItem({ item, active }: NavItemProps) {
  const isActiveRoot = active(item.path);
  const { title, path, icon, info, children } = item;
  const [open, setOpen] = useState(isActiveRoot);

  const handleOpen = () => {
    setOpen((prev) => !prev);
  };

  if (children) {
    return (
      <>
        <div
          onClick={handleOpen}
        >
          {icon && icon}
          <ListItemText disableTypography primary={title} />
          {info && info}
        </div>

        <Collapse in={open} timeout="auto" unmountOnExit>
          <List component="div" disablePadding>
            {children.map((item) => {
              const { title, path } = item;
              const isActiveSub = active(path);

              return (
                <RouterLink
                  key={title}
                  to={path}
                >
                  <ListItemText disableTypography primary={title} />
                </RouterLink>
              );
            })}
          </List>
        </Collapse>
      </>
    );
  }

  return (
    <RouterLink
      to={path}
    >
      <div>{icon && icon}</div>
      <ListItemText disableTypography primary={title} />
      {info && info}
    </RouterLink>
  );
}

type NavSectionProps = {
  navConfig: NavConfig[];
};

export default function NavSection({ navConfig, ...other } : NavSectionProps) {
  const { pathname } = useLocation();
  const match = (path: string) => (path ? !!matchPath({ path, end: false }, pathname) : false);

  return (
    <Box {...other}>
      <List disablePadding>
        {navConfig.map((item) => (
          <NavItem key={item.title} item={item} active={match} />
        ))}
      </List>
    </Box>
  );
}
