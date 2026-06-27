from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

from playwright.sync_api import sync_playwright


@dataclass
class BookingRequest:
    doctor_url: str
    patient_name: str
    patient_phone: str
    preferred_day_text: Optional[str] = None
    preferred_time_text: Optional[str] = None
    dry_run: bool = True
    user_confirmed_final: bool = False


def click_any(page, texts, timeout=2500) -> bool:
    for text in texts:
        try:
            loc = page.get_by_text(text, exact=False).first
            loc.wait_for(timeout=timeout)
            loc.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def fill_first_empty_input(page, value: str) -> bool:
    try:
        inputs = page.locator("input:visible")
        total = min(inputs.count(), 20)
        for i in range(total):
            inp = inputs.nth(i)
            try:
                if inp.input_value(timeout=500) == "":
                    inp.fill(value, timeout=1000)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def fill_any(page, labels, value: str) -> bool:
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
    return fill_first_empty_input(page, value)


def click_time_like(page) -> bool:
    pattern = re.compile(r"([0-9]{1,2}:[0-9]{2}|[0-9]{1,2}\s?(AM|PM|am|pm))")
    try:
        items = page.locator("button:visible, a:visible, div:visible, span:visible")
        total = min(items.count(), 150)
        for i in range(total):
            item = items.nth(i)
            try:
                text = item.inner_text(timeout=400).strip()
                if pattern.search(text):
                    item.click(timeout=1000)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def book_on_vezeeta(req: BookingRequest) -> Dict[str, Any]:
    if not req.doctor_url.startswith("https://www.vezeeta.com/"):
        raise ValueError("Only https://www.vezeeta.com/ URLs are allowed.")

    result: Dict[str, Any] = {
        "status": "started",
        "doctor_url": req.doctor_url,
        "dry_run": req.dry_run,
        "actions": [],
        "final_booking_clicked": False,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=250)
        page = browser.new_page(viewport={"width": 1400, "height": 900}, locale="en-US")

        page.goto(req.doctor_url, wait_until="domcontentloaded", timeout=45000)
        result["actions"].append("opened_doctor_page")
        time.sleep(3)

        cookie = click_any(page, ["Accept", "Agree", "Got it", "Allow all"], timeout=1000)
        result["actions"].append("cookie_clicked=" + str(cookie))

        book = click_any(page, ["Book Examination", "Book Now", "Book now", "Book"], timeout=5000)
        result["actions"].append("booking_clicked=" + str(book))
        time.sleep(2)

        if req.preferred_day_text:
            day = click_any(page, [req.preferred_day_text], timeout=2500)
            result["actions"].append("day_clicked=" + str(day))

        if req.preferred_time_text:
            slot = click_any(page, [req.preferred_time_text], timeout=2500)
        else:
            slot = click_time_like(page)
        result["actions"].append("time_clicked=" + str(slot))
        time.sleep(2)

        name = fill_any(page, ["Name", "Full name", "Patient name"], req.patient_name)
        result["actions"].append("name_filled=" + str(name))

        phone = fill_any(page, ["Phone", "Mobile", "Mobile number", "Phone number"], req.patient_phone)
        result["actions"].append("phone_filled=" + str(phone))

        cont = click_any(page, ["Continue", "Next", "Proceed"], timeout=2500)
        result["actions"].append("continue_clicked=" + str(cont))
        time.sleep(3)

        try:
            body = page.locator("body").inner_text(timeout=2000).lower()
        except Exception:
            body = ""

        if any(w in body for w in ["otp", "verification", "code", "login", "sign in", "captcha"]):
            result["status"] = "needs_manual_login_or_otp"
            result["message"] = "Manual login, OTP, or CAPTCHA is required in the opened browser."
            time.sleep(12)
            browser.close()
            return result

        if req.dry_run:
            result["status"] = "dry_run_stopped_before_final_confirmation"
            result["message"] = "Dry run only. No real booking was confirmed."
            time.sleep(12)
            browser.close()
            return result

        if not req.user_confirmed_final:
            result["status"] = "blocked_missing_final_user_confirmation"
            result["message"] = "Final booking blocked because user_confirmed_final is false."
            time.sleep(8)
            browser.close()
            return result

        final = click_any(page, ["Confirm Booking", "Confirm", "Book Appointment"], timeout=5000)
        result["final_booking_clicked"] = final
        result["status"] = "final_confirmation_clicked" if final else "final_confirmation_button_not_found"

        time.sleep(10)
        browser.close()
        return result
