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
        subtotal = Decimal('0')
        tax_total = Decimal('0')
        for item_data in items_data_list:
            product = item_data['product']
            qty = item_data['quantity']
            price = item_data.get('unit_price', product.selling_price)
            discount_pct = item_data.get('discount_percent', Decimal('0'))
            tax_rate = item_data.get('tax_rate', Decimal('0'))
            line = qty * price * (1 - discount_pct / 100)
            tax = line * (tax_rate / 100)
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
            subtotal += line
            tax_total += tax
        quote.subtotal = subtotal
        quote.tax_amount = tax_total
        quote.total_amount = subtotal + tax_total
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
        quote.status = Quote.CONVERTED
        quote.converted_invoice = invoice
        quote.save()
        return invoice
