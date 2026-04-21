from django.db import models
from django.contrib.auth.models import User


class UserSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    rules_seen = models.BooleanField(default=False)

    def __str__(self):
        return f"Settings de {self.user.username}"