// Vitest setup: jsdom globals + a deterministic-enough crypto polyfill for the
// chain-recompute test (Node's WebCrypto is present in modern versions; assert early).

import { beforeEach } from "vitest";

beforeEach(() => {
  if (typeof crypto !== "undefined" && !crypto.subtle) {
    throw new Error("WebCrypto unavailable — tests that hash need Node >= 19.");
  }
});
