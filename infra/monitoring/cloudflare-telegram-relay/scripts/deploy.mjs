import { spawnSync } from "node:child_process";

const name = String(process.env.PRODUCTION_RELAY_NAME || "");
if (!/^[a-z0-9](?:[a-z0-9-]{14,61}[a-z0-9])$/.test(name)) {
  throw new Error("PRODUCTION_RELAY_NAME must be a private 16-63 character Worker name");
}

const executable = process.platform === "win32" ? "wrangler.cmd" : "wrangler";
const result = spawnSync(executable, ["deploy", "--name", name], {
  cwd: process.cwd(),
  env: process.env,
  shell: process.platform === "win32",
  stdio: "inherit",
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
