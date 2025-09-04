from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Viewflow dashboard 
from viewflow.urls import Site, Application
from viewflow.workflow.flow import FlowAppViewset

from ticketflow.flows import TicketFlow, RiskDynamicFlow, GenericDynamicFlow, DBWorkflowFlow
from ticketflow.views import (
    export_form_entries_csv,
    export_process_csv,
    ProcessSummaryView,
    ChooseWorkflowStartView,
    DBStepExecutionView,
    DBWorkflowDashboardView,
)

# Viewflow dashboard with FOUR tiles
site = Site(
    title="GRC Workspace",
    viewsets=[
        Application(
            title="Ticketing",
            app_name="ticketflow",
            viewsets=[FlowAppViewset(TicketFlow, icon="assignment")],
        ),
        Application(
            title="Risk Management",
            app_name="riskflow",
            viewsets=[FlowAppViewset(RiskDynamicFlow, icon="security")],
        ),
        Application(
            title="Generic (Choose Form)",
            app_name="genericflow",
            viewsets=[FlowAppViewset(GenericDynamicFlow, icon="dynamic_form")],
        ),
        Application(
            title="DB Workflow",
            app_name="dbworkflow",
            viewsets=[FlowAppViewset(DBWorkflowFlow, icon="dynamic_form")],
        ),
    ],
)

urlpatterns = [
    # CSV export endpoints
    path("export/form/<str:form_slug_or_id>/csv/", export_form_entries_csv, name="export_form_csv"),
    path("export/process/<int:process_id>/csv/", export_process_csv, name="export_process_csv"),

    # Summary page for a process
    path("process/<int:pk>/summary/", ProcessSummaryView.as_view(), name="process_summary"),

    # Django admin & auth
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),

    # ✅ DB Workflow dynamic URLs (added inline, no separate urls.py needed)
    path("dbworkflow/start/", ChooseWorkflowStartView.as_view(), name="dbworkflow_start"),
    # path("dbworkflow/<int:process_pk>/step/", DBStepExecutionView.as_view(), name="dbworkflow_step"),
    path("dbworkflow/<int:pk>/step/", DBStepExecutionView.as_view(), name="dbworkflow_step"),

    # view dbflow dashboard
    path("dbworkflow/", DBWorkflowDashboardView.as_view(), name="dbworkflow_dashboard"),


    # Viewflow dashboard (tiles)
    path("", site.urls),
]

# Serve media in DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
