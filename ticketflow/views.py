from django import forms
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView
from django.db.models import TextChoices
from django.contrib import messages

from viewflow.workflow.flow.views import CreateProcessView, UpdateProcessView

from .models import (
    TicketProcess,
    DynamicTicketProcess,
    Form as FormModel,
    FormEntry,
    FormEntryValue,
    FormField,
    # NEW:
    WorkflowTemplate, WorkflowStep, ProcessStepLog,
    WorkflowStep, UserWorkflowRole,
    Form as FormModel, FormField, FormEntry, FormEntryValue
)
from .forms import add_fields_to_form, ApprovalForm

from django.views.generic.edit import UpdateView
from django.views.generic.edit import FormView
from django.urls import reverse

# from .utils import _ensure_ticket_data, _user_has_role, _required_role_name, add_fields_to_form  # adjust if you keep 

import csv

# ============== Helpers & Role metadata ==============

ROLE_LABELS = {
    "RR":  ("Risk Representative Decision", "Risk Representative Comment"),
    "RC":  ("Risk Champion Decision",       "Risk Champion Comment"),
    "RA":  ("Risk Approver Decision",       "Risk Approver Comment"),
    "CRO": ("CRO Decision",                 "CRO Comment"),
}
# ROLE_GROUP = {"RR": "RR", "RC": "RC", "RA": "RA", "CRO": "CRO"}
# Map codes to actual Django group names
ROLE_GROUP = {
    "RR": "Risk Representative",
    "RC": "Risk Champion",
    "RA": "Risk Approver",
    "CRO": "CRO",
}

def snapshot_get(proc: TicketProcess, label: str, default: str = ""):
    snap = proc.ticket_data or {}
    return snap.get(label, snap.get(label.strip(), default))

# ============== Dynamic Start Views ==============
class DynamicStartView(CreateProcessView):
    model = TicketProcess
    fields = []
    preselect_form_slug = None
    preselect_form_name = None

    def get_form_object(self):
        qs = FormModel.objects.all()
        if getattr(self, "preselect_form_slug", None):
            try:
                return qs.get(slug=self.preselect_form_slug)
            except FormModel.DoesNotExist:
                pass
        if getattr(self, "preselect_form_name", None):
            try:
                return qs.get(name=self.preselect_form_name)
            except FormModel.DoesNotExist:
                pass
        return qs.first()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form_obj = self.get_form_object()
        add_fields_to_form(form, form_obj)
        return form

    def form_valid(self, form):
        form_obj = self.get_form_object()
        self.object = form.save(commit=False)
        self.object.form = form_obj
        self.object.save()
        return super().form_valid(form)

class SelectableDynamicStartView(CreateProcessView):
    model = TicketProcess
    fields = []

    def _selected_form_from_request(self):
        form_id = self.request.POST.get('selected_form_id') or self.request.GET.get('selected_form_id')
        if form_id:
            try:
                return FormModel.objects.get(pk=form_id)
            except FormModel.DoesNotExist:
                return None
        return None

    def get_form_object(self):
        picked = self._selected_form_from_request()
        if picked:
            return picked
        return FormModel.objects.first()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        choices = [(str(f.pk), f.name) for f in FormModel.objects.all().order_by('name')]
        form.fields['selected_form_id'] = forms.ChoiceField(label="Select Form", choices=choices, required=True)
        current = self.get_form_object()
        if current:
            form.fields['selected_form_id'].initial = str(current.pk)
            add_fields_to_form(form, current)
        return form

    def form_valid(self, form):
        selected_id = form.cleaned_data.get('selected_form_id')
        form_obj = get_object_or_404(FormModel, pk=selected_id)
        self.object = form.save(commit=False)
        self.object.form = form_obj
        self.object.save()

        process = self.object
        entry = FormEntry.objects.create(
            form=form_obj,
            submitted_by=self.request.user if self.request.user.is_authenticated else None
        )
        snapshot = {}
        for ff in form_obj.fields.all():
            key = str(ff.id)
            if ff.field_type == FormField.FILE:
                fobj = self.request.FILES.get(key)
                if fobj:
                    FormEntryValue.objects.create(entry=entry, field=ff, value_file=fobj)
                    snapshot[ff.label] = getattr(fobj, "name", "uploaded-file")
            else:
                text_val = self.request.POST.get(key, "")
                FormEntryValue.objects.create(entry=entry, field=ff, value_text=str(text_val))
                snapshot[ff.label] = text_val

        process.ticket_data = snapshot
        process.save()
        send_submission_emails(process)

        return super().form_valid(form)

class RiskDynamicStartView(DynamicStartView):
    def form_valid(self, form):
        form_obj = self.get_form_object()
        self.object = form.save(commit=False)
        self.object.form = form_obj
        self.object.save()

        process = self.object
        entry = FormEntry.objects.create(
            form=form_obj,
            submitted_by=self.request.user if self.request.user.is_authenticated else None
        )
        snapshot = {}
        for ff in form_obj.fields.all():
            key = str(ff.id)
            if ff.field_type == FormField.FILE:
                fobj = self.request.FILES.get(key)
                if fobj:
                    FormEntryValue.objects.create(entry=entry, field=ff, value_file=fobj)
                    snapshot[ff.label] = getattr(fobj, "name", "uploaded-file")
            else:
                text_val = self.request.POST.get(key, "")
                FormEntryValue.objects.create(entry=entry, field=ff, value_text=str(text_val))
                snapshot[ff.label] = text_val

        process.ticket_data = snapshot
        process.save()
        send_submission_emails(process)

        return super().form_valid(form)

# ============== Legacy helper (used by legacy flow) ==============
def create_entry_and_snapshot(process: TicketProcess, activation=None):
    req = getattr(activation, "request", None)
    form_obj = process.form
    entry = FormEntry.objects.create(
        form=form_obj,
        submitted_by=req.user if (req and req.user.is_authenticated) else None
    )
    snapshot = {}
    for ff in form_obj.fields.all():
        key = str(ff.id)
        if ff.field_type == FormField.FILE:
            fobj = req.FILES.get(key) if req else None
            if fobj:
                FormEntryValue.objects.create(entry=entry, field=ff, value_file=fobj)
                snapshot[ff.label] = getattr(fobj, "name", "uploaded-file")
        else:
            text_val = req.POST.get(key, "") if req else ""
            FormEntryValue.objects.create(entry=entry, field=ff, value_text=str(text_val))
            snapshot[ff.label] = text_val
    return entry, snapshot

def send_submission_emails(process: TicketProcess):
    form_obj = process.form
    emails = [e.strip() for e in (form_obj.notify_emails or "").split(",") if e.strip()]
    if not emails:
        return
    subject = f"New submission for: {form_obj.name}"
    lines = [f"Ref: {process.ref_id}"] + [f"{k}: {v}" for k, v in (process.ticket_data or {}).items()]
    body = "\n".join(lines)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipient_list=emails, fail_silently=True)

# ============== Approval View with strict role gating + auto-claim ==============
class ApprovalView(UpdateView):
    """
    Legacy approval view refactored: no Viewflow activation, no Process writes.
    Use only if you want static roles on TicketProcess.
    """
    model = TicketProcess
    form_class = ApprovalForm
    role = None  # "RR" | "RC" | "RA" | "CRO"

    ROLE_MAP = {
        "RR":  ("user_decision", "approved_by_user", "user_comment"),
        "RC":  ("dev_decision",  "approved_by_dev",  "dev_comment"),
        "RA":  ("ba_decision",   "approved_by_ba",   "ba_comment"),
        "CRO": ("pm_decision",   "approved_by_pm",   "pm_comment"),
    }

    def dispatch(self, request, *args, **kwargs):
        group_needed = ROLE_GROUP.get(self.role)
        if group_needed and not (
            request.user.is_superuser or request.user.groups.filter(name=group_needed).exists()
        ):
            raise PermissionDenied(f"You must be in group '{group_needed}' to perform this action.")
        return super().dispatch(request, *args, **kwargs)

    def _auto_claim(self, request):
        try:
            activation = getattr(self, "activation", None)
            task = getattr(activation, "task", None) if activation else None
            if not task:
                return
            group_needed = ROLE_GROUP.get(self.role)
            user_in_group = request.user.is_superuser or request.user.groups.filter(name=group_needed).exists()
            if not user_in_group:
                return
            owner = getattr(task, "owner", None)
            if owner is None:
                activation.assign(request.user);  return
            owner_in_group = owner.is_superuser or owner.groups.filter(name=group_needed).exists()
            if not owner_in_group:
                activation.assign(request.user);  return
        except Exception:
            pass  # non-fatal

    def get(self, request, *args, **kwargs):
        self._auto_claim(request)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self._auto_claim(request)
        return super().post(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        decision_label, comment_label = ROLE_LABELS.get(self.role, ("Decision", "Comment"))
        form.fields['decision'].label = decision_label
        form.fields['comment'] = forms.CharField(
            label=comment_label, widget=forms.Textarea, required=False
        )
        return form

    def form_valid(self, form):
        decision_field, approver_field, comment_field = self.ROLE_MAP[self.role]
        proc: TicketProcess = self.object
        setattr(proc, decision_field, form.cleaned_data["decision"])
        setattr(proc, approver_field, self.request.user.get_username())
        setattr(proc, comment_field, form.cleaned_data.get("comment", ""))
        proc.save()
        return super().form_valid(form)

# ============== CSV EXPORTS ==============
def export_form_entries_csv(request, form_slug_or_id: str):
    try:
        form_obj = FormModel.objects.get(slug=form_slug_or_id)
    except FormModel.DoesNotExist:
        form_obj = get_object_or_404(FormModel, pk=form_slug_or_id)
    entries = (
        FormEntry.objects
        .filter(form=form_obj)
        .prefetch_related("values", "values__field", "submitted_by")
        .order_by("id")
    )
    headers = [ff.label for ff in form_obj.fields.all()]
    base_cols = ["Entry ID", "Submitted By", "Submitted At"]
    response = HttpResponse(content_type="text/csv")
    filename = (form_obj.slug or form_obj.name).replace(" ", "_")
    response["Content-Disposition"] = f'attachment; filename="{filename}_entries.csv"'
    writer = csv.writer(response)
    writer.writerow(base_cols + headers)
    for e in entries:
        value_map = {v.field.label: (v.value_text or (v.value_file.url if v.value_file else "")) for v in e.values.all()}
        row = [e.id, getattr(e.submitted_by, "username", "") or "", e.submitted_at.isoformat()] + [value_map.get(h, "") for h in headers]
        writer.writerow(row)
    return response

def export_process_csv(request, process_id: int):
    p = get_object_or_404(TicketProcess, pk=process_id)
    snapshot = p.ticket_data or {}
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="process_{p.id}.csv"'
    writer = csv.writer(response)
    keys = list(snapshot.keys())
    writer.writerow(keys)
    writer.writerow([snapshot.get(k, "") for k in keys])
    return response

# ============== Process Summary (nice labels) ==============
class ProcessSummaryView(DetailView):
    model = TicketProcess
    template_name = "ticketflow/process_summary.html"
    context_object_name = "object"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p: TicketProcess = ctx['object']
        ctx['snapshot'] = p.ticket_data or {}
        ctx['decisions'] = [
            ("Risk Representative", p.user_decision, p.approved_by_user, p.user_comment),
            ("Risk Champion",       p.dev_decision,  p.approved_by_dev,  p.dev_comment),
            ("Risk Approver",       p.ba_decision,   p.approved_by_ba,   p.ba_comment),
            ("CRO",                 p.pm_decision,   p.approved_by_pm,   p.pm_comment),
        ]
        # Also show DB workflow results if present
        wf_results = (p.ticket_data or {}).get("wf_results", [])
        ctx['wf_results'] = wf_results
        return ctx

# ===================== DB-DRIVEN WORKFLOW VIEWS =====================



# class ChooseWorkflowStartForm(forms.Form):
#     workflow = forms.ModelChoiceField(queryset=WorkflowTemplate.objects.filter(is_active=True))
#     form = forms.ModelChoiceField(queryset=FormModel.objects.all(), required=False)

class ChooseWorkflowStartForm(forms.Form):
    workflow = forms.ModelChoiceField(
        queryset=WorkflowTemplate.objects.filter(is_active=True),
        required=True,
        label="Workflow Template"
    )
    form = forms.ModelChoiceField(
        queryset=FormModel.objects.all(),
        required=True,   # 👈 make this required
        label="Form"
    )


class ChooseWorkflowStartView(FormView):
    template_name = "ticketflow/choose_workflow_start.html"
    form_class = ChooseWorkflowStartForm

    def form_valid(self, form):
        print("DEBUG cleaned_data:", form.cleaned_data)

        proc = DynamicTicketProcess.objects.create(
            form=form.cleaned_data["form"],
            ticket_data={
                "wf_id": form.cleaned_data["workflow"].id,
                "wf_step": 0,
                "wf_results": [],
            }
        )
        # ✅ redirect with pk (matches urls.py)
        return redirect(reverse("dbworkflow_step", kwargs={"pk": proc.pk}))


# ---------------------------
# Helpers
# ---------------------------

def _user_has_role(user, role_name: str) -> bool:
    """Check if a user has a given WorkflowRole by name."""
    if not role_name:
        return False
    return UserWorkflowRole.objects.filter(user=user, role__name=role_name).exists()


def _ensure_ticket_data(proc: TicketProcess):
    """Ensure ticket_data dict exists and has workflow keys."""
    data = getattr(proc, "ticket_data", None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("wf_id", None)
    data.setdefault("wf_step", 0)
    data.setdefault("wf_results", [])
    proc.ticket_data = data
    return data

def _required_role_name(step):
    """Return the role name required for a given step."""
    if step and step.role:
        return step.role.name
    return None

# ---------------------------
# Dynamic Approval Form
# ---------------------------

class ApprovalForm(forms.ModelForm):
    """Form for workflow step execution. ModelForm wrapper fixes `instance` errors."""
    DECISIONS = (("approved", "Approved"), ("rejected", "Rejected"))
    decision = forms.ChoiceField(choices=DECISIONS)
    comment = forms.CharField(widget=forms.Textarea, required=False)

    class Meta:
        model = TicketProcess
        fields = []   # 👈 no actual model fields are bound



def add_fields_to_form(form, dynamic_form: FormModel):
    """Attach FormFields (from Admin-defined Form) into a Django form instance."""
    for ff in dynamic_form.fields.all().order_by("order", "id"):
        key = str(ff.id)
        if ff.field_type == FormField.TEXT:
            form.fields[key] = forms.CharField(
                label=ff.label, required=ff.required, help_text=ff.help_text
            )
        elif ff.field_type == FormField.TEXTAREA:
            form.fields[key] = forms.CharField(
                label=ff.label, widget=forms.Textarea, required=ff.required, help_text=ff.help_text
            )
        elif ff.field_type == FormField.SELECT:
            choices = [(c.strip(), c.strip()) for c in (ff.choices or "").split(",") if c.strip()]
            form.fields[key] = forms.ChoiceField(
                label=ff.label, choices=choices, required=ff.required, help_text=ff.help_text
            )
        elif ff.field_type == FormField.FILE:
            form.fields[key] = forms.FileField(
                label=ff.label, required=ff.required, help_text=ff.help_text
            )


# ---------------------------
# DB Workflow Step Execution
# ---------------------------

class DBStepExecutionView(UpdateView):
    """
    Executes the current DB-defined step.
    Enforces access with WorkflowRoles (UserWorkflowRole), not Django Groups.
    """
    model = DynamicTicketProcess
    form_class = ApprovalForm
    template_name = "ticketflow/db_step.html"

    def get_object(self, queryset=None):
        return get_object_or_404(DynamicTicketProcess, pk=self.kwargs.get("pk"))

    def _current_step(self) -> WorkflowStep:
        """Locate the current step from wf_id + wf_step index in ticket_data."""
        p: DynamicTicketProcess = self.object
        data = _ensure_ticket_data(p)

        wf_id = data.get("wf_id")
        if not wf_id:
            raise PermissionDenied("No workflow selected for this process.")

        step = WorkflowStep.objects.filter(
            template_id=wf_id,
            position=data.get("wf_step", 0)
        ).first()

        if not step:
            raise PermissionDenied("No workflow step found for this process.")
        return step

    # ---------------------------
    # Role check
    # ---------------------------
    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        step = self._current_step()
        role_name = _required_role_name(step)

        # Debug info
        print(f"DEBUG dispatch: wf_id={self.object.ticket_data.get('wf_id')}, "
              f"step={self.object.ticket_data.get('wf_step')}, "
              f"user={request.user.username}, "
              f"role_required={role_name}")

        if not (request.user.is_superuser or _user_has_role(request.user, role_name)):
            raise PermissionDenied(f"You must have role '{role_name or '<<unset>>'}' to act on this step.")

        return super().dispatch(request, *args, **kwargs)

    # ---------------------------
    # Dynamic form rendering
    # ---------------------------
    ROLE_LABELS = {
        "RR": ("Risk Representative Decision", "Risk Representative Comment"),
        "RC": ("Risk Champion Decision", "Risk Champion Comment"),
        "RA": ("Risk Approver Decision", "Risk Approver Comment"),
        "CRO": ("CRO Decision", "CRO Comment"),
    }

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        step = self._current_step()

        # Adapt labels by role
        decision_label, comment_label = self.ROLE_LABELS.get(
            step.role_code(), ("Decision", "Comment")
        )
        form.fields["decision"].label = decision_label
        form.fields["comment"] = forms.CharField(
            label=comment_label, widget=forms.Textarea, required=False
        )

        # Add dynamic fields if step has a form
        bound_form = step.form or self.object.form
        if bound_form:
            add_fields_to_form(form, bound_form)

        return form

    # ---------------------------
    # Save decision + form values
    # ---------------------------
    def form_valid(self, form):
        p: DynamicTicketProcess = self.object
        data = _ensure_ticket_data(p)
        step = self._current_step()

        decision = form.cleaned_data.get("decision")
        comment = form.cleaned_data.get("comment")

        # If this step has a form, persist answers into FormEntry/FormEntryValue
        chosen_form = step.form or p.form
        if chosen_form:
            entry = FormEntry.objects.create(
                form=chosen_form,
                submitted_by=self.request.user if self.request.user.is_authenticated else None
            )
            req = self.request
            for ff in chosen_form.fields.all().order_by("order", "id"):
                key = str(ff.id)
                if ff.field_type == FormField.FILE:
                    fobj = req.FILES.get(key)
                    if fobj:
                        FormEntryValue.objects.create(entry=entry, field=ff, value_file=fobj)
                else:
                    val = req.POST.get(key, "")
                    FormEntryValue.objects.create(entry=entry, field=ff, value_text=str(val))

        # Record result into ticket_data
        result = {
            "step": step.title,
            "role": step.role.name if step.role else None,
            "decision": decision,
            "comment": comment,
            "by": self.request.user.username,
        }
        data.setdefault("wf_results", []).append(result)

        # Advance workflow pointer
        data["wf_step"] = step.position + 1
        p.ticket_data = data
        p.save()

        messages.success(self.request, f"Step '{step.title}' completed. Assigned to {step.role.name if step.role else 'next role'}.")

        # Redirect user back to process dashboard instead of next step
        # return redirect("/dbworkflow/")  # or your dashboard route
        return redirect("dbworkflow_dashboard") # enroute to dahboard

        # return redirect(reverse("dbworkflow_step", kwargs={"pk": p.pk})) # it will directly redirect to next role by giving erro

    # ---------------------------
    # Extra context for template
    # ---------------------------
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        step = self._current_step()
        ctx["required_role"] = step.role_name()
        ctx["workflow_step"] = step
        return ctx

# ---------------------------
# DB Workflow Dashboard (User-specific tasks)
# ---------------------------

from django.views.generic import TemplateView

def _process_visible_to_user(process, user):
    """
    Returns (visible, step, status) for the given process.
    - visible = True if user can act OR process is completed.
    - step = current WorkflowStep (or None if completed).
    - status = Pending / In Progress / Completed
    """
    data = process.ticket_data or {}
    wf_id = data.get("wf_id")
    step_index = data.get("wf_step", 0)

    if wf_id is None:
        return False, None, "Pending"

    step = WorkflowStep.objects.filter(template_id=wf_id, position=step_index).first()

    # Status logic
    if not step:  # No further steps
        return True, None, "Completed"

    required_role = step.role.name if step.role else None
    can_act = _user_has_role(user, required_role)

    # If user can act → show; If completed → show anyway
    if can_act:
        return True, step, "In Progress"
    return False, None, "In Progress"



class DBWorkflowDashboardView(TemplateView):
    template_name = "ticketflow/db_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filter_mode = self.request.GET.get("filter", "active")  # default = active
        processes_data = []

        for p in DynamicTicketProcess.objects.all():
            visible, step, status = _process_visible_to_user(p, self.request.user)
            data = p.ticket_data or {}
            history = data.get("wf_results", [])

            if visible:
                # If filtering
                if filter_mode == "completed" and status != "Completed":
                    continue
                if filter_mode == "active" and status == "Completed":
                    continue

                processes_data.append({
                    "process": p,
                    "step": step,
                    "required_role": step.role.name if step and step.role else "Unassigned",
                    "history": history,
                    "status": status,
                })

        ctx["processes"] = processes_data
        ctx["filter_mode"] = filter_mode
        return ctx

