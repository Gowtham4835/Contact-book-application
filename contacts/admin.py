from django.contrib import admin
from .models import Contact, ContactGroup, ContactMergeArchive, ReminderDelivery

@admin.register(ContactGroup)
class ContactGroupAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "phone_number", "email", "birthday", "contact_group")
    search_fields = ("name", "phone_number", "email")
    list_filter = ("contact_group",)


@admin.register(ContactMergeArchive)
class ContactMergeArchiveAdmin(admin.ModelAdmin):
    list_display = ("source_contact_id", "target_contact", "matched_on", "merged_at")
    readonly_fields = ("merged_at",)


@admin.register(ReminderDelivery)
class ReminderDeliveryAdmin(admin.ModelAdmin):
    list_display = ("contact", "reminder_type", "reminder_date", "sent_status")

    @admin.display(description="Sent at")
    def sent_status(self, obj):
        if obj.sent_at is None:
            return "Pending"
        return obj.sent_at.strftime("%Y-%m-%d %H:%M:%S")
