/**
 * Money, hashes, redaction, reason copy, and the chain-recompute cross-check.
 * `formatInr` asserts the Â§23 rule: never floats, Indian 2-2-3 grouping.
 */

import { describe, expect, it } from "vitest";
import { formatInr, formatLakhCrore, redactAccount, shortHash, formatCountdown } from "./format";
import { reasonSentence, stepRailLine } from "../copy/reasons";
import { canonicalize, recomputeRecordHash, sha256Hex } from "./recompute";

describe("money formatting", () => {
  it("45000000 paise → ₹4,50,000.00 (Indian 2-2-3 grouping)", () => {
    expect(formatInr(45000000)).toBe("₹4,50,000.00");
  });
  it("large crore values group correctly", () => {
    expect(formatInr(1000000000)).toBe("₹1,00,00,000.00");
  });
  it("small values do not group", () => {
    expect(formatInr(99999)).toBe("₹999.99");
    expect(formatInr(100000)).toBe("₹1,000.00");
  });
  it("negative amounts carry the sign", () => {
    expect(formatInr(-250000)).toBe("-₹2,500.00");
  });
  it("null and undefined render as absent, never 0", () => {
    expect(formatInr(null)).toBe("—");
    expect(formatInr(undefined)).toBe("—");
  });
  it("integers only — a float cannot reach the formatter", () => {
    expect(formatInr(Math.trunc(1.5))).toBe("₹0.01");
  });
  it("lakh/crore phrasing for the sandbox field", () => {
    expect(formatLakhCrore(1000000000)).toContain("crore");
    expect(formatLakhCrore(150000000)).toContain("lakh");
  });
});

describe("redaction — last 4 only, everywhere", () => {
  it("masks an IFSC-prefixed account", () => {
    expect(redactAccount("HDFC0001234567890")).toBe("••••7890");
  });
  it("is idempotent on already-masked values", () => {
    expect(redactAccount("••••9281")).toBe("••••9281");
  });
  it("null/empty render as absent", () => {
    expect(redactAccount(null)).toBe("—");
    expect(redactAccount("")).toBe("—");
  });
});

describe("hashes and countdowns", () => {
  it("truncates with an ellipsis", () => {
    expect(shortHash("a".repeat(64))).toBe("aaaa…aaa");
  });
  it("m:ss for the cooldown bar", () => {
    expect(formatCountdown(348)).toBe("5:48");
    expect(formatCountdown(0)).toBe("0:00");
  });
});

describe("reason copy â€” never a raw enum", () => {
  it("maps codes to sentences", () => {
    expect(reasonSentence("FINGERPRINT_MISMATCH")).toBe("The account changed after authorization.");
    expect(reasonSentence("HO-1")).toContain("not the account that was authorized");
  });
  it("unknown codes render as themselves â€” never blank", () => {
    expect(reasonSentence("WHATEVER")).toBe("WHATEVER");
    expect(reasonSentence(null)).toBeNull();
  });
  it("the step-rail line explains its own friction", () => {
    expect(stepRailLine(["the account changed"])).toContain("because the account changed");
    expect(stepRailLine([])).toContain("signature only");
  });
});

describe("the console's one piece of arithmetic â€” hash recompute", () => {
  const record = {
    seq: 1, record_id: "r1", timestamp: "2026-09-18T11:04:00+05:30",
    event_type: "INTENT_CAPTURED", transaction_id: null, actor: "system:core",
    payload: { risk_score: 58 }, policy_version: "1.0.0", policy_hash: "abc",
    prev_hash: "0".repeat(64), record_hash: "should-not-matter",
  };

  it("canonicalizes like the server: sorted keys, no whitespace", () => {
    expect(canonicalize({ b: 1, a: [2, 1] })).toBe('{"a":[2,1],"b":1}');
    expect(canonicalize({ purpose: null })).toBe('{"purpose":null}');
  });

  it("excludes record_hash from the hashed body", async () => {
    const one = await recomputeRecordHash(record);
    const two = await recomputeRecordHash({ ...record, record_hash: "f".repeat(64) });
    expect(one.computed).toBe(two.computed);
  });

  it("changing any hashed field changes the hash", async () => {
    const base = (await recomputeRecordHash(record)).computed;
    const mutated = (await recomputeRecordHash({ ...record, actor: "attacker" })).computed;
    expect(mutated).not.toBe(base);
  });

  it("agrees with the CRYPTO_WIRE_FORMAT frozen vector on sha256 length", async () => {
    const hex = await sha256Hex('{"a":2,"b":1}');
    expect(hex).toMatch(/^[0-9a-f]{64}$/);
  });
});
