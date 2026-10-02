from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Quote, QuoteItem


class QuoteService:
    @staticmethod
    @transaction.atomic
    def create_quote(validated_data, items_data, organisation, user):
        items_data_list = items_data
        quote = Quote.objects.create(
            organisation=organisation,
            created_by=user,
            **validated_data
        )
        # Priced exactly as the invoice it converts into will be (SaleService's
        # per-line rounding and inclusive/exclusive VAT rule). Quotes took the
        # rate only from the request — which the Quotes screen never sends — so
        # a taxed product was quoted without VAT and invoiced with it: quoted
        # 3,000, billed 3,225.
        from apps.core.utils import round_money
        from apps.sales.services import SaleService

        total = Decimal('0')
        tax_total = Decimal('0')
        for item_data in items_data_list:
            product = item_data['product']
            qty = item_data['quantity']
            price = item_data.get('unit_price', product.selling_price)
            discount_pct = item_data.get('discount_percent', Decimal('0'))
            tax_rate = item_data.get('tax_rate')
            if tax_rate is None:
                tax_rate = SaleService.default_tax_rate(product)
            gross = round_money(qty * price)
            line = gross - round_money(gross * discount_pct / Decimal('100'))
            tax, line_with_tax = SaleService.apply_tax(product, line, tax_rate)
            QuoteItem.objects.create(
                organisation=organisation,
                quote=quote,
                product=product,
                quantity=qty,
                unit_price=price,
                discount_percent=discount_pct,
                tax_rate=tax_rate,
                line_total=line,
            )
            total += line_with_tax
            tax_total += tax
        quote.subtotal = total - tax_total
        quote.tax_amount = tax_total
        quote.total_amount = total
        quote.save()
        return quote

    @staticmethod
    @transaction.atomic
    def convert_to_invoice(quote, user):
        if quote.status == Quote.CONVERTED:
            raise ValueError("Quote already converted")
        from apps.sales.services import SaleService
        # Build items list for SaleService
        items = []
        for qi in quote.items.all():
            items.append({
                'product_id': str(qi.product_id),
                'quantity': qi.quantity,
                'unit_price': qi.unit_price,
                'discount_percent': qi.discount_percent,
                # Bill the VAT that was quoted, even if the product's tax setup
                # changed since.
                'tax_rate': qi.tax_rate,
            })
        # Use credit if there's a named customer, bank_transfer otherwise
        payment_method = 'credit' if quote.customer else 'bank_transfer'
        invoice = SaleService.create_sale(
            organisation=quote.organisation,
            created_by=user,
            customer=quote.customer,
            warehouse=quote.warehouse,
            items=items,
            payment_method=payment_method,
            notes=quote.notes,
            issue_date=timezone.now().date(),
        )
        previous_status = quote.status
        quote.status = Quote.CONVERTED
        quote.converted_invoice = invoice
        quote.save()

        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.UPDATE,
                user=user,
                organisation=quote.organisation,
                model_name='Quote',
                object_id=str(quote.id),
                object_repr=str(quote),
                changes={'status': {'old': previous_status, 'new': quote.status}},
            )
        except Exception:
            pass

        return invoice
