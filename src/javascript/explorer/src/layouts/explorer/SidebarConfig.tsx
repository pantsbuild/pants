import HelpCenterIcon from '@mui/icons-material/HelpCenter';
import HomeIcon from "@mui/icons-material/Home";
import TargetIcon from '@mui/icons-material/LocationSearching';
import { NavConfig } from "components/NavSection";

// ----------------------------------------------------------------------

const sidebarConfig: NavConfig[] = [
  {
    title: 'Home',
    info: 'Explorer Dashboard',
    path: '/explorer/home',
    icon: <HomeIcon />,
  },
  {
    title: 'Targets',
    info: <span><code>BUILD</code> file targets</span>,
    path: '/explorer/targets',
    icon: <TargetIcon />,
  },
  {
    title: 'Documentation',
    info: 'Reference documentation',
    path: '/reference',
    icon: <HelpCenterIcon />,
    children: [
      {
        title: 'Targets Docs',
        info: 'Field types reference',
        path: '/reference/targets',
        icon: <TargetIcon />,
      },
    ]
  },
];

export default sidebarConfig;
