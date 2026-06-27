from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright


ACCOUNTS_PATH = Path("data/vezeeta_accounts.json")
DATABASE_PATH = Path("data/vezeeta_alexandria_autorec.sqlite")


def load_account(user_id: str) -> Dict[str, str]:
    if not ACCOUNTS_PATH.exists():
        raise FileNotFoundError("Missing data/vezeeta_accounts.json")

    data = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))

    if user_id not in data:
        raise ValueError("No Vezeeta account found for user_id=" + user_id)

    acc = data[user_id]

    return {
        "email": acc["email"],
        "password": acc["password"],
        "profile_dir": acc.get("profile_dir", "data/browser_profiles/" + user_id),
    }


def click_any(page, texts: List[str], timeout: int = 2500) -> bool:
    for text in texts:
        try:
            loc = page.get_by_text(text, exact=False).first
            loc.wait_for(timeout=timeout)
            loc.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def fill_any(page, labels: List[str], value: str) -> bool:
    for label in labels:
        try:
            page.get_by_label(label, exact=False).fill(value, timeout=1200)
            return True
        except Exception:
            pass

        try:
            page.get_by_placeholder(label, exact=False).fill(value, timeout=1200)
            return True
        except Exception:
            pass

    try:
        inputs = page.locator("input:visible")
        total = min(inputs.count(), 20)

        for i in range(total):
            item = inputs.nth(i)
            try:
                typ = (item.get_attribute("type") or "").lower()
                current = item.input_value(timeout=500)

                if current == "" and typ not in ["hidden", "checkbox", "radio"]:
                    item.fill(value, timeout=1000)
                    return True
            except Exception:
                continue
    except Exception:
        pass

    return False


def get_body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2500)
    except Exception:
        return ""


def manual_step_needed(page) -> bool:
    """
    Detect only real manual security steps.

    Do NOT treat generic page header words like "Login" or "Sign in" as manual steps,
    because Vezeeta shows them in the header even when the booking flow is usable.
    """
    text = get_body_text(page).lower()

    keys = [
        "otp",
        "one time password",
        "verification code",
        "enter code",
        "verify your phone",
        "verify your mobile",
        "captcha",
        "i'm not a robot",
        "recaptcha",
        "كود التحقق",
        "رمز التحقق",
        "ادخل الكود",
    ]

    return any(k in text for k in keys)


def open_context(playwright, account: Dict[str, str], headless: bool):
    profile_dir = account["profile_dir"]
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    context = playwright.chromium.launch_persistent_context(
        profile_dir,
        headless=headless,
        slow_mo=250,
        viewport={"width": 1400, "height": 900},
        locale="en-US",
    )

    page = context.new_page()
    return context, page


def login_if_needed(page, account: Dict[str, str]) -> Dict[str, Any]:
    result = {
        "attempted": False,
        "needs_manual_step": False,
        "actions": [],
    }

    text = get_body_text(page).lower()

    if any(x in text for x in ["my account", "profile", "logout", "sign out"]):
        result["actions"].append("already_logged_in_likely")
        return result

    clicked_login = click_any(page, ["Login", "Log in", "Sign in"], timeout=2500)
    result["actions"].append("login_clicked=" + str(clicked_login))

    if clicked_login:
        result["attempted"] = True
        time.sleep(2)

    email_filled = fill_any(
        page,
        ["Email", "E-mail", "Mobile", "Phone", "Email or mobile"],
        account["email"],
    )
    result["actions"].append("email_filled=" + str(email_filled))

    password_filled = fill_any(
        page,
        ["Password"],
        account["password"],
    )
    result["actions"].append("password_filled=" + str(password_filled))

    if email_filled or password_filled:
        result["attempted"] = True

    submitted = click_any(
        page,
        ["Login", "Log in", "Sign in", "Continue"],
        timeout=3000,
    )
    result["actions"].append("login_submit_clicked=" + str(submitted))

    time.sleep(4)

    if manual_step_needed(page):
        result["needs_manual_step"] = True

    return result


def open_booking_panel(page) -> Dict[str, Any]:
    result = {"actions": []}

    cookie_clicked = click_any(page, ["Accept", "Agree", "Got it", "Allow all"], timeout=1000)
    result["actions"].append("cookie_clicked=" + str(cookie_clicked))

    booking_clicked = click_any(
        page,
        ["Book Examination", "Book Now", "Book now", "Book"],
        timeout=6000,
    )
    result["actions"].append("booking_clicked=" + str(booking_clicked))

    time.sleep(2)
    return result



def extract_slots(page) -> List[Dict[str, Any]]:
    """
    Extract only real booking availability from the booking section.

    Avoids patient review timestamps such as 06:56 PM.
    Expected Vezeeta text style:
    Choose your appointment
    Today No Available Appointments BOOK
    Tomorrow From 2:00 PM To 4:00 PM BOOK
    Sun 06/28 No Available Appointments BOOK
    """
    full_text = get_body_text(page)
    compact = " ".join(full_text.split())

    marker = "Choose your appointment"
    if marker in compact:
        booking_text = compact.split(marker, 1)[1]
    else:
        booking_text = compact

    # Stop before footer/FAQ when possible
    for stop in [
        "Reservation required",
        "Frequently Asked Questions",
        "What is the closest appointment",
        "About Us",
    ]:
        if stop in booking_text:
            booking_text = booking_text.split(stop, 1)[0]

    slots: List[Dict[str, Any]] = []

    # Match available ranges like:
    # Tomorrow From 2:00 PM To 4:00 PM BOOK
    # Sun 06/28 From 2:00 PM To 4:00 PM BOOK
    pattern = re.compile(
        r"(?P<date>(Today|Tomorrow|Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:\s+[0-9]{2}/[0-9]{2})?)"
        r"\s+From\s+"
        r"(?P<from>[0-9]{1,2}:[0-9]{2}\s?(?:AM|PM|am|pm))"
        r"\s+To\s+"
        r"(?P<to>[0-9]{1,2}:[0-9]{2}\s?(?:AM|PM|am|pm))"
        r"\s+BOOK",
        re.IGNORECASE,
    )

    for match in pattern.finditer(booking_text):
        date_text = match.group("date")
        from_time = match.group("from")
        to_time = match.group("to")

        slots.append(
            {
                "slot_id": "slot_" + str(len(slots) + 1),
                "date_text": date_text,
                "time_from": from_time,
                "time_to": to_time,
                "time_text": f"{from_time} - {to_time}",
                "click_text": from_time,
                "raw_text": f"{date_text} From {from_time} To {to_time}",
            }
        )

    # Also return unavailable days for UI visibility, but mark them unavailable
    unavailable_pattern = re.compile(
        r"(?P<date>(Today|Tomorrow|Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:\s+[0-9]{2}/[0-9]{2})?)"
        r"\s+No Available Appointments\s+BOOK",
        re.IGNORECASE,
    )

    for match in unavailable_pattern.finditer(booking_text):
        date_text = match.group("date")

        slots.append(
            {
                "slot_id": "unavailable_" + str(len(slots) + 1),
                "date_text": date_text,
                "available": False,
                "time_text": "No Available Appointments",
                "raw_text": f"{date_text} No Available Appointments",
            }
        )

    # Put available slots first
    slots.sort(key=lambda x: 0 if x.get("available", True) else 1)

    return slots




def log_booking_event(
    user_id: str,
    doctor_cache_id: Optional[int],
    event_type: str,
    source: str = "vezeeta_live_booking",
) -> None:
    if doctor_cache_id is None:
        return

    if not DATABASE_PATH.exists():
        return

    conn = sqlite3.connect(DATABASE_PATH)

    try:
        conn.execute(
            """
            INSERT INTO interaction_events
            (user_id, doctor_cache_id, event_type, source)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, doctor_cache_id, event_type, source),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()





def click_final_booking_button(page) -> bool:
    allowed_texts = {
        "book",
        "confirm",
        "confirm booking",
        "book appointment",
    }

    for selector in ["button:visible", "a:visible"]:
        try:
            items = page.locator(selector)
            total = min(items.count(), 80)

            for i in range(total):
                item = items.nth(i)

                try:
                    raw_text = item.inner_text(timeout=500)
                    txt = " ".join(raw_text.split()).strip().lower()
                except Exception:
                    continue

                if txt in allowed_texts:
                    item.click(timeout=3000)
                    return True

        except Exception:
            continue

    return False


def get_live_availability(
    user_id: str,
    doctor_url: str,
    headless: bool = False,
) -> Dict[str, Any]:
    account = load_account(user_id)

    result = {
        "user_id": user_id,
        "doctor_url": doctor_url,
        "status": "started",
        "actions": [],
        "login": {},
        "slots": [],
    }

    with sync_playwright() as p:
        context, page = open_context(p, account, headless)

        page.goto(doctor_url, wait_until="domcontentloaded", timeout=45000)
        result["actions"].append("opened_doctor_page")
        time.sleep(3)

        login_result = login_if_needed(page, account)
        result["login"] = login_result

        if login_result.get("needs_manual_step"):
            result["status"] = "needs_manual_login_or_otp"
            result["message"] = "Complete OTP/CAPTCHA/login manually in the opened browser, then call this endpoint again."
            time.sleep(15)
            context.close()
            return result

        panel = open_booking_panel(page)
        result["actions"].extend(panel["actions"])

        result["slots"] = extract_slots(page)

        if result["slots"]:
            result["status"] = "slots_found"
        else:
            result["status"] = "no_slots_found_or_selectors_need_update"

        time.sleep(8)
        context.close()
        return result


def book_selected_slot(
    user_id: str,
    doctor_url: str,
    selected_time_text: str,
    patient_name: str,
    patient_phone: str,
    doctor_cache_id: Optional[int] = None,
    user_confirmed_final: bool = False,
    dry_run: bool = True,
    headless: bool = False,
) -> Dict[str, Any]:
    account = load_account(user_id)

    result = {
        "user_id": user_id,
        "doctor_url": doctor_url,
        "selected_time_text": selected_time_text,
        "dry_run": dry_run,
        "user_confirmed_final": user_confirmed_final,
        "actions": [],
        "final_booking_clicked": False,
        "status": "started",
    }

    with sync_playwright() as p:
        context, page = open_context(p, account, headless)

        page.goto(doctor_url, wait_until="domcontentloaded", timeout=45000)
        result["actions"].append("opened_doctor_page")
        time.sleep(3)

        login_result = login_if_needed(page, account)
        result["login"] = login_result

        if login_result.get("needs_manual_step"):
            result["status"] = "needs_manual_login_or_otp"
            result["message"] = "Complete OTP/CAPTCHA/login manually, then retry."
            time.sleep(15)
            context.close()
            return result

        panel = open_booking_panel(page)
        result["actions"].extend(panel["actions"])

        slot_clicked = click_any(page, [selected_time_text], timeout=4000)
        result["actions"].append("slot_clicked=" + str(slot_clicked))

        if not slot_clicked:
            result["status"] = "selected_slot_not_found"
            result["message"] = "Could not click selected time. Refresh availability and choose returned slot time."
            time.sleep(8)
            context.close()
            return result

        log_booking_event(user_id, doctor_cache_id, "book_intent")

        time.sleep(2)

        name_filled = fill_any(page, ["Name", "Full name", "Patient name"], patient_name)
        result["actions"].append("name_filled=" + str(name_filled))

        phone_filled = fill_any(page, ["Phone", "Mobile", "Mobile number", "Phone number"], patient_phone)
        result["actions"].append("phone_filled=" + str(phone_filled))

        continued = click_any(page, ["Continue", "Next", "Proceed", "Confirm information"], timeout=3500)
        result["actions"].append("continue_clicked=" + str(continued))

        time.sleep(3)

        if manual_step_needed(page):
            result["status"] = "needs_manual_login_or_otp"
            result["message"] = "Manual OTP/CAPTCHA/verification is required."
            time.sleep(15)
            context.close()
            return result

        if dry_run:
            result["status"] = "dry_run_stopped_before_final_confirmation"
            result["message"] = "Dry run only. No booking confirmed."
            time.sleep(10)
            context.close()
            return result

        if not user_confirmed_final:
            result["status"] = "blocked_missing_final_user_confirmation"
            result["message"] = "Final booking blocked because user_confirmed_final=false."
            time.sleep(10)
            context.close()
            return result

        final_clicked = click_final_booking_button(page)

        result["final_booking_clicked"] = final_clicked

        if final_clicked:
            result["status"] = "final_confirmation_clicked"
            log_booking_event(user_id, doctor_cache_id, "booked")
        else:
            result["status"] = "final_confirmation_button_not_found"

        time.sleep(10)
        context.close()
        return result
