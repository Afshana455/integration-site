import requests
import frappe
from bank_integration.api.otp import generate_payment_otp

@frappe.whitelist()
def create_payment_request(request_id,erp_site,erp_doctype, erp_document_name, amount, currency, source_account, beneficiary_account, mode_of_payment):
    if not request_id:
        frappe.throw("Request ID is required.")

    if not erp_site:
        frappe.throw("ERP site is required.")

    if not erp_doctype:
        frappe.throw("ERP DocType is required.")

    if not erp_document_name:
        frappe.throw("ERP document name is required.")

    if not amount:
        frappe.throw("Payment amount is required.")

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        frappe.throw( "Payment amount must be a valid number.")

    if amount <= 0:
        frappe.throw("Payment amount must be greater than zero." )

    if not currency:
        frappe.throw("Currency is required.")

    if not source_account:
        frappe.throw( "Source bank account is required.")

    if not beneficiary_account:
        frappe.throw( "Beneficiary account is required.")

    if not mode_of_payment:
        frappe.throw( "Mode of payment is required.")

    if frappe.db.exists("Bank Payment Request",{"request_id": request_id}):
        frappe.throw(  f"Payment request {request_id} already exists.")

    payment_request = frappe.get_doc({
        "doctype": "Bank Payment Request",
        "request_id": request_id,
        "erp_site": erp_site,
        "erp_doctype": erp_doctype,
        "erp_document_name": erp_document_name,
        "amount": amount,
        "currency": currency,
        "source_account": source_account,
        "beneficiary_account": beneficiary_account,
        "mode_of_payment": mode_of_payment,
        "otp_status": "Pending",
        "payment_status": "Initiated"
    })

    payment_request.insert(ignore_permissions=True)
    otp_data = generate_payment_otp( payment_request.name)
    return {
        "success": True,
        "request_id": payment_request.request_id,
        "otp": otp_data["otp"],
        "otp_expires_at": otp_data["otp_expires_at"],
        "payment_status": payment_request.payment_status
    }