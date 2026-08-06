/** Lightweight i18n for the app chrome (nav, stepper, workspace toolbar + headers).
 * Financial line-item labels are localized server-side (label_i18n + locale param).
 * The seed languages are English, Chinese, Arabic (RTL) and French — the set the
 * backend's /languages parity registry reports as fully supported. */
import type { Locale } from "./types";
import { useUI } from "./store";

export const RTL_LOCALES: Locale[] = ["ar"];
export const NATIVE_NAME: Record<Locale, string> = {
  en: "English",
  zh: "中文",
  ar: "العربية",
  fr: "Français",
};

type Dict = Record<string, string>;

const en: Dict = {
  "group.SETUP": "SETUP",
  "group.PRE-FLIGHT": "PRE-FLIGHT",
  "group.EXTRACT": "EXTRACT",
  "group.QUALITY": "QUALITY",
  "group.CONFIGURE": "CONFIGURE",
  "group.DELIVER": "DELIVER",
  "nav.upload": "Documents & Template",
  "nav.integrity": "Document Integrity",
  "nav.scope": "Page Scope",
  "nav.workspace": "Workspace",
  "nav.notes": "All Notes",
  "nav.review": "Review Queue",
  "nav.template": "Template & Ontology",
  "nav.export": "Export",
  "step.upload": "Upload",
  "step.integrity": "Integrity",
  "step.scope": "Scope",
  "step.workspace": "Extract",
  "step.review": "Review",
  "step.export": "Export",
  "progress.title": "Extraction progress",
  "ws.consolidated": "Consolidated",
  "ws.standalone": "Standalone",
  "ws.statement": "Statement",
  "ws.currency": "Currency",
  "ws.units": "Units",
  "ws.export": "Export",
  "ws.lowconf": "low-confidence",
  "ws.unreconciled": "unreconciled",
  "col.lineitem": "LINE ITEM",
  "col.note": "NOTE",
  "col.conf": "CONF.",
  "lang.label": "Language",
};

const zh: Dict = {
  "group.SETUP": "设置",
  "group.PRE-FLIGHT": "预检",
  "group.EXTRACT": "提取",
  "group.QUALITY": "质量",
  "group.CONFIGURE": "配置",
  "group.DELIVER": "交付",
  "nav.upload": "文档与模板",
  "nav.integrity": "文档完整性",
  "nav.scope": "页面范围",
  "nav.workspace": "工作区",
  "nav.notes": "所有附注",
  "nav.review": "审核队列",
  "nav.template": "模板与本体",
  "nav.export": "导出",
  "step.upload": "上传",
  "step.integrity": "完整性",
  "step.scope": "范围",
  "step.workspace": "提取",
  "step.review": "审核",
  "step.export": "导出",
  "progress.title": "提取进度",
  "ws.consolidated": "合并",
  "ws.standalone": "单体",
  "ws.statement": "报表",
  "ws.currency": "币种",
  "ws.units": "单位",
  "ws.export": "导出",
  "ws.lowconf": "低置信度",
  "ws.unreconciled": "未核对",
  "col.lineitem": "项目",
  "col.note": "附注",
  "col.conf": "置信度",
  "lang.label": "语言",
};

const ar: Dict = {
  "group.SETUP": "الإعداد",
  "group.PRE-FLIGHT": "الفحص المسبق",
  "group.EXTRACT": "الاستخراج",
  "group.QUALITY": "الجودة",
  "group.CONFIGURE": "التهيئة",
  "group.DELIVER": "التسليم",
  "nav.upload": "المستندات والقالب",
  "nav.integrity": "سلامة المستند",
  "nav.scope": "نطاق الصفحات",
  "nav.workspace": "مساحة العمل",
  "nav.notes": "كل الإيضاحات",
  "nav.review": "قائمة المراجعة",
  "nav.template": "القالب والأنطولوجيا",
  "nav.export": "تصدير",
  "step.upload": "رفع",
  "step.integrity": "السلامة",
  "step.scope": "النطاق",
  "step.workspace": "استخراج",
  "step.review": "مراجعة",
  "step.export": "تصدير",
  "progress.title": "تقدّم الاستخراج",
  "ws.consolidated": "موحّد",
  "ws.standalone": "منفصل",
  "ws.statement": "القائمة",
  "ws.currency": "العملة",
  "ws.units": "الوحدات",
  "ws.export": "تصدير",
  "ws.lowconf": "ثقة منخفضة",
  "ws.unreconciled": "غير مسوّى",
  "col.lineitem": "البند",
  "col.note": "إيضاح",
  "col.conf": "الثقة",
  "lang.label": "اللغة",
};

const fr: Dict = {
  "group.SETUP": "CONFIGURATION",
  "group.PRE-FLIGHT": "CONTRÔLE PRÉALABLE",
  "group.EXTRACT": "EXTRACTION",
  "group.QUALITY": "QUALITÉ",
  "group.CONFIGURE": "PARAMÉTRAGE",
  "group.DELIVER": "LIVRAISON",
  "nav.upload": "Documents et modèle",
  "nav.integrity": "Intégrité du document",
  "nav.scope": "Périmètre des pages",
  "nav.workspace": "Espace de travail",
  "nav.notes": "Toutes les notes",
  "nav.review": "File de révision",
  "nav.template": "Modèle et ontologie",
  "nav.export": "Exporter",
  "step.upload": "Importer",
  "step.integrity": "Intégrité",
  "step.scope": "Périmètre",
  "step.workspace": "Extraction",
  "step.review": "Révision",
  "step.export": "Export",
  "progress.title": "Progression de l'extraction",
  "ws.consolidated": "Consolidé",
  "ws.standalone": "Individuel",
  "ws.statement": "État",
  "ws.currency": "Devise",
  "ws.units": "Unités",
  "ws.export": "Exporter",
  "ws.lowconf": "confiance faible",
  "ws.unreconciled": "non rapproché",
  "col.lineitem": "POSTE",
  "col.note": "NOTE",
  "col.conf": "CONF.",
  "lang.label": "Langue",
};

const DICT: Record<Locale, Dict> = { en, zh, ar, fr };

export function translate(locale: Locale, key: string): string {
  return DICT[locale]?.[key] ?? DICT.en[key] ?? key;
}

/** Hook returning a translator bound to the current locale. */
export function useT(): (key: string) => string {
  const locale = useUI((s) => s.locale);
  return (key: string) => translate(locale, key);
}
