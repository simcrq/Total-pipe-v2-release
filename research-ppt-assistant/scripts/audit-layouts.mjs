#!/usr/bin/env node

import { auditBundledLayoutLibrary } from "../server/layout-audit.mjs";
import { assertSupportedNodeVersion } from "../server/runtime.mjs";

assertSupportedNodeVersion();

const result = await auditBundledLayoutLibrary();
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
if (result.status !== "valid") process.exitCode = 1;
