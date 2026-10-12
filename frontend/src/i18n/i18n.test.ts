import en from "./en.json";
import ar from "./ar.json";
import i18n, { applyDirection } from "./index";

type Tree = { [k: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  return Object.entries(tree).reduce<Record<string, string>>((acc, [k, v]) => {
    if (typeof v === "string") acc[prefix + k] = v;
    else Object.assign(acc, flatten(v, `${prefix}${k}.`));
    return acc;
  }, {});
}

const flatEn = flatten(en as Tree);
const flatAr = flatten(ar as Tree);

describe("translations", () => {
  it("has an Arabic string for every English key", () => {
    const missing = Object.keys(flatEn).filter((k) => !(k in flatAr));
    expect(missing).toEqual([]);
  });

  it("keeps named placeholders in Arabic strings", () => {
    const broken = Object.entries(flatEn).filter(([k, v]) => {
      const names = [...v.matchAll(/{{(\w+)}}/g)].map((m) => m[1]).filter((n) => n !== "count");
      return names.some((n) => !flatAr[k]?.includes(`{{${n}}}`));
    });
    expect(broken.map(([k]) => k)).toEqual([]);
  });

  it("keeps the synthetic content disclaimer in both languages", () => {
    expect(flatEn["common.syntheticNotice"]).toBe("Synthetic demonstration content — not legal guidance.");
    expect(flatAr["common.syntheticNotice"]).toBeTruthy();
  });

  it("switches document direction for Arabic", async () => {
    await i18n.changeLanguage("ar");
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("ar");
    await i18n.changeLanguage("en");
    expect(document.documentElement.dir).toBe("ltr");
    applyDirection("ar");
    expect(document.documentElement.dir).toBe("rtl");
    applyDirection("en");
  });
});
