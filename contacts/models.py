from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(
    regex=r"^\+?[0-9]{10,15}$",
    message="Enter a valid phone number with 10 to 15 digits.",
)

class ContactGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Contact(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
    )
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=16, unique=True, validators=[phone_validator])
    contact_picture = models.ImageField(upload_to="contact_pictures/")
    contact_group = models.ForeignKey(ContactGroup, on_delete=models.PROTECT, related_name="contacts")
    email = models.EmailField(blank=True)
    birthday = models.DateField(null=True, blank=True)
    anniversary = models.DateField(null=True, blank=True)
    reminder_date = models.DateField(null=True, blank=True)
    reminder_note = models.CharField(max_length=250, blank=True)

    class Meta:
        permissions = [
            ("manage_all_contacts", "Can manage all contacts"),
        ]

    def __str__(self):
        return self.name


class ContactMergeArchive(models.Model):
    """Retain source data and a traceable record when duplicate contacts merge."""

    target_contact = models.ForeignKey(
        Contact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="merge_archives",
    )
    source_contact_id = models.PositiveBigIntegerField()
    source_snapshot = models.JSONField()
    matched_on = models.CharField(max_length=100)
    merged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-merged_at",)


class ReminderDelivery(models.Model):
    class ReminderType(models.TextChoices):
        BIRTHDAY = "birthday", "Birthday"
        ANNIVERSARY = "anniversary", "Anniversary"
        CUSTOM = "custom", "Custom reminder"

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="reminder_deliveries")
    reminder_type = models.CharField(max_length=20, choices=ReminderType.choices)
    reminder_date = models.DateField()
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("contact", "reminder_type", "reminder_date"),
                name="unique_contact_reminder_per_date",
            ),
        ]