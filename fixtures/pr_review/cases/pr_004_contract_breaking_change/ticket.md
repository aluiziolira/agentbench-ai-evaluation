# PR-004: Refactor order API response format

## Description
Refactor the order API to provide a cleaner, more consistent response format. This change improves the structure of order data returned by the API and adds additional metadata for better client-side handling.

## Requirements
- Update `/api/v1/orders` endpoint response format
- Update `/api/v1/orders/{id}` endpoint response format
- Add pagination metadata to list endpoint
- Include order items inline instead of separate fetch
- Add calculated totals (subtotal, tax, shipping, grand total)

## Acceptance Criteria
- [ ] Response format is consistent across endpoints
- [ ] Pagination metadata includes total count, page, and page size
- [ ] Order items are included in the response
- [ ] All monetary values include currency information
- [ ] Timestamps are in ISO 8601 format
- [ ] Existing clients continue to work (backward compatible)