from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Group
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
)
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView

from contacts.forms import LoginForm, RegistrationForm
from contacts.tasks import send_account_notification, send_password_reset_email
from .tokens import contact_password_reset_token_generator


User = get_user_model()


def store_user_session_context(request, user):
    request.session["contact_book"] = {
        "roles": list(user.groups.order_by("name").values_list("name", flat=True)),
        "permissions": sorted(user.get_all_permissions()),
        "preferences": {"page_size": 25},
    }

class RegistrationView(FormView):
    template_name = "authentication/register.html"
    form_class = RegistrationForm

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        
        user = User.objects.create_user(username=email, email=email, password=password)
        regular_group, _ = Group.objects.get_or_create(name="Regular Users")
        user.groups.add(regular_group)
        login(self.request, user)
        store_user_session_context(self.request, user)
        transaction.on_commit(
            lambda user_id=user.pk: send_account_notification.delay(
                user_id,
                "Welcome to Contact Book",
                "Your Contact Book account was created successfully.",
            ),
            robust=True,
        )
        return redirect("contacts:contact_list")
    
class LoginView(FormView):
    template_name = "authentication/login.html"
    form_class = LoginForm

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        
        user = authenticate(self.request, username=email, password=password)
        if user is not None:
            login(self.request, user)
            store_user_session_context(self.request, user)
            return redirect("contacts:contact_list")
        
        form.add_error(None, "Invalid email or password.")
        return self.form_invalid(form)
    
class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect("authentication:login")


class PasswordResetRequestView(FormView):
    template_name = "authentication/password_reset.html"
    form_class = PasswordResetForm
    success_url = reverse_lazy("authentication:password_reset_done")

    def form_valid(self, form):
        for user in form.get_users(form.cleaned_data["email"]):
            transaction.on_commit(
                lambda user_id=user.pk: send_password_reset_email.delay(user_id),
                robust=True,
            )
        return super().form_valid(form)


class PasswordResetConfirmPageView(PasswordResetConfirmView):
    template_name = "authentication/password_reset_confirm.html"
    success_url = reverse_lazy("authentication:password_reset_complete")
    token_generator = contact_password_reset_token_generator

    def form_valid(self, form):
        user = form.user
        response = super().form_valid(form)
        transaction.on_commit(
            lambda user_id=user.pk: send_account_notification.delay(
                user_id,
                "Your Contact Book password was changed",
                "Your Contact Book password was successfully changed. If you did not make this change, contact support.",
            ),
            robust=True,
        )
        return response


class PasswordResetDonePageView(PasswordResetDoneView):
    template_name = "authentication/password_reset_done.html"


class PasswordResetCompletePageView(PasswordResetCompleteView):
    template_name = "authentication/password_reset_complete.html"