/** Screen 6 — All Notes. Left index of extracted notes; right detail with a
 * particulars grid and a note-to-face reconciliation callout. */
import { useNavigate } from "react-router-dom";

import { Card } from "../components/ui";
import { SCREENS } from "./config";
import { useNote, useNotes } from "../lib/queries";
import { useUI } from "../store";
import { color, confStyle, fmtIN, font, radius } from "../theme";
import type { NoteDetail, NoteDetailRow } from "../types";

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
  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span style={{ fontFamily: font.mono, fontSize: 13, fontWeight: 600, color: color.indigo }}>
          Note {detail.no}
        </span>
        <h1 style={{ fontSize: 19, fontWeight: 600, margin: 0 }}>{detail.title}</h1>
      </div>
      <div style={{ fontSize: 12, color: color.muted, marginBottom: 18 }}>
        Extracted from p.{detail.page} · linked to{" "}
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
        on the face of the Balance Sheet
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
          <span>PARTICULARS</span>
          <span style={{ textAlign: "right" }}>FY25</span>
          <span style={{ textAlign: "right" }}>FY24</span>
          <span style={{ textAlign: "right" }}>CONF.</span>
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
          <b>Note-to-face reconciliation.</b> {detail.reconciliation}
        </div>
      )}
    </div>
  );
}

export default function NotesScreen() {
  const { data: notes } = useNotes();
  const { note, setNote } = useUI();
  const { data: detail } = useNote(note);

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
          <h2 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 3px" }}>Extracted notes</h2>
          <div style={{ fontSize: 11.5, color: color.muted }}>
            {notes.count} notes · linked to {notes.linked} line items
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
            <span style={{ fontSize: 12, color: color.faint }}>Search notes…</span>
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
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "26px 34px" }}>
        {detail ? <Detail detail={detail} /> : <Loading />}
      </div>
    </div>
  );
}
