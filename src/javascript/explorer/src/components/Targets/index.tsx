import { useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Masonry from '@mui/lab/Masonry';

import { useTargets } from "../../lib/target-data";
import Loading from "../Loading";
import Error from "../Error";
import RefetchButton from "../RefetchButton";

import Target from "./Target";


export const Targets = () => {
  const theme = useTheme();
  const large = useMediaQuery(theme.breakpoints.up('xl'));
  const small = useMediaQuery(theme.breakpoints.down('lg'));
  const masonry_columns = large ? 3 : small ? 1 : 2;
  
  const [targets, loading, error, refetch] = useTargets(["address", "targetType", "fields"]);

  if (!targets.length) {
    // Skeleton placeholders..
    targets.push(undefined, undefined, undefined, undefined, undefined);
  }

  const show_targets = (targets.length > 100) ? targets.slice(0, 50) : targets;

  const content = targets.slice(0, 50).map(
    (target, index) => (
      <Target key={index} target={target} />
    )
  );

  return (
    <>
      <Stack direction="row" justifyContent="space-between">
        {!loading && !error && <Typography>Showing {show_targets.length} of {targets.length} targets</Typography>}
        {loading && <Loading title="Loading targets data..." />}
        {error && <Error title="Failed to load target data" error={error.toString()} />}
        {!loading && <RefetchButton onClick={refetch} />}
      </Stack>
      <Masonry columns={masonry_columns} spacing={3}>
        {content}
      </Masonry>
    </>
  );
};


export default Targets;
