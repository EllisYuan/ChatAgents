import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const outputDirectory = path.join(frontendRoot, "src", "generated");
const outputPath = path.join(outputDirectory, "api.d.ts");
const configuredInput = process.env.OPENAPI_INPUT;
const temporaryInput = configuredInput ? null : path.join(os.tmpdir(), `chatagents-openapi-${process.pid}.json`);
const inputPath = configuredInput ? path.resolve(process.cwd(), configuredInput) : temporaryInput;

mkdirSync(outputDirectory, { recursive: true });

try {
  if (temporaryInput) {
    const uvCommand = process.platform === "win32" ? "uv.exe" : "uv";
    const schema = execFileSync(
      uvCommand,
      [
        "run",
        "--project",
        path.join(frontendRoot, "..", "backend"),
        "python",
        "-c",
        "import json; from chat_agents.main import app; print(json.dumps(app.openapi()))",
      ],
      { cwd: frontendRoot, encoding: "utf8" },
    );
    writeFileSync(temporaryInput, schema);
  }

  const openapiCli = path.join(frontendRoot, "node_modules", "openapi-typescript", "bin", "cli.js");
  execFileSync(process.execPath, [openapiCli, inputPath, "-o", outputPath], {
    cwd: frontendRoot,
    stdio: "inherit",
  });
} finally {
  if (temporaryInput) {
    rmSync(temporaryInput, { force: true });
  }
}
