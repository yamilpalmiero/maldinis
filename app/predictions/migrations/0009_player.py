import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('predictions', '0008_specialprediction_golden_glove'),
    ]

    operations = [
        migrations.CreateModel(
            name='Player',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('position', models.CharField(
                    blank=True,
                    choices=[('GK', 'Portero'), ('DEF', 'Defensor'), ('MID', 'Mediocampista'), ('FWD', 'Delantero')],
                    max_length=3,
                )),
                ('external_id', models.IntegerField(
                    blank=True,
                    help_text='ID del jugador en Football-Data.org',
                    null=True,
                    unique=True,
                )),
                ('shirt_number', models.IntegerField(blank=True, null=True)),
                ('date_of_birth', models.DateField(blank=True, null=True)),
                ('photo_url', models.URLField(blank=True)),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='Marcar False si el jugador ya no está en el plantel activo',
                )),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='players',
                    to='predictions.team',
                )),
            ],
            options={
                'ordering': ['team__name', 'position', 'name'],
            },
        ),
    ]
