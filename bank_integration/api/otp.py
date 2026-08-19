import frappe
import random
import requests

from frappe.utils import now_datetime, add_to_date
from frappe.utils.password import get_decrypted_password


def generate_payment_otp(payment_request):
    doc = frappe.get_doc(
        "Bank Payment Request",
        payment_request
    )

    otp = str(random.randint(100000, 999999))

    current_time = now_datetime()

    doc.otp = otp
    doc.otp_status = "Pending"
    doc.otp_expires_at = add_to_date(
        current_time,
        minutes=5
    )

    doc.save(ignore_permissions=True)

    return {
        "success": True,
        "request_id": doc.request_id,
        "otp": otp,
        "otp_expires_at": doc.otp_expires_at
    }


def normalize_payment_status(status):
    """
    Converts bank-style uppercase payment statuses
    into the exact Select field options used by
    Bank Payment Request.payment_status.

    Allowed Frappe values:
        Initiated
        Pending
        Completed
        Failed
        Rejected
    """

    if not status:
        return "Failed"

    normalized_status = str(status).strip().upper()

    status_map = {
        "INITIATED": "Initiated",
        "PENDING": "Pending",
        "COMPLETED": "Completed",
        "FAILED": "Failed",
        "REJECTED": "Rejected"
    }

    return status_map.get(
        normalized_status,
        "Failed"
    )


def initiate_bank_payment(doc):

    if not doc.source_account:
        frappe.throw(
            "Source account is required."
        )

    bank_account = frappe.db.get_value(
        "Bank Integration Account",
        {
            "account_number": doc.source_account
        },
        [
            "name",
            "account_number",
            "currency",
            "api_key",
            "api_secret",
            "payment_initiation_url"
        ],
        as_dict=True
    )

    if not bank_account:
        frappe.throw(
            f"No Bank Integration Account found for source account "
            f"{doc.source_account}."
        )

    if (
        bank_account.currency
        and bank_account.currency != doc.currency
    ):
        frappe.throw(
            "Bank account currency does not match payment currency."
        )

    api_key = get_decrypted_password(
        "Bank Integration Account",
        bank_account.name,
        "api_key"
    )

    api_secret = get_decrypted_password(
        "Bank Integration Account",
        bank_account.name,
        "api_secret"
    )

    if not api_key:
        frappe.throw(
            "Bank API Key is not configured."
        )

    if not api_secret:
        frappe.throw(
            "Bank API Secret is not configured."
        )

    if not bank_account.payment_initiation_url:
        frappe.throw(
            "Payment initiation URL is not configured."
        )

    payload = {
        "unique_id": doc.request_id,
        "account_number": doc.beneficiary_account,
        "payment_status": "COMPLETED",
        "mode_of_payment": doc.mode_of_payment,
        "amount": float(doc.amount)
    }

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # -------------------------------------------------
    # Call Mock Bank
    # -------------------------------------------------

    try:
        response = requests.post(
            bank_account.payment_initiation_url,
            json=payload,
            headers=headers,
            timeout=15
        )

    except requests.Timeout:

        frappe.log_error(
            title="Mock Bank Timeout",
            message=frappe.get_traceback()
        )

        return {
            "success": False,
            "request_id": doc.request_id,
            "response_code": "TIMEOUT",
            "response_message": (
                "Mock Bank did not respond in time."
            ),
            "payment_status": "FAILED",
            "transaction_id": ""
        }

    except requests.RequestException:

        frappe.log_error(
            title="Mock Bank Connection Error",
            message=frappe.get_traceback()
        )

        return {
            "success": False,
            "request_id": doc.request_id,
            "response_code": "CONNECTION_ERROR",
            "response_message": (
                "Unable to connect to Mock Bank."
            ),
            "payment_status": "FAILED",
            "transaction_id": None
        }

    try:
        data = response.json()

    except ValueError:

        frappe.log_error(
            title="Invalid Mock Bank Response",
            message=response.text
        )

        return {
            "success": False,
            "request_id": doc.request_id,
            "response_code": "INVALID_RESPONSE",
            "response_message": (
                "Mock Bank returned an invalid response."
            ),
            "payment_status": "FAILED",
            "transaction_id": None
        }

    # -------------------------------------------------
    # HTTP status validation
    # -------------------------------------------------

    if response.status_code not in (200, 202):

        frappe.log_error(
            title="Mock Bank HTTP Error",
            message=(
                f"HTTP Status: {response.status_code}\n\n"
                f"Response: {frappe.as_json(data)}"
            )
        )

        return {
            "success": False,
            "request_id": data.get(
                "request_id",
                doc.request_id
            ),
            "response_code": data.get(
                "response_code",
                f"HTTP_{response.status_code}"
            ),
            "response_message": data.get(
                "response_message",
                "Mock Bank returned an HTTP error."
            ),
            "payment_status": "FAILED",
            "transaction_id": data.get(
                "transaction_id"
            )
        }

    # -------------------------------------------------
    # Read bank response
    # -------------------------------------------------

    bank_status = data.get(
        "payment_status"
    )

    response_code = data.get(
        "response_code"
    )

    response_message = data.get(
        "response_message"
    )

    transaction_id = data.get(
        "transaction_id"
    )

    bank_status_upper = str(
        bank_status or "FAILED"
    ).strip().upper()


    frappe_payment_status = normalize_payment_status(
        bank_status_upper
    )

    doc.payment_status = frappe_payment_status

    if transaction_id:
        doc.bank_transaction_id = transaction_id

    if hasattr(
        doc,
        "bank_response_code"
    ):
        doc.bank_response_code = (
            response_code or ""
        )

    if hasattr(
        doc,
        "bank_response_message"
    ):
        doc.bank_response_message = (
            response_message or ""
        )

    if (
        hasattr(doc, "processed_at")
        and data.get("processed_at")
    ):
        doc.processed_at = data.get(
            "processed_at"
        )

    doc.save(
        ignore_permissions=True
    )

    return {
        "success": (
            response.status_code in (200, 202)
            and bank_status_upper in {
                "COMPLETED",
                "PENDING",
                "FAILED",
                "REJECTED"
            }
        ),
        "request_id": data.get(
            "request_id",
            doc.request_id
        ),
        "response_code": response_code,
        "response_message": response_message,

        "payment_status": bank_status_upper,

        "transaction_id": transaction_id,

        "debit_account_number":
            data.get(
                "debit_account_number"
            ),

        "beneficiary_account_number":
            data.get(
                "beneficiary_account_number"
            ),

        "mode_of_payment":
            data.get(
                "mode_of_payment",
                doc.mode_of_payment
            ),

        "amount":
            data.get(
                "amount",
                doc.amount
            ),

        "currency":
            data.get(
                "currency",
                doc.currency
            ),

        "available_balance":
            data.get(
                "available_balance"
            ),

        "processed_at":
            data.get(
                "processed_at"
            ),

        "processing_time_ms":
            data.get(
                "processing_time_ms"
            ),

        "response_timestamp":
            data.get(
                "response_timestamp"
            )
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
            "request_id": payment_request
        },
        "name"
    )

    if not doc_name:
        frappe.throw(
            f"Bank Payment Request with Request ID "
            f"{payment_request} not found."
        )

    doc = frappe.get_doc(
        "Bank Payment Request",
        doc_name
    )

    if doc.otp_status == "Verified":
        frappe.throw(
            "OTP has already been verified."
        )

    if (
        doc.otp_expires_at
        and now_datetime() > doc.otp_expires_at
    ):

        doc.otp_status = "Expired"

        doc.save(
            ignore_permissions=True
        )

        return {
            "success": False,
            "request_id": doc.request_id,
            "otp_status": "Expired",
            "payment_status": doc.payment_status,
            "message": "OTP has expired."
        }

    if str(entered_otp).strip() != str(
        doc.otp
    ).strip():

        doc.otp_status = "Invalid"

        doc.save(
            ignore_permissions=True
        )

        return {
            "success": False,
            "request_id": doc.request_id,
            "otp_status": "Invalid",
            "payment_status": doc.payment_status,
            "message": "Invalid OTP."
        }

    doc.otp_status = "Verified"
    doc.otp_verified_at = now_datetime()

    doc.save(
        ignore_permissions=True
    )

    bank_result = initiate_bank_payment(
        doc
    )

    return {
        "success":
            bank_result["success"],

        "request_id":
            bank_result["request_id"],

        "otp_status":
            "Verified",

        "payment_status":
            bank_result["payment_status"],

        "response_code":
            bank_result["response_code"],

        "response_message":
            bank_result["response_message"],

        "transaction_id":
            bank_result["transaction_id"],

        "debit_account_number":
            bank_result.get(
                "debit_account_number"
            ),

        "beneficiary_account_number":
            bank_result.get(
                "beneficiary_account_number"
            ),

        "mode_of_payment":
            bank_result.get(
                "mode_of_payment"
            ),

        "amount":
            bank_result.get(
                "amount"
            ),

        "currency":
            bank_result.get(
                "currency"
            ),

        "available_balance":
            bank_result.get(
                "available_balance"
            ),

        "processed_at":
            bank_result.get(
                "processed_at"
            ),

        "processing_time_ms":
            bank_result.get(
                "processing_time_ms"
            ),

        "response_timestamp":
            bank_result.get(
                "response_timestamp"
            )
    }

