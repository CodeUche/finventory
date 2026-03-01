from django.contrib import admin
from .models import PaymentGatewayConfig, PaymentLink

admin.site.register(PaymentGatewayConfig)
admin.site.register(PaymentLink)
