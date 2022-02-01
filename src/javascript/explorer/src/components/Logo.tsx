import { FunctionComponent } from "react";

import { Box } from '@mui/material';

// ----------------------------------------------------------------------

interface Props {
  sx?: object,
};

export default ({ sx = {} }: Props) => {
  return <Box component="img" src="/static/logo.svg" sx={{ width: 40, height: 40, ...sx }} />;
};
