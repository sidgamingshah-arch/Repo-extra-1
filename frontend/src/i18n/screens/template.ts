import type { Locale } from "../../types";

export const template: Record<Locale, Record<string, string>> = {
  en: {
    "tp.structure": "Template structure",
    "tp.lineItems": "line items",
    "tp.addLineItem": "+ Add line item",
    "tp.editorSubhead":
      "Ontology rules that tell the extractor which source descriptions map here, how to treat the sign, and how to net note detail against the face value.",
    "tp.viewOnly": "View only",
    "tp.viewOnlyHint":
      "The rules that map source descriptions here, treat the sign, and net note detail against the face value. Editing templates is an admin task — you can select which template a run uses on the Documents & Template screen.",
    "tp.emptyTitle": "No template loaded yet",
    "tp.emptyHint":
      "Start a project from the Documents & Template screen — upload a document and choose an output template. The chosen template's structure and rules will appear here.",
    "tp.aliases": "Description aliases",
    "tp.signConvention": "Sign convention",
    "tp.dataTypeUnits": "Data type & units",
    "tp.addAlias": "+ add alias",
    "tp.valueType": "Value type",
    "tp.aggregation": "Aggregation",
    "tp.nettingRule": "Note-to-face netting rule",
    "tp.key": "KEY",
    "tp.sign.asReported": "As reported (positive)",
    "tp.sign.expenseContra": "Expense / contra — negative",
    "tp.sign.auto": "Auto-detect from context",
  },
  zh: {
    "tp.structure": "模板结构",
    "tp.lineItems": "个项目",
    "tp.addLineItem": "+ 添加项目",
    "tp.editorSubhead":
      "本体规则告诉提取器哪些源描述映射到此处、如何处理正负号，以及如何将附注明细与账面金额进行净额抵销。",
    "tp.viewOnly": "仅查看",
    "tp.viewOnlyHint":
      "这些规则决定哪些源描述映射到此处、如何处理正负号，以及如何将附注明细与账面金额抵销。编辑模板属于管理员操作——您可在“文档与模板”页面选择某次运行使用的模板。",
    "tp.emptyTitle": "尚未加载模板",
    "tp.emptyHint":
      "请在“文档与模板”页面开始项目——上传文档并选择输出模板。所选模板的结构与规则将显示在此处。",
    "tp.aliases": "描述别名",
    "tp.signConvention": "正负号约定",
    "tp.dataTypeUnits": "数据类型与单位",
    "tp.addAlias": "+ 添加别名",
    "tp.valueType": "值类型",
    "tp.aggregation": "汇总方式",
    "tp.nettingRule": "附注与账面净额抵销规则",
    "tp.key": "关键",
    "tp.sign.asReported": "按列报（正值）",
    "tp.sign.expenseContra": "费用 / 抵减 — 负值",
    "tp.sign.auto": "根据上下文自动识别",
  },
  ar: {
    "tp.structure": "بنية القالب",
    "tp.lineItems": "بنود",
    "tp.addLineItem": "+ إضافة بند",
    "tp.editorSubhead":
      "قواعد الأنطولوجيا التي تحدد للمُستخرِج أي أوصاف المصدر تُربط هنا، وكيفية معالجة الإشارة، وكيفية تسوية تفاصيل الإيضاح مقابل القيمة الاسمية.",
    "tp.viewOnly": "عرض فقط",
    "tp.viewOnlyHint":
      "القواعد التي تحدد أي أوصاف المصدر تُربط هنا، وكيفية معالجة الإشارة، وتسوية تفاصيل الإيضاح مقابل القيمة الاسمية. تحرير القوالب مهمة للمسؤول — يمكنك اختيار القالب المستخدم في التشغيل من شاشة «المستندات والقالب».",
    "tp.emptyTitle": "لم يتم تحميل أي قالب بعد",
    "tp.emptyHint":
      "ابدأ مشروعًا من شاشة «المستندات والقالب» — ارفع مستندًا واختر قالب إخراج. ستظهر بنية القالب المختار وقواعده هنا.",
    "tp.aliases": "الأسماء البديلة للوصف",
    "tp.signConvention": "اصطلاح الإشارة",
    "tp.dataTypeUnits": "نوع البيانات والوحدات",
    "tp.addAlias": "+ إضافة اسم بديل",
    "tp.valueType": "نوع القيمة",
    "tp.aggregation": "التجميع",
    "tp.nettingRule": "قاعدة تسوية الإيضاح مقابل القيمة الاسمية",
    "tp.key": "أساسي",
    "tp.sign.asReported": "كما هو مُبلَّغ (موجب)",
    "tp.sign.expenseContra": "مصروف / مقابل — سالب",
    "tp.sign.auto": "كشف تلقائي من السياق",
  },
  fr: {
    "tp.structure": "Structure du modèle",
    "tp.lineItems": "postes",
    "tp.addLineItem": "+ Ajouter un poste",
    "tp.editorSubhead":
      "Règles d'ontologie qui indiquent à l'extracteur quelles descriptions sources correspondent ici, comment traiter le signe et comment compenser le détail des notes avec la valeur nominale.",
    "tp.viewOnly": "Lecture seule",
    "tp.viewOnlyHint":
      "Les règles qui associent les descriptions sources ici, traitent le signe et compensent le détail des notes avec la valeur nominale. La modification des modèles est réservée à l'administrateur — vous pouvez choisir le modèle utilisé pour une extraction sur l'écran Documents et modèle.",
    "tp.emptyTitle": "Aucun modèle chargé pour l'instant",
    "tp.emptyHint":
      "Démarrez un projet depuis l'écran Documents et modèle — téléversez un document et choisissez un modèle de sortie. La structure et les règles du modèle choisi apparaîtront ici.",
    "tp.aliases": "Alias de description",
    "tp.signConvention": "Convention de signe",
    "tp.dataTypeUnits": "Type de données et unités",
    "tp.addAlias": "+ ajouter un alias",
    "tp.valueType": "Type de valeur",
    "tp.aggregation": "Agrégation",
    "tp.nettingRule": "Règle de compensation note/valeur nominale",
    "tp.key": "CLÉ",
    "tp.sign.asReported": "Tel que déclaré (positif)",
    "tp.sign.expenseContra": "Charge / contrepartie — négatif",
    "tp.sign.auto": "Détection automatique selon le contexte",
  },
};
