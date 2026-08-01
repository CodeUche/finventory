"""
Permissions for the employee self-service portal.

This is the first non-operator user class to touch tenant data, so the rule is
deliberately narrow: an ESS request may only ever see rows belonging to the one
Employee record linked to the calling user. Nothing here widens by role — an
owner hitting /me still only sees their own employee record (or a 404 if they
do not have one), because /me is not an admin surface.
"""

from rest_framework.permissions import BasePermission


def get_employee_for(request):
    """
    Return the Employee linked to the authenticated user, or None.

    Resolved through the OneToOne on Employee rather than through membership so
    that a user with several memberships can never read another org's employee
    record by switching the X-Organisation-ID header.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None
    from .models import Employee

    return (
        Employee.objects
        .filter(user=user, is_active=True)
        .select_related('organisation', 'manager')
        .first()
    )


class IsEmployeeSelf(BasePermission):
    """
    Grants access only to a user that has an Employee record.

    Object-level checks confirm the row actually belongs to that employee, so a
    view that forgets to filter its queryset still cannot leak another
    employee's payslip.
    """

    message = 'This area is only available to employees with a portal account.'

    def has_permission(self, request, view):
        employee = get_employee_for(request)
        if employee is None:
            return False
        # Cache on the request so views and serializers do not re-query.
        request.employee = employee
        return True

    def has_object_permission(self, request, view, obj):
        employee = getattr(request, 'employee', None) or get_employee_for(request)
        if employee is None:
            return False

        # Direct Employee objects
        if obj.__class__.__name__ == 'Employee':
            return obj.id == employee.id

        # Anything hanging off an employee
        obj_employee_id = getattr(obj, 'employee_id', None)
        if obj_employee_id is not None:
            return str(obj_employee_id) == str(employee.id)

        # Payslip deliveries reach the employee through the payslip
        payslip = getattr(obj, 'payslip', None)
        if payslip is not None:
            return str(payslip.employee_id) == str(employee.id)

        return False
