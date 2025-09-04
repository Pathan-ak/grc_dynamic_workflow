from viewflow import this
from viewflow.workflow import flow, lock

from django.contrib.auth.models import AnonymousUser

from .models import TicketProcess, WorkflowStep
from .views import (
    DynamicStartView,
    RiskDynamicStartView,
    SelectableDynamicStartView,
    create_entry_and_snapshot,
    send_submission_emails,
    ApprovalView,
    # NEW
    ChooseWorkflowStartView, DBStepExecutionView,
)

from .permissions import in_group
from .notify import send_stage_email

def _get_user_from_permission_call(*args, **kwargs):
    if args:
        obj = args[0]
        if hasattr(obj, "user"):
            return getattr(obj, "user", AnonymousUser())
        if hasattr(obj, "request") and hasattr(obj.request, "user"):
            return getattr(obj.request, "user", AnonymousUser())
    req = kwargs.get("request")
    if req and hasattr(req, "user"):
        return req.user
    act = kwargs.get("activation")
    if act and hasattr(act, "request") and hasattr(act.request, "user"):
        return act.request.user
    return AnonymousUser()

# ---- email hooks (plain functions; signature = fn(activation)) ----
def email_after_rr(activation):
    p = activation.process
    send_stage_email(p, stage_title="RR Review",
        actor=p.approved_by_user or "RR",
        decision=p.user_decision or "pending",
        comment=p.user_comment or "")

def email_after_rc(activation):
    p = activation.process
    send_stage_email(p, stage_title="RC Review",
        actor=p.approved_by_dev or "RC",
        decision=p.dev_decision or "pending",
        comment=p.dev_comment or "")

def email_after_ra(activation):
    p = activation.process
    send_stage_email(p, stage_title="RA Approval",
        actor=p.approved_by_ba or "RA",
        decision=p.ba_decision or "pending",
        comment=p.ba_comment or "")

def email_after_cro(activation):
    p = activation.process
    send_stage_email(p, stage_title="CRO Approval",
        actor=p.approved_by_pm or "CRO",
        decision=p.pm_decision or "pending",
        comment=p.pm_comment or "")

# ---------- Optional: legacy Ticket flow kept as-is ----------
class TicketFlow(flow.Flow):
    process_class = TicketProcess
    lock_impl = lock.select_for_update_lock

    start = flow.Start(DynamicStartView.as_view()).Annotation(title="Start Ticket").Permission(auto_create=True).Next(this.save_ticket_data)

    def _save_ticket_data(self, activation):
        process: TicketProcess = activation.process
        entry, snapshot = create_entry_and_snapshot(process, activation=activation)
        process.ticket_data = snapshot
        process.save()
        send_submission_emails(process)

    save_ticket_data = flow.Function(_save_ticket_data).Annotation(title="Save Data").Next(this.user_approval)

    user_approval = flow.View(ApprovalView.as_view(role="RR")).Annotation(title="RR Review").Permission(auto_create=True).Next(this.route_user)
    route_user = flow.If(lambda act: act.process.user_decision == "approved").Then(this.dev_approval).Else(this.start)
    dev_approval = flow.View(ApprovalView.as_view(role="RC")).Annotation(title="RC Review").Permission(auto_create=True).Next(this.route_dev)
    route_dev = flow.If(lambda act: act.process.dev_decision == "approved").Then(this.ba_approval).Else(this.user_approval)
    ba_approval = flow.View(ApprovalView.as_view(role="RA")).Annotation(title="RA Approval").Permission(auto_create=True).Next(this.route_ba)
    route_ba = flow.If(lambda act: act.process.ba_decision == "approved").Then(this.pm_approval).Else(this.dev_approval)
    pm_approval = flow.View(ApprovalView.as_view(role="CRO")).Annotation(title="CRO Approval").Permission(auto_create=True).Next(this.route_pm)
    route_pm = flow.If(lambda act: act.process.pm_decision == "approved").Then(this.end).Else(this.ba_approval)
    end = flow.End()

# ---------- Risk flow locked to 'risk' form; group-gated; mail after each stage ----------
class RiskDynamicFlow(flow.Flow):
    process_class = TicketProcess
    lock_impl = lock.select_for_update_lock

    start = flow.Start(RiskDynamicStartView.as_view(preselect_form_slug="risk")).Annotation(title="Start Risk").Permission(auto_create=True).Next(this.rr_review)

    rr_review = flow.View(ApprovalView.as_view(role="RR")).Annotation(title="RR Review").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "RR")).Next(this.post_rr)
    post_rr = flow.Function(email_after_rr).Next(this.route_rr)
    route_rr = flow.If(lambda act: act.process.user_decision == "approved").Then(this.rc_review).Else(this.start)

    rc_review = flow.View(ApprovalView.as_view(role="RC")).Annotation(title="RC Review").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "RC")).Assign(lambda act: None).Next(this.post_rc)
    post_rc = flow.Function(email_after_rc).Next(this.route_rc)
    route_rc = flow.If(lambda act: act.process.dev_decision == "approved").Then(this.ra_approval).Else(this.rr_review)

    ra_approval = flow.View(ApprovalView.as_view(role="RA")).Annotation(title="RA Approval").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "RA")).Assign(lambda act: None).Next(this.post_ra)
    post_ra = flow.Function(email_after_ra).Next(this.route_ra)
    route_ra = flow.If(lambda act: act.process.ba_decision == "approved").Then(this.cro_approval).Else(this.rc_review)

    cro_approval = flow.View(ApprovalView.as_view(role="CRO")).Annotation(title="CRO Approval").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "CRO")).Assign(lambda act: None).Next(this.post_cro)
    post_cro = flow.Function(email_after_cro).Next(this.route_cro)
    route_cro = flow.If(lambda act: act.process.pm_decision == "approved").Then(this.end).Else(this.ra_approval)

    end = flow.End()

# ---------- Generic flow where the user chooses the form at start ----------
class GenericDynamicFlow(flow.Flow):
    process_class = TicketProcess
    lock_impl = lock.select_for_update_lock

    start = flow.Start(SelectableDynamicStartView.as_view()).Annotation(title="Start (Choose Form)").Permission(auto_create=True).Next(this.rr_review)
    rr_review = flow.View(ApprovalView.as_view(role="RR")).Annotation(title="RR Review").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "RR")).Next(this.route_rr)
    route_rr = flow.If(lambda act: act.process.user_decision == "approved").Then(this.rc_review).Else(this.start)
    rc_review = flow.View(ApprovalView.as_view(role="RC")).Annotation(title="RC Review").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "RC")).Next(this.route_rc)
    route_rc = flow.If(lambda act: act.process.dev_decision == "approved").Then(this.ra_approval).Else(this.rr_review)
    ra_approval = flow.View(ApprovalView.as_view(role="RA")).Annotation(title="RA Approval").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "RA")).Next(this.route_ra)
    route_ra = flow.If(lambda act: act.process.ba_decision == "approved").Then(this.cro_approval).Else(this.rc_review)
    cro_approval = flow.View(ApprovalView.as_view(role="CRO")).Annotation(title="CRO Approval").Permission(lambda *a, **kw: in_group(_get_user_from_permission_call(*a, **kw), "CRO")).Next(this.route_cro)
    route_cro = flow.If(lambda act: act.process.pm_decision == "approved").Then(this.end).Else(this.ra_approval)
    end = flow.End()

# ===================== DB-DRIVEN FLOW =====================
def _has_more_steps(activation):
    p = activation.process
    data = p.ticket_data or {}
    wf_id = data.get("wf_id")
    if not wf_id:
        return False
    total = WorkflowStep.objects.filter(template_id=wf_id).count()
    return (data.get("wf_step", 0)) < total

class DBWorkflowFlow(flow.Flow):
    """
    One flow to run ANY workflow defined in Admin (WorkflowTemplate + steps).
    """
    process_class = TicketProcess
    lock_impl = lock.select_for_update_lock

    start = flow.Start(ChooseWorkflowStartView.as_view()).Annotation(title="Start (Choose Workflow & Form)").Permission(auto_create=True).Next(this.step)

    step = flow.View(DBStepExecutionView.as_view()).Annotation(title="Execute Step").Permission(auto_create=True).Assign(lambda act: None).Next(this.route)

    route = flow.If(lambda act: _has_more_steps(act)).Then(this.step).Else(this.end)

    end = flow.End()
