import { describe, expect, it } from "vitest";

import { DEFAULT_THEME, THEMES, parseThemeId } from "./themes";

describe("THEMES", () => {
  it("lists holo, aurora and instrumento with Spanish names, holo first", () => {
    expect(THEMES.map((theme) => [theme.id, theme.name])).toEqual([
      ["holo", "Holo Ámbar"],
      ["aurora", "Aurora"],
      ["instrumento", "Instrumento"],
    ]);
  });

  it("defaults to holo", () => {
    expect(DEFAULT_THEME).toBe("holo");
  });
});

describe("parseThemeId", () => {
  it.each(["holo", "aurora", "instrumento"])("accepts the known theme %s", (id) => {
    expect(parseThemeId(id)).toBe(id);
  });

  it.each([null, undefined, "", " aurora", "AURORA", "fosforo", "__proto__", "toString", "{}", 3, {}])(
    "falls back to holo for the invalid value %j",
    (raw) => {
      expect(parseThemeId(raw)).toBe("holo");
    },
  );
});
