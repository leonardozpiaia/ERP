from django.contrib.admin.apps import AdminConfig


class ErpAdminConfig(AdminConfig):
    default_site = "config.admin_site.ErpAdminSite"
