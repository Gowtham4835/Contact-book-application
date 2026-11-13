from datetime import date
from urllib.parse import urljoin

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .authentication.tokens import contact_password_reset_token_generator
from .models import Contact, ReminderDelivery


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_account_notification(user_id, subject, message):
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user or not user.email:
        return 0
    return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_contact_event_email(contact_id, event, merged_count=0):
    contact = Contact.objects.select_related("user").filter(pk=contact_id).first()
    if not contact or not contact.user or not contact.user.email:
        return 0

    if event == "created":
        subject = "Contact added to your contact book"
        message = "You added {name} to your contact book.".format(name=contact.name)
    elif event == "updated":
        subject = "Contact details updated"
        message = "The details for {name} were updated.".format(name=contact.name)
    else:
        subject = "Duplicate contacts merged"
        message = "{count} duplicate contact record(s) were merged into {name}.".format(
            count=merged_count,
            name=contact.name,
        )
    return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [contact.user.email], fail_silently=False)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_password_reset_email(user_id):
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user or not user.email:
        return 0

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = contact_password_reset_token_generator.make_token(user)
    path = reverse("authentication:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    reset_url = urljoin(settings.SITE_URL.rstrip("/") + "/", path.lstrip("/"))
    message = "Use this link to reset your Contact Book password:\n\n{url}\n\nIf you did not request this, ignore this email.".format(
        url=reset_url
    )
    return send_mail(
        "Reset your Contact Book password",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


def _is_annual_occurrence(value, today):
    if value.month == 2 and value.day == 29:
        return today.month == 2 and today.day == 28 and not _is_leap_year(today.year)
    return value.month == today.month and value.day == today.day


def _is_leap_year(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _send_contact_reminders(contact, today):
    if not contact.user or not contact.user.email:
        return 0

    due_reminders = []
    for field, reminder_type in (
        ("birthday", ReminderDelivery.ReminderType.BIRTHDAY),
        ("anniversary", ReminderDelivery.ReminderType.ANNIVERSARY),
    ):
        value = getattr(contact, field)
        if value and _is_annual_occurrence(value, today):
            due_reminders.append((reminder_type, field.title()))
    if contact.reminder_date == today:
        due_reminders.append((ReminderDelivery.ReminderType.CUSTOM, contact.reminder_note or "Custom reminder"))

    sent_count = 0
    for reminder_type, label in due_reminders:
        with transaction.atomic():
            delivery, _ = ReminderDelivery.objects.get_or_create(
                contact=contact,
                reminder_type=reminder_type,
                reminder_date=today,
            )
            delivery = ReminderDelivery.objects.select_for_update().get(pk=delivery.pk)
            if delivery.sent_at:
                continue
            subject = "Contact reminder: {label}".format(label=label)
            message = "Today is {label} for {name}.".format(label=label.lower(), name=contact.name)
            if reminder_type == ReminderDelivery.ReminderType.CUSTOM and contact.reminder_note:
                message += "\n\n{note}".format(note=contact.reminder_note)
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [contact.user.email],
                fail_silently=False,
            )
            delivery.sent_at = timezone.now()
            delivery.save(update_fields=("sent_at",))
            sent_count += 1
    return sent_count


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_contact_reminders(contact_id, today_iso=None):
    contact = Contact.objects.select_related("user").filter(pk=contact_id).first()
    if not contact:
        return 0
    today = date.fromisoformat(today_iso) if today_iso else timezone.localdate()
    return _send_contact_reminders(contact, today)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_due_contact_reminders(today_iso=None):
    today = date.fromisoformat(today_iso) if today_iso else timezone.localdate()
    sent_count = 0
    contacts = Contact.objects.select_related("user").filter(user__isnull=False)
    for contact in contacts:
        sent_count += _send_contact_reminders(contact, today)
    return sent_count


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def merge_duplicate_contacts():
    from .services import merge_all_duplicate_contacts

    return merge_all_duplicate_contacts()