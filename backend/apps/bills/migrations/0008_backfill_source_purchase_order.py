"""Backfill Bill.source_purchase_order for bills that were auto-created from a
PO before the FK existed — matched the only way they could be at the time,
by (organisation, reference == po_number). Best-effort: bills with no matching
PO (e.g. reference was hand-edited afterwards) are left as-is."""

from django.db import migrations


def backfill(apps, schema_editor):
    Bill = apps.get_model('bills', 'Bill')
    PurchaseOrder = apps.get_model('purchases', 'PurchaseOrder')

    po_by_org_number = {
        (po.organisation_id, po.po_number): po.id
        for po in PurchaseOrder.objects.all().only('id', 'organisation_id', 'po_number')
    }

    updated = 0
    for bill in Bill.objects.filter(source_purchase_order__isnull=True).exclude(reference=''):
        po_id = po_by_org_number.get((bill.organisation_id, bill.reference))
        if po_id:
            bill.source_purchase_order_id = po_id
            bill.save(update_fields=['source_purchase_order'])
            updated += 1


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('bills', '0007_bill_source_purchase_order'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
