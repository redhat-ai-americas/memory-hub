export interface Logger {
  info(msg: string): void;
  warn(msg: string): void;
  error(msg: string): void;
  debug(msg: string): void;
}

/**
 * Console-backed logger. opencode plugins have no host logger; console
 * output lands in the opencode server log. Prefixed so lines are findable,
 * on stderr so nothing can interleave with protocol/TUI output. `info` and
 * `debug` stay silent unless MEMORYHUB_DEBUG is set.
 */
export function createLogger(
  env: Record<string, string | undefined> = process.env,
): Logger {
  const verbose = Boolean(env.MEMORYHUB_DEBUG);
  return {
    info: (msg) => {
      if (verbose) console.error(`memoryhub: ${msg}`);
    },
    warn: (msg) => console.error(`memoryhub: ${msg}`),
    error: (msg) => console.error(`memoryhub: ${msg}`),
    debug: (msg) => {
      if (verbose) console.error(`memoryhub: ${msg}`);
    },
  };
}
