from cProfile import label
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import FactoryOrder
from django.shortcuts import redirect, render
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .models import Order, FactoryOrder, Transport

# Deposit types are checked in this order — Deposit is resolved before
# Final Payment, so the card shows whichever is still outstanding first.
DEPOSIT_TYPE_PRIORITY = {"Deposit": 0, "Final Payment": 1, "Full Payment": 0}


def _compute_deposit_status(deposits, today):
    """
    deposits: an iterable of DepositClient or DepositFactory rows for one
    order (there are normally two: "Deposit" and "Final Payment").

    Returns a dict describing which single badge to show on the card.
    """
    deposits = list(deposits)
    if not deposits:
        return {
            "token": "due",
            "paid": False,
            "label": "No deposit info",
            "deposit_type": None,
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    unpaid = [d for d in deposits if not d.is_paid]
    if not unpaid:
        return {
            "token": "paid",
            "paid": True,
            "label": "Paid ✓",
            "deposit_type": None,
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    unpaid.sort(key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99))
    active = unpaid[0]
    # Prefer unpaid payments that actually have a due date.
    dated_unpaid = sorted((d for d in unpaid if d.payment_due_by),
        key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99),
    )
    if dated_unpaid:
        active = dated_unpaid[0]
    else:
        unpaid.sort(key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99))
        active = unpaid[0]

    days_remaining = None
    overdue = False
    if active.payment_due_by:
        days_remaining = (active.payment_due_by - today).days
        overdue = days_remaining < 0

    if days_remaining is None:
        label = f"{active.deposit_type.type_name} due"
    elif overdue:
        label = f"{active.deposit_type.type_name} overdue by {abs(days_remaining)} days"
    else:
        label = f"{active.deposit_type.type_name} due in {days_remaining} days"

    return {
        "token": "overdue" if overdue else "due",
        "paid": False,
        "label": label,
        "deposit_type": active.deposit_type.type_name,
        "days_remaining": days_remaining,
        "overdue": overdue,
        "reminder_sent": active.is_reminder_sent,
    }


def _compute_transport_status(transport, today):
    if not transport:
        return {
            "token": "pending",
            "label": "Transport pending",
            "courier": "",
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    courier = (transport.courier or "").strip()
    confirmed = bool(courier)

    days_remaining = None
    overdue = False
    if transport.delivery_date:
        days_remaining = (transport.delivery_date - today).days
        overdue = days_remaining < 0 and not confirmed

    if confirmed:
        token = "confirmed"
        label = "Transport confirmed"
    elif overdue:
        token = "overdue"
        label = f"Transport pending · overdue by {abs(days_remaining)} days"
    elif days_remaining is not None:
        token = "pending"
        label = f"Transport pending · {days_remaining} days remaining"
    else:
        token = "pending"
        label = "Transport pending"

    return {
        "token": token,
        "label": label,
        "courier": courier,
        "days_remaining": days_remaining,
        "overdue": overdue,
        "reminder_sent": transport.is_reminder_sent,
    }

def _compute_furniture_status(factory_order, today):
    if not factory_order or not factory_order.furniture_reminder_date:
        return None
    
    days_remaining = (factory_order.furniture_reminder_date - today).days
    overdue = days_remaining <= 0
    if factory_order.is_furniture_reminder_sent:
        token = "paid"
        label = "Furniture reminder sent"
    elif overdue:
        token = "overdue"
        label = f"Furniture reminder overdue by {abs(days_remaining)} days"
    else:
        token = "due"
        label = f"Furniture reminder in {days_remaining} days"

    return {
        "label": label,
        "token": token,
        "due": overdue,
        "days_remaining": days_remaining,
        "reminder_sent": factory_order.is_furniture_reminder_sent,
    }


def _compute_package_clarification_status(factory_order, today):
    if not factory_order or not factory_order.package_clarification_reminder_date:
        return None
    
    days_remaining = (factory_order.package_clarification_reminder_date - today).days
    overdue = days_remaining <= 0
    if factory_order.is_package_clarification_reminder_sent:
        token = "paid"
        label = "Package clarification reminder sent"
    elif overdue:
        token = "overdue"
        label = f"Package clarification overdue by {abs(days_remaining)} days"
    else:        
        token = "due"
        label = f"Package clarification in {days_remaining} days"
        
    return {
        "label": label,
        "token": token,
        "due": overdue,
        "days_remaining": days_remaining,
        "reminder_sent": factory_order.is_package_clarification_reminder_sent,
    }
    
def login_page(request):
    return render(request, 'main/login_page.html')

@require_POST
def mark_reminder_sent(request, kind, factory_order_id):
    factory_order = get_object_or_404(FactoryOrder, pk=factory_order_id)

    if kind == "furniture":
        factory_order.is_furniture_reminder_sent = True
    elif kind == "package":
        factory_order.is_package_clarification_reminder_sent = True
    else:
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse({"ok": False, "error": "unknown kind"}, status=400)
        return redirect("main_offer_page")

    factory_order.save()

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True})
    return redirect("main_offer_page")

def main_offer_page(request):
    today = timezone.now().date()

    orders = (
        Order.objects.select_related("client")
        .prefetch_related(
            "clientorder_set__depositclient_set__deposit_type",
            "factoryorder_set__depositfactory_set__deposit_type",
            "transport",
        )
        .order_by("-created_at")
    )

    order_cards = []
    for order in orders:
        client_order = order.clientorder_set.first()
        factory_order = order.factoryorder_set.first()
        transport = getattr(order, "transport", None)

        client_status = _compute_deposit_status(
            client_order.depositclient_set.all() if client_order else [], today
        )
        factory_status = _compute_deposit_status(
            factory_order.depositfactory_set.all() if factory_order else [], today
        )
        transport_status = _compute_transport_status(transport, today)
        furniture_status = _compute_furniture_status(factory_order, today)
        package_clarification_status = _compute_package_clarification_status(factory_order, today)
        
        search_text = f"{order.contract_number} {order.client.client_name}".lower()
        furniture_token = f"furniture-{furniture_status['token']}" if furniture_status else ""
        package_token = f"package-{package_clarification_status['token']}" if package_clarification_status else ""
        status_tokens = " ".join(filter(None, [
            f"client-{client_status['token']}",
            f"factory-{factory_status['token']}",
            f"transport-{transport_status['token']}",
            furniture_token,
            package_token,
        ]))


        order_cards.append({
            "order": order,
            "client_order": client_order,
            "factory_order": factory_order,
            "transport": transport,
            "client_status": client_status,
            "factory_status": factory_status,
            "furniture_status": furniture_status,
            "package_clarification_status": package_clarification_status,
            "transport_status": transport_status,
            "search_text": search_text,
            "status_tokens": status_tokens,
        })

    # --- Stat cards ---
    total_orders = len(order_cards)

    payments_past_due = sum(
        1
        for card in order_cards
        if (
            card["client_status"]["overdue"]
            or card["factory_status"]["overdue"]
        )
    )

    due_this_week = sum(
        1
        for card in order_cards
        if (
            (
                card["client_status"]["days_remaining"] is not None
                and 0 <= card["client_status"]["days_remaining"] <= 7
            )
            or (
                card["factory_status"]["days_remaining"] is not None
                and 0 <= card["factory_status"]["days_remaining"] <= 7
            )
            or (
                card["furniture_status"] and card["furniture_status"]["days_remaining"] is not None
                and 0 <= card["furniture_status"]["days_remaining"] <= 3 
                and not card["furniture_status"]["reminder_sent"]   
            )
            or (
                card["package_clarification_status"] and card["package_clarification_status"]["days_remaining"] is not None
                and 0 <= card["package_clarification_status"]["days_remaining"] <= 3
                and not card["package_clarification_status"]["reminder_sent"]
            )
        )
    )
    
    furniture_package_reminders_due = sum(
        1
        for card in order_cards
        if (
            (card["furniture_status"] and card["furniture_status"]["due"]) and not card["furniture_status"]["reminder_sent"]
            or (card["package_clarification_status"] and card["package_clarification_status"]["due"]) and not card["package_clarification_status"]["reminder_sent"]
        )
    )
    stats = {
        "total_orders": total_orders,
        "payments_past_due": payments_past_due,
        "due_this_week": due_this_week,
        "furniture_package_reminders_due": furniture_package_reminders_due,
    }
    
    return render(request, 'main/main_offer_page.html', {"order_cards": order_cards, "stats": stats})

