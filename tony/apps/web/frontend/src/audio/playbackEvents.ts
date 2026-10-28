import type { Envelope } from "../protocol/types";

export interface PlaybackControls {
  begin: (messageId: string) => void;
  end: (messageId: string) => void;
  stop: (messageId?: string) => void;
}

/** What each server event means for the local playback queue. */
export function applyToPlayback(envelope: Envelope, player: PlaybackControls): void {
  const messageId = envelope.message_id === undefined ? undefined : String(envelope.message_id);
  switch (envelope.type) {
    case "tts.start":
      if (messageId !== undefined) {
        player.begin(messageId);
      }
      return;
    case "tts.end":
      if (messageId !== undefined) {
        player.end(messageId);
      }
      return;
    case "tts.cancelled":
      player.stop(messageId);
      return;
    case "user.accepted":
      player.stop();
      return;
  }
}
