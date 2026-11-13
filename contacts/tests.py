import io
import shutil
import tempfile
from datetime import date
from urllib.parse import urlsplit

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.db.models import ProtectedError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.utils import timezone
from PIL import Image

from .admin import ContactMergeArchiveAdmin, ReminderDeliveryAdmin
from .authentication.tokens import contact_password_reset_token_generator
from .api_exceptions import custom_exception_handler
from .models import Contact, ContactGroup, ContactMergeArchive, ReminderDelivery
from .services import find_duplicate_groups, merge_all_duplicate_contacts
from .tasks import send_due_contact_reminders, send_password_reset_email


User = get_user_model()
image_buffer = io.BytesIO()
Image.new("RGB", (1, 1), color="white").save(image_buffer, format="PNG")
PNG_CONTENT = image_buffer.getvalue()


class AuthenticationTests(TestCase):
	def setUp(self):
		self.register_url = reverse("authentication:register")
		self.login_url = reverse("authentication:login")

	def test_registration_creates_user_with_hashed_password_and_regular_role(self):
		response = self.client.post(
			self.register_url,
			{
				"email": " New.User@example.com ",
				"password": "Mango!River482",
				"confirm_password": "Mango!River482",
			},
		)

		self.assertRedirects(response, reverse("contacts:contact_list"), fetch_redirect_response=False)
		user = User.objects.get(email="new.user@example.com")
		self.assertTrue(user.check_password("Mango!River482"))
		self.assertNotEqual(user.password, "Mango!River482")
		self.assertTrue(user.groups.filter(name="Regular Users").exists())
		self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
		self.assertIn("Regular Users", self.client.session["contact_book"]["roles"])
		self.assertIn("contacts.view_contact", self.client.session["contact_book"]["permissions"])

	def test_registration_rejects_invalid_email_weak_password_and_mismatch(self):
		cases = [
			{"email": "not-an-email", "password": "Mango!River482", "confirm_password": "Mango!River482"},
			{"email": "weak@example.com", "password": "123", "confirm_password": "123"},
			{"email": "mismatch@example.com", "password": "Mango!River482", "confirm_password": "Other!Pass482"},
		]

		for data in cases:
			with self.subTest(data=data):
				response = self.client.post(self.register_url, data)
				self.assertEqual(response.status_code, 200, response.content.decode())
				self.assertFalse(User.objects.filter(email=data["email"].lower()).exists())

	def test_registration_rejects_duplicate_email_case_insensitively(self):
		User.objects.create_user(username="existing@example.com", email="existing@example.com", password="A-strong-password!2")
		response = self.client.post(
			self.register_url,
			{
				"email": "EXISTING@example.com",
				"password": "Mango!River482",
				"confirm_password": "Mango!River482",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(User.objects.filter(email__iexact="existing@example.com").count(), 1)

	def test_login_accepts_email_and_redirects_after_authentication(self):
		User.objects.create_user(username="login@example.com", email="login@example.com", password="Mango!River482")

		response = self.client.post(
			self.login_url,
			{"email": "login@example.com", "password": "Mango!River482"},
		)

		self.assertRedirects(response, reverse("contacts:contact_list"), fetch_redirect_response=False)
		self.assertEqual(self.client.session["_auth_user_id"], str(User.objects.get(email="login@example.com").pk))

	def test_login_accepts_email_with_different_letter_case(self):
		User.objects.create_user(username="login@example.com", email="login@example.com", password="Mango!River482")

		response = self.client.post(
			self.login_url,
			{"email": "LOGIN@EXAMPLE.COM", "password": "Mango!River482"},
		)

		self.assertRedirects(response, reverse("contacts:contact_list"), fetch_redirect_response=False)
		self.assertIn("_auth_user_id", self.client.session)

	def test_login_rejects_wrong_password_and_unknown_email(self):
		User.objects.create_user(username="login@example.com", email="login@example.com", password="Mango!River482")

		for email, password in (("login@example.com", "wrong-password"), ("missing@example.com", "Mango!River482")):
			with self.subTest(email=email):
				response = self.client.post(self.login_url, {"email": email, "password": password})
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, "Invalid email or password")

	def test_logout_requires_post_and_clears_session(self):
		user = User.objects.create_user(username="logout@example.com", email="logout@example.com", password="Mango!River482")
		self.client.force_login(user)

		get_response = self.client.get(reverse("authentication:logout"))
		self.assertEqual(get_response.status_code, 405)

		response = self.client.post(reverse("authentication:logout"))
		self.assertRedirects(response, self.login_url)
		self.assertNotIn("_auth_user_id", self.client.session)


class ContactRolePermissionTests(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.media_dir = tempfile.mkdtemp(prefix="contact-book-tests-")
		cls.media_settings = override_settings(MEDIA_ROOT=cls.media_dir)
		cls.media_settings.enable()
		cls.addClassCleanup(cls.media_settings.disable)
		cls.addClassCleanup(shutil.rmtree, cls.media_dir, ignore_errors=True)

	@classmethod
	def setUpTestData(cls):
		cls.regular_role = Group.objects.get(name="Regular Users")
		cls.admin_role = Group.objects.get(name="Admins")
		cls.group = ContactGroup.objects.create(name="Friends")
		cls.owner = User.objects.create_user(
			username="owner@example.com", email="owner@example.com", password="Mango!River482"
		)
		cls.owner.groups.add(cls.regular_role)
		cls.other_user = User.objects.create_user(
			username="other@example.com", email="other@example.com", password="Mango!River482"
		)
		cls.other_user.groups.add(cls.regular_role)
		cls.admin = User.objects.create_user(
			username="admin@example.com", email="admin@example.com", password="Mango!River482"
		)
		cls.admin.groups.add(cls.admin_role)
		cls.owned_contact = cls.make_contact(cls.owner, "Owner Contact", "+15550000001")
		cls.other_contact = cls.make_contact(cls.other_user, "Other Contact", "+15550000002")

	@classmethod
	def make_contact(cls, user, name, phone):
		return Contact.objects.create(
			user=user,
			name=name,
			phone_number=phone,
			contact_picture="contact_pictures/test.png",
			contact_group=cls.group,
			email=f"{name.lower().replace(' ', '.')}@example.com",
		)

	def test_reminder_delivery_admin_keeps_required_fields_editable(self):
		request = RequestFactory().get("/admin/contacts/reminderdelivery/add/")
		request.user = self.admin
		form = ReminderDeliveryAdmin(ReminderDelivery, admin.site).get_form(request)
		self.assertIn("contact", form.base_fields)
		self.assertIn("reminder_type", form.base_fields)
		self.assertIn("reminder_date", form.base_fields)
		self.assertNotIn("reminder_date", ReminderDeliveryAdmin.readonly_fields)

	def test_contact_merge_archive_admin_keeps_required_fields_editable(self):
		request = RequestFactory().get("/admin/contacts/contactmergearchive/add/")
		request.user = self.admin
		form = ContactMergeArchiveAdmin(ContactMergeArchive, admin.site).get_form(request)
		self.assertIn("source_contact_id", form.base_fields)
		self.assertIn("source_snapshot", form.base_fields)
		self.assertIn("matched_on", form.base_fields)
		self.assertIn("target_contact", form.base_fields)
		self.assertNotIn("source_contact_id", ContactMergeArchiveAdmin.readonly_fields)
		self.assertNotIn("source_snapshot", ContactMergeArchiveAdmin.readonly_fields)
		self.assertNotIn("matched_on", ContactMergeArchiveAdmin.readonly_fields)

	def test_reminder_delivery_admin_keeps_sent_at_editable(self):
		request = RequestFactory().get("/admin/contacts/reminderdelivery/add/")
		request.user = self.admin
		form = ReminderDeliveryAdmin(ReminderDelivery, admin.site).get_form(request)
		self.assertIn("sent_at", form.base_fields)
		self.assertNotIn("sent_at", ReminderDeliveryAdmin.readonly_fields)

	def test_contact_pages_require_authentication(self):
		for url in (
			reverse("contacts:contact_list"),
			reverse("contacts:contact_create"),
			reverse("contacts:contact_datatable"),
			reverse("contacts:contact_edit", args=[self.owned_contact.pk]),
			reverse("contacts:contact_delete", args=[self.owned_contact.pk]),
		):
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertRedirects(response, f"{reverse('authentication:login')}?next={url}")

	def test_create_and_edit_pages_render_forms(self):
		self.client.force_login(self.owner)

		create_response = self.client.get(reverse("contacts:contact_create"))
		edit_response = self.client.get(reverse("contacts:contact_edit", args=[self.owned_contact.pk]))

		self.assertEqual(create_response.status_code, 200)
		self.assertIn("form", create_response.context)
		self.assertEqual(edit_response.status_code, 200)
		self.assertEqual(edit_response.context["contact"], self.owned_contact)

	def test_regular_user_sees_only_owned_contacts_in_table_queryset(self):
		from .datatables import ContactAjaxDatatableView

		request = RequestFactory().get(reverse("contacts:contact_datatable"))
		request.user = self.owner
		queryset = ContactAjaxDatatableView().get_initial_queryset(request)

		self.assertEqual(list(queryset.values_list("pk", flat=True)), [self.owned_contact.pk])

	def test_regular_user_can_create_owned_contact(self):
		self.client.force_login(self.owner)
		response = self.client.post(
			reverse("contacts:contact_create"),
			{
				"name": "New Contact",
				"phone_number": "+15550000003",
				"contact_picture": SimpleUploadedFile("new.png", PNG_CONTENT, content_type="image/png"),
				"contact_group": self.group.pk,
				"email": "new-contact@example.com",
			},
		)

		self.assertEqual(response.status_code, 200, response.content.decode())
		self.assertJSONEqual(response.content, {
			"success": True,
			"message": "Contact saved successfully",
			"id": Contact.objects.get(phone_number="+15550000003").pk,
		})
		self.assertEqual(Contact.objects.get(phone_number="+15550000003").user, self.owner)

	@override_settings(
		EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
		CELERY_TASK_ALWAYS_EAGER=True,
	)
	def test_saving_contact_with_reminder_today_sends_reminder_immediately(self):
		self.client.force_login(self.owner)
		today = timezone.localdate()
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.post(
				reverse("contacts:contact_create"),
				{
					"name": "Today Reminder",
					"phone_number": "+15550000030",
					"contact_picture": SimpleUploadedFile("today.png", PNG_CONTENT, content_type="image/png"),
					"contact_group": self.group.pk,
					"email": "today@example.com",
					"reminder_date": today.isoformat(),
					"reminder_note": "Call today",
				},
			)

		self.assertEqual(response.status_code, 200, response.content.decode())
		self.assertEqual(response.json()["success"], True)
		delivery = ReminderDelivery.objects.get(contact_id=response.json()["id"])
		self.assertIsNotNone(delivery.sent_at)
		self.assertTrue(any("Contact reminder: Call today" == message.subject for message in mail.outbox))
	def test_contact_creation_rejects_invalid_phone_and_image(self):
		self.client.force_login(self.owner)
		response = self.client.post(
			reverse("contacts:contact_create"),
			{
				"name": "Invalid Contact",
				"phone_number": "not-a-phone",
				"contact_picture": SimpleUploadedFile("invalid.txt", b"not an image", content_type="text/plain"),
				"contact_group": self.group.pk,
				"email": "invalid-contact@example.com",
			},
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn(b"phone_number", response.content)
		self.assertIn(b"contact_picture", response.content)

	def test_contact_creation_returns_field_errors_for_missing_name_duplicate_phone_and_invalid_email(self):
		self.client.force_login(self.owner)
		response = self.client.post(
			reverse("contacts:contact_create"),
			{
				"phone_number": self.owned_contact.phone_number,
				"contact_picture": SimpleUploadedFile("valid.png", PNG_CONTENT, content_type="image/png"),
				"contact_group": self.group.pk,
				"email": "not-an-email",
			},
		)

		self.assertEqual(response.status_code, 400)
		payload = response.json()
		self.assertFalse(payload["success"])
		self.assertTrue({"name", "phone_number", "email"}.issubset(payload["errors"]))
		self.assertEqual(Contact.objects.count(), 2)

	def test_regular_user_cannot_read_or_mutate_another_users_contact(self):
		self.client.force_login(self.owner)

		edit_url = reverse("contacts:contact_edit", args=[self.other_contact.pk])
		delete_url = reverse("contacts:contact_delete", args=[self.other_contact.pk])
		self.assertEqual(self.client.get(edit_url).status_code, 404)
		self.assertEqual(self.client.post(edit_url, {}).status_code, 404)
		self.assertEqual(self.client.post(delete_url).status_code, 404)
		self.assertTrue(Contact.objects.filter(pk=self.other_contact.pk).exists())

	def test_regular_user_can_edit_and_delete_owned_contact(self):
		self.client.force_login(self.owner)
		edit_url = reverse("contacts:contact_edit", args=[self.owned_contact.pk])
		edit_response = self.client.post(
			edit_url,
			{
				"name": "Updated Contact",
				"phone_number": self.owned_contact.phone_number,
				"contact_group": self.group.pk,
				"email": "updated@example.com",
			},
		)

		self.assertEqual(edit_response.status_code, 200)
		self.owned_contact.refresh_from_db()
		self.assertEqual(self.owned_contact.name, "Updated Contact")

		delete_response = self.client.post(reverse("contacts:contact_delete", args=[self.owned_contact.pk]))
		self.assertEqual(delete_response.status_code, 200)
		self.assertFalse(Contact.objects.filter(pk=self.owned_contact.pk).exists())

	def test_invalid_edit_returns_errors_without_changing_contact(self):
		self.client.force_login(self.owner)
		response = self.client.post(
			reverse("contacts:contact_edit", args=[self.owned_contact.pk]),
			{
				"name": "Should Not Be Saved",
				"phone_number": "invalid-phone",
				"contact_group": self.group.pk,
				"email": "invalid-email",
			},
		)

		self.assertEqual(response.status_code, 400)
		self.assertFalse(response.json()["success"])
		self.assertIn("phone_number", response.json()["errors"])
		self.assertIn("email", response.json()["errors"])
		self.owned_contact.refresh_from_db()
		self.assertEqual(self.owned_contact.name, "Owner Contact")

	def test_delete_endpoint_rejects_get_requests(self):
		self.client.force_login(self.owner)
		response = self.client.get(reverse("contacts:contact_delete", args=[self.owned_contact.pk]))

		self.assertEqual(response.status_code, 405)
		self.assertTrue(Contact.objects.filter(pk=self.owned_contact.pk).exists())

	def test_admin_role_can_access_contacts_owned_by_other_users(self):
		self.client.force_login(self.admin)

		edit_response = self.client.get(reverse("contacts:contact_edit", args=[self.owned_contact.pk]))
		delete_response = self.client.post(reverse("contacts:contact_delete", args=[self.owned_contact.pk]))

		self.assertEqual(edit_response.status_code, 200)
		self.assertEqual(delete_response.status_code, 200)

	def test_user_without_contact_permissions_is_forbidden(self):
		user = User.objects.create_user(
			username="limited@example.com", email="limited@example.com", password="Mango!River482"
		)
		self.client.force_login(user)

		self.assertEqual(self.client.get(reverse("contacts:contact_list")).status_code, 403)
		self.assertEqual(self.client.post(reverse("contacts:contact_create"), {}).status_code, 403)

	def test_user_without_change_or_delete_permission_cannot_edit_or_delete(self):
		from django.contrib.auth.models import Permission

		user = User.objects.create_user(
			username="viewer@example.com", email="viewer@example.com", password="Mango!River482"
		)
		permissions = Permission.objects.filter(
			content_type__app_label="contacts",
			codename__in=("view_contact", "add_contact"),
		)
		user.user_permissions.add(*permissions)
		self.client.force_login(user)

		self.assertEqual(self.client.get(reverse("contacts:contact_edit", args=[self.owned_contact.pk])).status_code, 403)
		self.assertEqual(self.client.post(reverse("contacts:contact_delete", args=[self.owned_contact.pk])).status_code, 403)
		self.assertTrue(Contact.objects.filter(pk=self.owned_contact.pk).exists())

	def test_superuser_can_manage_all_contacts(self):
		super_admin = User.objects.create_superuser(
			username="root@example.com", email="root@example.com", password="Mango!River482"
		)
		self.client.force_login(super_admin)

		self.assertEqual(self.client.get(reverse("contacts:contact_edit", args=[self.other_contact.pk])).status_code, 200)
		self.assertEqual(
			self.client.post(reverse("contacts:contact_delete", args=[self.other_contact.pk])).status_code,
			200,
		)

	def test_contact_group_cannot_be_deleted_while_contacts_use_it(self):
		with self.assertRaises(ProtectedError):
			self.group.delete()

	def test_deleting_contact_owner_keeps_contact_with_no_owner(self):
		contact_id = self.owned_contact.pk
		self.owner.delete()

		self.owned_contact.refresh_from_db()
		self.assertIsNone(self.owned_contact.user)
		self.assertTrue(Contact.objects.filter(pk=contact_id).exists())

	def test_duplicate_api_identifies_email_matches_and_merges_with_archive(self):
		duplicate = self.make_contact(self.owner, "Owner Contact Copy", "+15550000009")
		duplicate.email = self.owned_contact.email.upper()
		duplicate.save(update_fields=("email",))
		self.client.force_login(self.owner)

		response = self.client.get(reverse("contact_duplicates"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["duplicates"][0]["matched_on"], ["email"])

		merge_response = self.client.post(
			reverse("contact_duplicates"),
			{"contact_id": duplicate.pk},
			content_type="application/json",
		)
		self.assertEqual(merge_response.status_code, 200, merge_response.content.decode())
		self.assertFalse(Contact.objects.filter(pk=duplicate.pk).exists())
		self.assertEqual(Contact.objects.filter(merge_archives__source_contact_id=duplicate.pk).count(), 1)

	def test_duplicate_detection_uses_name_group_and_birthday_as_strong_match(self):
		first = self.make_contact(self.owner, "Same Person", "+15550000011")
		second = self.make_contact(self.owner, " same   person ", "+15550000012")
		first.birthday = date(1990, 4, 3)
		second.birthday = date(1990, 4, 3)
		first.save(update_fields=("birthday",))
		second.save(update_fields=("birthday",))

		duplicates = find_duplicate_groups(Contact.objects.filter(user=self.owner))
		matching = next(group for group in duplicates if first in group["contacts"])
		self.assertEqual(matching["matched_on"], ["name+birthday+group"])
		self.assertIn(second, matching["contacts"])

	def test_duplicate_detection_does_not_chain_different_match_criteria(self):
		first = self.make_contact(self.owner, "Phone Match A", "+15550000031")
		middle = self.make_contact(self.owner, "Email Match B", "15550000031")
		last = self.make_contact(self.owner, "Email Match C", "+15550000032")
		middle.email = last.email
		middle.save(update_fields=("email",))

		duplicates = find_duplicate_groups(Contact.objects.filter(user=self.owner))
		member_sets = {frozenset(contact.pk for contact in group["contacts"]) for group in duplicates}

		self.assertEqual(
			member_sets,
			{frozenset((first.pk, middle.pk)), frozenset((middle.pk, last.pk))},
		)

	def test_automatic_duplicate_detection_ignores_contacts_without_an_owner(self):
		first = self.make_contact(None, "Unowned A", "+15550000041")
		second = self.make_contact(None, "Unowned B", "+15550000042")
		second.email = first.email
		second.save(update_fields=("email",))

		self.assertEqual(find_duplicate_groups(), [])
		self.assertEqual(merge_all_duplicate_contacts(), 0)
		self.assertTrue(Contact.objects.filter(pk__in=(first.pk, second.pk)).exists())

	def test_empty_owner_scope_does_not_fall_back_to_other_contacts(self):
		limited_user = User.objects.create_user(
			username="empty@example.com", email="empty@example.com", password="Mango!River482"
		)
		limited_user.groups.add(self.regular_role)
		self.client.force_login(limited_user)

		response = self.client.get(reverse("contact_duplicates"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["duplicates"], [])

	def test_contact_session_stores_recent_contacts_and_preferences(self):
		self.client.force_login(self.owner)
		self.client.get(reverse("contacts:contact_edit", args=[self.owned_contact.pk]))

		response = self.client.get(reverse("contact_session"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["recent_contacts"][0]["id"], self.owned_contact.pk)
		self.assertEqual(response.json()["preferences"]["page_size"], 25)

		update = self.client.post(
			reverse("contact_session"),
			{"page_size": 50},
			content_type="application/json",
		)
		self.assertEqual(update.status_code, 200)
		self.assertEqual(self.client.get(reverse("contact_session")).json()["preferences"]["page_size"], 50)

	def test_api_validation_errors_use_the_shared_error_shape(self):
		self.client.force_login(self.owner)
		response = self.client.post(
			reverse("contact_duplicates"),
			{"contact_id": "not-an-id"},
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.json()["error"], "validation_error")
		self.assertEqual(response.json()["status"], 400)
		self.assertFalse(response.json()["success"])

	def test_unhandled_api_exceptions_return_a_sanitized_server_error(self):
		with self.assertLogs("contacts.api_exceptions", level="ERROR"):
			response = custom_exception_handler(
				RuntimeError("private implementation detail"),
				{"view": None},
			)

		self.assertEqual(response.status_code, 500)
		self.assertFalse(response.data["success"])
		self.assertEqual(response.data["error"], "internal_server_error")
		self.assertNotIn("private implementation detail", response.data["detail"])

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_contact_reminders_send_once_per_contact_and_occurrence(self):
		self.owned_contact.birthday = date(1990, 6, 15)
		self.owned_contact.reminder_date = date(2026, 6, 15)
		self.owned_contact.reminder_note = "Renew membership"
		self.owned_contact.save(update_fields=("birthday", "reminder_date", "reminder_note"))

		first_run = send_due_contact_reminders.apply(args=["2026-06-15"]).get()
		second_run = send_due_contact_reminders.apply(args=["2026-06-15"]).get()

		self.assertEqual(first_run, 2)
		self.assertEqual(second_run, 0)
		self.assertEqual(len(mail.outbox), 2)
		self.assertEqual(self.owned_contact.reminder_deliveries.count(), 2)

	def test_password_reset_page_does_not_disclose_unknown_accounts(self):
		response = self.client.post(
			reverse("authentication:password_reset"),
			{"email": "not-registered@example.com"},
		)
		self.assertRedirects(
			response,
			reverse("authentication:password_reset_done"),
			fetch_redirect_response=False,
		)

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_password_reset_email_is_generated_by_the_async_task(self):
		user = User.objects.create_user(
			username="reset@example.com",
			email="reset@example.com",
			password="Mango!River482",
		)

		result = send_password_reset_email.apply(args=[user.pk]).get()

		self.assertEqual(result, 1)
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn("Reset your Contact Book password", mail.outbox[0].subject)
		reset_url = next(
			line for line in mail.outbox[0].body.splitlines()
			if "/accounts/password-reset/confirm/" in line
		)
		user.last_login = timezone.now()
		user.save(update_fields=("last_login",))

		response = self.client.get(urlsplit(reset_url).path)
		self.assertEqual(response.status_code, 302)
		self.assertContains(self.client.get(response["Location"]), "Choose a new password")

	@override_settings(
		EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
		CELERY_TASK_ALWAYS_EAGER=True,
	)
	def test_successful_password_reset_sends_account_security_notification(self):
		user = User.objects.create_user(
			username="changed-password@example.com",
			email="changed-password@example.com",
			password="Mango!River482",
		)
		uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
		token = contact_password_reset_token_generator.make_token(user)
		confirm_url = reverse(
			"authentication:password_reset_confirm",
			kwargs={"uidb64": uidb64, "token": token},
		)

		initial_response = self.client.get(confirm_url)
		self.assertEqual(initial_response.status_code, 302)
		confirm_path = self.client.get(initial_response["Location"]).wsgi_request.path
		with self.captureOnCommitCallbacks(execute=True):
			confirm_response = self.client.post(
				confirm_path,
				{"new_password1": "New!SecurePassword482", "new_password2": "New!SecurePassword482"},
			)

		self.assertEqual(confirm_response.status_code, 302)
		user.refresh_from_db()
		self.assertTrue(user.check_password("New!SecurePassword482"))
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn("password was changed", mail.outbox[0].subject)
