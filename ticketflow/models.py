from django.conf import settings
from django.db import models, transaction
from viewflow.workflow.models import Process
from viewflow import jsonstore
from django.utils.text import slugify  # ##GRC RISK


from django.conf import settings
from django.db import models


class WorkflowRole(models.Model):
    """App-local workflow role (no dependency on Django groups)."""
    name = models.CharField(max_length=100, unique=True)   # e.g. "Risk Representative"
    code = models.CharField(max_length=20, unique=True)    # e.g. "RR"

    def __str__(self):
        return self.name


class UserWorkflowRole(models.Model):
    """Assign roles to users."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.ForeignKey('WorkflowRole', on_delete=models.CASCADE)

    class Meta:
        unique_together = (("user", "role"),)

    def __str__(self):
        return f"{self.user.username} → {self.role.name}"


class WorkflowTemplate(models.Model):
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class WorkflowStep(models.Model):
    template = models.ForeignKey('WorkflowTemplate', related_name='steps', on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    role = models.ForeignKey('WorkflowRole', null=True, blank=True, on_delete=models.SET_NULL)  # 👈 NEW
    form = models.ForeignKey("Form", null=True, blank=True, on_delete=models.SET_NULL)
    position = models.PositiveIntegerField(default=0)
    auto_claim = models.BooleanField(default=True)
    end_on_reject = models.BooleanField(default=False)

    def role_name(self):
        return self.role.name if self.role else ""

    def role_code(self):
        return self.role.code if self.role else ""

    def __str__(self):
        return f"{self.position}. {self.title}"


# Keep your existing Form, FormField, FormEntry, TicketProcess, etc. definitions
# untouched here.




# ------------ FORMS (dynamic; admin builds forms & fields) ------------
class Form(models.Model):
    name = models.CharField(max_length=200)
    notify_emails = models.TextField(
        blank=True,
        help_text="Comma-separated emails to notify when this form is submitted"
    )
    created = models.DateTimeField(auto_now_add=True)

    # Stable identifier (used by flows/links/exports)
    slug = models.SlugField(
        max_length=64,
        unique=True,
        null=True,           # allow NULL for backfill; you can make it non-null later
        blank=True,
        help_text="Stable identifier (e.g., 'risk', 'control'). Auto-filled from name if blank."
    )


    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)
            candidate = base or "form"
            i = 1
            while Form.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                i += 1
                candidate = f"{base}-{i}"
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class FormField(models.Model):
    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    FILE = "file"
    FIELD_TYPES = [
        (TEXT, "Text"),
        (TEXTAREA, "Long text"),
        (SELECT, "Drop-down"),
        (FILE, "File upload"),
    ]

    form = models.ForeignKey(Form, related_name="fields", on_delete=models.CASCADE)
    label = models.CharField(max_length=200)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default=TEXT)
    required = models.BooleanField(default=False)
    help_text = models.CharField(max_length=300, blank=True)
    choices = models.TextField(
        blank=True,
        help_text='For "Drop-down": write options separated by commas, e.g. "Low, Medium, High"'
    )
    max_length = models.PositiveIntegerField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.form.name} / {self.label}"


class FormEntry(models.Model):
    form = models.ForeignKey(Form, related_name="entries", on_delete=models.CASCADE)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Entry #{self.id} / {self.form.name}"


class FormEntryValue(models.Model):
    entry = models.ForeignKey(FormEntry, related_name="values", on_delete=models.CASCADE)
    field = models.ForeignKey(FormField, on_delete=models.CASCADE)
    value_text = models.TextField(blank=True)
    value_file = models.FileField(upload_to="form_uploads/", null=True, blank=True)

    def __str__(self):
        val = self.value_text or (self.value_file.name if self.value_file else "")
        return f"{self.field.label} = {val}"


# -------------------- PER-FORM COUNTER FOR FRIENDLY IDs --------------------
class FormCounter(models.Model):
    """
    Per-Form monotonically increasing counter used to generate friendly IDs like RISK-0001.
    """
    form = models.OneToOneField(Form, on_delete=models.CASCADE, related_name='counter')
    next_seq = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.form.name} counter @ {self.next_seq}"

    @staticmethod
    def get_and_increment(form: 'Form') -> int:
        # Lock row to avoid race conditions when multiple processes are created
        with transaction.atomic():
            counter, _ = FormCounter.objects.select_for_update().get_or_create(form=form)
            seq = counter.next_seq
            counter.next_seq = seq + 1
            counter.save(update_fields=['next_seq'])
            return seq


# ------------------------- VIEWFLOW PROCESS -------------------------
class TicketProcess(Process):
    form = models.ForeignKey(Form, on_delete=models.PROTECT)

    # Auto-generated human-readable reference (e.g., RISK-0001, CTRL-0001)
    ref_id = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        blank=True,
        null=True,
        help_text="Auto-generated reference like RISK-0001 or CTRL-0001"
    )

    # Human-readable snapshot of submitted data (for quick lookups)
    ticket_data = jsonstore.JSONField(default=dict)

    # decisions: "approved" / "rejected"
    user_decision = jsonstore.CharField(max_length=10, blank=True)
    dev_decision = jsonstore.CharField(max_length=10, blank=True)
    ba_decision = jsonstore.CharField(max_length=10, blank=True)
    pm_decision = jsonstore.CharField(max_length=10, blank=True)

    # who approved/rejected
    approved_by_user = jsonstore.CharField(max_length=100, blank=True)
    approved_by_dev = jsonstore.CharField(max_length=100, blank=True)
    approved_by_ba = jsonstore.CharField(max_length=100, blank=True)
    approved_by_pm = jsonstore.CharField(max_length=100, blank=True)

    # comments
    user_comment = jsonstore.TextField(blank=True)
    dev_comment = jsonstore.TextField(blank=True)
    ba_comment = jsonstore.TextField(blank=True)
    pm_comment = jsonstore.TextField(blank=True)

    def __str__(self):
        return f"{self.ref_id or 'UNSET'} for {self.form.name}"

    # ---- ID generation helpers ----
    @staticmethod
    def _prefix_for_form(form: Form) -> str:
        """
        Decide prefix based on form slug/name. Extend mapping as needed.
        """
        slug = getattr(form, 'slug', None) or slugify(form.name or '') or 'form'
        s = slug.lower()
        if s.startswith('risk'):
            return 'RISK'
        if s.startswith('control') or s.startswith('ctrl'):
            return 'CTRL'
        # fallback: first 4 letters uppercased
        return (s[:4] or 'FORM').upper()

    @classmethod
    def _generate_ref_id(cls, form: Form) -> str:
        prefix = cls._prefix_for_form(form)
        seq = FormCounter.get_and_increment(form)
        return f"{prefix}-{seq:04d}"

    def save(self, *args, **kwargs):
        # ensure ref_id only set on first save, once form is attached
        if not self.ref_id and self.form_id:
            self.ref_id = self._generate_ref_id(self.form)
        super().save(*args, **kwargs)


# ---------------------- DYNAMIC WORKFLOW (admin-driven) ----------------------

class ProcessStepLog(models.Model):
    process = models.ForeignKey("ticketflow.TicketProcess", on_delete=models.CASCADE, related_name="step_logs")
    template = models.ForeignKey(WorkflowTemplate, on_delete=models.SET_NULL, null=True)
    step = models.ForeignKey(WorkflowStep, on_delete=models.SET_NULL, null=True)
    index = models.PositiveIntegerField()
    acted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    acted_at = models.DateTimeField(auto_now_add=True)
    decision = models.CharField(max_length=20, blank=True)  # "approved"/"rejected"/"sent_back"
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["process_id", "index", "acted_at"]

    def __str__(self):
        return f"{self.process_id} #{self.index} {self.decision}"


class DynamicTicketProcess(models.Model):
    form = models.ForeignKey(Form, on_delete=models.PROTECT)

    ref_id = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        blank=True,
        null=True,
        help_text="Auto-generated reference like RISK-0001 or CTRL-0001"
    )

    ticket_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.ref_id or 'UNSET'} for {self.form.name}"

    # ---- ID generation helpers ----
    @staticmethod
    def _prefix_for_form(form: Form) -> str:
        slug = getattr(form, 'slug', None) or slugify(form.name or '') or 'form'
        s = slug.lower()
        if s.startswith('risk'):
            return 'RISK'
        if s.startswith('control') or s.startswith('ctrl'):
            return 'CTRL'
        return (s[:4] or 'FORM').upper()

    @classmethod
    def _generate_ref_id(cls, form: Form) -> str:
        prefix = cls._prefix_for_form(form)
        seq = FormCounter.get_and_increment(form)
        return f"{prefix}-{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.ref_id and self.form_id:
            self.ref_id = self._generate_ref_id(self.form)
        super().save(*args, **kwargs)