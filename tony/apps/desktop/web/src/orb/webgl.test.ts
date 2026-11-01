import { describe, expect, it } from "vitest";

import { isWebGLAvailable } from "./webgl";

function fakeDocument(getContext: (kind: string) => unknown): Document {
  return { createElement: () => ({ getContext }) } as unknown as Document;
}

describe("isWebGLAvailable", () => {
  it("is true when WebGL 2 answers", () => {
    expect(isWebGLAvailable(fakeDocument((kind) => (kind === "webgl2" ? {} : null)))).toBe(true);
  });

  it("falls back to WebGL 1", () => {
    expect(isWebGLAvailable(fakeDocument((kind) => (kind === "webgl" ? {} : null)))).toBe(true);
  });

  it("is false when no context is returned", () => {
    expect(isWebGLAvailable(fakeDocument(() => null))).toBe(false);
  });

  it("is false when asking for a context throws", () => {
    expect(
      isWebGLAvailable(
        fakeDocument(() => {
          throw new Error("blocked");
        }),
      ),
    ).toBe(false);
  });

  it("is false in jsdom, which has no WebGL", () => {
    expect(isWebGLAvailable(document)).toBe(false);
  });
});
