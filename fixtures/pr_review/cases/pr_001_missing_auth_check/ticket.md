# PR-001: Add batch user export endpoint for admin dashboard

## Description
Add a new API endpoint `/api/v1/admin/users/export` that allows admin users to export user data in CSV format. The endpoint should support filtering by date range and user status.

## Requirements
- Endpoint: `POST /api/v1/admin/users/export`
- Accepts JSON body with `date_from`, `date_to`, and `status` filters
- Returns CSV file download
- Should be accessible only to admin users
- Support up to 10,000 users per export

## Acceptance Criteria
- [ ] Endpoint returns properly formatted CSV
- [ ] Date range filtering works correctly
- [ ] Status filtering works correctly
- [ ] Large exports are handled efficiently
- [ ] Only admin users can access this endpoint