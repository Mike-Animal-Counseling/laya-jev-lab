// Keep telemetry disabled for development, builds and the local server.
process.env.NEXT_TELEMETRY_DISABLED = "1";
require("next/dist/bin/next");
