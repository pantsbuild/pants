// This import should work via pnpm link: protocol
import { childFunction } from "child-pkg";

export function parentFunction(): string {
  return `Parent calling: ${childFunction()}`;
}
