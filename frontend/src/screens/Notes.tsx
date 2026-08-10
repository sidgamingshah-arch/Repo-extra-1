/** Screen 6 — All Notes. Left index of extracted notes; right detail with a
 * particulars grid and a note-to-face reconciliation callout. When a real uploaded
 * annual-report PDF is available, the note's source page is rendered beside the
 * detail by default (no toggle) — reusing the same auth'd page-image fetch the
 * extraction Source panel uses. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card } from "../components/ui";
import { SCREENS } from "./config";
import { useT } from "../i18n";
import { ApiError, api } from "../lib/api";
import { useDocuments, useNote, useNotes, useProjectLoaded } from "../lib/queries";
import { EmptyState } from "../components/EmptyState";
import { useUI } from "../store";
import { color, confStyle, fmtIN, font, radius } from "../theme";
import type { NoteDetail, NoteDetailRow, SourceDoc } from "../types";

const GRID = "1fr 120px 120px 64px";

function Loading() {
  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: color.muted }}>
      Loading…
    </div>
  );
}

function DetailRow({ row }: { row: NoteDetailRow }) {
  const isSub = row.kind === "sub";
  const isTot = row.kind === "tot";
  const wt = isSub || isTot ? 600 : 400;
  const fg = isTot ? color.indigo : color.ink;
  const bg = isTot ? color.indigoTint2 : isSub ? color.rowAltBg : color.surface;
  const cc = row.conf ? confStyle(row.conf) : null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: GRID,
        alignItems: "center",
        padding: "10px 18px",
        borderBottom: `1px solid ${color.hairline}`,
        background: bg,
      }}
    >
      <span style={{ fontSize: 12.5, fontWeight: wt, color: fg }}>{row.label}</span>
      <span style={{ textAlign: "right", fontFamily: font.mono, fontSize: 12, fontWeight: wt, color: fg }}>
        {fmtIN(row.v1)}
      </span>
      <span style={{ textAlign: "right", fontFamily: font.mono, fontSize: 12, color: color.muted }}>
        {fmtIN(row.v2)}
      </span>
      <span style={{ textAlign: "right" }}>
        {cc && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              padding: "2px 7px",
              borderRadius: radius.pill,
              background: cc.bg,
              color: cc.fg,
            }}
          >
            {cc.pct}
          </span>
        )}
      </span>
    </div>
  );
}

function Detail({ detail }: { detail: NoteDetail }) {
  const navigate = useNavigate();
  const t = useT();
  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span style={{ fontFamily: font.mono, fontSize: 13, fontWeight: 600, color: color.indigo }}>
          {t("n.note")} {detail.no}
        </span>
        <h1 style={{ fontSize: 19, fontWeight: 600, margin: 0 }}>{detail.title}</h1>
      </div>
      <div style={{ fontSize: 12, color: color.muted, marginBottom: 18 }}>
        {t("n.extractedFrom")}{detail.page} {t("n.linked")}{" "}
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate(SCREENS.workspace.path);
          }}
          style={{ color: color.indigo }}
        >
          {detail.linked_label}
        </a>{" "}
        {t("n.onFace")}
      </div>
      <Card pad={0} style={{ overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: GRID,
            padding: "10px 18px",
            background: color.rowAltBg,
            borderBottom: "1px solid #e8eaee",
            fontSize: 10.5,
            fontWeight: 600,
            color: color.muted,
          }}
        >
          <span>{t("n.particulars")}</span>
          <span style={{ textAlign: "right" }}>FY25</span>
          <span style={{ textAlign: "right" }}>FY24</span>
          <span style={{ textAlign: "right" }}>{t("n.conf")}</span>
        </div>
        {detail.rows.map((r, i) => (
          <DetailRow key={i} row={r} />
        ))}
      </Card>
      {detail.reconciliation && (
        <div
          style={{
            marginTop: 14,
            padding: "13px 15px",
            background: color.indigoTint,
            border: `1px solid ${color.indigoBorder}`,
            borderRadius: 10,
            fontSize: 12,
            color: color.indigo,
            lineHeight: 1.55,
          }}
        >
          <b>{t("n.reconciliation")}</b> {detail.reconciliation}
        </div>
      )}
    </div>
  );
}

/** Side-by-side annual-report page for the selected note. Fetches the auth'd PDF page
 * image (same endpoint as the extraction Source panel) for the note's 0-based `pageIndex`.
 * A 404 means the note's page lies outside this document (e.g. a partial upload) — that
 * is shown as a neutral "no source page" hint rather than a hard error. */
function NotePageViewer({
  documentId,
  pageIndex,
  t,
}: {
  documentId: string;
  pageIndex: number;
  t: (k: string) => string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "missing" | "error">("loading");

  useEffect(() => {
    let objUrl: string | null = null;
    let cancelled = false;
    setStatus("loading");
    setUrl(null);
    api
      .fetchPageImage(documentId, pageIndex)
      .then((blob) => {
        if (cancelled) return;
        objUrl = URL.createObjectURL(blob);
        setUrl(objUrl);
        setStatus("ok");
      })
      .catch((e) => {
        if (cancelled) return;
        // Out-of-range page (note references a page this document doesn't contain).
        setStatus(e instanceof ApiError && e.status === 404 ? "missing" : "error");
      });
    return () => {
      cancelled = true;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [documentId, pageIndex]);

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}>
      <div
        style={{
          fontSize: 10.5,
          fontWeight: 600,
          letterSpacing: 0.3,
          color: color.muted,
          padding: "0 0 8px",
        }}
      >
        {t("n.sourcePage").toUpperCase()}
        <span style={{ fontFamily: font.mono, fontWeight: 500, marginInlineStart: 8 }}>
          p.{pageIndex + 1}
        </span>
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "auto",
          background: color.rowAltBg,
          border: `1px solid ${color.hairline3}`,
          borderRadius: 8,
          padding: 12,
        }}
      >
        {status === "loading" && (
          <div style={{ fontSize: 12, color: color.muted, padding: "24px 8px", textAlign: "center" }}>
            {t("n.loadingPage")}
          </div>
        )}
        {status === "missing" && (
          <div style={{ fontSize: 12, color: color.muted, padding: "24px 8px", textAlign: "center" }}>
            {t("n.noSourcePage")}
          </div>
        )}
        {status === "error" && (
          <div style={{ fontSize: 12, color: color.redFg, padding: "24px 8px", textAlign: "center" }}>
            {t("n.pageFailed")}
          </div>
        )}
        {status === "ok" && url && (
          <img
            src={url}
            alt=""
            style={{
              display: "block",
              width: "100%",
              background: "#fff",
              border: `1px solid ${color.hairline3}`,
              borderRadius: 6,
            }}
          />
        )}
      </div>
    </div>
  );
}

export default function NotesScreen() {
  const t = useT();
  const locale = useUI((s) => s.locale);
  const loaded = useProjectLoaded();
  const { data: notes } = useNotes(locale);
  const { note, setNote } = useUI();
  const { data: detail } = useNote(note, locale);
  const { data: docsData } = useDocuments();

  // The annual-report source: the first real uploaded PDF document (has an id).
  const pdfDoc: SourceDoc | null =
    docsData?.documents?.find((d) => !!d.id && d.ext.toUpperCase().startsWith("PDF")) ?? null;
  // Default the viewer to the selected note's 1-based page (0/undefined = unknown).
  const pageIndex = detail && detail.page > 0 ? detail.page - 1 : null;

  if (!loaded) return <EmptyState />;
  if (!notes) return <Loading />;

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      <div
        style={{
          width: 290,
          flex: "0 0 290px",
          borderRight: `1px solid ${color.cardBorder}`,
          background: color.surface,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <div style={{ padding: "16px 16px 11px", flex: "0 0 auto" }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 3px" }}>{t("n.heading")}</h2>
          <div style={{ fontSize: 11.5, color: color.muted }}>
            {notes.count} {t("n.notes")} · {t("n.linkedTo")} {notes.linked} {t("n.lineItems")}
          </div>
          <div
            style={{
              marginTop: 11,
              display: "flex",
              alignItems: "center",
              gap: 7,
              border: `1px solid ${color.cardBorder}`,
              borderRadius: 8,
              padding: "7px 10px",
            }}
          >
            <span style={{ color: color.faint }}>⌕</span>
            <span style={{ fontSize: 12, color: color.faint }}>{t("n.search")}</span>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", minHeight: 0, padding: "0 8px 12px" }}>
          {notes.notes.map((n) => {
            const sel = n.no === note;
            const cc = confStyle(n.conf);
            return (
              <div
                key={n.no}
                onClick={() => setNote(n.no)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "9px 10px",
                  borderRadius: 8,
                  cursor: "pointer",
                  background: sel ? color.indigoTint : "transparent",
                  marginBottom: 2,
                }}
              >
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 11,
                    fontWeight: 600,
                    color: sel ? color.indigo : color.muted,
                    minWidth: 26,
                  }}
                >
                  N{n.no}
                </span>
                <span
                  style={{
                    flex: 1,
                    fontSize: 12,
                    fontWeight: sel ? 600 : 500,
                    color: sel ? color.indigo : color.ink2,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {n.title}
                </span>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: cc.fg }} />
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, display: "flex", minHeight: 0 }}>
        <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "26px 34px" }}>
          {detail ? <Detail detail={detail} /> : <Loading />}
        </div>
        {pdfDoc?.id && pageIndex != null && (
          <div
            style={{
              flex: 1,
              minWidth: 0,
              borderLeft: `1px solid ${color.cardBorder}`,
              background: color.surface,
              overflow: "hidden",
              padding: "26px 24px",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            <NotePageViewer documentId={pdfDoc.id} pageIndex={pageIndex} t={t} />
          </div>
        )}
      </div>
    </div>
  );
}
