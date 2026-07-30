/**
 * Convert absolute paths into Vitest-compatible glob paths.
 *
 * Vitest's glob matcher expects forward slashes even when the configuration is
 * evaluated on Windows, where path.resolve() returns backslashes.
 */
export function toVitestGlob(pathValue: string): string {
  return pathValue.replace(/\\/g, "/");
}
