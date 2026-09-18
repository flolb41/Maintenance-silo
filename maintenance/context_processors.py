from .models import Notification, Profile


def navigation_context(request):
    if not request.user.is_authenticated:
        return {"profile": None}

    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = None

    return {
        "profile": profile,
        "notifications_non_lues": Notification.objects.filter(
            utilisateur=request.user,
            lue=False,
        ).count(),
    }
