from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import DelegationTreeView, PeopleView, ShareViewSet

router = SimpleRouter(trailing_slash=True)
router.register("shares", ShareViewSet, basename="share")

urlpatterns = [
    path("shares/tree/<str:credential_id>/", DelegationTreeView.as_view(), name="delegation-tree"),
    path("people/", PeopleView.as_view(), name="people"),
    *router.urls,
]
