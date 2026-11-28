from rest_framework import serializers


class ActionCreateSerializer(serializers.Serializer):
    action_type = serializers.CharField()
    subject_code = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    priority = serializers.CharField(required=False, default="normale")
    due_date = serializers.DateField()
    responsible = serializers.UUIDField(required=False, allow_null=True)
    line_stop = serializers.UUIDField(required=False, allow_null=True)
    equipment = serializers.UUIDField(required=False, allow_null=True)
    lot = serializers.UUIDField(required=False, allow_null=True)
    article = serializers.UUIDField(required=False, allow_null=True)
    origin = serializers.ChoiceField(choices=["saisie", "alerte"], required=False, default="saisie")


class CallSerializer(serializers.Serializer):
    line_stop = serializers.UUIDField()
    action_type = serializers.ChoiceField(choices=["maintenance", "qualite"])


class AssignSerializer(serializers.Serializer):
    responsible = serializers.UUIDField(allow_null=True)
    due_date = serializers.DateField(required=False)
    priority = serializers.CharField(required=False)


class CloseSerializer(serializers.Serializer):
    result_code = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class CancelSerializer(serializers.Serializer):
    reason_code = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class _Ref(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()


class ActionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    action_type = serializers.CharField()
    type_label = serializers.CharField()
    subject_code = serializers.CharField()
    subject = serializers.CharField()
    comment = serializers.CharField()
    priority = serializers.CharField()
    origin = serializers.CharField()
    status = serializers.CharField()
    status_label = serializers.CharField(source="get_status_display")
    late = serializers.BooleanField()
    due_date = serializers.DateField()
    responsible = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)
    result = serializers.CharField()
    result_comment = serializers.CharField()
    cancel_reason = serializers.CharField()
    line_stop = serializers.SerializerMethodField()
    equipment = serializers.SerializerMethodField()
    lot = serializers.SerializerMethodField()
    article = serializers.SerializerMethodField()

    @staticmethod
    def _user(user):
        if user is None:
            return None
        return {"id": str(user.id), "username": user.username, "name": user.get_full_name() or user.username}

    def get_responsible(self, a):
        return self._user(a.responsible)

    def get_created_by(self, a):
        return self._user(a.created_by)

    def get_line_stop(self, a):
        s = a.line_stop
        return {"id": str(s.id), "started_at": s.started_at, "ended_at": s.ended_at} if s else None

    def get_equipment(self, a):
        e = a.equipment
        return {"id": str(e.id), "code": e.code, "name": e.name} if e else None

    def get_lot(self, a):
        return {"id": str(a.lot.id), "code": a.lot.code} if a.lot else None

    def get_article(self, a):
        return {"id": str(a.article.id), "code": a.article.code, "name": a.article.name} if a.article else None
