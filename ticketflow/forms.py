from django import forms
from .models import WorkflowTemplate, Form as FormModel, FormField, TicketProcess


def add_fields_to_form(django_form, form_obj: FormModel):
    """
    Add fields (Text/Long text/Drop-down/File) to a Django form instance,
    based on FormField rows configured in admin.
    Keys use field.id to avoid label name conflicts.
    """
    for ff in form_obj.fields.all():
        key = str(ff.id)
        if ff.field_type == FormField.TEXT:
            django_form.fields[key] = forms.CharField(
                label=ff.label,
                required=ff.required,
                max_length=ff.max_length or 255,
                help_text=ff.help_text,
            )
        elif ff.field_type == FormField.TEXTAREA:
            django_form.fields[key] = forms.CharField(
                label=ff.label,
                required=ff.required,
                widget=forms.Textarea,
                help_text=ff.help_text,
            )
        elif ff.field_type == FormField.SELECT:
            choices = [(c.strip(), c.strip()) for c in ff.choices.split(",") if c.strip()]
            django_form.fields[key] = forms.ChoiceField(
                label=ff.label,
                required=ff.required,
                choices=choices,
                help_text=ff.help_text,
            )
        elif ff.field_type == FormField.FILE:
            django_form.fields[key] = forms.FileField(
                label=ff.label,
                required=ff.required,
                help_text=ff.help_text,
            )


class ApprovalForm(forms.ModelForm):
    decision = forms.ChoiceField(
        choices=[("approved", "Approve"), ("rejected", "Reject")],
        widget=forms.RadioSelect
    )

    class Meta:
        model = TicketProcess
        fields = []  # we will add the proper comment field dynamically in the view
