from django.contrib import admin
from .models import Employee, PayrollRun, PayslipLine

admin.site.register(Employee)
admin.site.register(PayrollRun)
admin.site.register(PayslipLine)
