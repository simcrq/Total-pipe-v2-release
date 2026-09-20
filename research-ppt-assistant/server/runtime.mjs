export const MINIMUM_NODE_MAJOR = 22;

export function nodeMajor(version) {
  const match = String(version ?? "").trim().match(/^v?(\d+)(?:\.|$)/);
  if (!match) throw new TypeError(`Invalid Node.js version: ${version}`);
  return Number(match[1]);
}

export function assertSupportedNodeVersion(version = process.versions.node) {
  const major = nodeMajor(version);
  if (major < MINIMUM_NODE_MAJOR) {
    throw new RangeError(`Node.js >=${MINIMUM_NODE_MAJOR} is required; detected ${version}`);
  }
  return major;
}
