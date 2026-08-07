from cProfile import label
from datetime import date
import logging
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .constants import (
    RECOVERY_CODE_VALID_MINUTES,
    RESET_TOKEN_SALT,
    RESET_TOKEN_MAX_AGE_SECONDS,
    )
from .models import FactoryOrder, Order, RecoveryAttempt, RecoverySession
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
    generate_and_send_recovery_code, get_latest_sync_result, get_latest_sync_result, verify_recovery_code,
    RecoveryCodeLocked, NoPhoneNumberOnFile,
)
import functools
from .models import ApiToken, FactoryOrder
from .services import (
    get_due_reminders, compute_deposit_status, compute_transport_status,
    get_client_ip, compute_furniture_status, compute_package_clarification_status,
    is_order_complete, extract_contract_date
)


def recover_password_verify(request):
    username = request.session.get("recovery_username")
    if not username:
        return redirect("recover_password_request_page")

    error = None

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        ip = get_client_ip(request)
        recovery_session = get_object_or_404(RecoverySession, pk=request.session["recovery_session_id"],)
        try:
            user = User.objects.get(username=username)
            if verify_recovery_code(user, code, ip_address=ip, recovery_session=recovery_session):
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
        if len(password1) < 14:
            error = "Password must be at least 14 characters."
        elif password1 != password2:
            error = "Passwords don't match."
        else:
            user.set_password(password1)
            user.save()

            recovery_session = get_object_or_404(RecoverySession, pk=request.session["recovery_session_id"],)

            RecoveryAttempt.objects.create(
                session=recovery_session,
                user=user,
                status="password_reset",
                ip_address=get_client_ip(request),
                detail="Password reset successfully",
            )

            recovery_session.result = "success"
            recovery_session.finished_at = timezone.now()
            recovery_session.save(update_fields=["result", "finished_at"])

            del request.session["password_reset_token"]
            request.session.pop("recovery_session_id", None)

            return redirect("login_page")

    return render(request, "main/set_new_password_page.html", {"error": error, "user": user, "link_expiration_minutes": RESET_TOKEN_MAX_AGE_SECONDS // 60, "username": user.username, "recovery_code_valid_minutes": RECOVERY_CODE_VALID_MINUTES})

logger = logging.getLogger(__name__)

def recover_password_request(request):
    error = None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        ip = get_client_ip(request)
        
        try:
            user = User.objects.get(username=username)
            
            recovery_session = RecoverySession.objects.create(user=user, ip_address=ip,)
            request.session["recovery_session_id"] = recovery_session.id
            
            generate_and_send_recovery_code(user, ip_address=ip, recovery_session=recovery_session)
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

        client_status = compute_deposit_status(
            client_order.depositclient_set.all() if client_order else [], today
        )
        factory_status = compute_deposit_status(
            factory_order.depositfactory_set.all() if factory_order else [], today
        )
        transport_status = compute_transport_status(transport, today)
        furniture_status = compute_furniture_status(factory_order, today)
        package_clarification_status = compute_package_clarification_status(factory_order, today)

        is_complete = is_order_complete(client_status, factory_status, transport_status,
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

        contract_date = extract_contract_date(order.contract_number)
        
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
    
    latest_sync = get_latest_sync_result()
    latest_sync_iso = latest_sync.date_done.isoformat() if latest_sync else ""
    
    return render(request, 'main/main_offer_page.html', {
        "order_cards": order_cards,
        "stats": stats,
        "show_completed": show_completed,
        "completed_orders_count": completed_orders_count,
        "latest_sync_iso": latest_sync_iso,
        })

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
    due = get_due_reminders(today)
    return JsonResponse({"due_reminders": due})

@login_required
def latest_sync_time(request):
    latest = get_latest_sync_result()
    return JsonResponse({
        "last_sync": latest.date_done.isoformat() if latest else None
    })
