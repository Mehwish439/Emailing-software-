from django.contrib import admin

from .models import Automation, AutomationEnrollment, AutomationExecution, AutomationStep


class AutomationStepInline(admin.TabularInline):
    model = AutomationStep
    extra = 0


@admin.register(Automation)
class AutomationAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "trigger_type", "status", "created_at")
    list_filter = ("status", "trigger_type")
    search_fields = ("name",)
    inlines = [AutomationStepInline]


@admin.register(AutomationEnrollment)
class AutomationEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("automation", "contact", "status", "current_step_order", "next_run_at")
    list_filter = ("status",)
    raw_id_fields = ("contact", "automation")


@admin.register(AutomationExecution)
class AutomationExecutionAdmin(admin.ModelAdmin):
    list_display = ("automation", "contact", "step_order", "action_type", "status", "attempt", "executed_at")
    list_filter = ("status", "action_type")
    raw_id_fields = ("contact", "automation", "enrollment", "step")
