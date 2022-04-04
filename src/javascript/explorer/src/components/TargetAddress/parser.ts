import { TargetAddress } from './types';


export const parse_address = (spec: string): TargetAddress => {
  // Adapted from Python: `pants.build_graph.address:AddessInput.parse()`.
  const spec_parts = spec.split(":", 2);
  let path_component = spec_parts[0];
  let target_component = null;
  let generated_component = null;

  if (spec_parts.length === 1) {
    const generated_parts = path_component.split("#", 2)
    if (generated_parts.length === 2) {
      [path_component, generated_component] = generated_parts;
    }
  }
  else
  {
    const generated_parts = spec_parts[1].split("#", 2)
    if (generated_parts.length === 1)  {
      target_component = generated_parts[0];
    }
    else
    {
      [target_component, generated_component] = generated_parts;
    }
  }

  return {
    path: path_component,
    name: target_component,
    generated_name: generated_component,
    default_name: path_component.split("/")[-1],
  };
};
