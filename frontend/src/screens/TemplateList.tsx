/** Screen 7, page 1 — the template index.
 *
 * The whole job of this page is picking a template, so it carries only the facts you choose
 * between: what a version is called, which key it is a version of, how many lines it spreads,
 * whether it is published, and which ontology supplies its rules. The structure tree and the
 * ontology editors are a different task and live on the detail page (see Template.tsx), reached
 * by clicking a row.
 *
 * Authoring stays HERE: publishing a template version, or a rulebook for it, is something you
 * do to the collection rather than to one concept inside one version of it.
 */
import type { CSSProperties } from "react";
import { useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { useOntologies, useTemplateXlsxColumns, useUploadOntology, useUploadTemplateXlsx } from "../lib/queries";
import { ApiError, api, downloadTemplateXlsx } from "../lib/api";
import { color, font, layout, radius } from "../theme";
import type { Locale, OntologyRef, TemplateRef } from "../types";

/** Admin-only: the authoring desk for templates and ontologies.
 *
 * Deciding what a spread should contain is a spreadsheet job, so the primary path is the round
 * trip: download the active template as a workbook, mark each line extracted or calculated (and
 * for a calculated one, what it is calculated FROM), upload it back. That publishes a new
 * VERSION — nothing is overwritten, so an extraction that already ran still explains itself
 * against the template it actually used. The ontology (the extraction rulebook) is uploaded
 * against a named template and validated against it, so a rule for a line the template does not
 * define is refused with the key in the message rather than silently ignored.
 */
function TemplateAuthoring({
  templates,
  selectedId,
  onSelect,
  t,
}: {
  templates: TemplateRef[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  t: (k: string) => string;
}) {
  const xlsxRef = useRef<HTMLInputElement>(null);
  const ontRef = useRef<HTMLInputElement>(null);
  const jsonRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // Upload onto the selected template's key (a new version of it) or start a fresh template.
  const [asNew, setAsNew] = useState(false);
  const uploadXlsx = useUploadTemplateXlsx();
  const uploadOnt = useUploadOntology();
  const cols = useTemplateXlsxColumns();

  const selected = templates.find((x) => x.id === selectedId);

  const fail = (err: unknown) => {
    const text = err instanceof ApiError ? (err.detail ?? err.message)
      : err instanceof Error ? err.message : String(err);
    setMsg({ ok: false, text: text.slice(0, 400) });
  };

  async function download() {
    if (!selected) return;
    setBusy("xlsx");
    setMsg(null);
    try {
      await downloadTemplateXlsx(selected.id, selected.template_key);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function onXlsx(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy("upload");
    setMsg(null);
    try {
      const res = await uploadXlsx.mutateAsync({
        file: f,
        templateKey: asNew ? "" : (selected?.template_key ?? ""),
        name: asNew ? f.name.replace(/\.(xlsx|xlsm)$/i, "") : (selected?.name ?? ""),
      });
      setMsg({ ok: true, text: t("tp.auth.publishedTemplate")
        .replace("{key}", res.template_key).replace("{v}", String(res.version))
        .replace("{n}", String(res.line_items)) });
      onSelect(res.id);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
      if (xlsxRef.current) xlsxRef.current.value = "";
    }
  }

  async function onOntology(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy("ontology");
    setMsg(null);
    try {
      const definition = JSON.parse(await f.text());
      const res = await uploadOnt.mutateAsync({
        definition,
        // Point the rulebook at the template the buttons act on — that is the one it will be
        // checked against, and checking it against something else would be the wrong answer
        // quietly.
        targetTemplateKey: selected?.template_key,
      });
      setMsg({ ok: true, text: t("tp.auth.publishedOntology")
        .replace("{key}", res.ontology_key).replace("{v}", String(res.version))
        .replace("{n}", String(res.mappings)).replace("{tpl}", res.target_template_key) });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
      if (ontRef.current) ontRef.current.value = "";
    }
  }

  async function onJson(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy("json");
    setMsg(null);
    try {
      const def = JSON.parse(await f.text());
      const isOntology = "target_template_key" in def || "mappings" in def;
      const res = isOntology ? await api.createOntology(def) : await api.createTemplate(def);
      const key = "template_key" in res ? res.template_key : res.ontology_key;
      setMsg({ ok: true, text: t("tp.importOk").replace("{key}", key)
        .replace("{v}", String(res.version)) });
      if ("template_key" in res) onSelect(res.id);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
      if (jsonRef.current) jsonRef.current.value = "";
    }
  }

  const btn = (primary: boolean): CSSProperties => ({
    fontSize: 12, fontWeight: 600,
    color: primary ? "#fff" : color.indigo,
    background: primary ? color.indigo : "#fff",
    border: primary ? "none" : `1px solid ${color.indigoBorder2}`,
    borderRadius: radius.control, padding: "8px 14px",
    cursor: busy ? "wait" : "pointer", whiteSpace: "nowrap",
  });

  return (
    <div
      data-testid="template-authoring"
      style={{
        background: color.surface, border: `1px solid ${color.cardBorder}`,
        borderRadius: radius.card, padding: 18, marginBottom: 22,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 9, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.auth.title")}</span>
        <span style={{ fontSize: 11, color: color.muted }}>{t("tp.auth.versioned")}</span>
      </div>
      <p style={{ margin: "0 0 14px", fontSize: 12, color: color.sec, lineHeight: 1.55 }}>
        {t("tp.auth.hint")}
      </p>

      <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12,
                      fontSize: 12, color: color.sec }}>
        <span style={{ color: color.muted }}>{t("tp.auth.active")}</span>
        <select
          value={selectedId ?? ""}
          data-testid="template-picker"
          onChange={(e) => onSelect(e.target.value)}
          style={{ fontSize: 12, fontWeight: 600, fontFamily: font.sans, color: color.ink,
                   border: `1px solid ${color.controlBorder}`, borderRadius: radius.controlSm,
                   padding: "6px 9px", background: "#fff", cursor: "pointer", maxWidth: 420 }}
        >
          {sortTemplates(templates).map((x) => (
            <option key={x.id} value={x.id}>{`${x.name || x.template_key} · v${x.version}`}</option>
          ))}
        </select>
      </label>

      <input ref={xlsxRef} type="file" data-testid="tpl-xlsx-input" style={{ display: "none" }}
             onChange={onXlsx}
             accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />
      <input ref={ontRef} type="file" accept="application/json,.json" data-testid="tpl-ont-input"
             style={{ display: "none" }} onChange={onOntology} />
      <input ref={jsonRef} type="file" accept="application/json,.json" data-testid="tpl-json-input"
             style={{ display: "none" }} onChange={onJson} />

      <div style={{ display: "flex", gap: 9, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={download} disabled={!!busy || !selected} data-testid="tpl-download-xlsx"
                style={btn(false)}>
          {busy === "xlsx" ? t("tp.auth.working") : t("tp.auth.download")}
        </button>
        <button onClick={() => xlsxRef.current?.click()} disabled={!!busy}
                data-testid="tpl-upload-xlsx" style={btn(true)}>
          {busy === "upload" ? t("tp.auth.working") : t("tp.auth.upload")}
        </button>
        <button onClick={() => ontRef.current?.click()} disabled={!!busy}
                data-testid="tpl-upload-ontology" style={btn(false)}>
          {busy === "ontology" ? t("tp.auth.working") : t("tp.auth.uploadOntology")}
        </button>
        <button onClick={() => jsonRef.current?.click()} disabled={!!busy}
                data-testid="tpl-import-json"
                style={{ ...btn(false), color: color.sec2,
                         border: `1px solid ${color.controlBorder}` }}>
          {busy === "json" ? t("tp.auth.working") : t("tp.importTemplate")}
        </button>
      </div>

      <label style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 11,
                      fontSize: 11.5, color: color.sec }}>
        <input type="checkbox" checked={asNew} data-testid="tpl-as-new"
               onChange={(e) => setAsNew(e.target.checked)} />
        {t("tp.auth.asNew")}
      </label>

      {/* The workbook's contract, read from the reader that enforces it — so this screen can
          never describe columns the API does not actually accept. */}
      {cols.data && (
        <div style={{ marginTop: 13, paddingTop: 12, borderTop: `1px solid ${color.hairline}`,
                      fontSize: 11.5, color: color.sec, lineHeight: 1.6 }}>
          <div style={{ fontWeight: 600, color: color.ink, marginBottom: 4 }}>
            {t("tp.auth.columns")}
          </div>
          <div style={{ fontFamily: font.mono, fontSize: 10.5, color: color.sec2,
                        marginBottom: 7 }}>
            {cols.data.columns.map((c) => c.header).join(" · ")}
          </div>
          {cols.data.kinds.map((k) => (
            <div key={k.value}>
              <span style={{ fontFamily: font.mono, fontWeight: 600, color: color.ink }}>
                {k.value}
              </span>{" — "}{k.help}
            </div>
          ))}
        </div>
      )}

      {msg && (
        <div
          data-testid="tpl-auth-message"
          style={{ marginTop: 12, padding: "8px 11px", borderRadius: radius.control,
                   fontSize: 11.5, lineHeight: 1.55,
                   background: msg.ok ? color.indigoTint : color.redBg,
                   color: msg.ok ? color.indigo : color.redFg }}
        >
          {msg.text}
        </div>
      )}
    </div>
  );
}

/** Row order for the index: the versions of one template stay together, newest first — that is
 *  the one in force — and templates are ordered by name. Exported because the screen aims the
 *  authoring controls at the version a reader sees FIRST; defaulting them at the list's oldest
 *  row would mean "Download as Excel" handed back a superseded spread. */
export function sortTemplates(templates: TemplateRef[]): TemplateRef[] {
  return [...templates].sort((a, b) => (a.template_key === b.template_key
    ? b.version - a.version
    : (a.name || a.template_key).localeCompare(b.name || b.template_key)));
}

/** Line-item counts for the index, keyed by template id.
 *
 * GET /templates does not carry the count: it is only on the per-template detail, which is a
 * ~200 KB document (the whole tree plus every concept's criteria). Two consequences are designed
 * around here. Rows fill in one request at a time, so the index is readable immediately instead of
 * pulling megabytes before it paints. And the counts are cached under their OWN key rather than
 * the detail's: a stored template version is immutable, so its line count can never change, while
 * every ontology save invalidates `template-detail` — sharing that key would drag one 200 KB
 * document per row down the wire again on each save.
 */
function useLineItemCounts(templates: TemplateRef[], locale: Locale): Record<string, number> {
  const qc = useQueryClient();
  // How far down the list the counts have settled. Read from the cache rather than from the
  // results below, which cannot describe their own `enabled`.
  let head = 0;
  while (head < templates.length) {
    const st = qc.getQueryState(["template-line-count", templates[head].id, locale]);
    // An error advances the head too: one template that cannot be read must not stall the rest.
    if (st?.status !== "success" && st?.status !== "error") break;
    head++;
  }
  const results = useQueries({
    queries: templates.map((tpl, i) => ({
      queryKey: ["template-line-count", tpl.id, locale],
      queryFn: () => api.templateDetail(tpl.id, locale),
      enabled: i <= head,
      staleTime: Infinity,
    })),
  });
  const counts: Record<string, number> = {};
  results.forEach((r, i) => {
    const n = r.data?.template.line_items;
    if (typeof n === "number") counts[templates[i].id] = n;
  });
  return counts;
}

const GRID = "minmax(200px,2.4fr) minmax(130px,1.1fr) 74px 90px 96px minmax(130px,1.2fr)";

function HeadCell({ label, right }: { label: string; right?: boolean }) {
  return (
    <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: 0.4, color: color.muted,
                  textAlign: right ? "end" : "start" }}>
      {label}
    </div>
  );
}

/** One template version. The whole row is the affordance — an index exists to be clicked into,
 *  so there is no separate "open" button to hunt for. */
function TemplateRow({ tpl, count, ontology, active, onOpen, t }: {
  tpl: TemplateRef; count: number | undefined; ontology: OntologyRef | undefined;
  active: boolean; onOpen: () => void; t: (k: string) => string;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      data-testid="tpl-row"
      role="button"
      tabIndex={0}
      title={t("tp.list.openHint")}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "grid", gridTemplateColumns: GRID, alignItems: "center", gap: 12,
        padding: "13px 18px", cursor: "pointer",
        borderTop: `1px solid ${color.hairline}`,
        background: active ? color.indigoTint : hover ? color.rowAltBg : color.surface,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: color.ink }}>
          {tpl.name || tpl.template_key}
        </div>
        {active && (
          <div style={{ fontSize: 10.5, color: color.indigo, marginTop: 2 }}>
            {t("tp.list.activeRow")}
          </div>
        )}
      </div>
      <div style={{ fontFamily: font.mono, fontSize: 11, color: color.sec2, overflowWrap: "anywhere" }}>
        {tpl.template_key}
      </div>
      <div style={{ fontFamily: font.mono, fontSize: 11.5, fontWeight: 600, color: color.ink2 }}>
        {`v${tpl.version}`}
      </div>
      {/* Until this row's count arrives the cell says nothing rather than guessing at zero. */}
      <div data-testid="tpl-row-lines"
           style={{ fontSize: 12, textAlign: "end", color: count == null ? color.faint : color.ink2 }}>
        {count == null ? "…" : count}
      </div>
      <div>
        <span style={{ fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: radius.pill,
                       background: tpl.is_published ? color.greenBg : color.rowAltBg,
                       color: tpl.is_published ? color.greenFg : color.muted }}>
          {t(tpl.is_published ? "tp.list.published" : "tp.list.draft")}
        </span>
      </div>
      <div style={{ fontSize: 11.5, minWidth: 0 }}>
        {ontology ? (
          <>
            <span style={{ fontFamily: font.mono, color: color.sec, overflowWrap: "anywhere" }}>
              {ontology.ontology_key}
            </span>
            <span style={{ color: color.muted }}>{` · v${ontology.version}`}</span>
          </>
        ) : (
          <span style={{ color: color.muted }}>{t("tp.list.noOntology")}</span>
        )}
      </div>
    </div>
  );
}

/** Page 1: the index. `activeId` is the version the authoring buttons act on; `onOpen` hands a
 *  row to the screen, which raises the detail over this page — this component stays mounted, so
 *  the filter and the scroll position are exactly where they were when the detail is dismissed. */
export function TemplateList({
  templates, activeId, canEdit, locale, onPick, onOpen, t,
}: {
  templates: TemplateRef[]; activeId: string | undefined; canEdit: boolean; locale: Locale;
  onPick: (id: string) => void; onOpen: (id: string) => void; t: (k: string) => string;
}) {
  const [filter, setFilter] = useState("");
  const counts = useLineItemCounts(templates, locale);
  const ontologies = useOntologies();

  // Nothing configured yet → guidance, plus the authoring desk that is the way out of it.
  if (templates.length === 0) {
    return (
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0, padding: "0 24px" }}>
        <div style={{ maxWidth: 560, margin: "60px auto", textAlign: "center", color: color.muted }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>◆</div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: color.ink, marginBottom: 8 }}>
            {t("tp.emptyTitle")}
          </h1>
          <p style={{ fontSize: 12.5, lineHeight: 1.6 }}>{t("tp.emptyHint")}</p>
          {canEdit && (
            <div style={{ maxWidth: 560, margin: "18px auto 0", textAlign: "left" }}>
              <TemplateAuthoring templates={[]} selectedId={undefined} onSelect={onPick} t={t} />
            </div>
          )}
        </div>
      </div>
    );
  }

  // Latest ontology per template key: the extractor reads the highest version targeting a
  // template, so that is the rulebook a row is honestly described by.
  const latestOntology: Record<string, OntologyRef> = {};
  (ontologies.data ?? []).forEach((o) => {
    const seen = latestOntology[o.target_template_key];
    if (!seen || o.version > seen.version) latestOntology[o.target_template_key] = o;
  });

  const q = filter.trim().toLowerCase();
  const rows = sortTemplates(
    templates.filter((x) => !q || `${x.name} ${x.template_key}`.toLowerCase().includes(q)));

  return (
    <div data-testid="template-list" style={{ flex: 1, overflowY: "auto", minHeight: 0,
                                              padding: "26px 30px 60px" }}>
      <div style={{ maxWidth: layout.screenMax, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between",
                      gap: 18, marginBottom: 18, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>{t("tp.list.title")}</h1>
            <p style={{ margin: 0, color: color.sec2, fontSize: 12.5, maxWidth: 640,
                        lineHeight: 1.55 }}>
              {t("tp.list.subhead")}
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            {/* INTEGRATION SLOT — the "download the expected ontology structure" control belongs
                HERE, next to the filter: it describes the collection, not one version. Left
                unwired on purpose; the endpoint arrives in lib/api.ts under a separate change,
                and a button that 404s would be worse than no button. */}
            <input
              value={filter}
              data-testid="tpl-filter"
              placeholder={t("tp.list.filter")}
              onChange={(e) => setFilter(e.target.value)}
              style={{ fontFamily: font.sans, fontSize: 12, color: color.ink, background: "#fff",
                       border: `1px solid ${color.controlBorder}`, borderRadius: radius.controlSm,
                       padding: "7px 11px", outline: "none", minWidth: 230 }}
            />
          </div>
        </div>

        {/* The index comes FIRST — picking a template is what this page is for; publishing a new
            version of one is the occasional task, so the authoring desk sits below it. */}
        <div style={{ background: color.surface, border: `1px solid ${color.cardBorder}`,
                      borderRadius: radius.card, overflow: "hidden", marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 9, padding: "14px 18px 12px" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.list.stored")}</span>
            <span style={{ fontSize: 11, color: color.muted }}>
              {t("tp.list.count").replace("{n}", String(rows.length))}
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: GRID, alignItems: "center", gap: 12,
                        padding: "0 18px 9px" }}>
            <HeadCell label={t("tp.list.colName")} />
            <HeadCell label={t("tp.list.colKey")} />
            <HeadCell label={t("tp.list.colVersion")} />
            <HeadCell label={t("tp.list.colLines")} right />
            <HeadCell label={t("tp.list.colState")} />
            <HeadCell label={t("tp.list.colOntology")} />
          </div>
          {rows.length === 0 ? (
            <div style={{ borderTop: `1px solid ${color.hairline}`, padding: "22px 18px",
                          fontSize: 12, color: color.muted }}>
              {t("tp.list.noMatch")}
            </div>
          ) : rows.map((tpl) => (
            <TemplateRow
              key={tpl.id} tpl={tpl} count={counts[tpl.id]}
              ontology={latestOntology[tpl.template_key]} active={tpl.id === activeId}
              onOpen={() => onOpen(tpl.id)} t={t}
            />
          ))}
        </div>

        {canEdit && (
          <TemplateAuthoring templates={templates} selectedId={activeId} onSelect={onPick} t={t} />
        )}
      </div>
    </div>
  );
}
