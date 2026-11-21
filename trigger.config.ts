import { defineConfig } from "@trigger.dev/sdk";
import { pythonExtension } from "@trigger.dev/python/extension";

export default defineConfig({
  project: "<YOUR_PROJECT_REF>",
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
