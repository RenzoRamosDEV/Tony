import { describe, expect, it } from "vitest";

import type { Envelope } from "../protocol/types";
import { applyToPlayback } from "./playbackEvents";

function envelope(type: string, messageId?: string): Envelope {
  return { v: 1, type, seq: 1, conversation_id: "c-1", payload: {}, ...(messageId ? { message_id: messageId } : {}) };
}

function recorder() {
  const calls: string[] = [];
  return {
    calls,
    player: {
      begin: (id: string) => calls.push(`begin ${id}`),
      end: (id: string) => calls.push(`end ${id}`),
      stop: (id?: string) => calls.push(`stop ${id ?? "-"}`),
    },
  };
}

describe("applyToPlayback", () => {
  it.each([
    ["tts.start", "m-1", ["begin m-1"]],
    ["tts.end", "m-1", ["end m-1"]],
    ["tts.cancelled", "m-1", ["stop m-1"]],
    ["tts.cancelled", undefined, ["stop -"]],
    ["user.accepted", "m-2", ["stop -"]],
    ["tts.start", undefined, []],
    ["tts.end", undefined, []],
    ["assistant.final", "m-1", []],
  ])("%s (%s)", (type, messageId, expected) => {
    const { calls, player } = recorder();

    applyToPlayback(envelope(type, messageId), player);

    expect(calls).toEqual(expected);
  });
});
