from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin):
    roles_requis = []

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if request.user.is_authenticated:
            try:
                role = request.user.profile.role
            except Exception:
                raise PermissionDenied
            if self.roles_requis and role not in self.roles_requis:
                raise PermissionDenied
        return response


class AdminRequiredMixin(RoleRequiredMixin):
    roles_requis = ['admin']


class MaintenanceRequiredMixin(RoleRequiredMixin):
    roles_requis = ['admin', 'maintenance']


class SiloRequiredMixin(RoleRequiredMixin):
    roles_requis = ['admin', 'maintenance', 'silo']


def get_sites_utilisateur(user):
    """Retourne les sites accessibles selon le rôle."""
    try:
        profile = user.profile
    except Exception:
        return []
    if profile.is_admin():
        from .models import Site
        return Site.objects.all()
    return profile.sites.all()
