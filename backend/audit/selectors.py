"""Lectures du journal d'audit. Pas de filtre tenant ici : la RLS de PostgreSQL le fait."""

from audit.models import AuditLog


def audit_entries(*, entity_type=None, entity_id=None, action=None, user_id=None, date_from=None, date_to=None):
    qs = AuditLog.objects.select_related("user").order_by("-created_at", "-id")
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if entity_id:
        qs = qs.filter(entity_id=entity_id)
    if action:
        qs = qs.filter(action=action)
    if user_id:
        qs = qs.filter(user_id=user_id)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


# Presentation lisible ----------------------------------------------------------
# Le journal stocke des identifiants (UUID). Pour l'ecran, on les traduit en noms, page par page, avec les
# droits de l'utilisateur : la RLS ne laisse voir que les objets de son entreprise. Rien n'est reecrit.

UUID_KEYS = ("_id",)


def entry_uuids(entry):
    found = {str(entry.entity_id)} if entry.entity_id else set()
    for values in (entry.old_values or {}, entry.new_values or {}):
        for key, value in values.items():
            if key.endswith(UUID_KEYS) and isinstance(value, str) and len(value) == 36:
                found.add(value)
    return found


def describe(entries):
    """Retourne (sujets, refs) : sujets[id] = {"subject", "unit"} pour l'objet de chaque ligne,
    refs = {uuid: nom lisible} pour tous les identifiants cites dans la page."""
    from django.apps import apps

    ids = set().union(*(entry_uuids(e) for e in entries)) if entries else set()
    names, units = {}, {}

    def lot_name(lot):
        return f"{lot.code} · {lot.article.code} {lot.article.name}"

    Article = apps.get_model("catalog", "Article")
    Partner = apps.get_model("catalog", "Partner")
    Conversion = apps.get_model("catalog", "UnitConversion")
    Site = apps.get_model("tenants", "Site")
    Lot = apps.get_model("lots", "Lot")
    Movement = apps.get_model("lots", "Movement")
    Approval = apps.get_model("lots", "ApprovalRequest")
    LotLink = apps.get_model("lots", "LotLink")

    for a in Article.objects.filter(pk__in=ids):
        names[str(a.pk)], units[str(a.pk)] = f"{a.code} {a.name}", a.base_unit
    for p in Partner.objects.filter(pk__in=ids):
        names[str(p.pk)] = p.name
    for s in Site.objects.filter(pk__in=ids):
        names[str(s.pk)] = s.name
    for c in Conversion.objects.filter(pk__in=ids).select_related("article"):
        names[str(c.pk)] = f"{c.unit_name} · {c.article.code} {c.article.name}"
        units[str(c.pk)] = c.article.base_unit
    for lot in Lot.objects.filter(pk__in=ids).select_related("article"):
        names[str(lot.pk)], units[str(lot.pk)] = lot_name(lot), lot.article.base_unit
    for m in Movement.objects.filter(pk__in=ids).select_related("lot__article"):
        names[str(m.pk)] = f"{m.get_movement_type_display()} · {m.lot.code}"
        units[str(m.pk)] = m.lot.article.base_unit
    for r in Approval.objects.filter(pk__in=ids).select_related("lot__article"):
        names[str(r.pk)] = f"{r.get_action_display()} · {r.lot.code}"
        units[str(r.pk)] = r.lot.article.base_unit
    for link in LotLink.objects.filter(pk__in=ids).select_related("parent_lot", "child_lot"):
        names[str(link.pk)] = f"{link.parent_lot.code} → {link.child_lot.code}"
    Parcel = apps.get_model("catalog", "Parcel")
    Check = apps.get_model("lots", "QualityCheck")
    Equipment = apps.get_model("production", "Equipment")
    Run = apps.get_model("production", "ProductionRun")
    Shipment = apps.get_model("shipping", "Shipment")
    for parcel in Parcel.objects.filter(pk__in=ids).select_related("producer"):
        names[str(parcel.pk)] = f"{parcel.code} · {parcel.producer.name}"
    for check in Check.objects.filter(pk__in=ids).select_related("lot__article"):
        names[str(check.pk)] = f"Contrôle · {check.lot.code}"
        units[str(check.pk)] = check.lot.article.base_unit
    for equipment in Equipment.objects.filter(pk__in=ids):
        names[str(equipment.pk)] = f"{equipment.code} {equipment.name}"
    for run in Run.objects.filter(pk__in=ids).select_related("output_lot__article"):
        names[str(run.pk)] = f"{run.get_step_display()} · {run.output_lot.code}"
        units[str(run.pk)] = run.output_lot.article.base_unit
    for shipment in Shipment.objects.filter(pk__in=ids).select_related("customer"):
        names[str(shipment.pk)] = f"{shipment.customer.name}" + (
            f" · {shipment.container_number}" if shipment.container_number else ""
        )
    if entries:
        # Table des utilisateurs sans RLS : on passe par le selecteur, filtre par entreprise.
        from tenants.selectors import users_of_tenant

        for u in users_of_tenant(tenant_id=entries[0].tenant_id).filter(pk__in=ids):
            names[str(u.pk)] = u.username

    subjects = {}
    for e in entries:
        key = str(e.entity_id) if e.entity_id else ""
        values = e.new_values or e.old_values or {}
        fallback = " ".join(str(values[k]) for k in ("code", "name", "username") if values.get(k))
        subjects[e.pk] = {"subject": names.get(key, fallback), "unit": units.get(key)}
    return subjects, names
