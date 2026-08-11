"""Document endpoints: upload (+ upfront integrity/classification) and fetch."""
from __future__ import annotations

import copy
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import db, object_store
from app.ports.object_store import LocalObjectStore
from app.security import Permission, Principal, Role, current_principal, require
from app.services.documents import analyze_document, content_hash
from app.services.periods import (
    basis_values as _basis_values_of, concept_value as _concept_value, edited_for as _edited_for,
    period_displays, slot_for, split_current_prior)
from app.services.reconcile import tie_status

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
    # KPI / Additional-items views
    "KPIs": {"zh": "关键指标", "ar": "المؤشرات الرئيسية", "fr": "Indicateurs clés"},
    "Computed KPIs": {"zh": "计算得出的关键指标", "ar": "مؤشرات محسوبة",
                      "fr": "Indicateurs calculés"},
    "Additional items": {"zh": "其他项目", "ar": "بنود إضافية", "fr": "Postes supplémentaires"},
    "Extracted, not on a statement": {"zh": "已提取，但不在报表中",
                                      "ar": "مستخرج، وليس في أي قائمة",
                                      "fr": "Extrait, hors états financiers"},
    "computed": {"zh": "计算值", "ar": "محسوب", "fr": "calculé"},
    "unmapped": {"zh": "未映射", "ar": "غير مُعيَّن", "fr": "non mappé"},
    "inputs not extracted": {"zh": "输入项未提取", "ar": "المدخلات غير مستخرجة",
                             "fr": "entrées non extraites"},
    "numerator": {"zh": "分子", "ar": "البسط", "fr": "numérateur"},
    "denominator": {"zh": "分母", "ar": "المقام", "fr": "dénominateur"},
    "Not mapped to any concept": {"zh": "未映射到任何概念", "ar": "غير مُعيَّن إلى أي مفهوم",
                                  "fr": "Non rattaché à un concept"},
    "Mapped, but not on any statement in this template":
        {"zh": "已映射，但不在此模板的任何报表中",
         "ar": "مُعيَّن، لكنه ليس في أي قائمة في هذا القالب",
         "fr": "Rattaché, mais absent des états de ce modèle"},
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


# structural validation (template rollups / identities)
_TR.update({
    "Figure does not equal its template components":
        {"zh": "数字与模板组成部分不符", "ar": "الرقم لا يساوي مكوناته في القالب",
         "fr": "Le montant ne correspond pas à ses composantes du modèle"},
    "Reported": {"zh": "已报告", "ar": "المُبلَّغ", "fr": "Déclaré"},
    "Sum of template components": {"zh": "模板组成部分合计", "ar": "مجموع مكونات القالب",
                                   "fr": "Somme des composantes du modèle"},
    "The reported figure does not equal the components the template says it is made of, so a "
    "value is on the wrong line. Check the components and the total against the document.":
        {"zh": "报告的数字与模板所述的组成部分不相等，说明某个数值被放在了错误的行。请将各组成部分及合计与文档核对。",
         "ar": "الرقم المُبلَّغ لا يساوي المكونات التي يحددها القالب، أي أن قيمة وُضعت في السطر الخطأ. راجع المكونات والمجموع مقابل المستند.",
         "fr": "Le montant déclaré ne correspond pas aux composantes définies par le modèle : une valeur est sur la mauvaise ligne. Vérifiez les composantes et le total dans le document."},
    "Flipping the sign of": {"zh": "改变符号的项目：", "ar": "قلب إشارة", "fr": "Inverser le signe de"},
    "would make it balance.": {"zh": "即可使其平衡。", "ar": "سيجعلها متوازنة.",
                               "fr": "permettrait d'équilibrer."},
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

    pages_json = [p.model_dump(mode="json") for p in doc_model.pages]
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
        # Persist the classified pages so Page Scope / scope editing reuse them (no recompute).
        pages=pages_json,
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


@router.delete("/{document_id}", status_code=204,
               dependencies=[Depends(require(Permission.DOCUMENTS_MANAGE))])
def delete_document(
    doc=Depends(authorized_document),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> Response:
    """Delete a document the caller owns (admins may delete any), along with its extraction
    runs. The stored blob is content-addressed and de-duplicated, so it's only removed when
    no other document still references it."""
    from app.db.models import Document, ExtractionRun

    object_key = doc.object_key
    session.execute(sql_delete(ExtractionRun).where(ExtractionRun.document_id == doc.id))
    session.delete(doc)
    session.commit()

    shared = session.execute(
        select(Document.id).where(Document.object_key == object_key).limit(1)
    ).first()
    if not shared:
        store.delete(object_key)
    return Response(status_code=204)


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


def _low_conf_threshold() -> float:
    """Mapping confidence below which a line routes to review — the same threshold the mapper
    uses to auto-accept, so the two never disagree."""
    from app.config import get_settings

    return get_settings().extraction.auto_accept_confidence


def _row_value(rows: list[dict], key: str, basis: str = "consolidated", period: str = "current"):
    """One concept's figure — exactly the figure the statement grid shows for it.

    Read through ``concept_value`` so the accounting checks validate the number on screen: the
    sum when several printed lines map to the concept, or the analyst's manual value when one
    was entered. Checking a different number than the grid displays is worse than not checking.
    """
    return _concept_value([r for r in rows if r.get("canonical_key") == key], basis, period)


def _balance_sides(rows: list[dict], basis: str, period: str) -> tuple[float | None, float | None,
                                                                     bool]:
    """The two sides of the accounting identity, derived from subtotals when the filing does
    not print the totals themselves.

    Plenty of statements — HK/PRC ones especially — never print a "Total assets" line: they run
    non-current assets, current assets, then "Total assets less current liabilities". Requiring
    the printed total meant the identity check silently never ran on exactly those filings.
    Both sides are reconstructed from the section subtotals instead, which the template already
    defines, so the identity is genuinely checked. Returns (assets, equity+liabilities,
    whether either side was derived).
    """
    def v(key: str):
        return _row_value(rows, key, basis, period)

    assets, derived = v("bs_total_assets"), False
    if assets is None:
        nca, ca = v("bs_non_current_assets__total_non_current_assets"), \
            v("bs_current_assets__total_current_assets")
        if nca is not None and ca is not None:
            assets, derived = nca + ca, True

    eqliab = v("bs_total_equity_and_liabilities")
    if eqliab is None:
        eq = v("bs_equity__total_equity")
        ncl = v("bs_non_current_liabilities__total_non_current_liabilities")
        cl = v("bs_current_liabilities__total_current_liabilities")
        if eq is not None and ncl is not None and cl is not None:
            eqliab, derived = eq + ncl + cl, True
    return assets, eqliab, derived


def _structural_checks(structural: list[dict], locale: str, covered: set[str]) -> list[dict]:
    """Failed template-structure relations as review items (from the structural stage).

    Only ``fail`` rows become checks: a ``skipped`` row means the relation could not be
    evaluated because a participant was never extracted, which is a coverage fact, not a
    defect. Relations whose total already has its own check (the balance identity) are left to
    it so the analyst doesn't see the same difference twice.
    """
    def L(s: str) -> str:
        return _t(s, locale)

    out: list[dict] = []
    for res in structural:
        d = res.get("details") or {}
        if res.get("status") != "fail" or d.get("target") in covered:
            continue
        expected, actual = float(res.get("expected") or 0), float(res.get("actual") or 0)
        suspect = d.get("sign_suspect")
        calc = [[L("Reported"), f"{actual:,.0f}", False],
                [L("Sum of template components"), f"{expected:,.0f}", True],
                [L("Difference"), f"{actual - expected:,.0f}", False]]
        calc += [[k, f"{float(v):,.0f}", False]
                 for k, v in (d.get("component_values") or {}).items()]
        fix = L("The reported figure does not equal the components the template says it is made "
                "of, so a value is on the wrong line. Check the components and the total "
                "against the document.")
        if suspect:
            fix = f"{fix} {L('Flipping the sign of')} {suspect} {L('would make it balance.')}"
        out.append({
            "id": f"chk-structural-{res.get('rule_id')}-{res.get('scope_key')}",
            "type": "structural", "icon": "≠",
            "title": L("Figure does not equal its template components"),
            "where": f"{d.get('target')} · {res.get('scope_key')}",
            "severity": L("Check failed"), "tone": "high",
            "delta": f"{actual - expected:,.0f}", "target": d.get("target") or "",
            "calc": calc, "fix": fix,
        })
    return out


def _accounting_checks(rows: list[dict], reconciliation: list[dict], locale: str,
                       structural: list[dict] | None = None,
                       template_def: dict | None = None) -> list[dict]:
    """Failed accounting validations for the review queue (Req 11): the balance-sheet
    identity, note→face ties, the template's structural relations, and — since the face now
    carries the COMPUTED figure for every calculated line — what the document printed instead.
    Computed from the real extracted values."""
    def L(s: str) -> str:
        return _t(s, locale)

    checks: list[dict] = []
    a, e, derived = _balance_sides(rows, "consolidated", "current")
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
            ] + ([[L("Totals derived from the section subtotals"), "", False]] if derived else []),
            "fix": L("Assets do not equal equity plus liabilities. Check the extracted totals "
                     "and their components against the document."),
        })
    # The statement of changes in equity must END where the balance sheet says equity stands.
    # It is the one relation that crosses two statements, and it is worth checking precisely
    # because the two are extracted by completely different paths — a matrix reader and a
    # two-column reader — so agreement is real evidence rather than a restatement.
    eq_close, bs_equity = _equity_closing(rows, "consolidated"), _row_value(
        rows, "bs_equity__total_equity")
    if eq_close is not None and bs_equity is not None and abs(eq_close[1] - bs_equity) > 1:
        checks.append({
            "id": "chk-equity-closing", "type": "equity_tie", "icon": "≠",
            "title": L("Equity statement does not close at the balance sheet's equity"),
            "where": L("Statement of changes in equity"),
            "severity": L("Check failed"), "tone": "high",
            "delta": f"{eq_close[1] - bs_equity:,.0f}", "target": "bs_equity__total_equity",
            "calc": [
                [eq_close[0], f"{eq_close[1]:,.0f}", False],
                [L("Total equity per the balance sheet"), f"{bs_equity:,.0f}", True],
                [L("Difference"), f"{eq_close[1] - bs_equity:,.0f}", False],
            ],
            "fix": L("The closing balance of the equity statement should equal total equity on "
                     "the balance sheet. Check both figures against the document."),
        })
    # Only a note that IS a breakdown of the face figure, yet does not tie, is a finding. An
    # "unconfirmed" entry means the cited note is an analysis/segment/commitments table rather
    # than a decomposition — raising those turned the queue into hundreds of non-findings.
    # One item per (note, basis, period): a note spanning several tables asks one question.
    seen_ties: set[tuple] = set()
    for ent in reconciliation:
        if tie_status(ent) != "untied":
            continue
        note = ent.get("note_number")
        ident = (note, ent.get("basis"), ent.get("period_label"))
        if ident in seen_ties:
            continue
        seen_ties.add(ident)
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
    checks += _structural_checks(structural or [], locale,
                                 covered={c["target"] for c in checks})
    checks += _calculated_checks(rows, template_def, locale,
                                 covered={c["target"] for c in checks})
    return checks


def _calculated_checks(rows: list[dict], template_def: dict | None, locale: str,
                       covered: set[str]) -> list[dict]:
    """Review items for the template's CALCULATED lines — the face now shows the computed figure,
    so the printed one has to be accounted for somewhere.

    Two findings, and the distinction is what an analyst does next:

    * the document printed a subtotal that its own components do not come to. Either a component
      is mis-mapped or missing, or the filing's own arithmetic is being read wrongly. Either way
      the face is showing the computed figure, and this says what was printed instead.
    * a calculated line had NO extracted components at all, so there was nothing to compute from
      and the printed figure is on the face unverified.

    Relations that already have their own check (the balance identity) are left to it, so the same
    difference is never raised twice.
    """
    def L(s: str) -> str:
        return _t(s, locale)

    from app.services.rollups import node_labels

    if not template_def:
        return []
    names = node_labels(template_def, locale)
    out: list[dict] = []
    for basis in ("consolidated", "standalone"):
        calc = _calculated(rows, template_def, basis, "current", locale)
        if not any(c.components for c in calc.values()):
            continue
        groups: dict[str, list[dict]] = {}
        for r in rows:
            k = r.get("canonical_key")
            if k:
                groups.setdefault(k, []).append(r)
        # Only report on a basis the document actually presented.
        if not any(_basis_values(r, basis) for r in rows):
            continue
        for key, c in calc.items():
            if key in covered or c.cycle:
                continue
            reported = _concept_value(groups.get(key, []), basis, "current")
            label = names.get(key, key)
            where = f"{label} · {basis}/current"
            parts = [[comp.label, "—" if comp.value is None else f"{comp.value:,.0f}", False]
                     for comp in c.components]
            if not c.computable:
                if reported is None:
                    continue        # neither printed nor computable: nothing to say about it
                out.append({
                    "id": f"chk-uncomputed-{basis}-{key}", "type": "uncomputed", "icon": "∅",
                    "title": L("Printed subtotal could not be verified"),
                    "where": where, "severity": L("Not computable"), "tone": "med",
                    "delta": "—", "target": key,
                    "calc": [[L("Printed in the document"), f"{reported:,.0f}", True],
                             [L("Components extracted"), "0", False], *parts],
                    "fix": L("None of the lines this subtotal is made of were extracted, so it "
                             "could not be recomputed. The printed figure is on the face "
                             "unverified — map its components, or accept it as reported."),
                })
                continue
            if reported is None:
                continue            # computed cleanly and the document never printed it: fine
            diff = c.value - reported
            if abs(diff) <= _CALC_TOLERANCE:
                continue            # the printed figure and the components agree
            out.append({
                "id": f"chk-calc-{basis}-{key}", "type": "calculated_mismatch", "icon": "≠",
                "title": L("Printed subtotal differs from its components"),
                "where": where, "severity": L("Check failed"), "tone": "high",
                "delta": f"{diff:,.0f}", "target": key,
                "calc": [[L("Printed in the document"), f"{reported:,.0f}", False],
                         [L("Computed from components"), f"{c.value:,.0f}", True],
                         [L("Difference"), f"{diff:,.0f}", False], *parts],
                "fix": L("The face shows the computed figure. The document printed a different "
                         "one, so a component is mis-mapped, missing, or double-counted — check "
                         "the components below against the page."),
            })
    return out


def _build_review(rows: list[dict], filename: str, locale: str = "en",
                  reconciliation: list[dict] | None = None,
                  structural: list[dict] | None = None,
                  template_def: dict | None = None) -> dict:
    """Derive the human-in-the-loop review queue from a real extraction: failed accounting
    checks (balance identity, note ties, template structure) plus unmapped and low-confidence
    line items become review items (the QA the analyst works before export). No demo data
    involved."""
    def L(s: str) -> str:
        return _t(s, locale)

    _UNMAPPED_FIX = ("No canonical concept matched with confidence. Pick the correct template "
                     "line item, or add an alias so future runs map it automatically.")
    _LOWCONF_FIX = ("The mapping is uncertain. Confirm the concept is correct or reassign it; "
                    "the value and its source location are shown so you can verify against the document.")
    accounting = _accounting_checks(rows, reconciliation or [], locale, structural or [],
                                    template_def)
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
        elif "low_mapping_confidence" in flags or (isinstance(conf, (int, float)) and conf < _low_conf_threshold()):
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
    from app.services.derived import (
        build_credit_analysis, build_free_notes, compute_ratios, localize_disclosures)

    run = _latest_run(session, document_id)
    if run is None or not run.result:
        return {"ratios": [], "disclosures": [], "notes": [],
                "credit": build_credit_analysis([], [], locale=locale)}
    rows = run.result.get("rows", [])
    disclosures = localize_disclosures(run.result.get("disclosures", []), locale)
    credit = build_credit_analysis(rows, disclosures, locale=locale)
    # Fold in the cached LLM narrative (auto-generated at extraction when a provider is
    # configured, or produced on demand) so the Analysis screen shows it without a click.
    narrative = run.result.get("credit_narrative")
    if narrative and narrative.get("text"):
        credit = {**credit, "narrative": narrative}
    return {
        "ratios": compute_ratios(rows, locale=locale),
        "disclosures": disclosures,
        "notes": build_free_notes(rows, locale=locale),
        # Credit view combines the extracted ratios with the report's narrative disclosures.
        "credit": credit,
    }


@router.post("/{document_id}/credit-narrative",
             dependencies=[Depends(require(Permission.ANALYSIS_RUN)), Depends(authorized_document)])
def run_credit_narrative_endpoint(document_id: str, locale: str = Query("en"),
                                  session: Session = Depends(db)) -> dict:
    """Generate an LLM credit narrative that rationalises the deterministic credit view.

    The numbers stay deterministic — the model is given the already-computed stance, rating
    factors and report signals and only writes grounded prose (see analysis_llm.CREDIT_SYSTEM).
    Requires a real LLM provider (config ``llm.provider``); returns 409 when none is configured
    so the caller can keep using the deterministic summary. The run is written to the audit log."""
    from app.config import get_settings
    from app.ports.registry import registry as reg
    from app.services import audit as audit_svc
    from app.services.analysis_llm import run_credit_narrative
    from app.services.derived import build_credit_analysis, localize_disclosures

    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")

    rows = run.result.get("rows", [])
    disclosures = localize_disclosures(run.result.get("disclosures", []), locale)
    credit = build_credit_analysis(rows, disclosures, locale=locale)
    if not credit.get("factors") and not credit.get("flags"):
        raise HTTPException(status_code=422,
                            detail="Insufficient extracted data for a credit narrative")

    settings = get_settings()
    provider_id = settings.llm.provider
    entity = run.result.get("entity") or run.result.get("filename") or ""
    run_id = audit_svc.make_run_id(entity or "credit")
    if provider_id == "stub":
        raise HTTPException(
            status_code=409,
            detail="No LLM provider configured. Set llm.provider (e.g. 'anthropic') to enable "
                   "the credit narrative; the deterministic credit summary remains available.")

    try:
        provider = reg.get("llm", provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result, meta = run_credit_narrative(provider, credit, entity=entity, locale=locale,
                                            max_tokens=settings.llm.max_tokens)
    except Exception as exc:  # provider unreachable / no key / bad response
        audit_svc.record(document_id, audit_svc.AuditEntry(
            run_id=run_id, entity=entity, action="credit_narrative", provider=provider_id,
            model=settings.llm.model, input_tokens=None, output_tokens=None, status="failed"))
        raise HTTPException(status_code=502, detail=f"Credit narrative failed: {exc}") from exc

    model = meta.get("model", settings.llm.model)
    audit_svc.record(document_id, audit_svc.AuditEntry(
        run_id=run_id, entity=entity, action="credit_narrative", provider=provider_id,
        model=model, input_tokens=meta.get("input_tokens"),
        output_tokens=meta.get("output_tokens"), status="succeeded"))

    # Persist the narrative on the run so the Excel/JSON export can fold it in. Reassigning
    # the JSON column marks it dirty for the commit.
    run.result = {**run.result, "credit_narrative": {
        "text": result.narrative, "provider": provider_id, "model": model}}
    session.commit()

    return {"narrative": result.narrative, "provider": provider_id, "model": model}


def _localize_commentary(c: dict, locale: str) -> dict:
    """Localize a commentary payload's fixed catalog strings (headline/assessment/points and
    metric/trend labels) via the i18n table — the same table the demo path uses."""
    from app.sample.i18n_data import tr

    if locale == "en" or not c.get("metrics"):
        return c
    c["headline"] = tr(c["headline"], locale)
    c["assessment"] = tr(c["assessment"], locale)
    c["data_quality"] = tr(c["data_quality"], locale)
    c["strengths"] = [tr(s, locale) for s in c["strengths"]]
    c["weaknesses"] = [tr(w, locale) for w in c["weaknesses"]]
    for mtr in c["metrics"]:
        mtr["label"] = tr(mtr["label"], locale)
    for tnd in c.get("trends", []):
        tnd["label"] = tr(tnd["label"], locale)
    return c


@router.get("/{document_id}/commentary",
            dependencies=[Depends(require(Permission.COMMENTARY_VIEW)), Depends(authorized_document)])
def get_document_commentary(document_id: str, locale: str = Query("en"),
                            basis: str = Query("consolidated"),
                            session: Session = Depends(db)) -> dict:
    """Data-driven financial commentary for a REAL document, computed from its latest
    extraction (ratios, year-on-year trends, strengths/weaknesses) — not the demo project.
    Open review items are counted from the same extraction so the assessment stays honest
    about provisional figures. Empty (valid) shape until the document is extracted."""
    from app.services.commentary import build_commentary_from_rows

    run = _latest_run(session, document_id)
    if run is None or not run.result:
        return {"headline": "", "assessment": "", "metrics": [], "trends": [],
                "strengths": [], "weaknesses": [], "data_quality": "", "basis": ""}
    rows = run.result.get("rows", [])
    review = _build_review(rows, "", locale, run.result.get("reconciliation", []),
                           run.result.get("structural", []), _template_for_run(session, run))
    units = run.result.get("units") or {}
    c = build_commentary_from_rows(
        rows, open_review_items=review["summary"]["open"], basis=basis,
        currency=units.get("currency") or "", units=units.get("units_label") or "")
    return _localize_commentary(c, locale)


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
                         run.result.get("reconciliation", []),
                         run.result.get("structural", []), _template_for_run(session, run))


class LineItemEdit(BaseModel):
    value: float | None = None
    formula: str = ""
    period: str = "current"
    # Which set of figures is being edited. Without it every edit landed on the consolidated
    # column, so an analyst working the standalone statement saw nothing change.
    basis: str = "consolidated"
    # WHY the figure was changed. A manual value overrides what the document says and what the
    # template computes, so the reason it was overridden is part of the record — it travels with
    # the row, into the export, and to whoever reviews the spread after the analyst.
    comment: str = ""


def _template_concept(template_def: dict | None, canonical_key: str,
                      locale: str = "en") -> tuple[str, str] | None:
    """``(label, role)`` for a canonical key the template defines, else None."""
    for stmt in (template_def or {}).get("statements", []):
        for sec in stmt.get("sections") or []:
            for c in sec.get("children") or []:
                if c.get("canonical_key") == canonical_key:
                    label = (c.get("label_i18n") or {}).get(locale) or c.get("label") \
                        or canonical_key
                    return label, (c.get("role") or "line")
    return None


def _slot_id(basis: str, period: str) -> str:
    return f"{basis}/{period}"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.patch("/{document_id}/line-items/{canonical_key:path}",
              dependencies=[Depends(require(Permission.EXTRACTION_EDIT)), Depends(authorized_document)])
def edit_document_line_item(document_id: str, canonical_key: str, body: LineItemEdit,
                            session: Session = Depends(db),
                            principal: Principal = Depends(current_principal)) -> dict:
    """Edit one figure of a real extraction: a concept, in one basis, for one period.

    Three cases, all of which an analyst hits in the grid, and all of which used to fail
    silently:

    * the concept was extracted once — the ordinary case, the value is overlaid on that row;
    * SEVERAL printed lines map to the concept (a section's "Others", three depreciation
      lines) and the grid shows their sum — a typed figure then REPLACES that sum rather than
      joining it, so what was entered is what appears;
    * the template defines the line but the document never yielded it (a blank row in the
      grid) — the figure is recorded as a manual entry against that concept instead of 404ing.

    The overlay is persisted onto the latest run, so the statement, export, checks and review
    all read it; the machine-extracted numbers are snapshotted first so a revert is exact.
    """
    from app.db.models import Document

    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    if body.basis not in ("consolidated", "standalone"):
        raise HTTPException(status_code=422, detail=f"Unknown basis '{body.basis}'")
    result = dict(run.result)
    rows = result.get("rows", [])
    group = [r for r in rows if r.get("canonical_key") == canonical_key]
    if group:
        # The whole concept's manual figure lives on ONE row — its first, in run order — which
        # is the row the statement view and the export look to for an override. Every other
        # contributing line keeps its printed figure, so the composition stays auditable.
        target = group[0]
    else:
        concept = _template_concept(_template_for_run(session, run), canonical_key)
        if concept is None:
            raise HTTPException(
                status_code=404,
                detail=f"'{canonical_key}' is neither in this extraction nor in its template")
        label, role = concept
        target = {"canonical_key": canonical_key, "source_label": label, "role": role,
                  "values": [], "mapping_method": "manual", "mapping_confidence": None,
                  # Entered by hand rather than read off the page: a revert removes the row
                  # entirely instead of restoring a figure that never existed.
                  "manual": True}
        rows.append(target)

    values = target.setdefault("values", [])
    # Snapshot the machine-extracted values ONCE, before this concept's first edit, so a revert
    # restores the original numbers exactly (edits are overlays, never a lossy overwrite). The
    # WHOLE list is copied rather than a (basis, period) → value map: a row can legitimately hold
    # two values that share a basis and period label, and a map would collapse them and hand both
    # the same figure back on revert.
    if not target.get("edited"):
        target["_original"] = copy.deepcopy(values)

    # The slot the grid shows for this (basis, period) — matched by the period it names, so an
    # edit to the prior column cannot land on the current one (or vice versa).
    slot = slot_for(target, body.basis, body.period)
    if slot is None:
        slot = {"period_label": body.period, "basis": body.basis, "value": None,
                "provenance": None}
        values.append(slot)

    # A formula drives the value: evaluate it against the other line items (same basis and
    # period), so a real formula shows its computed result. If a formula is given alongside an
    # explicit value and can't be evaluated (e.g. free-form references), the explicit value
    # stands and the formula is kept as an annotation. A formula-ONLY edit that can't evaluate
    # is a 422.
    computed: float | None = None
    formula_error: str | None = None
    if body.formula and body.formula.strip().lstrip("=").strip():
        from app.services.formula import FormulaError, evaluate

        def _resolve(name: str) -> float:
            # Resolve a reference the way the grid renders it: the concept's figure, summed
            # across every printed line that maps to it (or its own manual override).
            n = _concept_value([r for r in rows if r.get("canonical_key") == name],
                               body.basis, body.period)
            if n is None:
                raise KeyError(name)
            return n

        try:
            computed = evaluate(body.formula, _resolve)
        except FormulaError as exc:
            formula_error = str(exc)

    if computed is not None:
        new_val = computed
    elif body.value is not None:
        new_val = body.value            # explicit value stands; formula kept as annotation
    elif formula_error is not None:
        raise HTTPException(status_code=422,
                            detail={"error": "bad_formula", "message": formula_error})
    else:
        new_val = None
    if new_val is None:
        slot["value"] = None
    else:
        fv = float(new_val)
        slot["value"] = str(int(fv)) if fv == int(fv) else str(fv)
    slot.setdefault("basis", body.basis)
    target["formula"] = body.formula or None
    target["edited"] = True
    slot_id = _slot_id(body.basis, body.period)
    # Which figures were typed, so an edit to one basis doesn't claim the other.
    target["edited_slots"] = sorted(set(target.get("edited_slots") or []) | {slot_id})
    comments = dict(target.get("edit_comments") or {})
    if body.comment.strip():
        comments[slot_id] = {"text": body.comment.strip()[:2000],
                             "by": getattr(principal, "username", "") or "",
                             "at": _now_iso()}
    else:
        # Clearing the box removes the note rather than leaving a stale reason on a new figure.
        comments.pop(slot_id, None)
    if comments:
        target["edit_comments"] = comments
    else:
        target.pop("edit_comments", None)

    result["rows"] = rows
    run.result = result
    flag_modified(run, "result")
    session.commit()
    return {"ok": True, "canonical_key": canonical_key, "basis": body.basis,
            "period": body.period, "value": slot["value"], "formula": target.get("formula"),
            "status": "edited", "label": target.get("source_label") or "",
            "comment": (target.get("edit_comments") or {}).get(slot_id, {}).get("text", ""),
            # What the grid will now show for this concept, so the caller can confirm the
            # figure it typed is the figure that took effect.
            "current": _concept_value(group or [target], body.basis, "current"),
            "prior": _concept_value(group or [target], body.basis, "prior"),
            "combined_from": len(group) if len(group) > 1 else 0}


@router.delete("/{document_id}/line-items/{canonical_key:path}",
               dependencies=[Depends(require(Permission.EXTRACTION_EDIT)), Depends(authorized_document)])
def revert_document_line_item(document_id: str, canonical_key: str,
                              session: Session = Depends(db)) -> dict:
    """Revert an edited line item to its original machine-extracted values, dropping the
    manual value(s) and formula. A line that only ever existed as a manual entry is removed."""
    from app.db.models import Document

    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    result = dict(run.result)
    rows = result.get("rows", [])
    target = next((r for r in rows
                   if r.get("canonical_key") == canonical_key and r.get("edited")), None)
    if target is None:
        target = next((r for r in rows if r.get("canonical_key") == canonical_key), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Line item not found in this run")
    if not target.get("edited"):
        return {"ok": True, "canonical_key": canonical_key, "reverted": False, "status": None}

    if target.get("manual"):
        # Nothing to restore: the line came from the analyst, not the document.
        rows = [r for r in rows if r is not target]
    else:
        original = target.get("_original")
        if isinstance(original, dict):
            # Runs edited before the snapshot was a full list: restore by period label alone.
            for v in target.get("values") or []:
                if v.get("period_label") in original:
                    v["value"] = original[v["period_label"]]
        elif original is not None:
            # Restore the machine-extracted values wholesale. Slots that exist only because an
            # edit created them are not in the snapshot and go away with the edit.
            target["values"] = copy.deepcopy(original)
        target.pop("_original", None)
        target.pop("formula", None)
        target["edited"] = False
        target.pop("edited_slots", None)
        target.pop("edit_comments", None)

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
    include: str | None = Query(None),
    units: str | None = Query(None),
    session: Session = Depends(db),
) -> Response:
    """Export a real document's extracted, mapped line items as Excel or JSON, built from
    the latest run (not the demo project).

    Excel supports two layouts: ``statement`` (default) mirrors the run's template —
    sections, subtotals, totals, ordering, localized labels, consolidated + standalone
    side by side; ``flat`` is one row per line item. ``include`` is a comma-separated set of
    optional analysis sheets to add (note_details, ratios, disclosures) — omit for all. JSON
    carries the line items with formulas plus a derived-analysis block."""
    from app.db.models import Document
    from app.services.export import (
        build_rows_json, build_rows_xlsx, build_statement_workbook, units_scale,
    )

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    rows = run.result.get("rows", [])
    name = (doc.filename or "extract").rsplit(".", 1)[0]
    include_set = ({p.strip() for p in include.split(",") if p.strip()}
                   if include is not None else None)
    # Present in a chosen unit only when the source scale was detected (never guess).
    src_units = run.result.get("units")
    scale, unit_label = units_scale(src_units, units)
    ccy = (src_units or {}).get("currency")
    caption = (f"Amounts in {ccy + ' ' if ccy else ''}{unit_label}" if unit_label else None)
    narrative = run.result.get("credit_narrative")  # stored LLM narrative, if generated
    if fmt == "json":
        data = build_rows_json(rows, filename=doc.filename or "document",
                               disclosures=run.result.get("disclosures", []),
                               note_details=run.result.get("note_details", []),
                               reconciliation=run.result.get("reconciliation", []), locale=locale,
                               credit_narrative=narrative,
                               netting_rules=run.result.get("netting") or [])
        return Response(content=data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})

    template_def = _template_for_run(session, run)
    if layout == "statement" and template_def:
        data = build_statement_workbook(rows, template_def, locale=locale,
                                        filename=doc.filename or "document",
                                        disclosures=run.result.get("disclosures", []),
                                        note_details=run.result.get("note_details", []),
                                        reconciliation=run.result.get("reconciliation", []),
                                        include=include_set, scale=scale, units_caption=caption,
                                        credit_narrative=narrative)
    else:
        data = build_rows_xlsx(rows, filename=doc.filename or "document", scale=scale)
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


def _default_scope(pages: list[dict]) -> set[int]:
    """Pages extraction would target by default — the classified face/notes pages."""
    return {(p.get("index", 0) or 0) for p in pages if p.get("kind") in ("face", "notes")}


def _build_pages(pages: list[dict], scope: list[int] | None = None) -> dict:
    """PagesResponse from the document's real classified pages. Inclusion reflects the user's
    persisted scope when set; otherwise the default (face/notes are in scope, the rest are
    skipped)."""
    chosen = set(scope) if scope is not None else _default_scope(pages)
    cards = []
    counts = {"face": 0, "notes": 0, "other": 0}
    for p in pages:
        kind = p.get("kind", "unknown")
        idx = p.get("index", 0) or 0
        included = idx in chosen
        cat, _ = _conf_cat(p.get("classification_confidence"))
        cards.append({
            "no": idx + 1,
            "kind": kind if kind in ("face", "notes") else "other",
            "cls": _PAGE_CLS.get(kind, kind.title()),
            "sub": "in scope" if included else "skipped",
            "conf": cat,
            "included": included,
            "scan": "scanned" if p.get("source_kind") == "scanned" else "native",
        })
        counts[kind if kind in counts else "other"] = counts.get(kind if kind in counts else "other", 0) + 1
    total = len(cards)
    focused = sum(1 for c in cards if c["included"])
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


def _document_pages(row, store: LocalObjectStore) -> list[dict]:
    """The document's classified pages — the copy persisted at upload, recomputing (and
    back-filling) only for legacy rows that predate page persistence."""
    if row.pages:
        return row.pages
    doc_model, _ctx = analyze_document(store.get(row.object_key), filename=row.filename or "")
    return [p.model_dump(mode="json") for p in doc_model.pages]


@router.get("/{document_id}/pages", dependencies=[Depends(authorized_document)])
def get_document_pages(
    document_id: str,
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> dict:
    """Real per-page classification for the Page Scope screen. Served from the pages captured
    at upload (no recompute), with inclusion reflecting any persisted user scope."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _build_pages(_document_pages(row, store), row.page_scope)


class ScopeEdit(BaseModel):
    included_pages: list[int]


@router.put("/{document_id}/scope",
            dependencies=[Depends(require(Permission.PIPELINE_RUN)), Depends(authorized_document)])
def set_document_scope(
    document_id: str,
    body: ScopeEdit,
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> dict:
    """Persist the user's page selection for extraction (the Page Scope screen). Extraction
    then restricts itself to these pages. Indices are validated against the document's pages;
    an empty selection resets to the default (all face/notes pages)."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    pages = _document_pages(row, store)
    valid = {(p.get("index", 0) or 0) for p in pages}
    chosen = sorted({i for i in body.included_pages if i in valid})
    # Empty (or a selection matching the default) → clear the override so the default applies.
    row.page_scope = chosen or None
    if row.pages is None:
        row.pages = pages          # back-fill persistence for legacy rows
    session.commit()
    return {"ok": True, "document_id": document_id,
            "included_pages": chosen, "count": len(chosen)}


# Fallback chrome for the reference statement types. The real label + canonical-key prefix
# are derived from the run's template (see _stmt_label/_stmt_prefix), so a template that adds
# a fourth statement (e.g. changes in equity) renders without code changes; these maps only
# apply when the template omits a label or can't be resolved.
_STMT_PREFIX = {"balance_sheet": "bs", "profit_and_loss": "pl", "cash_flow": "cf"}
_STMT_LABEL = {"balance_sheet": "Balance sheet", "profit_and_loss": "Profit & loss",
               "cash_flow": "Cash flow"}


def _stmt_node(template_def: dict | None, statement_type: str) -> dict | None:
    return next((s for s in (template_def or {}).get("statements", [])
                 if s.get("type") == statement_type), None)


def _stmt_prefix(template_def: dict | None, statement_type: str) -> str:
    """The canonical-key prefix for a statement (e.g. 'bs'), read from the template's own
    keys so it isn't limited to the three reference statements."""
    node = _stmt_node(template_def, statement_type)
    if node:
        for sec in node.get("sections", []):
            for c in sec.get("children") or []:
                k = c.get("canonical_key") or ""
                if "_" in k:
                    return k.split("_", 1)[0]
    if statement_type in _STMT_PREFIX:
        return _STMT_PREFIX[statement_type]
    return statement_type.split("_", 1)[0] if statement_type else ""


def _stmt_label(template_def: dict | None, statement_type: str, locale: str) -> str:
    """The statement's display label in the output locale — from the template node's
    label_i18n/label, falling back to the reference labels then a humanized type."""
    node = _stmt_node(template_def, statement_type)
    if node:
        lbl = (node.get("label_i18n") or {}).get(locale) or node.get("label")
        if lbl:
            return lbl
    if statement_type in _STMT_LABEL:
        return _t(_STMT_LABEL[statement_type], locale)
    return statement_type.replace("_", " ").title()


def _to_num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _basis_values(r: dict, basis: str) -> list[dict]:
    """Values for the requested basis; values with no basis are treated as consolidated."""
    return _basis_values_of(r, basis)


def _cur_prior(r: dict, basis: str = "consolidated") -> tuple[dict | None, dict | None]:
    """This row's current- and prior-period values. A period the row has no figure for stays
    None — see services.periods for why the positional fallback must not fire here."""
    return split_current_prior(_basis_values(r, basis))


def _inspector(r: dict, cur: dict | None) -> dict:
    prov = (cur or {}).get("provenance")
    return {"tag": "machine", "src": _prov_label(prov) if prov else "",
            "formula": "", "result": str((cur or {}).get("value") or ""),
            "note": f"Mapped by {r.get('mapping_method') or 'ensemble'}"}


def _netting_rules_for_run(session: Session, run) -> list:
    """The face-line netting rules from the ontology the run used (empty when none/unavailable)."""
    from app.db.models import OntologyVersion
    from app.schemas.loader import load_ontology

    oid = (run.options or {}).get("ontology_version_id")
    row = session.get(OntologyVersion, oid) if oid else None
    if row is None:
        return []
    try:
        return load_ontology(row.definition).netting_rules
    except Exception:  # noqa: BLE001 — a malformed ontology must not break the statement
        return []


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


_BASIS_LABEL_I18N = {
    "consolidated": {"en": "Consolidated", "zh": "合并", "ar": "موحّد", "fr": "Consolidé"},
    "standalone": {"en": "Standalone", "zh": "单独", "ar": "مستقل", "fr": "Individuel"},
}


def _loc(node: dict, locale: str) -> str:
    """A template node's label in the output locale, from label_i18n (falls back to label)."""
    return (node.get("label_i18n") or {}).get(locale) or node.get("label") or ""


def _disp_period(lbl: str | None, idx: int, locale: str) -> str:
    """Display a period header: the source's own header (e.g. a year-end date like
    '31 Mar 2025') when it captured one; otherwise the generic Current/Prior label."""
    if not lbl or lbl in ("current",) or lbl.startswith("col"):
        return _t("Current" if idx == 0 else "Prior", locale)
    if lbl == "prior":
        return _t("Prior", locale)
    return lbl


def _period_labels(rows: list[dict], basis: str, locale: str) -> list[str]:
    """The two period-column headers for the statement. Uses the real headers the extractor
    captured (Excel carries the year/date text); falls back to Current/Prior (e.g. native PDF,
    where the column header date isn't yet detected).

    Each header is looked up by the period it NAMES, across every row, rather than taken
    positionally from the first row that carries any value at all — a row printed for one year
    only would otherwise label both columns with that year's period.
    """
    found: dict[str, str | None] = {}
    positional: list[str | None] | None = None
    for r in rows:
        vals = _basis_values(r, basis)
        if not vals:
            continue
        for period, disp in period_displays(vals).items():
            found.setdefault(period, disp)
        if positional is None and not period_displays(vals):
            # A row whose columns are unnamed (col0/col1) still tells us the header order.
            positional = [(v.get("period_display") or v.get("period_label")) for v in vals]
        if "current" in found and "prior" in found:
            break
    if found:
        return [_disp_period(found.get("current"), 0, locale),
                _disp_period(found.get("prior"), 1, locale)]
    if positional:
        return [_disp_period(positional[0] if positional else None, 0, locale),
                _disp_period(positional[1] if len(positional) > 1 else None, 1, locale)]
    return [_t("Current", locale), _t("Prior", locale)]


# A two-column comparative labels its values positionally — "current", "prior", "col2" for a
# third numeric column. A matrix labels them with the column header text it read off the page
# ("Issued capital", "Retained profits"). That is the discriminator between the two shapes, and
# it needs no extra plumbing: the label already travels with every value.
_POSITIONAL_PERIOD = re.compile(r"^(current|prior|col\d+)$", re.IGNORECASE)
# A column header that reads as a period rather than a component. Excel carries the sheet's real
# header TEXT in period_label ("2023", "31 December 2023", "FY2024"), so without this every
# spreadsheet row looks like an equity movement with two component columns.
_PERIOD_LIKE = re.compile(r"(19|20)\d{2}|\bfy\b|\bq[1-4]\b|年", re.IGNORECASE)


def _is_named_column(label) -> bool:
    """Whether a value's column is NAMED — an equity component ("Retained profits") — as opposed
    to a period, whether that period was labelled positionally or by its own printed date."""
    s = str(label or "").strip()
    return bool(s) and not _POSITIONAL_PERIOD.match(s) and not _PERIOD_LIKE.search(s)


def _matrix_cells(row: dict, basis: str) -> dict[str, object]:
    """This row's named component cells for one basis — empty for a comparative row."""
    out: dict[str, object] = {}
    for v in row.get("values") or []:
        if (v.get("basis") or "consolidated") != basis:
            continue
        if _is_named_column(v.get("period_label")):
            out[str(v["period_label"])] = v
    return out


def _matrix_rows(rows: list[dict], basis: str) -> list[tuple[dict, dict]]:
    """(row, named cells) for every row that is part of the matrix.

    A movement in equity always touches at least its own component and a total column, so two
    named cells is the floor — that keeps a stray one-column row out of the statement.
    """
    out = []
    for r in rows:
        cells = _matrix_cells(r, basis)
        if len(cells) >= 2:
            out.append((r, cells))
    return out


def _matrix_columns(rows: list[dict], basis: str) -> list[str]:
    """The component columns of a matrix statement, in the order they are PRINTED.

    Column identity is the header text extraction already attached to each value; the order is
    recovered from where the figures sit on the page (the median x of a column's cells), because
    a dict of values has no left-to-right order of its own and equity statements are read
    left-to-right — issued capital through to total equity.
    """
    xs: dict[str, list[float]] = {}
    for _r, cells in _matrix_rows(rows, basis):
        for name, v in cells.items():
            box = ((v.get("provenance") or {}).get("bbox")) or {}
            x = box.get("x0")
            xs.setdefault(name, []).append(0.0 if x is None else float(x))
    def centre(name: str) -> float:
        vals = sorted(xs[name])
        return vals[len(vals) // 2] if vals else 0.0
    return sorted(xs, key=centre)


def _build_matrix_statement(rows: list[dict], statement_type: str, filename: str, *,
                            basis: str, locale: str, units_ctx: dict | None,
                            company: str | None, doc_format: str, page_count: int,
                            template_def: dict | None) -> dict:
    """A matrix statement: named component columns, one row per movement, in document order.

    Rows keep the caption as printed. A movement's identity in a statement of changes in equity
    IS its caption ("Profit for the year", "Dividends paid", "Acquisition of a subsidiary"), and
    there is no section skeleton to slot it into — so the printed order is the statement's order,
    and every parsed row appears. ``cells`` is keyed by column name; ``v1``/``v2`` stay null so
    nothing downstream mistakes a component for a period.
    """
    columns = _matrix_columns(rows, basis)
    out: list[dict] = []
    for r, raw_cells in _matrix_rows(rows, basis):
        cells = {name: _to_num(v.get("value")) for name, v in raw_cells.items()}
        prov = next((v.get("provenance") for v in raw_cells.values() if v.get("provenance")), None)
        cat, pct = _conf_cat(r.get("mapping_confidence"))
        label = r.get("source_label") or ""
        out.append({
            "id": r.get("canonical_key") or f"eq:{len(out)}:{label[:40]}",
            "label": label, "source_label": label,
            # A row whose every figure lands in a "total" column is the statement's own subtotal.
            "kind": "subtotal" if _looks_like_equity_total(label) else "item",
            "note": r.get("note"), "note2": None, "status": None,
            "confidence": {"cat": cat, "pct": pct} if r.get("mapping_confidence") else None,
            "editable": False, "formula": None,
            "inspector": _inspector(r, {"value": next(iter(cells.values()), None),
                                        "provenance": prov}),
            "contributions": None, "cells": cells,
            # A matrix has no prior COLUMN — its columns are components — so there is no second
            # period provenance to carry.
            "v1": None, "v2": None, "source": prov, "source2": None,
        })

    basis_label = _t("Consolidated" if basis == "consolidated" else "Standalone", locale)
    return {
        "statement": statement_type,
        "label": _stmt_label(template_def, statement_type, locale),
        "basis": basis,
        # The shape the client must render. Absent/"comparative" is the two-column default.
        "layout": "matrix",
        "columns": [{"key": c, "label": c} for c in columns],
        "periods": [],
        "currency": (units_ctx or {}).get("currency") or "",
        "currency_symbol": "", "units": (units_ctx or {}).get("units_label") or "",
        "units_scale_factor": _to_num((units_ctx or {}).get("scale_factor")) or 1.0,
        "format": doc_format, "page_count": page_count,
        "rows": out,
        "viewer": {
            "company": company or filename, "subtitle": _t("Extracted statement", locale),
            "chips": [{"label": basis_label, "active": True}],
            "callout": _t("Columns are equity components as printed, not periods. Click a row "
                          "to see it in the document.", locale),
        },
    }


# A movement row whose caption is an opening/closing balance is the matrix's own subtotal line.
_EQUITY_TOTAL = re.compile(
    r"^\s*(at|as at|balance(s)? (at|as at))\b|^\s*(於|于|截至)", re.IGNORECASE)


def _looks_like_equity_total(label: str) -> bool:
    return bool(_EQUITY_TOTAL.search(label or ""))


def _equity_closing(rows: list[dict], basis: str) -> tuple[str, float] | None:
    """The equity statement's CLOSING total equity, as (caption, amount).

    The last balance line in document order is the closing one — an equity statement runs
    opening balance, movements, closing balance, and a two-year statement simply does that
    twice. Returns None when the document carries no equity matrix at all.
    """
    total_col = None
    last = None
    for r, cells in _matrix_rows(rows, basis):
        if total_col is None:
            total_col = next((c for c in cells if "total equity" in c.lower()), None)
        if total_col and _looks_like_equity_total(r.get("source_label") or ""):
            v = _to_num((cells.get(total_col) or {}).get("value"))
            if v is not None:
                last = (r.get("source_label") or "", v)
    return last


# A computed subtotal and the printed one are read from the same page in the same units, so any
# real difference is a whole currency unit or more. Below that it is float noise from the sum.
_CALC_TOLERANCE = 0.5


def _component_value(calc: dict, owner_key: str, index: int):
    """One component's figure for the period `calc` was evaluated for.

    Read from that period's own evaluation rather than from another period's component list: a
    Calculated is evaluated for ONE period, so reusing its figures would print this year's
    components under last year's total.
    """
    own = calc.get(owner_key)
    if own is not None and index < len(own.components):
        return own.components[index].value
    return None


_CALC_NOTES = {
    "calculated": "Computed from the {n} template lines below, each of which clicks through to "
                  "the page it was printed on. The document's own printed figure is held for "
                  "review, not shown here — a subtotal that contradicts its components is a "
                  "finding rather than a number.",
    "manual": "A value entered by hand, which stands over the computed one. The components below "
              "are what the template says this line is made of.",
    "reported_uncomputed": "None of the components this line is made of were extracted, so there "
                           "was nothing to compute from and the document's printed figure is "
                           "shown unverified. It is in the review queue.",
}


def _calculated_note(origin: str, diff: float | None, n_components: int, locale: str) -> str:
    note = _t(_CALC_NOTES[origin], locale).replace("{n}", str(n_components))
    if diff is not None and abs(diff) > _CALC_TOLERANCE:
        note = f"{note} {_t('The printed figure differs by', locale)} {diff:,.0f}."
    return note


def _calculated(rows: list[dict], template_def: dict | None, basis: str, period: str,
                locale: str) -> dict:
    """Evaluate the template's calculated lines for one (basis, period).

    Inputs are read through ``concept_value``, so a calculated line is built from exactly the
    figures the grid shows for its components — including an analyst's manual correction to one
    of them, which is the point: fixing a component has to fix every subtotal above it.
    """
    from app.services.rollups import evaluate, node_labels

    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = r.get("canonical_key")
        if k:
            groups.setdefault(k, []).append(r)

    def reported(key: str):
        return _concept_value(groups.get(key, []), basis, period)

    return evaluate(template_def, reported, labels=node_labels(template_def, locale))


_KPI_CATEGORY_I18N = {
    "Liquidity": {"zh": "流动性", "ar": "السيولة", "fr": "Liquidité"},
    "Leverage": {"zh": "杠杆", "ar": "الرافعة المالية", "fr": "Endettement"},
    "Coverage": {"zh": "偿付能力", "ar": "التغطية", "fr": "Couverture"},
    "Efficiency": {"zh": "运营效率", "ar": "الكفاءة", "fr": "Efficacité"},
    "Profitability": {"zh": "盈利能力", "ar": "الربحية", "fr": "الربحية"},
}


def _key_provenance(rows: list[dict], basis: str) -> dict[str, tuple[dict | None, dict | None]]:
    """canonical key → (current, prior) provenance of the first line that carried it, so a
    derived figure can still be traced to the page its inputs were printed on."""
    out: dict[str, tuple[dict | None, dict | None]] = {}
    for r in rows:
        k = r.get("canonical_key")
        if not k or k in out:
            continue
        cur, prior = _cur_prior(r, basis)
        out[k] = ((cur or {}).get("provenance"), (prior or {}).get("provenance"))
    return out


def _kpi_inputs_as_contributions(inputs: dict, prior_inputs: dict, provs: dict,
                                 locale: str) -> list[dict]:
    """A ratio's inputs in the same shape as a combined line's contributions, so the inspector
    shows the arithmetic with each figure clickable through to where it was printed."""
    out: list[dict] = []
    for side, sign_label in (("numerator", _t("numerator", locale)),
                             ("denominator", _t("denominator", locale))):
        prior_by = {str(i.get("canonical_key")): i for i in (prior_inputs.get(side) or [])}
        for i in inputs.get(side) or []:
            key = str(i.get("canonical_key") or "")
            cur_prov, prior_prov = provs.get(key, (None, None))
            sign = i.get("sign") or 1
            pv = prior_by.get(key, {}).get("value")
            out.append({
                "label": f"{sign_label}: {i.get('label') or ''}",
                "canonical_key": key or None,
                "v1": None if i.get("value") is None else sign * float(i["value"]),
                "v2": None if pv is None else sign * float(pv),
                "method": None,
                # An input the filing never reported: shown, and shown as absent.
                "residual": i.get("value") is None,
                "src": _prov_label(cur_prov), "source": cur_prov,
                "src2": _prov_label(prior_prov), "source2": prior_prov,
            })
    return out


def _build_kpi_statement(rows: list[dict], filename: str, *, basis: str, locale: str,
                         company: str | None, doc_format: str, page_count: int,
                         template_def: dict | None) -> dict:
    """The KPI view — the ratio catalog computed from THIS extraction, current beside prior.

    A ratio is not a currency amount: it carries its own unit (×, %, days) and is untouched by
    the presentation currency or magnitude an analyst picks for the statements. So every figure
    ships a formatted ``display`` string beside the raw number and the grid renders that
    verbatim, instead of scaling a current ratio of 1.35 into "thousands".

    Ratios whose inputs the filing never reported are listed as unavailable rather than dropped:
    which KPIs a document cannot support is itself a finding.
    """
    from app.services.derived import compute_ratios

    cur = compute_ratios(rows, basis=basis, period="current", locale=locale)
    prior = {r["key"]: r for r in compute_ratios(rows, basis=basis, period="prior", locale=locale)}
    provs = _key_provenance(rows, basis)

    out: list[dict] = []
    seen_cat: set[str] = set()
    for ratio in cur:
        cat = ratio.get("category") or "Profitability"
        if cat not in seen_cat:
            seen_cat.add(cat)
            out.append({"id": f"kpi_sec_{cat.lower()}",
                        "label": _KPI_CATEGORY_I18N.get(cat, {}).get(locale, cat),
                        "kind": "section", "v1": None, "v2": None})
        p = prior.get(ratio["key"], {})
        contributions = _kpi_inputs_as_contributions(
            ratio.get("inputs") or {}, p.get("inputs") or {}, provs, locale)
        out.append({
            "id": f"kpi_{ratio['key']}", "label": ratio["label"], "source_label": None,
            "kind": "item", "note": None, "note2": None,
            "status": None if ratio.get("available") else "missing",
            "confidence": None,
            # Derived, not extracted: there is no single figure on a page to correct, so the fix
            # for a wrong ratio is to fix the line items it is computed from.
            "editable": False,
            "formula": ratio.get("formula"),
            "inspector": {
                "tag": _t("computed", locale) if ratio.get("available")
                       else _t("inputs not extracted", locale),
                "src": "", "formula": ratio.get("formula") or "",
                "result": ratio.get("display") or "",
                "note": _t("Computed from the extracted line items below — each one clicks "
                           "through to the page it was printed on. Correct a KPI by correcting "
                           "its inputs.", locale),
            },
            "contributions": contributions or None,
            "v1": ratio.get("value"), "v2": p.get("value"),
            # Pre-formatted with the ratio's own unit; the grid shows these instead of applying
            # the statements' currency/magnitude presentation.
            "display1": ratio.get("display") or "—", "display2": p.get("display") or "—",
            "source": None, "source2": None,
        })

    return {
        "statement": "kpi", "label": _t("KPIs", locale), "basis": basis,
        "layout": "comparative", "periods": _period_labels(rows, basis, locale),
        # Ratios are unitless: no currency, no magnitude, nothing for the presentation
        # selectors to scale. `display1`/`display2` are already in each ratio's own unit.
        "currency": "", "currency_symbol": "", "units": "", "units_scale_factor": 1.0,
        "presentation": "raw",
        "format": doc_format, "page_count": page_count,
        "rows": out,
        "viewer": {
            "company": company or filename, "subtitle": _t("Computed KPIs", locale),
            "chips": [{"label": _t("Consolidated" if basis == "consolidated" else "Standalone",
                                   locale), "active": True}],
            "callout": _t("Every KPI is computed from this document's own extracted figures. "
                          "Select one to see its inputs and jump to where each was printed.",
                          locale),
        },
    }


def _face_prefixes(template_def: dict | None) -> set[str]:
    """The canonical-key prefixes that DO reach a face statement, so anything else can be
    recognised as not being on one."""
    out = {p for p in _STMT_PREFIX.values()}
    for stmt in (template_def or {}).get("statements", []):
        t = stmt.get("type")
        if t:
            p = _stmt_prefix(template_def, t)
            if p:
                out.add(p)
    return out


def _build_additional_items_statement(rows: list[dict], template_def: dict | None, filename: str,
                                      *, basis: str, locale: str, units_ctx: dict | None,
                                      company: str | None, doc_format: str,
                                      page_count: int) -> dict:
    """Everything extracted that reaches NO face statement — the honest remainder.

    A figure the pipeline read off the page but could not place is the one thing a spreading tool
    must never hide: silence there reads as "the document did not contain it". Two kinds end up
    here, and the distinction is what an analyst acts on:

    * lines mapped to no concept at all — the mapper found nothing close enough, so they need a
      concept (or an ontology alias) before they can join a statement;
    * lines mapped to a concept that belongs to no statement in the active template — correctly
      identified, but the template has nowhere to print them.

    Rows that are part of the changes-in-equity matrix are excluded: they are on a face already.
    """
    prefixes = _face_prefixes(template_def)
    on_matrix = {id(r) for r, _cells in _matrix_rows(rows, basis)}

    unmapped: list[dict] = []
    off_template: list[dict] = []
    for r in rows:
        if not _basis_values(r, basis) or id(r) in on_matrix:
            continue
        key = r.get("canonical_key") or ""
        if key and key.split("_", 1)[0] in prefixes:
            continue                      # reaches a face statement (or its "Other extracted")
        (off_template if key else unmapped).append(r)

    def row_of(r: dict, idx: int) -> dict:
        cur, prior = _cur_prior(r, basis)
        cat, pct = _conf_cat(r.get("mapping_confidence"))
        key = r.get("canonical_key")
        return {
            # Rows with no concept have no canonical key to address, so the id is positional.
            "id": key or f"extra:{idx}:{(r.get('source_label') or '')[:40]}",
            "label": r.get("source_label") or "", "source_label": r.get("source_label"),
            "kind": "item", "note": r.get("note"), "note2": None,
            "status": "edited" if _edited_for(r, basis) else None,
            "confidence": {"cat": cat, "pct": pct} if r.get("mapping_confidence") else None,
            # Editing addresses a CONCEPT, so a line mapped to none cannot be edited here —
            # give it a concept on the Review screen first.
            "editable": bool(key),
            "formula": r.get("formula"),
            "inspector": {
                "tag": (r.get("mapping_method") or "unmapped") if key else _t("unmapped", locale),
                "src": _prov_label((cur or {}).get("provenance")),
                "formula": r.get("formula") or "",
                "result": str((cur or {}).get("value") or ""),
                "note": _t("Mapped to a concept the active template has no line for.", locale)
                        if key else
                        _t("No concept matched this caption, so it appears on no statement. "
                           "Map it from the Review queue to bring it onto the face.", locale),
            },
            "contributions": None,
            "v1": _to_num((cur or {}).get("value")), "v2": _to_num((prior or {}).get("value")),
            "source": (cur or {}).get("provenance"),
            "source2": (prior or {}).get("provenance"),
        }

    out: list[dict] = []
    idx = 0
    for label, group in ((_t("Not mapped to any concept", locale), unmapped),
                         (_t("Mapped, but not on any statement in this template", locale),
                          off_template)):
        if not group:
            continue
        out.append({"id": f"extra_sec_{len(out)}", "label": label, "kind": "section",
                    "v1": None, "v2": None})
        for r in group:
            out.append(row_of(r, idx))
            idx += 1

    return {
        "statement": "additional_items", "label": _t("Additional items", locale), "basis": basis,
        "layout": "comparative", "periods": _period_labels(rows, basis, locale),
        "currency": (units_ctx or {}).get("currency") or "",
        "currency_symbol": "", "units": (units_ctx or {}).get("units_label") or "",
        "units_scale_factor": _to_num((units_ctx or {}).get("scale_factor")) or 1.0,
        "format": doc_format, "page_count": page_count,
        "rows": out,
        "viewer": {
            "company": company or filename, "subtitle": _t("Extracted, not on a statement", locale),
            "chips": [{"label": _t("Consolidated" if basis == "consolidated" else "Standalone",
                                   locale), "active": True}],
            "callout": _t("Figures read from the document that reach no face statement. Click one "
                          "to see where it was printed.", locale),
        },
    }


def _build_statement(rows: list[dict], template_def: dict | None, statement_type: str,
                     filename: str, basis: str = "consolidated", locale: str = "en",
                     units_ctx: dict | None = None, company: str | None = None,
                     doc_format: str = "", page_count: int = 0,
                     netting_rules: list | None = None) -> dict:
    """Group the real extracted rows into one statement (by the template's sections), so the
    Workspace grid renders real data with its provenance-backed values. Only rows that
    carry a value for the requested `basis` (consolidated / standalone) are shown. Labels are
    resolved in the output `locale` from the template's label_i18n (input=output parity)."""
    prefix = _stmt_prefix(template_def, statement_type)
    # A statement of changes in equity is not a two-column comparative — its columns are equity
    # COMPONENTS (issued capital, each reserve, retained profits, non-controlling interests,
    # total equity) and its rows are movements through the year. Forcing it into current/prior
    # columns files a component under a period that does not exist, so it gets its own shape.
    if statement_type == "changes_in_equity":
        return _build_matrix_statement(
            rows, statement_type, filename, basis=basis, locale=locale, units_ctx=units_ctx,
            company=company, doc_format=doc_format, page_count=page_count,
            template_def=template_def)
    # Two views that are not statements the document prints, but which the document's figures
    # determine: the KPIs computed off them, and everything extracted that reaches no face.
    if statement_type == "kpi":
        return _build_kpi_statement(
            rows, filename, basis=basis, locale=locale, company=company,
            doc_format=doc_format, page_count=page_count, template_def=template_def)
    if statement_type == "additional_items":
        return _build_additional_items_statement(
            rows, template_def, filename, basis=basis, locale=locale, units_ctx=units_ctx,
            company=company, doc_format=doc_format, page_count=page_count)
    # Several printed lines legitimately share one concept: three depreciation lines roll into
    # "Depreciation and amortisation", two tax payments into "Income tax paid", and an "Others"
    # bucket exists precisely to absorb a handful. Keeping only the first row would drop the
    # rest from the statement silently, so rows are grouped and their values added.
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        k = r.get("canonical_key")
        if k:
            by_key.setdefault(k, []).append(r)

    def has_basis(r: dict) -> bool:
        return bool(_basis_values(r, basis))

    # The template's calculated lines — subtotals, totals, net figures — evaluated from the
    # components the template says they are made of. A subtotal printed on the page is a fourth
    # opinion alongside the lines it is meant to be the sum of; when they disagree, showing the
    # printed one puts a figure on the face that its own components contradict. So the computed
    # figure is what the grid shows, the printed one is kept for the review queue, and their
    # difference becomes a finding rather than a silent inconsistency.
    calc_cur = _calculated(rows, template_def, basis, "current", locale)
    calc_prior = _calculated(rows, template_def, basis, "prior", locale)

    # A template child's presentation kind (subtotal / total rows are styled differently in
    # the grid); anything else is a plain line item.
    def _kind_for(role: str | None) -> str:
        return {"subtotal": "subtotal", "total": "total"}.get(role or "", "item")

    provs = _key_provenance(rows, basis)

    def as_calculated(row: dict) -> dict:
        """Put the COMPUTED figure on a calculated line, and keep the printed one out of sight.

        The template says this line is made of other lines, so that is the figure the face
        carries. What the document printed is retained as ``reported1``/``reported2`` — not shown
        as the line's value, because a subtotal that contradicts its own components is a finding,
        not a number — and the review queue is built from exactly that difference.

        Precedence is manual > computed > printed. An analyst's typed value is their answer for
        the line and outranks the arithmetic; a line whose components were never extracted has
        nothing to compute from, so it falls back to the printed figure and says so.
        """
        key = row["id"]
        c1, c2 = calc_cur.get(key), calc_prior.get(key)
        if c1 is None and c2 is None:
            return row                                   # not a calculated line
        row["reported1"], row["reported2"] = row["v1"], row["v2"]
        if row.get("status") == "edited":
            # A manual value stands. Still say what the components come to, so the analyst can
            # see what they overrode.
            row["origin"] = "manual"
            row["calculated1"] = c1.value if c1 else None
            row["calculated2"] = c2.value if c2 else None
        elif (c1 and c1.computable) or (c2 and c2.computable):
            row["origin"] = "calculated"
            row["v1"] = c1.value if (c1 and c1.computable) else None
            row["v2"] = c2.value if (c2 and c2.computable) else None
            row["calculated1"], row["calculated2"] = row["v1"], row["v2"]
            # The document not printing this line is no longer a gap: the template says what it
            # is made of, and the components were there.
            if row.get("status") == "missing":
                row["status"] = None
        else:
            # Nothing to compute from: no component of this line was extracted. Showing the
            # printed figure beats showing a blank, but it is labelled as unverified.
            row["origin"] = "reported_uncomputed"
            row["calculated1"] = row["calculated2"] = None

        source = c1 if (c1 and c1.components) else c2
        if source is not None:
            row["formula"] = source.formula or row.get("formula")
            # The components ARE the traceability: each with its own figure and the page it was
            # printed on, so a computed subtotal can be taken apart line by line.
            row["contributions"] = [{
                "label": comp.label,
                "canonical_key": comp.canonical_key,
                "v1": _component_value(calc_cur, key, i),
                "v2": _component_value(calc_prior, key, i),
                "method": "calculated" if comp.canonical_key in calc_cur else None,
                "residual": comp.value is None,
                "src": _prov_label(provs.get(comp.canonical_key, (None, None))[0]),
                "source": provs.get(comp.canonical_key, (None, None))[0],
                "src2": _prov_label(provs.get(comp.canonical_key, (None, None))[1]),
                "source2": provs.get(comp.canonical_key, (None, None))[1],
            } for i, comp in enumerate(source.components)]
        diff = None
        if row["origin"] == "calculated" and row["v1"] is not None \
                and row["reported1"] is not None:
            diff = row["v1"] - row["reported1"]
        row["inspector"] = {
            "tag": {"calculated": _t("calculated", locale),
                    "manual": _t("manual override", locale),
                    "reported_uncomputed": _t("printed, not computable", locale)}[row["origin"]],
            "src": "", "formula": row.get("formula") or "",
            "result": "" if row["v1"] is None else f"{row['v1']:,.0f}",
            "note": _calculated_note(row["origin"], diff, len(source.components) if source else 0,
                                    locale),
        }
        if diff is not None and abs(diff) > _CALC_TOLERANCE:
            # A divergence is the finding; the review queue carries it with the arithmetic.
            row["status"] = "recon"
        row["confidence"] = row.get("confidence")
        return row

    def item_row(key: str, label: str, group: list[dict], kind: str = "item") -> dict:
        """One statement row from every extracted row that mapped to this concept.

        With a single source row this is that row. With several, the values are summed and the
        inspector says how many printed lines went into the figure, so a total that does not
        match any one line on the page is explainable rather than mysterious. Provenance stays
        on the first contributing line, which is where click-to-source lands — carried for BOTH
        periods, because last year's figure is printed somewhere too and is just as much a
        number a reviewer needs to check against the page.
        """
        r = group[0]
        cur, prior = _cur_prior(r, basis)
        cat, pct = _conf_cat(min((x.get("mapping_confidence") or 0) for x in group)
                             if len(group) > 1 else r.get("mapping_confidence"))
        # An edit to the consolidated figures does not make the standalone ones edited.
        edited_row = next((x for x in group if _edited_for(x, basis)), None)
        edited = edited_row is not None
        # One reader for the figure — the sum of the printed lines, or the analyst's manual
        # value replacing it. See services.periods.concept_value.
        v1 = _concept_value(group, basis, "current")
        v2 = _concept_value(group, basis, "prior")
        inspector = _inspector(r, cur)
        formula = (edited_row or r).get("formula")
        contributions: list[dict] = []
        if len(group) > 1:
            # A combined figure has to be auditable line by line: each contributing caption with
            # its OWN values and its OWN source location, so every part can be traced back to the
            # page it was printed on. A prose summary cannot be clicked.
            for x in group:
                c, p = _cur_prior(x, basis)
                contributions.append({
                    "label": x.get("source_label") or "",
                    "canonical_key": x.get("canonical_key"),
                    "v1": _to_num((c or {}).get("value")),
                    "v2": _to_num((p or {}).get("value")),
                    "method": x.get("mapping_method"),
                    # Whether this line was ROUTED here (no specific concept matched) rather than
                    # identified — the difference an analyst needs before accepting the figure.
                    "residual": any("residual_combined" in ((v.get("confidence") or {})
                                                            .get("flags") or [])
                                    for v in (x.get("values") or [])),
                    "src": _prov_label((c or {}).get("provenance")),
                    "source": (c or {}).get("provenance"),
                    # …and the same for the prior period, which sits in its own column on its
                    # own page in a filing that reprints last year's statement.
                    "src2": _prov_label((p or {}).get("provenance")),
                    "source2": (p or {}).get("provenance"),
                })
            terms = [f"{c['v1']:,.0f}" if c["v1"] is not None else "—" for c in contributions]
            printed = " + ".join(terms)
            formula = formula or printed
            inspector = {**inspector, "tag": "combined",
                         "formula": formula,
                         "result": "" if v1 is None else f"{v1:,.0f}",
                         "src": " · ".join(dict.fromkeys(
                             c["src"] for c in contributions if c["src"])),
                         "note": (f"Combined from {len(group)} printed lines that map to this "
                                  f"concept. Each line below keeps its own figure and page — "
                                  f"click one to jump to it in the document.")
                                 + (f" A manual value replaces the combined figure; the printed "
                                    f"lines still add to {printed}." if edited else "")}
        notes = {}
        for x in group:
            for slot, meta in (x.get("edit_comments") or {}).items():
                b, _, per = str(slot).partition("/")
                if b == basis and (meta or {}).get("text"):
                    notes[per] = meta
        return as_calculated({
            "id": key, "label": label or r.get("source_label"),
            "source_label": r.get("source_label"), "kind": kind,
            "note": next((x.get("note") for x in group if x.get("note")), None),
            "note2": None, "status": "edited" if edited else None,
            "confidence": {"cat": cat, "pct": pct}, "editable": True,
            "origin": "manual" if edited else "extracted",
            # Why a figure was overridden, per period — kept beside the number it explains.
            "comments": notes or None,
            "formula": formula, "inspector": inspector,
            # Present only when more than one printed line was combined into this figure.
            "contributions": contributions or None,
            "v1": v1, "v2": v2,
            # Structured source location of each period's value, so the Workspace's live viewer
            # can hyperlink BOTH figures in the row to the page+bbox (PDF) or sheet+cell (Excel)
            # they were printed at — the prior year is a number a reviewer checks too.
            "source": (cur or {}).get("provenance"),
            "source2": (prior or {}).get("provenance"),
        })

    # A template line that wasn't extracted (or has no value for this basis) still appears, so
    # the analyst sees the FULL template skeleton and can spot/fill gaps — just with blank values.
    # A CALCULATED line is a different case entirely: the document never had to print it for the
    # spread to carry it, so as_calculated fills it in from its components.
    def blank_row(key: str, label: str, kind: str = "item") -> dict:
        return as_calculated({
            "id": key, "label": label, "source_label": None, "kind": kind,
            "note": None, "note2": None, "status": "missing",
            "confidence": None, "editable": True, "formula": None, "origin": "extracted",
            "comments": None,
            "inspector": {"tag": _t("not extracted", locale), "src": "", "formula": "",
                          "result": "", "note": _t("This template line was not found in the "
                                                    "document's extraction for this basis. Enter "
                                                    "a value to record it manually.", locale)},
            "v1": None, "v2": None, "source": None, "source2": None,
        })

    # Show the full template skeleton only when this statement+basis is actually present in the
    # document. If the basis wasn't extracted at all (e.g. no standalone figures), the grid stays
    # empty rather than implying an all-blank statement that the filing never contained.
    basis_present = any(
        has_basis(r) for r in rows if (r.get("canonical_key") or "").startswith(f"{prefix}_")
    )

    out: list[dict] = []
    seen: set[str] = set()
    stmt = next((s for s in (template_def or {}).get("statements", [])
                 if s.get("type") == statement_type), None)
    def emit(key: str, label: str, kind: str) -> None:
        seen.add(key)
        group = [r for r in by_key.get(key, []) if has_basis(r)]
        out.append(item_row(key, label, group, kind) if group
                   else blank_row(key, label, kind))

    if stmt and basis_present:
        for sec in stmt.get("sections") or []:
            children = [c for c in sec.get("children") or [] if c.get("canonical_key")]
            if not children:
                # A statement-level total — gross profit, profit before tax, total assets, net
                # assets, closing cash — is declared as a section with no children of its own.
                # These were being skipped, which left a P&L with no "Profit for the year" on it:
                # exactly the calculated lines a reader looks for first. They are single rows.
                if sec.get("canonical_key"):
                    emit(sec["canonical_key"], _loc(sec, locale), _kind_for(sec.get("role")))
                continue
            # Show every section and every template line (extracted or not) so the whole
            # template is represented, not only the lines that happened to be extracted.
            out.append({"id": f"sec_{sec.get('node_id', '')}", "label": _loc(sec, locale),
                        "kind": "section", "v1": None, "v2": None})
            for c in children:
                emit(c["canonical_key"], _loc(c, locale), _kind_for(c.get("role")))

    # Concepts this statement extracted that the template has no node for — shown so a mapped
    # figure is never invisible just because the template skeleton omits its line.
    extra: dict[str, list[dict]] = {}
    for r in rows:
        k = r.get("canonical_key") or ""
        if k.startswith(f"{prefix}_") and k not in seen and has_basis(r):
            extra.setdefault(k, []).append(r)
    if extra:
        out.append({"id": "sec_other", "label": _t("Other extracted items", locale),
                    "kind": "section", "v1": None, "v2": None})
        for k, group in extra.items():
            out.append(item_row(k, group[0].get("source_label", ""), group))

    # Face-line containment netting: reduce a target line by the lines already included in it
    # (e.g. cost of sales inclusive of admin / S&M), showing the net value + formula. Signed and
    # non-destructive — the raw figure is preserved in the inspector for audit.
    if netting_rules:
        from app.services.netting import compute_netting

        net_cur = compute_netting(rows, netting_rules, basis=basis, period="current")
        net_prior = compute_netting(rows, netting_rules, basis=basis, period="prior")
        for r in out:
            if r.get("kind") != "item":
                continue
            # A figure the analyst typed is the answer for that line; an automatic restatement
            # must not quietly overwrite it.
            if r.get("status") == "edited":
                continue
            nc, np = net_cur.get(r["id"]), net_prior.get(r["id"])
            if not nc and not np:
                continue
            info = nc or np
            if nc:
                r["v1"] = _to_num(nc["net"])
            if np:
                r["v2"] = _to_num(np["net"])
            r["formula"] = info["formula"]
            r["status"] = "recon"
            raw = info["raw"]
            note = info.get("label") or _t("Contained lines netted out.", locale)
            r["inspector"] = {"tag": "netted", "src": (r.get("inspector") or {}).get("src", ""),
                              "formula": info["formula"], "result": info["net"],
                              "note": f"{note} {_t('Raw', locale)}: {raw}."}

    basis_label = _BASIS_LABEL_I18N.get(basis, {}).get(locale, basis.title())
    return {
        "statement": statement_type,
        "label": _stmt_label(template_def, statement_type, locale),
        "basis": basis, "periods": _period_labels(rows, basis, locale),
        "currency": (units_ctx or {}).get("currency") or "",
        "currency_symbol": "", "units": (units_ctx or {}).get("units_label") or "",
        # The detected source magnitude (e.g. 1000 for "in thousands"); the Workspace units
        # selector converts relative to this so it never double-scales already-scaled figures.
        "units_scale_factor": _to_num((units_ctx or {}).get("scale_factor")) or 1.0,
        # Document shape so the Workspace picks the right live viewer (PDF pages vs Excel cells).
        "format": doc_format, "page_count": page_count,
        "rows": out,
        "viewer": {
            "company": company or filename, "subtitle": _t("Extracted statement", locale),
            "chips": [{"label": basis_label, "active": True}],
            "callout": _t("Values are read deterministically from the source; mapping is by the "
                          "ensemble. Open the extraction view for click-to-source provenance.",
                          locale),
        },
    }


@router.get("/{document_id}/statement", dependencies=[Depends(authorized_document)])
def get_document_statement(
    document_id: str,
    statement: str = Query("balance_sheet"),
    basis: str = Query("consolidated"),
    locale: str = Query("en"),
    session: Session = Depends(db),
) -> dict:
    """One statement of a document's real extraction, grouped for the Workspace grid,
    with labels resolved in the output `locale`."""
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
                            doc.filename or "document", basis, locale,
                            run.result.get("units"), company=run.result.get("entity"),
                            doc_format=run.result.get("format") or doc.fmt or "",
                            page_count=run.result.get("page_count") or doc.page_count or 0,
                            # Apply only the netting the LLM confirmed for this document (cached at
                            # extraction); the raw ontology policies are candidates, not results.
                            netting_rules=run.result.get("netting") or [])


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


def _note_row_kind(row: dict) -> str | None:
    """Map a note-detail row's role to the frontend's emphasis kind: 'tot' for a total,
    'sub' for a subtotal. Falls back to a label heuristic when the role is a plain line but
    the caption clearly reads as a total."""
    role = (row.get("role") or "line").lower()
    if role == "total":
        return "tot"
    if role == "subtotal":
        return "sub"
    if role == "line" and re.match(r"\s*(total|net\b)", (row.get("label") or "").lower()):
        return "tot"
    return None


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
    # An entry we could actually grade says more than an unconfirmed one, so prefer it; then
    # prefer the consolidated / current-period view.
    mine.sort(key=lambda e: (tie_status(e) == "unconfirmed",
                             e.get("basis") != "consolidated",
                             e.get("period_label") != "current"))
    e = mine[0]
    raw, sub, rec = e.get("raw_face"), e.get("subtracted"), e.get("reconciled")
    resid = e.get("residual")
    status = tie_status(e)
    parts: list[str] = []
    try:
        if abs(float(sub)) > 0:
            parts.append(
                f"Face figure {_fmt_amt(raw)} less {_fmt_amt(sub)} of note detail already "
                f"carried as separate line items → reconciled {_fmt_amt(rec)}.")
    except (TypeError, ValueError):
        pass
    if status == "tied":
        parts.append(f"The note total ties to the face figure (residual {_fmt_amt(resid)}).")
    elif status == "untied":
        parts.append(f"The note total does not tie to the face figure — residual {_fmt_amt(resid)} "
                     f"(flagged for review).")
    else:
        parts.append("This note is not a breakdown of the face figure it is cited from, so no "
                     "tie is asserted.")
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
            cur_v, prior_v = split_current_prior(row.get("values") or [])
            cur, prior = cur_v or {}, prior_v or {}
            detail_rows.append({
                "label": row.get("label", ""),
                "v1": _to_num(cur.get("value")) or 0,
                "v2": _to_num(prior.get("value")) or 0,
                # Role → emphasis (subtotal/total) and mapping confidence → a per-row badge,
                # so a real note detail shows the same role/confidence cues as the demo.
                **({"kind": _note_row_kind(row)} if _note_row_kind(row) else {}),
                **({"conf": _conf_cat(row.get("confidence"))[0]}
                   if isinstance(row.get("confidence"), (int, float)) else {}),
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
