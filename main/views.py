from cProfile import label
from datetime import date
import logging
from django.http import JsonResponse, request
from django.shortcuts import redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .constants import (
    RECOVERY_CODE_VALID_MINUTES,
    DEPOSIT_TYPE_PRIORITY,
    RESET_TOKEN_SALT,
    RESET_TOKEN_MAX_AGE_SECONDS,
    CONTRACT_NUMBER_PATTERN
    )
from .models import FactoryOrder, Order
from django.shortcuts import redirect, render
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth import authenticate, login, logout
from .models import Order, FactoryOrder, Transport
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.contrib.auth.models import User
from .services import (
    SmsDeliveryError, generate_and_send_recovery_code, verify_recovery_code,
    RecoveryCodeLocked, NoPhoneNumberOnFile,
)
import functools
from .models import ApiToken, FactoryOrder
from django_celery_results.models import TaskResult

def recover_password_request(request):
    error = None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        try:
            user = User.objects.get(username=username)
            generate_and_send_recovery_code(user)
            request.session["recovery_username"] = username
            return redirect("recover_password_verify_page")
        except User.DoesNotExist:
            # Don't reveal whether the username exists.
            request.session["recovery_username"] = username
            return redirect("recover_password_verify_page")
        except NoPhoneNumberOnFile:
            error = "No phone number on file for this account. Contact an admin."
        except RecoveryCodeLocked as exc:
            error = f"Too many attempts. Try again after {timezone.localtime(exc.locked_until).strftime('%H:%M')}."
        except SmsDeliveryError:
            error = "Unable to send recovery code right now. Please try again later."
            
    return render(request, "main/recover_password_request_page.html", {"error": error})


def recover_password_verify(request):
    username = request.session.get("recovery_username")
    if not username:
        return redirect("recover_password_request_page")

    error = None

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        try:
            user = User.objects.get(username=username)
            if verify_recovery_code(user, code):
                token = signing.dumps({"user_id": user.id}, salt=RESET_TOKEN_SALT)
                request.session["password_reset_token"] = token
                del request.session["recovery_username"]
                return redirect("set_new_password_page")
        except User.DoesNotExist:
            pass
            
        error = "Invalid or expired code."

    return render(request, "main/recover_password_verify_page.html", {"error": error, "username": username, "recovery_code_valid_minutes": RECOVERY_CODE_VALID_MINUTES})


def set_new_password(request):
    token = request.session.get("password_reset_token")
    if not token:
        return redirect("login_page")

    try:
        data = signing.loads(token, salt=RESET_TOKEN_SALT, max_age=RESET_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return redirect("login_page")

    user = User.objects.get(pk=data["user_id"])
    error = None

    if request.method == "POST":
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        if len(password1) < 8:
            error = "Password must be at least 8 characters."
        elif password1 != password2:
            error = "Passwords don't match."
        else:
            user.set_password(password1)
            user.save()
            del request.session["password_reset_token"]
            return redirect("login_page")

    return render(request, "main/set_new_password_page.html", {"error": error, "user": user, "link_expiration_minutes": RESET_TOKEN_MAX_AGE_SECONDS // 60, "username": user.username, "recovery_code_valid_minutes": RECOVERY_CODE_VALID_MINUTES})

logger = logging.getLogger(__name__)

def recover_password_request(request):
    error = None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()

        try:
            user = User.objects.get(username=username)
            generate_and_send_recovery_code(user)
            request.session["recovery_username"] = username
            return redirect("recover_password_verify_page")

        except User.DoesNotExist:
            request.session["recovery_username"] = username
            return redirect("recover_password_verify_page")

        except NoPhoneNumberOnFile:
            error = "No phone number on file for this account. Contact an admin."

        except RecoveryCodeLocked as exc:
            error = (
                f"Too many attempts. Try again after "
                f"{timezone.localtime(exc.locked_until).strftime('%H:%M')}."
            )

    return render(
        request,
        "main/recover_password_request_page.html",
        {"error": error},
    )
        
def _compute_deposit_status(deposits, today):
    deposits = list(deposits)
    if not deposits:
        return {
            "token": "due",
            "paid": False,
            "label": "no deposit info",
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

    # A deposit row only counts as "informative" if it actually carries an
    # amount or a due date — otherwise it's just an empty placeholder row
    # created by sync (e.g. factory deposits before any sheet data exists).
    informative_unpaid = [
        d for d in unpaid if d.amount is not None or d.payment_due_by is not None
    ]
    if not informative_unpaid:
        return {
            "token": "due",
            "paid": False,
            "label": "no deposit info",
            "deposit_type": None,
            "days_remaining": None,
            "overdue": False,
            "reminder_sent": False,
        }

    informative_unpaid.sort(key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99))
    active = informative_unpaid[0]
    dated_unpaid = sorted(
        (d for d in informative_unpaid if d.payment_due_by),
        key=lambda d: DEPOSIT_TYPE_PRIORITY.get(d.deposit_type.type_name, 99),
    )
    if dated_unpaid:
        active = dated_unpaid[0]

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
        if transport.delivery_date and days_remaining is not None and days_remaining < 0:
            label = f"Transport confirmed · overdue by {abs(days_remaining)} days past original date"
        else:
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
    error = None
    
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("main_offer_page")
        else:
            error = "Invalid username or password."
            
    return render(request, 'main/login_page.html', {"error": error})

def logout_view(request):
    return redirect("login_page")


@login_required(login_url='login_page')
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

@login_required(login_url='login_page')
@require_POST
def mark_transport_reminder_sent(request, order_id):
    transport = get_object_or_404(Transport, order_id=order_id)
    transport.is_reminder_sent = True
    transport.save()

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True})
    return redirect("main_offer_page")

def _is_order_complete(client_status, factory_status, transport_status,
                        furniture_status, package_clarification_status):
    return (
        client_status["paid"]
        and factory_status["paid"]
        and transport_status["token"] == "confirmed"
        and (furniture_status is None or furniture_status["reminder_sent"])
        and (package_clarification_status is None or package_clarification_status["reminder_sent"])
    )
    
@login_required(login_url='login_page')
def main_offer_page(request):
    today = timezone.now().date()
    show_completed = request.GET.get("show_completed") == "1"

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
    completed_orders_count = 0
    
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
        
        is_complete = _is_order_complete(client_status, factory_status, transport_status,
                                            furniture_status, package_clarification_status
                                        )
        if is_complete:
            completed_orders_count += 1
            if not show_completed:
                continue

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

        contract_date = _extract_contract_date(order.contract_number)
        
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
            "contract_date_iso": contract_date.isoformat() if contract_date else "",
            "production_end_date_iso": (factory_order.production_end_date.isoformat() if factory_order and factory_order.production_end_date else ""),
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
    
    latest_sync = _get_latest_sync_result()
    latest_sync_iso = latest_sync.date_done.isoformat() if latest_sync else ""
    
    return render(request, 'main/main_offer_page.html', {
        "order_cards": order_cards,
        "stats": stats,
        "show_completed": show_completed,
        "completed_orders_count": completed_orders_count,
        "latest_sync_iso": latest_sync_iso,
        })
    
def _extract_contract_date(contract_number):
    match = CONTRACT_NUMBER_PATTERN.match(contract_number)
    if not match:
        return None
    year_prefix, month, day = match.groups()
    try:
        return date(2000 + int(year_prefix), int(month), int(day))
    except ValueError:
        return None

def api_token_required(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        print("Authorization header:", repr(request.headers.get("Authorization")))
        print("META HTTP_AUTHORIZATION:", repr(request.META.get("HTTP_AUTHORIZATION")))
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "Missing or malformed Authorization header"}, status=401)

        token_value = auth_header.removeprefix("Bearer ").strip()
        try:
            token = ApiToken.objects.get(token=token_value, is_active=True)
        except ApiToken.DoesNotExist:
            return JsonResponse({"error": "Invalid or revoked token"}, status=403)

        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])

        return view_func(request, *args, **kwargs)
    return wrapper

@api_token_required
def reminders_due_api(request):
    today = timezone.now().date()
    due = []

    orders = Order.objects.select_related("client").prefetch_related(
        "clientorder_set__depositclient_set__deposit_type",
        "factoryorder_set__depositfactory_set__deposit_type",
        "transport",
    )

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
        package_status = _compute_package_clarification_status(factory_order, today)

        # --- Client deposit ---
        if (
            not client_status["paid"]
            and not client_status["reminder_sent"]
            and client_status["days_remaining"] is not None
            and client_status["days_remaining"] <= 7
        ):
            due.append({
                "id": f"client-deposit-{order.id}",
                "message": f"{order.contract_number}: Client {client_status['label']}",
            })

        # --- Factory deposit ---
        if (
            not factory_status["paid"]
            and not factory_status["reminder_sent"]
            and factory_status["days_remaining"] is not None
            and factory_status["days_remaining"] <= 7
        ):
            due.append({
                "id": f"factory-deposit-{order.id}",
                "message": f"{order.contract_number}: Factory {factory_status['label']}",
            })

        # --- Transport ---
        if (
            transport_status["token"] != "confirmed"
            and not transport_status["reminder_sent"]
            and transport_status["days_remaining"] is not None
            and transport_status["days_remaining"] <= 7
        ):
            due.append({
                "id": f"transport-{order.id}",
                "message": f"{order.contract_number}: {transport_status['label']}",
            })

        # --- Furniture (unchanged) ---
        if furniture_status and furniture_status["due"] and not furniture_status["reminder_sent"]:
            due.append({
                "id": f"furniture-{factory_order.id}",
                "message": f"{order.contract_number}: {furniture_status['label']}",
            })

        # --- Package clarification (unchanged) ---
        if package_status and package_status["due"] and not package_status["reminder_sent"]:
            due.append({
                "id": f"package-{factory_order.id}",
                "message": f"{order.contract_number}: {package_status['label']}",
            })

    return JsonResponse({"due": due})

def _get_latest_sync_result():
    return (
        TaskResult.objects
        .filter(task_name="main.tasks.sync_sheet_task", status="SUCCESS")
        .order_by("-date_done")
        .first()
    )

@login_required
def latest_sync_time(request):
    latest = _get_latest_sync_result()
    return JsonResponse({
        "last_sync": latest.date_done.isoformat() if latest else None
    })
