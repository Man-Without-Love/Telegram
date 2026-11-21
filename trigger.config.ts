import { defineConfig } from "@trigger.dev/sdk";
import { pythonExtension } from "@trigger.dev/python/extension";

export default defineConfig({
  project: "tr_dev_sk_7HpO3TiYU7USajJ4f23fwaPQ",
  maxDuration: 1200,
  build: {
    extensions: [
      pythonExtension({
        requirementsFile: "./requirements.txt",
        scripts: ["./python/**/*.py"],
      }),
    ],
  },
});
