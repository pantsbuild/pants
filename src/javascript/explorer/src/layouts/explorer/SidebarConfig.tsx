import FeedbackIcon from "@mui/icons-material/Feedback";
import HomeIcon from "@mui/icons-material/Home";
import { NavConfig } from "../../components/NavSection";

// ----------------------------------------------------------------------

const sidebarConfig: NavConfig[] = [
  {
    title: 'Home',
    info: 'Explorer Dashboard',
    path: '/explorer/home',
    icon: <HomeIcon />,
  },
  /* {
    title: 'Not found',
    info: 'Error page',
    path: '/404',
    icon: <FeedbackIcon />,
  } */
];

export default sidebarConfig;
