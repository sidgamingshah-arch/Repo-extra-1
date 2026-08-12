/** Screen 7 — Template & Ontology, in two pages.
 *
 * Page 1 is the index (see TemplateList.tsx): the templates that exist, one row each, and the
 * authoring desk. Page 2 — everything below — is one template's detail: its structure tree, the
 * node editor, the netting policies, the ontology editing. It is raised OVER the index rather
 * than replacing it, so dismissing it puts the reader back on the list they were reading, filter
 * and scroll intact, and `?template=` keeps a reloaded tab on the version it was open on.
 */
import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Card } from "../components/ui";
import { TemplateList, sortTemplates } from "./TemplateList";
import { useAppLocale, useUI } from "../store";
import { color, font, radius } from "../theme";
import type {
  Locale, NettingRuleEdit, NettingRuleView, NodeConfig, TemplateRef, ValueScope,
} from "../types";
import { useTemplateDetail, useTemplates } from "../lib/queries";
import { ApiError, api } from "../lib/api";
import { useCan } from "../lib/rbac";
import { NATIVE_NAME, useT } from "../i18n";

const SIGN_OPTIONS: { key: string; labelKey: string }[] = [
  { key: "as_reported", labelKey: "tp.sign.asReported" },
  { key: "expense_contra", labelKey: "tp.sign.expenseContra" },
  { key: "auto", labelKey: "tp.sign.auto" },
];

function Radio({ on }: { on: boolean }) {
  return (
    <span
      style={{
        width: 15,
        height: 15,
        borderRadius: "50%",
        border: `2px solid ${on ? color.indigo : color.dashed}`,
        background: on ? color.indigo : "#fff",
        flex: "0 0 auto",
      }}
    />
  );
}

function FieldMock({ label, value }: { label: string; value: string }) {
  return (
    <>
      <div style={{ fontSize: 11, color: color.muted, marginBottom: 4 }}>{label}</div>
      <div
        style={{
          border: `1px solid ${color.cardBorder}`,
          borderRadius: radius.controlSm,
          padding: "7px 10px",
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        {value} ▾
      </div>
    </>
  );
}

/** Render the netting expression: left muted, added token indigo, subtracted token red. */
function NettingExpr({ expr }: { expr: string }) {
  // Format: "face_value = Note12.total − Note12.related_party"
  const eq = expr.indexOf("=");
  const lhs = eq >= 0 ? expr.slice(0, eq).trim() : expr;
  const rhs = eq >= 0 ? expr.slice(eq + 1).trim() : "";
  const parts = rhs.split("−");
  const added = (parts[0] ?? "").trim();
  const subtracted = (parts[1] ?? "").trim();
  const box: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    background: color.rowAltBg,
    border: `1px solid ${color.hairline3}`,
    borderRadius: radius.control,
    padding: "10px 12px",
    fontFamily: font.mono,
    fontSize: 11.5,
    color: color.ink,
    flexWrap: "wrap",
  };
  return (
    <div style={box}>
      <span style={{ color: color.muted }}>{lhs}</span> ={" "}
      <span style={{ color: color.indigo, fontWeight: 600 }}>{added}</span> −{" "}
      <span style={{ color: color.redFg, fontWeight: 600 }}>{subtracted}</span>
    </div>
  );
}

/** A concept that EXISTS in this template. `confusable_with` and every netting key must name
 *  one: the server 422s on an unknown key, so both are picked from this list, never typed. */
interface Concept { key: string; label: string }

type Msg = { ok: boolean; text: string };

/** The server's own `detail` when it sent one — a rejected key or an invalid regex has to say
 *  WHY, verbatim, or the admin is left guessing at what to change. */
function serverText(err: unknown): string {
  return err instanceof ApiError ? (err.detail ?? err.message) : String(err);
}

const textInput: CSSProperties = {
  width: "100%", boxSizing: "border-box", fontFamily: font.sans, fontSize: 12, color: color.ink,
  background: "#fff", border: `1px solid ${color.controlBorder}`, borderRadius: radius.controlSm,
  padding: "7px 10px", outline: "none",
};
const chipBase: CSSProperties = {
  fontSize: 11.5, fontWeight: 500, padding: "5px 11px", borderRadius: radius.pill,
};
// Chips carry meaning by colour: what belongs here (indigo), what must be kept out (red),
// and patterns that are read literally (mono).
const TONE = {
  indigo: { background: color.indigoTint2, color: color.indigo },
  red: { background: color.redBg, color: color.redFg },
  mono: { background: color.rowAltBg, color: color.ink2, fontFamily: font.mono },
} as const;

function FieldLabel({ label, hint }: { label: string; hint?: string }) {
  return (
    <div style={{ marginBottom: 5 }}>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: color.ink2 }}>{label}</div>
      {hint && (
        <div style={{ fontSize: 10.5, color: color.muted, lineHeight: 1.5, marginTop: 2 }}>{hint}</div>
      )}
    </div>
  );
}

/** Pick a concept that exists. A free-text field would let a typo through, and a rule naming
 *  a line that isn't there never fires — indistinguishable from one that simply didn't apply. */
function KeyPicker({ options, placeholder, onPick }: {
  options: Concept[]; placeholder: string; onPick: (key: string) => void;
}) {
  return (
    <select
      value=""
      onChange={(e) => { if (e.target.value) onPick(e.target.value); }}
      style={{ ...textInput, width: "auto", maxWidth: 270, fontSize: 11.5, padding: "5px 9px",
               borderRadius: radius.pill, border: `1px dashed ${color.dashed}`, cursor: "pointer" }}
    >
      <option value="">{placeholder}</option>
      {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
    </select>
  );
}

/** Chips plus an add affordance — deliberately the same interaction as the alias editor, so
 *  every list on this screen behaves the same. Passing `options` swaps the free-text input for
 *  a picker, which is what the canonical-key lists use. */
function ChipList({
  label, hint, items, editable, tone = "indigo", draft, placeholder, testId, options, labelOf,
  onChange, onDraft, t,
}: {
  label: string; hint?: string; items: string[]; editable: boolean; tone?: keyof typeof TONE;
  draft?: string; placeholder?: string; testId?: string; options?: Concept[];
  labelOf?: (v: string) => string; onChange: (next: string[]) => void;
  onDraft?: (v: string) => void; t: (k: string) => string;
}) {
  function commit(raw: string) {
    const v = raw.trim();
    onDraft?.("");
    if (v && !items.includes(v)) onChange([...items, v]);
  }
  return (
    <div style={{ marginBottom: 13 }} data-testid={testId}>
      <FieldLabel label={label} hint={hint} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 7, alignItems: "center" }}>
        {items.map((v) => (
          <span key={v} title={labelOf ? v : undefined} style={{ ...chipBase, ...TONE[tone] }}>
            {labelOf ? labelOf(v) : v}
            {editable && (
              <span
                role="button"
                title={t("tp.removeItem")}
                onClick={() => onChange(items.filter((x) => x !== v))}
                style={{ opacity: 0.55, cursor: "pointer", marginInlineStart: 4, fontWeight: 700 }}
              >
                ×
              </span>
            )}
          </span>
        ))}
        {editable && options && (
          <KeyPicker
            options={options.filter((o) => !items.includes(o.key))}
            placeholder={placeholder ?? ""}
            onPick={(k) => onChange([...items, k])}
          />
        )}
        {editable && !options && (
          <input
            value={draft ?? ""}
            placeholder={placeholder}
            title={t("tp.addItemHint")}
            onChange={(e) => onDraft?.(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(draft ?? ""); } }}
            onBlur={() => commit(draft ?? "")}
            style={{ fontSize: 11.5, padding: "5px 11px", borderRadius: radius.pill,
                     border: `1px dashed ${color.dashed}`, color: color.ink, background: "transparent",
                     minWidth: 170, outline: "none",
                     fontFamily: tone === "mono" ? font.mono : font.sans }}
          />
        )}
        {!editable && items.length === 0 && (
          <span style={{ fontSize: 11.5, color: color.muted }}>{t("tp.noneSet")}</span>
        )}
      </div>
    </div>
  );
}

/** The mapping criteria this editor owns. Normalised on load so an absent field and an empty
 *  one compare equal — the dirty check is then a plain signature comparison. */
interface Criteria {
  definition: string;
  value_scope: ValueScope;
  include: string[];
  exclude: string[];
  confusable_with: string[];
  keyword_hints: string[];
  regex_hints: string[];
  exclude_hints: string[];
}
type CriteriaList = Exclude<keyof Criteria, "definition" | "value_scope">;

const EMPTY_DRAFTS: Record<CriteriaList, string> = {
  include: "", exclude: "", confusable_with: "", keyword_hints: "", regex_hints: "",
  exclude_hints: "",
};

function criteriaOf(cfg: NodeConfig): Criteria {
  return {
    definition: cfg.definition ?? "",
    value_scope: cfg.value_scope ?? "exclusive_leaf",
    include: cfg.include ?? [],
    exclude: cfg.exclude ?? [],
    confusable_with: cfg.confusable_with ?? [],
    keyword_hints: cfg.keyword_hints ?? [],
    regex_hints: cfg.regex_hints ?? [],
    exclude_hints: cfg.exclude_hints ?? [],
  };
}
const criteriaSig = (c: Criteria) => JSON.stringify(c);

/** What a save would persist: the committed chips plus whatever is still sitting in a list's
 *  input. Folded in here (rather than trusting blur to fire before the button's click) so
 *  typing a criterion and clicking Save directly can never drop it. `confusable_with` has no
 *  text input — it is picked — and simply never carries a draft. */
function withDrafts(c: Criteria, drafts: Record<CriteriaList, string>): Criteria {
  const out: Criteria = { ...c };
  (Object.keys(drafts) as CriteriaList[]).forEach((f) => {
    const v = drafts[f].trim();
    if (v && !out[f].includes(v)) out[f] = [...out[f], v];
  });
  return out;
}

// The four value scopes the backend accepts, each with an explanation — an analyst has no
// reason to know what "exclusive_residual" means, and picking the wrong one silently changes
// whether the figure is taken as printed, netted out of its parent, or computed.
const VALUE_SCOPES: { key: ValueScope; labelKey: string; hintKey: string }[] = [
  { key: "exclusive_leaf", labelKey: "tp.scope.leaf", hintKey: "tp.scope.leafHint" },
  { key: "exclusive_child", labelKey: "tp.scope.child", hintKey: "tp.scope.childHint" },
  { key: "exclusive_residual", labelKey: "tp.scope.residual", hintKey: "tp.scope.residualHint" },
  { key: "not_applicable", labelKey: "tp.scope.na", hintKey: "tp.scope.naHint" },
];

/** The criteria the mapper actually reasons over — grouped (meaning first, lexical hints
 *  second) so the editor reads as sections instead of a wall of inputs. Values are lifted:
 *  saving is the surrounding node editor's single Save, so one bar covers every change. */
function CriteriaEditor({
  criteria, drafts, concepts, canonicalKey, editable, onChange, onDraft, t,
}: {
  criteria: Criteria; drafts: Record<CriteriaList, string>; concepts: Concept[];
  canonicalKey: string | undefined; editable: boolean;
  onChange: (patch: Partial<Criteria>) => void;
  onDraft: (field: CriteriaList, v: string) => void; t: (k: string) => string;
}) {
  // A concept is never confusable with itself, and only keys in this ontology are legal.
  const others = concepts.filter((c) => c.key !== canonicalKey);
  const labelOf = (k: string) => concepts.find((c) => c.key === k)?.label ?? k;
  const list = (field: CriteriaList, labelKey: string, hintKey: string, phKey: string,
                tone: keyof typeof TONE) => (
    <ChipList
      label={t(labelKey)} hint={t(hintKey)} placeholder={t(phKey)} tone={tone}
      items={criteria[field]} draft={drafts[field]} editable={editable}
      testId={`criteria-${field}`}
      onChange={(next) => onChange({ [field]: next } as Partial<Criteria>)}
      onDraft={(v) => onDraft(field, v)} t={t}
    />
  );

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{t("tp.criteria")}</div>
      <p style={{ margin: "0 0 14px", fontSize: 11.5, color: color.sec2, lineHeight: 1.55 }}>
        {t("tp.criteriaHint")}
      </p>

      <FieldLabel label={t("tp.definition")} hint={t("tp.definitionHint")} />
      {editable ? (
        <textarea
          data-testid="criteria-definition"
          value={criteria.definition}
          rows={3}
          placeholder={t("tp.definitionPh")}
          onChange={(e) => onChange({ definition: e.target.value })}
          style={{ ...textInput, resize: "vertical", lineHeight: 1.55, marginBottom: 14 }}
        />
      ) : (
        <p style={{ margin: "0 0 14px", fontSize: 12, lineHeight: 1.55,
                    color: criteria.definition ? color.sec : color.muted }}>
          {criteria.definition || t("tp.noneSet")}
        </p>
      )}

      <FieldLabel label={t("tp.valueScope")} hint={t("tp.valueScopeHint")} />
      {editable ? (
        <select
          data-testid="criteria-scope"
          value={criteria.value_scope}
          onChange={(e) => onChange({ value_scope: e.target.value as ValueScope })}
          style={{ ...textInput, cursor: "pointer" }}
        >
          {VALUE_SCOPES.map((s) => <option key={s.key} value={s.key}>{t(s.labelKey)}</option>)}
        </select>
      ) : (
        <div style={{ fontSize: 12, fontWeight: 500 }}>
          {t((VALUE_SCOPES.find((s) => s.key === criteria.value_scope) ?? VALUE_SCOPES[0]).labelKey)}
        </div>
      )}
      {/* Every option explained, not just the chosen one — the choice is only meaningful
          against the alternatives. */}
      <div style={{ margin: "8px 0 16px", display: "flex", flexDirection: "column", gap: 4 }}>
        {VALUE_SCOPES.map((s) => {
          const on = s.key === criteria.value_scope;
          return (
            <div key={s.key} style={{ fontSize: 10.5, lineHeight: 1.5,
                                      color: on ? color.sec : color.muted }}>
              <b style={{ color: on ? color.indigo : color.sec2 }}>{t(s.labelKey)}</b>
              {" — "}{t(s.hintKey)}
            </div>
          );
        })}
      </div>

      {list("include", "tp.include", "tp.includeHint", "tp.includePh", "indigo")}
      {list("exclude", "tp.exclude", "tp.excludeHint", "tp.excludePh", "red")}
      <ChipList
        label={t("tp.confusable")} hint={t("tp.confusableHint")} placeholder={t("tp.confusablePick")}
        items={criteria.confusable_with} editable={editable} options={others} labelOf={labelOf}
        testId="criteria-confusable_with"
        onChange={(next) => onChange({ confusable_with: next })} t={t}
      />

      <div style={{ borderTop: `1px solid ${color.hairline3}`, marginTop: 3, paddingTop: 13,
                    marginBottom: 12, fontSize: 11.5, fontWeight: 600, color: color.sec }}>
        {t("tp.lexicalGroup")}
      </div>
      {list("keyword_hints", "tp.keywordHints", "tp.keywordHintsHint", "tp.keywordHintsPh", "indigo")}
      {list("regex_hints", "tp.regexHints", "tp.regexHintsHint", "tp.regexHintsPh", "mono")}
      {list("exclude_hints", "tp.excludeHints", "tp.excludeHintsHint", "tp.excludeHintsPh", "red")}
    </Card>
  );
}

/** One netting policy. Admins edit its key sets, condition and explanation in place; everyone
 *  else sees exactly the read-only expression. Each save publishes a new ontology version via
 *  `apply`, which the card above owns so the confirmation survives the refetch. */
function NettingRuleRow({ rule, concepts, editable, isNew, apply, onDone, t }: {
  rule: NettingRuleView; concepts: Concept[]; editable: boolean; isNew?: boolean;
  apply: (edit: NettingRuleEdit) => Promise<boolean>; onDone?: () => void;
  t: (k: string) => string;
}) {
  const stored = {
    target: rule.target_key,
    subtract: rule.subtract.map((c) => c.key),
    add: rule.add.map((c) => c.key),
    condition: rule.condition ?? "",
    label: rule.label ?? "",
  };
  const sig = JSON.stringify(stored);
  const [form, setForm] = useState(stored);
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);

  // Adopt stored truth when the rule changes under us: our own save's refetch, or another
  // admin's edit. The card-level save confirmation is deliberately left alone.
  const seen = useRef(sig);
  useEffect(() => {
    if (seen.current !== sig) {
      seen.current = sig;
      setForm(stored);
      setConfirmDel(false);
    }
  }, [sig, stored]);

  /** Prefer the template's own label for a key, then the labels the server sent with this
   *  rule (a netted line need not be a leaf of the tree the editor shows). */
  function labelOf(k: string): string {
    const inTemplate = concepts.find((c) => c.key === k);
    if (inTemplate) return inTemplate.label;
    const inRule = [...rule.subtract, ...rule.add].find((c) => c.key === k);
    if (inRule) return inRule.label;
    if (k === rule.target_key && rule.target_label) return rule.target_label;
    return k;
  }

  const dirty = JSON.stringify(form) !== sig;
  const patch = (p: Partial<typeof stored>) => setForm((f) => ({ ...f, ...p }));
  // A line cannot be netted against itself, nor subtracted and added at once.
  const others = concepts.filter((c) => c.key !== form.target);

  async function save() {
    if (!form.target || !dirty || busy) return;
    setBusy("save");
    const ok = await apply({
      id: rule.id, target_key: form.target, subtract_keys: form.subtract, add_keys: form.add,
      condition: form.condition, label: form.label,
    });
    setBusy(null);
    if (ok) onDone?.();
  }

  async function remove() {
    if (busy) return;
    setBusy("delete");
    await apply({ id: rule.id, delete: true });
    setBusy(null);
  }

  const btn: CSSProperties = {
    fontSize: 12, fontWeight: 600, color: "#fff", background: color.indigo, border: "none",
    borderRadius: radius.control, padding: "7px 13px",
  };
  const ghost: CSSProperties = {
    fontSize: 12, color: color.sec, background: "none",
    border: `1px solid ${color.controlBorder}`, borderRadius: radius.control, padding: "7px 12px",
    cursor: "pointer",
  };

  return (
    <div data-testid="netting-rule"
         style={{ border: `1px solid ${color.hairline3}`, borderRadius: radius.control, padding: 12 }}>
      {isNew && (
        <div style={{ marginBottom: 11 }}>
          <FieldLabel label={t("tp.nettingTarget")} hint={t("tp.nettingTargetHint")} />
          <select
            data-testid="netting-target"
            value={form.target}
            onChange={(e) => patch({ target: e.target.value })}
            style={{ ...textInput, cursor: "pointer" }}
          >
            <option value="">{t("tp.nettingTargetPick")}</option>
            {concepts.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </div>
      )}

      {form.target && (
        <div style={{ fontFamily: font.mono, fontSize: 11.5, color: color.ink, marginBottom: 6,
                      display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span style={{ fontWeight: 600, color: color.indigo }}>{labelOf(form.target)}</span>
          <span style={{ color: color.muted }}>=</span>
          <span style={{ color: color.muted }}>{labelOf(form.target)}</span>
          {form.subtract.map((k) => (
            <span key={k} style={{ color: color.redFg, fontWeight: 600 }}>− {labelOf(k)}</span>
          ))}
          {form.add.map((k) => (
            <span key={k} style={{ color: color.greenFg, fontWeight: 600 }}>+ {labelOf(k)}</span>
          ))}
        </div>
      )}

      {!editable && (
        <>
          {rule.label && (
            <div style={{ fontSize: 11.5, color: color.sec, lineHeight: 1.5 }}>{rule.label}</div>
          )}
          {rule.condition && (
            <div style={{ fontSize: 11, color: color.muted, lineHeight: 1.5, marginTop: 6 }}>
              <b style={{ color: color.sec2 }}>{t("tp.nettingWhen")}:</b> {rule.condition}
            </div>
          )}
        </>
      )}

      {editable && (
        <div style={{ marginTop: 10 }}>
          <ChipList
            label={t("tp.nettingSubtract")} hint={t("tp.nettingSubtractHint")}
            placeholder={t("tp.nettingKeyPick")} tone="red" items={form.subtract} editable
            options={others.filter((o) => !form.add.includes(o.key))} labelOf={labelOf}
            testId="netting-subtract" onChange={(next) => patch({ subtract: next })} t={t}
          />
          <ChipList
            label={t("tp.nettingAddKeys")} hint={t("tp.nettingAddKeysHint")}
            placeholder={t("tp.nettingKeyPick")} items={form.add} editable
            options={others.filter((o) => !form.subtract.includes(o.key))} labelOf={labelOf}
            testId="netting-add-keys" onChange={(next) => patch({ add: next })} t={t}
          />
          <FieldLabel label={t("tp.nettingCondition")} hint={t("tp.nettingConditionHint")} />
          <textarea
            value={form.condition} rows={2} placeholder={t("tp.nettingConditionPh")}
            onChange={(e) => patch({ condition: e.target.value })}
            style={{ ...textInput, resize: "vertical", lineHeight: 1.5, marginBottom: 12 }}
          />
          <FieldLabel label={t("tp.nettingLabel")} />
          <input
            data-testid="netting-label"
            value={form.label} placeholder={t("tp.nettingLabelPh")}
            onChange={(e) => patch({ label: e.target.value })}
            style={{ ...textInput, marginBottom: 12 }}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
            <button
              data-testid="netting-save" onClick={save}
              disabled={!form.target || !dirty || !!busy}
              style={{ ...btn, cursor: !form.target || !dirty || busy ? "default" : "pointer",
                       opacity: !form.target || !dirty ? 0.5 : 1 }}
            >
              {/* Labelled apart from the concept editor's Save: on this screen two different
                  things can be pending at once, and "Save changes" would be ambiguous. */}
              {busy === "save" ? t("tp.saving") : t("tp.nettingSave")}
            </button>
            {isNew ? (
              <button onClick={onDone} style={ghost}>{t("tp.nettingCancel")}</button>
            ) : dirty && !busy ? (
              <button onClick={() => { setForm(stored); setConfirmDel(false); }} style={ghost}>
                {t("tp.revert")}
              </button>
            ) : null}
            {dirty && <span style={{ fontSize: 11, color: color.muted }}>{t("tp.unsaved")}</span>}
            <span style={{ flex: 1 }} />
            <span style={{ fontFamily: font.mono, fontSize: 10, color: color.faint }}>{rule.id}</span>
            {!isNew && (
              <button
                data-testid="netting-delete"
                onClick={confirmDel ? remove : () => setConfirmDel(true)}
                style={{ ...ghost, color: color.redFg, borderColor: color.redFg }}
              >
                {busy === "delete" ? t("tp.deleting")
                  : confirmDel ? t("tp.nettingDeleteConfirm") : t("tp.nettingDelete")}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Template-wide netting policies (LLM-gated): a target line net of the components it may
 *  include, applied per-document only when the model confirms the containment. Editable by
 *  admins because netting RESTATES a reported figure — so it goes through the same versioned
 *  publish as a concept edit, never an in-place change. */
function NettingRules({ rules, concepts, ontologyId, canEdit, t }: {
  rules: NettingRuleView[]; concepts: Concept[]; ontologyId: string | undefined;
  canEdit: boolean; t: (k: string) => string;
}) {
  const qc = useQueryClient();
  const editable = canEdit && !!ontologyId;
  const [msg, setMsg] = useState<Msg | null>(null);
  // Id of the rule being drafted, generated once per draft so the upsert creates a rule
  // instead of overwriting an existing one.
  const [adding, setAdding] = useState<string | null>(null);

  /** The single place a rule edit is published: report the version it created, then re-read
   *  the detail so the card shows stored truth. The message lives here, not in the row, so it
   *  survives both the refetch and the draft editor unmounting. */
  async function apply(edit: NettingRuleEdit): Promise<boolean> {
    if (!ontologyId) return false;
    setMsg(null);
    try {
      const res = await api.editNettingRule(ontologyId, edit);
      setMsg({ ok: true, text: t("tp.saved").replace("{v}", String(res.version)) });
      await qc.invalidateQueries({ queryKey: ["template-detail"] });
      qc.invalidateQueries({ queryKey: ["ontologies"] });
      return true;
    } catch (err) {
      setMsg({ ok: false, text: `${t("tp.saveErr")} ${serverText(err)}`.slice(0, 300) });
      return false;
    }
  }

  return (
    <Card style={{ marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.nettingRules")}</span>
        <span style={{ fontSize: 9.5, fontWeight: 600, padding: "2px 7px", borderRadius: radius.pill,
                       background: color.amberBg, color: color.amberFg }}>{t("tp.nettingLLM")}</span>
      </div>
      <p style={{ margin: "0 0 12px", fontSize: 11.5, color: color.sec2, lineHeight: 1.55 }}>
        {t("tp.nettingRulesHint")}
      </p>
      {rules.length === 0 && !adding ? (
        <div style={{ fontSize: 12, color: color.muted }}>{t("tp.nettingNone")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rules.map((r) => (
            <NettingRuleRow key={r.id} rule={r} concepts={concepts} editable={editable}
                            apply={apply} t={t} />
          ))}
          {adding && (
            <NettingRuleRow
              key={adding} isNew editable
              rule={{ id: adding, target_key: "", target_label: "", subtract: [], add: [],
                      condition: "", label: "" }}
              concepts={concepts} apply={apply} onDone={() => setAdding(null)} t={t}
            />
          )}
        </div>
      )}
      {editable && !adding && (
        <button
          data-testid="netting-add"
          onClick={() => setAdding(`netting_${Date.now().toString(36)}`)}
          style={{ marginTop: 12, fontSize: 12, fontWeight: 600, color: color.indigo,
                   background: "#fff", border: `1px dashed ${color.indigoBorder2}`,
                   borderRadius: radius.control, padding: "8px 13px", cursor: "pointer" }}
        >
          {t("tp.nettingAdd")}
        </button>
      )}
      {msg && (
        <div style={{ marginTop: 11, fontSize: 11.5, lineHeight: 1.5,
                      color: msg.ok ? color.greenFg : color.redFg }}>
          {msg.text}
        </div>
      )}
    </Card>
  );
}

/** Editable ontology rules for the selected concept: the aliases the extractor matches on, the
 *  sign convention, and the criteria the mapper reasons over (definition / include / exclude /
 *  confusable-with / scope / lexical hints). Saving publishes a NEW ontology version
 *  server-side (history preserved), then re-reads the screen so what you see is the stored
 *  result, not local optimism. */
function NodeRules({ cfg, canonicalKey, ontologyId, concepts, locale, canEdit, t }: {
  cfg: NodeConfig; canonicalKey: string | undefined; ontologyId: string | undefined;
  concepts: Concept[]; locale: Locale; canEdit: boolean; t: (k: string) => string;
}) {
  const qc = useQueryClient();
  // Edit the RAW per-locale list (falls back to the merged set when the backend predates it).
  const stored = cfg.aliases_locale ?? cfg.aliases;
  const storedCriteria = criteriaOf(cfg);
  const [aliases, setAliases] = useState<string[]>(stored);
  const [sign, setSign] = useState<string>(cfg.sign);
  const [criteria, setCriteria] = useState<Criteria>(storedCriteria);
  const [draft, setDraft] = useState("");
  const [drafts, setDrafts] = useState<Record<CriteriaList, string>>(EMPTY_DRAFTS);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg | null>(null);

  // Switching concept (or language) starts a fresh edit: drop the pending drafts AND the last
  // save message, which belonged to the previous concept.
  const conceptKey = `${canonicalKey}|${locale}`;
  const seenConcept = useRef(conceptKey);
  useEffect(() => {
    if (seenConcept.current !== conceptKey) {
      seenConcept.current = conceptKey;
      setAliases(stored);
      setSign(cfg.sign);
      setCriteria(storedCriteria);
      setDraft("");
      setDrafts(EMPTY_DRAFTS);
      setMsg(null);
    }
  }, [conceptKey, stored, cfg.sign, storedCriteria]);

  // Adopt server truth when the stored rules change under us: our own save's refetch, or
  // another admin's edit. Deliberately does NOT clear `msg` -- the save confirmation has to
  // survive the very refetch that saving triggered.
  const storedKey = `${stored.join(" ")}|${cfg.sign}|${criteriaSig(storedCriteria)}`;
  const seenStored = useRef(storedKey);
  useEffect(() => {
    if (seenStored.current !== storedKey) {
      seenStored.current = storedKey;
      setAliases(stored);
      setSign(cfg.sign);
      setCriteria(storedCriteria);
    }
  }, [storedKey, stored, cfg.sign, storedCriteria]);

  const editable = canEdit && !!ontologyId && !!canonicalKey;
  // What a save would persist: the committed chips plus any alias still sitting in the input.
  // Folding the draft in here (rather than relying on the input's blur firing before the
  // button's click) means typing an alias and clicking Save directly can never drop it.
  const pending = draft.trim();
  const effective = pending && !aliases.includes(pending) ? [...aliases, pending] : aliases;
  const effCriteria = withDrafts(criteria, drafts);
  const dirty = effective.join(" ") !== stored.join(" ") || sign !== cfg.sign
    || criteriaSig(effCriteria) !== criteriaSig(storedCriteria);
  // The merged display set minus what we edit here = aliases inherited from the fallback
  // locale. Shown read-only so it's clear why the extractor also matches them.
  const inherited = cfg.aliases.filter((a) => !stored.includes(a));

  function addDraft() {
    const v = draft.trim();
    if (!v) return;
    if (!aliases.includes(v)) setAliases([...aliases, v]);
    setDraft("");
  }

  function discard() {
    setAliases(stored);
    setSign(cfg.sign);
    setCriteria(storedCriteria);
    setDraft("");
    setDrafts(EMPTY_DRAFTS);
    setMsg(null);
  }

  async function save() {
    if (!editable || !dirty) return;
    setBusy(true);
    setMsg(null);
    try {
      // One PATCH for the whole concept: aliases, sign and criteria are validated together,
      // so a bad regex or an unknown key cannot leave half the edit published.
      const res = await api.editOntologyMapping(ontologyId!, {
        canonical_key: canonicalKey!, locale, aliases: effective, sign_convention: sign,
        definition: effCriteria.definition, value_scope: effCriteria.value_scope,
        include: effCriteria.include, exclude: effCriteria.exclude,
        confusable_with: effCriteria.confusable_with, keyword_hints: effCriteria.keyword_hints,
        regex_hints: effCriteria.regex_hints, exclude_hints: effCriteria.exclude_hints,
      });
      setAliases(effective);
      setCriteria(effCriteria);
      setDraft("");
      setDrafts(EMPTY_DRAFTS);
      setMsg({ ok: true, text: t("tp.saved").replace("{v}", String(res.version)) });
      // Re-read the detail (and the ontology list) so the screen shows the stored version.
      await qc.invalidateQueries({ queryKey: ["template-detail"] });
      qc.invalidateQueries({ queryKey: ["ontologies"] });
    } catch (err) {
      setMsg({ ok: false, text: `${t("tp.saveErr")} ${serverText(err)}`.slice(0, 300) });
    } finally {
      setBusy(false);
    }
  }

  const chip: CSSProperties = { ...chipBase, ...TONE.indigo };

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between",
                      gap: 10, marginBottom: 11 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.aliases")}</span>
          {editable && (
            <span style={{ fontSize: 10.5, color: color.muted }}>
              {t("tp.editingLocale")} {NATIVE_NAME[locale]}
            </span>
          )}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7, alignItems: "center" }}>
          {aliases.map((a) => (
            <span key={a} style={chip}>
              {a}
              {editable && (
                <span
                  role="button"
                  title={t("tp.revert")}
                  onClick={() => setAliases(aliases.filter((x) => x !== a))}
                  style={{ opacity: 0.55, cursor: "pointer", marginInlineStart: 4, fontWeight: 700 }}
                >
                  ×
                </span>
              )}
            </span>
          ))}
          {editable && (
            <input
              value={draft}
              placeholder={t("tp.newAlias")}
              title={t("tp.addAliasHint")}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); addDraft(); }
              }}
              onBlur={addDraft}
              style={{ fontSize: 11.5, padding: "5px 11px", borderRadius: radius.pill,
                       border: `1px dashed ${color.dashed}`, color: color.ink,
                       background: "transparent", minWidth: 130, outline: "none" }}
            />
          )}
          {/* Aliases coming from the fallback locale — matched by the extractor, edited under
              their own language, so they're shown here read-only rather than silently merged. */}
          {inherited.map((a) => (
            <span key={`inh-${a}`} title={t("tp.viewOnly")}
                  style={{ ...chip, background: color.rowAltBg, color: color.muted }}>
              {a}
            </span>
          ))}
        </div>
      </Card>

      {/* The criteria the mapper reasons over — aliases only fire on close wording. */}
      <CriteriaEditor
        criteria={criteria}
        drafts={drafts}
        concepts={concepts}
        canonicalKey={canonicalKey}
        editable={editable}
        onChange={(p) => setCriteria((c) => ({ ...c, ...p }))}
        onDraft={(field, v) => setDrafts((d) => ({ ...d, [field]: v }))}
        t={t}
      />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>{t("tp.signConvention")}</div>
          {SIGN_OPTIONS.map((opt) => {
            const on = opt.key === sign;
            return (
              <div
                key={opt.key}
                role={editable ? "button" : undefined}
                onClick={editable ? () => setSign(opt.key) : undefined}
                style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 0",
                         cursor: editable ? "pointer" : "default" }}
              >
                <Radio on={on} />
                <span style={{ fontSize: 12, color: on ? color.ink : color.sec2, fontWeight: on ? 600 : 400 }}>
                  {t(opt.labelKey)}
                </span>
              </div>
            );
          })}
        </Card>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>{t("tp.dataTypeUnits")}</div>
          <div style={{ marginBottom: 11 }}>
            <FieldMock label={t("tp.valueType")} value={cfg.value_type} />
          </div>
          <FieldMock label={t("tp.aggregation")} value={cfg.aggregation} />
        </Card>
      </div>

      {editable && (dirty || msg) && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <button
            onClick={save}
            disabled={busy || !dirty}
            style={{ fontSize: 12, fontWeight: 600, color: "#fff", background: color.indigo,
                     border: "none", borderRadius: radius.control, padding: "8px 14px",
                     cursor: busy || !dirty ? "default" : "pointer", opacity: dirty ? 1 : 0.5 }}
          >
            {busy ? t("tp.saving") : t("tp.save")}
          </button>
          {dirty && !busy && (
            <button
              onClick={discard}
              style={{ fontSize: 12, color: color.sec, background: "none",
                       border: `1px solid ${color.controlBorder}`, borderRadius: radius.control,
                       padding: "8px 12px", cursor: "pointer" }}
            >
              {t("tp.revert")}
            </button>
          )}
          {dirty && <span style={{ fontSize: 11, color: color.muted }}>{t("tp.unsaved")}</span>}
          {msg && (
            <span style={{ fontSize: 11.5, color: msg.ok ? color.greenFg : color.redFg }}>
              {msg.text}
            </span>
          )}
        </div>
      )}
    </>
  );
}


/** Page 2 — one template's detail, raised over the index.
 *
 * Everything that belongs to a single template is here: its structure tree, the concept editor,
 * the netting policies. The way back to the list is rendered BEFORE the body and in every state,
 * including the two states where there is nothing to show — a reader who followed a stale
 * `?template=` link must not land on a screen with no exit.
 */
function TemplateDetail({ id, tpl, locale, canEdit, onDismiss, t }: {
  id: string; tpl: TemplateRef | undefined; locale: Locale; canEdit: boolean;
  onDismiss: () => void; t: (k: string) => string;
}) {
  const { data, isError } = useTemplateDetail(id, locale);
  const tplSel = useUI((s) => s.tplSel);
  const setTpl = useUI((s) => s.setTpl);

  const cfg: NodeConfig | undefined = data
    ? (data.node_config[tplSel] ?? data.node_config["trade_recv"]
       ?? Object.values(data.node_config)[0])
    : undefined;
  // Every concept this template maps, in statement order — the only legal values for
  // `confusable_with` and for a netting rule's keys, so both are picked from here.
  const concepts: Concept[] = Object.entries(data?.node_config ?? {})
    .map(([key, c]) => ({ key, label: c.label || key }));

  function body() {
    if (isError) {
      return (
        <div style={{ maxWidth: 520, margin: "60px auto", textAlign: "center", color: color.muted,
                      padding: "0 24px", fontSize: 12.5, lineHeight: 1.6 }}>
          {t("tp.detail.gone")}
        </div>
      );
    }
    if (!data) {
      return (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                      color: color.muted }}>
          {t("empty.loading")}
        </div>
      );
    }
    // Greenfield (no project loaded yet): the template tree is empty. Show guidance rather
    // than crashing on a missing node config.
    if (!data.tree.length || !cfg) {
      return (
        <div style={{ maxWidth: 560, margin: "60px auto", textAlign: "center", color: color.muted,
                      padding: "0 24px" }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>◆</div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: color.ink, marginBottom: 8 }}>
            {t("tp.emptyTitle")}
          </h1>
          <p style={{ fontSize: 12.5, lineHeight: 1.6 }}>{t("tp.emptyHint")}</p>
        </div>
      );
    }

    return (
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* LEFT: template tree */}
        <div
          style={{
            width: 360,
            flex: "0 0 360px",
            borderRight: `1px solid ${color.cardBorder}`,
            background: color.surface,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div style={{ padding: 16, flex: "0 0 auto", borderBottom: `1px solid ${color.hairline3}` }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 3 }}>{t("tp.structure")}</h2>
            <div style={{ fontSize: 11.5, color: color.muted }}>
              {data.template.line_items} {t("tp.lineItems")}
            </div>
          </div>

          <div style={{ flex: 1, overflowY: "auto", minHeight: 0, padding: "8px 6px" }}>
            {data.tree.map((node) => {
              const sel = node.id === tplSel;
              const head = !!node.head;
              return (
                <div
                  key={node.id}
                  // Only leaves map to a concept (headings carry no ontology rules to edit).
                  data-testid={head ? undefined : "tpl-node"}
                  onClick={() => setTpl(node.id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "7px 10px",
                    borderRadius: radius.controlSm,
                    cursor: "pointer",
                    background: sel ? color.indigoTint : "transparent",
                    marginLeft: node.lvl * 16,
                  }}
                >
                  <span style={{ fontSize: 10, color: color.faint, width: 10 }}>{head ? "▾" : ""}</span>
                  <span
                    style={{
                      flex: 1,
                      fontSize: 12,
                      fontWeight: head ? 700 : sel ? 600 : 400,
                      color: head ? color.viewerBg : sel ? color.indigo : color.ink2,
                    }}
                  >
                    {node.label}
                  </span>
                  {node.rule && (
                    <span
                      style={{
                        fontSize: 9.5,
                        fontWeight: 600,
                        padding: "1px 6px",
                        borderRadius: 4,
                        background: color.indigoTint2,
                        color: color.indigo,
                      }}
                    >
                      rule
                    </span>
                  )}
                </div>
              );
            })}
          </div>

        </div>

        {/* RIGHT: node editor */}
        <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "26px 30px" }}>
          <div style={{ maxWidth: 680 }}>
            <div style={{ fontSize: 11, color: color.muted, marginBottom: 3 }}>{cfg.breadcrumb}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 3 }}>
              <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>{cfg.label}</h1>
              {!canEdit && (
                <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: radius.pill,
                               background: color.rowAltBg, color: color.muted, border: `1px solid ${color.hairline3}` }}>
                  {t("tp.viewOnly")}
                </span>
              )}
            </div>
            <p style={{ margin: "0 0 20px", color: color.sec2, fontSize: 12.5 }}>
              {canEdit ? t("tp.editorSubhead") : t("tp.viewOnlyHint")}
            </p>

            {/* Editable ontology rules for this concept (aliases + sign + mapping criteria),
                saved as a new version */}
            <NodeRules
              cfg={cfg}
              canonicalKey={cfg.canonical_key ?? tplSel}
              ontologyId={data.ontology?.id}
              concepts={concepts}
              locale={locale}
              canEdit={canEdit}
              t={t}
            />

            {/* Note-to-face netting rule (flagship) */}
            <div
              style={{
                background: color.surface,
                border: `1px solid ${color.indigoBorder}`,
                borderRadius: radius.card,
                padding: 18,
                borderLeft: `3px solid ${color.indigo}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.nettingRule")}</span>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "2px 7px",
                    borderRadius: radius.pill,
                    background: color.indigoTint2,
                    color: color.indigo,
                  }}
                >
                  {t("tp.key")}
                </span>
              </div>
              <p style={{ margin: "0 0 12px", fontSize: 12, color: color.sec, lineHeight: 1.55 }}>
                {cfg.netting.explain}
              </p>
              <NettingExpr expr={cfg.netting.expr} />
            </div>

            {/* Template-wide containment-netting policies (LLM-gated), admin-editable. */}
            {data.netting_rules && (
              <NettingRules rules={data.netting_rules} concepts={concepts}
                            ontologyId={data.ontology?.id} canEdit={canEdit} t={t} />
            )}
          </div>
        </div>
      </div>
    );
  }

  const name = tpl?.name || data?.template.name || tpl?.template_key || "";
  return (
    <div
      data-testid="template-detail"
      style={{
        position: "absolute", inset: 0, zIndex: 5, background: color.pageBg,
        display: "flex", flexDirection: "column", minHeight: 0,
      }}
    >
      <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 12,
                    padding: "11px 18px", background: color.surface,
                    borderBottom: `1px solid ${color.cardBorder}` }}>
        <button
          data-testid="tpl-detail-close"
          onClick={onDismiss}
          style={{ fontSize: 12, fontWeight: 600, color: color.indigo, background: "#fff",
                   border: `1px solid ${color.indigoBorder2}`, borderRadius: radius.control,
                   padding: "7px 12px", cursor: "pointer", whiteSpace: "nowrap" }}
        >
          {t("tp.detail.back")}
        </button>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: color.ink }}>{name}</div>
          <div style={{ fontSize: 11, color: color.muted, fontFamily: font.mono }}>
            {[tpl?.template_key ?? data?.template.key, tpl && `v${tpl.version}`]
              .filter(Boolean).join(" · ")}
          </div>
        </div>
      </div>
      {body()}
    </div>
  );
}

export default function TemplateScreen() {
  const locale = useAppLocale();
  const t = useT();
  // Render the REAL configured template(s), not the demo project: the index lists the templates
  // that exist, and a row's detail (tree + per-node config) comes from that template and its
  // paired ontology.
  const tplList = useTemplates();
  const canEdit = useCan("config:template"); // authoring is admin-only
  // Which template's detail is up lives in the URL, so a reload — and the browser's own Back
  // button — return to what was on screen instead of resetting to the index.
  const [params, setParams] = useSearchParams();
  const openId = params.get("template") ?? undefined;
  // The version the authoring buttons act on. It follows the last row opened or picked, and
  // falls back to the first template so Download/Upload are never aimed at nothing.
  const [picked, setPicked] = useState<string | undefined>(undefined);

  if (!tplList.data) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                    height: "100%", color: color.muted }}>
        {t("empty.loading")}
      </div>
    );
  }

  const templates = tplList.data;
  // Default the authoring target to the index's first row rather than the API's first record: the
  // list shows the newest version of a template at the top, and that is the one an admin means by
  // "the active template" when they download it to edit.
  const activeId = picked ?? openId ?? sortTemplates(templates)[0]?.id;

  function setOpen(id: string | undefined) {
    const next = new URLSearchParams(params);
    if (id) next.set("template", id);
    else next.delete("template");
    setParams(next);
  }

  return (
    <div style={{ position: "relative", height: "100%", minHeight: 0, display: "flex",
                  flexDirection: "column", overflow: "hidden" }}>
      {/* The index stays MOUNTED under the detail: dismissing has to put the reader back on the
          list they were reading, with its filter and scroll position, not on a fresh one. */}
      <TemplateList
        templates={templates}
        activeId={activeId}
        canEdit={canEdit}
        locale={locale}
        onPick={setPicked}
        onOpen={(id) => { setPicked(id); setOpen(id); }}
        t={t}
      />
      {openId && (
        <TemplateDetail
          id={openId}
          tpl={templates.find((x) => x.id === openId)}
          locale={locale}
          canEdit={canEdit}
          onDismiss={() => setOpen(undefined)}
          t={t}
        />
      )}
    </div>
  );
}
