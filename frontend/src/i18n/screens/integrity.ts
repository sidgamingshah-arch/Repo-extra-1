import type { Locale } from "../../types";

export const integrity: Record<Locale, Record<string, string>> = {
  en: {
    "i.title": "Document integrity",
    "i.subhead":
      "Pre-flight scan run before extraction. Resolve blocking issues; warnings are logged against affected pages.",
    "i.col.issue": "ISSUE",
    "i.col.pages": "PAGES",
    "i.col.detail": "DETAIL",
    "i.col.status": "STATUS",
    "i.back": "Back",
    "i.detect": "Detect statement pages",
    "i.extractNow": "Extract now",
    "i.blocked": "Blocked — cannot extract",
    "i.failed": "Could not load integrity",
  },
  zh: {
    "i.title": "文档完整性",
    "i.subhead":
      "提取前运行的预检扫描。请解决阻断性问题；警告将记录在相关页面上。",
    "i.col.issue": "问题",
    "i.col.pages": "页码",
    "i.col.detail": "详情",
    "i.col.status": "状态",
    "i.back": "返回",
    "i.detect": "检测报表页面",
    "i.extractNow": "立即提取",
    "i.blocked": "已阻止 — 无法提取",
    "i.failed": "无法加载完整性检查",
  },
  ar: {
    "i.title": "سلامة المستند",
    "i.subhead":
      "فحص مسبق يُجرى قبل الاستخراج. عالج المشكلات الحاجبة؛ تُسجَّل التحذيرات مقابل الصفحات المتأثرة.",
    "i.col.issue": "المشكلة",
    "i.col.pages": "الصفحات",
    "i.col.detail": "التفاصيل",
    "i.col.status": "الحالة",
    "i.back": "رجوع",
    "i.detect": "اكتشاف صفحات القوائم",
    "i.extractNow": "استخرج الآن",
    "i.blocked": "محظور — لا يمكن الاستخراج",
    "i.failed": "تعذّر تحميل فحص السلامة",
  },
  fr: {
    "i.title": "Intégrité du document",
    "i.subhead":
      "Analyse de contrôle exécutée avant l'extraction. Résolvez les problèmes bloquants ; les avertissements sont consignés sur les pages concernées.",
    "i.col.issue": "PROBLÈME",
    "i.col.pages": "PAGES",
    "i.col.detail": "DÉTAIL",
    "i.col.status": "STATUT",
    "i.back": "Retour",
    "i.detect": "Détecter les pages d'états",
    "i.extractNow": "Extraire maintenant",
    "i.blocked": "Bloqué — extraction impossible",
    "i.failed": "Impossible de charger l'intégrité",
  },
};
