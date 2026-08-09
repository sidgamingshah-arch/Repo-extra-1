"""Document endpoints: upload (+ upfront integrity/classification) and fetch."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import db, object_store
from app.ports.object_store import LocalObjectStore
from app.security import Permission, Principal, Role, current_principal, require
from app.services.documents import analyze_document, content_hash

router = APIRouter(prefix="/documents", tags=["documents"])

_ELEVATED = {Role.ADMIN, Role.REVIEWER}  # roles that work across the whole queue


def _can_access(doc, principal: Principal) -> bool:
    """A document is visible to its uploader, and to reviewers/admins who work every
    analyst's queue. Ownerless (legacy/seeded) documents stay open."""
    return principal.role in _ELEVATED or not doc.owner or doc.owner == principal.username


def authorized_document(
    document_id: str,
    session: Session = Depends(db),
    principal: Principal = Depends(current_principal),
):
    """Resolve a document and enforce ownership. Returns 404 (not 403) for a document the
    caller may not see, so existence isn't leaked across tenants."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None or not _can_access(row, principal):
        raise HTTPException(status_code=404, detail="Document not found")
    return row

# Bounded translations for the fixed vocabulary the real integrity/review surfaces emit, so
# a real run localizes like the demo path. Dynamic parts (source labels, finding messages)
# stay verbatim — they're data, not chrome.
_TR: dict[str, dict[str, str]] = {
    # integrity grades
    "Not analyzed": {"zh": "未分析", "ar": "لم يُحلَّل", "fr": "Non analysé"},
    "Blocked": {"zh": "已阻止", "ar": "محظور", "fr": "Bloqué"},
    "Ready to extract": {"zh": "可提取", "ar": "جاهز للاستخراج", "fr": "Prêt à extraire"},
    "Minor issues": {"zh": "存在小问题", "ar": "مشكلات طفيفة", "fr": "Problèmes mineurs"},
    "Needs attention": {"zh": "需要关注", "ar": "يتطلب انتباهًا", "fr": "À vérifier"},
    # summaries
    "No integrity report is available for this document. Re-upload to run the pre-flight checks.":
        {"zh": "该文档没有可用的完整性报告。请重新上传以运行预检。",
         "ar": "لا يتوفر تقرير سلامة لهذا المستند. أعد الرفع لتشغيل الفحوصات المسبقة.",
         "fr": "Aucun rapport d'intégrité disponible pour ce document. Re-téléversez pour lancer les contrôles."},
    "Resolve the blocking issues before extracting.":
        {"zh": "请在提取前解决阻断性问题。", "ar": "عالج المشكلات الحاجبة قبل الاستخراج.",
         "fr": "Résolvez les problèmes bloquants avant l'extraction."},
    "No material issues detected.":
        {"zh": "未发现重大问题。", "ar": "لم تُكتشف مشكلات جوهرية.", "fr": "Aucun problème important détecté."},
    "Proceed with caution — review the flagged items.":
        {"zh": "请谨慎处理——请查看标记的项目。", "ar": "تابع بحذر — راجع العناصر المُعلَّمة.",
         "fr": "Procédez avec prudence — vérifiez les éléments signalés."},
    "Several issues detected — review before extracting.":
        {"zh": "发现多个问题——请在提取前查看。", "ar": "اكتُشفت عدة مشكلات — راجعها قبل الاستخراج.",
         "fr": "Plusieurs problèmes détectés — vérifiez avant l'extraction."},
    # stat labels / subs / values
    "Pages": {"zh": "页数", "ar": "الصفحات", "fr": "Pages"},
    "Document type": {"zh": "文档类型", "ar": "نوع المستند", "fr": "Type de document"},
    "Scanned pages": {"zh": "扫描页", "ar": "الصفحات الممسوحة", "fr": "Pages numérisées"},
    "Issues": {"zh": "问题", "ar": "المشكلات", "fr": "Problèmes"},
    "detected": {"zh": "已检测", "ar": "مكتشفة", "fr": "détectées"},
    "native vs scanned": {"zh": "原生与扫描", "ar": "أصلي مقابل ممسوح", "fr": "natif vs numérisé"},
    "need OCR": {"zh": "需要 OCR", "ar": "تحتاج OCR", "fr": "nécessitent l'OCR"},
    "found": {"zh": "已发现", "ar": "موجودة", "fr": "trouvés"},
    "not checked": {"zh": "未检查", "ar": "لم تُفحص", "fr": "non vérifié"},
    "Native": {"zh": "原生", "ar": "أصلي", "fr": "Natif"},
    "Scanned": {"zh": "扫描", "ar": "ممسوح", "fr": "Numérisé"},
    "Mixed": {"zh": "混合", "ar": "مختلط", "fr": "Mixte"},
    "Unknown": {"zh": "未知", "ar": "غير معروف", "fr": "Inconnu"},
    # statuses
    "Blocking": {"zh": "阻断", "ar": "حاجب", "fr": "Bloquant"},
    "Advisory": {"zh": "提示", "ar": "إرشادي", "fr": "Indicatif"},
    "Passed": {"zh": "通过", "ar": "ناجح", "fr": "Réussi"},
    # special
    "No issues detected": {"zh": "未发现问题", "ar": "لم تُكتشف مشكلات", "fr": "Aucun problème détecté"},
    "The document passed all integrity checks.":
        {"zh": "该文档通过了所有完整性检查。", "ar": "اجتاز المستند جميع فحوصات السلامة.",
         "fr": "Le document a réussi tous les contrôles d'intégrité."},
    "Integrity not available": {"zh": "无完整性信息", "ar": "السلامة غير متاحة", "fr": "Intégrité indisponible"},
    "This document has no stored pre-flight report.":
        {"zh": "该文档没有已存储的预检报告。", "ar": "لا يوجد تقرير مسبق مخزَّن لهذا المستند.",
         "fr": "Ce document n'a pas de rapport de contrôle enregistré."},
    # review
    "All": {"zh": "全部", "ar": "الكل", "fr": "Tous"},
    "Unmapped": {"zh": "未映射", "ar": "غير مُطابَق", "fr": "Non mappé"},
    "Low confidence": {"zh": "低置信度", "ar": "ثقة منخفضة", "fr": "Faible confiance"},
    "No canonical concept matched with confidence. Pick the correct template line item, "
    "or add an alias so future runs map it automatically.":
        {"zh": "没有可信匹配的规范概念。请选择正确的模板项目，或添加别名以便后续自动映射。",
         "ar": "لم يُطابَق أي مفهوم قياسي بثقة. اختر بند القالب الصحيح أو أضف اسمًا بديلًا ليُطابَق تلقائيًا لاحقًا.",
         "fr": "Aucun concept canonique n'a été associé avec confiance. Choisissez le bon poste du modèle, ou ajoutez un alias."},
    "The mapping is uncertain. Confirm the concept is correct or reassign it; the value and "
    "its source location are shown so you can verify against the document.":
        {"zh": "映射不确定。请确认概念是否正确或重新指定；已显示数值及其来源位置以便与文档核对。",
         "ar": "التطابق غير مؤكد. أكِّد صحة المفهوم أو أعِد تعيينه؛ تظهر القيمة وموقع مصدرها للتحقق مقابل المستند.",
         "fr": "Le mappage est incertain. Confirmez le concept ou réattribuez-le ; la valeur et sa source sont affichées pour vérification."},
}


_TR.update({
    "Unrecognized file format": {"zh": "无法识别的文件格式", "ar": "تنسيق ملف غير معروف", "fr": "Format de fichier non reconnu"},
    "File appears corrupt": {"zh": "文件似乎已损坏", "ar": "يبدو الملف تالفًا", "fr": "Le fichier semble corrompu"},
    "Password-protected document": {"zh": "受密码保护的文档", "ar": "مستند محمي بكلمة مرور", "fr": "Document protégé par mot de passe"},
    "Encrypted document": {"zh": "加密文档", "ar": "مستند مشفَّر", "fr": "Document chiffré"},
    "Mixed scanned and native pages": {"zh": "扫描页与原生页混合", "ar": "صفحات ممسوحة وأصلية مختلطة", "fr": "Pages numérisées et natives mélangées"},
    "Rotated page": {"zh": "页面旋转", "ar": "صفحة مُدارة", "fr": "Page pivotée"},
    "Inconsistent page dimensions": {"zh": "页面尺寸不一致", "ar": "أبعاد صفحات غير متسقة", "fr": "Dimensions de page incohérentes"},
    "Hidden worksheet": {"zh": "隐藏的工作表", "ar": "ورقة عمل مخفية", "fr": "Feuille masquée"},
    "No pages found": {"zh": "未找到页面", "ar": "لا توجد صفحات", "fr": "Aucune page trouvée"},
    "Blank page": {"zh": "空白页", "ar": "صفحة فارغة", "fr": "Page vierge"},
})


def _t(s: str, locale: str) -> str:
    if not s or locale == "en":
        return s
    return _TR.get(s, {}).get(locale, s)


def _tag_for(fmt: str) -> str:
    return {"image": "Scanned", "pdf": "Native", "xlsx": "Native"}.get(fmt, "Native")


def _human_size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, n // 1024)} KB"


def _to_source_doc(row) -> dict:
    """Map a stored Document to the frontend SourceDoc shape used by the Upload list."""
    name = row.filename or "document"
    ext = (name.rsplit(".", 1)[-1] if "." in name else row.fmt or "").upper()[:4]
    return {
        "id": row.id,
        "name": name,
        "ext": ext or "DOC",
        "meta": f"{row.page_count} pages · {_human_size(row.byte_size)}",
        "tag": _tag_for(row.fmt),
    }


@router.get("")
def list_documents(session: Session = Depends(db),
                   principal: Principal = Depends(current_principal)) -> dict:
    """Real uploaded documents, most recent first (Upload screen list). Scoped to the
    caller's own uploads; reviewers/admins see the whole queue."""
    from app.db.models import Document

    q = select(Document).order_by(Document.created_at.desc())
    if principal.role not in _ELEVATED:
        q = q.where((Document.owner == principal.username) | (Document.owner == ""))
    rows = session.execute(q).scalars().all()
    return {"documents": [_to_source_doc(r) for r in rows]}


@router.post("", status_code=201, dependencies=[Depends(require(Permission.DOCUMENTS_MANAGE))])
async def upload_document(
    file: UploadFile = File(...),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
    principal: Principal = Depends(current_principal),
) -> dict:
    from app.db.models import Document

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    digest = content_hash(data)
    # Dedup against the caller's OWN prior upload of the same bytes (reviewers/admins may
    # also reuse an existing accessible copy rather than creating a duplicate).
    existing = session.execute(
        select(Document).where(Document.content_hash == digest)
        .where((Document.owner == principal.username) if principal.role not in _ELEVATED else True)
    ).scalars().first()
    if existing is not None and _can_access(existing, principal):
        return {"id": existing.id, "status": existing.status,
                "content_hash": digest, "duplicate_of": existing.id,
                "page_count": existing.page_count,
                "integrity_report": existing.integrity_report}

    doc_model, _ctx = analyze_document(data, filename=file.filename or "")
    object_key = store.put_bytes(data)

    row = Document(
        owner=principal.username,
        filename=file.filename or "",
        content_hash=digest,
        byte_size=len(data),
        fmt=doc_model.fmt.value,
        object_key=object_key,
        status="integrity_checked",
        locale=doc_model.locale,
        page_count=len(doc_model.pages),
        integrity_report=doc_model.integrity.model_dump(mode="json") if doc_model.integrity else None,
    )
    session.add(row)
    session.commit()

    return {
        "id": row.id,
        "status": row.status,
        "content_hash": digest,
        "duplicate_of": None,
        "format": row.fmt,
        "locale": row.locale,
        "page_count": row.page_count,
        "pages": [p.model_dump(mode="json") for p in doc_model.pages],
        "integrity_report": row.integrity_report,
    }


_CHECK_TITLES = {
    "UNKNOWN_FORMAT": "Unrecognized file format",
    "CORRUPT": "File appears corrupt",
    "PASSWORD_PROTECTED": "Password-protected document",
    "ENCRYPTED": "Encrypted document",
    "MIXED_SCAN": "Mixed scanned and native pages",
    "ROTATED_PAGE": "Rotated page",
    "INCONSISTENT_DIMENSIONS": "Inconsistent page dimensions",
    "HIDDEN_SHEET": "Hidden worksheet",
    "NO_PAGES": "No pages found",
    "BLANK_PAGE": "Blank page",
}
# Map pipeline severities → the frontend's issue severity + score penalty.
_SEV = {
    "blocker": ("low", 35), "error": ("low", 25),
    "warning": ("warn", 8), "info": ("ok", 2),
}


def _pct_label(ratio: float) -> str:
    """Percent label that never reads a contradictory '0%' for a non-zero ratio."""
    pct = round(ratio * 100)
    if ratio > 0 and pct == 0:
        return "<1%"
    return f"{pct}%"


def _serialize_document_integrity(row, locale: str = "en") -> dict:
    """Map a stored IntegrityReport (per uploaded document) into the IntegrityResponse the
    Document Integrity screen renders — so a real uploaded file surfaces its own pre-flight
    results, not the demo project's. Localized to `locale` for the fixed vocabulary."""
    def L(s: str) -> str:
        return _t(s, locale)

    report = row.integrity_report
    # No stored report → the file was never actually checked. Do NOT fabricate an all-clear;
    # surface an explicit "not analyzed" state so an unchecked file is never shown as clean.
    if not report:
        return {
            "score": 0, "grade": L("Not analyzed"),
            "summary": L("No integrity report is available for this document. Re-upload to run the pre-flight checks."),
            "stats": [
                {"label": L("Pages"), "value": str(row.page_count or 0), "sub": L("detected"), "tone": "neutral"},
                {"label": L("Document type"), "value": L("Unknown"), "sub": L("native vs scanned"), "tone": "warn"},
                {"label": L("Scanned pages"), "value": "—", "sub": L("need OCR"), "tone": "neutral"},
                {"label": L("Issues"), "value": "—", "sub": L("not checked"), "tone": "warn"},
            ],
            "issues": [{"title": L("Integrity not available"),
                        "detail": L("This document has no stored pre-flight report."),
                        "pages": "All", "note": "UNKNOWN", "status": L("Not analyzed"), "severity": "warn"}],
        }

    findings = report.get("findings", []) or []
    page_count = report.get("page_count", row.page_count or 0)
    scanned_ratio = float(report.get("scanned_page_ratio", 0.0) or 0.0)

    score = 100
    has_blocker = False
    issues = []
    for f in findings:
        sev = str(f.get("severity", "info"))
        fe_sev, penalty = _SEV.get(sev, ("ok", 2))
        score -= penalty
        # Only BLOCKER gates extraction — matches IntegrityReport.has_blockers and the
        # pipeline's gating semantics (ERROR/WARNING annotate but never halt the run).
        blocking = sev == "blocker"
        has_blocker = has_blocker or blocking
        pidx = f.get("page_index")
        title = _CHECK_TITLES.get(f.get("check_id", ""), str(f.get("check_id", "Issue")).replace("_", " ").title())
        issues.append({
            "title": L(title),
            "detail": f.get("message", ""),
            "pages": f"p.{pidx + 1}" if isinstance(pidx, int) else "All",
            "note": sev.upper(),
            "status": L("Blocking") if blocking else L("Advisory"),
            "severity": fe_sev,
        })
    score = max(0, min(100, score))

    if has_blocker:
        grade, summary = "Blocked", "Resolve the blocking issues before extracting."
    elif score >= 90:
        grade, summary = "Ready to extract", "No material issues detected."
    elif score >= 70:
        grade, summary = "Minor issues", "Proceed with caution — review the flagged items."
    else:
        grade, summary = "Needs attention", "Several issues detected — review before extracting."

    kind = "Native" if scanned_ratio == 0 else "Scanned" if scanned_ratio >= 0.99 else "Mixed"
    stats = [
        {"label": L("Pages"), "value": str(page_count), "sub": L("detected"), "tone": "neutral"},
        {"label": L("Document type"), "value": L(kind), "sub": L("native vs scanned"),
         "tone": "ok" if kind == "Native" else "warn"},
        {"label": L("Scanned pages"), "value": _pct_label(scanned_ratio),
         "sub": L("need OCR"), "tone": "warn" if scanned_ratio > 0 else "ok"},
        {"label": L("Issues"), "value": str(len(findings)), "sub": L("found"),
         "tone": "warn" if findings else "ok"},
    ]
    if not issues:
        issues = [{"title": L("No issues detected"), "detail": L("The document passed all integrity checks."),
                   "pages": "All", "note": "OK", "status": L("Passed"), "severity": "ok"}]
    return {"score": score, "grade": L(grade), "summary": L(summary), "stats": stats, "issues": issues}


@router.get("/{document_id}/integrity", dependencies=[Depends(authorized_document)])
def get_document_integrity(document_id: str, locale: str = Query("en"),
                           session: Session = Depends(db)) -> dict:
    """Real pre-flight integrity for one uploaded document (drives the Document Integrity
    screen when working a real file, rather than the demo project)."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _serialize_document_integrity(row, locale)


def _latest_run(session: Session, document_id: str):
    """Most recent extraction run for a document, or None if it hasn't been extracted."""
    from app.db.models import ExtractionRun

    return session.execute(
        select(ExtractionRun)
        .where(ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.created_at.desc())
    ).scalars().first()


def _prov_label(prov: dict | None) -> str:
    if not prov:
        return "—"
    if prov.get("source_kind") == "spreadsheet" and prov.get("sheet"):
        return f"{prov['sheet']}!{prov.get('cell', '')}"
    return f"p.{(prov.get('page_index', 0) or 0) + 1}"


_LOW_CONF = 0.75  # mapping confidence below this routes to review


def _row_value(rows: list[dict], key: str, basis: str = "consolidated", period: str = "current"):
    for r in rows:
        if r.get("canonical_key") != key:
            continue
        for v in r.get("values") or []:
            if (v.get("basis") or "consolidated") == basis and v.get("period_label") == period:
                try:
                    return float(str(v.get("value")).replace(",", ""))
                except (TypeError, ValueError):
                    return None
    return None


def _accounting_checks(rows: list[dict], reconciliation: list[dict], locale: str) -> list[dict]:
    """Failed accounting validations for the review queue (Req 11): the balance-sheet
    identity and note→face ties. Computed from the real extracted values."""
    def L(s: str) -> str:
        return _t(s, locale)

    checks: list[dict] = []
    a = _row_value(rows, "bs_total_assets")
    e = _row_value(rows, "bs_total_equity_and_liabilities")
    if a is not None and e is not None and abs(a - e) > 1:
        checks.append({
            "id": "chk-balance", "type": "balance", "icon": "≠",
            "title": L("Balance sheet does not balance"), "where": L("Balance sheet identity"),
            "severity": L("Check failed"), "tone": "high", "delta": f"{a - e:,.0f}",
            "target": "bs_total_assets",
            "calc": [
                [L("Total assets"), f"{a:,.0f}", False],
                [L("Total equity and liabilities"), f"{e:,.0f}", True],
                [L("Difference"), f"{a - e:,.0f}", False],
            ],
            "fix": L("Assets do not equal equity plus liabilities. Check the extracted totals "
                     "and their components against the document."),
        })
    for ent in reconciliation:
        if ent.get("within_tolerance"):
            continue
        note = ent.get("note_number")
        checks.append({
            "id": f"chk-note-{note}-{ent.get('basis')}-{ent.get('period_label')}",
            "type": "note_tie", "icon": "≠",
            "title": L("Note does not tie to the face figure"),
            "where": f"Note {note} · {ent.get('basis')}/{ent.get('period_label')}",
            "severity": L("Check failed"), "tone": "high",
            "delta": f"{float(ent.get('residual') or 0):,.0f}", "target": f"note:{note}",
            "calc": [
                [L("Face figure"), f"{float(ent.get('raw_face') or 0):,.0f}", False],
                [L("Residual vs note total"), f"{float(ent.get('residual') or 0):,.0f}", True],
            ],
            "fix": L("The note's detail rows do not sum to the face figure it supports. "
                     "Verify the note breakdown and the face value."),
        })
    return checks


def _build_review(rows: list[dict], filename: str, locale: str = "en",
                  reconciliation: list[dict] | None = None) -> dict:
    """Derive the human-in-the-loop review queue from a real extraction: failed accounting
    checks (balance identity, note ties) plus unmapped and low-confidence line items become
    review items (the QA the analyst works before export). No demo data involved."""
    def L(s: str) -> str:
        return _t(s, locale)

    _UNMAPPED_FIX = ("No canonical concept matched with confidence. Pick the correct template "
                     "line item, or add an alias so future runs map it automatically.")
    _LOWCONF_FIX = ("The mapping is uncertain. Confirm the concept is correct or reassign it; "
                    "the value and its source location are shown so you can verify against the document.")
    accounting = _accounting_checks(rows, reconciliation or [], locale)
    checks: list[dict] = list(accounting)
    unmapped = low_conf = 0
    for i, r in enumerate(rows):
        key = r.get("canonical_key")
        conf = r.get("mapping_confidence")
        flags = r.get("flags") or []
        first = (r.get("values") or [{}])[0]
        val = first.get("value")
        where = f"{filename} · {_prov_label(first.get('provenance'))}"
        pct = f"{round(conf * 100)}%" if isinstance(conf, (int, float)) else "—"

        if not key:
            unmapped += 1
            checks.append({
                "id": f"chk-unmapped-{i}", "type": "unmapped", "icon": "?",
                "title": r.get("source_label", "Line item"), "where": where,
                "severity": L("Unmapped"), "tone": "low", "delta": "—",
                "target": r.get("source_label", ""),
                "calc": [
                    ["Source label", r.get("source_label", ""), False],
                    ["Mapped to", "— (no confident match)", True],
                    ["Value", str(val) if val is not None else "—", False],
                ],
                "fix": L(_UNMAPPED_FIX),
            })
        elif "low_mapping_confidence" in flags or (isinstance(conf, (int, float)) and conf < _LOW_CONF):
            low_conf += 1
            checks.append({
                "id": f"chk-lowconf-{i}", "type": "low_confidence", "icon": "!",
                "title": r.get("source_label", "Line item"), "where": where,
                "severity": L("Low confidence"), "tone": "med", "delta": pct,
                "target": r.get("source_label", ""),
                "calc": [
                    ["Source label", r.get("source_label", ""), False],
                    ["Mapped to", key, True],
                    ["Method", r.get("mapping_method") or "—", False],
                    ["Confidence", pct, False],
                    ["Value", str(val) if val is not None else "—", False],
                ],
                "fix": L(_LOWCONF_FIX),
            })
    total = len(checks)
    passed = max(0, len(rows) - (unmapped + low_conf))
    return {
        "checks": checks,
        "tabs": [
            {"label": L("All"), "count": total},
            {"label": L("Checks"), "count": len(accounting)},
            {"label": L("Unmapped"), "count": unmapped},
            {"label": L("Low confidence"), "count": low_conf},
        ],
        "summary": {"open": total, "passed": passed},
    }


@router.get("/{document_id}/run", dependencies=[Depends(authorized_document)])
def get_document_run(document_id: str, session: Session = Depends(db)) -> dict:
    """The latest extraction result for a document (drives the Export preview/counts for a
    real run). 404 until the document has been extracted."""
    from app.db.models import Document

    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    return {"run_id": run.id, "status": run.status, "result": run.result}


@router.get("/{document_id}/analysis", dependencies=[Depends(authorized_document)])
def get_document_analysis(document_id: str, locale: str = Query("en"),
                          session: Session = Depends(db)) -> dict:
    """Derived analysis for a document, from its latest extraction: computed ratios and
    plain-language notes (recomputed from the current values so edits show) plus the stored
    disclosure scan. Empty (but valid) until the document has been extracted."""
    from app.services.derived import build_free_notes, compute_ratios

    run = _latest_run(session, document_id)
    if run is None or not run.result:
        return {"ratios": [], "disclosures": [], "notes": []}
    rows = run.result.get("rows", [])
    return {
        "ratios": compute_ratios(rows, locale=locale),
        "disclosures": run.result.get("disclosures", []),
        "notes": build_free_notes(rows, locale=locale),
    }


@router.get("/{document_id}/review", dependencies=[Depends(authorized_document)])
def get_document_review(document_id: str, locale: str = Query("en"),
                        session: Session = Depends(db)) -> dict:
    """Real review queue for a document, derived from its latest extraction."""
    from app.db.models import Document

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        return {"checks": [], "tabs": [{"label": _t("All", locale), "count": 0}],
                "summary": {"open": 0, "passed": 0}}
    return _build_review(run.result.get("rows", []), doc.filename or "document", locale,
                         run.result.get("reconciliation", []))


class LineItemEdit(BaseModel):
    value: float | None = None
    formula: str = ""
    period: str = "current"


@router.patch("/{document_id}/line-items/{canonical_key:path}",
              dependencies=[Depends(require(Permission.EXTRACTION_EDIT)), Depends(authorized_document)])
def edit_document_line_item(document_id: str, canonical_key: str, body: LineItemEdit,
                            session: Session = Depends(db)) -> dict:
    """Edit a value (and optional formula) on a real extraction. The override is persisted
    onto the latest run so the statement, export and review all reflect it; the row is
    flagged 'edited' while its original provenance is retained."""
    from app.db.models import Document

    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    result = dict(run.result)
    rows = result.get("rows", [])
    target = next((r for r in rows if r.get("canonical_key") == canonical_key), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Line item not found in this run")

    values = target.get("values") or []
    # Snapshot the machine-extracted values ONCE, before the first edit, so a revert can
    # restore the original numbers exactly (edits are overlays, never a lossy overwrite).
    if not target.get("edited"):
        target["_original"] = {v.get("period_label"): v.get("value") for v in values}

    slot = next((v for v in values if v.get("period_label") == body.period), None)
    if slot is None:
        slot = {"period_label": body.period, "value": None, "provenance": None}
        values.append(slot)
        target["values"] = values
    if body.value is None:
        slot["value"] = None
    else:
        fv = float(body.value)
        slot["value"] = str(int(fv)) if fv == int(fv) else str(fv)
    target["formula"] = body.formula or None
    target["edited"] = True

    result["rows"] = rows
    run.result = result
    flag_modified(run, "result")
    session.commit()
    return {"ok": True, "canonical_key": canonical_key, "period": body.period,
            "value": slot["value"], "formula": target.get("formula"), "status": "edited"}


@router.delete("/{document_id}/line-items/{canonical_key:path}",
               dependencies=[Depends(require(Permission.EXTRACTION_EDIT)), Depends(authorized_document)])
def revert_document_line_item(document_id: str, canonical_key: str,
                              session: Session = Depends(db)) -> dict:
    """Revert an edited line item to its original machine-extracted values, dropping the
    manual value(s) and formula."""
    from app.db.models import Document

    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    result = dict(run.result)
    rows = result.get("rows", [])
    target = next((r for r in rows if r.get("canonical_key") == canonical_key), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Line item not found in this run")
    if not target.get("edited"):
        return {"ok": True, "canonical_key": canonical_key, "reverted": False, "status": None}

    original = target.get("_original") or {}
    for v in target.get("values") or []:
        if v.get("period_label") in original:
            v["value"] = original[v["period_label"]]
    target.pop("_original", None)
    target.pop("formula", None)
    target["edited"] = False

    result["rows"] = rows
    run.result = result
    flag_modified(run, "result")
    session.commit()
    return {"ok": True, "canonical_key": canonical_key, "reverted": True, "status": None}


@router.get("/{document_id}/export",
            dependencies=[Depends(require(Permission.EXPORT_RUN)), Depends(authorized_document)])
def export_document(
    document_id: str,
    fmt: str = Query("excel", pattern="^(excel|json)$"),
    layout: str = Query("statement", pattern="^(statement|flat)$"),
    locale: str = Query("en"),
    session: Session = Depends(db),
) -> Response:
    """Export a real document's extracted, mapped line items as Excel or JSON, built from
    the latest run (not the demo project).

    Excel supports two layouts: ``statement`` (default) mirrors the run's template —
    sections, subtotals, totals, ordering, localized labels, consolidated + standalone
    side by side; ``flat`` is one row per line item. JSON is always the structured-flat
    shape for downstream systems."""
    from app.db.models import Document
    from app.services.export import build_rows_json, build_rows_xlsx, build_statement_workbook

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    rows = run.result.get("rows", [])
    name = (doc.filename or "extract").rsplit(".", 1)[0]
    if fmt == "json":
        data = build_rows_json(rows, filename=doc.filename or "document")
        return Response(content=data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})

    template_def = _template_for_run(session, run)
    if layout == "statement" and template_def:
        data = build_statement_workbook(rows, template_def, locale=locale,
                                        filename=doc.filename or "document",
                                        disclosures=run.result.get("disclosures", []),
                                        note_details=run.result.get("note_details", []),
                                        reconciliation=run.result.get("reconciliation", []))
    else:
        data = build_rows_xlsx(rows, filename=doc.filename or "document")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )


_PAGE_CLS = {"face": "Statement face", "notes": "Notes", "other": "Other",
             "cover": "Cover", "toc": "Contents", "unknown": "Unclassified"}


def _conf_cat(c) -> tuple[str, int]:
    if not isinstance(c, (int, float)):
        return "med", 60
    pct = round(c * 100)
    return ("high" if c >= 0.85 else "med" if c >= 0.7 else "low"), pct


def _build_pages(pages: list[dict]) -> dict:
    """PagesResponse from the document's real classified pages — face/notes are included in
    the extraction scope, everything else is skipped."""
    cards = []
    counts = {"face": 0, "notes": 0, "other": 0}
    for p in pages:
        kind = p.get("kind", "unknown")
        included = kind in ("face", "notes")
        cat, _ = _conf_cat(p.get("classification_confidence"))
        cards.append({
            "no": (p.get("index", 0) or 0) + 1,
            "cls": _PAGE_CLS.get(kind, kind.title()),
            "sub": "in scope" if included else "skipped",
            "conf": cat,
            "included": included,
            "scan": "scanned" if p.get("source_kind") == "scanned" else "native",
        })
        counts[kind if kind in counts else "other"] = counts.get(kind if kind in counts else "other", 0) + 1
    total = len(cards)
    focused = counts["face"] + counts["notes"]
    return {
        "pages": cards,
        "filters": [
            {"label": "All pages", "count": total},
            {"label": "Face", "count": counts["face"]},
            {"label": "Notes", "count": counts["notes"]},
            {"label": "Other", "count": counts["other"]},
        ],
        "focused": focused, "total": total, "skipped": total - focused,
    }


@router.get("/{document_id}/pages", dependencies=[Depends(authorized_document)])
def get_document_pages(
    document_id: str,
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> dict:
    """Real per-page classification for the Page Scope screen — recomputed from the stored
    file so it's available even before extraction (the confirm-scope step)."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_model, _ctx = analyze_document(store.get(row.object_key), filename=row.filename or "")
    return _build_pages([p.model_dump(mode="json") for p in doc_model.pages])


_STMT_PREFIX = {"balance_sheet": "bs", "profit_and_loss": "pl", "cash_flow": "cf"}
_STMT_LABEL = {"balance_sheet": "Balance sheet", "profit_and_loss": "Profit & loss",
               "cash_flow": "Cash flow"}


def _to_num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _basis_values(r: dict, basis: str) -> list[dict]:
    """Values for the requested basis; values with no basis are treated as consolidated."""
    return [v for v in (r.get("values") or []) if (v.get("basis") or "consolidated") == basis]


def _cur_prior(r: dict, basis: str = "consolidated") -> tuple[dict | None, dict | None]:
    vals = _basis_values(r, basis)
    by = {v.get("period_label"): v for v in vals}
    cur = by.get("current") or (vals[0] if vals else None)
    prior = by.get("prior") or (vals[1] if len(vals) > 1 else None)
    return cur, prior


def _inspector(r: dict, cur: dict | None) -> dict:
    prov = (cur or {}).get("provenance")
    return {"tag": "machine", "src": _prov_label(prov) if prov else "",
            "formula": "", "result": str((cur or {}).get("value") or ""),
            "note": f"Mapped by {r.get('mapping_method') or 'ensemble'}"}


def _template_for_run(session: Session, run) -> dict | None:
    """The template the run used, else the seeded HK reference template."""
    from app.db.models import TemplateVersion

    tid = (run.options or {}).get("template_version_id")
    if tid:
        tv = session.get(TemplateVersion, tid)
        if tv:
            return tv.definition
    tv = session.execute(
        select(TemplateVersion).order_by(TemplateVersion.version.desc())
    ).scalars().first()
    return tv.definition if tv else None


def _build_statement(rows: list[dict], template_def: dict | None, statement_type: str,
                     filename: str, basis: str = "consolidated") -> dict:
    """Group the real extracted rows into one statement (by the template's sections), so the
    Workspace grid renders real data with its provenance-backed values. Only rows that
    carry a value for the requested `basis` (consolidated / standalone) are shown."""
    prefix = _STMT_PREFIX.get(statement_type, "")
    by_key: dict[str, dict] = {}
    for r in rows:
        k = r.get("canonical_key")
        if k:
            by_key.setdefault(k, r)

    def has_basis(r: dict) -> bool:
        return bool(_basis_values(r, basis))

    def item_row(key: str, label: str, r: dict) -> dict:
        cur, prior = _cur_prior(r, basis)
        cat, pct = _conf_cat(r.get("mapping_confidence"))
        edited = bool(r.get("edited"))
        return {
            "id": key, "label": label or r.get("source_label"),
            "source_label": r.get("source_label"), "kind": "item",
            "note": r.get("note"), "note2": None, "status": "edited" if edited else None,
            "confidence": {"cat": cat, "pct": pct}, "editable": True,
            "formula": r.get("formula"), "inspector": _inspector(r, cur),
            "v1": _to_num((cur or {}).get("value")), "v2": _to_num((prior or {}).get("value")),
        }

    out: list[dict] = []
    seen: set[str] = set()
    stmt = next((s for s in (template_def or {}).get("statements", [])
                 if s.get("type") == statement_type), None)
    if stmt:
        for sec in stmt.get("sections", []):
            matched = [c for c in sec.get("children", [])
                       if c.get("canonical_key") in by_key and has_basis(by_key[c["canonical_key"]])]
            if not matched:
                continue
            out.append({"id": f"sec_{sec.get('node_id', '')}", "label": sec.get("label", ""),
                        "kind": "section", "v1": None, "v2": None})
            for c in matched:
                k = c["canonical_key"]
                seen.add(k)
                out.append(item_row(k, c.get("label", ""), by_key[k]))

    extra = [r for r in rows
             if (r.get("canonical_key") or "").startswith(f"{prefix}_")
             and r["canonical_key"] not in seen and has_basis(r)]
    if extra:
        out.append({"id": "sec_other", "label": "Other extracted items", "kind": "section",
                    "v1": None, "v2": None})
        for r in extra:
            out.append(item_row(r["canonical_key"], r.get("source_label", ""), r))

    return {
        "statement": statement_type, "label": _STMT_LABEL.get(statement_type, statement_type),
        "basis": "consolidated", "periods": ["Current", "Prior"],
        "currency": "", "currency_symbol": "", "units": "",
        "rows": out,
        "viewer": {
            "company": filename, "subtitle": "Extracted statement",
            "chips": [{"label": "Consolidated", "active": True}],
            "callout": "Values are read deterministically from the source; mapping is by the "
                       "ensemble. Open the extraction view for click-to-source provenance.",
        },
    }


@router.get("/{document_id}/statement", dependencies=[Depends(authorized_document)])
def get_document_statement(
    document_id: str,
    statement: str = Query("balance_sheet"),
    basis: str = Query("consolidated"),
    session: Session = Depends(db),
) -> dict:
    """One statement of a document's real extraction, grouped for the Workspace grid."""
    from app.db.models import Document

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    template_def = _template_for_run(session, run)
    # Consolidated and standalone are extracted in one pass; the grid shows the requested
    # basis (empty if the source didn't present that basis).
    return _build_statement(run.result.get("rows", []), template_def, statement,
                            doc.filename or "document", basis)


def _note_no(raw) -> int | None:
    """Parse a note reference to an int; the notes index/detail key on numbers."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _rows_by_note(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for r in rows:
        n = _note_no(r.get("note"))
        if n is not None:
            grouped.setdefault(n, []).append(r)
    return grouped


def _note_index(details: list[dict]) -> dict[int, dict]:
    return {n: d for d in details if (n := _note_no(d.get("no"))) is not None}


def _fmt_amt(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _reconciliation_text(entries: list[dict], note_no: int) -> str | None:
    """A human-readable note→face reconciliation summary for one note, from the reconcile
    stage's entries. Prefers the consolidated / current-period entry."""
    mine = [e for e in entries if _note_no(e.get("note_number")) == note_no]
    if not mine:
        return None
    mine.sort(key=lambda e: (e.get("basis") != "consolidated", e.get("period_label") != "current"))
    e = mine[0]
    raw, sub, rec = e.get("raw_face"), e.get("subtracted"), e.get("reconciled")
    resid, tie = e.get("residual"), e.get("within_tolerance")
    parts: list[str] = []
    try:
        if abs(float(sub)) > 0:
            parts.append(
                f"Face figure {_fmt_amt(raw)} less {_fmt_amt(sub)} of note detail already "
                f"carried as separate line items → reconciled {_fmt_amt(rec)}.")
    except (TypeError, ValueError):
        pass
    if tie:
        parts.append(f"The note total ties to the face figure (residual {_fmt_amt(resid)}).")
    else:
        parts.append(f"The note total does not tie to the face figure — residual {_fmt_amt(resid)} "
                     f"(flagged for review).")
    return " ".join(parts)


@router.get("/{document_id}/notes", dependencies=[Depends(authorized_document)])
def get_document_notes(document_id: str, session: Session = Depends(db)) -> dict:
    """All-notes index for a real document. Prefers the EXTRACTED note detail tables (the
    breakdowns parsed from the notes pages); falls back to the notes referenced by face
    line items when no detail tables were parsed."""
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        return {"notes": [], "count": 0, "linked": 0}

    details = _note_index(run.result.get("note_details", []))
    if details:
        notes = [{"no": n, "title": details[n].get("title") or f"Note {n}", "conf": "high"}
                 for n in sorted(details)]
        linked = sum(len(details[n].get("rows", [])) for n in details)
        return {"notes": notes, "count": len(notes), "linked": linked}

    grouped = _rows_by_note(run.result.get("rows", []))
    notes = [{"no": n, "title": f"Note {n}", "conf": "med"} for n in sorted(grouped)]
    return {"notes": notes, "count": len(notes), "linked": sum(len(v) for v in grouped.values())}


@router.get("/{document_id}/notes/{note_no}", dependencies=[Depends(authorized_document)])
def get_document_note(document_id: str, note_no: int, session: Session = Depends(db)) -> dict:
    """One note's detail for a real document: its EXTRACTED breakdown rows (label + period
    values) with the page they came from, plus the face line that cites it. Falls back to
    the face line items referencing the note when no detail table was parsed."""
    run = _latest_run(session, document_id)
    result = run.result if run and run.result else {}
    details = _note_index(result.get("note_details", []))
    faces = _rows_by_note(result.get("rows", []))
    linked_face = faces.get(note_no, [])
    linked_label = linked_face[0].get("source_label") if linked_face else ""
    linked_key = linked_face[0].get("canonical_key") if linked_face else ""

    if note_no in details:
        d = details[note_no]
        detail_rows = []
        for row in d.get("rows", []):
            vals = row.get("values") or []
            by = {v.get("period_label"): v for v in vals}
            cur = by.get("current") or (vals[0] if vals else {})
            prior = by.get("prior") or (vals[1] if len(vals) > 1 else {})
            detail_rows.append({
                "label": row.get("label", ""),
                "v1": _to_num(cur.get("value")) or 0,
                "v2": _to_num(prior.get("value")) or 0,
            })
        return {
            "no": note_no, "title": d.get("title") or f"Note {note_no}", "page": d.get("page", 0),
            "linked_line": linked_key, "linked_label": linked_label,
            "rows": detail_rows,
            "reconciliation": _reconciliation_text(result.get("reconciliation", []), note_no),
        }

    # Fallback: the face items that reference the note.
    first = linked_face[0] if linked_face else None
    prov = (_cur_prior(first)[0] or {}).get("provenance") if first else None
    detail_rows = []
    for r in linked_face:
        cur, prior = _cur_prior(r)
        detail_rows.append({"label": r.get("source_label", ""),
                            "v1": _to_num((cur or {}).get("value")) or 0,
                            "v2": _to_num((prior or {}).get("value")) or 0})
    return {
        "no": note_no, "title": f"Note {note_no}",
        "page": (prov.get("page_index", 0) + 1) if prov else 0,
        "linked_line": linked_key, "linked_label": linked_label,
        "rows": detail_rows, "reconciliation": None,
    }


@router.get("/{document_id}", dependencies=[Depends(authorized_document)])
def get_document(document_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": row.id,
        "filename": row.filename,
        "status": row.status,
        "format": row.fmt,
        "locale": row.locale,
        "page_count": row.page_count,
        "integrity_report": row.integrity_report,
    }


@router.get("/{document_id}/pages/{page_index}/image", dependencies=[Depends(authorized_document)])
def get_page_image(
    document_id: str,
    page_index: int,
    dpi: int = Query(110, ge=50, le=300),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> Response:
    """Rasterize one PDF page to PNG — the backdrop the frontend draws the value's
    normalized bbox over (click-to-source). PDF only; spreadsheets have no page image."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.fmt != "pdf":
        raise HTTPException(status_code=400, detail="Page images are only available for PDFs")
    try:
        import fitz
    except ImportError:  # pragma: no cover - PyMuPDF is a core dep
        raise HTTPException(status_code=501, detail="PDF rendering unavailable")
    data = store.get(row.object_key)
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
        if page_index < 0 or page_index >= pdf.page_count:
            raise HTTPException(status_code=404, detail="Page out of range")
        png = pdf[page_index].get_pixmap(dpi=dpi).tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not render page: {exc}")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.get("/{document_id}/cell-context", dependencies=[Depends(authorized_document)])
def get_cell_context(
    document_id: str,
    sheet: str = Query(..., description="Sheet name the value came from"),
    cell: str = Query(..., description="Cell reference, e.g. C14"),
    radius: int = Query(4, ge=1, le=12),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> dict:
    """A window of cells around a value's origin — the spreadsheet click-to-source
    backdrop (mirrors the PDF page image for XLSX sources)."""
    from app.db.models import Document
    from app.services.excel_extract import cell_context

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.fmt != "xlsx":
        raise HTTPException(status_code=400, detail="Cell context is only available for spreadsheets")
    data = store.get(row.object_key)
    try:
        return cell_context(data, sheet=sheet, cell=cell, radius=radius)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Sheet not found: {sheet}")
