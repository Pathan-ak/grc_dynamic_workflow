# ticketflow/management/commands/grc_assign_perms.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# model labels to grant view perms for
MODELS_VIEW = [
    ("ticketflow", "form"),
    ("ticketflow", "formfield"),
    ("ticketflow", "formentry"),
    ("ticketflow", "formentryvalue"),
    # Optional, if you want Viewflow admin views:
    # ("workflow", "process"),
]

GROUPS = ["RR", "RC", "RA", "CRO"]

class Command(BaseCommand):
    help = "Grant baseline view-only perms to RR/RC/RA/CRO groups"

    def handle(self, *args, **kwargs):
        for gname in GROUPS:
            group, _ = Group.objects.get_or_create(name=gname)
            for app_label, model in MODELS_VIEW:
                ct = ContentType.objects.get(app_label=app_label, model=model)
                perm = Permission.objects.get(content_type=ct, codename=f"view_{model}")
                group.permissions.add(perm)
        self.stdout.write(self.style.SUCCESS("Granted baseline view-only perms to RR/RC/RA/CRO"))
