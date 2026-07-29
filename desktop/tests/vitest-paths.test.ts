import { describe, expect, it } from "vitest";
import { toVitestGlob } from "../vitest-paths";

describe("toVitestGlob", () => {
  it("normalizes Windows absolute paths for Vitest glob matching", () => {
    expect(
      toVitestGlob(
        "D:\\a\\obs-overlay-import-utility\\desktop\\tests\\**\\*.test.ts"
      )
    ).toBe("D:/a/obs-overlay-import-utility/desktop/tests/**/*.test.ts");
  });

  it("preserves POSIX glob paths", () => {
    expect(toVitestGlob("/workspace/desktop/tests/**/*.test.tsx")).toBe(
      "/workspace/desktop/tests/**/*.test.tsx"
    );
  });
});
