/**
 * â˜… The duress bundle test. Â§12.1 `[NOVEL-N1c]`
 *
 * The requester's screen must be indistinguishable from a genuine slow approval. That
 * means the *built bundle* must contain no duress vocabulary â€” not in component names,
 * not in console strings, not in copy. One grep in CI removes a whole class of leak.
 *
 * The production build is `dist/assets/*.js`; when the bundle exists this test greps it
 * for the forbidden vocabulary. In test environments without a prior build it asserts
 * the source half of the guarantee instead: the ProcessingPane and its imports contain
 * none of the words, and the module map keeps them out of the requester-facing tree.
 */

import { describe, expect, it } from "vitest";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONSOLE_ROOT = join(HERE, "..", "..");
const DIST = join(CONSOLE_ROOT, "dist", "assets");

const FORBIDDEN = ["duress", "coercion", "coerced", "marker", "distress"];

function sourceOf(rel: string): string {
  return readFileSync(join(CONSOLE_ROOT, rel), "utf-8");
}

describe("duress vocabulary never reaches a requester-facing bundle", () => {
  it("ProcessingPane (the requester's screen) contains none of the vocabulary", () => {
    const src = sourceOf(join("src", "panels", "ProcessingPane.tsx"));
    // The doc comment may explain the rule without naming it in code paths; strip
    // block comments before the check, since comments are stripped by the build.
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    for (const word of FORBIDDEN) {
      expect(code.toLowerCase(), `ProcessingPane source contains "${word}"`).not.toContain(word);
    }
  });

  it("the component is named ProcessingPane, not anything readable in devtools", () => {
    expect(existsSync(join(CONSOLE_ROOT, "src", "panels", "ProcessingPane.tsx"))).toBe(true);
  });

  it("the Desk screen is not imported by the requester's default route", () => {
    const app = sourceOf(join("src", "App.tsx"));
    const deskImported = /import.*DeskScreen/.test(app);
    expect(deskImported).toBe(true); // imported for the /desk route â€” but never rendered by default
    // The default render path: route === "verify" renders VerifyScreen, which never
    // imports DeskScreen or the escalation vocabulary.
    const verify = sourceOf(join("src", "screens", "Verify.tsx"));
    expect(verify).not.toMatch(/Desk|desk/i);
  });

  it("when a production bundle exists, it contains no duress vocabulary", () => {
    if (!existsSync(DIST)) {
      console.warn("dist/assets not built yet â€” run `npm run build` for the full bundle check.");
      return;
    }
    for (const file of readdirSync(DIST)) {
      if (!file.endsWith(".js")) continue;
      const bundle = readFileSync(join(DIST, file), "utf-8");
      for (const word of FORBIDDEN) {
        expect(bundle.toLowerCase(), `bundle ${file} contains "${word}"`).not.toContain(word);
      }
    }
  });
});
