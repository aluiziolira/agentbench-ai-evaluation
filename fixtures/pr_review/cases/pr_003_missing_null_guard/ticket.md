# PR-003: Add user profile update endpoint

## Description
Implement a new API endpoint to allow users to update their profile information including display name, bio, and social media links.

## Requirements
- Endpoint: `PUT /api/v1/users/profile`
- Accepts JSON body with optional fields: display_name, bio, website, twitter_handle
- Validate input lengths and formats
- Update user record in database
- Return updated profile on success

## Acceptance Criteria
- [ ] Users can update their display name (max 50 chars)
- [ ] Users can update their bio (max 500 chars)
- [ ] Users can add a website URL (must be valid URL format)
- [ ] Users can add a Twitter handle (must be valid format)
- [ ] Partial updates work (only provided fields are updated)
- [ ] Invalid inputs return appropriate error messages