"""
Notification adapter layer for AIR Climate Suite alerts.

Backend is selected via NOTIFICATION_BACKEND env var:
  log    — print to stdout (default; development / no config needed)
  smtp   — send real email via SMTP (set SMTP_* env vars)
  digit3 — POST to DIGIT3 Notification service (set DIGIT3_NOTIFICATION_URL)

Usage:
    from urban_platform.notifications import dispatcher
    dispatcher.dispatch_air(packets, city_id="bangalore")
    dispatcher.dispatch_heat(packets, city_id="bangalore")
    dispatcher.dispatch_flood(packets, city_id="bangalore")
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────

_AIR_ALERT_CATEGORIES  = {"poor", "very_poor", "severe"}
_HEAT_RISK_THRESHOLD   = 0.65
_FLOOD_RISK_THRESHOLD  = 0.55

# Suppress repeat alerts for the same city+domain within this window (seconds)
_DEDUP_TTL_SECONDS = 3600


# ── Abstract adapter ────────────────────────────────────────────────────────

class NotificationAdapter(ABC):
    @abstractmethod
    def send(self, recipient: str, subject: str, body_text: str, body_html: str = "") -> bool:
        """Send a notification. Returns True on success."""


# ── Log adapter (default) ───────────────────────────────────────────────────

class LogAdapter(NotificationAdapter):
    def send(self, recipient, subject, body_text, body_html=""):
        logger.info("ALERT → %s | %s\n%s", recipient, subject, body_text)
        return True


# ── SMTP adapter ─────────────────────────────────────────────────────────────

class SmtpAdapter(NotificationAdapter):
    def __init__(self):
        self.host     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.port     = int(os.environ.get("SMTP_PORT", "587"))
        self.user     = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.from_    = os.environ.get("ALERT_EMAIL_FROM", self.user)

    def send(self, recipient, subject, body_text, body_html=""):
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = self.from_
            msg["To"]      = recipient
            msg.attach(MIMEText(body_text, "plain"))
            if body_html:
                msg.attach(MIMEText(body_html, "html"))

            with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.sendmail(self.from_, [recipient], msg.as_string())
            logger.info("SMTP alert sent to %s: %s", recipient, subject)
            return True
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return False


# ── DIGIT3 Notification adapter (stub) ──────────────────────────────────────

class Digit3NotificationAdapter(NotificationAdapter):
    """
    Stub for DIGIT3 Notification service.

    When DIGIT3 is deployed, set:
      DIGIT3_NOTIFICATION_URL=http://<host>/notification/v1/send
      DIGIT3_AUTH_TOKEN=<service-account-token>

    The payload shape follows DIGIT3 Notification v1 contract.
    Currently logs a warning and falls back to LogAdapter.
    """
    def __init__(self):
        self.url   = os.environ.get("DIGIT3_NOTIFICATION_URL", "").strip()
        self.token = os.environ.get("DIGIT3_AUTH_TOKEN", "").strip()
        self._fallback = LogAdapter()

    def send(self, recipient, subject, body_text, body_html=""):
        if not self.url:
            logger.warning(
                "DIGIT3_NOTIFICATION_URL not set — falling back to log. "
                "Set DIGIT3_NOTIFICATION_URL when DIGIT3 Notification is deployed."
            )
            return self._fallback.send(recipient, subject, body_text, body_html)

        payload = {
            "RequestInfo": {"authToken": self.token},
            "notifications": [{
                "recipient":  recipient,
                "subject":    subject,
                "body":       body_text,
                "channel":    "EMAIL",
                "priority":   "HIGH",
            }],
        }
        try:
            resp = requests.post(self.url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("DIGIT3 notification sent to %s: %s", recipient, subject)
            return True
        except Exception as exc:
            logger.error("DIGIT3 notification failed: %s", exc)
            return False


# ── Dedup cache ──────────────────────────────────────────────────────────────

class _DedupCache:
    def __init__(self, ttl: int = _DEDUP_TTL_SECONDS):
        self._cache: dict[str, float] = {}
        self._ttl = ttl

    def should_send(self, key: str) -> bool:
        now = time.monotonic()
        last = self._cache.get(key, 0)
        if now - last > self._ttl:
            self._cache[key] = now
            return True
        return False


# ── Dispatcher ───────────────────────────────────────────────────────────────

class AlertDispatcher:
    def __init__(self):
        self._adapter = self._build_adapter()
        self._dedup   = _DedupCache()
        self._recipients = [
            r.strip()
            for r in os.environ.get("ALERT_RECIPIENTS", "").split(",")
            if r.strip()
        ]

    def _build_adapter(self) -> NotificationAdapter:
        backend = os.environ.get("NOTIFICATION_BACKEND", "log").lower()
        if backend == "digit3":
            return Digit3NotificationAdapter()
        if backend == "smtp":
            return SmtpAdapter()
        return LogAdapter()

    def _recipients_for(self, city_id: str) -> list[str]:
        city_key = f"ALERT_RECIPIENTS_{city_id.upper()}"
        city_specific = [
            r.strip()
            for r in os.environ.get(city_key, "").split(",")
            if r.strip()
        ]
        return city_specific or self._recipients

    def _send(self, city_id: str, domain: str, subject: str, body_text: str, body_html: str = "") -> None:
        key = f"{city_id}:{domain}"
        if not self._dedup.should_send(key):
            logger.debug("Alert suppressed (dedup TTL active): %s", key)
            return
        recipients = self._recipients_for(city_id)
        if not recipients:
            logger.warning("No ALERT_RECIPIENTS configured — alert logged only.")
            recipients = ["(console)"]
        for r in recipients:
            self._adapter.send(r, subject, body_text, body_html)

    def dispatch_air(self, packets: list[dict], city_id: str) -> None:
        triggered = [
            p for p in packets
            if (p.get("aqi_assessment") or {}).get("aqi_category") in _AIR_ALERT_CATEGORIES
        ]
        if not triggered:
            return
        worst = triggered[0]
        aa    = worst.get("aqi_assessment") or {}
        cat   = aa.get("aqi_category", "poor").replace("_", " ").title()
        score = aa.get("aqi_score", 0)
        loc   = worst.get("location") or {}
        subj  = f"[AIR ALERT] {city_id.title()} — AQI {cat}"
        body  = (
            f"Air quality alert for {city_id.title()}.\n\n"
            f"Category : {cat}\n"
            f"Score    : {score:.3f}\n"
            f"Location : lat {loc.get('lat_centroid','?')}, lon {loc.get('lon_centroid','?')}\n"
            f"Cells    : {len(triggered)} H3 cell(s) above threshold\n\n"
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
            f"Source   : AIR Climate Suite — AIR AQ\n"
        )
        self._send(city_id, "air", subj, body)

    def dispatch_heat(self, packets: list[dict], city_id: str) -> None:
        triggered = [
            p for p in packets
            if (p.get("risk_score") or 0) >= _HEAT_RISK_THRESHOLD
        ]
        if not triggered:
            return
        worst = triggered[0]
        score = worst.get("risk_score", 0)
        loc   = worst.get("location") or {}
        subj  = f"[HEAT ALERT] {city_id.title()} — Risk score {score:.2f}"
        body  = (
            f"Urban heat alert for {city_id.title()}.\n\n"
            f"Risk score : {score:.3f}\n"
            f"UHI        : {worst.get('uhi_intensity','?')}°C\n"
            f"Cells      : {len(triggered)} H3 cell(s) above threshold ({_HEAT_RISK_THRESHOLD})\n\n"
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
            f"Source   : AIR Climate Suite — AIR Heat\n"
        )
        self._send(city_id, "heat", subj, body)

    def dispatch_flood(self, packets: list[dict], city_id: str) -> None:
        triggered = [
            p for p in packets
            if (p.get("flood_risk_assessment") or {}).get("flood_risk_score", 0) >= _FLOOD_RISK_THRESHOLD
        ]
        if not triggered:
            return
        worst = triggered[0]
        fra   = worst.get("flood_risk_assessment") or {}
        score = fra.get("flood_risk_score", 0)
        level = fra.get("risk_level", "")
        subj  = f"[FLOOD ALERT] {city_id.title()} — {level.title()} risk"
        body  = (
            f"Flood risk alert for {city_id.title()}.\n\n"
            f"Risk score : {score:.3f}\n"
            f"Risk level : {level}\n"
            f"Cells      : {len(triggered)} H3 cell(s) above threshold ({_FLOOD_RISK_THRESHOLD})\n\n"
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
            f"Source   : AIR Climate Suite — AIR Flood\n"
        )
        self._send(city_id, "flood", subj, body)


# ── Singleton ────────────────────────────────────────────────────────────────

dispatcher = AlertDispatcher()
