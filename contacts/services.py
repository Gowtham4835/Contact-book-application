import re

from django.db import transaction

from .models import Contact, ContactMergeArchive


def _duplicate_keys(contact):
    owner_key = contact.user_id
    phone = re.sub(r"\D", "", contact.phone_number)
    if phone:
        yield (owner_key, "phone", phone), "phone"
    if contact.email.strip():
        yield (owner_key, "email", contact.email.strip().casefold()), "email"
    normalized_name = " ".join(contact.name.casefold().split())
    # A name alone is too weak for safe automation; birthday and group add context.
    if normalized_name and contact.birthday:
        yield (
            owner_key,
            "name_birthday_group",
            normalized_name,
            contact.birthday.isoformat(),
            contact.contact_group_id,
        ), "name+birthday+group"


def find_duplicate_groups(queryset=None):
    """Return exact same-owner matches without chaining unrelated records together."""
    source = queryset if queryset is not None else Contact.objects.all()
    contacts = list(source.filter(user__isnull=False).select_related("contact_group"))
    matches = {}

    for contact in contacts:
        for key, criterion in _duplicate_keys(contact):
            match = matches.setdefault(key, {"contacts": [], "criterion": criterion})
            match["contacts"].append(contact)

    # A~B by phone and B~C by email must not silently merge A, B, and C.
    grouped = {}
    for match in matches.values():
        group = match["contacts"]
        if len(group) < 2:
            continue
        member_ids = tuple(sorted(contact.pk for contact in group))
        result = grouped.setdefault(member_ids, {"contacts": group, "matched_on": set()})
        result["matched_on"].add(match["criterion"])

    return [
        {
            "contacts": sorted(group["contacts"], key=lambda item: item.pk),
            "matched_on": sorted(group["matched_on"]),
        }
        for _member_ids, group in sorted(grouped.items())
    ]


def _contact_snapshot(contact):
    return {
        "id": contact.pk,
        "user_id": contact.user_id,
        "name": contact.name,
        "phone_number": contact.phone_number,
        "email": contact.email,
        "contact_picture": contact.contact_picture.name,
        "contact_group_id": contact.contact_group_id,
        "birthday": contact.birthday.isoformat() if contact.birthday else None,
        "anniversary": contact.anniversary.isoformat() if contact.anniversary else None,
        "reminder_date": contact.reminder_date.isoformat() if contact.reminder_date else None,
        "reminder_note": contact.reminder_note,
    }


@transaction.atomic
def merge_contact_group(contacts, matched_on):
    """Merge duplicate contacts into the oldest record while archiving source data."""
    contact_ids = sorted({contact.pk for contact in contacts if contact.pk is not None})
    locked_contacts = list(
        Contact.objects.select_for_update()
        .filter(pk__in=contact_ids)
        .order_by("pk")
    )
    if len(locked_contacts) < 2:
        return None
    if len({contact.user_id for contact in locked_contacts}) != 1:
        raise ValueError("Contacts must belong to the same account before merging.")
    if locked_contacts[0].user_id is None:
        raise ValueError("Unowned contacts cannot be merged automatically.")

    primary = locked_contacts[0]
    archived_sources = []
    for duplicate in locked_contacts[1:]:
        archived_sources.append(_contact_snapshot(duplicate))
        for field in ("email", "birthday", "anniversary", "reminder_date", "reminder_note"):
            if not getattr(primary, field) and getattr(duplicate, field):
                setattr(primary, field, getattr(duplicate, field))
        ContactMergeArchive.objects.create(
            target_contact=primary,
            source_contact_id=duplicate.pk,
            source_snapshot=_contact_snapshot(duplicate),
            matched_on=", ".join(matched_on),
        )
        duplicate.delete()

    primary.save()
    if primary.user_id:
        from .tasks import send_contact_event_email

        transaction.on_commit(
            lambda contact_id=primary.pk: send_contact_event_email.delay(
                contact_id,
                "duplicates_merged",
                len(archived_sources),
            ),
            robust=True,
        )
    return primary


def merge_all_duplicate_contacts():
    merged = 0
    processed_contact_ids = set()
    for duplicate_group in find_duplicate_groups():
        contact_ids = {contact.pk for contact in duplicate_group["contacts"]}
        if contact_ids & processed_contact_ids:
            continue
        processed_contact_ids.update(contact_ids)
        primary = merge_contact_group(duplicate_group["contacts"], duplicate_group["matched_on"])
        if primary:
            merged += len(duplicate_group["contacts"]) - 1
    return merged