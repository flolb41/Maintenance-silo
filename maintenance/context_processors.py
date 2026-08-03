def notifications_non_lues(request):
    if request.user.is_authenticated:
        count = request.user.notifications.filter(lue=False).count()
        notifications = request.user.notifications.filter(lue=False).order_by('-created_at')[:10]
    else:
        count = 0
        notifications = []
    return {
        'notif_count': count,
        'notifs_non_lues': notifications,
    }
