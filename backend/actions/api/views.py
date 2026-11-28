from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from actions import reasons, selectors, services
from actions.api.serializers import (
    ActionCreateSerializer,
    ActionSerializer,
    AssignSerializer,
    CallSerializer,
    CancelSerializer,
    CloseSerializer,
)
from catalog.models import Article
from core.api import TenantAPIView
from lots.models import Lot
from production.models import Equipment, LineStop
from tenants import selectors as tenant_selectors
from tenants.models import User
from tenants.permissions import has_role

R = User.Role


class ActionPermission(BasePermission):
    """Lecture : tous les roles. Creation : Admin, Production, Qualite. L'operateur appelle depuis un arret (call)
    et fait avancer les actions dont il est charge (controle dans le service)."""

    message = "Votre rôle ne permet pas cette action."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return has_role(request.user, *R.values)
        return has_role(request.user, *getattr(view, "write_roles", (R.ADMIN, R.PRODUCTION, R.QUALITE)))


def _found(model, pk, field):
    if pk is None:
        return None
    obj = model.objects.filter(pk=pk).first()
    if obj is None:  # inexistant OU d'une autre entreprise (RLS)
        raise ValidationError({field: ["Introuvable."]})
    return obj


def _person(request, pk):
    if pk is None:
        return None
    person = tenant_selectors.users_of_tenant(tenant_id=request.user.tenant_id).filter(pk=pk).first()
    if person is None:
        raise ValidationError({"responsible": ["Introuvable."]})
    return person


def _out(action, status_code=http.HTTP_200_OK):
    return Response(ActionSerializer(selectors.action_or_404(action.id)).data, status=status_code)


class ActionListView(TenantAPIView):
    permission_classes = [IsAuthenticated, ActionPermission]

    @extend_schema(responses={200: ActionSerializer(many=True)},
                   parameters=[OpenApiParameter("status", str, description="open (defaut), all ou un statut"),
                               OpenApiParameter("mine", bool, description="Mes actions (responsable ou auteur)")])
    def get(self, request):
        found = selectors.actions(status=request.query_params.get("status", "open"), user=request.user,
                                  mine=request.query_params.get("mine") in ("1", "true"))
        return Response(ActionSerializer([selectors.decorate(a) for a in found[:500]], many=True).data)

    @extend_schema(request=ActionCreateSerializer, responses={201: ActionSerializer})
    def post(self, request):
        s = ActionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        action = services.create_action(
            tenant_id=request.user.tenant_id, user=request.user, action_type=d["action_type"],
            subject_code=d["subject_code"], comment=d["comment"], priority=d["priority"], due_date=d["due_date"],
            responsible=_person(request, d.get("responsible")),
            line_stop=_found(LineStop, d.get("line_stop"), "line_stop"),
            equipment=_found(Equipment, d.get("equipment"), "equipment"), lot=_found(Lot, d.get("lot"), "lot"),
            article=_found(Article, d.get("article"), "article"), origin=d["origin"],
        )
        return _out(action, http.HTTP_201_CREATED)


class ActionDetailView(TenantAPIView):
    """Une action. Pas de modification directe ni de suppression : elle avance par etapes (attribuer, commencer,
    terminer, annuler)."""

    permission_classes = [IsAuthenticated, ActionPermission]

    @extend_schema(responses={200: ActionSerializer})
    def get(self, request, action_id):
        return Response(ActionSerializer(selectors.action_or_404(action_id)).data)


class ActionCallView(TenantAPIView):
    """Appel au poste depuis un arret : maintenance ou qualite, en un clic."""

    permission_classes = [IsAuthenticated, ActionPermission]
    write_roles = (R.ADMIN, R.PRODUCTION, R.QUALITE, R.OPERATEUR)

    @extend_schema(request=CallSerializer, responses={201: ActionSerializer})
    def post(self, request):
        s = CallSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        action = services.call_from_post(tenant_id=request.user.tenant_id, user=request.user,
                                         line_stop=_found(LineStop, s.validated_data["line_stop"], "line_stop"),
                                         action_type=s.validated_data["action_type"])
        return _out(action, http.HTTP_201_CREATED)


class ActionOptionsView(TenantAPIView):
    permission_classes = [IsAuthenticated, ActionPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        people = tenant_selectors.users_of_tenant(tenant_id=request.user.tenant_id).filter(is_active=True)
        return Response({
            "types": [{"code": c, "label": label} for c, label in reasons.TYPES.items()],
            "subjects": [{"code": c, "label": label, "action_type": t} for c, (t, label) in reasons.SUBJECTS.items()],
            "priorities": [{"code": c, "label": label} for c, label in reasons.PRIORITIES.items()],
            "results": [{"code": c, "label": label} for c, label in reasons.RESULTS.items()],
            "cancel_reasons": [{"code": c, "label": label} for c, label in reasons.CANCEL.items()],
            "people": [{"id": str(u.id), "username": u.username, "name": u.get_full_name() or u.username,
                        "role": u.role} for u in people],
        })


class ActionAlertsView(TenantAPIView):
    permission_classes = [IsAuthenticated, ActionPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(selectors.current_alerts())


class _ActionStepView(TenantAPIView):
    permission_classes = [IsAuthenticated, ActionPermission]
    write_roles = (R.ADMIN, R.PRODUCTION, R.QUALITE, R.OPERATEUR)


class ActionAssignView(_ActionStepView):
    write_roles = (R.ADMIN, R.PRODUCTION, R.QUALITE)

    @extend_schema(request=AssignSerializer, responses={200: ActionSerializer})
    def post(self, request, action_id):
        selectors.action_or_404(action_id)
        s = AssignSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        action = services.assign_action(tenant_id=request.user.tenant_id, user=request.user, action_id=action_id,
                                        responsible=_person(request, d.get("responsible")),
                                        due_date=d.get("due_date"), priority=d.get("priority"))
        return _out(action)


class ActionStartView(_ActionStepView):
    @extend_schema(request=None, responses={200: ActionSerializer})
    def post(self, request, action_id):
        selectors.action_or_404(action_id)
        return _out(services.start_action(tenant_id=request.user.tenant_id, user=request.user, action_id=action_id))


class ActionCloseView(_ActionStepView):
    @extend_schema(request=CloseSerializer, responses={200: ActionSerializer})
    def post(self, request, action_id):
        selectors.action_or_404(action_id)
        s = CloseSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return _out(services.close_action(tenant_id=request.user.tenant_id, user=request.user, action_id=action_id,
                                          result_code=s.validated_data["result_code"],
                                          comment=s.validated_data["comment"]))


class ActionCancelView(_ActionStepView):
    write_roles = (R.ADMIN, R.PRODUCTION, R.QUALITE)

    @extend_schema(request=CancelSerializer, responses={200: ActionSerializer})
    def post(self, request, action_id):
        selectors.action_or_404(action_id)
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return _out(services.cancel_action(tenant_id=request.user.tenant_id, user=request.user, action_id=action_id,
                                           reason_code=s.validated_data["reason_code"],
                                           comment=s.validated_data["comment"]))
