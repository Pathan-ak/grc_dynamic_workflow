from django.conf import settings
from django.core.mail import send_mail

def _recipient_list(process):
    raw = (process.form.notify_emails or "").split(",")
    recips = [e.strip() for e in raw if e.strip()]
    return recips or ([getattr(settings, "DEFAULT_TO_EMAIL", "")] if getattr(settings, "DEFAULT_TO_EMAIL", "") else [])

def send_stage_email(process, stage_title: str, actor: str, decision: str, comment: str = ""):
    recips = _recipient_list(process)
    if not recips:
        return
    subject = f"[GRC] {stage_title}: {decision.upper()} — {process.form.name}"
    lines = [f"Stage: {stage_title}",
             f"Decision: {decision}",
             f"By: {actor}",
             ""]
    if comment:
        lines.append(f"Comment: {comment}")
        lines.append("")
    # include snapshot for quick context
    for k, v in (process.ticket_data or {}).items():
        lines.append(f"{k}: {v}")
    body = "\n".join(lines)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipient_list=recips, fail_silently=True)
