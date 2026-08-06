import type { Locale } from "../../types";

export const review: Record<Locale, Record<string, string>> = {
  en: {
    "r.title": "Review queue",
    "r.subhead":
      "Items where automated checks — balance-sheet equality, section subtotals, sign logic and note reconciliation — did not pass. Resolve each before export.",
    "r.open": "open",
    "r.passed": "passed",
    "r.reconciliation": "RECONCILIATION",
    "r.suggestedFix": "SUGGESTED FIX",
    "r.applyFix": "Apply fix",
    "r.openInWorkspace": "Open in workspace",
    "r.acceptAsIs": "Accept as-is",
  },
  zh: {
    "r.title": "审核队列",
    "r.subhead":
      "自动检查未通过的项目——资产负债表平衡、分节小计、符号逻辑及附注核对。请在导出前逐项解决。",
    "r.open": "未解决",
    "r.passed": "已通过",
    "r.reconciliation": "核对",
    "r.suggestedFix": "建议修正",
    "r.applyFix": "应用修正",
    "r.openInWorkspace": "在工作区中打开",
    "r.acceptAsIs": "按原样接受",
  },
  ar: {
    "r.title": "قائمة المراجعة",
    "r.subhead":
      "البنود التي لم تجتز الفحوصات الآلية — توازن الميزانية العمومية، والمجاميع الفرعية للأقسام، ومنطق الإشارة، ومطابقة الإيضاحات. عالِج كل بند قبل التصدير.",
    "r.open": "مفتوح",
    "r.passed": "مجتاز",
    "r.reconciliation": "المطابقة",
    "r.suggestedFix": "التصحيح المقترح",
    "r.applyFix": "تطبيق التصحيح",
    "r.openInWorkspace": "فتح في مساحة العمل",
    "r.acceptAsIs": "القبول كما هو",
  },
  fr: {
    "r.title": "File de révision",
    "r.subhead":
      "Éléments pour lesquels les contrôles automatiques — équilibre du bilan, sous-totaux de section, logique des signes et rapprochement des notes — n'ont pas été validés. Résolvez chacun avant l'export.",
    "r.open": "ouverts",
    "r.passed": "validés",
    "r.reconciliation": "RAPPROCHEMENT",
    "r.suggestedFix": "CORRECTION SUGGÉRÉE",
    "r.applyFix": "Appliquer la correction",
    "r.openInWorkspace": "Ouvrir dans l'espace de travail",
    "r.acceptAsIs": "Accepter tel quel",
  },
};
