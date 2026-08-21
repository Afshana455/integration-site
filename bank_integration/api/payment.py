import frappe
from bank_integration.api.otp import generate_payment_otp
import requests
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password
from frappe.utils import generate_hash

@frappe.whitelist()
def create_payment_request(
    erp_site,
    erp_doctype,
    erp_document_name,
    currency,
    source_account,
    beneficiary_account,
    mode_of_payment
):
   
    request_id = generate_hash()   

    if not erp_site:
        frappe.throw("ERP site is required.")

    if not erp_doctype:
        frappe.throw("ERP DocType is required.")

    if not erp_document_name:
        frappe.throw("ERP document name is required.")

    if not currency:
        frappe.throw("Currency is required.")

    if not source_account:
        frappe.throw("Source bank account is required.")

    if not beneficiary_account:
        frappe.throw("Beneficiary account is required.")

    if not mode_of_payment:
        frappe.throw("Mode of payment is required.")

    if frappe.db.exists(
        "Bank Payment Request",
        {"request_id": request_id}
    ):
        frappe.throw(
            f"Payment request {request_id} already exists."
        )

    

    payment_request = frappe.get_doc({
        "doctype": "Bank Payment Request",

        "request_id": request_id,

        "erp_site": erp_site,

        "erp_doctype": erp_doctype,

        "erp_document_name": erp_document_name,

        "currency": currency,

        "source_account": source_account,

        "beneficiary_account": beneficiary_account,

        "mode_of_payment": mode_of_payment,

        "otp_status": "Pending",

        "payment_status": "OTP Pending",

        "payment_submitted": 0
    })

    payment_request.insert(
        ignore_permissions=True
    )

    otp_data = generate_payment_otp(
        payment_request.name
    )

    return {
        "success": True,

        "request_id":
            payment_request.request_id,

        "otp":
            otp_data["otp"],

        "otp_expires_at":
            otp_data["otp_expires_at"],

        "otp_status":
            "Pending",

        "payment_status":
            "OTP Pending"
    }

@frappe.whitelist()
def submit_payment_request(
    payment_request,
    amount
):

    if not payment_request:
        frappe.throw(
            "Payment request is required."
        )

    amount = float(amount or 0)

    if amount <= 0:
        frappe.throw(
            "Payment amount must be greater than zero."
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
            (
                "Bank Payment Request "
                f"{payment_request} not found."
            )
        )

    doc = frappe.get_doc(
        "Bank Payment Request",
        doc_name
    )

    if doc.otp_status != "Verified":

        frappe.throw(
            "OTP must be verified before payment submission."
        )

    if doc.payment_submitted:

        return {
            "success": True,

            "request_id":
                doc.request_id,

            "payment_status":
                doc.payment_status,

            "bank_payment_status":
                doc.payment_status,

            "transaction_id":
                doc.bank_transaction_id,

            "response_code":
                doc.bank_response_code,

            "response_message":
                doc.bank_response_message,

            "amount":
                doc.amount,

            "currency":
                doc.currency,

            "mode_of_payment":
                doc.mode_of_payment,

            "otp_verified_at":
                doc.otp_verified_at
        }

    doc.amount = amount

    doc.payment_status = "Pending"

    doc.payment_submitted = 1

    doc.payment_submitted_at = (
        now_datetime()
    )

    doc.save(
        ignore_permissions=True
    )

    return {

        "success":
            True,

        "request_id":
            doc.request_id,

        "payment_status":
            "Pending",

        "bank_payment_status":
            "Pending",

        "transaction_id":
            None,

        "response_code":
            "PAYMENT_ACCEPTED",

        "response_message":
            "Payment request accepted and queued for processing.",

        "amount":
            doc.amount,

        "currency":
            doc.currency,

        "mode_of_payment":
            doc.mode_of_payment,

        "otp_verified_at":
            doc.otp_verified_at
    }


@frappe.whitelist()
def get_payment_status(payment_request):

    if not payment_request:
        frappe.throw(
            "Payment request is required."
        )

    doc_name = frappe.db.get_value(
        "Bank Payment Request",
        {
            "request_id": payment_request
        },
        "name"
    )

    if not doc_name:

        return {
            "success": False,
            "payment_status": "NOT_FOUND",
            "transaction_id": None,
            "response_code": "NOT_FOUND",
            "response_message": (
                "Payment request not found."
            )
        }

    doc = frappe.get_doc(
        "Bank Payment Request",
        doc_name
    )

    if not doc.payment_submitted:

        return {
            "success": False,
            "payment_status": doc.payment_status,
            "transaction_id": doc.bank_transaction_id,
            "response_code": "NOT_SUBMITTED",
            "response_message": (
                "Payment has not been submitted."
            )
        }

    response = call_mock_bank_status_api(
        doc
    )

    if not response:

        return {
            "success": False,
            "payment_status": "ERROR",
            "transaction_id": None,
            "response_code": "NO_RESPONSE",
            "response_message": (
                "No response from Mock Bank."
            )
        }

    bank_status = response.get(
        "payment_status"
    )

    if bank_status:
        doc.payment_status = normalize_payment_status(
            bank_status
        )

    transaction_id = response.get(
        "transaction_id"
    )

    if transaction_id:
        doc.bank_transaction_id = transaction_id

    if response.get("response_code"):
        doc.bank_response_code = response.get(
            "response_code"
        )

    if response.get("response_message"):
        doc.bank_response_message = response.get(
            "response_message"
        )

    if response.get("processed_at"):
        doc.processed_at = response.get(
            "processed_at"
        )

    doc.last_status_checked_at = now_datetime()

    doc.save(
        ignore_permissions=True
    )

    frappe.db.commit()

    return {
        "success": True,

        "request_id":
            response.get(
                "request_id",
                doc.request_id
            ),

        "payment_status":
            bank_status,

        "transaction_id":
            transaction_id,

        "response_code":
            response.get(
                "response_code"
            ),

        "response_message":
            response.get(
                "response_message"
            ),

        "mode_of_payment":
            response.get(
                "mode_of_payment",
                doc.mode_of_payment
            ),

        "amount":
            response.get(
                "amount",
                doc.amount
            ),

        "currency":
            response.get(
                "currency",
                doc.currency
            ),

        "processed_at":
            response.get(
                "processed_at"
            ),

        "response_timestamp":
            response.get(
                "response_timestamp"
            ),

        "otp_verified_at":
            doc.otp_verified_at
    }


def initiate_bank_payment(doc):

    if not doc.source_account:
        frappe.throw("Source account is required.")

    bank_account = frappe.db.get_value(
        "Bank Integration Account",
        {
            "account_number": doc.source_account
        },
        [
            "name",
            "account_number",
            "currency",
            "payment_initiation_url"
        ],
        as_dict=True
    )

    if not bank_account:
        frappe.throw(
            f"No Bank Integration Account found for "
            f"source account {doc.source_account}."
        )

    api_key = get_decrypted_password(
    "Bank Integration Account",
    bank_account.name,
    "api_key")

    api_secret = get_decrypted_password(
    "Bank Integration Account",
    bank_account.name,
    "api_secret")


    headers = {
    "Authorization": f"token {api_key}:{api_secret}"
}


    if (
        bank_account.currency
        and bank_account.currency != doc.currency
    ):
        frappe.throw(
            "Bank account currency does not match payment currency."
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

    try:

        response = requests.post(
            bank_account.payment_initiation_url,
            json=payload,
            headers=headers,
            timeout=180
        )

    except requests.Timeout:

        frappe.log_error(
            title="Mock Bank Initiation Timeout",
            message=frappe.get_traceback()
        )

        return {
            "success": False,
            "request_id": doc.request_id,
            "response_code": "TIMEOUT",
            "response_message": (
                "Mock Bank did not respond within the allowed time."
            ),
            "payment_status": "Pending",
            "transaction_id": None
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
            "payment_status": "Pending",
            "transaction_id": None
        }

    try:

        result = response.json()

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
            "payment_status": "Pending",
            "transaction_id": None
        }

    if response.status_code not in (200, 202):

        frappe.log_error(
            title="Mock Bank HTTP Error",
            message=(
                f"HTTP Status: {response.status_code}\n\n"
                f"Response: {frappe.as_json(result)}"
            )
        )

        return {
            "success": False,
            "request_id": result.get(
                "request_id",
                doc.request_id
            ),
            "response_code": result.get(
                "response_code",
                f"HTTP_{response.status_code}"
            ),
            "response_message": result.get(
                "response_message",
                "Mock Bank returned an HTTP error."
            ),
            "payment_status": "Pending",
            "transaction_id": result.get(
                "transaction_id"
            )
        }

    bank_status = result.get(
        "payment_status"
    )

    transaction_id = result.get(
        "transaction_id"
    )

    response_code = result.get(
        "response_code"
    )

    response_message = result.get(
        "response_message"
    )

    if bank_status:
        doc.payment_status = normalize_payment_status(
            bank_status
        )

    if transaction_id:
        doc.bank_transaction_id = transaction_id

    if response_code:
        doc.bank_response_code = response_code

    if response_message:
        doc.bank_response_message = response_message

    if result.get("processed_at"):
        doc.processed_at = result.get(
            "processed_at"
        )

    doc.last_status_checked_at = now_datetime()

    doc.save(
        ignore_permissions=True
    )

    frappe.db.commit()

    return {
        "success": True,

        "request_id":
            result.get(
                "request_id",
                doc.request_id
            ),

        "payment_status":
            bank_status,

        "transaction_id":
            transaction_id,

        "response_code":
            response_code,

        "response_message":
            response_message,

        "amount":
            result.get(
                "amount",
                doc.amount
            ),

        "currency":
            result.get(
                "currency",
                doc.currency
            ),

        "mode_of_payment":
            result.get(
                "mode_of_payment",
                doc.mode_of_payment
            ),

        "processed_at":
            result.get(
                "processed_at"
            ),

        "response_timestamp":
            result.get(
                "response_timestamp"
            )
    }



def normalize_payment_status(status):

    if not status:
        return "Failed"

    normalized_status = (
        str(status)
        .strip()
        .upper()
    )

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


def call_mock_bank_status_api(doc):

    if not doc.source_account:
        return {
            "success": False,
            "payment_status": "ERROR",
            "response_code": "NO_SOURCE_ACCOUNT",
            "response_message": "Source account is missing."
        }

    bank_account = frappe.db.get_value(
        "Bank Integration Account",
        {
            "account_number": doc.source_account
        },
        [
            "name",
            "account_number",
            "currency",
            "payment_status_url"
        ],
        as_dict=True
    )

    if not bank_account:
        return {
            "success": False,
            "payment_status": "ERROR",
            "response_code": "BANK_ACCOUNT_NOT_FOUND",
            "response_message": (
                f"No Bank Integration Account found for "
                f"{doc.source_account}."
            )
        }

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

    headers = {
    "Authorization": f"token {api_key}:{api_secret}"
}

    if not bank_account.payment_status_url:

        return {
            "success": False,
            "payment_status": "ERROR",
            "response_code": "STATUS_URL_NOT_CONFIGURED",
            "response_message": (
                "Payment Status URL is not configured."
            )
        }

    payload = {
        "unique_id": doc.request_id
    }

    try:

        response = requests.post(
            bank_account.payment_status_url,
            headers = headers,
            json=payload,
            timeout=30
        )

    except requests.Timeout:

        frappe.log_error(
            title="Mock Bank Status Timeout",
            message=frappe.get_traceback()
        )

        return {
            "success": False,
            "payment_status": "Pending",
            "response_code": "TIMEOUT",
            "response_message": (
                "Mock Bank status API timed out."
            )
        }

    except requests.RequestException:

        frappe.log_error(
            title="Mock Bank Status Connection Error",
            message=frappe.get_traceback()
        )

        return {
            "success": False,
            "payment_status": "Pending",
            "response_code": "CONNECTION_ERROR",
            "response_message": (
                "Unable to connect to Mock Bank status API."
            )
        }

    try:

        result = response.json()

    except ValueError:

        frappe.log_error(
            title="Invalid Mock Bank Status Response",
            message=response.text
        )

        return {
            "success": False,
            "payment_status": "Pending",
            "response_code": "INVALID_RESPONSE",
            "response_message": (
                "Mock Bank returned invalid status response."
            )
        }

    if response.status_code not in (200, 202):

        return {
            "success": False,
            "payment_status": "Pending",
            "response_code": result.get(
                "response_code",
                f"HTTP_{response.status_code}"
            ),
            "response_message": result.get(
                "response_message",
                "Mock Bank status request failed."
            ),
            "transaction_id": result.get(
                "transaction_id"
            )
        }

    return result