from django.contrib import admin
from .models import Bill, BillItem, BillPayment

admin.site.register(Bill)
admin.site.register(BillItem)
admin.site.register(BillPayment)
