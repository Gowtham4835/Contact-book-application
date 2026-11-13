from django.db import migrations


CONTACT_PERMISSIONS = {
    "add_contact": "Can add contact",
    "change_contact": "Can change contact",
    "delete_contact": "Can delete contact",
    "view_contact": "Can view contact",
    "manage_all_contacts": "Can manage all contacts",
}


def create_contact_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="contacts",
        model="contact",
    )
    permissions = {}
    for codename, name in CONTACT_PERMISSIONS.items():
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions[codename] = permission

    regular_users, _ = Group.objects.get_or_create(name="Regular Users")
    admins, _ = Group.objects.get_or_create(name="Admins")
    super_admins, _ = Group.objects.get_or_create(name="Super Admins")

    regular_permission_ids = [
        permissions[codename].pk
        for codename in ("add_contact", "change_contact", "delete_contact", "view_contact")
    ]
    admin_permission_ids = [permission.pk for permission in permissions.values()]

    regular_users.permissions.add(*regular_permission_ids)
    admins.permissions.add(*admin_permission_ids)
    super_admins.permissions.add(*admin_permission_ids)


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="contact",
            options={
                "permissions": [("manage_all_contacts", "Can manage all contacts")],
            },
        ),
        migrations.RunPython(create_contact_roles, migrations.RunPython.noop),
    ]