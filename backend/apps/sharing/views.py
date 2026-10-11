from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.vault.models import Credential
from core.permissions import Perm, has_perm
from core.tenancy import get_in_org_or_404

from . import services
from .models import Share
from .serializers import DelegationTreeSerializer, PersonSerializer, RevokeSerializer, ShareSerializer


class ShareViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Grants you gave or received (direction=given|received). Admins with shares.view_all see the whole org."""

    queryset = Share.objects.none()  # for schema generation; get_queryset() scopes to the caller
    serializer_class = ShareSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Share.objects.filter(organization=user.organization).select_related(
            "credential", "grantor__department", "grantee__department", "revoked_by"
        )
        direction = self.request.query_params.get("direction")
        if direction == "given":
            queryset = queryset.filter(grantor=user)
        elif direction == "received":
            queryset = queryset.filter(grantee=user)
        elif not has_perm(user, Perm.SHARES_VIEW_ALL):
            queryset = queryset.filter(Q(grantor=user) | Q(grantee=user) | Q(credential__owner=user))
        credential = self.request.query_params.get("credential")
        if credential:
            queryset = queryset.filter(credential_id=credential)
        state = self.request.query_params.get("state")
        now = timezone.now()
        if state == "active":
            queryset = queryset.filter(revoked_at__isnull=True, burned_at__isnull=True, expires_at__gt=now)
        elif state == "revoked":
            queryset = queryset.filter(revoked_at__isnull=False)
        elif state == "expired":
            queryset = queryset.filter(revoked_at__isnull=True, burned_at__isnull=True, expires_at__lte=now)
        elif state == "consumed":
            queryset = queryset.filter(burned_at__isnull=False)
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("direction", str, enum=["given", "received"]),
            OpenApiParameter("state", str, enum=["active", "expired", "revoked", "consumed"]),
            OpenApiParameter("credential", str),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_object(self):
        # Revocation is allowed for people who may not otherwise list the grant (e.g. an ancestor grantee),
        # so look it up org-wide and let services.can_revoke decide.
        return get_in_org_or_404(
            Share.objects.select_related("credential", "parent_share"),
            self.request.user.organization,
            self.kwargs["pk"],
        )

    def retrieve(self, request, *args, **kwargs):
        share = self.get_object()
        if not (
            has_perm(request.user, Perm.SHARES_VIEW_ALL)
            or request.user.pk in (share.grantor_id, share.grantee_id, share.credential.owner_id)
        ):
            raise Http404
        return Response(ShareSerializer(share).data)

    @extend_schema(request=None, responses={200: RevokeSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        revoked = services.revoke_share(actor=request.user, share=self.get_object())
        return Response({"revoked": revoked})


class DelegationTreeView(APIView):
    """The delegation tree of one credential.

    Owner and administrators with shares.view_all: every grant. A grantee holding SHARE: their own grant and
    everything delegated beneath it. Anyone else: 404. Metadata only, never secrets.
    """

    @extend_schema(responses={200: DelegationTreeSerializer})
    def get(self, request, credential_id):
        user = request.user
        credential = get_in_org_or_404(Credential.objects.select_related("owner"), user.organization, credential_id)

        shares = list(
            Share.objects.filter(credential=credential)
            .select_related("grantor", "grantee")
            .order_by("depth", "created_at")
        )
        if credential.owner_id != user.pk and not has_perm(user, Perm.SHARES_VIEW_ALL):
            roots = {s.pk for s in shares if s.grantee_id == user.pk}
            if not roots:
                raise Http404
            visible = set(roots)
            for share in shares:  # ordered by depth: parents come first
                if share.parent_share_id in visible:
                    visible.add(share.pk)
            shares = [s for s in shares if s.pk in visible]

        now = timezone.now()
        nodes = [
            {
                "id": s.pk,
                "parent_share": s.parent_share_id,
                "depth": s.depth,
                "grantor": s.grantor.full_name,
                "grantee": s.grantee.full_name,
                "grantee_email": s.grantee.email,
                "permission": s.permission,
                "state": s.state(now),
                "expires_at": s.expires_at,
                "is_view_once": s.is_view_once,
                "created_at": s.created_at,
            }
            for s in shares
        ]
        data = {
            "credential": credential.pk,
            "credential_title": credential.title,
            "owner": credential.owner.full_name,
            "nodes": nodes,
        }
        return Response(DelegationTreeSerializer(data).data)


class PeopleView(generics.ListAPIView):
    """Active colleagues, for choosing whom to share with. Minimal fields only."""

    queryset = User.objects.none()  # for schema generation; get_queryset() scopes to the caller
    serializer_class = PersonSerializer
    search_fields = ["full_name", "email"]

    def get_queryset(self):
        user = self.request.user
        return (
            User.objects.filter(organization=user.organization, status=User.Status.ACTIVE)
            .exclude(pk=user.pk)
            .select_related("department")
        )
