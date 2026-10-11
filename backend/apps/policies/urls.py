from django.urls import path

from .views import SecurityPolicyView

urlpatterns = [path("policy/", SecurityPolicyView.as_view(), name="security-policy")]
