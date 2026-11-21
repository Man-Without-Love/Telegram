import { task, logger } from "@trigger.dev/sdk";
import { python } from "@trigger.dev/python";

export const tgForwarderTask = task({
  id: "tg-forwarder",
  queue: {
    name: "tg_forwarding_group",
    concurrencyLimit: 1,
  },
  run: async () => {
    logger.info("Запуск Python-скрипта пересылки Telegram -> Mail");

    const result = await python.runScript("./python/main.py", [], {
      env: {
        TG_API_ID: process.env.TG_API_ID ?? "",
        TG_API_HASH: process.env.TG_API_HASH ?? "",
        TG_SESSION: process.env.TG_SESSION ?? "",
        MAIL_SENDER: process.env.MAIL_SENDER ?? "",
        MAIL_PASS: process.env.MAIL_PASS ?? "",
        MAIL_RECEIVER: process.env.MAIL_RECEIVER ?? "",
        VPN_GIST_URL: process.env.VPN_GIST_URL ?? "",
      },
    });

    if (result.stdout) logger.info(result.stdout);
    if (result.stderr) logger.warn(result.stderr);

    return { exitCode: result.exitCode };
  },
});
      
