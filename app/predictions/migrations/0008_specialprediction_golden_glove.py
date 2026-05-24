from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('predictions', '0007_bracketprediction_groupprediction_thirdplaceranking_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='specialprediction',
            name='golden_glove',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
