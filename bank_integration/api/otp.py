import frappe
import random

from frappe.utils import (
    now_datetime,
    add_to_date
)

def generate_payment_otp(
    payment_request
):

    doc = frappe.get_doc(
        "Bank Payment Request",
        payment_request
    )

    otp = str(
        random.randint(
            100000,
            999999
        )
    )

    current_time = now_datetime()

    doc.otp = otp

    doc.otp_status = "Pending"

    doc.otp_expires_at = add_to_date(
        current_time,
        minutes=5
    )

    doc.save(
        ignore_permissions=True
    )

    return {
        "success":
            True,

        "request_id":
            doc.request_id,

        "otp":
            otp,

        "otp_expires_at":
            doc.otp_expires_at
    }


@frappe.whitelist()
def validate_payment_otp(
    payment_request,
    entered_otp
):

    if not payment_request:

        frappe.throw(
            "Payment request is required."
        )

    if not entered_otp:

        frappe.throw(
            "OTP is required."
        )

    doc_name = frappe.db.get_value(
        "Bank Payment Request",
        {
            "request_id":
                payment_request
        },
        "name"
    )

    if not doc_name:

        frappe.throw(
            (
                "Bank Payment Request with Request ID "
                f"{payment_request} not found."
            )
        )

    doc = frappe.get_doc(
        "Bank Payment Request",
        doc_name
    )

    # --------------------------------------------------------
    # Already verified
    # --------------------------------------------------------

    if doc.otp_status == "Verified":

        frappe.throw(
            "OTP has already been verified."
        )

    # --------------------------------------------------------
    # Expired
    # --------------------------------------------------------

    if (
        doc.otp_expires_at
        and now_datetime()
        > doc.otp_expires_at
    ):

        doc.otp_status = "Expired"

        doc.save(
            ignore_permissions=True
        )

        return {

            "success":
                False,

            "request_id":
                doc.request_id,

            "otp_status":
                "Expired",

            "payment_status":
                doc.payment_status,

            "message":
                "OTP has expired."
        }

    # --------------------------------------------------------
    # Invalid OTP
    # --------------------------------------------------------

    if str(entered_otp).strip() != str(
        doc.otp
    ).strip():

        doc.otp_status = "Invalid"

        doc.save(
            ignore_permissions=True
        )

        return {

            "success":
                False,

            "request_id":
                doc.request_id,

            "otp_status":
                "Invalid",

            "payment_status":
                doc.payment_status,

            "message":
                "Invalid OTP."
        }

    # --------------------------------------------------------
    # OTP SUCCESS
    # --------------------------------------------------------

    verified_at = now_datetime()

    doc.otp_status = "Verified"

    doc.otp_verified_at = (
        verified_at
    )

    doc.payment_status = (
        "OTP Verified"
    )

    doc.save(
        ignore_permissions=True
    )

    return {

        "success":
            True,

        "request_id":
            doc.request_id,

        "otp_status":
            "Verified",

        "otp_verified_at":
            verified_at,

        "payment_status":
            "OTP Verified",

        "message":
            "OTP verified successfully."
    }