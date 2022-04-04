import { useState } from 'react';
import { styled } from '@mui/material/styles';
// import ReactMarkdown from 'react-markdown'
import Chip from '@mui/material/Chip';
import Card, { CardProps } from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import Collapse from '@mui/material/Collapse';
import Divider from '@mui/material/Divider';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import Skeleton from '@mui/material/Skeleton';
import Stack from '@mui/material/Stack';
import AnnouncementIcon from '@mui/icons-material/Announcement';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import IconButton, { IconButtonProps } from '@mui/material/IconButton';

import ContextHelp from "components/ContextHelp";
import { TargetTypeDocs } from "components/docs/Targets";
import { TargetData, getTargetFieldValue } from "lib/target-data";
import TargetAddress from "components/TargetAddress";


type ExpandMoreProps = IconButtonProps & {
  expand: boolean;
};

const ExpandMore = styled((props: ExpandMoreProps) => {
  const { expand, ...other } = props;
  return <IconButton {...other} />;
})(({ theme, expand }) => ({
  transform: !expand ? 'rotate(0deg)' : 'rotate(180deg)',
  marginLeft: 'auto',
  transition: theme.transitions.create('transform', {
    duration: theme.transitions.duration.shortest,
  }),
}));


type TargetProps = CardProps & {
  target?: TargetData;
}

export default ({target, ...props}: TargetProps) => {
  const [expanded, setExpanded] = useState(false);
  const toggleExpanded = () => setExpanded(!expanded);

  if (!target) {
    return (
      <Skeleton variant="rectangular" height={300} />
    );
  }

  const description = getTargetFieldValue<string>(target, "description");
  const tags = getTargetFieldValue<string[]>(target, "tags");
  const dependencies = getTargetFieldValue<string[]>(target, "dependencies");
  const collapsible = dependencies && dependencies.length > 2;
  const dependencies_content = (dependencies && dependencies.length > 0) ? (
    <>
      <Divider />
      <CardActions disableSpacing>
        <Typography variant="subtitle2">
          {dependencies.length} {dependencies.length !== 1 ? "Dependencies" : "Dependency"}
        </Typography>
        {collapsible ? (
          <ExpandMore
            expand={expanded}
            onClick={toggleExpanded}
            aria-expanded={expanded}
            aria-label="show more"
          >
            <ExpandMoreIcon />
          </ExpandMore>
        ) : null }
      </CardActions>
      <Collapse in={expanded || !collapsible} collapsedSize={75}>
        <CardContent sx={{ pt: 0 }}>
          <Stack alignItems="flex-start" spacing={1}>
            {dependencies.map((dep, index) => (
              <Chip key={index} variant="outlined" label={dep} size="small" />
            ))}
          </Stack>
        </CardContent>
      </Collapse>
    </>
  ) : null;

  return (
    <Card {...props}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between">
          <TargetAddress tooltip>{target.address}</TargetAddress>
          <ContextHelp
            maxWidth="lg"
            title={(
              <div>
                <AnnouncementIcon color="primary" sx={{ mr: 2 }} />
                <code>{target.targetType}</code> reference documenation
              </div>
            )}
            help={<TargetTypeDocs alias={target.targetType} />}
          >
            <Typography color="text.secondary">
              {target.targetType}
            </Typography>
          </ContextHelp>
        </Stack>
        <Stack direction="row" spacing={1} sx={{ my: 1 }}>
          {tags && tags.map((tag, index) => (
            <Chip key={index} variant="outlined" label={tag} color="primary" size="small" />
          ))}
        </Stack>
        {description && (
          <>
            <Divider />
            {/*<ReactMarkdown>{description}</ReactMarkdown>*/}
          </>
        )}
      </CardContent>
      {dependencies_content}
    </Card>
  );
};
