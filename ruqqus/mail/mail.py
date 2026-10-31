"""
Outgoing e-mail.

The original implementation was hardwired to Mailgun's HTTP API on the
``mail.ruqqus.com`` domain.  It is now backend-driven:

* ``console`` (default) -- prints the message to the application log.  A fresh
  install works with no third-party account; the verification link is right
  there in the terminal.
* ``smtp`` -- delivers through a real SMTP relay configured via ``SMTP_*``.

See ``.env.example`` for the settings.
"""

from __future__ import annotations

import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

from flask import abort, render_template, request

from ruqqus import config
from ruqqus.classes import Badge, User
from ruqqus.helpers.security import generate_hash, validate_hash
from ruqqus.helpers.wrappers import auth_desired, auth_required
from ruqqus.__main__ import app, db

log = logging.getLogger("ruqqus.mail")


def send_mail(to_address, subject, html, plaintext=None,
              from_address=None):
    """
    Deliver an e-mail through the configured backend.

    Returns True on success, False on failure.  Unlike the original, failures
    are logged rather than silently discarded.
    """
    from_address = from_address or config.MAIL_FROM

    if config.MAIL_BACKEND == "console":
        log.info(
            "MAIL (console backend)\n"
            "  To:      %s\n"
            "  From:    %s\n"
            "  Subject: %s\n"
            "%s",
            to_address, from_address, subject, html,
        )
        return True

    # ---- SMTP ----
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address

    if plaintext:
        message.attach(MIMEText(plaintext, "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT
        ) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.sendmail(from_address, [to_address], message.as_string())
        log.info("Mail sent to %s (%s)", to_address, subject)
        return True
    except Exception:
        log.exception("Failed to send mail to %s (%s)", to_address, subject)
        return False


def send_verification_email(user, email=None):

    if not email:
        email = user.email

    url = f"{config.SITE_URL}/activate"
    now = int(time.time())

    token = generate_hash(f"{email}+{user.id}+{now}")
    params = f"?email={quote(email)}&id={user.id}&time={now}&token={token}"

    link = url + params

    return send_mail(
        to_address=email,
        html=render_template("email/email_verify.html",
                             action_url=link,
                             v=user),
        subject="Validate your Ruqqus account email.",
    )


@app.route("/api/verify_email", methods=["POST"])
@auth_required
def api_verify_email(v):

    send_verification_email(v)

    return "", 204


@app.route("/activate", methods=["GET"])
@auth_desired
def activate(v):

    email = request.args.get("email", "")
    id = request.args.get("id", "")
    timestamp = int(request.args.get("time", "0"))
    token = request.args.get("token", "")

    if int(time.time()) - timestamp > 3600:
        return render_template("message.html", v=v,
                               title="Verification link expired.",
                               message="That link has expired."), 410

    if not validate_hash(f"{email}+{id}+{timestamp}", token):
        abort(403)

    user = db.query(User).filter_by(id=id).first()
    if not user:
        abort(404)

    if user.is_activated and user.email == email:
        return render_template("message_success.html", v=v,
                               title="Email already verified.",
                               message="Email already verified."), 404

    user.email = email
    user.is_activated = True

    if not any([b.badge_id == 2 for b in user.badges]):
        mail_badge = Badge(user_id=user.id,
                           badge_id=2,
                           created_utc=time.time())
        db.add(mail_badge)

    db.add(user)
    db.commit()
    return render_template("message_success.html", v=v,
                           title="Email verified.",
                           message=f"Your email {email} has been verified. Thank you.")
