import { Link2, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  baseUrl, partsFromUrl, partsListExport, partsListGet, partsListRemove, partsStatus,
  searchParts, type PartResult, type UrlPart,
} from "../lib/api";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const isUrl = (s: string) => /^https?:\/\//i.test(s.trim());

export function PartsPanel() {
  const [base, setBase] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [results, setResults] = useState<PartResult[]>([]);
  const [nexar, setNexar] = useState(false);
  const [myParts, setMyParts] = useState<UrlPart[]>([]);
  const [urlBusy, setUrlBusy] = useState(false);
  const [urlNote, setUrlNote] = useState("");

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      setBase(b);
      const st = await partsStatus(b);
      setCategories(st.categories ?? []);
      setNexar(Boolean(st.providers?.nexar));
      setMyParts((await partsListGet(b)).parts);
      // search bar + results start CLEAR — nothing is pre-populated
    })();
  }, []);

  async function go() {
    if (!base || !query.trim()) return;
    if (isUrl(query)) return addFromUrl();
    const r = await searchParts(base, query, category || undefined);
    setResults(r.results ?? []);
  }

  async function addFromUrl() {
    if (!base) return;
    setUrlBusy(true);
    setUrlNote("");
    try {
      const r = await partsFromUrl(base, query.trim(), true);
      if (!r.ok) { setUrlNote(r.error ?? "could not parse that link"); return; }
      setUrlNote(r.duplicate
        ? `already in your list: ${r.mpn ?? r.name}`
        : `added ${r.mpn ?? r.name}${r.fetched ? " (info fetched from page)" : " (from URL — page fetch blocked)"}`);
      setMyParts((await partsListGet(base)).parts);
      setQuery("");
    } finally {
      setUrlBusy(false);
    }
  }

  async function removePart(id: number) {
    if (!base) return;
    await partsListRemove(base, id);
    setMyParts((await partsListGet(base)).parts);
  }

  const urlMode = isUrl(query);

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Parts search</CardTitle>
          <span className="text-xs text-muted">
            search MPN/description — or paste a Digi-Key / Mouser / LCSC / TI / ST link to auto-add it
            · Nexar {nexar ? "configured" : "not configured"}
          </span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[260px] flex-1">
              {urlMode
                ? <Link2 className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-accent" />
                : <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />}
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && go()}
                placeholder="Search MPN / description — or paste a product URL…"
                className={`w-full rounded-lg border bg-panel py-2 pl-9 pr-3 text-sm text-ink shadow-sm outline-none focus:ring-2 ${
                  urlMode ? "border-accent/60 focus:border-accent focus:ring-accent/20"
                          : "border-line focus:border-accent focus:ring-accent/20"}`}
              />
            </div>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="cursor-pointer rounded-lg border border-line bg-panel px-2.5 py-2 text-sm text-ink shadow-sm outline-none focus:border-accent"
            >
              <option value="">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <Button variant="primary" size="md" onClick={go} disabled={urlBusy}>
              {urlMode ? <><Link2 className="h-4 w-4" /> {urlBusy ? "Fetching…" : "Add from link"}</>
                       : <><Search className="h-4 w-4" /> Search</>}
            </Button>
          </div>
          {urlNote && <div className="text-[11.5px] text-accent">{urlNote}</div>}

          {results.length > 0 && (
            <>
              <div className="flex items-center justify-between text-[11px] text-muted">
                <span>{results.length} result{results.length === 1 ? "" : "s"}</span>
                <span>prices indicative · qty 1k</span>
              </div>
              <div className="overflow-hidden rounded-lg border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="bg-panel2 text-[11px] uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-3 py-2 font-semibold">MPN</th>
                      <th className="px-3 py-2 font-semibold">Manufacturer</th>
                      <th className="px-3 py-2 font-semibold">Description</th>
                      <th className="px-3 py-2 font-semibold">Specs (normalized)</th>
                      <th className="px-3 py-2 font-semibold">Package</th>
                      <th className="px-3 py-2 text-right font-semibold">@ 1k</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((p, i) => {
                      const disp = Object.entries(p.specs_typed ?? {}).filter(([k]) => k.endsWith("_display")).map(([, v]) => String(v));
                      return (
                        <tr key={p.mpn} className={`border-t border-line transition-colors hover:bg-accent/[0.04] ${i % 2 ? "bg-panel2/40" : ""}`}>
                          <td className="px-3 py-1.5 font-mono font-medium text-ink">{p.mpn}</td>
                          <td className="px-3 py-1.5 text-muted">{p.mfr}</td>
                          <td className="px-3 py-1.5 text-muted">{p.desc}</td>
                          <td className="px-3 py-1.5">
                            <div className="flex flex-wrap gap-1">
                              {disp.map((d, j) => <span key={j} className="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent">{d}</span>)}
                            </div>
                          </td>
                          <td className="px-3 py-1.5 font-mono text-muted">{p.package}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-ink">${p.price_1k.toFixed(3)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {results.length === 0 && !myParts.length && (
            <div className="py-4 text-center text-xs text-muted">Type to search the catalog — or paste a product link to capture it below.</div>
          )}
        </CardContent>
      </Card>

      {/* My parts — link-captured list */}
      <Card>
        <CardHeader>
          <CardTitle>My parts ({myParts.length})</CardTitle>
          <button onClick={() => base && partsListExport(base)} disabled={!myParts.length}
            className="rounded-md bg-panel2 px-3 py-1.5 text-xs font-semibold text-ink hover:opacity-90 disabled:opacity-40">
            Export CSV
          </button>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {myParts.length === 0 && (
            <div className="py-2 text-center text-xs text-muted">Paste a product link above — its part number, manufacturer and info are captured here automatically.</div>
          )}
          {myParts.map((p) => (
            <div key={p.id} className="relative flex items-center gap-3 overflow-hidden rounded-lg border border-line bg-panel2/50 px-3.5 py-2 text-xs transition-all hover:border-[#39424f]">
              <span className="absolute left-0 top-0 h-full w-[3px] bg-accent/70" aria-hidden />
              <span className="font-mono font-semibold text-ink">{p.mpn ?? "—"}</span>
              <span className="text-muted">{p.manufacturer ?? ""}</span>
              <span className="truncate text-muted">{p.name ?? ""}</span>
              <span className="ml-auto flex shrink-0 items-center gap-2">
                {p.price != null && p.price !== "" && <span className="font-mono text-verified">${p.price}</span>}
                <span className="rounded border border-line px-1.5 py-0.5 text-[10px] text-muted">{p.vendor}</span>
                <a href={p.source_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">link</a>
                <button onClick={() => p.id != null && removePart(p.id)} className="text-muted hover:text-danger" title="remove">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
