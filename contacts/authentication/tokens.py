from django.contrib.auth.tokens import PasswordResetTokenGenerator


class ContactPasswordResetTokenGenerator(PasswordResetTokenGenerator):
    """Keep reset links valid across sign-ins; password changes still invalidate them."""

    def _make_hash_value(self, user, timestamp):
        return "{}:{}:{}:{}".format(
            user.pk,
            user.password,
            timestamp,
            user.email,
        )


contact_password_reset_token_generator = ContactPasswordResetTokenGenerator()
