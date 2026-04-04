# PR-007: Add webhook endpoint for payment notifications

## Description
Implement a webhook endpoint to receive payment gateway notifications. This endpoint will receive real-time updates about payment status changes (successful payments, refunds, chargebacks) and update our internal order records accordingly.

## Requirements
- Endpoint: `POST /webhooks/payment`
- Accept JSON payload with payment event data
- Verify webhook signature for security
- Update order status based on payment event type
- Return 200 OK for successful processing
- Return appropriate error codes for invalid requests

## Acceptance Criteria
- [ ] Webhook endpoint accepts payment notifications
- [ ] Signature verification prevents spoofed requests
- [ ] Order status is updated correctly for successful payments
- [ ] Order status is updated correctly for refunds
- [ ] Order status is updated correctly for chargebacks
- [ ] Duplicate webhook delivery is handled gracefully
- [ ] Invalid payloads return 400 Bad Request