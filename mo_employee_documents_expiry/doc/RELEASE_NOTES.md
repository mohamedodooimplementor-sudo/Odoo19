## Module <employee_documents_expiry>

#### Version 18.0.1.1.0
#### ADD

- Staged reminders (default 60, 30, 7, 1, 0 days) instead of a daily email;
  the days can be set globally (Settings) or per document type.
- Odoo notifications: inbox (bell) message + "Document Expiry" activity on
  the document, for selected users (Notify Users) or by default the employee,
  his manager and HR managers.
- Expired notice repeated every X days (default 7).
- Status field (Valid / Expiring Soon / Expired), colors, filters, graph and
  pivot dashboard (menu "Documents Expiry").
- "Renew" button: creates the new document, archives the old one and closes
  its activities. Changing the expiry date also closes old activities.
- Weekly summary email for HR managers.
- Escalation to manager, department manager and HR managers.
- Editable bilingual (EN/AR) email template.

#### 16.01.2025
#### Version 18.0.1.0.0
#### ADD

- Initial commit for Employee Documents
