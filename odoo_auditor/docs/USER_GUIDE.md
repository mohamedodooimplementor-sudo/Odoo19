# Odoo Auditor - User Guide

## 1. First-time setup (5 minutes)
1. Give yourself the group **Odoo Auditor / Audit Manager** (Settings > Users).
2. Open **Odoo Auditor > Configuration > Quick Setup**, review the thresholds, choose a frequency, press **Apply**.
   Rules whose apps (Accounting, Sales, Purchase, Inventory, MRP, HR) are installed are activated.
3. For FIN009 (suspense balances) open the rule and put your account codes in *Extra parameters*, e.g. `{"codes": ["101404"]}`, then activate it.

## 2. Daily work
- **Dashboard**: open findings by severity and domain, overdue actions, latest runs. Click any card to drill down.
- **Findings** (kanban / list): Triage > Investigate > Request management response > Require action >
  Submit for verification > Close (manager). Use **Create Corrective Action** to assign work in one click.
- **Ignore in Future** (manager): rejects the finding with a documented reason and stops the same item being reported again.
  Archive the record in *Configuration > Exclusions* to make it reportable again.
- **Export to Excel**: select findings in the list > Action > Export to Excel, or use the button on an audit run.

## 3. Running audits
- *Audits > Run Audit*: choose company, period and rules. Keep **Run in background** on for large databases;
  the run form shows live progress.
- Scheduled rules run through the cron *Odoo Auditor: run scheduled rules*.

## 4. Important principles
- The module is read-only toward business data. It never posts, cancels, approves or edits your records.
- A finding is an indicator for human review, not a conclusion of fraud.
- HR / payroll findings are confidential; only the Confidential group sees them. No salary values are shown.

---

# دليل الاستخدام (ملخص)
1. أضف نفسك لمجموعة **Audit Manager**، ثم افتح **الإعدادات > Quick Setup** واضبط الحدود (مبالغ، أيام، نسب) واضغط **Apply**؛ بتتفعل القواعد اللي تطبيقاتها متثبتة.
2. **لوحة المعلومات**: ملخص الملاحظات المفتوحة بالخطورة والمجال، والإجراءات المتأخرة؛ اضغط على أي كارت للتفاصيل.
3. **الملاحظات**: فرز > تحقيق > طلب رد الإدارة > إجراء مطلوب > تحقق > إغلاق (المدير فقط). زر **Create Corrective Action** بيفتح إجراء تصحيحي جاهز.
4. **Ignore in Future**: بيرفض الملاحظة بسبب موثّق ويمنع تكرارها؛ لإعادة تفعيلها أرشف السجل من **Exclusions**.
5. **تشغيل المراجعة**: من *Run Audit*؛ خلّي "Run in background" شغال للقواعد الكبيرة وتابع التقدم من شاشة التشغيل.
6. التصدير لـ Excel من زر التشغيل أو من قائمة الملاحظات (Action > Export to Excel).
7. المديول للقراءة فقط: مبيرحّلش ولا بيلغي ولا بيعدّل أي مستند.
