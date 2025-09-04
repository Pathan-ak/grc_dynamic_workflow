import csv
from io import StringIO
from django import forms
from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils.text import slugify
from openpyxl import Workbook

from .models import (
    Form, FormField, FormEntry, FormEntryValue, TicketProcess,
    WorkflowTemplate, WorkflowStep, ProcessStepLog,
    WorkflowRole, UserWorkflowRole, DynamicTicketProcess
)


# -------------------- ADMIN FORMS (shrink widgets) --------------------
class FormAdminForm(forms.ModelForm):
    class Meta:
        model = Form
        fields = "__all__"
        widgets = {"notify_emails": forms.TextInput(attrs={"size": 40})}

class FormFieldInlineForm(forms.ModelForm):
    class Meta:
        model = FormField
        fields = "__all__"
        widgets = {"choices": forms.TextInput(attrs={"size": 40})}

# -------------------- INLINE FIELDS UNDER FORM --------------------
class FormFieldInline(admin.TabularInline):
    model = FormField
    form = FormFieldInlineForm
    extra = 1
    fields = ("order", "label", "field_type", "required", "max_length", "choices", "help_text")

@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    form = FormAdminForm
    list_display = ("name", "created")
    inlines = [FormFieldInline]

# -------------------- EXPORT HELPERS --------------------
def _ensure_single_form_or_error(modeladmin, request, queryset):
    form_ids = set(queryset.values_list("form_id", flat=True))
    if len(form_ids) != 1:
        modeladmin.message_user(
            request,
            "Please filter to ONE Form (use the right-side filter), then select entries to export.",
            level=messages.ERROR,
        )
        return None
    return queryset.first().form

def export_entries_csv(modeladmin, request, queryset):
    form = _ensure_single_form_or_error(modeladmin, request, queryset)
    if not form:
        return
    fields = list(form.fields.all())
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{slugify(form.name)}_entries.csv"'
    writer = csv.writer(response)
    header = ["Entry ID", "Submitted by", "Submitted at"] + [f.label for f in fields]
    writer.writerow(header)
    for entry in queryset.select_related("form", "submitted_by").prefetch_related("values", "values__field").order_by("id"):
        values_map = {v.field_id: (v.value_text or (v.value_file.url if v.value_file else "")) for v in entry.values.all()}
        row = [
            entry.id,
            getattr(entry.submitted_by, "username", "") or "",
            entry.submitted_at.strftime("%Y-%m-%d %H:%M"),
        ] + [values_map.get(f.id, "") for f in fields]
        writer.writerow(row)
    return response
export_entries_csv.short_description = "Export selected to CSV"

def export_entries_xlsx(modeladmin, request, queryset):
    form = _ensure_single_form_or_error(modeladmin, request, queryset)
    if not form:
        return
    fields = list(form.fields.all())
    wb = Workbook()
    ws = wb.active
    ws.title = "Entries"
    header = ["Entry ID", "Submitted by", "Submitted at"] + [f.label for f in fields]
    ws.append(header)
    for entry in queryset.select_related("form", "submitted_by").prefetch_related("values", "values__field").order_by("id"):
        values_map = {v.field_id: (v.value_text or (v.value_file.url if v.value_file else "")) for v in entry.values.all()}
        row = [
            entry.id,
            getattr(entry.submitted_by, "username", "") or "",
            entry.submitted_at.strftime("%Y-%m-%d %H:%M"),
        ] + [values_map.get(f.id, "") for f in fields]
        ws.append(row)
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{slugify(form.name)}_entries.xlsx"'
    wb.save(response)
    return response
export_entries_xlsx.short_description = "Export selected to XLSX"

@admin.register(FormEntry)
class FormEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "form", "submitted_by", "submitted_at")
    list_filter = ("form", "submitted_at")
    date_hierarchy = "submitted_at"
    actions = [export_entries_csv, export_entries_xlsx]

@admin.register(TicketProcess)
class TicketProcessAdmin(admin.ModelAdmin):
    readonly_fields = (
        "ticket_data",
        "approved_by_user", "approved_by_dev", "approved_by_ba", "approved_by_pm",
        "user_comment", "dev_comment", "ba_comment", "pm_comment",
        "user_decision", "dev_decision", "ba_decision", "pm_decision",
    )
    list_display = ("id", "ref_id", "form")

# -------------------- WORKFLOW BUILDER ADMIN --------------------
# class WorkflowStepInline(admin.TabularInline):
#     model = WorkflowStep
#     extra = 0
#     fields = ("position", "title", "role_group", "form", "allow_reject", "end_on_reject", "auto_claim", "notify_emails")
#     ordering = ("position",)

# @admin.register(WorkflowTemplate)
# class WorkflowTemplateAdmin(admin.ModelAdmin):
#     list_display = ("name", "slug", "is_active")
#     search_fields = ("name", "slug")
#     inlines = [WorkflowStepInline]

class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0
    fields = ("position", "title", "role", "form", "end_on_reject", "auto_claim")  # 👈 show role FK here
    ordering = ("position",)

@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    inlines = [WorkflowStepInline]

@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
    list_display = ("template", "position", "title", "role")
    list_filter = ("template", "role")
    ordering = ("template", "position")

@admin.register(ProcessStepLog)
class ProcessStepLogAdmin(admin.ModelAdmin):
    list_display = ("process", "index", "decision", "acted_by", "acted_at", "step")
    list_filter = ("template", "step")
    readonly_fields = ("acted_at",)

@admin.register(WorkflowRole)
class WorkflowRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")

@admin.register(UserWorkflowRole)
class UserWorkflowRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "role__name", "role__code")

@admin.register(DynamicTicketProcess)
class DynamicTicketProcessAdmin(admin.ModelAdmin):
    list_display = ("id", "ref_id", "form", "created_at", "updated_at")
    search_fields = ("ref_id",)
    list_filter = ("form", "created_at")