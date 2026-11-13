from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Contact
from .services import find_duplicate_groups, merge_contact_group
from .views import can_manage_all_contacts


def visible_contacts(user):
    contacts = Contact.objects.select_related("contact_group", "user")
    if not can_manage_all_contacts(user):
        contacts = contacts.filter(user=user)
    return contacts


class DuplicateContactsAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        if not request.user.has_perm("contacts.view_contact"):
            raise PermissionDenied
        duplicates = find_duplicate_groups(visible_contacts(request.user))
        return Response({
            "success": True,
            "duplicates": [
                {
                    "contact_ids": [contact.pk for contact in group["contacts"]],
                    "names": [contact.name for contact in group["contacts"]],
                    "matched_on": group["matched_on"],
                }
                for group in duplicates
            ],
        })

    def post(self, request):
        if not request.user.has_perm("contacts.change_contact") or not request.user.has_perm("contacts.delete_contact"):
            raise PermissionDenied
        contact_id = request.data.get("contact_id")
        try:
            contact_id = int(contact_id)
        except (TypeError, ValueError):
            raise ValidationError({"contact_id": "Provide a valid contact ID."})

        selected = get_object_or_404(visible_contacts(request.user), pk=contact_id)
        duplicate_group = next(
            (
                group
                for group in find_duplicate_groups(visible_contacts(request.user))
                if any(contact.pk == selected.pk for contact in group["contacts"])
            ),
            None,
        )
        if duplicate_group is None:
            raise ValidationError({"contact_id": "No matching duplicate contact group was found."})

        primary = merge_contact_group(duplicate_group["contacts"], duplicate_group["matched_on"])
        return Response({
            "success": True,
            "primary_contact_id": primary.pk,
            "merged_count": len(duplicate_group["contacts"]) - 1,
        })


class ContactSessionAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        session_context = request.session.get("contact_book", {})
        preferences = session_context.get("preferences", {"page_size": 25})
        recent_ids = request.session.get("recent_contact_ids", [])
        recent_queryset = visible_contacts(request.user).filter(pk__in=recent_ids)
        recent_by_id = {contact.pk: contact for contact in recent_queryset}
        recent = [
            {"id": pk, "name": recent_by_id[pk].name, "email": recent_by_id[pk].email}
            for pk in recent_ids
            if pk in recent_by_id
        ]
        return Response({
            "success": True,
            "roles": session_context.get("roles", []),
            "permissions": session_context.get("permissions", []),
            "preferences": preferences,
            "recent_contacts": recent,
        })

    def post(self, request):
        raw_page_size = request.data.get("page_size")
        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError):
            raise ValidationError({"page_size": "Choose 10, 25, 50, or 100."})
        if page_size not in (10, 25, 50, 100):
            raise ValidationError({"page_size": "Choose 10, 25, 50, or 100."})
        session_context = request.session.get("contact_book", {})
        preferences = session_context.get("preferences", {})
        preferences["page_size"] = page_size
        session_context["preferences"] = preferences
        request.session["contact_book"] = session_context
        return Response({"success": True, "preferences": preferences})