from django.core.management.base import BaseCommand
from viewflow.workflow.models import Task

# Map node (flow task) names to required groups
REQUIRED = {
    "rr_review":  "RR",
    "rc_review":  "RC",
    "ra_approval":"RA",
    "cro_approval":"CRO",
}

class Command(BaseCommand):
    help = "Unassign tasks owned by users not in the required group for that node"

    def handle(self, *args, **opts):
        # Only select_related valid FKs (no 'flow_task' here)
        qs = Task.objects.select_related("owner", "process")
        cleared = 0

        for t in qs.iterator():
            # In this Viewflow version, flow_task is NOT a relation; just access the attribute.
            flow_task = getattr(t, "flow_task", None)
            flow_task_name = getattr(flow_task, "name", "") if flow_task else ""

            required_group = REQUIRED.get(flow_task_name)
            if not required_group or t.owner is None:
                continue

            owner = t.owner
            owner_ok = owner.is_superuser or owner.groups.filter(name=required_group).exists()
            if not owner_ok:
                t.owner = None
                t.save(update_fields=["owner"])
                cleared += 1

        self.stdout.write(self.style.SUCCESS(f"Cleared owner on {cleared} task(s)."))
