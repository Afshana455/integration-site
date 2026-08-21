import frappe

from bank_integration.api.payment import (initiate_bank_payment)
def process_pending_bank_payments():

    payments = frappe.get_all(
        "Bank Payment Request",
        filters={"payment_submitted": 1,"payment_status": "Pending","bank_initiation_started": 0},
        fields=[ "name", "request_id"],
        limit_page_length=50)

    for payment in payments:

        try:

            doc = frappe.get_doc( "Bank Payment Request", payment.name)
            doc.bank_initiation_started = 1

            doc.save( ignore_permissions=True)

            result = initiate_bank_payment(doc)

            if not result.get("success"):
                doc.reload()
                doc.bank_initiation_started = 0
                doc.save(ignore_permissions=True)

        except Exception:

            frappe.log_error( title="Bank Payment Scheduler Error", message=frappe.get_traceback())

            try:
                doc.reload()
                doc.bank_initiation_started = 0

                doc.save(  ignore_permissions=True)

            except Exception:
                pass