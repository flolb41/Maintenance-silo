from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from maintenance import views as maintenance_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("media/pannes/<path:chemin>", maintenance_views.panne_media_prive),
    path("media/factures/<path:chemin>",
         maintenance_views.facture_media_prive),
    path(
        "auth/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path(
        "auth/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "auth/mot-de-passe/modifier/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change_form.html",
        ),
        name="password_change",
    ),
    path(
        "auth/mot-de-passe/modifie/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html",
        ),
        name="password_change_done",
    ),
    path(
        "auth/mot-de-passe/oublie/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "auth/mot-de-passe/email-envoye/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "auth/reinitialisation/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
        ),
        name="password_reset_confirm",
    ),
    path(
        "auth/reinitialisation/terminee/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("vehicules/", include("vehicules.urls")),
    path("", include("maintenance.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
