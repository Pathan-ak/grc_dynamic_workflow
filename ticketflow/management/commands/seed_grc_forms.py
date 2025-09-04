from django.core.management.base import BaseCommand
from django.db import transaction
from ticketflow.models import Form as FormModel, FormField

RISK_FIELDS = [
    # (label, type, required, help_text, choices)
    ("Risk ID", "text", True, "e.g., RISK-2025-0001 (or auto)", ""),
    ("Business Unit", "select", True, "Select BU", "Agency,Applied Intelligence,Board Secretariat,Branch Services,Business Excellence,Business Office,Compliance,Consumer GI Operations,Contact Centre,Corporate Affairs,Customer Care Shared Services,Customer Engagement,Data Analytics,Digital Office,Distribution Middle Office,Technology Services"),
    ("Level 1 Risk Category", "select", True, "Top level risk class",
     "Legal, Regulatory & Reputational Risk,Operational Risk,Sustainability Risk,Technology Risk"),
    ("Level 2 Risk Type", "select", True, "Filtered by Level 1",
     "Communication & Brand,Corporate Governance,Financial Crime,Business Continuity,Claims,Data Governance,Underwriting,Environmental,Governance,Social,Cyber Security"),
    ("Risk Description", "textarea", True, "", ""),
    ("Impact Rating", "select", True, "", "Very Significant,Significant,Moderate,Minor"),
    ("Impact Rating Justification", "textarea", False, "", ""),
    ("Likelihood Rating", "select", True, "", "Very Likely,Likely,Possible,Rare"),
    ("Likelihood Rating Justification", "textarea", False, "", ""),
    # Calculated placeholders (kept visible for now, could be read-only in UI)
    ("Inherent Risk Level (calculated)", "text", False, "Filled by rule/script", ""),
    ("Residual Risk Level (calculated)", "text", False, "Filled by rule/script", ""),
    ("Overall Control Effectiveness (calculated)", "text", False, "Filled by rule/script", ""),
    # Stakeholders (user lookups can be ‘text’ for now; later can integrate user picker)
    ("Risk Owner", "text", False, "User name/email", ""),
    ("Risk Representative (RR)", "text", False, "Auto by BU or choose", ""),
    ("Risk Champion (RC)", "text", False, "", ""),
    ("Risk Approver (RA)", "text", False, "", ""),
    ("CRO", "text", False, "", ""),
    ("Attachments", "file", False, "", ""),
]

CONTROL_FIELDS = [
    ("Control ID", "text", True, "e.g., CTRL-2025-0001", ""),
    ("Control Factor", "select", True, "", "Approval Process & Authorization Limits,Audit/Self-Assessment,System Access/ Controls"),
    ("Sub-Control Factor", "select", True, "Filtered by Control Factor",
     "Review of legal documents by Legal Team.,2nd level review of scanned documents is done by another staff.(1),Ad-hoc cash count to verify completeness and accuracy of cash recording,Ad-hoc mystery shopping to audit sales quality, product brochures, etc,Privileged Access Management Solution have been implemented,Privileged accounts are managed via privileged account management system,Remote Access,User Access Review is performed on a half yearly basis,Vendor shall access environment via VDI"),
    ("Control Description", "textarea", True, "", ""),
    ("Control Frequency", "select", False, "", "Daily,Weekly,Monthly,Quarterly,Half Yearly,Yearly"),
    ("Control Owner", "text", False, "User name/email", ""),
    # Effectiveness inputs
    ("Control Operating Effectively", "select", False, "", "Yes,Needs minor improvement,Needs improvement,No,N/A"),
    ("Number of Samples Tested", "text", False, "Numeric", ""),
    ("Number of Samples where Objective is met", "text", False, "Numeric", ""),
    ("Control documentation and up-to-date", "select", False, "", "Yes,Needs minor improvement,Needs improvement,No,N/A"),
    ("Number of Samples Tested (Doc)", "text", False, "Numeric", ""),
    ("Number of Samples met (Doc)", "text", False, "Numeric", ""),
    ("Attachments", "file", False, "", ""),
]

TYPE_MAP = {"text":"text", "textarea":"textarea", "select":"select", "file":"file"}

class Command(BaseCommand):
    help = "Seeds/updates dynamic Risk and Control forms & fields"

    @transaction.atomic
    def handle(self, *args, **kwargs):
        # Create or get the forms
        risk_form, _ = FormModel.objects.get_or_create(name="Risk", defaults={"slug": "risk"})
        control_form, _ = FormModel.objects.get_or_create(name="Control", defaults={"slug": "control"})

        # Wipe previous dynamic fields if needed (idempotent seed)
        risk_form.fields.all().delete()
        control_form.fields.all().delete()

        def add_fields(form_obj, rows):
            for order, (label, ftype, required, help_text, choices) in enumerate(rows, start=1):
                FormField.objects.create(
                    form=form_obj,
                    label=label,
                    field_type=TYPE_MAP[ftype],
                    required=required,
                    help_text=help_text or "",
                    choices=choices or "",
                    order=order
                )

        add_fields(risk_form, RISK_FIELDS)
        add_fields(control_form, CONTROL_FIELDS)

        self.stdout.write(self.style.SUCCESS("Seeded dynamic forms: Risk and Control"))
