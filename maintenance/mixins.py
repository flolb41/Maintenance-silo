from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

from .models import Profile, Site


def get_sites_utilisateur(user):
    """Retourne les sites autorisés pour un utilisateur."""
    if user is None or not getattr(user, "is_authenticated", False):
        return Site.objects.none()

    if getattr(user, "is_superuser", False):
        return Site.objects.filter(actif=True).order_by("nom")

    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return Site.objects.none()

    if profile.is_admin() or profile.is_maintenance():
        return Site.objects.filter(actif=True).order_by("nom")

    # Seuls les agents de silo sont rattachés à un site spécifique.
    return Site.objects.filter(utilisateurs=user, actif=True).order_by("nom")


class _ProfileRequiredMixin(AccessMixin):
    permission_denied_message = "Accès interdit."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            raise PermissionDenied("Aucun profil défini pour cet utilisateur.")

        if not self._user_allowed(profile):
            raise PermissionDenied(self.permission_denied_message)

        return super().dispatch(request, *args, **kwargs)

    def _user_allowed(self, profile):
        return False


class AdminRequiredMixin(_ProfileRequiredMixin):
    permission_denied_message = "Accès réservé à l'administrateur."

    def _user_allowed(self, profile):
        return profile.is_admin()


class MaintenanceRequiredMixin(_ProfileRequiredMixin):
    permission_denied_message = "Accès réservé au service maintenance."

    def _user_allowed(self, profile):
        return profile.is_admin() or profile.is_maintenance()


class SiloRequiredMixin(_ProfileRequiredMixin):
    permission_denied_message = "Accès réservé au service silo."

    def _user_allowed(self, profile):
        return profile.is_admin() or profile.is_silo()


class AdminSiloRequiredMixin(_ProfileRequiredMixin):
    permission_denied_message = "Accès réservé à l'administration ou au service silo."

    def _user_allowed(self, profile):
        return profile.is_admin() or profile.is_silo()


class AdminSiloMaintenanceRequiredMixin(_ProfileRequiredMixin):
    permission_denied_message = "Accès réservé aux équipes opérationnelles."

    def _user_allowed(self, profile):
        return profile.is_admin() or profile.is_silo() or profile.is_maintenance()
