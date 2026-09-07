from django.db import migrations

LABEL_TO_VALUE = {
    "Visa suma": "visa_suma",
    "Po pristatymo": "po_pristatymo",
    "Avansas": "avansas",
}


def forwards(apps, schema_editor):
    ClientOrder = apps.get_model("main", "ClientOrder")
    for label, value in LABEL_TO_VALUE.items():
        ClientOrder.objects.filter(payment_type=label).update(payment_type=value)


def backwards(apps, schema_editor):
    ClientOrder = apps.get_model("main", "ClientOrder")
    for label, value in LABEL_TO_VALUE.items():
        ClientOrder.objects.filter(payment_type=value).update(payment_type=label)


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0018_add_indexes"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
