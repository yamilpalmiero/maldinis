from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('predictions', '0004_match_external_id_match_status_alter_match_away_team_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='home_source',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='match',
            name='away_source',
            field=models.CharField(blank=True, max_length=50),
        ),
    ]